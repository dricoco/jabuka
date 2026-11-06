"""Golden tests pinning the direction/unit conventions (literals, never recomputed with the code
under test).

Radians internally; variation and heading offset East-positive; wind direction FROM; current
TOWARDS; TWA/AWA signed, negative = port; u = east component, v = north component.
"""

from __future__ import annotations

import math

import pytest

from jabuka.common.conventions import (
    apparent_from_true,
    apply_heading_offset,
    current_towards_uv,
    gpsd_magvar_to_east,
    mag_to_true,
    true_to_mag,
    true_wind_from_apparent,
    uv_from_wind_from,
    uv_to_current_towards,
    wind_from_uv,
)

R350 = 6.1086523819801535  # radians(350)
R355 = 6.19591884457987  # radians(355)
R358 = 6.2482787221397  # radians(358)
R5 = 0.08726646259971647  # radians(5)
R3 = 0.05235987755982989  # radians(3)
R90 = 1.5707963267948966
R135 = 2.356194490192345
PI = 3.141592653589793
EPS = 1e-12


def _ang_eq(a: float, b: float, tol: float = 1e-9) -> bool:
    d = (a - b + PI) % (2 * PI) - PI
    return abs(d) < tol


# -- magnetic / true ---------------------------------------------------------------------------
def test_mag_to_true_east_variation() -> None:
    assert mag_to_true(R350, R5) == pytest.approx(R355, abs=EPS)


def test_mag_to_true_wraps_through_north() -> None:
    assert mag_to_true(R358, R5) == pytest.approx(R3, abs=EPS)


def test_true_to_mag_inverts() -> None:
    assert true_to_mag(R3, R5) == pytest.approx(R358, abs=EPS)
    assert true_to_mag(R355, R5) == pytest.approx(R350, abs=EPS)


def test_west_variation_is_negative() -> None:
    # 5 deg W = -5 deg E: magnetic 3 deg -> true 358 deg
    assert mag_to_true(R3, -R5) == pytest.approx(R358, abs=EPS)


def test_apply_heading_offset_wraps() -> None:
    assert apply_heading_offset(R358, R5) == pytest.approx(R3, abs=EPS)
    assert apply_heading_offset(R3, -R5) == pytest.approx(R358, abs=EPS)


def test_gpsd_magvar_is_west_positive() -> None:
    assert gpsd_magvar_to_east(5.0) == -5.0
    assert gpsd_magvar_to_east(-4.6) == 4.6


# -- wind FROM / current TOWARDS u,v -----------------------------------------------------------
def test_wind_blowing_south_is_from_north() -> None:
    d, s = wind_from_uv(0.0, -10.0)
    assert _ang_eq(d, 0.0) and s == pytest.approx(10.0, abs=EPS)


def test_wind_blowing_west_is_from_east() -> None:
    d, s = wind_from_uv(-10.0, 0.0)
    assert d == pytest.approx(R90, abs=EPS) and s == pytest.approx(10.0, abs=EPS)


def test_wind_from_southwest() -> None:
    d, s = wind_from_uv(3.0, 4.0)  # air moving NE -> from SW (216.87 deg)
    assert d == pytest.approx(3.7850937623830774, abs=EPS)
    assert s == pytest.approx(5.0, abs=EPS)


def test_uv_from_wind_from_inverts() -> None:
    u, v = uv_from_wind_from(R90, 10.0)
    assert u == pytest.approx(-10.0, abs=EPS) and v == pytest.approx(0.0, abs=EPS)
    u, v = uv_from_wind_from(0.0, 10.0)
    assert u == pytest.approx(0.0, abs=EPS) and v == pytest.approx(-10.0, abs=EPS)
    d, s = wind_from_uv(*uv_from_wind_from(3.7850937623830774, 5.0))
    assert d == pytest.approx(3.7850937623830774, abs=EPS) and s == pytest.approx(5.0)


def test_current_towards_east() -> None:
    u, v = current_towards_uv(R90, 1.0)
    assert u == pytest.approx(1.0, abs=EPS) and v == pytest.approx(0.0, abs=EPS)


def test_uv_to_current_towards_inverts() -> None:
    d, s = uv_to_current_towards(1.0, 0.0)
    assert d == pytest.approx(R90, abs=EPS) and s == pytest.approx(1.0, abs=EPS)
    d, s = uv_to_current_towards(0.0, -2.0)  # flowing south
    assert d == pytest.approx(PI, abs=EPS) and s == pytest.approx(2.0, abs=EPS)


# -- true / apparent wind ----------------------------------------------------------------------
def test_true_from_apparent_beam_reach() -> None:
    tw = true_wind_from_apparent(awa=R90, aws=10.0, bsp=10.0, hdg=0.0)
    assert tw.twa == pytest.approx(R135, abs=1e-9)
    assert tw.tws == pytest.approx(14.142, abs=1e-3)
    assert tw.twd == pytest.approx(R135, abs=1e-9)


def test_true_from_apparent_dead_downwind() -> None:
    tw = true_wind_from_apparent(awa=PI, aws=5.0, bsp=5.0, hdg=0.0)
    assert tw.twa == pytest.approx(PI, abs=1e-9)
    assert tw.tws == pytest.approx(10.0, abs=1e-9)


def test_true_from_apparent_port_is_negative() -> None:
    tw = true_wind_from_apparent(awa=-0.5235987755982988, aws=12.0, bsp=6.0, hdg=R90)
    assert tw.twa < 0.0
    # TWD wrapped to [0, 2pi)
    assert 0.0 <= tw.twd < 2 * PI


def test_true_from_apparent_heading_and_wrap() -> None:
    tw = true_wind_from_apparent(awa=R90, aws=10.0, bsp=10.0, hdg=R350)
    assert tw.twd == pytest.approx(2.181661564992912, abs=1e-9)  # 350 + 135 - 360 = 125 deg


def test_apparent_from_true_close_hauled() -> None:
    # TWD 0, TWS 10, heading 315 (TWA +45 starboard), BSP 6
    aw = apparent_from_true(twd=0.0, tws=10.0, bsp=6.0, hdg=5.497787143782138)
    assert aw.awa == pytest.approx(0.4958846908538251, abs=1e-9)  # 28.41 deg
    assert aw.aws == pytest.approx(14.86111751324192, abs=1e-9)


def test_apparent_from_true_round_trip_grid() -> None:
    worst = 0.0
    for twd_deg in range(0, 360, 10):
        for tws in (2.0, 5.0, 8.0, 12.5, 18.0, 25.0):
            for hdg_deg in (0.0, 45.0, 137.0, 200.0, 359.0):
                for bsp in (0.0, 1.5, 3.0, 5.0, 7.0, 9.0):
                    twd = math.radians(twd_deg)
                    hdg = math.radians(hdg_deg)
                    aw = apparent_from_true(twd=twd, tws=tws, bsp=bsp, hdg=hdg)
                    tw = true_wind_from_apparent(awa=aw.awa, aws=aw.aws, bsp=bsp, hdg=hdg)
                    d = abs((tw.twd - twd + PI) % (2 * PI) - PI)
                    worst = max(worst, d, abs(tw.tws - tws))
                    assert 0.0 <= tw.twd < 2 * PI
                    assert -PI < aw.awa <= PI
    assert worst < 1e-9
