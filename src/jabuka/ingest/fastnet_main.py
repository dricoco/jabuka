"""jabuka-ingest-fastnet: receive-only Fastnet ingest.

Read path per chunk: RAW LOG FIRST -> CountingFramer -> pyfastnet decode -> UDP delta to the core.
The device is opened O_RDONLY (ReadOnlySerial); nothing in this process can write to the bus.

Unattended operation: the process never exits because the device is absent or disappears. A
reconnect loop retries open_fastnet every 1-2 s, and a 1 Hz heartbeat (health_message "fastnet")
reports device ok/missing plus the bus verdict (ok/silent/no_frames/noisy/...) even when no byte
arrives, so the core can tell "ingest alive, bus silent" from "ingest dead".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jabuka.common import messages, sdnotify
from jabuka.ingest.bus_health import HINT_BUSY, HINT_MISSING, WindowStats, classify
from jabuka.ingest.fastnet_decode import ROUTED_CHANNELS, decode_to_values
from jabuka.ingest.fastnet_framing import CountingFramer
from jabuka.ingest.fastnet_records import iter_records, record_hex
from jabuka.ingest.rawlog import RotatingAppendLog
from jabuka.ingest.retention import Retention
from jabuka.ingest.serial_ro import PortBusyError, open_fastnet

log = logging.getLogger("jabuka.ingest.fastnet")

SRC = "fastnet"
HEARTBEAT_S = 1.0
HEALTH_WINDOW_S = 5.0
RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 2.0
MAX_UNKNOWN_CH = 50
_ROUTED_PATHS = frozenset(ROUTED_CHANNELS.values())


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
        self.raw_errors = 0
        self.send_errors = 0
        self.messages_sent = 0
        self.unknown_ch: set[str] = set()
        self.channels_seen: set[str] = set()
        self.window = WindowStats(HEALTH_WINDOW_S)
        # device state, maintained by DeviceReader (the reconnect loop)
        self.device_open = False
        self.device_busy = False  # another process holds the port (exclusive lock)
        self.reconnects = 0
        self.last_error: str | None = None
        # data-volume retention (free-space reserve), run by the flusher task
        self.retention: Retention | None = None

    def bus_stats(self) -> dict:
        s = self.framer.stats
        return {
            "bytes_in": s.bytes_in,
            "bytes_discarded": s.bytes_discarded,
            "frames_ok": s.frames_ok,
            "decode_errors": self.decode_errors,
            "unknown_ch": sorted(self.unknown_ch)[:MAX_UNKNOWN_CH],
        }

    def on_chunk(self, b: bytes) -> None:
        """Never raises: bad bytes or decoder bugs are counted, the read loop keeps going."""
        try:
            self.rawlog.write_chunk(b)  # RAW FIRST: on disk before anything interprets the bytes
        except (OSError, ValueError) as e:  # disk full / closed log: keep live data flowing
            self.raw_errors += 1
            log.error("raw log write failed: %s", e)
        try:
            frames = self.framer.feed(b)
        except Exception:
            self.decode_errors += 1
            log.exception("framer failed")
            return
        for frame in frames:
            try:
                res = decode_to_values(frame, awa_sign=self.awa_sign)
            except Exception as e:
                self.decode_errors += 1
                log.debug("decode failed for %s: %s", frame.hex(), e)
                continue
            if res.error is not None:
                self.decode_errors += 1
                continue
            self.unknown_ch.update(res.unknown_ch)
            if not res.values:
                continue
            values = res.values
            try:
                values = self._with_layout_records(frame, values)
            except Exception:  # diagnostics extra: never lose the decoded values over it
                log.debug("layout record extraction failed for %s", frame.hex())
            self._emit(values)

    def _with_layout_records(self, frame: bytes, values: list[dict]) -> list[dict]:
        """For Heading/TWD/Set whose M/T reference is unknown ("?"), also publish the raw record
        as bandg.layoutRecord.0xNN, so the unidentified layout is visible on the diagnostics
        page (RESEARCH Pattern 3, Pitfall 1)."""
        unknown_ref: set[int] = set()
        for v in values:
            ch = v.get("ch")
            if not isinstance(ch, str):
                continue
            self.channels_seen.add(ch.upper())
            if v.get("path") in _ROUTED_PATHS and v.get("ref") == "?":
                unknown_ref.add(int(ch, 16))
        if not unknown_ref:
            return values
        extra = [
            {
                "path": f"bandg.layoutRecord.0x{ch:02X}",
                "value": record_hex(ch, fmt, data),
                "unit": None,
                "ch": f"0x{ch:02X}",
            }
            for ch, fmt, data in iter_records(frame)
            if ch in unknown_ref
        ]
        return values + extra

    # -- 1 Hz heartbeat ----------------------------------------------------------------------
    def health(self) -> dict:
        """Heartbeat payload: device ok/missing, bus verdict over the last 5 s, counters."""
        s = self.framer.stats
        self.window.push(self._mono(), s)
        r = self.window.rates()
        if self.device_open:
            state, hint = classify(
                int(r["bytes_in"]),
                int(r["bytes_discarded"]),
                int(r["frames_ok"]),
                float(r["span_s"]),
                len(self.channels_seen),
            )
        elif self.device_busy:
            state, hint = "busy", HINT_BUSY
        else:
            state, hint = "missing", HINT_MISSING
        return {
            "device": "ok" if self.device_open else ("busy" if self.device_busy else "missing"),
            "state": state,
            "hint": hint,
            "bytes_per_s": r["bytes_per_s"],
            "frames_per_s": r["frames_per_s"],
            "bytes_in": s.bytes_in,
            "bytes_discarded": s.bytes_discarded,
            "frames_ok": s.frames_ok,
            "decode_errors": self.decode_errors,
            "unknown_ch": sorted(self.unknown_ch)[:MAX_UNKNOWN_CH],
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            # raw-first is a guarantee: losing the raw log must be visible (WR-06)
            "raw_errors": self.raw_errors,
            "send_errors": self.send_errors,
            "raw_file": self.rawlog.current_path.name if self.rawlog.current_path else None,
            **self._disk(),
        }

    def _disk(self) -> dict:
        if self.retention is None:
            return {}
        st = self.retention.status()
        return {
            "disk_state": st["state"],
            "disk_free_bytes": st["free_bytes"],
            "retention_deleted": st["deleted"],
        }

    def send_heartbeat(self) -> None:
        """Never raises (same contract as on_chunk)."""
        try:
            msg = messages.health_message(SRC, self.health(), self._mono(), self._wall())
            data = messages.encode(msg)
        except (ValueError, TypeError) as e:
            self.send_errors += 1
            log.debug("cannot encode heartbeat: %s", e)
            return
        try:
            self.send(data)
            self.messages_sent += 1
        except OSError as e:
            self.send_errors += 1
            log.debug("udp send failed: %s", e)

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


class DeviceReader:
    """Owns the serial port: open, read via loop.add_reader, detect loss, reopen. Forever."""

    def __init__(self, device: str, ingest: FastnetIngest, loop: asyncio.AbstractEventLoop) -> None:
        self.device = device
        self.ingest = ingest
        self.loop = loop
        self.ser: Any = None
        self.fd: int | None = None
        self.opens = 0
        self._lost: asyncio.Future[str] | None = None

    def try_open(self) -> bool:
        """One open attempt. On success the fd is registered with the loop."""
        ing = self.ingest
        try:
            ser = open_fastnet(self.device)
        except PortBusyError as e:
            ing.device_open = False
            ing.device_busy = True
            ing.last_error = str(e)
            return False
        except Exception as e:  # FileNotFoundError / SerialException / OSError while unplugged
            ing.device_open = False
            ing.device_busy = False
            ing.last_error = f"open {self.device}: {e}"
            return False
        ing.device_busy = False
        self.ser = ser
        self.fd = ser.fileno()
        if self.opens > 0:
            ing.reconnects += 1
        self.opens += 1
        ing.framer.buf.clear()  # never splice bytes from before the loss onto the new stream
        ing.device_open = True
        self._lost = self.loop.create_future()
        self.loop.add_reader(self.fd, self._on_readable)
        log.info("reading %s (fd %d) receive-only", self.device, self.fd)
        return True

    def _on_readable(self) -> None:
        fd = self.fd
        if fd is None:
            return
        try:
            b = os.read(fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:  # EIO on USB unplug / pty master closed
            self._mark_lost(f"read error: {e}")
            return
        if not b:
            self._mark_lost("device EOF")
            return
        self.ingest.on_chunk(b)

    def _mark_lost(self, reason: str) -> None:
        log.warning("device %s lost: %s", self.device, reason)
        self.close()
        self.ingest.last_error = reason
        if self._lost is not None and not self._lost.done():
            self._lost.set_result(reason)

    def close(self) -> None:
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
        self.ingest.device_open = False

    async def run(self) -> None:
        """Reconnect loop: never ends because the device is absent (RESEARCH Pitfall 7)."""
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


async def _run(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    raw_dir = Path(args.data_dir) / "logs" / "raw"
    rawlog = RotatingAppendLog(raw_dir, "fastnet")
    sock, send = _make_udp_sender(args.udp)
    ingest = FastnetIngest(rawlog, send, awa_sign=args.awa_sign)
    # Same policy as the core, free-space reserve only (the core owns the budgets): the disk stays
    # protected while the core is down.
    ingest.retention = Retention(raw_dir.parent, enforce_budgets=False)
    reader = DeviceReader(str(args.device), ingest, loop)
    done: asyncio.Future[int] = loop.create_future()

    async def flusher() -> None:
        # the flush/fsync cadence also applies when the bus goes quiet
        while True:
            await asyncio.sleep(1.0)
            rawlog.maybe_flush()
            if ingest.retention is not None:
                ingest.retention.maybe_run(protect=[rawlog.current_path])

    async def heartbeat() -> None:
        # independent of byte arrival: a silent bus or a missing device is still reported
        while True:
            ingest.send_heartbeat()
            await asyncio.sleep(HEARTBEAT_S)

    def on_signal(signum: int) -> None:
        sdnotify.notify("STOPPING=1")
        log.info("signal %d: stopping", signum)
        if not done.done():
            done.set_result(0)

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, on_signal, signum)

    # first attempt before READY=1, so READY means "device open" whenever the device is present
    if not reader.try_open():
        log.warning("%s unavailable (%s): retrying every 1-2 s", args.device, ingest.last_error)
    tasks = [
        asyncio.create_task(flusher(), name="rawlog-flush"),
        asyncio.create_task(heartbeat(), name="heartbeat"),
        asyncio.create_task(reader.run(), name="device"),
    ]
    interval = sdnotify.watchdog_interval()
    if interval is not None:
        tasks.append(asyncio.create_task(sdnotify.watchdog_loop(interval), name="watchdog"))
    sdnotify.notify("READY=1")  # UDP socket + heartbeat running; device open if present
    try:
        rc = await done
    finally:
        for t in tasks:
            t.cancel()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
        reader.close()
        rawlog.close()  # final flush + fsync
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
