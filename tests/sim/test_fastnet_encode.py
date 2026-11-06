"""Fastnet encoder round-trip through the real framer and decoder (RESEARCH Pattern 6 values)."""

from __future__ import annotations

import pytest

from jabuka.ingest.fastnet_decode import decode_to_values
from jabuka.ingest.fastnet_encode import frame, rec01, rec08
from jabuka.ingest.fastnet_framing import CountingFramer


def _vals(f: bytes) -> dict[str, dict]:
    res = decode_to_values(f)
    assert res.error is None
    return {v["path"]: v for v in res.values}


def test_research_example_round_trip() -> None:
    body = (
        rec01(0x41, 4.77, 2)
        + rec01(0x51, -35, 0)
        + rec01(0x4F, 6.3, 1)
        + rec08(0x49, 287, 0x66)
        + rec01(0x59, 42, 0)
    )
    f = frame(body)
    framer = CountingFramer()
    frames = framer.feed(f + f)  # both frames validate in the real framer
    assert frames == [f, f]
    assert framer.stats.frames_ok == 2
    vals = _vals(f)
    assert vals["navigation.speedThroughWater"]["value"] == pytest.approx(2.45389788, abs=1e-9)
    assert vals["environment.wind.angleApparent"]["value"] == pytest.approx(
        -0.6108652381980153, abs=1e-12
    )
    assert vals["environment.wind.speedApparent"]["value"] == pytest.approx(6.3, abs=1e-12)
    assert vals["environment.wind.angleTrueWater"]["value"] == pytest.approx(
        0.7330382858376184, abs=1e-12
    )
    hdg = vals["navigation.heading"]
    assert hdg["ref"] == "M"
    assert hdg["value"] == pytest.approx(5.009094953223726, abs=1e-9)  # 287 deg


def test_true_wind_speed_channel() -> None:
    vals = _vals(frame(rec01(0x56, 7.2, 1)))
    assert vals["environment.wind.speedTrue"]["value"] == pytest.approx(7.2, abs=1e-12)


def test_checksums() -> None:
    f = frame(rec01(0x41, 1.0, 2))
    assert (-sum(f[0:4])) & 0xFF == f[4]
    assert (-sum(f[5:-1])) & 0xFF == f[-1]
    corrupt = bytearray(f)
    corrupt[6] ^= 0x01
    framer = CountingFramer()
    assert framer.feed(bytes(corrupt)) == []
    assert framer.stats.bytes_discarded > 0


@pytest.mark.parametrize(
    "call",
    [
        lambda: rec01(0x41, 400.0, 2),  # 40000 > int16
        lambda: rec01(0x51, -40000, 0),
        lambda: rec01(0x41, 1.0, 4),
        lambda: rec08(0x49, 512),
        lambda: rec08(0x49, -1),
        lambda: frame(b"\x00" * 256),
    ],
)
def test_out_of_range_raises(call) -> None:
    with pytest.raises(ValueError):
        call()
