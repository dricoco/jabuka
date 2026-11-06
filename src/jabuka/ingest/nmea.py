"""Minimal NMEA 0183 parser (dev-only GPS path: NMEA file replay through jabuka-fake-gpsd).

On the Pi gpsd parses the receiver; this module only turns RMC/GGA sentences into gpsd-shaped
TPV/SKY dicts so recorded NMEA can drive the same gpsd client the core uses.
"""

from __future__ import annotations

import math
from typing import Any

KN_IN_MS = 1852.0 / 3600.0  # local copy: ingest code does not depend on common.units


def _checksum(body: str) -> int:
    c = 0
    for ch in body.encode("ascii"):
        c ^= ch
    return c


def parse_sentence(line: str) -> dict | None:
    """``$TTSSS,f1,f2,...*HH`` -> {"talker", "type", "fields"}; None on a bad/missing checksum,
    non-ASCII or malformed input. Any talker (GP/GN/GL/GA/BD) is accepted."""
    if not isinstance(line, str):
        return None
    s = line.strip()
    if len(s) > 200 or not s.startswith("$") or not s.isascii():
        return None
    star = s.rfind("*")
    if star < 0 or len(s) - star - 1 != 2:
        return None
    body, cks = s[1:star], s[star + 1 :]
    try:
        want = int(cks, 16)
    except ValueError:
        return None
    if _checksum(body) != want:
        return None
    parts = body.split(",")
    head = parts[0]
    if len(head) != 5 or not head.isalnum():
        return None
    return {"talker": head[:2], "type": head[2:], "fields": parts[1:]}


def _float(text: str) -> float | None:
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _coord(value: str, hemi: str, deg_digits: int) -> float | None:
    """ddmm.mmmm / dddmm.mmmm + N/S/E/W -> signed decimal degrees."""
    if len(value) < deg_digits + 2 or hemi not in ("N", "S", "E", "W"):
        return None
    deg = _float(value[:deg_digits])
    minutes = _float(value[deg_digits:])
    if deg is None or minutes is None or not 0.0 <= minutes < 60.0:
        return None
    v = deg + minutes / 60.0
    return -v if hemi in ("S", "W") else v


def _iso_time(ddmmyy: str, hhmmss: str) -> str | None:
    if len(ddmmyy) != 6 or not ddmmyy.isdigit() or len(hhmmss) < 6 or not hhmmss[:6].isdigit():
        return None
    dd, mm, yy = int(ddmmyy[:2]), int(ddmmyy[2:4]), int(ddmmyy[4:])
    year = 2000 + yy if yy < 80 else 1900 + yy
    h, mi = int(hhmmss[:2]), int(hhmmss[2:4])
    sec = _float(hhmmss[4:])
    if sec is None or not (1 <= dd <= 31 and 1 <= mm <= 12 and h < 24 and mi < 60 and sec < 61):
        return None
    whole = int(sec)
    ms = int(round((sec - whole) * 1000))
    return f"{year:04d}-{mm:02d}-{dd:02d}T{h:02d}:{mi:02d}:{whole:02d}.{ms:03d}Z"


class NmeaToGpsd:
    """Feed NMEA lines, get gpsd-shaped objects.

    GGA -> SKY {uSat, hdop} and remembers the fix quality. RMC status A -> TPV with time (from
    ddmmyy + hhmmss.ss), lat/lon, speed (kn -> m/s) and track (deg true); mode 3 when the last GGA
    had a fix, else 2. RMC status V -> TPV mode 1 without time.
    """

    def __init__(self, device: str = "nmea") -> None:
        self.device = device
        self._gga_fix = False
        self.rejected = 0

    def feed(self, line: str) -> list[dict]:
        s = parse_sentence(line)
        if s is None:
            if isinstance(line, str) and line.strip():
                self.rejected += 1
            return []
        f = s["fields"]
        if s["type"] == "GGA" and len(f) >= 8:
            return self._gga(f)
        if s["type"] == "RMC" and len(f) >= 9:
            return self._rmc(f)
        return []

    def _gga(self, f: list[str]) -> list[dict]:
        quality = f[5]
        self._gga_fix = quality.isdigit() and int(quality) > 0
        sky: dict[str, Any] = {"class": "SKY", "device": self.device}
        if f[6].isdigit():
            sky["uSat"] = int(f[6])
        hdop = _float(f[7])
        if hdop is not None:
            sky["hdop"] = hdop
        return [sky]

    def _rmc(self, f: list[str]) -> list[dict]:
        if f[1] != "A":
            return [{"class": "TPV", "device": self.device, "mode": 1}]
        tpv: dict[str, Any] = {
            "class": "TPV",
            "device": self.device,
            "mode": 3 if self._gga_fix else 2,
        }
        t = _iso_time(f[8], f[0])
        if t is not None:
            tpv["time"] = t
        lat = _coord(f[2], f[3], 2)
        lon = _coord(f[4], f[5], 3)
        if lat is not None and lon is not None:
            tpv["lat"] = lat
            tpv["lon"] = lon
        sog = _float(f[6])
        if sog is not None:
            tpv["speed"] = sog * KN_IN_MS
        track = _float(f[7])
        if track is not None:
            tpv["track"] = track
        return [tpv]
