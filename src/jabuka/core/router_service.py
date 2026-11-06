"""Live routing inside the core (ROUT-02/05/06): the race pack, the router worker supervised from
the 1 Hz tick, and the route's advice in every nav message (CONTEXT §Router, §Supervisor, §Tack
advice; RESEARCH Patterns 9 and 11).

- ``tick(nav_msg)`` runs synchronously in the event loop once per nav message and never raises
  out: it gates routing (switch, GPS clock, pack, course, position), fires the reroute triggers,
  schedules one CycleRequest snapshot on the RouterPool (one running + one pending, latest wins)
  and fills ``nav_msg["route"]`` from the RouteFollower of the adopted route.
- The worker (``route.cycle.run_cycle`` in a forkserver process at nice +10, 60 s timeout, killed
  and recreated when stuck or crashed) never blocks the loop. The last good route is kept with
  its growing age.
- Every time comes from the injected clock: UTC epoch seconds from ``clock.now_utc()`` (GPS
  disciplined on the Pi) for routing, ``clock.monotonic()`` for state rows.

Units in the route block: degrees TRUE, knots, nm, seconds; unknown values are null, never NaN.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jabuka.common.clock import Clock
from jabuka.core.state import StateStore
from jabuka.nav.polar import polar_to_json
from jabuka.route import cycle
from jabuka.route.advice import Follow, RouteFollower, Trigger, TriggerInputs, Triggers
from jabuka.route.fields import Fields, fields_from_pack
from jabuka.route.frame import DEFAULT_FRAME
from jabuka.route.polar_grid import normalize_curves
from jabuka.route.pool import PoolOutcome, RouterPool
from jabuka.route.racepack import RacePack, load_pack
from jabuka.route.types import (
    LEVELS,
    CourseMark,
    CycleRequest,
    CycleResult,
    PathPoint,
    RouteRequest,
    RouteResult,
    TackPoint,
)

log = logging.getLogger("jabuka.router")

ROUTE_MSG_VERSION = 1
POOL_TIMEOUT_S = 60.0
POOL_NICE = 10
MAX_ROUTE_POINTS = 300
RETRY_NO_ROUTE_S = 60.0  # no route yet and the last request failed: retry after this
PRIMARY_TWA_UP_DEG = 70.0  # |target TWA| below: steer the TWA (upwind)
PRIMARY_TWA_DOWN_DEG = 110.0  # above: steer the TWA (downwind); between: the heading

REASON_DISABLED = "routage désactivé (Réglages)"
REASON_CLOCK = "heure GPS non valide"
REASON_NO_COURSE = "plus de marque à rejoindre"
REASON_NO_POSITION = "pas de position GPS"
REASON_NOT_LOADED = "pack de course non chargé"


def iso_utc(t: float | None) -> str | None:
    """UTC epoch seconds -> "2026-11-13T18:00:00Z" (None stays None)."""
    if t is None or not math.isfinite(t):
        return None
    return datetime.fromtimestamp(round(t), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(x: Any, nd: int) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _wrap180(a: float) -> float:
    r = math.fmod(a, 360.0)
    if r <= -180.0:
        r += 360.0
    elif r > 180.0:
        r -= 360.0
    return r


def _tack_name(tack: int | None) -> str | None:
    if tack is None or tack == 0:
        return None
    return "stbd" if tack > 0 else "port"


@dataclasses.dataclass
class Adopted:
    """The route shown to the helm (the last good one), as persisted."""

    version: int
    kind: str  # optimal | stay
    t0: float  # UTC s of the snapshot it was computed from
    adopted_t: float  # UTC s
    level: str
    eta: float | None
    legs: tuple[tuple[str, float], ...]  # (mark_id, eta)
    path: tuple[PathPoint, ...]
    tacks: tuple[TackPoint, ...]
    horizon_hold: bool = False
    start_in_margin: bool = False
    force_released_at: float | None = None
    course_version: int = 0


class RouterService:
    def __init__(
        self,
        state: StateStore,
        clock: Clock,
        nav: Any,
        hub: Any,
        data_dir: str | Path,
        racepack_dir: str | Path | None,
        *,
        pool_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.state = state
        self.clock = clock
        self.nav = nav
        self.hub = hub
        self.data_dir = Path(data_dir)
        self.racepack_dir = Path(racepack_dir) if racepack_dir is not None else None
        self.pool_factory = pool_factory
        self.pool: Any | None = None
        # race pack
        self.pack: RacePack | None = None
        self.pack_ok = False
        self.pack_reason: str | None = REASON_NOT_LOADED
        self.pack_version = 0
        self.fields: Fields | None = None
        # routing state
        self.version = 0
        self.route: Adopted | None = None
        self.follower: RouteFollower | None = None
        self.triggers = Triggers(LEVELS["L0"].cadence_s)
        self.errors = 0
        self._req_n = 0
        self._inflight = 0
        self._last_req_t: float | None = None
        self._last_fail: str | None = None
        self._force: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task] = set()
        self._curves_key: int | None = None
        self._curves: Any = None
        self._counts = {
            "jobs_submitted": 0,
            "adopted": 0,
            "kept": 0,
            "invalid": 0,
            "failed": 0,
            "superseded": 0,
        }
        self.last_block: dict | None = None

    # -- lifecycle ---------------------------------------------------------------------------
    def load_pack(self) -> None:
        """(Re)load the race pack: routing needs a valid wind and a land mask."""
        self.pack_version += 1
        self.fields = None
        if self.racepack_dir is None:
            self.pack, self.pack_ok, self.pack_reason = None, False, "pas de dossier de pack"
            return
        pack = load_pack(self.racepack_dir)
        self.pack = pack
        reasons = []
        if pack.wind is None:
            reasons.append("; ".join(e for e in pack.errors if "wind" in e) or "vent absent")
        if pack.landmask_path is None:
            reasons.append(f"landmask.npz absent du pack {self.racepack_dir}")
        if pack.wind is not None:
            try:
                self.fields = fields_from_pack(pack, DEFAULT_FRAME)
            except ValueError as exc:
                reasons.append(str(exc))
        self.pack_ok = not reasons
        self.pack_reason = "; ".join(reasons) if reasons else None

    def _make_pool(self) -> Any:
        if self.pool_factory is not None:
            return self.pool_factory()
        return RouterPool(
            cycle.init_worker,
            (str(self.racepack_dir),),
            timeout_s=POOL_TIMEOUT_S,
            nice=POOL_NICE,
        )

    async def startup(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            self.load_pack()
        except Exception:  # noqa: BLE001 - a broken pack never stops the core
            log.exception("race pack load failed")
            self.pack_ok, self.pack_reason = False, "pack illisible"
        if self.pack_ok and self.pool is None:
            self.pool = self._make_pool()
            self.pool.start()
        self.record_health()

    async def shutdown(self) -> None:
        pool, self.pool = self.pool, None
        if pool is not None:
            try:
                pool.close()
            except Exception:  # noqa: BLE001
                log.exception("router pool close failed")
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    def busy(self) -> bool:
        return self._inflight > 0

    def force(self, reason: str = "manuel") -> None:
        """Ask for a forced reroute at the next tick (the result replaces the current route)."""
        self._force = reason

    # -- clock -------------------------------------------------------------------------------
    def now(self) -> float | None:
        """UTC epoch seconds when the routing gate is ok, else None."""
        try:
            if self.clock.status().get("routing_time_gate") != "ok":
                return None
            dt = self.clock.now_utc()
        except Exception:  # noqa: BLE001
            return None
        return dt.timestamp() if dt is not None else None

    # -- tick --------------------------------------------------------------------------------
    def tick(self, nav_msg: dict) -> None:
        """Fill nav_msg["route"] (never raises out; failures give state "failed")."""
        try:
            self._tick(nav_msg)
        except Exception:
            self.errors += 1
            log.exception("router tick failed")
            nav_msg["route"] = self.failed_block("erreur du routeur")

    def _tick(self, msg: dict) -> None:
        now = self.now()
        block = self._block()
        msg["route"] = block
        boat = msg.get("boat") or {}
        lat, lon = boat.get("lat"), boat.get("lon")
        if now is None:
            self._set_state(block, "blocked_clock", REASON_CLOCK)
        elif not self.pack_ok:
            self._set_state(block, "no_pack", self.pack_reason or REASON_NOT_LOADED)
        elif not self._remaining_marks():
            self._set_state(block, "no_course", REASON_NO_COURSE)
        elif lat is None or lon is None:
            self._set_state(block, "no_position", REASON_NO_POSITION)
        else:
            self._maybe_request(now, msg)
            self._fill_advice(block, now, msg)
        self._write_back(block)
        self.record_health()
        self.last_block = block

    # -- requests ----------------------------------------------------------------------------
    def _remaining_marks(self) -> list[CourseMark]:
        course = self.nav.course
        c = course.course
        if c.finished or not 1 <= c.active_idx < len(c.seq):
            return []
        out = []
        for leg in c.seq[c.active_idx : course.last_idx + 1]:
            m = c.marks.get(leg.mark_id)
            if m is None:
                continue
            out.append(CourseMark(m.id, m.name, m.lat, m.lon, leg.side, float(leg.radius_nm)))
        return out

    def _prev_mark(self) -> CourseMark | None:
        c = self.nav.course.course
        i = c.active_idx - 1
        if not 0 <= i < len(c.seq):
            return None
        leg = c.seq[i]
        m = c.marks.get(leg.mark_id)
        if m is None:
            return None
        return CourseMark(m.id, m.name, m.lat, m.lon, leg.side, float(leg.radius_nm))

    def _polar_curves(self) -> Any:
        polar = self.nav.polar
        if self._curves_key != id(polar):
            # the Phase 2 polar carries TWA 0 points; the router grid adds its own 0 knot
            curves = [
                (tws, [(a, b) for a, b in pts if 0.0 < a <= 180.0])
                for tws, pts in polar_to_json(polar)["curves"]
            ]
            self._curves = normalize_curves([c for c in curves if c[1]])
            self._curves_key = id(polar)
        return self._curves

    def _tack0(self, msg: dict) -> int:
        twa = (msg.get("wind") or {}).get("twa")
        if twa is None or abs(twa) < 1e-9:
            return 0
        return 1 if twa > 0 else -1

    def _router_settings(self) -> Any:
        return LEVELS["L0"]

    def _trigger_inputs(self, now: float, msg: dict) -> TriggerInputs:
        return TriggerInputs(
            course_version=self.nav.course.version,
            pack_version=self.pack_version,
            has_route=self.route is not None,
        )

    def _maybe_request(self, now: float, msg: dict) -> None:
        rs = self._router_settings()
        self.triggers.cadence_s = rs.cadence_s
        inputs = self._trigger_inputs(now, msg)
        trigs = self.triggers.check(now, inputs)
        if self._force is not None:
            trigs.append(Trigger(self._force, True))
        if (
            not trigs
            and self.route is None
            and self._inflight == 0
            and self._last_req_t is not None
            and now - self._last_req_t >= RETRY_NO_ROUTE_S
        ):
            trigs.append(Trigger("retry", False))
        if not trigs or self.pool is None:
            return
        req = self._build_request(now, msg, rs)
        if req is None:
            return
        self.triggers.mark_requested(now, inputs)
        self._force = None
        self._last_req_t = now
        forced = any(t.forced for t in trigs)
        self._submit(req, forced, tuple(t.reason for t in trigs))

    def _build_request(self, now: float, msg: dict, rs: Any) -> CycleRequest | None:
        boat = msg.get("boat") or {}
        marks = self._remaining_marks()
        if not marks:
            return None
        s = self.nav.settings
        self._req_n += 1
        base = RouteRequest(
            request_id=f"r{self._req_n}",
            t0=float(now),
            lat=float(boat["lat"]),
            lon=float(boat["lon"]),
            tack0=self._tack0(msg),
            prev_mark=self._prev_mark(),
            marks=tuple(marks),
            polar_curves=self._polar_curves(),
            eff=float(s.efficiency),
            eff_up=s.efficiency_up,
            eff_down=s.efficiency_down,
            bias=None,
            settings=rs,
        )
        old = self.route.path if self.route is not None else None
        return CycleRequest(base=base, want_forced=True, stay_active=False, old_path=old)

    # -- worker ------------------------------------------------------------------------------
    def _submit(self, req: CycleRequest, forced: bool, reasons: tuple[str, ...]) -> None:
        self._counts["jobs_submitted"] += 1
        self._spawn(lambda: self._run(req, forced, reasons, self.nav.course.version))

    def _spawn(self, make: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Start a task on the core loop (from the loop thread, or from another thread)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None and (self._loop is None or running is self._loop):
            self._start_task(make)
        elif self._loop is not None and self._loop.is_running():
            self._inflight += 1  # counted now so busy() is right before the loop runs it
            self._loop.call_soon_threadsafe(self._start_task, make, True)

    def _start_task(self, make: Callable[[], Coroutine[Any, Any, None]], counted=False) -> None:
        if not counted:
            self._inflight += 1
        task = asyncio.get_running_loop().create_task(make())
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        self._inflight = max(0, self._inflight - 1)

    async def _run(
        self, req: CycleRequest, forced: bool, reasons: tuple[str, ...], course_version: int
    ) -> None:
        pool = self.pool
        if pool is None:
            return
        try:
            out: PoolOutcome = await pool.run_latest(cycle.run_cycle, req)
        except RuntimeError:  # pool closed
            return
        try:
            self._on_outcome(req, out, forced, reasons, course_version)
        except Exception:
            self.errors += 1
            log.exception("route outcome handling failed")

    def _on_outcome(
        self,
        req: CycleRequest,
        out: PoolOutcome,
        forced: bool,
        reasons: tuple[str, ...],
        course_version: int,
    ) -> None:
        if out.status == "superseded":
            self._counts["superseded"] += 1
            return
        if out.status != "ok" or not isinstance(out.value, CycleResult):
            self._counts["failed"] += 1
            self._last_fail = f"{out.status}: {out.error}" if out.error else out.status
            return
        res: CycleResult = out.value
        opt = res.optimal
        if not opt.ok or not opt.valid or not opt.path:
            self._counts["failed"] += 1
            self._last_fail = opt.reason or "route invalide"
            return
        self._last_fail = None
        self._adopt(req, opt, "optimal", course_version)

    def _adopt(self, req: CycleRequest, shown: RouteResult, kind: str, course_version: int):
        now = self.now()
        self.version += 1
        self._counts["adopted"] += 1
        self.route = Adopted(
            version=self.version,
            kind=kind,
            t0=float(req.base.t0),
            adopted_t=float(now if now is not None else req.base.t0),
            level=shown.level,
            eta=shown.eta,
            legs=tuple((lg.mark_id, float(lg.eta)) for lg in shown.legs),
            path=tuple(shown.path),
            tacks=tuple(shown.tacks),
            horizon_hold=bool(shown.horizon_hold),
            start_in_margin=bool(shown.start_in_margin),
            force_released_at=shown.force_released_at,
            course_version=course_version,
        )
        self.follower = RouteFollower(self.route.path, self.route.tacks)
        text = self.route_text()
        if text is not None:
            self.hub.publish(text)

    # -- advice ------------------------------------------------------------------------------
    def _follow(self, now: float, msg: dict) -> Follow | None:
        if self.follower is None:
            return None
        boat = msg.get("boat") or {}
        wind = msg.get("wind") or {}
        return self.follower.follow(
            now, float(boat["lat"]), float(boat["lon"]), boat.get("cog_t"), wind.get("twd_t")
        )

    def _fill_advice(self, block: dict, now: float, msg: dict) -> None:
        r = self.route
        if r is None:
            if self._inflight > 0:
                self._set_state(block, "computing", None)
            elif self._last_fail is not None:
                self._set_state(block, "failed", self._last_fail)
            else:
                self._set_state(block, "computing", None)
            return
        self._set_state(block, "ok", None)
        f = self._follow(now, msg)
        block.update(
            version=r.version,
            kind=r.kind,
            age_s=_r(max(0.0, now - r.t0), 0),
            computed_utc=iso_utc(r.t0),
            level=r.level,
            horizon_hold=r.horizon_hold,
            start_in_margin=r.start_in_margin,
        )
        if f is None:
            return
        shift = f.eta_now - (r.eta if r.eta is not None else f.eta_now)
        block["eta_utc"] = iso_utc(f.eta_now)
        block["leg_eta_utc"] = iso_utc(r.legs[0][1] + shift) if r.legs else None
        block["target_twa"] = _r(f.target_twa, 1)
        block["target_tack"] = _tack_name(f.target_tack)
        block["target_hdg_t"] = (
            _r(f.target_hdg_t % 360.0, 1) if f.target_hdg_t is not None else None
        )
        block["xte_nm"] = _r(f.xte_nm, 2)
        twa_abs = abs(f.target_twa)
        wind = msg.get("wind") or {}
        boat = msg.get("boat") or {}
        if twa_abs < PRIMARY_TWA_UP_DEG or twa_abs > PRIMARY_TWA_DOWN_DEG:
            block["primary"] = "twa"
            block["target"] = _r(twa_abs, 1)
            twa_now = wind.get("twa")
            block["deviation"] = _r(abs(twa_now) - twa_abs, 1) if twa_now is not None else None
        else:
            block["primary"] = "hdg"
            block["target"] = block["target_hdg_t"]
            hdg = boat.get("hdg_t")
            if hdg is None:
                hdg = boat.get("cog_t")
            if hdg is not None and f.target_hdg_t is not None:
                block["deviation"] = _r(_wrap180(hdg - f.target_hdg_t), 1)
        block["countdown_s"] = _r(f.countdown_s, 0)
        if f.next_tack is not None:
            block["tack_kind"] = str(f.next_tack[5])
            block["tack_lat"] = _r(f.next_tack[1], 6)
            block["tack_lon"] = _r(f.next_tack[2], 6)

    # -- message pieces ----------------------------------------------------------------------
    def _block(self) -> dict:
        """The route block with every key present (null-safe shape)."""
        return {
            "state": None,
            "reason": None,
            "version": self.version,
            "kind": None,
            "age_s": None,
            "computed_utc": None,
            "level": None,
            "eta_utc": None,
            "leg_eta_utc": None,
            "primary": None,
            "target": None,
            "deviation": None,
            "target_twa": None,
            "target_tack": None,
            "target_hdg_t": None,
            "xte_nm": None,
            "off_route": False,
            "countdown_s": None,
            "tack_kind": None,
            "tack_lat": None,
            "tack_lon": None,
            "missed": False,
            "updating": False,
            "cost_s": None,
            "cost_text": None,
            "stay": {"active": False, "tack": None, "released_land": False, "release_in_s": None},
            "horizon_hold": False,
            "start_in_margin": False,
            "bias": {
                "enabled": True,
                "valid": False,
                "state": None,
                "dir_deg": None,
                "ratio": None,
                "text": None,
            },
            "pack": self._pack_info(),
            "health": self._pool_health(),
        }

    def failed_block(self, reason: str) -> dict:
        try:
            block = self._block()
        except Exception:  # noqa: BLE001 - the fallback must not fail
            block = {"version": self.version}
        block["state"] = "failed"
        block["reason"] = reason
        return block

    @staticmethod
    def _set_state(block: dict, state: str, reason: str | None) -> None:
        block["state"] = state
        block["reason"] = reason

    def _pack_info(self) -> dict:
        meta = (self.pack.meta.get("wind") if self.pack is not None else None) or {}
        return {
            "ok": self.pack_ok,
            "model": meta.get("model") or None,
            "run": meta.get("run") or None,
            "alerts": [],
        }

    def _pool_health(self) -> dict:
        st = dict(self.pool.stats) if self.pool is not None else {}
        return {
            "jobs": int(st.get("jobs", 0)),
            "ok": int(st.get("ok", 0)),
            "timeouts": int(st.get("timeouts", 0)),
            "crashes": int(st.get("crashes", 0)),
            "last_ms": _r(st.get("last_ms"), 0),
            "running": int(st.get("running", 0)),
            "pending": int(st.get("pending", 0)),
        }

    def health(self) -> dict:
        """Health row (src "router") for the Diag page."""
        return {
            "pack_ok": self.pack_ok,
            "pack_reason": self.pack_reason,
            "pack": self._pack_info(),
            "version": self.version,
            "route_age_s": None,
            "last_fail": self._last_fail,
            "errors": self.errors,
            "pool": self._pool_health(),
            **self._counts,
        }

    def record_health(self) -> None:
        try:
            self.state.update_health("router", self.health(), self.clock.monotonic())
        except Exception:  # noqa: BLE001
            log.exception("router health failed")

    def _write_back(self, block: dict) -> None:
        self.state.update_values(
            "nav",
            [{"path": "nav.route.countdown", "value": block.get("countdown_s"), "unit": "s"}],
            self.clock.monotonic(),
        )

    # -- route message -----------------------------------------------------------------------
    def route_message(self) -> dict | None:
        r = self.route
        if r is None:
            return None
        coords = [[round(p.lon, 6), round(p.lat, 6)] for p in r.path[:MAX_ROUTE_POINTS]]
        features: list[dict] = [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"role": "route", "version": r.version, "kind": r.kind},
            }
        ]
        for tk in r.tacks:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(tk.lon, 6), round(tk.lat, 6)],
                    },
                    "properties": {
                        "role": "tack",
                        "t_utc": iso_utc(tk.t),
                        "kind": tk.kind,
                        "to_tack": _tack_name(tk.to_tack),
                    },
                }
            )
        nxt = next((tk for tk in r.tacks if tk.t > r.adopted_t), None)
        if nxt is not None:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(nxt.lon, 6), round(nxt.lat, 6)],
                    },
                    "properties": {
                        "role": "next_tack",
                        "t_utc": iso_utc(nxt.t),
                        "kind": nxt.kind,
                        "to_tack": _tack_name(nxt.to_tack),
                    },
                }
            )
        return {
            "type": "route",
            "v": ROUTE_MSG_VERSION,
            "version": r.version,
            "kind": r.kind,
            "computed_utc": iso_utc(r.t0),
            "level": r.level,
            "eta_utc": iso_utc(r.eta),
            "legs": [{"mark_id": mid, "eta_utc": iso_utc(eta)} for mid, eta in r.legs],
            "geojson": {"type": "FeatureCollection", "features": features},
        }

    def route_text(self) -> str | None:
        msg = self.route_message()
        if msg is None:
            return None
        try:
            return json.dumps(msg, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            log.exception("route message not serializable")
            return None

    def status_reason(self) -> dict:
        """{"state", "reason"} for GET /api/route when there is no route."""
        b = self.last_block or {}
        return {"state": b.get("state") or "no_route", "reason": b.get("reason")}
