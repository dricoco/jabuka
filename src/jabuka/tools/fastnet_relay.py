"""jabuka-fastnet-relay: give Plan B (fastnet2ip) the Fastnet bytes without giving it the bus.

The relay opens /dev/fastnet with open_fastnet (O_RDONLY, line control refused, exclusive lock) and
copies every byte into a pseudo-terminal whose slave is linked at --link (default
/run/jabuka-relay/fastnet-ro). fastnet2ip runs as the unprivileged jabuka user WITHOUT the dialout
group and opens that pty instead of the device: it cannot open /dev/fastnet at all, and anything it
writes (data, break, modem lines) lands in the pty, is read back here and discarded, and never
reaches the wire. Discarded bytes are counted and logged as a warning.

Unattended operation like the ingest: the pty (and its link) exist for the relay's whole lifetime,
so the reader never loses its port; the device side reconnects every 1-2 s when the adapter is
absent or unplugged. READY=1 is sent once the pty link exists; WATCHDOG=1 from the event loop.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from jabuka.common import sdnotify
from jabuka.ingest.serial_ro import PortBusyError, open_fastnet
from jabuka.sim.pty_replay import PtyFeeder

log = logging.getLogger("jabuka.relay")

RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 2.0
STATS_INTERVAL_S = 60.0
DEFAULT_LINK = Path("/run/jabuka-relay/fastnet-ro")


class FastnetRelay:
    """Device (read-only) -> pty master. The pty's own output (the reader's writes) is drained and
    discarded."""

    def __init__(self, device: str, feeder: PtyFeeder, loop: asyncio.AbstractEventLoop) -> None:
        self.device = device
        self.feeder = feeder
        self.loop = loop
        self.ser: Any = None
        self.fd: int | None = None
        self.opens = 0
        self.reconnects = 0
        self.bytes_in = 0
        self.bytes_relayed = 0
        self.bytes_dropped = 0  # the reader stopped reading and the pty buffer was full
        self.tx_discarded = 0  # bytes the reader tried to send
        self.last_error: str | None = None
        self._lost: asyncio.Future[str] | None = None
        assert feeder.master is not None
        loop.add_reader(feeder.master, self._drain)

    # -- reader side ---------------------------------------------------------------------------
    def _drain(self) -> None:
        try:
            n = self.feeder.drain()
        except OSError as e:  # master unreadable: stop polling instead of spinning
            log.warning("relay pty unreadable: %s", e)
            if self.feeder.master is not None:
                self.loop.remove_reader(self.feeder.master)
            return
        if n:
            self.tx_discarded += n
            log.warning("Plan B reader wrote %d bytes into the relay pty: discarded", n)

    # -- device side ---------------------------------------------------------------------------
    def try_open(self) -> bool:
        try:
            ser = open_fastnet(self.device)
        except PortBusyError as e:
            self.last_error = str(e)
            return False
        except Exception as e:  # FileNotFoundError / SerialException / OSError while unplugged
            self.last_error = f"open {self.device}: {e}"
            return False
        self.ser = ser
        self.fd = ser.fileno()
        if self.opens > 0:
            self.reconnects += 1
        self.opens += 1
        self._lost = self.loop.create_future()
        self.loop.add_reader(self.fd, self._on_readable)
        log.info(
            "relaying %s (fd %d, receive-only) -> %s", self.device, self.fd, self.feeder.slave_path
        )
        return True

    def _on_readable(self) -> None:
        fd = self.fd
        if fd is None:
            return
        try:
            b = os.read(fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:  # EIO on USB unplug
            self._mark_lost(f"read error: {e}")
            return
        if not b:
            self._mark_lost("device EOF")
            return
        self.bytes_in += len(b)
        try:
            n = self.feeder.offer(b)
        except OSError as e:
            n = 0
            self.last_error = f"pty write: {e}"
        self.bytes_relayed += n
        self.bytes_dropped += len(b) - n

    def _mark_lost(self, reason: str) -> None:
        log.warning("device %s lost: %s", self.device, reason)
        self.close_device()
        self.last_error = reason
        if self._lost is not None and not self._lost.done():
            self._lost.set_result(reason)

    def close_device(self) -> None:
        if self.fd is not None:
            try:
                self.loop.remove_reader(self.fd)
            except Exception:
                pass
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.fd = None

    def close(self) -> None:
        self.close_device()
        if self.feeder.master is not None:
            try:
                self.loop.remove_reader(self.feeder.master)
            except Exception:
                pass

    def stats(self) -> dict:
        return {
            "device_open": self.fd is not None,
            "bytes_in": self.bytes_in,
            "bytes_relayed": self.bytes_relayed,
            "bytes_dropped": self.bytes_dropped,
            "tx_discarded": self.tx_discarded,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
        }

    async def run(self) -> None:
        """Reconnect loop: never ends because the device is absent."""
        backoff = RECONNECT_MIN_S
        while True:
            if self.fd is None:
                if not self.try_open():
                    await asyncio.sleep(backoff)
                    backoff = min(RECONNECT_MAX_S, backoff * 1.5)
                    continue
                backoff = RECONNECT_MIN_S
            assert self._lost is not None
            await self._lost
            await asyncio.sleep(RECONNECT_MIN_S)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-fastnet-relay",
        description="Receive-only relay of the Fastnet bus into a pty for Plan B (fastnet2ip).",
    )
    p.add_argument("--device", default="/dev/fastnet", help="serial device (default /dev/fastnet)")
    p.add_argument(
        "--link",
        type=Path,
        default=DEFAULT_LINK,
        help=f"pty slave symlink (default {DEFAULT_LINK})",
    )
    p.add_argument("--log-level", default="INFO")
    return p


async def _run(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[int] = loop.create_future()
    with PtyFeeder(args.link) as feeder:
        relay = FastnetRelay(str(args.device), feeder, loop)

        def on_signal(signum: int) -> None:
            sdnotify.notify("STOPPING=1")
            if not done.done():
                done.set_result(0)

        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, on_signal, signum)

        async def stats() -> None:
            while True:
                await asyncio.sleep(STATS_INTERVAL_S)
                log.info("relay stats: %s", relay.stats())

        if not relay.try_open():
            log.warning("%s unavailable (%s): retrying every 1-2 s", args.device, relay.last_error)
        tasks = [
            asyncio.create_task(relay.run(), name="device"),
            asyncio.create_task(stats(), name="stats"),
        ]
        interval = sdnotify.watchdog_interval()
        if interval is not None:
            tasks.append(asyncio.create_task(sdnotify.watchdog_loop(interval), name="watchdog"))
        print(f"{feeder.slave_path} -> {args.link}", flush=True)
        sdnotify.notify("READY=1")  # the pty link exists; the device is open if present
        try:
            return await done
        finally:
            for t in tasks:
                t.cancel()
            for signum in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(signum)
            relay.close()
            log.info("relay stopped: %s", relay.stats())


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
