"""Shared fixtures for the plan 01-01 suite. Wave-2 plans add their own conftest.py in
subdirectories (tests/bus, tests/gps, ...) and must not edit this file."""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from jabuka.common.clock import SimClock
from jabuka.ingest.fastnet_framing import load_capture

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FASTNET_FIXTURES = FIXTURES_DIR / "fastnet"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def capture_bytes() -> Callable[[str], bytes]:
    """capture_bytes("example2_fastnet_data.txt") -> the decoded byte stream."""

    def _load(name: str) -> bytes:
        return load_capture(FASTNET_FIXTURES / name)

    return _load


def _free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def free_udp_port() -> int:
    return _free_port(socket.SOCK_DGRAM)


@pytest.fixture
def free_tcp_port() -> int:
    return _free_port(socket.SOCK_STREAM)


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def sim_clock() -> Callable[..., SimClock]:
    """Factory: sim_clock() or sim_clock(start_utc=1762470000.0)."""

    def _make(start_utc: float | None = None) -> SimClock:
        return SimClock(start_utc=start_utc)

    return _make


def _wait_until(pred: Callable[[], object], timeout: float = 10.0, interval: float = 0.05):
    """Poll pred() until truthy (returns its value) or raise AssertionError on timeout."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = pred()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last={last!r})")


@pytest.fixture
def wait_until() -> Callable[..., object]:
    """wait_until(pred, timeout=10.0): poll until pred() is truthy, return its value."""
    return _wait_until


@pytest.fixture
def process_has_open() -> Callable[[int, str], bool]:
    """process_has_open(pid, path): the process holds an fd on path (Linux /proc)."""
    return _process_has_open


def _process_has_open(pid: int, path: str) -> bool:
    """True when process pid holds an fd on path (Linux /proc)."""
    target = os.path.realpath(path)
    fd_dir = Path(f"/proc/{pid}/fd")
    try:
        for fd in fd_dir.iterdir():
            try:
                if os.path.realpath(os.readlink(fd)) == target:
                    return True
            except OSError:
                continue
    except OSError:
        return False
    return False
