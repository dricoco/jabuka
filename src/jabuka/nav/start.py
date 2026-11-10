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

log = logging.getLogger("jabuka.nav.start")

START_FILE = "start.json"
START_S = 300.0
END_NAMES = ("committee", "pin")


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
    return {
        "open": True,
        "error": False,
        "restored": store.restored,
        "timer": {
            "state": state,
            "remaining_s": round(rem, 1) if rem is not None else None,
            "gun_utc": _iso(st.gun_utc),
        },
        "line": {"committee": _end_block(st.committee), "pin": _end_block(st.pin)},
    }
