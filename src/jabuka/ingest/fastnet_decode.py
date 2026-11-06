"""pyfastnet decode -> normalized value entries (SI units, Signal K-style paths, M/T ref kept).

pyfastnet's projection routes Heading (0x49), True Wind Direction (0x6D) and Tidal Set (0x84) to
"...Magnetic" whenever the layout byte is not "°T", and the "°T" code is unknown upstream. So this
module uses the rich decode (which keeps ``layout``) and publishes those three channels under a
ref-neutral path with an explicit ``ref``: "M" for layout "°M", "T" for "°T", "?" otherwise.
The core never assumes True; conversion happens once, in Phase 2 (WIND-03).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import fastnet_decoder

from jabuka.ingest.fastnet_framing import BROADCAST, LATLON

# pyfastnet installs an INFO stderr handler on import and warns on buffer trims: keep journald
# quiet and rely on our own counters (RESEARCH Pitfall 10).
fastnet_decoder.set_log_level("WARNING")

ROUTED_CHANNELS: dict[int, str] = {
    0x49: "navigation.heading",
    0x6D: "environment.wind.direction",
    0x84: "environment.current.set",
}

SIGNED_WIND_ANGLES = ("environment.wind.angleApparent", "environment.wind.angleTrueWater")


@dataclass
class DecodeResult:
    values: list[dict] = field(default_factory=list)
    unknown_ch: list[str] = field(default_factory=list)
    error: str | None = None
    command: int = 0


def _ref_for_layout(layout: Any) -> str:
    if layout == "°M":
        return "M"
    if layout == "°T":
        return "T"
    return "?"


def _same(a: Any, b: Any) -> bool:
    if a is b or a == b:
        return True
    if isinstance(a, float) and isinstance(b, float):
        return math.isnan(a) and math.isnan(b)
    return False


def _finite(v: Any) -> bool:
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, dict):
        return all(_finite(x) for x in v.values())
    return True


def _channel_int(entry: dict) -> int | None:
    ch = entry.get("channel_id")
    if not isinstance(ch, str):
        return None
    try:
        return int(ch, 16)
    except ValueError:
        return None


def decode_to_values(frame: bytes, *, awa_sign: int = 1) -> DecodeResult:
    """Decode one valid frame (from CountingFramer) into value entries.

    BROADCAST -> fastnet_decoder.decode_frame, LATLON -> decode_ascii_frame; other commands
    (Light Intensity, pilot traffic, ...) yield no values.
    """
    command = frame[3] if len(frame) > 3 else 0
    if command == BROADCAST:
        decoded = fastnet_decoder.decode_frame(frame)
    elif command == LATLON:
        decoded = fastnet_decoder.decode_ascii_frame(frame)
    else:
        return DecodeResult(command=command)

    if not isinstance(decoded, dict) or "error" in decoded or "values" not in decoded:
        err = decoded.get("error") if isinstance(decoded, dict) else None
        return DecodeResult(error=str(err or "decode failed"), command=command)

    projected: dict[str, Any] = fastnet_decoder.project(decoded)
    if not projected:
        return DecodeResult(command=command)

    # Map every projected path back to the rich entry that produced it, by projecting each entry
    # alone. For depth fallbacks (several channels -> one path) the entry whose own projection
    # equals the frame-level winner is chosen.
    source: dict[str, dict] = {}
    for name, entry in decoded["values"].items():
        if not isinstance(entry, dict):
            continue
        single = fastnet_decoder.project(
            {"command": decoded.get("command"), "values": {name: entry}}
        )
        for path, v in single.items():
            if path in projected and path not in source and _same(v, projected[path]):
                source[path] = entry

    values: list[dict] = []
    unknown: list[str] = []
    for path, value in projected.items():
        if not _finite(value):
            continue
        entry = source.get(path)
        unit = fastnet_decoder.unit_for(path) or None
        out_path = path
        item: dict[str, Any] = {}
        if entry is not None:
            ch = _channel_int(entry)
            if ch in ROUTED_CHANNELS:
                out_path = ROUTED_CHANNELS[ch]
                item["ref"] = _ref_for_layout(entry.get("layout"))
            if entry.get("channel_id"):
                item["ch"] = str(entry["channel_id"])
            if entry.get("display_text") is not None:
                item["disp"] = str(entry["display_text"])
        if path.startswith("bandg.unknown."):
            unknown.append(path.rsplit(".", 1)[-1])
        if out_path in SIGNED_WIND_ANGLES and isinstance(value, (int, float)):
            value = value * awa_sign
        values.append({"path": out_path, "value": value, "unit": unit, **item})
    return DecodeResult(values=values, unknown_ch=unknown, command=command)
