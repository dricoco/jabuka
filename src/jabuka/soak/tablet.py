"""The soak's "tablet": a WebSocket client on the core's /ws reading the same diag / nav / route
messages the helm app renders.

- Reconnects every 0.5 s while the core is down.
- Liveness: wind is live when environment.wind.angleApparent from src "fastnet" is present and not
  stale per the diag row's own stale flag; position likewise for navigation.position from "gpsd".
  A signal goes dead on a disconnect, or after DEAD_DEBOUNCE consecutive diag rows without it.
  Every transition is recorded with its wall time.
- Every route message is re-validated against the pack's land mask (LandMask.load +
  frame.to_xy + validate_polyline), skipping the first segment when that route's
  nav.route.start_in_margin is true (as tests/routing/test_real_pack_e2e.py does). The core
  publishes the route rounded to COORD_DECIMALS (up to 6.9 cm from the polyline the router
  validated), so a segment the exact raster check flags only fails when it goes deeper into the
  blocked cells than that rounding can explain (Pi soak 20261110T220521Z, v121: the router's
  segment cleared the 100 m margin by millimetres, its published copy touched it).
- The core error counters (diag core.*) are tracked per connection: every increase is recorded
  with its wall time, for the "outside a fault window" check.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jabuka.route.frame import NM_M, NM_PER_DEG

WIND_PATH = "environment.wind.angleApparent"
POS_PATH = "navigation.position"
ERROR_COUNTERS = (
    "handler_errors",
    "nav_errors",
    "router_errors",
    "derived_errors",
    "bus_log_errors",
    "events_errors",
    "flush_errors",
)
DEAD_DEBOUNCE = 3  # consecutive diag messages without the signal
RECONNECT_S = 0.5
JUMP_S = 30.0  # a diag uptime step larger than this is a clock jump, not a tick
# router_service.RouterService.route_message publishes [round(lon, 6), round(lat, 6)]
COORD_DECIMALS = 6
GRAZE_STEP_M = 0.01  # depth sampling step along a flagged segment
_GRAZE_CHUNK = 1 << 18  # samples per numpy batch


def publication_precision_nm(frame: Any) -> float:
    """Farthest the core's COORD_DECIMALS rounding can move a route point (nm, local frame): half
    a unit of the last decimal east and north (4.04 / 5.56 cm in the race frame, 6.87 cm in all).
    A point of a published segment is as close to the matching point of the segment the router
    validated (the rounding of the two ends, interpolated)."""
    half = 0.5 * 10.0**-COORD_DECIMALS
    return math.hypot(half * frame.kx, half * NM_PER_DEG)


def graze_depth_nm(mask: Any, grid: Any, ax: float, ay: float, bx: float, by: float) -> float:
    """How deep segment AB goes into the blocked cells of ``grid`` (``mask.mask`` or
    ``mask.raw``): the largest distance from a point of it, sampled every GRAZE_STEP_M, to the
    nearest clear cell. 0.0 when no sample is blocked; inf when a blocked sample lies outside the
    grid or has no clear cell among its 8 neighbours (then it is at least a cell deep).

    Sampling can only miss the true maximum, so the published copy of a segment the router
    validated never measures deeper than publication_precision_nm."""
    import numpy as np

    ny, nx = grid.shape
    cell = mask.cell_nm
    step = GRAZE_STEP_M / NM_M
    n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / step)))
    worst = 0.0
    for i0 in range(0, n + 1, _GRAZE_CHUNK):
        t = np.arange(i0, min(i0 + _GRAZE_CHUNK, n + 1), dtype=np.float64) / n
        px = ax + t * (bx - ax)
        py = ay + t * (by - ay)
        r, c = mask.rc(px, py)
        if ((r < 0) | (r >= ny) | (c < 0) | (c >= nx)).any():
            return math.inf
        hit = grid[r, c]
        if not hit.any():
            continue
        px, py, r, c = px[hit], py[hit], r[hit], c[hit]
        best = np.full(len(px), np.inf)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                free = (rr >= 0) & (rr < ny) & (cc >= 0) & (cc < nx)
                free[free] = ~grid[rr[free], cc[free]]
                if not free.any():
                    continue
                x0 = mask.x0_nm + cc * cell
                y0 = mask.y0_nm + rr * cell
                dx = np.maximum(np.maximum(x0 - px, 0.0), px - (x0 + cell))
                dy = np.maximum(np.maximum(y0 - py, 0.0), py - (y0 + cell))
                best = np.minimum(best, np.where(free, np.hypot(dx, dy), np.inf))
        worst = max(worst, float(best.max()))
        if math.isinf(worst):
            return worst
    return worst


def row_live(rows: list[dict], path: str, src: str) -> bool:
    for r in rows:
        if r.get("path") == path and r.get("src") == src:
            return r.get("value") is not None and not r.get("stale", True)
    return False


class Signal:
    """A boolean with wall-time transitions."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.value = False
        self.transitions: list[tuple[float, bool]] = [(time.time(), False)]
        self._misses = 0

    def observe(self, live: bool, t: float, *, debounce: int = DEAD_DEBOUNCE) -> None:
        if live:
            self._misses = 0
            if not self.value:
                self.value = True
                self.transitions.append((t, True))
            return
        self._misses += 1
        if self.value and self._misses >= debounce:
            self.value = False
            self.transitions.append((t, False))

    def force(self, value: bool, t: float) -> None:
        self._misses = 0
        if self.value != value:
            self.value = value
            self.transitions.append((t, value))

    def value_at(self, t: float) -> bool:
        v = False
        for tt, vv in self.transitions:
            if tt > t:
                break
            v = vv
        return v

    def first_true_after(self, t: float) -> float | None:
        if self.value_at(t):
            return t
        for tt, vv in self.transitions:
            if tt > t and vv:
                return tt
        return None

    def went_false_between(self, t0: float, t1: float) -> bool:
        if not self.value_at(t0):
            return True
        return any(t0 <= tt <= t1 and not vv for tt, vv in self.transitions)


class TabletClient(threading.Thread):
    def __init__(
        self,
        url: str,
        mask_path: Path | None = None,
        *,
        name: str = "tablet",
        on_route: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(name=f"soak-{name}", daemon=True)
        self.url = url
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self.mask = None
        if mask_path is not None:
            from jabuka.route.landmask import LandMask

            self.mask = LandMask.load(mask_path)
        self.on_route = on_route
        self.wind = Signal("wind")
        self.pos = Signal("pos")
        self.conn = Signal("conn")
        self.connects = 0
        self.conn_errors = 0
        self.last_error: tuple[float, str] | None = None
        self.last_diag: dict | None = None
        self.last_nav: dict | None = None
        self.diag_count = 0
        self.nav_count = 0
        self.routes: list[dict[str, Any]] = []
        self._pending_routes: dict[int, tuple[float, dict]] = {}
        self._margin: dict[Any, bool] = {}  # route version -> start_in_margin seen True
        self.counter_increases: list[dict[str, Any]] = []
        self._counters: dict[str, int] | None = None
        self._uptime: float | None = None
        self.tick_pairs = 0
        self.tick_sim_s = 0.0
        self.alerts_seen: dict[str, float] = {}
        self.course_versions: list[tuple[float, Any]] = []  # (t_wall, nav.course_version)
        self.wind_sources: list[tuple[float, str | None]] = []
        self.route_blocks: list[tuple[float, dict]] = []  # (t_wall, nav.route), on change only
        self._last_route_key: Any = None
        self.clock_valid = Signal("clock")
        self.clock_invalid_count = 0  # valid -> invalid transitions of the diag clock
        self.layline_missing = 0  # beat/run nav messages with live wind + position, no laylines
        self.layline_legs = 0  # beat/run nav messages with live wind + position

    # -- lifecycle ---------------------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        from websockets.sync.client import connect

        while not self._stop.is_set():
            try:
                with connect(self.url, open_timeout=2.0, close_timeout=1.0, max_size=8 << 20) as ws:
                    with self.lock:
                        self.connects += 1
                        self._counters = None
                        self._uptime = None
                        self.conn.force(True, time.time())
                    while not self._stop.is_set():
                        try:
                            text = ws.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        self._on_text(text if isinstance(text, str) else text.decode())
            except Exception as exc:  # noqa: BLE001 - core down / restarting / closed
                with self.lock:
                    self.conn_errors += 1
                    self.last_error = (time.time(), repr(exc)[:200])
            t = time.time()
            with self.lock:
                self.conn.force(False, t)
                self.wind.force(False, t)
                self.pos.force(False, t)
            self._stop.wait(RECONNECT_S)

    # -- messages ----------------------------------------------------------------------------
    def _on_text(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        t = time.time()
        kind = msg.get("type")
        with self.lock:
            if kind == "diag":
                self._on_diag(msg, t)
            elif kind == "nav":
                self._on_nav(msg, t)
            elif kind == "route":
                self._on_route(msg, t)

    def _on_diag(self, msg: dict, t: float) -> None:
        self.diag_count += 1
        self.last_diag = msg
        rows = msg.get("values") or []
        self.wind.observe(row_live(rows, WIND_PATH, "fastnet"), t)
        self.pos.observe(row_live(rows, POS_PATH, "gpsd"), t)
        valid = bool((msg.get("clock") or {}).get("time_valid"))
        if self.clock_valid.value and not valid:
            self.clock_invalid_count += 1
        self.clock_valid.observe(valid, t, debounce=1)
        core = msg.get("core") or {}
        up = core.get("uptime_s")
        if isinstance(up, int | float):
            if self._uptime is not None:
                d = up - self._uptime
                if 0 < d <= JUMP_S:
                    self.tick_pairs += 1
                    self.tick_sim_s += d
            self._uptime = up
        cur = {k: int(core.get(k) or 0) for k in ERROR_COUNTERS}
        if self._counters is not None:
            for k, v in cur.items():
                if v > self._counters.get(k, 0):
                    self.counter_increases.append(
                        {"t_wall": t, "counter": k, "delta": v - self._counters[k]}
                    )
        self._counters = cur

    def _on_nav(self, msg: dict, t: float) -> None:
        self.nav_count += 1
        self.last_nav = msg
        # reach legs have no laylines by design (nav/laylines.py): only beats and runs count
        if self.wind.value and self.pos.value and msg.get("leg") in ("beat", "run"):
            self.layline_legs += 1
            if not msg.get("layline"):
                self.layline_missing += 1
        for a in msg.get("alerts") or []:
            self.alerts_seen.setdefault(a, t)
        r = msg.get("route") or {}
        for a in (r.get("pack") or {}).get("alerts") or []:
            self.alerts_seen.setdefault(a, t)
        cv = msg.get("course_version")
        if not self.course_versions or self.course_versions[-1][1] != cv:
            self.course_versions.append((t, cv))
        src = (msg.get("wind") or {}).get("source")
        if not self.wind_sources or self.wind_sources[-1][1] != src:
            self.wind_sources.append((t, src))
        key = (
            r.get("state"),
            r.get("version"),
            r.get("reason"),
            (r.get("stay") or {}).get("active"),
        )
        if key != self._last_route_key:
            self._last_route_key = key
            self.route_blocks.append((t, r))
        v = r.get("version")
        if isinstance(v, int):
            for pv in sorted(self._pending_routes):
                if pv <= v:
                    tr, rmsg = self._pending_routes.pop(pv)
                    margin = bool(r.get("start_in_margin")) if pv == v else None
                    self._validate(rmsg, tr, margin)

    def _on_route(self, msg: dict, t: float) -> None:
        v = msg.get("version")
        if not isinstance(v, int):
            return
        self._pending_routes[v] = (t, msg)

    def _validate(self, msg: dict, t: float, start_in_margin: bool | None) -> None:
        coords: list = []
        for f in (msg.get("geojson") or {}).get("features") or []:
            if (f.get("properties") or {}).get("role") == "route":
                coords = (f.get("geometry") or {}).get("coordinates") or []
        rec: dict[str, Any] = {
            "t_wall": t,
            "version": msg.get("version"),
            "kind": msg.get("kind"),
            "n_points": len(coords),
            "start_in_margin": start_in_margin,
            "land_ok": None,
            "bad_index": None,
        }
        if self.mask is not None and len(coords) >= 2:
            import numpy as np

            lons = np.array([c[0] for c in coords], dtype=np.float64)
            lats = np.array([c[1] for c in coords], dtype=np.float64)
            xs, ys = self.mask.frame.to_xy(lats, lons)
            v = msg.get("version")
            if start_in_margin:
                self._margin[v] = True
            elif self._margin.get(v):  # a restored route ("outdated") does not carry the flag
                start_in_margin = True
            v0 = 1 if start_in_margin else 0
            ok, bad, graze = self._published_ok(False, xs[v0:], ys[v0:])
            if not ok and v0 == 0 and bad == 0 and self._starts_in_margin(xs, ys):
                # the router's own rule: a start inside the shore margin only has to clear real
                # land on its exit segment (raw raster), the rest the full mask
                raw_ok, _bad, g_exit = self._published_ok(True, xs[:2], ys[:2])
                ok2, bad2, g_rest = self._published_ok(False, xs[1:], ys[1:])
                ok, bad = (
                    raw_ok and ok2,
                    (0 if not raw_ok else (None if bad2 is None else bad2 + 1)),
                )
                graze = max(g_exit, g_rest)
                rec["detail"] = "start in the shore margin: exit segment checked on raw land"
                v0 = 0
            rec["land_ok"] = bool(ok)
            rec["bad_index"] = None if bad is None else int(bad) + v0
            if ok and graze > 0.0:
                rec["graze_m"] = round(graze * NM_M, 4)
                tol_m = publication_precision_nm(self.mask.frame) * NM_M
                note = (
                    f"published route grazes the mask by {rec['graze_m']:g} m, within the "
                    f"{COORD_DECIMALS}-decimal rounding ({tol_m:.3f} m)"
                )
                rec["detail"] = f"{rec['detail']}; {note}" if rec.get("detail") else note
        self.routes.append(rec)
        if self.on_route is not None:
            try:
                self.on_route(rec)
            except Exception:  # noqa: BLE001
                pass

    def _published_ok(self, raw: bool, xs: Any, ys: Any) -> tuple[bool, int | None, float]:
        """validate_polyline (raw_segments_clear when ``raw``) at the publication precision:
        (ok, index of the first segment deeper than publication_precision_nm, deepest graze nm
        among the flagged segments that are not)."""
        import numpy as np

        m = self.mask
        assert m is not None
        if len(xs) < 2:
            ok, bad = m.validate_polyline(xs, ys)
            return ok, bad, 0.0
        ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
        clear = m.raw_segments_clear(ax, ay, bx, by) if raw else m.segments_clear(ax, ay, bx, by)
        grid = m.raw if raw else m.mask
        tol = publication_precision_nm(m.frame) + 1e-12  # float noise of the frame round trip
        graze = 0.0
        for i in np.nonzero(~clear)[0].tolist():
            depth = graze_depth_nm(m, grid, ax[i], ay[i], bx[i], by[i])
            if depth > tol:
                return False, i, graze
            graze = max(graze, depth)
        return True, None, graze

    def _starts_in_margin(self, xs: Any, ys: Any) -> bool:
        m = self.mask
        assert m is not None
        return bool(not m.points_clear(xs[:1], ys[:1])[0] and m.raw_points_clear(xs[:1], ys[:1])[0])

    # -- queries -----------------------------------------------------------------------------
    def live(self) -> bool:
        with self.lock:
            return self.wind.value and self.pos.value

    def signal(self, what: str) -> Signal:
        return {"wind": self.wind, "pos": self.pos, "conn": self.conn}[what]

    def first_live_after(self, t: float, what: tuple[str, ...] = ("wind", "pos")) -> float | None:
        """Wall time at which every signal in ``what`` was live at or after t."""
        with self.lock:
            sigs = [self.signal(w) for w in what]
            cand = t
            for _ in range(100):
                times = [s.first_true_after(cand) for s in sigs]
                if any(x is None for x in times):
                    return None
                m = max(times)  # type: ignore[type-var]
                if all(s.value_at(m) for s in sigs):
                    return m
                cand = m
            return None

    def wait_live(
        self, after: float, timeout: float, what: tuple[str, ...] = ("wind", "pos")
    ) -> float | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            t = self.first_live_after(after, what)
            if t is not None:
                return t
            time.sleep(0.05)
        return None

    def wait(self, pred: Callable[[TabletClient], Any], timeout: float) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                v = pred(self)
            if v:
                return v
            time.sleep(0.05)
        return None

    def route_block(self) -> dict:
        with self.lock:
            return dict((self.last_nav or {}).get("route") or {})

    def max_route_version(self) -> int:
        with self.lock:
            vs = [r["version"] for r in self.routes if isinstance(r.get("version"), int)]
            return max(vs) if vs else 0

    def last_route_version(self) -> int:
        """Version of the route the core shows now: the "before" baseline of a fault. The last
        nav message's route.version (the core's own counter: 0 when it has no route), else the
        version adopted last, 0 before any. Not max_route_version: a core restart whose saved
        route is rightly not restored numbers from 1 again (Pi soak 20261110T153632Z, f65 ->
        f67..f85); and not the last route message either: a core restarted with the course
        finished publishes none and shows 0 (Pi soak 20261110T220521Z f67: v129 came from the
        process f65 replaced, the new course's route was v1)."""
        with self.lock:
            v = ((self.last_nav or {}).get("route") or {}).get("version")
            if isinstance(v, int) and not isinstance(v, bool):
                return v
            for r in reversed(self.routes):
                if isinstance(r.get("version"), int):
                    return r["version"]
            return 0

    def routes_after(self, t: float) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.routes if r["t_wall"] >= t]

    def summary(self, t0: float) -> dict[str, Any]:
        """Transitions (seconds after t0) and counters, for the report."""
        with self.lock:
            return {
                "connects": self.connects,
                "conn_errors": self.conn_errors,
                "diag": self.diag_count,
                "nav": self.nav_count,
                "transitions": {
                    s.name: [(round(t - t0, 3), v) for t, v in s.transitions]
                    for s in (self.conn, self.wind, self.pos)
                },
                "wind_sources": [(round(t - t0, 3), src) for t, src in self.wind_sources],
                "route_states": [
                    (round(t - t0, 3), b.get("state"), b.get("version"), b.get("reason"))
                    for t, b in self.route_blocks
                ],
            }

    def clock_valid_since(self, t: float) -> float | None:
        """Wall time the diag clock was (or became) valid at or after t."""
        return self.clock_valid.first_true_after(t)

    def tick_ratio(self) -> float | None:
        with self.lock:
            return self.tick_pairs / self.tick_sim_s if self.tick_sim_s > 0 else None
