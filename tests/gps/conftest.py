"""GPS test helpers: a FakeGpsd running on its own event loop in a background thread, and a core
factory that builds the app from real CLI flags (--gpsd, --clock)."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jabuka.core.main import CoreContext, build_arg_parser, build_context
from jabuka.core.web import create_app
from jabuka.sim.fake_gpsd import FakeGpsd

GPS_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "gps"


class FakeGpsdThread:
    """FakeGpsd driven from test code: every call is marshalled onto the server's own loop."""

    def __init__(self, port: int = 0) -> None:
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.fake: FakeGpsd | None = None
        self._play: object | None = None

    def _call(self, coro, timeout: float = 5.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def start(self) -> int:
        self.fake = FakeGpsd("127.0.0.1", self.port)
        self.port = self._call(self.fake.start())
        return self.port

    def push(self, obj: dict) -> None:
        assert self.fake is not None
        fake = self.fake
        self._call(_run_sync(lambda: fake.push(obj)))

    def pause(self) -> None:
        assert self.fake is not None
        self.loop.call_soon_threadsafe(self.fake.pause)

    def resume(self) -> None:
        assert self.fake is not None
        self.loop.call_soon_threadsafe(self.fake.resume)

    def watching(self) -> int:
        return self.fake.watching if self.fake is not None else 0

    def play(self, objs: list[dict], **kw) -> None:
        assert self.fake is not None
        self._play = asyncio.run_coroutine_threadsafe(self.fake.play(objs, **kw), self.loop)

    def sent_lines(self) -> list[str]:
        return list(self.fake.sent_lines) if self.fake is not None else []

    def stop_server(self) -> None:
        if self._play is not None:
            self._play.cancel()  # type: ignore[attr-defined]
            self._play = None
        if self.fake is not None:
            self._call(self.fake.close())
            self.fake = None

    def close(self) -> None:
        try:
            self.stop_server()
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            self.loop.close()


async def _run_sync(fn: Callable[[], object]) -> object:
    return fn()


@pytest.fixture
def fake_gpsd() -> Iterator[Callable[..., FakeGpsdThread]]:
    """fake_gpsd(port=0) -> a started FakeGpsdThread (closed at teardown)."""
    made: list[FakeGpsdThread] = []

    def _make(port: int = 0) -> FakeGpsdThread:
        f = FakeGpsdThread(port)
        made.append(f)
        f.start()
        return f

    yield _make
    for f in made:
        f.close()


@pytest.fixture
def make_core() -> Callable[..., CoreContext]:
    """make_core(data_dir, udp_port, gpsd="127.0.0.1:P", clock="system") -> CoreContext built
    exactly as jabuka-core builds it from its flags."""

    def _make(data_dir: Path, udp_port: int, *, gpsd: str = "none", clock: str = "system"):
        args = build_arg_parser().parse_args(
            [
                "--data-dir",
                str(data_dir),
                "--udp-port",
                str(udp_port),
                "--gpsd",
                gpsd,
                "--clock",
                clock,
            ]
        )
        return build_context(args)

    return _make


@pytest.fixture
def core_app() -> Callable[[CoreContext], object]:
    return create_app


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def tpv_sky_objs() -> list[dict]:
    return load_jsonl(GPS_FIXTURES / "tpv_sky.jsonl")


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@pytest.fixture
def now_tpv() -> Callable[..., dict]:
    """now_tpv(mode=3, offset_s=0.0) -> a TPV stamped with the current UTC (+offset)."""

    def _make(mode: int = 3, offset_s: float = 0.0) -> dict:
        t = datetime.fromtimestamp(datetime.now(tz=UTC).timestamp() + offset_s, tz=UTC)
        iso = t.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return {
            "class": "TPV",
            "device": "/dev/gps",
            "mode": mode,
            "time": iso,
            "lat": 43.73,
            "lon": 15.75,
            "track": 225.0,
            "speed": 3.0,
        }

    return _make
