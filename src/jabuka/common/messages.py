"""UDP message schema v1 between producers (ingest, replay, sim) and the core.

One JSON object per datagram, at most MAX_DATAGRAM bytes, sent to 127.0.0.1:DEFAULT_UDP_PORT.

Delta message::

    {"v": 1, "type": "delta", "src": "fastnet", "t_mono": 81234.512, "t_wall": 1762470000.123,
     "values": [{"path": "environment.wind.angleApparent", "value": -0.61, "unit": "rad"},
                {"path": "navigation.heading", "value": 5.0, "unit": "rad", "ref": "M",
                 "ch": "0x49", "disp": "287°M"}],
     "bus": {"bytes_in": 123456, ...},      # optional, stored as health[src] by the core
     "t_sim": 1762470000.0}                 # optional, replay/sim UTC epoch (drives SimClock)

Health message::

    {"v": 1, "type": "health", "src": "fastnet", "t_mono": ..., "t_wall": ..., "health": {...}}

decode() never raises: anything malformed returns None and the caller counts a rejection.
"""

from __future__ import annotations

import json
import math
from typing import Any

SCHEMA_VERSION = 1
MAX_DATAGRAM = 8192
DEFAULT_UDP_PORT = 47100

_REFS = ("M", "T", "?")


def delta_message(
    src: str,
    values: list[dict],
    t_mono: float,
    t_wall: float,
    *,
    bus: dict | None = None,
    t_sim: float | None = None,
) -> dict:
    """Build a delta message (decoded values from one source)."""
    msg: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "type": "delta",
        "src": src,
        "t_mono": t_mono,
        "t_wall": t_wall,
        "values": values,
    }
    if bus is not None:
        msg["bus"] = bus
    if t_sim is not None:
        msg["t_sim"] = t_sim
    return msg


def health_message(
    src: str,
    health: dict,
    t_mono: float,
    t_wall: float,
    *,
    t_sim: float | None = None,
) -> dict:
    """Build a health/heartbeat message for one source."""
    msg: dict[str, Any] = {
        "v": SCHEMA_VERSION,
        "type": "health",
        "src": src,
        "t_mono": t_mono,
        "t_wall": t_wall,
        "health": health,
    }
    if t_sim is not None:
        msg["t_sim"] = t_sim
    return msg


def encode(msg: dict) -> bytes:
    """Compact JSON encoding. Raises ValueError if the result exceeds MAX_DATAGRAM or contains
    non-finite floats (allow_nan=False)."""
    data = json.dumps(msg, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_DATAGRAM:
        raise ValueError(f"message too large: {len(data)} > {MAX_DATAGRAM} bytes")
    return data


def _reject_constant(name: str) -> Any:
    # json.loads accepts NaN/Infinity/-Infinity by default; refuse them outright.
    raise ValueError(f"non-finite constant {name}")


def _all_finite(obj: Any, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return True
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_all_finite(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_finite(v, depth + 1) for v in obj)
    return False


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _valid_value_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        return False
    if "value" not in entry:
        return False
    value = entry["value"]
    if not (value is None or isinstance(value, (int, float, str, dict, bool))):
        return False
    unit = entry.get("unit")
    if unit is not None and not isinstance(unit, str):
        return False
    ref = entry.get("ref")
    if ref is not None and ref not in _REFS:
        return False
    for key in ("ch", "disp"):
        v = entry.get(key)
        if v is not None and not isinstance(v, str):
            return False
    return True


def decode(data: bytes) -> dict | None:
    """Parse and validate one datagram. Returns None for anything malformed:
    oversize, bad UTF-8/JSON, v != 1, missing/non-str src, bad values shape, non-finite floats."""
    try:
        if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_DATAGRAM:
            return None
        msg = json.loads(bytes(data).decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    try:
        if not isinstance(msg, dict):
            return None
        if msg.get("v") != SCHEMA_VERSION or isinstance(msg.get("v"), bool):
            return None
        src = msg.get("src")
        if not isinstance(src, str) or not src:
            return None
        for key in ("t_mono", "t_wall"):
            if key in msg and not _is_number(msg[key]):
                return None
        if "t_sim" in msg and msg["t_sim"] is not None and not _is_number(msg["t_sim"]):
            return None
        if "values" in msg:
            values = msg["values"]
            if not isinstance(values, list) or not all(_valid_value_entry(e) for e in values):
                return None
        for key in ("bus", "health"):
            if key in msg and not isinstance(msg[key], dict):
                return None
        if "values" not in msg and "health" not in msg:
            return None
        if not _all_finite(msg):
            return None
        return msg
    except Exception:  # defensive: decode must never raise into the bus listener
        return None
