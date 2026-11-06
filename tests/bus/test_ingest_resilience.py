"""The ingest survives unplug/replug, an absent device, silence and decoder bugs, and sends a 1 Hz
health heartbeat throughout (CONTEXT: never exit because the device is absent)."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from jabuka.common import messages
from jabuka.common.clock import SystemClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
from jabuka.ingest import fastnet_main
from jabuka.ingest.fastnet_framing import chunks_from_capture, load_capture
from jabuka.ingest.fastnet_main import FastnetIngest
from jabuka.ingest.rawlog import RotatingAppendLog
from jabuka.sim.pty_replay import PtyFeeder

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fastnet"
EXAMPLE2 = FIX / "example2_fastnet_data.txt"
RAWFN = FIX / "rawfn-20260502-011827.txt"
HEALTH_KEYS = {
    "device",
    "state",
    "hint",
    "bytes_per_s",
    "frames_per_s",
    "bytes_in",
    "bytes_discarded",
    "frames_ok",
    "decode_errors",
    "unknown_ch",
    "reconnects",
    "last_error",
}


class UdpCollector:
    """Receives schema-v1 datagrams on 127.0.0.1:port in a background thread."""

    def __init__(self, port: int) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.2)
        self.msgs: list[tuple[float, dict]] = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.sock.recv(65536)
            except (TimeoutError, OSError):
                continue
            msg = messages.decode(data)
            if msg is not None:
                self.msgs.append((time.monotonic(), msg))

    def health(self, since: float = 0.0) -> list[dict]:
        return [m["health"] for t, m in list(self.msgs) if t >= since and m["type"] == "health"]

    def last_health(self, since: float = 0.0) -> dict | None:
        h = self.health(since)
        return h[-1] if h else None

    def close(self) -> None:
        self._stop.set()
        self._t.join(timeout=2)
        self.sock.close()


def _start_ingest(device: Path | str, port: int, data_dir: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jabuka.ingest.fastnet_main",
            "--device",
            str(device),
            "--udp",
            f"127.0.0.1:{port}",
            "--data-dir",
            str(data_dir),
        ]
    )


def _write_when_open(feeder: PtyFeeder, proc: subprocess.Popen, data: bytes, has_open, wait):
    wait(lambda: has_open(proc.pid, feeder.slave_path), timeout=5)
    time.sleep(0.3)  # termios setup + input flush happen right after the open
    feeder.write(data)


def test_unplug_and_replug_reconnects_without_exiting(
    tmp_path: Path, free_udp_port: int, wait_until, process_has_open, terminate
) -> None:
    rx = UdpCollector(free_udp_port)
    link = tmp_path / "fastnet"
    feeder = PtyFeeder(link)
    data = load_capture(EXAMPLE2)[:6000]
    proc = _start_ingest(link, free_udp_port, tmp_path / "var")
    try:
        _write_when_open(feeder, proc, data, process_has_open, wait_until)
        wait_until(lambda: (h := rx.last_health()) and h["device"] == "ok" and h["frames_ok"] > 0)
        frames_before = rx.last_health()["frames_ok"]

        feeder.close()  # unplug: reader sees EIO/EOF, symlink removed
        t_unplug = time.monotonic()
        h = wait_until(
            lambda: (h := rx.last_health(t_unplug)) and h["device"] == "missing" and h,
            timeout=3,
        )
        assert h["state"] == "missing"
        assert h["last_error"]
        time.sleep(1.5)
        assert proc.poll() is None, "ingest exited on unplug"
        assert rx.last_health()["device"] == "missing"

        feeder.reopen()  # replug: fresh pty, symlink re-pointed
        t_replug = time.monotonic()
        h = wait_until(
            lambda: (h := rx.last_health(t_replug)) and h["device"] == "ok" and h, timeout=3
        )
        assert h["reconnects"] >= 1
        _write_when_open(feeder, proc, data, process_has_open, wait_until)
        wait_until(lambda: rx.last_health()["frames_ok"] > frames_before, timeout=5)
        assert proc.poll() is None
    finally:
        terminate(proc)
        feeder.close()
        rx.close()
    assert proc.returncode == 0


def test_absent_device_at_start_does_not_exit(
    tmp_path: Path, free_udp_port: int, wait_until, process_has_open, terminate
) -> None:
    rx = UdpCollector(free_udp_port)
    link = tmp_path / "later"
    proc = _start_ingest(link, free_udp_port, tmp_path / "var")
    feeder = None
    try:
        h = wait_until(lambda: rx.last_health(), timeout=10)
        assert h["device"] == "missing" and h["state"] == "missing"
        time.sleep(1.5)
        assert proc.poll() is None, "ingest exited because the device was absent"
        assert len(rx.health()) >= 2

        feeder = PtyFeeder(link)  # adapter plugged in later
        t_plug = time.monotonic()
        wait_until(lambda: (h := rx.last_health(t_plug)) and h["device"] == "ok", timeout=3)
        _write_when_open(feeder, proc, load_capture(EXAMPLE2)[:6000], process_has_open, wait_until)
        wait_until(lambda: rx.last_health()["frames_ok"] > 0, timeout=5)
    finally:
        terminate(proc)
        if feeder is not None:
            feeder.close()
        rx.close()


def test_silent_bus_heartbeats_at_1hz_and_core_shows_silent(
    tmp_data_dir: Path, free_udp_port: int, wait_until, process_has_open, terminate
) -> None:
    ctx = CoreContext.create(SystemClock(), tmp_data_dir, udp_port=free_udp_port)
    app = create_app(ctx)
    with TestClient(app) as client, PtyFeeder() as feeder:
        proc = _start_ingest(feeder.slave_path, free_udp_port, tmp_data_dir)
        try:
            wait_until(lambda: process_has_open(proc.pid, feeder.slave_path), timeout=5)
            wait_until(lambda: ctx.stats["udp_rx"] > 0, timeout=5)
            rx0 = ctx.stats["udp_rx"]
            time.sleep(6.0)  # nothing written to the pty
            n = ctx.stats["udp_rx"] - rx0
            assert 5 <= n <= 8, f"{n} heartbeats in 6 s"
            diag = client.get("/api/state").json()
            fn = diag["health"]["fastnet"]
            assert fn["alive"] is True
            assert fn["device"] == "ok"
            assert fn["state"] == "silent"
            assert fn["hint"].startswith("NO BYTES")
            assert HEALTH_KEYS <= set(fn)
            assert proc.poll() is None
        finally:
            terminate(proc)


def _raw_bytes(raw_dir: Path) -> bytes:
    out = bytearray()
    for p in sorted(raw_dir.glob("fastnet-*.log")):
        for line in p.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3:
                out += bytes.fromhex(parts[2])
    return bytes(out)


def test_decoder_exception_keeps_raw_first(tmp_path: Path, monkeypatch) -> None:
    def boom(frame: bytes, *, awa_sign: int = 1):
        raise RuntimeError("decoder bug")

    monkeypatch.setattr(fastnet_main, "decode_to_values", boom)
    rawlog = RotatingAppendLog(tmp_path, "fastnet", min_free_bytes=0)
    sent: list[bytes] = []
    ingest = FastnetIngest(rawlog, sent.append)
    chunks = chunks_from_capture(EXAMPLE2)[:200]
    for c in chunks:
        ingest.on_chunk(c)  # must never raise
    errors_mid = ingest.decode_errors
    assert errors_mid > 0
    ingest.on_chunk(chunks[0])
    rawlog.close()
    assert ingest.decode_errors >= errors_mid
    assert _raw_bytes(tmp_path) == b"".join(chunks) + chunks[0]
    assert sent == []  # nothing decoded, nothing emitted
    ingest.send_heartbeat()  # heartbeat still works and reports the errors
    hb = json.loads(sent[-1])
    assert hb["type"] == "health"
    assert hb["health"]["decode_errors"] == ingest.decode_errors


def test_unknown_ref_layout_record_path(tmp_path: Path) -> None:
    rawlog = RotatingAppendLog(tmp_path, "fastnet", min_free_bytes=0)
    sent: list[bytes] = []
    ingest = FastnetIngest(rawlog, sent.append)
    for c in chunks_from_capture(RAWFN):
        ingest.on_chunk(c)
    rawlog.close()
    msgs = [json.loads(b) for b in sent]
    with_record = [
        m for m in msgs if any(v["path"] == "bandg.layoutRecord.0x49" for v in m["values"])
    ]
    assert with_record, "no layoutRecord published for ref-unknown heading"
    for m in with_record:
        by_path = {v["path"]: v for v in m["values"]}
        assert by_path["navigation.heading"]["ref"] == "?"
        rec = by_path["bandg.layoutRecord.0x49"]
        assert rec["value"] == "490600bee8e8"
        assert rec["unit"] is None and rec["ch"] == "0x49"
    # ref-known frames never carry the extra path
    for m in msgs:
        by_path = {v["path"]: v for v in m["values"]}
        hdg = by_path.get("navigation.heading")
        if hdg is not None and hdg["ref"] == "M":
            assert "bandg.layoutRecord.0x49" not in by_path
    # Tidal Set (0x84) is segment-display only in this capture: its record is published too
    assert any(any(v["path"] == "bandg.layoutRecord.0x84" for v in m["values"]) for m in msgs)
    # every message is still a valid schema-v1 datagram
    assert all(messages.decode(b) is not None for b in sent)


def test_heartbeat_payload_contract(tmp_path: Path) -> None:
    rawlog = RotatingAppendLog(tmp_path, "fastnet", min_free_bytes=0)
    t = [100.0]
    ingest = FastnetIngest(rawlog, lambda b: None, mono=lambda: t[0], wall=lambda: 1.7e9)
    h = ingest.health()
    assert set(h) == HEALTH_KEYS
    assert h["device"] == "missing" and h["state"] == "missing"
    ingest.device_open = True
    data = load_capture(EXAMPLE2)
    for i in range(0, 12000, 256):
        ingest.on_chunk(data[i : i + 256])
        t[0] += 256 / 2400
    h = ingest.health()
    rawlog.close()
    assert h["device"] == "ok"
    assert h["state"] == "ok", h
    assert h["frames_per_s"] > 0 and h["bytes_per_s"] > 0
    assert h["hint"].startswith("OK: ")
    assert isinstance(h["unknown_ch"], list) and len(h["unknown_ch"]) <= 50
