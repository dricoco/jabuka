"""Malformed datagrams and random bus bytes can't crash the core or the ingest."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path

from jabuka.common import messages
from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.ingest.fastnet_framing import MAX_BUF, load_capture
from jabuka.ingest.fastnet_main import FastnetIngest
from jabuka.ingest.rawlog import RotatingAppendLog

HOSTILE = [
    os.urandom(64),
    b"\x00\xff\xfe",
    b"{not json",
    b'{"v":1,"src":"x","values":[{"path":"a","value":1}]' + b" " * 9000 + b"}",
    b'{"v":2,"src":"x","values":[{"path":"a","value":1}]}',
    b'{"v":1,"src":"x","values":[{"path":"a","value":NaN}]}',
    b'{"v":1,"src":"x","values":[{"path":"a","value":Infinity}]}',
    b'{"v":1,"src":"x","values":[{"path":"a","value":{"latitude":-Infinity,"longitude":1}}]}',
    b'{"v":1,"src":"x","values":{"path":"a","value":1}}',
    b'{"v":1,"src":"x","values":[1,2,3]}',
    b'{"v":1,"src":"x","values":[{"value":1}]}',
    b'{"v":1,"values":[{"path":"a","value":1}]}',
    b'{"v":1,"src":5,"values":[{"path":"a","value":1}]}',
    b"[1,2,3]",
    b'"just a string"',
    b'{"v":1,"src":"x","t_mono":"soon","values":[]}',
    b'{"v":1,"src":"x","values":[{"path":"a","value":1,"ref":"Q"}]}',
    b'{"v":1,"src":"x","health":[1]}',
    b"[" * 5000 + b"]" * 5000,
]


def test_decode_rejects_every_hostile_payload() -> None:
    for payload in HOSTILE:
        assert messages.decode(payload) is None, payload[:80]


async def test_core_survives_hostile_datagrams(tmp_data_dir: Path, free_udp_port: int) -> None:
    clock = SimClock(start_utc=1_794_000_000.0)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port)
    await ctx.startup()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for payload in HOSTILE:
                s.sendto(payload, ("127.0.0.1", free_udp_port))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if ctx.stats["udp_rejected"] >= len(HOSTILE):
                    break
            assert ctx.stats["udp_rejected"] == len(HOSTILE)
            assert ctx.stats["udp_rx"] == 0
            good = messages.encode(
                messages.delta_message(
                    "fastnet",
                    [{"path": "navigation.speedThroughWater", "value": 3.1, "unit": "m/s"}],
                    1.0,
                    2.0,
                )
            )
            s.sendto(good, ("127.0.0.1", free_udp_port))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if ctx.stats["udp_rx"] >= 1:
                    break
    finally:
        await ctx.shutdown()
    assert ctx.stats["udp_rx"] == 1
    assert ctx.stats["handler_errors"] == 0
    latest = ctx.state.latest("navigation.speedThroughWater")
    assert latest is not None and latest["value"] == 3.1


def _raw_bytes(directory: Path) -> bytes:
    return b"".join(load_capture(p) for p in sorted(directory.glob("fastnet-*.log")))


def test_ingest_survives_1mb_urandom(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    rawlog = RotatingAppendLog(raw_dir, "fastnet", min_free_bytes=0)
    sent: list[bytes] = []
    ingest = FastnetIngest(rawlog, sent.append)
    data = os.urandom(1024 * 1024)
    for i in range(0, len(data), 4096):
        ingest.on_chunk(data[i : i + 4096])
        assert len(ingest.framer.buf) <= MAX_BUF
    rawlog.close()
    assert _raw_bytes(raw_dir) == data
    assert ingest.framer.stats.bytes_in == len(data)
    for d in sent:
        assert messages.decode(d) is not None


def test_ingest_send_failure_never_raises(tmp_path: Path, capture_bytes) -> None:
    rawlog = RotatingAppendLog(tmp_path, "fastnet", min_free_bytes=0)

    def broken_send(_: bytes) -> None:
        raise OSError("network is down")

    ingest = FastnetIngest(rawlog, broken_send)
    data = capture_bytes("big.txt")
    ingest.on_chunk(data[:4096])
    rawlog.close()
    assert ingest.send_errors > 0


def test_ingest_decoder_exception_counted(tmp_path: Path, capture_bytes, monkeypatch) -> None:
    from jabuka.ingest import fastnet_main

    def boom(frame: bytes, *, awa_sign: int = 1):
        raise RuntimeError("decoder bug")

    monkeypatch.setattr(fastnet_main, "decode_to_values", boom)
    rawlog = RotatingAppendLog(tmp_path, "fastnet", min_free_bytes=0)
    ingest = FastnetIngest(rawlog, lambda b: None)
    data = capture_bytes("big.txt")[:4096]
    ingest.on_chunk(data)  # must not raise
    rawlog.close()
    assert ingest.decode_errors > 0
    assert _raw_bytes(tmp_path) == data  # raw-first even when decoding blows up
    stats = json.loads(json.dumps(ingest.bus_stats()))
    assert stats["decode_errors"] == ingest.decode_errors
