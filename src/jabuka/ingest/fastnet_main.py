"""jabuka-ingest-fastnet: receive-only Fastnet ingest.

Read path per chunk: RAW LOG FIRST -> CountingFramer -> pyfastnet decode -> UDP delta to the core.
The device is opened O_RDONLY (ReadOnlySerial); nothing in this process can write to the bus.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

from jabuka.common import messages
from jabuka.ingest.fastnet_decode import decode_to_values
from jabuka.ingest.fastnet_framing import CountingFramer
from jabuka.ingest.rawlog import RotatingAppendLog
from jabuka.ingest.serial_ro import open_fastnet

log = logging.getLogger("jabuka.ingest.fastnet")

SRC = "fastnet"


class FastnetIngest:
    """Pure per-chunk pipeline (no IO besides the raw log and the injected send)."""

    def __init__(
        self,
        rawlog: RotatingAppendLog,
        send: Callable[[bytes], None],
        *,
        awa_sign: int = 1,
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.rawlog = rawlog
        self.send = send
        self.awa_sign = awa_sign
        self._mono = mono
        self._wall = wall
        self.framer = CountingFramer()
        self.decode_errors = 0
        self.send_errors = 0
        self.messages_sent = 0
        self.unknown_ch: set[str] = set()

    def bus_stats(self) -> dict:
        s = self.framer.stats
        return {
            "bytes_in": s.bytes_in,
            "bytes_discarded": s.bytes_discarded,
            "frames_ok": s.frames_ok,
            "decode_errors": self.decode_errors,
            "unknown_ch": sorted(self.unknown_ch),
        }

    def on_chunk(self, b: bytes) -> None:
        self.rawlog.write_chunk(b)  # RAW FIRST: bytes are on disk before anything interprets them
        for frame in self.framer.feed(b):
            res = decode_to_values(frame, awa_sign=self.awa_sign)
            if res.error is not None:
                self.decode_errors += 1
                continue
            self.unknown_ch.update(res.unknown_ch)
            if not res.values:
                continue
            self._emit(res.values)

    def _emit(self, values: list[dict]) -> None:
        try:
            msg = messages.delta_message(
                SRC, values, self._mono(), self._wall(), bus=self.bus_stats()
            )
            data = messages.encode(msg)
        except (ValueError, TypeError) as e:
            self.send_errors += 1
            log.debug("cannot encode delta: %s", e)
            return
        try:
            self.send(data)
            self.messages_sent += 1
        except OSError as e:  # never raise into the read path
            self.send_errors += 1
            log.debug("udp send failed: %s", e)


def parse_hostport(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"expected HOST:PORT, got {text!r}")
    return host, int(port)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-ingest-fastnet",
        description="Receive-only B&G Fastnet ingest: raw log, decode, UDP deltas to the core.",
    )
    p.add_argument("--device", default="/dev/fastnet", help="serial device (default /dev/fastnet)")
    p.add_argument(
        "--udp",
        type=parse_hostport,
        default=("127.0.0.1", messages.DEFAULT_UDP_PORT),
        help=f"core UDP HOST:PORT (default 127.0.0.1:{messages.DEFAULT_UDP_PORT})",
    )
    p.add_argument("--data-dir", type=Path, default=Path("./var"), help="data dir (default ./var)")
    p.add_argument("--awa-sign", type=int, choices=(1, -1), default=1)
    p.add_argument("--log-level", default="WARNING")
    return p


def _make_udp_sender(addr: tuple[str, int]) -> tuple[socket.socket, Callable[[bytes], None]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    def send(data: bytes) -> None:
        try:
            sock.sendto(data, addr)
        except (BlockingIOError, ConnectionRefusedError):
            pass  # core not up yet / socket buffer full: drop, the raw log has the bytes

    return sock, send


async def _run(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    raw_dir = Path(args.data_dir) / "logs" / "raw"
    rawlog = RotatingAppendLog(raw_dir, "fastnet")
    sock, send = _make_udp_sender(args.udp)
    ingest = FastnetIngest(rawlog, send, awa_sign=args.awa_sign)
    done: asyncio.Future[int] = loop.create_future()

    try:
        ser = open_fastnet(str(args.device))
    except Exception as e:
        log.error("cannot open %s: %s", args.device, e)
        rawlog.close()
        sock.close()
        return 2
    fd = ser.fileno()

    def on_readable() -> None:
        try:
            b = os.read(fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:  # EIO on USB unplug / pty master closed
            loop.remove_reader(fd)
            log.warning("device read error: %s", e)
            if not done.done():
                done.set_result(3)
            return
        if not b:
            loop.remove_reader(fd)
            log.warning("device EOF")
            if not done.done():
                done.set_result(3)
            return
        ingest.on_chunk(b)

    async def flusher() -> None:
        # the flush/fsync cadence also applies when the bus goes quiet
        while True:
            await asyncio.sleep(1.0)
            rawlog.maybe_flush()

    loop.add_reader(fd, on_readable)
    log.info("reading %s (fd %d) receive-only", args.device, fd)
    flush_task = asyncio.create_task(flusher())
    try:
        rc = await done
    finally:
        flush_task.cancel()
        try:
            loop.remove_reader(fd)
        except Exception:
            pass
        ser.close()
        rawlog.close()
        sock.close()
    return rc


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
