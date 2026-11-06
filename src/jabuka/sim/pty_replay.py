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
import random
import sys
import time
import tty
from collections.abc import Sequence
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

    def offer(self, b: bytes) -> int:
        """Non-blocking write: as many bytes as the pty takes now (0 when full). For live relays,
        where blocking on a reader that stopped reading would stall the source."""
        if self.master is None:
            raise OSError(errno.EBADF, "pty closed")
        try:
            n = os.write(self.master, b)
        except BlockingIOError:
            return 0
        self.bytes_written += n
        return n

    def drain(self) -> int:
        """Read and discard whatever the reader wrote into the slave side (its transmit attempts:
        they end here, never on a wire). Returns the number of bytes discarded (0: nothing
        pending). Raises OSError when the master cannot be read (EIO: no slave side open)."""
        n = 0
        while self.master is not None:
            try:
                b = os.read(self.master, 4096)
            except BlockingIOError:
                break
            except OSError:
                if n:
                    break
                raise
            if not b:
                break
            n += len(b)
        return n

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
    invert: bool = False,
    garbage_rate: float = 0.0,
    silences: Sequence[tuple[float, float]] = (),
    rng: random.Random | None = None,
) -> None:
    """Write data in chunks paced at wire_rate * speed bytes/s (speed <= 0: as fast as possible).

    Fault injection (all off by default):
    - invert: XOR every byte with 0xFF (what A/B swapped wires look like: zero valid frames).
    - garbage_rate: probability per chunk of inserting 1-32 random bytes before it (noise).
    - silences: (start_s, dur_s) windows in replay time (seconds since this call started)
      during which nothing is written; pacing resumes after the window without bursting.
    - rng: random.Random for deterministic garbage (default: a fresh unseeded one).
    """
    loop = asyncio.get_running_loop()
    rate = wire_rate * speed if speed > 0 else 0.0
    rng = rng if rng is not None else random.Random()
    pending = sorted((float(s), float(d)) for s, d in silences)
    t0 = loop.time()
    shift = 0.0  # total silence inserted, so pacing does not catch up in a burst
    sent = 0
    for i in range(0, len(data), chunk):
        while pending and loop.time() - t0 >= pending[0][0]:
            _start, dur = pending.pop(0)
            if dur > 0:
                await asyncio.sleep(dur)
                shift += dur
        part = data[i : i + chunk]
        if invert:
            part = bytes(b ^ 0xFF for b in part)
        if garbage_rate > 0 and rng.random() < garbage_rate:
            part = rng.randbytes(rng.randint(1, 32)) + part
        await feeder.awrite(part)
        sent += len(part)
        if rate > 0:
            due = t0 + shift + sent / rate
            delay = due - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)


class _UnplugAwareFeeder:
    """Wraps a PtyFeeder for the CLI's --unplug-at: while unplugged, writes are dropped (as on a
    real unplugged cable) instead of raising."""

    def __init__(self, feeder: PtyFeeder) -> None:
        self.feeder = feeder
        self.dropped = 0

    async def awrite(self, b: bytes) -> None:
        if self.feeder.master is None:
            self.dropped += len(b)
            return
        try:
            await self.feeder.awrite(b)
        except OSError:
            if self.feeder.master is not None:
                raise
            self.dropped += len(b)


def _parse_silence(text: str) -> tuple[float, float]:
    start, sep, dur = text.partition(":")
    try:
        if not sep:
            raise ValueError
        out = (float(start), float(dur))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected START:DUR seconds, got {text!r}") from None
    if out[0] < 0 or out[1] < 0:
        raise argparse.ArgumentTypeError(f"START and DUR must be >= 0, got {text!r}")
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-replay", description="Replay a Fastnet capture into a pty (L0)."
    )
    p.add_argument("capture", type=Path, help="hex-per-line capture or Jabuka raw log")
    p.add_argument("--speed", type=float, default=1.0, help="multiple of wire rate (2400 B/s)")
    p.add_argument("--link", type=Path, default=None, help="stable symlink to the pty slave")
    p.add_argument("--loop", action="store_true", help="replay forever")
    p.add_argument("--chunk", type=int, default=64)
    faults = p.add_argument_group("fault injection")
    faults.add_argument(
        "--invert", action="store_true", help="XOR every byte with 0xFF (A/B swapped wires)"
    )
    faults.add_argument(
        "--garbage-rate",
        type=float,
        default=0.0,
        metavar="P",
        help="probability per chunk of inserting 1-32 random bytes (noise)",
    )
    faults.add_argument("--seed", type=int, default=None, help="seed for --garbage-rate")
    faults.add_argument(
        "--silence",
        type=_parse_silence,
        action="append",
        default=[],
        metavar="START:DUR",
        help="write nothing for DUR s starting START s into each pass (repeatable)",
    )
    faults.add_argument(
        "--unplug-at",
        type=float,
        default=None,
        metavar="T",
        help="close the pty T s after start (reader sees EOF/EIO, --link is removed)",
    )
    faults.add_argument(
        "--replug-after",
        type=float,
        default=None,
        metavar="D",
        help="reopen a fresh pty D s after --unplug-at (--link re-pointed); default: never",
    )
    return p


async def _unplug(feeder: PtyFeeder, at: float, replug_after: float | None) -> None:
    await asyncio.sleep(at)
    feeder.close()
    print("unplugged", flush=True)
    if replug_after is None:
        return
    await asyncio.sleep(replug_after)
    feeder.reopen()
    print(f"replugged {feeder.slave_path}", flush=True)


async def _run(args: argparse.Namespace) -> int:
    data = load_capture(args.capture)
    rng = random.Random(args.seed)
    with PtyFeeder(args.link) as feeder:
        print(feeder.slave_path, flush=True)
        if feeder.link_path is not None:
            print(feeder.link_path, flush=True)
        writer = _UnplugAwareFeeder(feeder)
        unplug_task = None
        if args.unplug_at is not None:
            unplug_task = asyncio.create_task(_unplug(feeder, args.unplug_at, args.replug_after))
        try:
            while True:
                await replay_bytes(
                    writer,  # type: ignore[arg-type]  # duck-typed: only awrite() is used
                    data,
                    speed=args.speed,
                    chunk=args.chunk,
                    invert=args.invert,
                    garbage_rate=args.garbage_rate,
                    silences=args.silence,
                    rng=rng,
                )
                if not args.loop:
                    break
            if unplug_task is not None and not unplug_task.done():
                await unplug_task  # finish the unplug/replug scenario before exiting
        finally:
            if unplug_task is not None and not unplug_task.done():
                unplug_task.cancel()
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
