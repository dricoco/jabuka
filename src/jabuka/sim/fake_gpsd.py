"""jabuka-fake-gpsd: a gpsd-protocol TCP server for tests and laptop development.

Speaks just enough of gpsd's JSON protocol for jabuka's client: VERSION on connect; on ``?WATCH``
it answers DEVICES (path /dev/gps, driver u-blox) and WATCH, then streams objects to watching
clients, one JSON object per line. push() sends an object now, pause() drops pushes (GPS loss)
until resume(), play() paces a script by its TPV times.

Dev/test tool only: never referenced by the systemd units. Default port 2948, so it cannot
silently take the real gpsd's 2947. It may read the wall clock (retime); it is not domain code.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from jabuka.ingest.nmea import NmeaToGpsd

log = logging.getLogger("jabuka.sim.fake_gpsd")

DEFAULT_PORT = 2948
DEVICE_PATH = "/dev/gps"

VERSION = {
    "class": "VERSION",
    "release": "3.25-jabuka-fake",
    "rev": "jabuka-fake-gpsd",
    "proto_major": 3,
    "proto_minor": 15,
}
DEVICES = {
    "class": "DEVICES",
    "devices": [
        {"class": "DEVICE", "path": DEVICE_PATH, "driver": "u-blox", "bps": 9600, "flags": 1}
    ],
}
WATCH = {"class": "WATCH", "enable": True, "json": True, "nmea": False, "raw": 0}


def _dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"))


def utc_iso(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_time(text: object) -> float | None:
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo is not None else None


class _Client:
    __slots__ = ("writer", "watching")

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.watching = False


class FakeGpsd:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self.paused = False
        self.sent = 0
        self.dropped = 0
        self.sent_lines: deque[str] = deque(maxlen=2000)
        self._server: asyncio.Server | None = None
        self._clients: set[_Client] = set()
        self._handlers: set[asyncio.Task] = set()

    # -- server --------------------------------------------------------------------------------
    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    @property
    def watching(self) -> int:
        return sum(1 for c in self._clients if c.watching)

    def _send(self, client: _Client, text: str) -> None:
        w = client.writer
        if w.is_closing():
            self._clients.discard(client)
            return
        w.write(text.encode("utf-8") + b"\n")
        self.sent_lines.append(text)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        client = _Client(writer)
        self._clients.add(client)
        try:
            self._send(client, _dumps(VERSION))
            while True:
                line = await reader.readline()
                if not line:
                    break
                cmd = line.strip()
                if cmd.startswith(b"?WATCH"):
                    enable = True
                    _, _, arg = cmd.partition(b"=")
                    try:
                        spec = json.loads(arg.rstrip(b";")) if arg else {}
                        enable = bool(spec.get("enable", True)) if isinstance(spec, dict) else True
                    except ValueError:
                        pass
                    if enable:
                        self._send(client, _dumps(DEVICES))
                        self._send(client, _dumps(WATCH))
                    client.watching = enable
                elif cmd.startswith(b"?VERSION"):
                    self._send(client, _dumps(VERSION))
                elif cmd.startswith(b"?DEVICES"):
                    self._send(client, _dumps(DEVICES))
        except (ConnectionError, OSError, ValueError, asyncio.CancelledError):
            pass
        finally:
            self._clients.discard(client)
            writer.close()
            if task is not None:
                self._handlers.discard(task)

    # -- feeding -------------------------------------------------------------------------------
    def push(self, obj: dict) -> None:
        """Send one object to every watching client now (dropped while paused)."""
        self.push_raw(_dumps(obj).encode("utf-8"))

    def push_raw(self, line: bytes) -> None:
        """Send one raw line (no validation; tests use it for hostile input)."""
        if self.paused:
            self.dropped += 1
            return
        text = line.decode("utf-8", errors="replace")
        for c in list(self._clients):
            if c.watching:
                w = c.writer
                if w.is_closing():
                    self._clients.discard(c)
                    continue
                w.write(bytes(line) + b"\n")
                self.sent_lines.append(text)
        self.sent += 1

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    async def wait_watching(self, timeout: float | None = None) -> bool:
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while self.watching == 0:
            if deadline is not None and loop.time() >= deadline:
                return False
            await asyncio.sleep(0.02)
        return True

    async def play(
        self,
        objs: list[dict],
        *,
        speed: float = 1.0,
        loop: bool = False,
        retime: bool = False,
        wait_client: float | None = 10.0,
    ) -> None:
        """Send objs paced by TPV "time" deltas (1 s when a time is missing) / speed. Non-TPV
        objects follow the preceding TPV immediately. retime=True stamps TPV/SKY times with the
        current UTC at send time. Waits up to wait_client seconds for a watcher first."""
        if wait_client:
            await self.wait_watching(wait_client)
        speed = speed if speed > 0 else 1.0
        while True:
            prev_t: float | None = None
            first = True
            for obj in objs:
                out = dict(obj)
                if out.get("class") == "TPV":
                    t = _parse_time(out.get("time"))
                    if not first:
                        dt = (t - prev_t) if (t is not None and prev_t is not None) else 1.0
                        await asyncio.sleep(min(max(dt, 0.0), 10.0) / speed)
                    first = False
                    prev_t = t
                if retime and "time" in out:
                    out["time"] = utc_iso(datetime.now(tz=UTC).timestamp())
                self.push(out)
            if not loop:
                return
            await asyncio.sleep(1.0 / speed)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
        for c in list(self._clients):
            c.writer.close()
        self._clients.clear()
        for t in list(self._handlers):
            t.cancel()
        if self._server is not None:
            with contextlib.suppress(TimeoutError, OSError):
                await asyncio.wait_for(self._server.wait_closed(), 2.0)
            self._server = None


# -- script loading ----------------------------------------------------------------------------
def load_script(path: Path) -> list[dict]:
    """JSONL of gpsd objects, or jabuka gps raw-log lines ``<t_mono> <t_wall> <json>``.
    Lines that are neither (garbage, torn last line) are skipped."""
    out: list[dict] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = None
        for candidate in (line, line.split(" ", 2)[-1] if line.count(" ") >= 2 else None):
            if candidate is None:
                continue
            try:
                obj = json.loads(candidate)
                break
            except ValueError:
                continue
        if isinstance(obj, dict) and isinstance(obj.get("class"), str):
            out.append(obj)
    return out


def load_nmea(path: Path) -> list[dict]:
    conv = NmeaToGpsd(device=DEVICE_PATH)
    out: list[dict] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        out.extend(conv.feed(line))
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-fake-gpsd",
        description="gpsd-protocol test server (dev only; default port 2948, never 2947).",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--script", type=Path, help="JSONL of gpsd objects or a jabuka gps raw log")
    src.add_argument("--nmea", type=Path, help="NMEA 0183 file (RMC/GGA)")
    p.add_argument("--speed", type=float, default=1.0, help="playback speed multiple")
    p.add_argument("--loop", action="store_true", help="replay forever")
    p.add_argument("--retime", action="store_true", help="stamp TPV times with current UTC")
    return p


async def _run(args: argparse.Namespace) -> int:
    objs = load_script(args.script) if args.script else load_nmea(args.nmea)
    fake = FakeGpsd(args.host, args.port)
    port = await fake.start()
    print(f"jabuka-fake-gpsd: listening on {args.host}:{port} ({len(objs)} objects)", flush=True)
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, lambda: stop.done() or stop.set_result(None))

    async def run_play() -> None:
        await fake.wait_watching()  # start the script when the first client watches
        await fake.play(
            objs, speed=args.speed, loop=args.loop, retime=args.retime, wait_client=None
        )

    task = asyncio.create_task(run_play())
    try:
        await stop
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
