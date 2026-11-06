"""Found while running the 04-01 gate (tests/sim/test_synth_e2e.py hung in the core's shutdown):
cancelling the gpsd client while a session is closing (gpsd went away, the writer is waiting for
the socket to close) was swallowed by the cleanup, so the task never ended and the core's
lifespan shutdown waited forever (on the Pi: a SIGTERM that only systemd's SIGKILL finishes)."""

from __future__ import annotations

import asyncio

import pytest

from jabuka.ingest import gpsd_client
from jabuka.ingest.gpsd_client import GpsdClient


class _EofReader:
    async def read(self, n: int) -> bytes:
        return b""  # gpsd went away


class _SlowCloseWriter:
    def __init__(self) -> None:
        self.closing = asyncio.Event()

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closing.set()

    async def wait_closed(self) -> None:
        await asyncio.sleep(0.8)  # the kernel takes its time to tear the socket down


class _Stop(BaseException):
    """Ends a client that swallowed its cancellation (so a RED run fails instead of hanging)."""


async def test_cancel_during_session_close_ends_the_task(monkeypatch: pytest.MonkeyPatch) -> None:
    writers: list[_SlowCloseWriter] = []
    stop = False

    async def fake_open(host: str, port: int):
        if stop:
            raise _Stop
        w = _SlowCloseWriter()
        writers.append(w)
        return _EofReader(), w

    monkeypatch.setattr(gpsd_client.asyncio, "open_connection", fake_open)
    client = GpsdClient("127.0.0.1", 9, lambda obj, t: None, None, backoff_min=0.05)
    task = asyncio.create_task(client.run())
    while not writers or not writers[0].closing.is_set():
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # inside the cleanup's wait for the close
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=2.0)
    ended = task in done
    if not ended:
        stop = True
        await asyncio.wait({task}, timeout=5.0)
    assert ended, "the gpsd client swallowed the cancellation and kept reconnecting"
    assert task.cancelled()
