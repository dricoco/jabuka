"""WR-03: Plan B reads the bus through a receive-only relay; its writes never reach the wire."""

from __future__ import annotations

import asyncio
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import serial

from jabuka.ingest.fastnet_framing import load_capture
from jabuka.sim.pty_replay import PtyFeeder
from jabuka.tools.fastnet_relay import FastnetRelay, build_arg_parser

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fastnet"
EXAMPLE2 = FIX / "example2_fastnet_data.txt"


def _pending(fd: int) -> bytes:
    """Whatever is readable on fd right now (b"" if nothing)."""
    out = b""
    while select.select([fd], [], [], 0.05)[0]:
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            break
        if not chunk:
            break
        out += chunk
    return out


async def _until(cond, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timeout"
        await asyncio.sleep(0.01)


async def test_relay_copies_bus_bytes_and_discards_reader_writes(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    data = load_capture(EXAMPLE2)[:3000]
    link = tmp_path / "run" / "fastnet-ro"
    with PtyFeeder() as bus, PtyFeeder(link) as relay_pty:
        relay = FastnetRelay(bus.slave_path, relay_pty, loop)
        assert relay.try_open()
        task = asyncio.create_task(relay.run())
        # "fastnet2ip": stock pyserial, read/write, on the relay's pty (never the device)
        planb = serial.Serial(str(link), baudrate=28800, timeout=0)
        try:
            _pending(bus.master)  # anything from opening is not the reader's doing
            for i in range(0, len(data), 200):
                bus.write(data[i : i + 200])
            got = b""

            def read_some() -> bool:
                nonlocal got
                got += planb.read(4096)
                return len(got) >= len(data)

            await _until(read_some)
            assert got == data
            # the reader tries every way to transmit
            tx = b"\x01\x02\x03 hello bus"
            planb.write(tx)
            planb.flush()
            for action in (
                lambda: planb.send_break(0.01),
                lambda: setattr(planb, "break_condition", True),
                lambda: setattr(planb, "rts", False),
                lambda: setattr(planb, "dtr", False),
            ):
                try:
                    action()
                except (OSError, serial.SerialException):
                    pass  # ENOTTY on a pty is fine: it still never reaches the bus
            await _until(lambda: relay.tx_discarded >= len(tx))
            await asyncio.sleep(0.05)
            assert _pending(bus.master) == b""  # nothing came out on the bus side
            assert relay.bytes_relayed == len(data)
            assert relay.bytes_dropped == 0
            st = relay.stats()
            assert st["device_open"] is True and st["tx_discarded"] >= len(tx)
        finally:
            planb.close()
            task.cancel()
            relay.close()


async def test_relay_reconnects_and_keeps_the_reader_port(tmp_path: Path) -> None:
    """Unplug/replug of the adapter: the pty (the reader's port) survives, data resumes."""
    loop = asyncio.get_running_loop()
    link = tmp_path / "fastnet-ro"
    bus_link = tmp_path / "fastnet"
    with PtyFeeder(bus_link) as bus, PtyFeeder(link) as relay_pty:
        relay = FastnetRelay(str(bus_link), relay_pty, loop)
        task = asyncio.create_task(relay.run())
        reader = os.open(link, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
        try:
            await _until(lambda: relay.fd is not None)
            bus.write(b"\xaa" * 10)
            await _until(lambda: relay.bytes_relayed >= 10)
            bus.reopen()  # unplug + replug (new pty, link re-pointed)
            await _until(lambda: relay.reconnects >= 1, timeout=8)
            bus.write(b"\xbb" * 10)
            await _until(lambda: relay.bytes_relayed >= 20)
            assert _pending(reader) == b"\xaa" * 10 + b"\xbb" * 10
        finally:
            os.close(reader)
            task.cancel()
            relay.close()


async def test_relay_waits_for_a_missing_device(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    with PtyFeeder(tmp_path / "ro") as relay_pty:
        relay = FastnetRelay(str(tmp_path / "absent"), relay_pty, loop)
        assert relay.try_open() is False
        assert "absent" in (relay.last_error or "")
        relay.close()


def test_relay_cli_defaults() -> None:
    args = build_arg_parser().parse_args([])
    assert args.device == "/dev/fastnet"
    assert str(args.link) == "/run/jabuka-relay/fastnet-ro"


def test_relay_cli_runs_and_stops_on_sigterm(tmp_path: Path) -> None:
    link = tmp_path / "ro"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jabuka.tools.fastnet_relay",
            "--device",
            str(tmp_path / "absent"),
            "--link",
            str(link),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert str(link) in line
        assert link.is_symlink()
        time.sleep(0.3)
        assert proc.poll() is None  # device missing: keeps running
    finally:
        proc.terminate()
        rc = proc.wait(timeout=10)
    assert rc == 0
    assert not link.exists()  # link removed on exit
