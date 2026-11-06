"""GpsClock: time-valid gate, rollover/no-fix rejection, holdover, jumps, system clock check; plus
the core E2E with --clock gps behind FakeGpsd."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import GpsClock, make_clock

T0 = datetime(2026, 11, 13, 19, 0, 0, tzinfo=UTC).timestamp()  # 1794596400.0


class Fake:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def tpv(epoch: float, mode: int = 3) -> dict:
    return {"class": "TPV", "mode": mode, "time": iso(epoch)}


def make(wall_offset: float = 0.0) -> tuple[GpsClock, Fake, Fake]:
    mono = Fake(1000.0)
    wall = Fake(T0 + wall_offset)
    return GpsClock(mono=mono, wall=wall), mono, wall


def feed_consistent(clk: GpsClock, mono: Fake, wall: Fake, start: float, n: int) -> float:
    """n fixes 1 s apart on the GPS timeline starting at start; returns the last fix time."""
    t = start
    for i in range(n):
        if i:
            mono.t += 1.0
            wall.t += 1.0
            t += 1.0
        assert clk.on_tpv(tpv(t), mono.t) is True
    return t


def test_make_clock_gps() -> None:
    assert isinstance(make_clock("gps"), GpsClock)
    assert make_clock("gps").kind == "gps"


def test_unsynced_until_three_consistent_fixes() -> None:
    clk, mono, wall = make()
    s = clk.status()
    assert s["time_valid"] is False and s["routing_time_gate"] == "blocked"
    assert s["utc"] is None and clk.now_utc() is None
    assert s["system_clock"] == "unknown"
    feed_consistent(clk, mono, wall, T0, 2)
    s = clk.status()
    assert s["time_valid"] is False
    assert s["routing_time_gate"] == "blocked"
    assert s["consistent_fixes"] == 2
    mono.t += 1.0
    wall.t += 1.0
    assert clk.on_tpv(tpv(T0 + 2.0), mono.t) is True
    s = clk.status()
    assert s["time_valid"] is True
    assert s["routing_time_gate"] == "ok"
    assert s["synced"] is True
    mono.t += 0.25
    assert clk.now_utc() == datetime.fromtimestamp(T0 + 2.25, tz=UTC)
    assert s["utc"] == "2026-11-13T19:00:02Z" or s["utc"].startswith("2026-11-13T19:00:02")


@pytest.mark.parametrize(
    "bad",
    [
        {"class": "TPV", "mode": 1, "time": iso(T0)},  # no fix, time present but invalid
        {"class": "TPV", "mode": 0, "time": iso(T0)},
        {"class": "TPV", "mode": 3},  # no time
        {"class": "TPV", "mode": 3, "time": "2019-04-07T00:00:00.000Z"},  # week rollover
        {"class": "TPV", "mode": 3, "time": "2045-01-01T00:00:00.000Z"},
        {"class": "TPV", "mode": 3, "time": "not a time"},
        {"class": "TPV", "mode": 3, "time": "2026-11-13T19:00:00"},  # no timezone
        {"class": "TPV", "mode": True, "time": iso(T0)},
    ],
)
def test_rejected_fixes_never_count(bad: dict) -> None:
    clk, mono, wall = make()
    feed_consistent(clk, mono, wall, T0, 2)
    mono.t += 1.0
    assert clk.on_tpv(bad, mono.t) is False
    assert clk.status()["time_valid"] is False
    assert clk.status()["consistent_fixes"] == 2


def test_rejected_only_never_syncs() -> None:
    clk, mono, _ = make()
    for i in range(10):
        mono.t += 1.0
        assert clk.on_tpv({"class": "TPV", "mode": 1, "time": iso(T0 + i)}, mono.t) is False
    assert clk.status()["routing_time_gate"] == "blocked"


def test_inconsistent_fixes_restart_the_count() -> None:
    clk, mono, wall = make()
    feed_consistent(clk, mono, wall, T0, 2)
    mono.t += 1.0
    assert clk.on_tpv(tpv(T0 + 5.0), mono.t) is True  # 4 s off the expected timeline
    assert clk.status()["consistent_fixes"] == 1
    assert clk.status()["time_valid"] is False


def test_holdover_after_gps_loss() -> None:
    clk, mono, wall = make()
    last = feed_consistent(clk, mono, wall, T0, 3)
    mono.t += 30.0
    wall.t += 30.0
    s = clk.status()
    assert s["time_valid"] is True
    assert s["routing_time_gate"] == "ok"
    assert s["holdover_s"] == pytest.approx(30.0, abs=1e-6)
    assert s["last_fix_age_s"] == pytest.approx(30.0, abs=1e-6)
    assert clk.now_utc().timestamp() == pytest.approx(last + 30.0, abs=1e-6)
    # a fix consistent with the held-over timeline re-anchors
    assert clk.on_tpv(tpv(last + 30.0), mono.t) is True
    assert clk.status()["holdover_s"] == pytest.approx(0.0, abs=1e-6)
    assert clk.status()["jumps"] == 0


def test_time_jump_counted_held_then_reanchored() -> None:
    clk, mono, wall = make()
    last = feed_consistent(clk, mono, wall, T0, 3)
    anchor_before = clk.now_utc()
    mono.t += 1.0
    assert clk.on_tpv(tpv(last + 1.0 + 3600.0), mono.t) is True
    s = clk.status()
    assert s["jumps"] == 1
    assert s["time_valid"] is True  # held over on the old anchor
    assert clk.now_utc().timestamp() == pytest.approx(anchor_before.timestamp() + 1.0)
    # core ages are monotonic differences: never negative whatever GPS says
    t_rx = mono.t
    mono.t += 1.0
    assert mono.t - t_rx >= 0
    assert clk.on_tpv(tpv(last + 2.0 + 3600.0), mono.t) is True
    assert clk.now_utc().timestamp() == pytest.approx(last + 2.0)  # still the old anchor
    mono.t += 1.0
    assert clk.on_tpv(tpv(last + 3.0 + 3600.0), mono.t) is True
    s = clk.status()
    assert s["jumps"] == 1
    assert clk.now_utc().timestamp() == pytest.approx(last + 3.0 + 3600.0)  # re-anchored
    assert s["holdover_s"] == pytest.approx(0.0, abs=1e-6)


def test_system_clock_check() -> None:
    clk, mono, wall = make(wall_offset=0.3)
    feed_consistent(clk, mono, wall, T0, 3)
    s = clk.status()
    assert s["system_clock"] == "synced"
    assert s["system_offset_s"] == pytest.approx(0.3, abs=1e-3)
    clk2, mono2, wall2 = make(wall_offset=-7200.0)  # stale fake-hwclock, chrony not stepped yet
    feed_consistent(clk2, mono2, wall2, T0, 3)
    s2 = clk2.status()
    assert s2["system_clock"] == "unsynced"
    assert s2["system_offset_s"] == pytest.approx(-7200.0, abs=1e-3)
    assert s2["time_valid"] is True  # validity comes from GPS, not the system clock


def test_status_keys() -> None:
    clk, _, _ = make()
    keys = {
        "kind",
        "time_valid",
        "routing_time_gate",
        "utc",
        "synced",
        "consistent_fixes",
        "holdover_s",
        "jumps",
        "last_fix_age_s",
        "system_clock",
        "system_offset_s",
    }
    assert keys <= set(clk.status())
    assert clk.status()["kind"] == "gps"


async def test_sleep_until_uses_injected_mono() -> None:
    clk = GpsClock()
    t0 = time.monotonic()
    await clk.sleep_until(clk.monotonic() + 0.05)
    assert time.monotonic() - t0 >= 0.04


# -- core E2E ----------------------------------------------------------------------------------
def test_core_gps_clock_gate(
    tmp_data_dir, free_udp_port, fake_gpsd, make_core, core_app, now_tpv, wait_until
) -> None:
    fg = fake_gpsd()
    ctx = make_core(tmp_data_dir, free_udp_port, gpsd=f"127.0.0.1:{fg.port}", clock="gps")
    with TestClient(core_app(ctx)) as client:

        def clock() -> dict:
            return client.get("/api/state").json()["clock"]

        assert clock()["kind"] == "gps"
        assert clock()["routing_time_gate"] == "blocked"
        wait_until(lambda: fg.watching() > 0, timeout=5)
        fg.push(now_tpv(mode=1))  # no-fix TPV never syncs
        fg.push(now_tpv())
        time.sleep(1.0)
        fg.push(now_tpv())
        wait_until(lambda: clock()["consistent_fixes"] == 2, timeout=5)
        c = clock()
        assert c["time_valid"] is False and c["routing_time_gate"] == "blocked"
        time.sleep(1.0)
        fg.push(now_tpv())
        c = wait_until(lambda: (c := clock())["routing_time_gate"] == "ok" and c, timeout=5)
        assert c["time_valid"] is True
        assert c["system_clock"] == "synced"  # the laptop clock is NTP-disciplined
        rows = [r for r in client.get("/api/state").json()["values"] if r["src"] == "gpsd"]
        assert rows and all(r["age_s"] >= 0 for r in rows)
