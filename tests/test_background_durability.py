"""G-4-R05: in background mode (jabuka-core, jabuka-ingest-fastnet) every fsync runs on the
durability thread (atomicio.WORKER_NAME), so an SD stall never freezes the event loop."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jabuka.common import atomicio
from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.ingest.rawlog import RotatingAppendLog, iter_log_lines

T0 = datetime(2026, 11, 12, 9, 30, tzinfo=UTC).timestamp()
PROMPT_S = 0.5


class Stall:
    """os.fsync recorder; blocks on the durability thread until released."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.release = threading.Event()

    def worker_calls(self) -> int:
        return sum(1 for n in self.names if n == atomicio.WORKER_NAME)

    def main_calls(self) -> int:
        main = threading.main_thread().name
        return sum(1 for n in self.names if n == main)


@pytest.fixture
def stall(monkeypatch: pytest.MonkeyPatch):
    s = Stall()
    real = os.fsync

    def recorder(fd: int) -> None:
        name = threading.current_thread().name
        s.names.append(name)
        if name == atomicio.WORKER_NAME:
            s.release.wait(15.0)
        real(fd)

    monkeypatch.setattr(os, "fsync", recorder)
    yield s
    s.release.set()


@pytest.fixture
def background(stall):
    """Background mode for one test. Teardown releases the stall first, then drains and switches
    the mode off, so later tests in this process stay synchronous."""
    atomicio.enable_background()
    yield
    stall.release.set()
    assert atomicio.disable_background(timeout_s=10.0) is True


def _wait_for(pred, timeout: float = 5.0) -> None:
    """The worker may not have been scheduled yet (GIL switch interval): poll briefly."""
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not met"
        time.sleep(0.01)


class FakeMono:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _log(tmp_path: Path, mono: FakeMono, **kw) -> RotatingAppendLog:
    return RotatingAppendLog(tmp_path, "t", mono=mono, wall=lambda: T0, **kw)


def test_tracer_a_stalled_fsync_never_blocks_the_core_tick(
    background, stall: Stall, tmp_data_dir: Path, free_udp_port: int
) -> None:
    clock = SimClock(start_utc=T0)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port)
    try:
        durations = []
        for _ in range(15):
            clock.advance(1.0)
            t = time.perf_counter()
            ctx.tick_once()
            durations.append(time.perf_counter() - t)
        assert max(durations) < PROMPT_S, durations
        _wait_for(lambda: stall.worker_calls() >= 1)
        assert stall.main_calls() == 0, stall.names
        stall.release.set()
        assert atomicio.drain(10.0) is True
        assert ctx.derived is not None and ctx.derived.log.current_path is not None
        assert len(list(iter_log_lines(ctx.derived.log.current_path))) >= 15
    finally:
        stall.release.set()
        ctx.close_logs()


def test_cadence_fsync_is_skipped_while_one_is_in_flight(
    background, stall: Stall, tmp_path: Path
) -> None:
    mono = FakeMono()
    lg = _log(tmp_path, mono)
    try:
        lg.write_line("one")
        mono.t += 11
        lg.maybe_flush()
        assert stall.worker_calls() <= 1
        assert atomicio.background_status()["pending"] == 1
        lg.write_line("two")
        mono.t += 11
        lg.maybe_flush()
        # the first fsync is stalled: no second job queued
        assert atomicio.background_status()["pending"] == 1
        stall.release.set()
        assert atomicio.drain(10.0) is True
        assert stall.worker_calls() == 1
        lg.write_line("three")
        mono.t += 11
        lg.maybe_flush()
        assert atomicio.drain(10.0) is True
        assert stall.worker_calls() == 2
        assert stall.main_calls() == 0
    finally:
        stall.release.set()
        lg.close()


def test_event_line_is_on_disk_before_its_fsync_completes(
    background, stall: Stall, tmp_path: Path
) -> None:
    mono = FakeMono()
    lg = _log(tmp_path, mono, suffix=".jsonl")
    try:
        t = time.perf_counter()
        lg.write_json({"type": "event", "n": 1}, fsync_now=True)
        assert time.perf_counter() - t < PROMPT_S
        assert lg.current_path is not None
        assert b'"n":1' in lg.current_path.read_bytes()
        assert atomicio.background_status()["pending"] == 1  # its fsync is still stalled
        assert stall.main_calls() == 0
    finally:
        stall.release.set()
        lg.close()


def test_rotation_closes_at_once_and_fsyncs_on_the_worker(
    background, stall: Stall, tmp_path: Path
) -> None:
    mono = FakeMono()
    lg = _log(tmp_path, mono, max_bytes=64)
    try:
        lg.write_line("a" * 40)
        first = lg.current_path
        t = time.perf_counter()
        lg.write_line("b" * 40)  # past max_bytes: rotates (close + fsync of the first file)
        assert time.perf_counter() - t < PROMPT_S
        assert lg.current_path != first
        assert lg.rotations == 1
        assert stall.main_calls() == 0
        stall.release.set()
        assert atomicio.drain(10.0) is True
        assert stall.worker_calls() >= 1
        assert atomicio.background_status()["errors"] == 0
    finally:
        stall.release.set()
        lg.close()


def test_sync_mode_is_unchanged(stall: Stall, tmp_path: Path) -> None:
    stall.release.set()
    assert atomicio.background_enabled() is False
    assert atomicio.background_status()["pending"] == 0
    mono = FakeMono()
    lg = _log(tmp_path, mono)
    try:
        lg.write_line("one")
        mono.t += 11
        lg.maybe_flush()
        assert stall.main_calls() == 1
        lg.write_json({"n": 1}, fsync_now=True)
        assert stall.main_calls() == 2
        assert stall.worker_calls() == 0
    finally:
        lg.close()
