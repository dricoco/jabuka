"""Fixtures for the bus-test kit suite (plan 01-02). tests/conftest.py is owned by plan 01-01."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jabuka.sim.pty_replay import PtyFeeder, replay_bytes


@dataclass
class RunningReplay:
    """A PtyFeeder plus a background thread that replays bytes once start() is called."""

    feeder: PtyFeeder
    _go: threading.Event = field(default_factory=threading.Event)
    _cancel: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None

    def start(self) -> None:
        self._go.set()

    @property
    def path(self) -> str:
        return str(self.feeder.link_path or self.feeder.slave_path)


@pytest.fixture
def probe_out_dir(tmp_path: Path) -> Path:
    return tmp_path / "probe-out"


@pytest.fixture
def running_replay() -> Iterator[Callable[..., Any]]:
    """running_replay(data, speed=20, link=None, **faults) -> context manager yielding a
    RunningReplay. Nothing is written until .start() (call it once the reader has opened the
    port: opening flushes pending input, exactly like the real device)."""

    @contextlib.contextmanager
    def _make(
        data: bytes, *, speed: float = 20.0, link: Path | None = None, **faults: Any
    ) -> Iterator[RunningReplay]:
        rr = RunningReplay(PtyFeeder(link))

        def worker() -> None:
            try:
                if not rr._go.wait(30) or rr._cancel:
                    return
                asyncio.run(replay_bytes(rr.feeder, data, speed=speed, **faults))
            except OSError as e:  # pty closed under us during teardown
                rr.error = e
            finally:
                rr.done.set()

        t = threading.Thread(target=worker, name="replay", daemon=True)
        t.start()
        try:
            yield rr
        finally:
            if not rr._go.is_set():
                rr._cancel = True
                rr._go.set()
            t.join(timeout=30)
            rr.feeder.close()

    yield _make


@pytest.fixture
def terminate() -> Callable[[subprocess.Popen], None]:
    """terminate(proc): SIGTERM, then SIGKILL after 5 s."""
    return _terminate


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
