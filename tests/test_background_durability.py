"""G-4-R05: in background mode (jabuka-core, jabuka-ingest-fastnet) every fsync runs on the
durability thread (atomicio.WORKER_NAME), so an SD stall never freezes the event loop."""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common import atomicio
from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
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


_STALLS: list[Stall] = []  # live stalls, released by the background teardown before it drains


@pytest.fixture
def stall(monkeypatch: pytest.MonkeyPatch):
    s = Stall()
    _STALLS.append(s)
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
    _STALLS.remove(s)


@pytest.fixture
def background():
    """Background mode for one test. Teardown releases the stall first, then drains and switches
    the mode off, so later tests in this process stay synchronous."""
    atomicio.enable_background()
    yield
    for s in _STALLS:
        s.release.set()
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
    errors0 = atomicio.background_status()["errors"]  # process-wide counter
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
        assert atomicio.background_status()["errors"] == errors0
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


# -- Task 2: atomic writes, entry points, diag ----------------------------------------------------
def _numbered_temps(directory: Path, name: str) -> list[str]:
    prefix = f".{name}."
    return sorted(
        p.name
        for p in directory.iterdir()
        if p.name.startswith(prefix)
        and p.name.endswith(".tmp")
        and p.name[len(prefix) : -len(".tmp")].isdigit()
    )


def test_atomic_writes_land_in_order_with_bak_and_no_temp_left(background, tmp_path: Path) -> None:
    errors0 = atomicio.background_status()["errors"]  # process-wide counter
    p = tmp_path / "state.json"
    for k in range(1, 6):
        atomicio.atomic_write_json(p, {"v": k})
    assert atomicio.drain(10.0) is True
    assert json.loads(p.read_text()) == {"v": 5}
    assert json.loads((tmp_path / "state.json.bak").read_text()) == {"v": 4}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []
    assert atomicio.background_status()["errors"] == errors0


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_atomic_write_error_is_raised_on_the_caller(background, tmp_path: Path) -> None:
    d = tmp_path / "ro"
    d.mkdir()
    p = d / "state.json"
    atomicio.atomic_write_json(p, {"v": 1})
    assert atomicio.drain(10.0) is True
    d.chmod(0o500)
    try:
        with pytest.raises(OSError):
            atomicio.atomic_write_json(p, {"v": 2})
        assert json.loads(p.read_text()) == {"v": 1}
        assert list(d.glob(".state.json*.tmp")) == []
    finally:
        d.chmod(0o700)
    assert atomicio.background_status()["pending"] == 0


def test_background_failure_is_logged_and_counted(
    background, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "state.json"
    atomicio.atomic_write_json(p, {"v": 1})
    assert atomicio.drain(10.0) is True
    errors0 = atomicio.background_status()["errors"]
    real = os.replace

    def replace(src, dst):
        if threading.current_thread().name == atomicio.WORKER_NAME:
            raise OSError(5, "EIO")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    atomicio.atomic_write_json(p, {"v": 2})  # the temp write succeeds: no error here
    assert atomicio.drain(10.0) is True
    st = atomicio.background_status()
    assert st["errors"] == errors0 + 1
    assert "EIO" in (st["last_error"] or "")
    assert json.loads(p.read_text()) == {"v": 1}
    assert list(tmp_path.glob(".state.json*.tmp")) == []


def test_api_writes_return_promptly_under_a_stalled_fsync(
    background, stall: Stall, tmp_data_dir: Path, free_udp_port: int
) -> None:
    ctx = CoreContext.create(SimClock(start_utc=T0), tmp_data_dir, udp_port=free_udp_port)
    client = TestClient(create_app(ctx))
    try:
        v = client.get("/api/course").json()["version"]
        sv = client.get("/api/settings").json()["version"]
        calls = [
            ("post", "/api/course/next", {"base_version": v}, 200),
            ("put", "/api/settings", {"patch": {"efficiency": 0.9}, "base_version": sv}, 200),
            ("post", "/api/wind/manual", {"twd": 200, "tws_kn": 12, "ref": "T"}, 200),
            ("post", "/api/event", {"label": "stall"}, 201),
        ]
        for method, url, body, code in calls:
            t = time.perf_counter()
            r = getattr(client, method)(url, json=body)
            dt = time.perf_counter() - t
            assert r.status_code == code, (url, r.text)
            assert dt < PROMPT_S, (url, dt)
        assert all(n == atomicio.WORKER_NAME for n in stall.names), stall.names
        stall.release.set()
        assert atomicio.drain(10.0) is True
        course = atomicio.load_json_with_bak(tmp_data_dir / "course.json", None)
        assert course is not None and course["version"] == v + 1
        settings = atomicio.load_json_with_bak(tmp_data_dir / "settings.json", None)
        assert settings is not None and settings["settings"]["efficiency"] == 0.9
    finally:
        stall.release.set()
        client.close()
        ctx.close_logs()


def test_orphaned_background_temps_are_swept_once_per_file(
    background, stall: Stall, tmp_path: Path
) -> None:
    errors0 = atomicio.background_status()["errors"]  # process-wide counter
    for name in (".state.json.7.tmp", ".state.json.12.tmp", ".other.json.3.tmp"):
        (tmp_path / name).write_bytes(b"orphan")
    (tmp_path / ".state.json.bak.tmp").write_bytes(b"bak")
    p = tmp_path / "state.json"
    atomicio.atomic_write_json(p, {"v": 1})
    # both orphans are gone at once; the one numbered temp left is this write's own (in flight;
    # the counter is process-wide, so it may reuse an orphan's number)
    left = _numbered_temps(tmp_path, "state.json")
    assert len(left) == 1, left
    assert (tmp_path / left[0]).read_bytes() == b'{"v":1}'
    assert (tmp_path / ".other.json.3.tmp").exists()
    _wait_for(lambda: stall.worker_calls() >= 1)  # first write's fsync now stalled
    atomicio.atomic_write_json(p, {"v": 2})
    assert len(_numbered_temps(tmp_path, "state.json")) == 2  # in-flight temps never swept
    assert (tmp_path / ".state.json.bak.tmp").exists()
    stall.release.set()
    assert atomicio.drain(10.0) is True
    assert json.loads(p.read_text()) == {"v": 2}
    assert json.loads((tmp_path / "state.json.bak").read_text()) == {"v": 1}
    assert atomicio.background_status()["errors"] == errors0
    assert _numbered_temps(tmp_path, "state.json") == []


def test_diag_reports_background_writes(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx = CoreContext.create(SimClock(start_utc=T0), tmp_data_dir, udp_port=free_udp_port)
    try:
        core = ctx.diag_message()["core"]
        assert isinstance(core["bg_write_pending"], int)
        assert isinstance(core["bg_write_errors"], int)
    finally:
        ctx.close_logs()


def test_entry_points_enable_and_drain_the_durability_thread() -> None:
    from jabuka.core import main as core_main
    from jabuka.ingest import fastnet_main

    for fn in (core_main.serve, fastnet_main._run):
        src = inspect.getsource(fn)
        assert "atomicio.enable_background()" in src, fn
        assert "atomicio.disable_background(" in src, fn
