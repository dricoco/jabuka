"""jabuka-replay: L0 byte-level replay of a Fastnet capture into a pseudo-terminal.

The ingest opens the pty slave exactly like /dev/fastnet, so the live code path is exercised.
close() makes the reader see EOF/EIO (simulated unplug); reopen() creates a fresh pty and
atomically re-points the stable symlink (simulated replug).
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import os
import pty
import sys
import time
import tty
from pathlib import Path

from jabuka.ingest.fastnet_framing import load_capture

WIRE_RATE = 2400.0  # 28800 baud / (1 start + 8 data + 1 parity + 2 stop) bits per byte


class PtyFeeder:
    def __init__(self, link_path: Path | None = None) -> None:
        self.link_path = Path(link_path) if link_path is not None else None
        self.master: int | None = None
        self.slave: int | None = None
        self.slave_path: str = ""
        self.bytes_written = 0
        self._open()

    def _open(self) -> None:
        master, slave = pty.openpty()
        tty.setraw(master)
        tty.setraw(slave)
        fl = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        self.master, self.slave = master, slave
        self.slave_path = os.ttyname(slave)
        if self.link_path is not None:
            self.link_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.link_path.with_name(f".{self.link_path.name}.{os.getpid()}.tmp")
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            os.symlink(self.slave_path, tmp)
            os.replace(tmp, self.link_path)  # atomic re-point

    # -- writing -----------------------------------------------------------------------------
    def write(self, b: bytes) -> None:
        """Write all bytes; retries on EAGAIN (pty buffer full) so nothing is dropped."""
        if self.master is None:
            raise OSError(errno.EBADF, "pty closed")
        view = memoryview(bytes(b))
        while view:
            try:
                n = os.write(self.master, view)
            except BlockingIOError:
                time.sleep(0.002)
                continue
            view = view[n:]
            self.bytes_written += n

    async def awrite(self, b: bytes) -> None:
        """Async variant: yields to the loop instead of sleeping while the pty is full."""
        if self.master is None:
            raise OSError(errno.EBADF, "pty closed")
        view = memoryview(bytes(b))
        while view:
            try:
                n = os.write(self.master, view)
            except BlockingIOError:
                await asyncio.sleep(0.002)
                continue
            view = view[n:]
            self.bytes_written += n

    # -- lifecycle ---------------------------------------------------------------------------
    def close(self) -> None:
        """Close both ends (reader sees EOF/EIO = unplug) and remove the symlink."""
        for fd in (self.master, self.slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.master = self.slave = None
        if self.link_path is not None:
            try:
                if self.link_path.is_symlink():
                    self.link_path.unlink()
            except OSError:
                pass

    def reopen(self) -> None:
        """New pty (replug); the symlink is atomically re-pointed to the new slave."""
        for fd in (self.master, self.slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.master = self.slave = None
        self._open()

    def __enter__(self) -> PtyFeeder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


async def replay_bytes(
    feeder: PtyFeeder,
    data: bytes,
    *,
    speed: float = 1.0,
    chunk: int = 64,
    wire_rate: float = WIRE_RATE,
) -> None:
    """Write data in chunks paced at wire_rate * speed bytes/s (speed <= 0: as fast as possible)."""
    loop = asyncio.get_running_loop()
    rate = wire_rate * speed if speed > 0 else 0.0
    t0 = loop.time()
    sent = 0
    for i in range(0, len(data), chunk):
        part = data[i : i + chunk]
        await feeder.awrite(part)
        sent += len(part)
        if rate > 0:
            due = t0 + sent / rate
            delay = due - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-replay", description="Replay a Fastnet capture into a pty (L0)."
    )
    p.add_argument("capture", type=Path, help="hex-per-line capture or Jabuka raw log")
    p.add_argument("--speed", type=float, default=1.0, help="multiple of wire rate (2400 B/s)")
    p.add_argument("--link", type=Path, default=None, help="stable symlink to the pty slave")
    p.add_argument("--loop", action="store_true", help="replay forever")
    p.add_argument("--chunk", type=int, default=64)
    return p


async def _run(args: argparse.Namespace) -> int:
    data = load_capture(args.capture)
    with PtyFeeder(args.link) as feeder:
        print(feeder.slave_path, flush=True)
        if feeder.link_path is not None:
            print(feeder.link_path, flush=True)
        while True:
            await replay_bytes(feeder, data, speed=args.speed, chunk=args.chunk)
            if not args.loop:
                break
        # give the reader a moment to drain before the pty disappears
        await asyncio.sleep(0.5)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
