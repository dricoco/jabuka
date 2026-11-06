"""Minimal Fastnet encoder for simulation and tests (never used against a real bus).

Format 0x01: signed int16 big-endian, divisor code in the top two bits of the format byte
(0 -> 1, 1 -> 10, 2 -> 100, 3 -> 1000). Format 0x08: byte0 = (layout << 1) | bit8, byte1 = low 8
bits of a 9-bit unsigned value; layout 0x66 = "°M". Frame = [to, from, len(body), cmd, cks(hdr)]
+ body + [cks(body)], cks = (-sum) & 0xFF. Round-trip verified against pyfastnet 3.2.1
(tests/sim/test_fastnet_encode.py).
"""

from __future__ import annotations

import struct

LAYOUT_DEG_M = 0x66


def cks(b: bytes) -> int:
    return (-sum(b)) & 0xFF


def rec01(ch: int, value: float, decimals: int) -> bytes:
    """Channel record, format 0x01: value * 10**decimals as signed int16 (ValueError if it does
    not fit)."""
    if not 0 <= decimals <= 3:
        raise ValueError(f"decimals must be 0..3, got {decimals}")
    raw = round(value * 10**decimals)
    if not -32768 <= raw <= 32767:
        raise ValueError(f"value {value} out of int16 range at {decimals} decimals")
    return bytes([ch & 0xFF, (decimals << 6) | 0x01]) + struct.pack(">h", raw)


def rec08(ch: int, value_int: int, layout_code: int = LAYOUT_DEG_M) -> bytes:
    """Channel record, format 0x08: 9-bit unsigned value + 7-bit layout (0x66 = °M)."""
    if not 0 <= value_int <= 511:
        raise ValueError(f"value {value_int} out of 9-bit range")
    return bytes(
        [ch & 0xFF, 0x08, ((layout_code & 0x7F) << 1) | ((value_int >> 8) & 1), value_int & 0xFF]
    )


def frame(body: bytes, to: int = 0xFF, frm: int = 0x05, cmd: int = 0x01) -> bytes:
    """Wrap channel records in a Fastnet frame (default: Broadcast from node 0x05)."""
    if len(body) > 255:
        raise ValueError("body longer than 255 bytes")
    hdr = bytes([to & 0xFF, frm & 0xFF, len(body), cmd & 0xFF])
    return hdr + bytes([cks(hdr)]) + body + bytes([cks(body)])
