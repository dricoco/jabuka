"""Soak hooks of the synthetic boat (plan 04-01): --clock-udp (src "simclock" health messages
carrying t_sim), --control (run-time fault on/off over UDP JSON, malformed datagrams counted and
ignored), --progress, and the pty fault kinds noise and unplug."""

from __future__ import annotations

import asyncio
import json
import os
import random
import select
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from jabuka.common import messages
from jabuka.sim.synth import (
    FAULT_KINDS,
    SynthConfig,
    build_arg_parser,
    config_from_args,
    noisy,
    parse_fault,
    run_synth,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="ptys: Linux only")

START = 1_794_600_000.0


class PtyReader(threading.Thread):
    """Reads whatever the pty link points to; reopens the link after an unplug (EIO/EOF)."""

    def __init__(self, link: Path) -> None:
        super().__init__(daemon=True)
        self.link = link
        self.chunks: list[tuple[float, int]] = []  # (monotonic, n bytes)
        self.eio = 0
        self.opens = 0
        self.stop = threading.Event()

    def run(self) -> None:
        fd = None
        while not self.stop.is_set():
            if fd is None:
                try:
                    fd = os.open(self.link, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
                    self.opens += 1
                except OSError:
                    time.sleep(0.01)
                    continue
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                continue
            try:
                b = os.read(fd, 4096)
            except BlockingIOError:
                continue
            except OSError:
                b = b""
            if not b:
                self.eio += 1
                os.close(fd)
                fd = None
                time.sleep(0.02)
                continue
            self.chunks.append((time.monotonic(), len(b)))
        if fd is not None:
            os.close(fd)

    def bytes_between(self, t0: float, t1: float) -> int:
        return sum(n for t, n in self.chunks if t0 <= t < t1)


def _udp_listener() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(0.05)
    return s


def _run_thread(
    cfg: SynthConfig, ready: dict, stop: threading.Event
) -> tuple[threading.Thread, dict]:
    out: dict = {}

    def target() -> None:
        try:
            out.update(asyncio.run(run_synth(cfg, on_ready=ready.update, stop=stop.is_set)))
        except BaseException as e:  # surfaced by the test
            out["error"] = repr(e)

    th = threading.Thread(target=target, daemon=True)
    th.start()
    return th, out


def _wait(pred, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not met"
        time.sleep(0.01)


def test_new_fault_kinds_parse() -> None:
    assert {"noise", "unplug"} <= set(FAULT_KINDS)
    assert parse_fault("noise@10+5").kind == "noise"
    assert parse_fault("unplug@1+2").dur == 2.0


def test_cli_flags_reach_the_config() -> None:
    args = build_arg_parser().parse_args(
        [
            "--mode",
            "pty",
            "--clock-udp",
            "127.0.0.1:4000",
            "--control",
            "127.0.0.1:0",
            "--progress",
            "--follow",
            "http://127.0.0.1:8080",
            "--follow-nowait",
        ]
    )
    cfg = config_from_args(args)
    assert cfg.clock_udp == ("127.0.0.1", 4000)
    assert cfg.control == ("127.0.0.1", 0)
    assert cfg.progress is True and cfg.follow_nowait is True


def test_noise_flips_one_bit_sometimes_and_is_seeded() -> None:
    data = bytes(range(40))
    rng_a, rng_b = random.Random(3), random.Random(3)
    outs = [noisy(data, rng_a) for _ in range(200)]
    assert outs == [noisy(data, rng_b) for _ in range(200)]
    changed = [o for o in outs if o != data]
    assert 40 < len(changed) < 160
    for o in changed:
        diff = [a ^ b for a, b in zip(o, data, strict=True) if a != b]
        assert len(diff) == 1 and bin(diff[0]).count("1") == 1


def test_clock_udp_and_control_in_pty_mode(tmp_path: Path) -> None:
    clock = _udp_listener()
    link = tmp_path / "fastnet-pty"
    cfg = SynthConfig(
        mode="pty",
        speed=50.0,
        duration=400.0,
        link=link,
        gpsd_port=0,
        start_utc=START,
        clock_udp=("127.0.0.1", clock.getsockname()[1]),
        control=("127.0.0.1", 0),
    )
    ready: dict = {}
    stop = threading.Event()
    th, out = _run_thread(cfg, ready, stop)
    reader = None
    try:
        _wait(lambda: ready.get("control_port") is not None and link.exists())
        reader = PtyReader(link)
        reader.start()
        ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dest = ("127.0.0.1", ready["control_port"])

        # the sim clock: one "simclock" health message per sim second, t_sim += 1
        t_sims: list[float] = []
        deadline = time.monotonic() + 5
        while len(t_sims) < 20 and time.monotonic() < deadline:
            try:
                data, _ = clock.recvfrom(9000)
            except TimeoutError:
                continue
            msg = messages.decode(data)
            assert msg is not None and msg["src"] == "simclock" and msg["type"] == "health"
            t_sims.append(msg["t_sim"])
        assert len(t_sims) >= 20
        assert t_sims[0] >= START
        assert all(b - a == pytest.approx(1.0) for a, b in zip(t_sims, t_sims[1:], strict=False))

        time.sleep(0.3)
        t_on = time.monotonic()
        ctl.sendto(json.dumps({"fault": "bus-silent", "on": True}).encode(), dest)
        ctl.sendto(b"not json", dest)  # malformed: ignored and counted
        ctl.sendto(json.dumps({"fault": "volcano", "on": True}).encode(), dest)
        ctl.sendto(json.dumps({"fault": "garbage", "on": "yes"}).encode(), dest)
        time.sleep(1.0)
        t_off = time.monotonic()
        ctl.sendto(json.dumps({"fault": "bus-silent", "on": False}).encode(), dest)
        time.sleep(0.6)
        t_end = time.monotonic()
        ctl.close()
        before = reader.bytes_between(t_on - 0.3, t_on)
        silent = reader.bytes_between(t_on + 0.2, t_off)
        after = reader.bytes_between(t_off + 0.2, t_end)
        assert before > 0, reader.chunks[-5:]
        assert silent == 0, silent
        assert after > 0
    finally:
        stop.set()
        th.join(timeout=10)
        if reader is not None:
            reader.stop.set()
            reader.join(timeout=5)
        clock.close()
    assert not th.is_alive()
    assert "error" not in out, out.get("error")
    assert out["counts"]["control"] == 2
    assert out["counts"]["control_bad"] == 3
    assert out["counts"]["clock"] >= 20


def test_unplug_closes_and_replugs_the_pty(tmp_path: Path) -> None:
    link = tmp_path / "fastnet-pty"
    cfg = SynthConfig(
        mode="pty",
        speed=50.0,
        duration=300.0,
        link=link,
        gpsd_port=0,
        start_utc=START,
        control=("127.0.0.1", 0),
    )
    ready: dict = {}
    stop = threading.Event()
    th, out = _run_thread(cfg, ready, stop)
    reader = None
    try:
        _wait(lambda: ready.get("control_port") is not None and link.exists())
        first = os.readlink(link)
        reader = PtyReader(link)
        reader.start()
        _wait(lambda: reader.chunks)
        ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dest = ("127.0.0.1", ready["control_port"])
        ctl.sendto(json.dumps({"fault": "unplug", "on": True}).encode(), dest)
        _wait(lambda: reader.eio >= 1, 5)  # the reader sees EIO/EOF
        ctl.sendto(json.dumps({"fault": "unplug", "on": False}).encode(), dest)
        _wait(lambda: reader.opens >= 2, 5)
        n = len(reader.chunks)
        _wait(lambda: len(reader.chunks) > n + 3, 5)  # frames flow on the fresh pty
        assert link.is_symlink() and first  # re-pointed (the kernel may reuse the pty number)
        ctl.close()
    finally:
        stop.set()
        th.join(timeout=10)
        if reader is not None:
            reader.stop.set()
            reader.join(timeout=5)
    assert "error" not in out, out.get("error")
    assert out["counts"]["unplugs"] == 1


def test_noise_window_frames_still_decoded(tmp_path: Path) -> None:
    """Bit-flipped frames: the decoder rejects some checksums but keeps decoding the rest."""
    from jabuka.ingest.fastnet_framing import CountingFramer

    link = tmp_path / "fastnet-pty"
    cfg = SynthConfig(
        mode="pty",
        speed=200.0,
        duration=200.0,
        link=link,
        gpsd_port=0,
        start_utc=START,
        faults=[parse_fault("noise@0+200")],
        seed=7,
    )
    ready: dict = {}
    stop = threading.Event()
    th, out = _run_thread(cfg, ready, stop)
    buf = bytearray()
    try:
        _wait(lambda: link.exists())
        fd = os.open(link, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            while th.is_alive():
                r, _, _ = select.select([fd], [], [], 0.05)
                if r:
                    try:
                        b = os.read(fd, 4096)
                    except OSError:
                        break
                    if not b:
                        break
                    buf += b
        finally:
            os.close(fd)
    finally:
        stop.set()
        th.join(timeout=10)
    assert "error" not in out, out.get("error")
    assert out["counts"]["noisy"] > 20
    framer = CountingFramer()
    frames = framer.feed(bytes(buf))
    assert len(frames) > 50  # most frames still decode
    assert framer.stats.bytes_discarded > 0  # the flipped ones are rejected (resync)
