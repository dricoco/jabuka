"""Golden tests for jabuka.common.units (literals, never recomputed with the code under test)."""

from __future__ import annotations

import math

import pytest

from jabuka.common.units import (
    KN_IN_MS,
    deg2rad,
    kn_to_ms,
    ms_to_kn,
    rad2deg,
    wrap_2pi,
    wrap_pi,
)


def test_knots() -> None:
    assert KN_IN_MS == pytest.approx(0.514444, abs=1e-6)
    assert kn_to_ms(1.0) == pytest.approx(0.514444, abs=1e-6)
    assert kn_to_ms(10.0) == pytest.approx(5.144444, abs=1e-6)
    assert ms_to_kn(5.144444) == pytest.approx(10.0, abs=1e-5)
    assert ms_to_kn(1.0) == pytest.approx(1.943844, abs=1e-6)


def test_degrees() -> None:
    assert deg2rad(180.0) == pytest.approx(3.141592653589793, abs=1e-15)
    assert deg2rad(90.0) == pytest.approx(1.5707963267948966, abs=1e-15)
    assert rad2deg(0.7853981633974483) == pytest.approx(45.0, abs=1e-12)


def test_wrap_2pi() -> None:
    assert wrap_2pi(-0.1) == pytest.approx(6.183185307179586, abs=1e-12)  # 2pi - 0.1
    assert wrap_2pi(6.283185307179586) == pytest.approx(0.0, abs=1e-12)
    assert wrap_2pi(7.0) == pytest.approx(0.7168146928204138, abs=1e-12)
    assert wrap_2pi(0.0) == 0.0
    for x in (-1e-17, -1e-300, 6.283185307179586 - 1e-16):
        r = wrap_2pi(x)
        assert 0.0 <= r < 2 * math.pi


def test_wrap_pi() -> None:
    assert wrap_pi(4.71238898038469) == pytest.approx(-1.5707963267948966, abs=1e-12)  # 3pi/2
    assert wrap_pi(-4.71238898038469) == pytest.approx(1.5707963267948966, abs=1e-12)
    assert wrap_pi(3.141592653589793) == pytest.approx(3.141592653589793, abs=1e-12)  # (-pi, pi]
    assert wrap_pi(-3.141592653589793) == pytest.approx(3.141592653589793, abs=1e-12)
    assert wrap_pi(0.5) == pytest.approx(0.5, abs=1e-15)
