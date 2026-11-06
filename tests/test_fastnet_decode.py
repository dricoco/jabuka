"""decode_to_values: SI values, ref-neutral M/T paths with ref, units, ch/disp, awa_sign."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from jabuka.ingest.fastnet_decode import ROUTED_CHANNELS, decode_to_values
from jabuka.ingest.fastnet_framing import CountingFramer, chunks_from_capture

FIX = Path(__file__).parent / "fixtures" / "fastnet"


def _cks(b: bytes) -> int:
    return (-sum(b)) & 0xFF


def _rec01(ch: int, value: float, decimals: int) -> bytes:
    return bytes([ch, (decimals << 6) | 0x01]) + struct.pack(">h", round(value * 10**decimals))


def _rec08(ch: int, value_int: int, layout_code: int) -> bytes:
    return bytes([ch, 0x08, ((layout_code & 0x7F) << 1) | ((value_int >> 8) & 1), value_int & 0xFF])


def _frame(body: bytes, to: int = 0xFF, frm: int = 0x05, cmd: int = 0x01) -> bytes:
    hdr = bytes([to, frm, len(body), cmd])
    return hdr + bytes([_cks(hdr)]) + body + bytes([_cks(body)])


def _all_values(name: str, awa_sign: int = 1) -> list[dict]:
    fr = CountingFramer()
    out: list[dict] = []
    for c in chunks_from_capture(FIX / name):
        for f in fr.feed(c):
            out.extend(decode_to_values(f, awa_sign=awa_sign).values)
    return out


def test_synthetic_frame_values_units_and_ref() -> None:
    body = (
        _rec01(0x41, 4.77, 2)
        + _rec01(0x51, -35, 0)
        + _rec01(0x4F, 6.3, 1)
        + _rec08(0x49, 287, 0x66)
        + _rec01(0x59, 42, 0)
    )
    res = decode_to_values(_frame(body))
    assert res.error is None
    by = {v["path"]: v for v in res.values}
    assert by["navigation.speedThroughWater"]["unit"] == "m/s"
    assert by["navigation.speedThroughWater"]["value"] == pytest.approx(4.77 * 1852 / 3600, 1e-3)
    assert by["environment.wind.angleApparent"]["unit"] == "rad"
    assert by["environment.wind.angleApparent"]["value"] == pytest.approx(math.radians(-35))
    assert by["environment.wind.angleApparent"]["ch"] == "0x51"
    assert "disp" in by["environment.wind.angleApparent"]
    hdg = by["navigation.heading"]
    assert hdg["ref"] == "M"
    assert hdg["ch"] == "0x49"
    assert hdg["value"] == pytest.approx(math.radians(287))
    assert "navigation.headingMagnetic" not in by


def test_awa_sign_flips_wind_angles() -> None:
    body = _rec01(0x51, -35, 0) + _rec01(0x59, 42, 0) + _rec01(0x41, 4.77, 2)
    pos = {v["path"]: v["value"] for v in decode_to_values(_frame(body)).values}
    neg = {v["path"]: v["value"] for v in decode_to_values(_frame(body), awa_sign=-1).values}
    assert neg["environment.wind.angleApparent"] == pytest.approx(
        -pos["environment.wind.angleApparent"]
    )
    assert neg["environment.wind.angleTrueWater"] == pytest.approx(
        -pos["environment.wind.angleTrueWater"]
    )
    assert neg["navigation.speedThroughWater"] == pos["navigation.speedThroughWater"]


def test_rawfn_heading_has_m_and_unknown_ref() -> None:
    vals = _all_values("rawfn-20260502-011827.txt")
    refs = {v["ref"] for v in vals if v["path"] == "navigation.heading"}
    assert "M" in refs
    assert "?" in refs
    assert "T" not in refs  # never silently True


def test_routed_paths_are_ref_neutral() -> None:
    vals = _all_values("example2_fastnet_data.txt")
    paths = {v["path"] for v in vals}
    for neutral in ROUTED_CHANNELS.values():
        assert neutral in paths
        assert neutral + "Magnetic" not in paths
        assert neutral + "True" not in paths
    for v in vals:
        if v["path"] in ROUTED_CHANNELS.values():
            assert v["ref"] in ("M", "T", "?")


def test_example2_core_paths() -> None:
    vals = _all_values("example2_fastnet_data.txt")
    by = {}
    for v in vals:
        by.setdefault(v["path"], v)
    assert by["environment.wind.angleApparent"]["unit"] == "rad"
    assert by["navigation.speedThroughWater"]["unit"] == "m/s"
    assert by["navigation.heading"]["ref"] == "M"


def test_latlon_frames_yield_position() -> None:
    vals = _all_values("example2_fastnet_data.txt")
    pos = [v for v in vals if v["path"] == "navigation.position"]
    assert pos
    p = pos[0]["value"]
    assert set(p) == {"latitude", "longitude"}
    assert p["latitude"] == pytest.approx(-33.868)
    assert p["longitude"] == pytest.approx(151.2335)


def test_non_broadcast_commands_yield_nothing() -> None:
    light = _frame(b"\x01\x02", cmd=0xC9)
    assert decode_to_values(light).values == []
    pilot = _frame(b"\x01\x02\x03", cmd=0xD3)
    assert decode_to_values(pilot).values == []


def test_decode_error_reported_without_values() -> None:
    # channel header claims a format whose data is missing -> pyfastnet returns {"error": ...}
    bad = _frame(bytes([0x41, 0x01, 0x00]))
    res = decode_to_values(bad)
    assert res.error is not None
    assert res.values == []


def test_unknown_channels_collected() -> None:
    vals_unknown = []
    fr = CountingFramer()
    for c in chunks_from_capture(FIX / "example2_fastnet_data.txt"):
        for f in fr.feed(c):
            vals_unknown.extend(decode_to_values(f).unknown_ch)
    for ch in vals_unknown:
        assert ch.startswith("0x")
