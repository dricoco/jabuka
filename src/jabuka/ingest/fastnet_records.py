"""Raw record access for Fastnet Broadcast frames.

A Broadcast body (frame[5:-1]) is a run of records ``[channel_id, format_byte, data...]``. The
data length depends on the low nibble of the format byte, from pyfastnet's format size table
(``fastnet_decoder.interpreter._FORMAT_SIZE_MAP``: a private name in the pinned pyfastnet 3.2.1,
pinned by tests/bus/test_records.py against decode_frame on every fixture).

layout_code() returns the raw layout (segment) code of a record, read from the format template's
``layoutBits`` (byte/mask/shiftRight) or ``layoutByte`` in pyfastnet's fastnet.json. It is how
the unknown "°T" code gets identified from a boat capture (RESEARCH Open Question 2).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastnet_decoder import interpreter as _interp

from jabuka.ingest.fastnet_framing import BROADCAST

_FORMAT_SIZE: dict[int, int] = dict(_interp._FORMAT_SIZE_MAP)
_TEMPLATES: dict[str, dict] = dict(_interp.SCHEMA["formatTemplates"])


def iter_records(frame: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Yield (channel_id, format_byte, data_bytes) for each record of a Broadcast frame.

    Non-Broadcast frames yield nothing. A truncated trailing record (which decode_frame reports
    as an error) ends the iteration without raising.
    """
    if len(frame) < 6 or frame[3] != BROADCAST:
        return
    body = bytes(frame[5:-1])
    i = 0
    n = len(body)
    while i + 1 < n:
        channel_id = body[i]
        format_byte = body[i + 1]
        i += 2
        size = _FORMAT_SIZE.get(format_byte & 0x0F, 0)
        if i + size > n:
            return
        yield channel_id, format_byte, body[i : i + size]
        i += size


def layout_code(format_byte: int, data_bytes: bytes) -> int | None:
    """Raw layout code of a record, or None when its format template has no layout field."""
    template = _TEMPLATES.get(f"0x{format_byte & 0x0F:02X}")
    if not isinstance(template, dict):
        return None
    try:
        bits = template.get("layoutBits")
        if isinstance(bits, dict):
            mask = int(str(bits["mask"]), 16)
            return (data_bytes[int(bits["byte"])] & mask) >> int(bits.get("shiftRight", 0))
        idx = template.get("layoutByte")
        if idx is not None:
            return data_bytes[int(idx)]
    except (IndexError, KeyError, ValueError, TypeError):
        return None
    return None


def record_hex(channel_id: int, format_byte: int, data_bytes: bytes) -> str:
    """The record as it appears on the wire, lower-case hex (channel, format, data)."""
    return (bytes([channel_id & 0xFF, format_byte & 0xFF]) + bytes(data_bytes)).hex()
