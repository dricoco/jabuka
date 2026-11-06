"""DATA-07 logging: rotation, flush/fsync cadence, torn lines, derived 1 Hz, bus log.

Disk space (retention) is covered by tests/test_retention.py."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jabuka.common import messages
from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.ingest import rawlog as rawlog_mod
from jabuka.ingest.rawlog import RotatingAppendLog, iter_log_lines

H10 = datetime(2026, 11, 12, 10, 59, 58, tzinfo=UTC).timestamp()


class FakeTime:
    def __init__(self, mono: float = 0.0, wall: float = H10) -> None:
        self.m = mono
        self.w = wall

    def mono(self) -> float:
        return self.m

    def wall(self) -> float:
        return self.w

    def step(self, dt: float) -> None:
        self.m += dt
        self.w += dt


def _log(tmp_path: Path, t: FakeTime, **kw) -> RotatingAppendLog:
    return RotatingAppendLog(tmp_path, "fastnet", mono=t.mono, wall=t.wall, **kw)


def test_rotation_by_utc_hour(tmp_path: Path) -> None:
    t = FakeTime()
    lg = _log(tmp_path, t)
    lg.write_chunk(b"\x01\x02")
    first = lg.current_path
    assert first is not None and "-20261112T10Z-" in first.name
    t.step(5.0)  # crosses 11:00:00 UTC
    lg.write_chunk(b"\x03")
    second = lg.current_path
    assert second is not None and "-20261112T11Z-" in second.name
    assert first != second
    lg.close()
    assert len(list(iter_log_lines(first))) == 1
    assert len(list(iter_log_lines(second))) == 1


def test_rotation_by_size(tmp_path: Path) -> None:
    t = FakeTime(wall=H10 - 1800)
    lg = _log(tmp_path, t, max_bytes=100)
    for _ in range(6):
        lg.write_chunk(b"\xaa" * 10)  # ~42 bytes per line
    lg.close()
    files = sorted(tmp_path.glob("fastnet-*.log"))
    assert len(files) >= 2
    assert files[0].name.endswith("-000.log")
    assert files[1].name.endswith("-001.log")
    for f in files:
        assert f.stat().st_size <= 100
    assert sum(len(list(iter_log_lines(f))) for f in files) == 6


def test_restart_same_hour_never_overwrites(tmp_path: Path) -> None:
    t = FakeTime(wall=H10 - 1800)
    a = _log(tmp_path, t)
    a.write_line("first run")
    a.close()
    first = a.current_path
    assert first is not None
    before = first.read_bytes()
    b = _log(tmp_path, t)
    b.write_line("second run")
    b.close()
    assert b.current_path != first
    assert first.read_bytes() == before
    assert b.current_path is not None and b.current_path.name.endswith("-001.log")


def test_file_name_format(tmp_path: Path) -> None:
    t = FakeTime(wall=H10 - 1800)
    lg = _log(tmp_path, t, suffix=".jsonl")
    lg.write_json({"a": 1})
    lg.close()
    name = lg.current_path.name
    prefix, hour, boot, seq = name[: -len(".jsonl")].split("-")
    assert prefix == "fastnet"
    assert hour == "20261112T10Z"
    assert len(boot) == 8
    assert seq == "000"


def test_flush_cadence(tmp_path: Path) -> None:
    t = FakeTime(wall=H10 - 1800)
    lg = _log(tmp_path, t, flush_s=1.0, fsync_s=10.0)
    lg.write_chunk(b"\x01")
    path = lg.current_path
    assert path is not None
    assert path.stat().st_size == 0  # buffered, not yet flushed
    t.step(0.5)
    lg.write_chunk(b"\x02")
    assert path.stat().st_size == 0
    t.step(0.6)  # 1.1 s since open
    lg.write_chunk(b"\x03")
    assert len(list(iter_log_lines(path))) == 3
    lg.close()


def test_fsync_cadence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = os.fsync
    monkeypatch.setattr(rawlog_mod.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    t = FakeTime(wall=H10 - 1800)
    lg = _log(tmp_path, t, flush_s=1.0, fsync_s=10.0)
    for _ in range(26):  # mono 0..25
        lg.write_chunk(b"\x01")
        t.step(1.0)
    assert len(calls) == 2  # at 10 s and 20 s
    lg.maybe_flush()
    lg.close()
    assert len(calls) == 3  # final fsync on close


def test_write_json_fsync_now(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = os.fsync
    monkeypatch.setattr(rawlog_mod.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    t = FakeTime(wall=H10 - 1800)
    lg = _log(tmp_path, t, suffix=".jsonl")
    lg.write_json({"type": "event", "label": "x"}, fsync_now=True)
    assert len(calls) == 1
    assert json.loads(next(iter_log_lines(lg.current_path)))["label"] == "x"
    lg.close()


def test_torn_last_line_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "torn.log"
    p.write_bytes(b"1.000 2.000 aa\n3.000 4.000 bb\n5.000 6.0")
    assert list(iter_log_lines(p)) == ["1.000 2.000 aa", "3.000 4.000 bb"]
    p.write_bytes(b"")
    assert list(iter_log_lines(p)) == []
    p.write_bytes(b"\xff\xfe broken utf8\n")
    assert len(list(iter_log_lines(p))) == 1


async def test_derived_log_1hz_under_simclock(tmp_data_dir: Path, free_udp_port: int) -> None:
    clock = SimClock(start_utc=H10 - 1800)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port)
    await ctx.startup()
    try:
        for _ in range(10):
            clock.advance(1.0)
            for _ in range(5):
                await asyncio.sleep(0.005)
    finally:
        await ctx.shutdown()
    files = sorted((tmp_data_dir / "logs" / "derived").glob("derived-*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(x) for x in iter_log_lines(files[0])]
    assert len(lines) == 10
    for rec in lines:
        for key in ("t_mono", "t_wall", "utc", "values", "health", "clock"):
            assert key in rec
    assert [rec["t_mono"] for rec in lines] == [float(i) for i in range(1, 11)]


async def test_bus_log_records_accepted_datagrams(tmp_data_dir: Path, free_udp_port: int) -> None:
    clock = SimClock(start_utc=H10 - 1800)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port, bus_log=True)
    await ctx.startup()
    try:
        good = messages.encode(
            messages.delta_message(
                "test", [{"path": "navigation.heading", "value": 1.0, "unit": "rad"}], 1.0, 2.0
            )
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"not json", ("127.0.0.1", free_udp_port))
            s.sendto(good, ("127.0.0.1", free_udp_port))
            s.sendto(good, ("127.0.0.1", free_udp_port))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if ctx.stats["udp_rx"] >= 2:
                break
    finally:
        await ctx.shutdown()
    assert ctx.stats["udp_rx"] == 2
    assert ctx.stats["udp_rejected"] == 1
    files = sorted((tmp_data_dir / "logs" / "bus").glob("bus-*.log"))
    assert files
    lines = [ln for f in files for ln in iter_log_lines(f)]
    assert len(lines) == 2
    t_mono, t_wall, payload = lines[0].split(" ", 2)
    float(t_mono), float(t_wall)
    assert json.loads(payload)["src"] == "test"


async def test_bus_log_is_off_by_default(tmp_data_dir: Path, free_udp_port: int) -> None:
    """CR-01: the bus log is ~8x the raw log; it is opt-in (--bus-log on)."""
    clock = SimClock(start_utc=H10 - 1800)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port)
    assert ctx.bus_log is None
    await ctx.startup()
    try:
        good = messages.encode(
            messages.delta_message("test", [{"path": "a.b", "value": 1.0}], 1.0, 2.0)
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(good, ("127.0.0.1", free_udp_port))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if ctx.stats["udp_rx"] >= 1:
                break
    finally:
        await ctx.shutdown()
    assert ctx.stats["udp_rx"] == 1
    assert not list((tmp_data_dir / "logs").glob("bus/bus-*.log"))


def test_core_cli_bus_log_and_budget_flags() -> None:
    from jabuka.core.main import build_arg_parser

    args = build_arg_parser().parse_args([])
    assert args.bus_log == "off"
    assert args.log_budget_gb is None
    args = build_arg_parser().parse_args(["--bus-log", "on", "--log-budget-gb", "6.5"])
    assert args.bus_log == "on" and args.log_budget_gb == 6.5
    for bad in ("0", "-1", "nan", "x"):
        with pytest.raises(SystemExit):
            build_arg_parser().parse_args(["--log-budget-gb", bad])


async def test_core_tick_runs_retention_and_reports_disk(
    tmp_data_dir: Path, free_udp_port: int
) -> None:
    """CR-01: derived/ is pruned by the core's retention pass; diag.core.disk reports it."""
    clock = SimClock(start_utc=H10 - 1800)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port, log_budget_bytes=10_000)
    old = tmp_data_dir / "logs" / "derived" / "derived-20261101T00Z-deadbeef-000.jsonl"
    old.write_bytes(b"{}\n" * 3000)  # 9 kB: over derived's 20 % share of 10 kB
    os.utime(old, (1_000_000, 1_000_000))
    await ctx.startup()
    try:
        clock.advance(1.0)
        for _ in range(20):
            await asyncio.sleep(0.005)
            if ctx.ticks >= 1:
                break
    finally:
        await ctx.shutdown()
    assert ctx.ticks >= 1
    assert not old.exists()
    disk = ctx.diag_message()["core"]["disk"]
    assert disk["budget_bytes"] == 10_000
    assert disk["deleted"] >= 1
    assert disk["free_bytes"] > 0
    assert set(disk["used_bytes"]) == {"raw", "bus", "derived", "gps", "events"}


async def test_log_write_failures_are_counted_in_diag(
    tmp_data_dir: Path, free_udp_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-06: derived and bus log failures used to go only to the volatile journal."""
    clock = SimClock(start_utc=H10 - 1800)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port, bus_log=True)

    def broken(*a, **k):
        raise OSError(30, "Read-only file system")

    assert ctx.derived is not None and ctx.bus_log is not None
    monkeypatch.setattr(ctx.derived, "write", broken)
    monkeypatch.setattr(ctx.bus_log, "write_line", broken)
    await ctx.startup()
    try:
        good = messages.encode(messages.delta_message("t", [{"path": "a.b", "value": 1.0}], 1, 2))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(good, ("127.0.0.1", free_udp_port))
        clock.advance(1.0)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if ctx.stats["udp_rx"] >= 1 and ctx.ticks >= 1:
                break
    finally:
        await ctx.shutdown()
    core = ctx.diag_message()["core"]
    assert core["derived_errors"] >= 1
    assert core["bus_log_errors"] == 1
    assert ctx.stats["udp_rx"] == 1  # state updates kept flowing
    for key in ("events_errors", "flush_errors", "handler_errors"):
        assert key in core
