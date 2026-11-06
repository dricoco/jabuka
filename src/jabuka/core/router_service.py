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
from collections import deque
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jabuka.common.atomicio import atomic_write_json, load_json_with_bak
from jabuka.common.clock import Clock
from jabuka.common.units import kn_to_ms
from jabuka.core.state import StateStore
from jabuka.nav.polar import polar_to_json
from jabuka.route import cycle
from jabuka.route.advice import (
    ROUTE_MAX_AGE_S,
    Follow,
    MissedTackWatch,
    OffRouteWatch,
    RouteFollower,
    StayOnTack,
    TackDetector,
    Trigger,
    TriggerInputs,
    Triggers,
    cost_text,
    should_replace,
)
from jabuka.route.bias import BiasEstimator, BiasParams, BiasSample
from jabuka.route.fields import Fields, fields_from_pack
from jabuka.route.frame import DEFAULT_FRAME
from jabuka.route.polar_grid import normalize_curves
from jabuka.route.pool import PoolOutcome, RouterPool
from jabuka.route.racepack import (
    RacePack,
    coverage,
    load_pack,
    pack_fingerprint,
    window_from_local,
)
from jabuka.route.types import (
    FAIL_LAND,
    FAIL_PACK,
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
POOL_STUCK_S = 2.0 * POOL_TIMEOUT_S  # one job "running" longer than this: the pool is wedged
POOL_RETRY_S = 30.0  # no pool (creation failed): try again after this
MAX_ROUTE_POINTS = 300
RETRY_NO_ROUTE_S = 60.0  # no route yet and the last request failed: retry after this
# Route expiry (03-REVIEW CR-02): a displayed route goes stale, then is withdrawn ("outdated":
# no target, no countdown, so the helm falls back to the Phase 2 laylines).
ROUTE_STALE_S = 2.0 * ROUTE_MAX_AGE_S  # not confirmed by any routing cycle this long: withdrawn
FAIL_WITHDRAW_N = 2  # this many consecutive failed cycles ...
ROUTE_FAIL_AGE_S = 600.0  # ... and the route unconfirmed this long: withdrawn
MISSED_MAX_S = 180.0  # "Route mise à jour…" (missed-tack reroute) at most this long
ROUNDING_TOL_S = 600.0  # course advanced by a rounding: the boat is this close to the leg's end
PRIMARY_TWA_UP_DEG = 70.0  # |target TWA| below: steer the TWA (upwind)
PRIMARY_TWA_DOWN_DEG = 110.0  # above: steer the TWA (downwind); between: the heading
WRONG_TACK_MIN_DEG = 15.0  # |TWA| below: head to wind / mid-tack, the side is not meaningful

REASON_DISABLED = "routage désactivé (Réglages)"
REASON_CLOCK = "heure GPS non valide"
REASON_NO_COURSE = "plus de marque à rejoindre"
REASON_NO_POSITION = "pas de position GPS"
REASON_NOT_LOADED = "pack de course non chargé"
REASON_STAY_NO_TACK = "amure inconnue : On reste impossible"
REASON_OUT_COURSE = "parcours modifié : recalcul en cours"
REASON_OUT_MISSED = "virement manqué : nouvelle route impossible"
REASON_OUT_AGE = "route périmée"
REASON_OUT_FAIL = "le routeur échoue"
REASON_OUT_RESTORED = "route sauvegardée : vérification en cours"

ROUTE_FILE = "route.json"
BIAS_FILE = "bias.json"
BIAS_SAVE_S = 60.0  # bias.json at most this often (and on every manual entry, at shutdown)
_UNSET = object()  # sentinel: nothing observed yet
ROUTE_FILE_VERSION = 1
INVALID_ALERT_S = 300.0  # "ROUTE INVALIDE" stays in the alerts this long
ALERT_INVALID = "ROUTE INVALIDE : "
ALERT_RESTORE = "Route sauvegardée illisible : ignorée"
ALERT_POOL = "ROUTEUR RELANCÉ : "
ALERT_PACK_CHANGED = "PACK DE COURSE MODIFIÉ : redémarrer jabuka-core"
PACK_CHECK_S = 60.0  # the pack's sidecars are re-read this often (MD-05)
POOL_ALERT_S = 300.0  # the router-restart alert stays this long


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


def display_points(path: Any, limit: int) -> list:
    """At most ``limit`` points of ``path`` for the map line, always ending at the finish
    (03-REVIEW LO-02: truncating to the first ``limit`` points cut the line short). The ends
    and the tack/gybe vertices are kept first, the other points evenly spaced."""
    n = len(path)
    if n <= limit:
        return list(path)
    limit = max(2, limit)

    def even(idx: list[int], k: int) -> list[int]:
        if k <= 0 or not idx:
            return []
        if k >= len(idx):
            return idx
        return [idx[round(j * (len(idx) - 1) / max(1, k - 1))] for j in range(k)]

    vertices = [i for i in range(1, n - 1) if int(path[i][4]) != int(path[i - 1][4])]
    if len(vertices) + 2 > limit:
        keep = {0, n - 1, *even(vertices, limit - 2)}
    else:
        others = [i for i in range(1, n - 1) if i not in set(vertices)]
        keep = {0, n - 1, *vertices, *even(others, limit - 2 - len(vertices))}
    return [path[i] for i in sorted(keep)]


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
    # the marks it was computed for: (mark_id, lat, lon, side, radius_nm), see _course_changed
    marks: tuple[tuple[str, float, float, str, float], ...] = ()


def _mark_key(m: CourseMark) -> tuple[str, float, float, str, float]:
    return (m.mark_id, round(m.lat, 6), round(m.lon, 6), m.side, round(float(m.radius_nm), 4))


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
        self.pack_fp: tuple | None = None  # fingerprint of the loaded pack (MD-05)
        self._pack_changed = False
        self._pack_check_mono: float | None = None
        self._restored_unverified = False  # a route.json route not yet re-checked by a cycle
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
        self._soft: str | None = None
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
            "pool_recycled": 0,
        }
        # pool watchdog (03-REVIEW CR-01): never let routing stop silently
        self._pool_wanted = False  # startup created a pool: keep one alive
        self._pool_watch: tuple[Any, float] | None = None  # (running job key, since t_mono)
        self._pool_faults_seen = 0
        self._pool_alert: tuple[str, float] | None = None  # (text, until t_mono)
        self._pool_retry_mono: float | None = None
        self.last_block: dict | None = None
        self._missed_edge = False
        # tack advice (ROUT-06..10)
        self.detector = TackDetector()
        self.offroute = OffRouteWatch()
        self.missed_watch = MissedTackWatch()
        self.stay = StayOnTack()
        self.missed = False  # a missed tack asked for a reroute: "Route mise à jour…"
        self._last_follow: Follow | None = None  # the previous tick's projection
        self._missed_t: float | None = None  # UTC s when the missed tack was flagged
        self._missed_req: str | None = None  # request id of the reroute it asked for
        self._missed_failed = False  # ... and that reroute failed
        self._fail_streak = 0  # consecutive failed routing cycles
        self._route_conf_t: float | None = None  # UTC t0 of the last cycle confirming the route
        self.withdrawn: str | None = None  # why the displayed route is withdrawn (CR-02)
        self.cost_s: float | None = None
        self._cycle_n = 0
        self._force_carry = False
        self._manual_key: Any = _UNSET
        self.manual_version = 0
        self.request_log: deque[tuple[float, tuple[str, ...]]] = deque(maxlen=200)
        self.last_request: CycleRequest | None = None
        # alerts and coverage (GRIB-02)
        self._invalid_alert: tuple[str, float] | None = None  # (text, until t_mono)
        self._restore_alert = False
        self.coverage_alerts: list[str] = []
        self.coverage_warnings: list[str] = []
        self._coverage_key: Any = None
        self.coverage_runs = 0
        self.route_file = self.data_dir / ROUTE_FILE
        # GRIB bias (WIND-06)
        self.bias_file = self.data_dir / BIAS_FILE
        self.bias = BiasEstimator()
        self._bias_prev_t: float | None = None
        self._bias_saved_mono: float | None = None
        self._bias_dirty = False

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
        self.pack_fp = pack.fingerprint
        self._pack_changed = False
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
        self.run_coverage()
        self.restore()
        self.restore_bias()
        if self.pack_ok and self.pool is None:
            self._pool_wanted = True
            self.pool = self._make_pool()
            self.pool.start()
        self.record_health()

    async def shutdown(self) -> None:
        self.save_bias()
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

    def request(self, reason: str = "manuel", forced: bool = True) -> None:
        """Ask for a reroute at the next tick; a non-forced one goes through the hysteresis."""
        if forced:
            self._force = reason
        else:
            self._soft = reason

    def set_stay(self, active: bool, msg: dict | None = None) -> str | None:
        """ "On reste" on/off. Returns a French error when the current tack is unknown."""
        if not active:
            self.stay.cancel()
            return None
        tack = self._tack0(msg or self.nav.last or {})
        if tack == 0:
            return REASON_STAY_NO_TACK
        if not (self.stay.active and self.stay.tack == tack):
            self.stay.activate(self.now() or 0.0, tack)
        return None

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
        s = self.nav.settings
        self._watch_pool()
        self._watch_pack()
        self._observe(now, msg)
        block = self._block()
        msg["route"] = block
        boat = msg.get("boat") or {}
        lat, lon = boat.get("lat"), boat.get("lon")
        if not s.routing_enabled:
            self._set_state(block, "disabled", REASON_DISABLED)
        elif now is None:
            self._set_state(block, "blocked_clock", REASON_CLOCK)
        elif not self.pack_ok:
            self._set_state(block, "no_pack", self.pack_reason or REASON_NOT_LOADED)
        elif not self._remaining_marks():
            self._set_state(block, "no_course", REASON_NO_COURSE)
        elif lat is None or lon is None:
            self._set_state(block, "no_position", REASON_NO_POSITION)
        else:
            f = self._follow(now, msg)
            self._last_follow = f
            sog = (msg.get("boat") or {}).get("sog_kn")
            off = self.offroute.update(now, f, sog) if f is not None else False
            if f is not None and self.missed_watch.update(
                now, f.countdown_s, self.detector.last_tack_t
            ):
                self.missed = True
                self._missed_edge = True
                self._missed_t = now
                self._missed_failed = False
            self.withdrawn = self._withdrawal(now, f)
            self._maybe_request(now, msg, off)
            self._missed_edge = False
            block["off_route"] = bool(off)
            self._fill_advice(block, now, msg, f)
        self._fill_common(block, now)
        block["bias"] = self.bias_block(now)
        self._alerts(msg)
        self._write_back(block)
        self.record_health()
        self.last_block = block

    def _observe(self, now: float | None, msg: dict) -> None:
        """Per-tick inputs that do not depend on the routing gate: tacks, manual wind, course."""
        if now is not None:
            twa = (msg.get("wind") or {}).get("twa")
            ev = self.detector.update(now, twa)
            if ev is not None and self.stay.active:
                self.stay.on_tack(ev)  # a detected tack ends "On reste" (stay trigger)
            elif ev is not None and self.route is not None:
                f = self._last_follow
                if f is not None and ev.new_side != f.target_tack:
                    # tacked away from the route (e.g. early): it is outdated for this boat
                    # (03-REVIEW MD-02), rerouted with the off-route treatment
                    self.request("tack", forced=False)
        store = self.nav.manual
        entry = getattr(store, "entry", None)
        # LO-01: key on the store's set/clear counter and the entry object, never on
        # t_set_wall (None for every entry made without trusted GPS time)
        key = (getattr(store, "version", None), id(entry) if entry is not None else None)
        if key != self._manual_key:
            if self._manual_key is _UNSET:
                pass  # first tick: an entry restored from disk is not a new observation
            else:
                self.manual_version += 1
                if entry is not None:
                    self._observe_manual(now, msg, entry)
            self._manual_key = key
        self._observe_bias(now, msg)
        cov_key = (self.nav.course.version, self.pack_version, self._window_key())
        if cov_key != self._coverage_key:
            self.run_coverage()

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
        """The boat's tack: the confirmed detector side, else the sign of the nav TWA."""
        if self.detector.side:
            return int(self.detector.side)
        twa = (msg.get("wind") or {}).get("twa")
        if twa is None or abs(twa) < 1e-9:
            return 0
        return 1 if twa > 0 else -1

    def _router_settings(self) -> Any:
        s = self.nav.settings
        base = LEVELS.get(s.route_level, LEVELS["L0"])
        return dataclasses.replace(
            base,
            tack_penalty_s=float(s.tack_penalty_s),
            stay_extra_s=float(s.stay_extra_min) * 60.0,
            use_waves=bool(s.route_waves),
            use_current=bool(s.route_current),
            cadence_s=max(base.cadence_s, float(s.route_cadence_min) * 60.0),
        )

    def _trigger_inputs(self, now: float, msg: dict, off_route: bool = False) -> TriggerInputs:
        return TriggerInputs(
            course_version=self.nav.course.version,
            bias_eff=self._bias_eff(now),
            manual_version=self.manual_version,
            off_route=bool(off_route),
            stay_version=self.stay.version,
            missed=self._missed_edge,
            pack_version=self.pack_version,
            has_route=self.route is not None,
        )

    def _bias_eff(self, now: float) -> tuple[float, float] | None:
        p = self._bias_params(now)
        return p.effective(now) if p is not None else None

    def _maybe_request(self, now: float, msg: dict, off_route: bool = False) -> None:
        rs = self._router_settings()
        self.triggers.cadence_s = rs.cadence_s
        inputs = self._trigger_inputs(now, msg, off_route)
        trigs = self.triggers.check(now, inputs)
        if self._force is not None:
            trigs.append(Trigger(self._force, True))
        if self._soft is not None:
            trigs.append(Trigger(self._soft, False))
        if (
            not trigs
            and (self.route is None or self._fail_streak > 0 or self.withdrawn is not None)
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
        self._force = self._soft = None
        self._last_req_t = now
        forced = any(t.forced for t in trigs)
        reasons = tuple(t.reason for t in trigs)
        self.request_log.append((now, reasons))
        self.last_request = req
        if self.missed:  # this request (or a newer one) is the missed-tack reroute
            self._missed_req = req.base.request_id
        self._submit(req, forced, reasons)

    def _build_request(self, now: float, msg: dict, rs: Any) -> CycleRequest | None:
        boat = msg.get("boat") or {}
        marks = self._remaining_marks()
        if not marks:
            return None
        s = self.nav.settings
        self._req_n += 1
        self._cycle_n += 1
        stay = self.stay.active and self.stay.tack is not None
        tack0 = int(self.stay.tack) if stay and self.stay.tack else self._tack0(msg)
        n = max(1, int(rs.forced_every_n))
        want_forced = stay or n == 1 or (self._cycle_n % n == 1)
        base = RouteRequest(
            request_id=f"r{self._req_n}",
            t0=float(now),
            lat=float(boat["lat"]),
            lon=float(boat["lon"]),
            tack0=tack0,
            prev_mark=self._prev_mark(),
            marks=tuple(marks),
            polar_curves=self._polar_curves(),
            eff=float(s.efficiency),
            eff_up=s.efficiency_up,
            eff_down=s.efficiency_down,
            bias=self._bias_params(now),
            settings=rs,
        )
        old = self.route.path if self.route is not None else None
        f = self._last_follow
        return CycleRequest(
            base=base,
            want_forced=want_forced,
            stay_active=stay,
            old_path=old,
            old_t_here=f.t_route_here if old is not None and f is not None else None,
            pack_fp=self.pack_fp,
        )

    def _bias_params(self, now: float | None) -> BiasParams | None:
        """Bias applied to the GRIB now (None when switched off or nothing learned)."""
        if now is None or not self.nav.settings.bias_enabled:
            return None
        return self.bias.params(now)

    # -- GRIB wind and bias (WIND-05/06) -----------------------------------------------------
    def _grib_raw(self, now: float, lat: float, lon: float, bias: BiasParams | None):
        """(TWD rad, TWS kn) of the pack wind at (lat, lon, now), None when not covered."""
        f, pack = self.fields, self.pack
        if f is None or pack is None or pack.wind is None:
            return None
        g = pack.wind
        if not (g.lat[0] <= lat <= g.lat[-1] and g.lon[0] <= lon <= g.lon[-1]):
            return None
        twd, tws_kn = f.wind.at(now, lat, lon, bias)
        if not (math.isfinite(twd) and math.isfinite(tws_kn)):
            return None
        return twd, tws_kn

    def grib_wind_at(self, lat: float, lon: float) -> tuple[float, float] | None:
        """GRIB-only wind provider for the nav WindPipeline: (TWD rad TRUE, TWS m/s) at the
        boat and GPS time, bias-corrected (with decay) when the bias is on."""
        now = self.now()
        if now is None or not self.pack_ok:
            return None
        g = self._grib_raw(now, lat, lon, self._bias_params(now))
        if g is None:
            return None
        return g[0], kn_to_ms(g[1])

    def _current_uv(self, now: float, lat: float, lon: float) -> tuple[float, float] | None:
        """Pack current at the boat (water motion TOWARDS, m/s), when the pack has one."""
        f = self.fields
        if f is None or f.current is None:
            return None
        try:
            x, y = DEFAULT_FRAME.to_xy(lat, lon)
            u, v = f.current.uv_kn(now, [x], [y])
            return kn_to_ms(float(u[0])), kn_to_ms(float(v[0]))
        except Exception:  # noqa: BLE001 - no current correction then
            return None

    def _observe_bias(self, now: float | None, msg: dict) -> None:
        """One BiasEstimator sample per tick (the estimator gates it, Pattern 8)."""
        s = self.nav.settings
        self.bias.tau_decay_s = float(s.bias_tau_decay_h) * 3600.0
        if now is None:
            return
        dt = 1.0 if self._bias_prev_t is None else max(0.0, now - self._bias_prev_t)
        self._bias_prev_t = now
        wind = msg.get("wind") or {}
        boat = msg.get("boat") or {}
        lat, lon = boat.get("lat"), boat.get("lon")
        twd, tws = wind.get("twd_t"), wind.get("tws_kn")
        bsp, cog = boat.get("bsp_kn"), boat.get("cog_t")
        grib = None
        if lat is not None and lon is not None and self.pack_ok:
            grib = self._grib_raw(now, lat, lon, None)
        current = self._current_uv(now, lat, lon) if lat is not None and lon is not None else None
        stale = bool(wind.get("stale")) or lat is None or bsp is None or twd is None or tws is None
        sample = BiasSample(
            t=now,
            dt=dt,
            source=str(wind.get("source") or "NONE"),
            stale=stale,
            twd_meas=math.radians(twd) if twd is not None else 0.0,
            tws_meas=kn_to_ms(tws) if tws is not None else 0.0,
            twd_grib=grib[0] if grib is not None else None,
            tws_grib=kn_to_ms(grib[1]) if grib is not None else None,
            bsp=kn_to_ms(bsp) if bsp is not None else 0.0,
            cog=math.radians(cog) if cog is not None else None,
            in_zone=bool(wind.get("in_zone")),
            last_tack_t=self.detector.last_tack_t,
            enabled=bool(s.bias_enabled),
            current_uv=current,
        )
        before = self.bias.status(now)["valid"]
        self.bias.update(sample)
        if self.bias.status(now)["valid"] != before:
            self._bias_dirty = True
        mono = self.clock.monotonic()
        if self._bias_dirty or (
            self._bias_saved_mono is None or mono - self._bias_saved_mono >= BIAS_SAVE_S
        ):
            if self.bias.raw() is not None or self._bias_dirty:
                self.save_bias()
            self._bias_saved_mono = mono

    def _observe_manual(self, now: float | None, msg: dict, entry: Any) -> None:
        """A manual TRUE wind entry is one bias observation against the GRIB at the boat."""
        boat = msg.get("boat") or {}
        lat, lon = boat.get("lat"), boat.get("lon")
        if now is None or lat is None or lon is None or not self.pack_ok:
            return
        g = self._grib_raw(now, lat, lon, None)
        if g is None:
            return
        self.bias.observe_manual(
            now,
            math.radians(float(entry.twd_t_deg)),
            kn_to_ms(float(entry.tws_kn)),
            g[0],
            kn_to_ms(g[1]),
        )
        self._bias_dirty = True

    def bias_block(self, now: float | None) -> dict:
        s = self.nav.settings
        out = {
            "enabled": bool(s.bias_enabled),
            "valid": False,
            "state": None,
            "dir_deg": None,
            "ratio": None,
            "text": None,
            "reason": None,
        }
        if now is None:
            return out
        st = self.bias.status(now)
        out["state"] = st["state"]
        out["reason"] = st["reason"]
        if st["valid"] and st["dir_deg"] is not None and st["ratio"] is not None:
            d, k = float(st["dir_deg"]), float(st["ratio"])
            out.update(valid=True, dir_deg=_r(d, 1), ratio=_r(k, 3))
            out["text"] = f"{round(d):+d}° ×{k:.2f}"
        return out

    def save_bias(self) -> None:
        """Atomic <data-dir>/bias.json (never raises)."""
        try:
            self.bias_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.bias_file, self.bias.to_json())
            self._bias_dirty = False
        except (OSError, TypeError, ValueError):
            log.exception("bias.json write failed")

    def restore_bias(self) -> None:
        raw = load_json_with_bak(self.bias_file, None)
        if raw is None:
            return
        try:
            est = BiasEstimator.from_json(raw)
        except (ValueError, TypeError):
            log.warning("bias.json ignored (invalid)")
            return
        self.bias = est

    # -- worker ------------------------------------------------------------------------------
    def _pool_alarm(self, why: str) -> None:
        """Routing-health alert (5 min) and Diag reason for a pool failure or restart."""
        self._pool_alert = (ALERT_POOL + why, self.clock.monotonic() + POOL_ALERT_S)
        self._last_fail = f"routeur relancé : {why}"
        log.warning("router pool: %s", why)

    def _watch_pack(self) -> None:
        """Every PACK_CHECK_S: the pack on disk must still be the one loaded at startup (the
        worker reloads it on every restart, MD-05)."""
        if self.racepack_dir is None or self.pack_fp is None:
            return
        mono = self.clock.monotonic()
        if self._pack_check_mono is not None and mono - self._pack_check_mono < PACK_CHECK_S:
            return
        self._pack_check_mono = mono
        try:
            fp = pack_fingerprint(self.racepack_dir)
        except Exception:  # noqa: BLE001 - diagnostics only
            return
        if fp != self.pack_fp and not self._pack_changed:
            log.warning("race pack changed on disk since startup: restart needed")
            self._pack_changed = True

    def _watch_pool(self) -> None:
        """1 Hz pool watchdog (03-REVIEW CR-01): alert on pool faults, recycle a pool whose job
        has been running for more than POOL_STUCK_S, recreate a missing pool."""
        mono = self.clock.monotonic()
        pool = self.pool
        if pool is None:
            self._pool_watch = None
            if (
                self._pool_wanted
                and self.pack_ok
                and (self._pool_retry_mono is None or mono - self._pool_retry_mono >= POOL_RETRY_S)
            ):
                self._pool_retry_mono = mono
                self.pool = self._new_pool()
            return
        try:
            st = dict(pool.stats)
        except Exception:  # noqa: BLE001 - a pool that cannot even report is treated as stuck
            st = {"running": 1, "jobs": None}
        faults = int(st.get("faults") or 0)
        if faults > self._pool_faults_seen:
            self._pool_faults_seen = faults
            self._pool_alarm(f"erreur du moteur ({st.get('last_fault') or 'inconnue'})")
        if not int(st.get("running") or 0):
            self._pool_watch = None
            return
        key = st.get("jobs")  # the same job keeps running while the job counter is unchanged
        if self._pool_watch is None or self._pool_watch[0] != key:
            self._pool_watch = (key, mono)
        elif mono - self._pool_watch[1] > POOL_STUCK_S:
            self._recycle_pool(f"calcul bloqué depuis plus de {POOL_STUCK_S:.0f} s")

    def _new_pool(self) -> Any | None:
        try:
            pool = self._make_pool()
            pool.start()
            return pool
        except Exception as exc:  # noqa: BLE001 - retried by the watchdog
            log.exception("router pool creation failed")
            self._pool_alarm(f"création du moteur impossible ({exc!r})")
            return None

    def _recycle_pool(self, why: str) -> None:
        """Replace a wedged pool: close it, cancel the jobs waiting on it, start a fresh one."""
        old = self.pool
        self._counts["pool_recycled"] += 1
        self._pool_watch = None
        self._pool_faults_seen = 0
        self._pool_alarm(why)
        self.pool = None
        new = self._new_pool()
        self.pool = new
        self._pool_retry_mono = self.clock.monotonic()
        if old is not None and old is not new:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                log.exception("router pool close failed")
        for t in list(self._tasks):
            t.cancel()  # their run_latest may never resolve on a wedged pool

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
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - closed pool, or a pool bug: never silent
            if self.pool is not pool:
                return  # closed or replaced meanwhile
            self.errors += 1
            log.exception("router pool job failed")
            out = PoolOutcome("error", None, 0.0, f"pool: {exc!r}")
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
            self._force_carry = self._force_carry or forced  # the newer request inherits it
            return
        if out.status != "ok" or not isinstance(out.value, CycleResult):
            self._counts["failed"] += 1
            self._failed(req, f"{out.status}: {out.error}" if out.error else out.status)
            return
        res: CycleResult = out.value
        opt = res.optimal
        if not opt.ok:
            reason = opt.reason or "échec du routage"
            if opt.fail_kind == FAIL_PACK:
                self._pack_changed = True
            if opt.fail_kind == FAIL_LAND:  # LO-04: the worker's kind, never French words
                self._invalid(reason, req)
            else:
                self._counts["failed"] += 1
                self._failed(req, reason)
            return
        if not opt.valid or not opt.path:
            self._invalid(opt.reason or "route non validée", req)
            return
        if course_version != self.nav.course.version:  # the course changed meanwhile
            self._counts["superseded"] += 1
            return
        self._last_fail = None
        self._fail_streak = 0
        shown, kind = opt, "optimal"
        f = res.forced
        if req.stay_active and self.stay.active:
            if f is not None and f.ok and f.valid and f.path:
                shown, kind = f, "stay"
        forced_eff = forced or self._force_carry
        if self.route is not None and self.route.kind != kind:
            forced_eff = True
        if self.withdrawn is not None:  # the displayed route is withdrawn: anything valid wins
            forced_eff = True
        now = float(req.base.t0)
        replace, why = True, "no_route"
        if self.route is not None:
            age = now - self.route.t0
            if "off_route" in reasons or "tack" in reasons:  # outdated for this boat
                age = max(age, ROUTE_MAX_AGE_S + 1.0)
            replace, why = should_replace(
                float(shown.eta if shown.eta is not None else math.inf),
                now,
                res.eta_old_now,
                res.old_valid is not False,
                age,
                forced_eff,
            )
        if not replace:
            self._counts["kept"] += 1
            if res.old_valid is not False:  # the cycle re-checked the displayed route: still good
                self._route_conf_t = max(self._route_conf_t or 0.0, now)
            return
        self._adopt(req, shown, kind, course_version, res)

    def _failed(self, req: CycleRequest, reason: str) -> None:
        """A routing cycle that produced no usable route (CR-02 bookkeeping)."""
        self._last_fail = reason
        self._fail_streak += 1
        if self.missed and req.base.request_id == self._missed_req:
            self._missed_failed = True  # the missed-tack reroute failed: stop "mise à jour…"

    def _invalid(self, reason: str, req: CycleRequest | None = None) -> None:
        """A worker route that failed validation: discarded, alert for 5 min (ROUT-11)."""
        self._counts["invalid"] += 1
        if req is not None:
            self._failed(req, reason)
        else:
            self._last_fail = reason
        self._invalid_alert = (ALERT_INVALID + reason, self.clock.monotonic() + INVALID_ALERT_S)
        log.warning("worker route discarded: %s", reason)

    # -- route expiry (03-REVIEW CR-02) ------------------------------------------------------
    def _course_changed(self, r: Adopted, f: Follow | None) -> bool:
        """True when the displayed route was computed for other marks than the ones left to
        sail. A course advanced by rounding (the route's first marks dropped while the boat is
        at the end of those legs) keeps the route; a skipped, moved or added mark does not."""
        if r.course_version == self.nav.course.version:
            return False
        if not r.marks:
            return True  # restored from an older route.json: no mark snapshot
        cur = tuple(_mark_key(m) for m in self._remaining_marks())
        n = len(r.marks) - len(cur)
        if n < 0 or r.marks[n:] != cur:
            return True
        if n == 0:
            return False  # same marks: an unrelated course edit
        if n > len(r.legs) or f is None:
            return True
        return f.t_route_here < r.legs[n - 1][1] - ROUNDING_TOL_S

    def _withdrawal(self, now: float, f: Follow | None) -> str | None:
        """Why the displayed route must not be steered any more (None = still good)."""
        r = self.route
        if r is None:
            return None
        if self._restored_unverified:
            return REASON_OUT_RESTORED
        if self._course_changed(r, f):
            return REASON_OUT_COURSE
        if self.missed and (
            self._missed_failed
            or (self._missed_t is not None and now - self._missed_t > MISSED_MAX_S)
        ):
            return REASON_OUT_MISSED + (f" ({self._last_fail})" if self._last_fail else "")
        conf = max(r.t0, self._route_conf_t or r.t0)
        age = now - conf
        if age > ROUTE_STALE_S:
            why = self._last_fail or "recalcul en cours"
            return f"{REASON_OUT_AGE} ({int(age // 60)} min) : {why}"
        if self._fail_streak >= FAIL_WITHDRAW_N and age > ROUTE_FAIL_AGE_S:
            return f"{REASON_OUT_FAIL} : {self._last_fail}"
        return None

    def _adopt(
        self,
        req: CycleRequest,
        shown: RouteResult,
        kind: str,
        course_version: int,
        res: CycleResult | None = None,
    ):
        now = self.now()
        self.version += 1
        self._counts["adopted"] += 1
        self.route = Adopted(
            version=self.version,
            kind=kind,
            t0=float(req.base.t0),
            adopted_t=float(now if now is not None else req.base.t0),
            level=shown.level,
            eta=self._whole_eta(req, shown, kind),
            legs=tuple((lg.mark_id, float(lg.eta)) for lg in shown.legs),
            path=tuple(shown.path),
            tacks=tuple(shown.tacks),
            horizon_hold=bool(shown.horizon_hold),
            start_in_margin=bool(shown.start_in_margin),
            force_released_at=shown.force_released_at,
            course_version=course_version,
            marks=tuple(_mark_key(m) for m in req.base.marks),
        )
        if res is not None and req.want_forced:
            # cost of not tacking, from the cycle that produced the displayed route only
            # (03-REVIEW MD-04: a kept or superseded cycle's cost belongs to another route);
            # a non-forced adoption (L5 alternate cycles) keeps the last forced cost
            self.cost_s = None if res.cost_s is None else max(0.0, float(res.cost_s))
        self._on_new_route()
        self._force_carry = False
        self._fail_streak = 0
        self._route_conf_t = float(req.base.t0)
        self.withdrawn = None
        self._restored_unverified = False
        self.missed = False
        self._missed_failed = False
        self._missed_t = None
        self._restore_alert = False
        self.save()
        text = self.route_text()
        if text is not None:
            self.hub.publish(text)

    def _on_new_route(self) -> None:
        assert self.route is not None
        self._last_follow = None
        self.follower = RouteFollower(
            self.route.path, self.route.tacks, legs=[eta for _mid, eta in self.route.legs]
        )
        self.offroute.reset()  # 03-04: the off-route timer follows the displayed route

    @staticmethod
    def _whole_eta(req: CycleRequest, shown: RouteResult, kind: str) -> float | None:
        """ETA of the shown route (a "stay" route covers the current leg only)."""
        return shown.eta

    # -- advice ------------------------------------------------------------------------------
    def _follow(self, now: float, msg: dict) -> Follow | None:
        if self.follower is None:
            return None
        boat = msg.get("boat") or {}
        wind = msg.get("wind") or {}
        return self.follower.follow(
            now, float(boat["lat"]), float(boat["lon"]), boat.get("cog_t"), wind.get("twd_t")
        )

    def _fill_advice(self, block: dict, now: float, msg: dict, f: Follow | None) -> None:
        r = self.route
        if r is None:
            if self._inflight > 0:
                self._set_state(block, "computing", None)
            elif self._last_fail is not None:
                self._set_state(block, "failed", self._last_fail)
            else:
                self._set_state(block, "computing", None)
            return
        if self.withdrawn is not None:
            # withdrawn (CR-02): what it was, but nothing to steer -> Phase 2 laylines
            self._set_state(block, "outdated", self.withdrawn)
            block.update(
                version=r.version,
                kind=r.kind,
                age_s=_r(max(0.0, now - r.t0), 0),
                computed_utc=iso_utc(r.t0),
                level=r.level,
            )
            return
        self._set_state(block, "ok", None)
        if self._fail_streak > 0:  # still steerable, but the last recompute failed
            block["stale"] = True
            block["last_fail"] = self._last_fail
        if r.kind == "stay" and r.force_released_at is not None:
            block["stay"]["released_land"] = True
            block["stay"]["release_in_s"] = _r(r.force_released_at - now, 0)
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
        twa_now = wind.get("twa")
        # on the other tack than the route's (HI-01): |TWA| - |target| would read ~0, green
        wrong = (
            twa_now is not None
            and abs(twa_now) >= WRONG_TACK_MIN_DEG
            and (1 if twa_now > 0 else -1) != int(f.target_tack)
        )
        block["wrong_tack"] = bool(wrong)
        if twa_abs < PRIMARY_TWA_UP_DEG or twa_abs > PRIMARY_TWA_DOWN_DEG:
            block["primary"] = "twa"
            block["target"] = _r(twa_abs, 1)
            if twa_now is not None and not wrong:
                block["deviation"] = _r(abs(twa_now) - twa_abs, 1)
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

    def _fill_common(self, block: dict, now: float | None) -> None:
        """Pieces shown whatever the routing state: On reste, cost, missed-tack recompute."""
        block["stay"]["active"] = self.stay.active
        block["stay"]["tack"] = _tack_name(self.stay.tack) if self.stay.active else None
        if not self.stay.active:
            block["stay"]["released_land"] = False
            block["stay"]["release_in_s"] = None
        block["missed"] = self.missed
        block["updating"] = self.missed and block.get("state") == "ok"
        if self.route is not None and block.get("state") == "ok":
            block["cost_s"] = _r(self.cost_s, 0)
            block["cost_text"] = cost_text(self.cost_s)

    def alerts(self) -> list[str]:
        out = list(self.coverage_alerts)
        if self._invalid_alert is not None:
            text, until = self._invalid_alert
            if self.clock.monotonic() < until:
                out.append(text)
            else:
                self._invalid_alert = None
        if self._restore_alert:
            out.append(ALERT_RESTORE)
        if self._pack_changed:
            out.append(ALERT_PACK_CHANGED)
        if self._pool_alert is not None:
            text, until = self._pool_alert
            if self.clock.monotonic() < until:
                out.append(text)
            else:
                self._pool_alert = None
        return out

    def _alerts(self, msg: dict) -> None:
        alerts = msg.setdefault("alerts", [])
        for a in self.alerts():
            if a not in alerts:
                alerts.append(a)

    # -- coverage (GRIB-02) ------------------------------------------------------------------
    def _window_key(self) -> tuple[str, str]:
        s = self.nav.settings
        return (s.race_start_local, s.race_end_local)

    def _course_points_legs(self) -> tuple[list, list]:
        """Marks and legs of the active course (the course actually sailed)."""
        c = self.nav.course.course
        seq = [lg.mark_id for lg in c.seq[: self.nav.course.last_idx + 1]]
        points: list[tuple[str, float, float]] = []
        seen: set[str] = set()
        for mid in seq:
            m = c.marks.get(mid)
            if m is not None and mid not in seen:
                seen.add(mid)
                points.append((m.name, m.lat, m.lon))
        legs = []
        for a, b in zip(seq, seq[1:], strict=False):
            ma, mb = c.marks.get(a), c.marks.get(b)
            if ma is None or mb is None or a == b:
                continue
            legs.append((f"{ma.name} → {mb.name}", (ma.lat, ma.lon), (mb.lat, mb.lon)))
        return points, legs

    def run_coverage(self) -> None:
        """Coverage of the race window, marks and legs by the pack (never raises)."""
        self._coverage_key = (self.nav.course.version, self.pack_version, self._window_key())
        self.coverage_alerts, self.coverage_warnings = [], []
        if self.pack is None:
            return
        self.coverage_runs += 1
        try:
            window = window_from_local(*self._window_key())
            points, legs = self._course_points_legs()
            rep = coverage(self.pack, points, legs, window)
        except Exception as exc:  # noqa: BLE001 - a coverage problem is an alert, not a crash
            log.exception("coverage failed")
            self.coverage_alerts = [f"MÉTÉO INCOMPLÈTE : contrôle impossible ({exc})"]
            return
        self.coverage_alerts = list(dict.fromkeys(rep.alerts))
        self.coverage_warnings = list(dict.fromkeys(rep.warnings))

    # -- persistence -------------------------------------------------------------------------
    def save(self) -> None:
        """Atomic <data-dir>/route.json of the adopted route (never raises)."""
        r = self.route
        if r is None:
            return
        doc = {
            "v": ROUTE_FILE_VERSION,
            "version": r.version,
            "kind": r.kind,
            "t0": r.t0,
            "adopted_t": r.adopted_t,
            "level": r.level,
            "eta": r.eta,
            "legs": [list(x) for x in r.legs],
            "path": [list(p) for p in r.path],
            "tacks": [list(k) for k in r.tacks],
            "horizon_hold": r.horizon_hold,
            "start_in_margin": r.start_in_margin,
            "force_released_at": r.force_released_at,
            "course_version": r.course_version,
            "marks": [list(m) for m in r.marks],
            "message": self.route_message(),
        }
        try:
            self.route_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.route_file, doc)
        except (OSError, TypeError, ValueError):
            log.exception("route.json write failed")

    def restore(self) -> None:
        """Last good route from route.json (same course only); corrupt -> ignored with an alert."""
        if not (
            self.route_file.exists() or self.route_file.with_name(ROUTE_FILE + ".bak").exists()
        ):
            return
        raw = load_json_with_bak(self.route_file, None)
        try:
            r = self._parse_saved(raw)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("route.json ignored: %s", exc)
            self._restore_alert = True
            return
        if r.course_version != self.nav.course.version:
            return  # computed for another course
        self.route = r
        # computed against a pack / mask that may have changed: shown (greyed, withdrawn)
        # until the first worker cycle replaces it (MD-05)
        self._restored_unverified = True
        self.version = max(self.version, r.version)
        self._on_new_route()

    @staticmethod
    def _parse_saved(raw: Any) -> Adopted:
        if not isinstance(raw, dict) or raw.get("v") != ROUTE_FILE_VERSION:
            raise ValueError("format inconnu")

        def num(x: Any) -> float:
            if isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x):
                raise ValueError(f"nombre invalide {x!r}")
            return float(x)

        def opt_num(x: Any) -> float | None:
            return None if x is None else num(x)

        path = tuple(
            PathPoint(*(num(v) for v in p[:4]), int(p[4]), *(num(v) for v in p[5:8]))
            for p in raw["path"]
            if len(p) == 8
        )
        if len(path) != len(raw["path"]) or not path:
            raise ValueError("chemin invalide")
        tacks = tuple(
            TackPoint(num(k[0]), num(k[1]), num(k[2]), int(k[3]), int(k[4]), str(k[5]))
            for k in raw["tacks"]
        )
        legs = tuple((str(m), num(e)) for m, e in raw["legs"])
        kind = raw["kind"]
        if kind not in ("optimal", "stay"):
            raise ValueError("type de route invalide")
        raw_marks = raw.get("marks") or []
        marks = tuple(
            (str(m[0]), num(m[1]), num(m[2]), str(m[3]), num(m[4]))
            for m in raw_marks
            if len(m) == 5
        )
        if len(marks) != len(raw_marks):
            raise ValueError("marques invalides")
        version = raw["version"]
        cv = raw["course_version"]
        if not isinstance(version, int) or not isinstance(cv, int):
            raise ValueError("version invalide")
        return Adopted(
            version=version,
            kind=kind,
            t0=num(raw["t0"]),
            adopted_t=num(raw["adopted_t"]),
            level=str(raw["level"]),
            eta=opt_num(raw["eta"]),
            legs=legs,
            path=path,
            tacks=tacks,
            horizon_hold=bool(raw["horizon_hold"]),
            start_in_margin=bool(raw["start_in_margin"]),
            force_released_at=opt_num(raw["force_released_at"]),
            course_version=cv,
            marks=marks,
        )

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
            "wrong_tack": False,
            "off_route": False,
            "countdown_s": None,
            "tack_kind": None,
            "tack_lat": None,
            "tack_lon": None,
            "missed": False,
            "updating": False,
            "stale": False,
            "last_fail": None,
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
                "reason": None,
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
            "alerts": list(self.coverage_alerts),
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
            "faults": int(st.get("faults", 0) or 0),
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
            "coverage": {
                "alerts": list(self.coverage_alerts),
                "warnings": list(self.coverage_warnings),
                "runs": self.coverage_runs,
            },
            "stay": self.stay.to_dict(),
            "cost_s": _r(self.cost_s, 0),
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
            [
                {"path": "nav.route.countdown", "value": block.get("countdown_s"), "unit": "s"},
                {"path": "nav.route.cost", "value": block.get("cost_s"), "unit": "s"},
                {"path": "nav.bias.dir", "value": block["bias"].get("dir_deg"), "unit": "deg"},
                {"path": "nav.bias.ratio", "value": block["bias"].get("ratio"), "unit": None},
            ],
            self.clock.monotonic(),
        )

    # -- route message -----------------------------------------------------------------------
    def route_message(self) -> dict | None:
        r = self.route
        if r is None:
            return None
        shown = display_points(r.path, MAX_ROUTE_POINTS)
        coords = [[round(p.lon, 6), round(p.lat, 6)] for p in shown]
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
        # route time of the boat at adoption is t0: a tack at t0 is the next one (HI-01)
        nxt = next((tk for tk in r.tacks if tk.t >= r.t0 - 1.0), None)
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
