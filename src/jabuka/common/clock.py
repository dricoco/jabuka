"""Injected clock: the ONLY module in jabuka.common / jabuka.core allowed to read the wall clock
or the monotonic clock (enforced by tests/test_no_wallclock.py).

- SystemClock: process clocks. It cannot vouch for UTC (the Pi has no RTC and no internet), so
  time_valid is False and routing_time_gate is "blocked". GpsClock provides validity.
- GpsClock: UTC disciplined by gpsd TPV fixes (3 consistent sane fixes), holdover, jump handling.
- SimClock: a simulated monotonic clock that only moves forward, driven by advance(dt) in tests
  and by observe_utc(t_sim) from replay/sim messages.
- os_monotonic(): the OS monotonic clock, never simulated, for supervising real OS processes only
  (the router worker pool watchdog, quick-261110-lqa).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    kind: str

    def monotonic(self) -> float: ...

    def wall(self) -> float: ...

    def now_utc(self) -> datetime | None: ...

    def status(self) -> dict: ...

    async def sleep_until(self, t_mono: float) -> None: ...


def os_monotonic() -> float:
    """The OS monotonic clock in seconds, never simulated or accelerated. Only for supervising
    real OS processes (the router worker pool watchdog and its re-creation back-off), whose run
    time is real seconds whatever the injected Clock (SimClock follows sim message time, x20
    under the soak). Domain time still comes from the injected Clock (quick-261110-lqa)."""
    return time.monotonic()


def utc_epoch(clock: Clock) -> float | None:
    """Trusted UTC (GPS-disciplined, or simulated) as an epoch, None while not synced. Domain
    decisions that must survive a restart (manual-wind age, the Annuler window) use this, never
    wall(): the Pi has no RTC and its system clock is fake-hwclock's last save until chrony
    locks (WR-03)."""
    now = clock.now_utc()
    return None if now is None else now.timestamp()


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


class SystemClock:
    """Process clocks. Not a trusted UTC source: routing stays blocked."""

    kind = "system"

    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()

    def now_utc(self) -> datetime | None:
        # The system clock is not trusted (no RTC, no GPS discipline proven here).
        return None

    @property
    def time_valid(self) -> bool:
        return False

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "time_valid": False,
            "routing_time_gate": "blocked",
            "utc": None,
            "system_utc": _iso(time.time()),
        }

    async def sleep_until(self, t_mono: float) -> None:
        delay = t_mono - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


class SimClock:
    """Simulated time. monotonic() never goes backwards; UTC becomes valid once observed."""

    kind = "sim"

    def __init__(self, start_utc: float | None = None) -> None:
        self._mono = 0.0
        self._utc: float | None = start_utc
        self._cond: asyncio.Condition | None = None
        self._cond_loop: asyncio.AbstractEventLoop | None = None

    # -- driving -----------------------------------------------------------------------------
    def advance(self, dt: float) -> None:
        """Step simulated time forward by dt seconds (negative steps are ignored)."""
        step = max(0.0, float(dt))
        self._mono += step
        if self._utc is not None:
            self._utc += step
        self._notify()

    def observe_utc(self, epoch: float) -> None:
        """Follow message time: advance by max(0, epoch - last_epoch) and set UTC to epoch."""
        epoch = float(epoch)
        if self._utc is not None:
            self._mono += max(0.0, epoch - self._utc)
        self._utc = epoch
        self._notify()

    # -- Clock protocol ----------------------------------------------------------------------
    def monotonic(self) -> float:
        return self._mono

    def wall(self) -> float:
        return self._utc if self._utc is not None else self._mono

    def now_utc(self) -> datetime | None:
        if self._utc is None:
            return None
        return datetime.fromtimestamp(self._utc, tz=UTC)

    @property
    def time_valid(self) -> bool:
        return self._utc is not None

    def status(self) -> dict:
        valid = self.time_valid
        return {
            "kind": self.kind,
            "time_valid": valid,
            "routing_time_gate": "ok" if valid else "blocked",
            "utc": _iso(self._utc),
            "sim_mono": self._mono,
        }

    def _condition(self) -> asyncio.Condition:
        loop = asyncio.get_running_loop()
        if self._cond is None or self._cond_loop is not loop:
            self._cond = asyncio.Condition()
            self._cond_loop = loop
        return self._cond

    def _notify(self) -> None:
        cond, loop = self._cond, self._cond_loop
        if cond is None or loop is None or loop.is_closed():
            return

        async def _wake() -> None:
            async with cond:
                cond.notify_all()

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_wake())
        else:
            asyncio.run_coroutine_threadsafe(_wake(), loop)

    async def sleep_until(self, t_mono: float) -> None:
        cond = self._condition()
        async with cond:
            await cond.wait_for(lambda: self._mono >= t_mono)


def parse_gps_time(text: object) -> datetime | None:
    """ISO8601 with an explicit offset ("...Z" accepted on 3.11+) -> aware datetime, else None."""
    if not isinstance(text, str) or len(text) > 64:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(UTC)


GPS_YEARS_SPAN = 50


def default_gps_years() -> tuple[int, int]:
    """(build year, build year + 50): the lower bound rejects GPS week-rollover dates (~19.6 years
    in the past); the upper bound is far enough that a shipped image never expires."""
    from jabuka import __build_year__

    return (__build_year__, __build_year__ + GPS_YEARS_SPAN)


class GpsClock:
    """UTC disciplined by GPS fixes (RESEARCH Pattern 8), monotonic for everything else.

    on_tpv(tpv, t_mono) accepts a fix only with mode >= 2, a parseable time and a year in
    ``years`` (rollover guard, default default_gps_years()); anything else returns False and never
    counts. Consecutive accepted fixes are consistent when |dGPS - dMono| < tolerance_s. After
    ``required_fixes`` consistent fixes the clock is synced and anchored:
    now_utc = ref_utc + (mono() - ref_mono).

    While synced, a fix consistent with the anchor re-anchors it. An inconsistent fix (GPS time
    jump) is counted in ``jumps`` and starts a candidate timeline; the old anchor is kept
    (holdover) until the candidate itself reaches required_fixes, then the clock re-anchors.
    GPS loss keeps time valid in holdover (holdover_s grows). Ages elsewhere are monotonic
    differences, so a jump can never make them negative.
    """

    kind = "gps"

    def __init__(
        self,
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        required_fixes: int = 3,
        tolerance_s: float = 0.5,
        years: tuple[int, int] | None = None,
    ) -> None:
        self._mono = mono
        self._wall = wall
        self.required_fixes = max(1, int(required_fixes))
        self.tolerance_s = float(tolerance_s)
        self.years = years if years is not None else default_gps_years()
        self._synced = False
        self._ref_utc: float | None = None
        self._ref_mono: float | None = None
        self._prev: tuple[float, float] | None = None  # (utc, mono) of the last accepted fix
        self._run = 0  # consecutive consistent fixes on the current (candidate) timeline
        self._off_anchor = False  # inside a jump candidate
        self._last_fix_mono: float | None = None
        self.jumps = 0
        self.fixes_accepted = 0
        self.fixes_rejected = 0

    # -- discipline --------------------------------------------------------------------------
    def _sane_epoch(self, tpv: dict) -> float | None:
        mode = tpv.get("mode")
        if isinstance(mode, bool) or not isinstance(mode, int) or mode < 2:
            return None
        dt = parse_gps_time(tpv.get("time"))
        if dt is None or not (self.years[0] <= dt.year <= self.years[1]):
            return None
        return dt.timestamp()

    def on_tpv(self, tpv: dict, t_mono: float) -> bool:
        """Feed one gpsd TPV received at t_mono (this clock's monotonic). True if accepted."""
        utc = self._sane_epoch(tpv) if isinstance(tpv, dict) else None
        if utc is None:
            self.fixes_rejected += 1
            return False
        self.fixes_accepted += 1
        tol = self.tolerance_s
        if self._prev is not None:
            pu, pm = self._prev
            consistent = abs((utc - pu) - (t_mono - pm)) < tol
            self._run = self._run + 1 if consistent else 1
        else:
            self._run = 1
        self._prev = (utc, t_mono)
        self._last_fix_mono = t_mono

        if not self._synced:
            if self._run >= self.required_fixes:
                self._anchor(utc, t_mono)
                self._synced = True
            return True

        assert self._ref_utc is not None and self._ref_mono is not None
        predicted = self._ref_utc + (t_mono - self._ref_mono)
        if abs(utc - predicted) < tol:
            self._anchor(utc, t_mono)
            self._off_anchor = False
        else:
            if not self._off_anchor:
                self.jumps += 1
                self._off_anchor = True
            if self._run >= self.required_fixes:
                self._anchor(utc, t_mono)  # the new timeline proved itself
                self._off_anchor = False
        return True

    def _anchor(self, utc: float, t_mono: float) -> None:
        self._ref_utc = utc
        self._ref_mono = t_mono

    # -- Clock protocol ----------------------------------------------------------------------
    def monotonic(self) -> float:
        return self._mono()

    def wall(self) -> float:
        """System wall clock: log metadata and the system_clock diagnostic only."""
        return self._wall()

    def _utc_epoch(self) -> float | None:
        if not self._synced or self._ref_utc is None or self._ref_mono is None:
            return None
        return self._ref_utc + (self._mono() - self._ref_mono)

    def now_utc(self) -> datetime | None:
        epoch = self._utc_epoch()
        return None if epoch is None else datetime.fromtimestamp(epoch, tz=UTC)

    @property
    def time_valid(self) -> bool:
        return self._synced

    def status(self) -> dict:
        now = self._mono()
        utc = self._utc_epoch()
        wall = self._wall()
        if utc is None:
            system_clock, offset = "unknown", None
        else:
            offset = wall - utc
            system_clock = "synced" if abs(offset) < 1.0 else "unsynced"
        holdover = None
        if self._synced and self._ref_mono is not None:
            holdover = round(max(0.0, now - self._ref_mono), 3)
        last_age = None
        if self._last_fix_mono is not None:
            last_age = round(max(0.0, now - self._last_fix_mono), 3)
        valid = self._synced
        return {
            "kind": self.kind,
            "time_valid": valid,
            "routing_time_gate": "ok" if valid else "blocked",
            "utc": _iso(utc),
            "synced": valid,
            "consistent_fixes": self._run,
            "required_fixes": self.required_fixes,
            "holdover_s": holdover,
            "jumps": self.jumps,
            "last_fix_age_s": last_age,
            "fixes_accepted": self.fixes_accepted,
            "fixes_rejected": self.fixes_rejected,
            "system_clock": system_clock,
            "system_offset_s": None if offset is None else round(offset, 3),
            "system_utc": _iso(wall),
        }

    async def sleep_until(self, t_mono: float) -> None:
        delay = t_mono - self._mono()
        if delay > 0:
            await asyncio.sleep(delay)


def make_clock(kind: str, *, gps_years: tuple[int, int] | None = None) -> Clock:
    """Factory used by the CLIs: "system" | "sim" | "gps" (gps_years: accepted fix years,
    default default_gps_years())."""
    if kind == "system":
        return SystemClock()
    if kind == "sim":
        return SimClock()
    if kind == "gps":
        return GpsClock(years=gps_years)
    raise ValueError(f"unknown clock kind: {kind!r}")
