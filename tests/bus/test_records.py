"""Broadcast record walker + layout code extraction, pinned against pyfastnet decode_frame.

fastnet_records uses pyfastnet's private _FORMAT_SIZE_MAP (pyfastnet 3.2.1 is pinned): these tests
fail loudly if an upgrade changes the record layout.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import fastnet_decoder
import pytest
from fastnet_decoder import interpreter as interp
from jabuka.ingest.fastnet_records import iter_records, layout_code, record_hex

from jabuka.ingest.fastnet_framing import BROADCAST, CountingFramer, chunks_from_capture

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fastnet"
CAPTURES = sorted(p.name for p in FIX.glob("*.txt"))


def _broadcast_frames(name: str) -> list[bytes]:
    framer = CountingFramer()
    frames: list[bytes] = []
    for chunk in chunks_from_capture(FIX / name):
        frames += framer.feed(chunk)
    return [f for f in frames if f[3] == BROADCAST]


def test_all_ten_fixtures_present() -> None:
    assert len(CAPTURES) == 10


@pytest.mark.parametrize("name", CAPTURES)
def test_iter_records_matches_decode_frame(name: str) -> None:
    frames = _broadcast_frames(name)
    assert frames
    checked = 0
    for frame in frames:
        decoded = fastnet_decoder.decode_frame(frame)
        if "error" in decoded:
            continue
        recs = list(iter_records(frame))
        names = {interp._lookup_or_unknown(interp.CHANNEL_LOOKUP, ch) for ch, _, _ in recs}
        assert names == set(decoded["values"]), frame.hex()
        ids = {f"0x{ch:02X}" for ch, _, _ in recs}
        reported = {e["channel_id"] for e in decoded["values"].values() if isinstance(e, dict)}
        assert reported <= ids, frame.hex()
        # the records tile the body exactly
        body_len = sum(2 + len(data) for _, _, data in recs)
        assert body_len == frame[2], frame.hex()
        # and each record decodes to what decode_frame reported
        for ch, fmt, data in recs:
            name_ = interp._lookup_or_unknown(interp.CHANNEL_LOOKUP, ch)
            assert interp.decode_channel_value(ch, fmt, data) == decoded["values"][name_] or (
                sum(1 for c, _, _ in recs if c == ch) > 1  # repeated channel: last one wins
            )
        checked += 1
    assert checked > 100


def test_iter_records_non_broadcast_and_truncated() -> None:
    assert list(iter_records(b"")) == []
    assert list(iter_records(bytes([0xFF, 0x05, 0x02, 0x0C, 0x00, 0x00, 0x00, 0x00]))) == []
    # Broadcast whose second record claims 2 data bytes but has 1: first record only
    body = bytes([0x41, 0x01, 0x00, 0x10, 0x51, 0x01, 0x00])
    frame = bytes([0xFF, 0x05, len(body), 0x01, 0x00]) + body + b"\x00"
    assert list(iter_records(frame)) == [(0x41, 0x01, bytes([0x00, 0x10]))]


def test_layout_code_heading_example2_is_0x66() -> None:
    codes = Counter()
    for frame in _broadcast_frames("example2_fastnet_data.txt"):
        for ch, fmt, data in iter_records(frame):
            if ch == 0x49:
                codes[layout_code(fmt, data)] += 1
    assert codes and set(codes) == {0x66}


def test_layout_code_rawfn_heading_has_0x66_and_other_records() -> None:
    """rawfn has Heading as 0x66 (°M) and as format-0x06 segment-display records (" OFF"): the
    latter carry no layout field at all, so layout_code is None and the raw record is kept."""
    codes: Counter = Counter()
    raw: set[str] = set()
    for frame in _broadcast_frames("rawfn-20260502-011827.txt"):
        for ch, fmt, data in iter_records(frame):
            if ch == 0x49:
                code = layout_code(fmt, data)
                codes[code] += 1
                if code != 0x66:
                    raw.add(record_hex(ch, fmt, data))
    assert codes[0x66] > 0
    assert len(codes) >= 2
    assert None in codes
    assert raw == {"490600bee8e8"}


def test_layout_code_templates() -> None:
    # 0x08 layoutBits: byte0 bits 7..1
    assert layout_code(0x08, bytes([0xCC, 0x29])) == 0x66
    assert layout_code(0x88, bytes([0xCC, 0x29])) == 0x66  # divisor bits ignored
    # 0x03 layoutByte 0
    assert layout_code(0x03, bytes([0x66, 0x10])) == 0x66
    # 0x07 layoutByte 1
    assert layout_code(0x07, bytes([0x00, 0x42, 0x00, 0x10])) == 0x42
    # no layout in the template
    assert layout_code(0x01, bytes([0x00, 0x10])) is None
    assert layout_code(0x06, bytes([0x00, 0xBE, 0xE8, 0xE8])) is None
    # short data never raises
    assert layout_code(0x07, b"") is None
