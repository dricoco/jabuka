"""Flat-earth geometry (nm, true bearings in radians)."""

from __future__ import annotations

import math

import pytest

from jabuka.nav import geo

VODICE = (43.75, 15.78)
PLIC_SESTRE = (43.684627, 15.811626)


def test_vodice_to_plic_sestre() -> None:
    b, d = geo.bearing_distance(*VODICE, *PLIC_SESTRE)
    assert math.degrees(b) == pytest.approx(161.0, abs=1.0)
    assert d == pytest.approx(4.2, abs=0.1)


@pytest.mark.parametrize("bearing_deg", [0, 37, 90, 161, 203, 270, 359])
@pytest.mark.parametrize("dist", [0.01, 1.0, 12.5, 40.0])
def test_offset_is_the_inverse_of_bearing_distance(bearing_deg: float, dist: float) -> None:
    b = math.radians(bearing_deg)
    lat2, lon2 = geo.offset(*PLIC_SESTRE, b, dist)
    b2, d2 = geo.bearing_distance(*PLIC_SESTRE, lat2, lon2)
    assert d2 == pytest.approx(dist, abs=1e-6)
    assert math.degrees(math.remainder(b2 - b, 2 * math.pi)) == pytest.approx(0.0, abs=1e-6)


def test_local_frame_round_trip() -> None:
    x, y = geo.to_local(43.7, 15.9, *PLIC_SESTRE)
    assert geo.from_local(x, y, *PLIC_SESTRE) == pytest.approx((43.7, 15.9), abs=1e-12)
    assert geo.to_local(*PLIC_SESTRE, *PLIC_SESTRE) == (0.0, 0.0)
    # one minute of latitude is one nautical mile
    assert geo.to_local(PLIC_SESTRE[0] + 1 / 60, PLIC_SESTRE[1], *PLIC_SESTRE)[1] == pytest.approx(
        1.0
    )


def test_unit_and_bearing_of() -> None:
    assert geo.unit(0.0) == pytest.approx((0.0, 1.0))
    assert geo.unit(math.pi / 2) == pytest.approx((1.0, 0.0))
    assert math.degrees(geo.bearing_of(-1.0, 0.0)) == pytest.approx(270.0)
