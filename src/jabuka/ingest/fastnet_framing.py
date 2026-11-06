"""Counting Fastnet framer: the exact pyfastnet FrameBuffer algorithm, plus error counters.

pyfastnet's FrameBuffer silently drops one byte per checksum failure and exposes no counters, so
the ingest and fastnet-probe use this framer and hand valid frames to pyfastnet's decoders.
Equivalence with FrameBuffer is proven on 10 real captures (tests/test_framing_equivalence.py).

Frame = [to, from, body_size, command, header_cks, body..., body_cks], length 5 + body_size + 1.
Checksum = (-sum(bytes)) & 0xFF. Wait for the full length before checking either checksum; on
failure drop exactly 1 byte. The buffer is capped at MAX_BUF (oldest bytes dropped).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

BROADCAST = 0x01
LATLON = 0x03
KEEP_ALIVE = 0x0C
LIGHT = 0xC9
MAX_BUF = 8192


def _cks(b: bytes | bytearray) -> int:
    return (-sum(b)) & 0xFF


@dataclass
class FramerStats:
    bytes_in: int = 0
    bytes_discarded: int = 0  # resync drops + buffer trims ("checksum failure" proxy)
    frames_ok: int = 0
    by_command: Counter = field(default_factory=Counter)


class CountingFramer:
    def __init__(self) -> None:
        self.buf = bytearray()
        self.stats = FramerStats()

    def feed(self, data: bytes) -> list[bytes]:
        """Add bytes, return every complete valid frame (KEEP_ALIVE frames are counted, not
        returned)."""
        s = self.stats
        s.bytes_in += len(data)
        self.buf += data
        if len(self.buf) > MAX_BUF:
            drop = len(self.buf) - MAX_BUF
            s.bytes_discarded += drop
            del self.buf[:drop]
        out: list[bytes] = []
        buf = self.buf
        while len(buf) >= 6:
            n = 5 + buf[2] + 1
            if len(buf) < n:
                break
            if _cks(buf[0:4]) != buf[4] or _cks(buf[5 : n - 1]) != buf[n - 1]:
                del buf[0]
                s.bytes_discarded += 1
                continue
            frame = bytes(buf[:n])
            del buf[:n]
            s.frames_ok += 1
            s.by_command[frame[3]] += 1
            if frame[3] != KEEP_ALIVE:
                out.append(frame)
        return out


def _parse_capture_line(line: str) -> bytes:
    parts = line.split()
    if not parts:
        return b""
    # Jabuka raw log: "<t_mono> <t_wall> <hex>"; pyfastnet/fastnet2ip: "<hex>"
    hexpart = parts[-1] if len(parts) == 3 else "".join(parts)
    return bytes.fromhex(hexpart)


def load_capture(path: str | Path) -> bytes:
    """Load a capture: hex-per-line (pyfastnet/fastnet2ip) or a Jabuka raw log
    ("<t_mono> <t_wall> <hex>" per line). Blank lines are ignored; a torn (non-hex) last line of
    a raw log is skipped."""
    raw = Path(path).read_bytes()
    lines = raw.split(b"\n")
    out = bytearray()
    for i, bline in enumerate(lines):
        line = bline.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            out += _parse_capture_line(line)
        except ValueError:
            if i == len(lines) - 1:
                continue  # torn final line (crash mid-write)
            raise
    return bytes(out)


def chunks_from_capture(path: str | Path) -> list[bytes]:
    """Like load_capture but keeps the per-line bursts (for chunk-faithful replays/tests)."""
    out: list[bytes] = []
    for bline in Path(path).read_bytes().split(b"\n"):
        line = bline.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            chunk = _parse_capture_line(line)
        except ValueError:
            continue
        if chunk:
            out.append(chunk)
    return out
