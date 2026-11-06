"""Injected clock: the ONLY module in jabuka.common / jabuka.core allowed to read the wall clock
or the monotonic clock (enforced by tests/test_no_wallclock.py).

- SystemClock: process clocks. It cannot vouch for UTC (the Pi has no RTC and no internet), so
  time_valid is False and routing_time_gate is "blocked". GpsClock (plan 01-03) provides validity.
- SimClock: a simulated monotonic clock that only moves forward, driven by advance(dt) in tests
  and by observe_utc(t_sim) from replay/sim messages.
"""

from __future__ import annotations

import asyncio
import time
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


def make_clock(kind: str) -> Clock:
    """Factory used by the CLIs: "system" | "sim" (plan 01-03 adds "gps")."""
    if kind == "system":
        return SystemClock()
    if kind == "sim":
        return SimClock()
    raise ValueError(f"unknown clock kind: {kind!r}")
