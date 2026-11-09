"""G-4-R04: the helm polar (nav/polar.py) and the router polar (route/polar_grid.py) share the
VMG-linear rule: within a curve, a segment whose two angles are both >= VMG_SEGMENT_MIN_DEG is
interpolated linearly in downwind VMG (bsp x -cos TWA), not in speed. Linear speed between 150 and
180 deg invents a VMG bump (helm 170 deg vs router 180 deg on a run at >= 14 kn).

The agreement test lists the TWS where both use the same knots. At 9, 11 and 13 kn (between
curves) they still differ by the deferred tail/deepest-angle rule: nav holds the last speed and
caps the search at the interpolated deepest TWA, the router tails to 0.9x (04-09-PLAN "Deferred
findings", review A LOW).
"""

from __future__ import annotations

import math

import pytest

import jabuka.nav.polar as nav_polar
import jabuka.route.polar_grid as polar_grid
from jabuka.nav.polar import Polar, load_racepack_polar, polar_to_json
from jabuka.route.polar_grid import PolarGrid, normalize_curves

AGREE_TWS = (4, 5, 6, 7, 8, 10, 12, 14, 15, 16, 17, 18, 20, 25)


@pytest.fixture(scope="module")
def polar() -> Polar:
    return load_racepack_polar(None)


@pytest.fixture(scope="module")
def grid(polar: Polar) -> PolarGrid:
    # exactly as router_service._polar_curves: drop the TWA 0 points, then normalize_curves
    curves = [
        (tws, [(a, b) for a, b in pts if 0.0 < a <= 180.0])
        for tws, pts in polar_to_json(polar)["curves"]
    ]
    return PolarGrid.from_curves(normalize_curves([c for c in curves if c[1]]))


def test_helm_and_router_targets_agree_on_the_shipped_polar(polar: Polar, grid: PolarGrid) -> None:
    for tws in AGREE_TWS:
        helm = polar.targets(float(tws))
        up, down = grid.targets(float(tws))
        assert abs(helm.down_twa - float(down)) <= 0.1, (tws, helm.down_twa, float(down))
        assert abs(helm.up_twa - float(up)) <= 0.1, (tws, helm.up_twa, float(up))


def test_downwind_target_is_180_from_14_kn(polar: Polar) -> None:
    for tws in (14, 15, 16, 18, 20, 22, 25):
        assert polar.targets(float(tws)).down_twa == 180.0, tws


def test_speed_is_vmg_linear_between_deep_knots(polar: Polar) -> None:
    # 14 kn curve: 150 deg -> 7.56 kn, 180 deg -> 6.94 kn
    c150 = -math.cos(math.radians(150.0))
    c165 = -math.cos(math.radians(165.0))
    expected = ((7.56 * c150 + 6.94) / 2.0) / c165
    assert polar.speed(14.0, 165.0) == pytest.approx(expected, rel=1e-9)
    assert polar.speed(14.0, 150.0) == pytest.approx(7.56)  # a knot keeps its value
    assert polar.speed(12.0, 90.0) == pytest.approx(7.69)  # below 120 deg: unchanged


def test_threshold_matches_the_router() -> None:
    assert nav_polar.VMG_SEGMENT_MIN_DEG == polar_grid.VMG_SEGMENT_MIN_DEG == 120.0
