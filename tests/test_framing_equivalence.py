"""CountingFramer + pyfastnet decode/project must equal pyfastnet FrameBuffer(project=True)."""

from __future__ import annotations

from pathlib import Path

import fastnet_decoder
import pytest
from fastnet_decoder import FrameBuffer

from jabuka.ingest.fastnet_framing import (
    BROADCAST,
    LATLON,
    LIGHT,
    CountingFramer,
    chunks_from_capture,
    load_capture,
)

FIX = Path(__file__).parent / "fixtures" / "fastnet"

GOLDEN = {
    "big.txt": 937,
    "big_with_ap_actions.txt": 2018,
    "example1_fastnet_data.txt": 2630,
    "example2_fastnet_data.txt": 2801,
    "heel-port.txt": 164,
    "heel-stb.txt": 422,
    "trim-neg.txt": 161,
    "trim-pos.txt": 189,
    "ap_backlight_20260514.txt": 2433,
    "rawfn-20260502-011827.txt": 3392,
}


def _framebuffer_projected(chunks: list[bytes]) -> list[dict]:
    """Reference: feed chunk by chunk (like a serial read loop) and drain after each chunk so the
    1000-entry queue never overflows."""
    fb = FrameBuffer(project=True)
    out: list[dict] = []
    for c in chunks:
        fb.add_to_buffer(c)
        fb.get_complete_frames()
        while not fb.frame_queue.empty():
            out.append(fb.frame_queue.get()["values"])
    return out


def _counting_projected(chunks: list[bytes]) -> tuple[list[dict], CountingFramer]:
    """Mirror FrameBuffer.decode_and_queue_frame dispatch exactly (frame_buffer.py)."""
    fr = CountingFramer()
    out: list[dict] = []
    for c in chunks:
        for frame in fr.feed(c):
            cmd = frame[3]
            if cmd == BROADCAST:
                decoded = fastnet_decoder.decode_frame(frame)
            elif cmd == LATLON:
                decoded = fastnet_decoder.decode_ascii_frame(frame)
            elif cmd == LIGHT:
                decoded = fastnet_decoder.decode_light_frame(frame)
            else:
                continue  # pilot / unknown commands are never queued
            if not (decoded and "values" in decoded):
                continue
            values = fastnet_decoder.project(decoded)
            if not values:
                continue
            out.append(values)
    return out, fr


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_counting_framer_equals_framebuffer(name: str) -> None:
    chunks = chunks_from_capture(FIX / name)
    assert b"".join(chunks) == load_capture(FIX / name)
    ref = _framebuffer_projected(chunks)
    ours, fr = _counting_projected(chunks)
    assert len(ref) == GOLDEN[name]
    assert len(ours) == GOLDEN[name]
    assert ours == ref
    assert fr.stats.bytes_in == sum(map(len, chunks))
    assert fr.stats.frames_ok >= len(ours)
