"""Routing never freezes the live display (ROUT-02, T-03-05-03): with the real 1 Hz tick loop on a
real-time clock and the real worker routing the whole Course A five times in a row, every interval
between consecutive ticks stays within 1 s +- 200 ms."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from jabuka.common.clock import SystemClock


class RealTimeGpsClock(SystemClock):
    """Real monotonic time, UTC valid (routing gate ok) and mapped into the fixture wind."""

    kind = "test"

    def __init__(self, utc0: float) -> None:
        self._m0 = time.monotonic()
        self._utc0 = utc0

    def wall(self) -> float:
        return self._utc0 + (time.monotonic() - self._m0)

    def now_utc(self) -> datetime | None:
        return datetime.fromtimestamp(self.wall(), UTC)

    @property
    def time_valid(self) -> bool:
        return True

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "time_valid": True,
            "routing_time_gate": "ok",
            "utc": self.now_utc().isoformat().replace("+00:00", "Z"),
        }


def test_tick_cadence_holds_while_the_worker_routes(routing_core, rh) -> None:
    clock = RealTimeGpsClock(rh.T_START)
    core = routing_core(clock=clock, tick_loop=True)
    ctx = core.ctx
    lat, lon = rh.boat_near_plic(2.0)
    stamps: list[float] = []
    orig = ctx.tick_once

    def stamped_tick() -> None:
        stamps.append(time.monotonic())
        core.sail(lat, lon, 0.0)
        orig()

    ctx.tick_once = stamped_tick  # type: ignore[method-assign]
    deadline = time.monotonic() + 120.0
    target = 5
    while core.router.version < target:
        assert time.monotonic() < deadline, f"only {core.router.version} routes in 120 s"
        v = core.router.version
        if v >= 1 and not core.call(core.router.busy):
            core.call(core.router.force, "test")
        while core.router.version == v and time.monotonic() < deadline:
            time.sleep(0.05)
    time.sleep(1.2)  # one more tick after the last adoption
    assert core.router.health()["jobs_submitted"] >= target
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert len(gaps) >= 3, stamps
    bad = [round(g, 3) for g in gaps if abs(g - 1.0) > 0.2]
    assert not bad, f"tick intervals off by more than 200 ms: {bad} (all {gaps})"
