"""Start mode (quick 261110-cuk, "Mode départ"): the start line, the 5:00 timer and the start block
of the nav message.

<data-dir>/start.json = {"open": bool, "gun_utc": float | null, "committee": End | null,
"pin": End | null}, End = {"lat", "lon", "src": "ping" | "typed", "utc": float | null}. Written
with atomic_write_json (write first, then memory: a failed write raises OSError and changes
nothing); a torn file falls back to start.json.bak (restored "bak"), then to the defaults
(restored "unreadable"). The restored state is shown inside the start block only, never in the
envelope alerts (H-01: the helm message keeps its exact shape).

Line ends: « Ping comité » / « Ping bouée » store the boat's GPS position (src "ping"), the
typed fallback stores degrees + decimal minutes parsed on the tablet (src "typed"). Both survive a
core restart and closing start mode.

Timer: start_timer() sets gun_mono = t_mono + 300 s in memory and, when the trusted GPS UTC is
known, gun_utc = utc_now + 300 s on disk. The page reads the remaining time from the nav message,
so a reload keeps the countdown. After a core restart gun_mono is unknown: with a persisted
gun_utc the timer reads "clock" until trusted UTC is known, then re-anchors gun_mono = t_mono +
gun_utc - utc_now (and fires the gun at once if it already passed). A timer started without
trusted UTC runs in memory only (it survives a page reload, not a core restart) and records its
gun_utc the first time utc_now is known. No clock is read here: t_mono and utc_now are
parameters (tests/test_no_wallclock.py).

SYNC rounds the remaining time to the nearest full minute, floor(remaining / 60 + 0.5) * 60
(4:40 -> 5:00, 4:20 -> 4:00, 4:30 -> 5:00); 0 is the gun (classic sync pressed at the start
signal). STOP cancels the timer, start mode stays open. Closing start mode clears the timer.

At the gun (tick() with remaining <= 0, or a SYNC to 0) the timer stops and start mode closes on
every tablet (D-04); routing is untouched (it already routes from the live position to the
active mark). Every change is an event {"type": "start", "action": open | close | ping | typed |
timer_start | sync | stop | gun, ...} through on_event (installed by core/start_api.py; an
exception there is logged, never raised).

Time to the line and the start zone (D-03, H-03, O-01), a simple documented model: measured
true wind from the nav wind block (TWD/TWS; unusable when absent, source NONE or stale), the
helm's polar (heavy-wind derated) x efficiency_for(|TWA|), no current, no acceleration.
Headings and angles in degrees TRUE; TWA = wrap(TWD - heading), positive = starboard, heading =
TWD - TWA (as in nav/laylines.py). Distances in nm in a local flat frame centred on the line
midpoint (geo.to_local).
- Current heading ("Ligne au cap"): the boat's heading; pinching above the polar beat angle
  (|TWA| < up_twa) counts as bearing away to the beat angle on the same tack (head to wind
  exactly = starboard). Time = distance to the line along that heading / (polar speed x
  efficiency); the crossing may fall outside the segment ("hors ligne", on_line false).
- Other tack ("Autre bord"): the heading mirrored about TWD with the same |TWA|, plus
  settings.start_tack_s (« Départ : durée d'un virement (s) », default 10 s), the one tack cost
  of start mode. The router's tack_penalty_s is never read here.
- Margin = remaining time - time to the line (positive = time to burn), only while the timer
  runs. tack_now: the other tack's margin is in (-TACK_NOW_WINDOW_S, 0] and it crosses inside the
  segment (D-03c: tack now).
- Zone (D-03a): the positions from which the boat reaches the line exactly at the gun, a reverse
  isochrone: the convex hull of the line ends and of A - T'v, B - T'v for every polar velocity v
  (every ZONE_STEP_DEG of heading, VMG with tacks and gybes allowed) that crosses towards the
  course side, with T' = max(0, remaining - start_tack_s) (one tack or gybe assumed: a boat that
  lays the line on one straight course has at most start_tack_s more than the zone shows). The
  course side is the active mark's side of the line (nav mark block), else the windward side.
  Drawn only while the timer runs; it needs the line and the wind, not the position; none when
  T' <= 0.
Missing inputs give reason no_line > no_position > no_heading > no_wind, with the times null and no
zone (never an error); a geometry exception gives reason calc_error (logged once per message) and
the timer part of the block survives.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jabuka.common.atomicio import atomic_write_json, load_json_status
from jabuka.nav import geo
from jabuka.nav.polar import efficiency_for

log = logging.getLogger("jabuka.nav.start")

START_FILE = "start.json"
START_S = 300.0
END_NAMES = ("committee", "pin")
TACK_NOW_WINDOW_S = 10.0  # the other tack's margin in (-10 s, 0]: tack now
ZONE_STEP_DEG = 5  # heading step of the start zone's polar velocities
MIN_SPEED_KN = 0.05  # below: no time to the line


class LineEnd(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    lat: float = Field(ge=42.0, le=45.0)
    lon: float = Field(ge=14.0, le=17.0)
    src: Literal["ping", "typed"]
    utc: float | None = None


class StartState(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    open: bool = False
    gun_utc: float | None = None
    committee: LineEnd | None = None
    pin: LineEnd | None = None


class NoTimer(Exception):
    """SYNC without a running timer with a known remaining time (HTTP 409)."""


def _parse_start_file(raw: Any) -> StartState:
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    return StartState.model_validate(raw)


def _num(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class StartStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / START_FILE
        self.on_event: Callable[[dict], None] | None = None
        parsed, source = load_json_status(self.path, None, validate=_parse_start_file)
        self.state: StartState = parsed if isinstance(parsed, StartState) else StartState()
        self.restored: str | None = source if source in ("bak", "unreadable") else None
        self.gun_mono: float | None = None  # memory only: re-anchored from gun_utc after a restart

    # -- accessors ---------------------------------------------------------------------------
    @property
    def open(self) -> bool:
        return self.state.open

    def _timer_set(self) -> bool:
        return self.gun_mono is not None or self.state.gun_utc is not None

    # -- events / persistence ----------------------------------------------------------------
    def _emit(self, rec: dict) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event({"type": "start", **rec})
        except Exception:  # an event line never breaks a start action or the tick
            log.exception("start event failed")

    def _write(self, state: StartState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, state.model_dump())

    def _commit(self, state: StartState) -> None:
        """Write, then memory (OSError propagates: nothing changed)."""
        self._write(state)
        self.state = state

    # -- mutations ---------------------------------------------------------------------------
    def set_open(self, flag: bool) -> None:
        """Open or close start mode; closing clears the timer (the line ends stay)."""
        upd: dict[str, Any] = {"open": bool(flag)}
        if not flag:
            upd["gun_utc"] = None
        self._commit(self.state.model_copy(update=upd))
        if not flag:
            self.gun_mono = None
        self._emit({"action": "open" if flag else "close"})

    def set_end(
        self, end: str, lat: float, lon: float, src: str, utc: float | None = None
    ) -> LineEnd:
        """Store one line end. ValueError (unknown end) / pydantic ValidationError (outside
        42-45 N / 14-17 E, NaN) / OSError: nothing changes."""
        if end not in END_NAMES:
            raise ValueError(f"unknown line end {end!r}")
        entry = LineEnd(lat=lat, lon=lon, src=src, utc=utc)  # type: ignore[arg-type]
        self._commit(self.state.model_copy(update={end: entry}))
        self._emit(
            {
                "action": "ping" if src == "ping" else "typed",
                "end": end,
                "lat": entry.lat,
                "lon": entry.lon,
                "src": entry.src,
            }
        )
        return entry

    def start_timer(self, t_mono: float, utc_now: float | None, seconds: float = START_S) -> None:
        """Start the countdown (the 5-minute signal); also opens start mode."""
        gun_utc = utc_now + seconds if utc_now is not None else None
        self._commit(self.state.model_copy(update={"open": True, "gun_utc": gun_utc}))
        self.gun_mono = t_mono + seconds
        self._emit({"action": "timer_start", "remaining_s": seconds, "gun_utc": gun_utc})

    def sync(
        self,
        t_mono: float,
        utc_now: float | None,
        boat: tuple[float, float] | None = None,
    ) -> float:
        """Round the remaining time to the nearest full minute; returns the new remaining time.
        0 fires the gun (via "sync"). NoTimer when no timer runs with a known remaining time."""
        state, rem = self.remaining(t_mono, utc_now)
        if state != "running" or rem is None:
            raise NoTimer()
        new = math.floor(rem / 60.0 + 0.5) * 60.0
        if new <= 0.0:
            self._gun("sync", boat, utc_now)
            return 0.0
        gun_utc = utc_now + new if utc_now is not None else None
        self._commit(self.state.model_copy(update={"gun_utc": gun_utc}))
        self.gun_mono = t_mono + new
        self._emit({"action": "sync", "remaining_s": new, "from_s": round(rem, 1)})
        return new

    def stop(self) -> None:
        """Cancel the timer (start postponed); start mode stays open."""
        self._commit(self.state.model_copy(update={"gun_utc": None}))
        self.gun_mono = None
        self._emit({"action": "stop"})

    # -- timer -------------------------------------------------------------------------------
    def remaining(self, t_mono: float, utc_now: float | None) -> tuple[str, float | None]:
        """("off", None) | ("clock", None) (gun UTC known, trusted UTC not yet) |
        ("running", seconds >= 0)."""
        if not self._timer_set():
            return "off", None
        if self.gun_mono is None:
            gun_utc = self.state.gun_utc
            if utc_now is None or gun_utc is None:
                return "clock", None
            self.gun_mono = t_mono + (gun_utc - utc_now)  # after a core restart
        elif self.state.gun_utc is None and utc_now is not None:
            # started before the GPS clock was trusted: record the gun UTC once (restart-proof)
            new = self.state.model_copy(update={"gun_utc": utc_now + (self.gun_mono - t_mono)})
            self.state = new
            try:
                self._write(new)
            except OSError:
                log.exception("start.json write failed (gun UTC)")
        return "running", max(0.0, self.gun_mono - t_mono)

    def _gun(self, via: str, boat: tuple[float, float] | None, utc_now: float | None) -> None:
        gun_utc = self.state.gun_utc if self.state.gun_utc is not None else utc_now
        new = self.state.model_copy(update={"open": False, "gun_utc": None})
        self.state = new  # memory closes even when the SD card refuses the write
        self.gun_mono = None
        try:
            self._write(new)
        except OSError:
            log.exception("start.json write failed (gun)")
        self._emit(
            {
                "action": "gun",
                "via": via,
                "gun_utc": gun_utc,
                "boat": [boat[0], boat[1]] if boat is not None else None,
            }
        )

    def tick(self, t_mono: float, utc_now: float | None, boat: tuple[float, float] | None) -> None:
        """Called every nav tick: the gun closes start mode (D-04)."""
        if not self.state.open:
            return
        state, rem = self.remaining(t_mono, utc_now)
        if state == "running" and rem is not None and rem <= 0.0:
            self._gun("timer", boat, utc_now)

    def to_api(self) -> dict:
        return {**self.state.model_dump(), "restored": self.restored}


# -- geometry (degrees TRUE, nm, kn) ------------------------------------------------------------
def _wrap180(deg: float) -> float:
    a = math.fmod(deg + 180.0, 360.0)
    if a < 0.0:
        a += 360.0
    return a - 180.0


def _norm360(deg: float) -> float:
    a = math.fmod(deg, 360.0)
    if a < 0.0:
        a += 360.0
    return 0.0 if a >= 360.0 else a


def tack_headings(
    hdg: float, twd: float, up_twa_deg: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """((heading now, TWA now), (heading other tack, TWA other tack)), degrees. Above the beat
    angle (|TWA| < up_twa) the boat is taken as bearing away to it on the same tack (head to wind
    exactly = starboard); the other tack is the heading mirrored about TWD with the same |TWA|."""
    twa = _wrap180(twd - hdg)
    if abs(twa) < up_twa_deg:
        twa = math.copysign(up_twa_deg, twa) if twa != 0.0 else up_twa_deg
    other = -twa
    return (_norm360(twd - twa), twa), (_norm360(twd - other), other)


def ray_to_line(
    px: float, py: float, hdg: float, ax: float, ay: float, bx: float, by: float
) -> tuple[float | None, bool]:
    """Distance (nm) from P along heading hdg (deg) to the infinite line through A and B, and
    whether the crossing falls inside the segment; (None, False) when parallel or behind."""
    dx, dy = math.sin(math.radians(hdg)), math.cos(math.radians(hdg))
    ex, ey = bx - ax, by - ay
    denom = dx * ey - dy * ex
    if abs(denom) < 1e-9:
        return None, False
    wx, wy = ax - px, ay - py
    t = (wx * ey - wy * ex) / denom
    if t < 0.0:
        return None, False
    s = (wx * dy - wy * dx) / denom
    return t, -1e-9 <= s <= 1.0 + 1e-9


def course_normal(
    a: tuple[float, float],
    b: tuple[float, float],
    mark_xy: tuple[float, float] | None,
    twd: float,
) -> tuple[float, float]:
    """Unit normal of the line A-B pointing to the course side: the side of the active mark,
    else the windward side (towards where the wind comes from)."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ey)
    if length <= 0.0:
        raise ValueError("degenerate start line")
    nx, ny = -ey / length, ex / length
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    ref = None
    if mark_xy is not None:
        rx, ry = mark_xy[0] - mx, mark_xy[1] - my
        if abs(rx * nx + ry * ny) > 1e-9:
            ref = (rx, ry)
    if ref is None:
        ref = (math.sin(math.radians(twd)), math.cos(math.radians(twd)))
    if ref[0] * nx + ref[1] * ny < 0.0:
        nx, ny = -nx, -ny
    return nx + 0.0, ny + 0.0


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain: the hull counter-clockwise, no repeated point."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0.0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0.0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def boat_speed(polar: Any, settings: Any, tws_kn: float, twa_deg: float) -> float:
    """Polar speed (kn) x the efficiency of that point of sail."""
    a = abs(twa_deg)
    eff = efficiency_for(a, settings.efficiency, settings.efficiency_up, settings.efficiency_down)
    return eff * polar.speed(tws_kn, a)


def zone_ring(
    a: tuple[float, float],
    b: tuple[float, float],
    n: tuple[float, float],
    twd: float | None,
    tws_kn: float | None,
    polar: Any,
    settings: Any,
    remaining_s: float,
    lat0: float,
    lon0: float,
) -> list[list[float]] | None:
    """The start zone as a closed [[lon, lat], ...] ring (5 decimals), None when there is no wind,
    no polar speed towards the course side or T' = remaining - start_tack_s <= 0."""
    if twd is None or tws_kn is None or tws_kn <= 0.0:
        return None
    t_h = max(0.0, remaining_s - settings.start_tack_s) / 3600.0
    if t_h <= 0.0:
        return None
    pts: list[tuple[float, float]] = [a, b]
    kept = 0
    for h in range(0, 360, ZONE_STEP_DEG):
        speed = boat_speed(polar, settings, tws_kn, _wrap180(twd - h))
        vx = speed * math.sin(math.radians(h))
        vy = speed * math.cos(math.radians(h))
        if vx * n[0] + vy * n[1] <= 1e-6:
            continue
        kept += 1
        pts.append((a[0] - t_h * vx, a[1] - t_h * vy))
        pts.append((b[0] - t_h * vx, b[1] - t_h * vy))
    if kept == 0:
        return None
    ring = []
    for x, y in convex_hull(pts):
        lat, lon = geo.from_local(x, y, lat0, lon0)
        ring.append([round(lon, 5), round(lat, 5)])
    if len(ring) < 3:
        return None
    ring.append(list(ring[0]))
    return ring


def tack_now(other: dict | None) -> bool:
    """D-03c: the other tack's margin is in (-TACK_NOW_WINDOW_S, 0] and it lays the segment."""
    if not other or not other.get("on_line"):
        return False
    m = other.get("margin_s")
    return isinstance(m, int | float) and -TACK_NOW_WINDOW_S < m <= 0.0


# -- nav block -----------------------------------------------------------------------------------
def _iso(epoch: float | None) -> str | None:
    """UTC epoch -> "2026-11-13T19:00:00Z" (same form as the clock status)."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def _end_block(e: LineEnd | None) -> dict | None:
    return None if e is None else {"lat": e.lat, "lon": e.lon, "src": e.src}


def _boat_pos(msg: dict) -> tuple[float, float] | None:
    boat = msg.get("boat") or {}
    lat, lon = _num(boat.get("lat")), _num(boat.get("lon"))
    return (lat, lon) if lat is not None and lon is not None else None


def start_block(
    store: StartStore,
    msg: dict,
    polar: Any,
    settings: Any,
    t_mono: float,
    utc_now: float | None,
) -> dict | None:
    """The "start" block of the nav message, None while start mode is closed (the key is then
    absent: the closed-mode message keeps exactly its old shape)."""
    store.tick(t_mono, utc_now, _boat_pos(msg))
    if not store.open:
        return None
    state, rem = store.remaining(t_mono, utc_now)
    st = store.state
    block: dict[str, Any] = {
        "open": True,
        "error": False,
        "restored": store.restored,
        "timer": {
            "state": state,
            "remaining_s": round(rem, 1) if rem is not None else None,
            "gun_utc": _iso(st.gun_utc),
        },
        "line": {
            "committee": _end_block(st.committee),
            "pin": _end_block(st.pin),
            "length_nm": None,
            "bearing_t": None,
        },
        "reason": None,
        "now": None,
        "other": None,
        "start_tack_s": _num(getattr(settings, "start_tack_s", None)),
        "tack_now": False,
        "zone": None,
    }
    running = rem if state == "running" else None
    try:
        _geometry(block, st, msg, polar, settings, running)
    except Exception as e:  # the timer part above always survives (H-01)
        _log_calc_error(e)
        block.update(reason="calc_error", now=None, other=None, tack_now=False, zone=None)
    return block


_logged_errors: set[str] = set()


def _log_calc_error(e: Exception) -> None:
    key = f"{type(e).__name__}: {e}"[:200]
    if key not in _logged_errors and len(_logged_errors) < 100:
        _logged_errors.add(key)
        log.exception("start computation failed")


def _wind_of(msg: dict) -> tuple[float, float] | None:
    w = msg.get("wind")
    if not isinstance(w, dict) or w.get("source") == "NONE" or w.get("stale") is True:
        return None
    twd, tws = _num(w.get("twd_t")), _num(w.get("tws_kn"))
    return (twd, tws) if twd is not None and tws is not None else None


def _side(
    h: float,
    twa: float,
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    tws: float,
    polar: Any,
    settings: Any,
    extra_s: float,
    remaining: float | None,
) -> dict:
    dist, on_line = ray_to_line(p[0], p[1], h, a[0], a[1], b[0], b[1])
    speed = boat_speed(polar, settings, tws, twa)
    t_s = None
    if dist is not None and speed >= MIN_SPEED_KN:
        t_s = dist / speed * 3600.0 + extra_s
    margin = remaining - t_s if remaining is not None and t_s is not None else None
    return {
        "hdg_t": round(h, 1),
        "twa": round(twa, 1),
        "t_s": round(t_s, 1) if t_s is not None else None,
        "on_line": bool(on_line),
        "margin_s": round(margin, 1) if margin is not None else None,
    }


def _geometry(
    block: dict,
    st: StartState,
    msg: dict,
    polar: Any,
    settings: Any,
    remaining: float | None,
) -> None:
    """Task 2 keys of the start block (line length/bearing, times, margins, tack_now, zone)."""
    com, pin = st.committee, st.pin
    if com is None or pin is None:
        block["reason"] = "no_line"
        return
    brg, length = geo.bearing_distance(com.lat, com.lon, pin.lat, pin.lon)
    block["line"]["length_nm"] = round(length, 3)
    block["line"]["bearing_t"] = round(math.degrees(brg) % 360.0, 1)
    lat0, lon0 = (com.lat + pin.lat) / 2.0, (com.lon + pin.lon) / 2.0
    a = geo.to_local(com.lat, com.lon, lat0, lon0)
    b = geo.to_local(pin.lat, pin.lon, lat0, lon0)
    wind = _wind_of(msg)
    boat = _boat_pos(msg)
    hdg = _num((msg.get("boat") or {}).get("hdg_t"))
    if boat is None:
        block["reason"] = "no_position"
    elif hdg is None:
        block["reason"] = "no_heading"
    elif wind is None:
        block["reason"] = "no_wind"
    if wind is None:
        return
    twd, tws = wind
    if remaining is not None:
        mark = msg.get("mark") if isinstance(msg.get("mark"), dict) else {}
        mlat, mlon = _num(mark.get("lat")), _num(mark.get("lon"))
        mark_xy = (
            geo.to_local(mlat, mlon, lat0, lon0) if mlat is not None and mlon is not None else None
        )
        n = course_normal(a, b, mark_xy, twd)
        block["zone"] = zone_ring(a, b, n, twd, tws, polar, settings, remaining, lat0, lon0)
    if block["reason"] is not None or boat is None or hdg is None:
        return
    p = geo.to_local(boat[0], boat[1], lat0, lon0)
    (h_now, twa_now), (h_other, twa_other) = tack_headings(hdg, twd, polar.targets(tws).up_twa)
    block["now"] = _side(h_now, twa_now, p, a, b, tws, polar, settings, 0.0, remaining)
    block["other"] = _side(
        h_other, twa_other, p, a, b, tws, polar, settings, settings.start_tack_s, remaining
    )
    block["tack_now"] = tack_now(block["other"])
