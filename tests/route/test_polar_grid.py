"""PolarGrid: the X35 polar resampled once into a dense table (RESEARCH Pattern 4)."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.polar_grid import PolarGrid, curves_from_json  # noqa: E402


@pytest.fixture(scope="module")
def pg(polar_curves) -> PolarGrid:
    return PolarGrid.from_curves(polar_curves, eff=1.0)


@pytest.mark.parametrize("eff", [1.0, 0.92])
def test_given_point_is_exact_times_efficiency(polar_curves, eff: float) -> None:
    p = PolarGrid.from_curves(polar_curves, eff=eff)
    assert float(p.speed(12, 37.7)) == pytest.approx(6.50 * eff, abs=0.02 * eff)
    assert float(p.speed(16, 90)) == pytest.approx(8.28 * eff, abs=0.02)


def test_clamped_above_highest_tws_and_zero_at_zero(pg: PolarGrid) -> None:
    assert float(pg.speed(25, 90)) == pytest.approx(float(pg.speed(20, 90)))
    assert float(pg.speed(40, 120)) == pytest.approx(9.45)
    for twa in (0, 45, 90, 135, 180):
        assert float(pg.speed(0, twa)) == 0.0
    # linear across TWS between curves, and from the implicit TWS 0 curve
    assert float(pg.speed(13, 90)) == pytest.approx((7.69 + 8.01) / 2, abs=1e-6)
    assert float(pg.speed(3, 90)) == pytest.approx(6.10 / 2, abs=1e-6)


def test_vmg_targets(pg: PolarGrid) -> None:
    up12, down12 = pg.targets(12)
    assert float(up12) == pytest.approx(37.7, abs=0.2)
    assert float(down12) == pytest.approx(158.9, abs=1.0)
    _up20, down20 = pg.targets(20)
    assert float(down20) == pytest.approx(180.0, abs=0.5)
    up, down = pg.targets(np.array([6.0, 10.0, 14.0]))
    assert up.shape == down.shape == (3,)
    assert np.all((up > 30) & (up < 50)) and np.all(down > 135)


def test_never_extended_flat_beyond_last_angle(pg: PolarGrid) -> None:
    # the 12 kn curve stops at 158.9 deg (6.77 kn): 0.9 x that at 180, never flat
    assert float(pg.speed(12, 180)) == pytest.approx(0.9 * 6.77, abs=0.01)
    assert float(pg.speed(12, 170)) < 6.77 - 0.05
    # the target did not move to 180 (the prototype bug)
    assert float(pg.targets(12)[1]) < 165.0


def test_targets_do_not_depend_on_efficiency(polar_curves) -> None:
    a = PolarGrid.from_curves(polar_curves, eff=1.0)
    b = PolarGrid.from_curves(polar_curves, eff=0.8, eff_up=0.7, eff_down=0.9)
    w = np.arange(0, 41, dtype=float)
    for x, y in zip(a.targets(w), b.targets(w), strict=True):
        assert np.array_equal(x, y)


def test_eff_up_below_90_and_eff_down_from_90(polar_curves) -> None:
    raw = PolarGrid.from_curves(polar_curves)
    p = PolarGrid.from_curves(polar_curves, eff=0.9, eff_up=0.8, eff_down=0.95)
    assert float(p.speed(12, 60)) == pytest.approx(0.8 * float(raw.speed(12, 60)))
    assert float(p.speed(12, 89.9)) == pytest.approx(0.8 * float(raw.speed(12, 89.9)))
    assert float(p.speed(12, 90)) == pytest.approx(0.95 * float(raw.speed(12, 90)))
    assert float(p.speed(12, 150)) == pytest.approx(0.95 * float(raw.speed(12, 150)))
    q = PolarGrid.from_curves(polar_curves, eff=0.9)
    assert float(q.speed(12, 60)) == pytest.approx(0.9 * float(raw.speed(12, 60)))
    assert float(q.speed(12, 150)) == pytest.approx(0.9 * float(raw.speed(12, 150)))


def test_vectorised_and_symmetric(pg: PolarGrid) -> None:
    tws = np.array([[8.0], [12.0]])
    twa = np.array([40.0, 90.0, 150.0])
    out = pg.speed(tws, twa)
    assert out.shape == (2, 3)
    assert np.allclose(pg.speed(tws, -twa), out)
    assert np.all(np.isfinite(out)) and np.all(out > 0)


@pytest.mark.parametrize(
    "obj",
    [
        {},
        {"curves": []},
        {"curves": "x"},
        {"curves": [[12, [[40, -1.0]]]]},
        {"curves": [[12, [[40, float("nan")]]]]},
        {"curves": [[-5, [[40, 5.0]]]]},
        {"curves": [[12, [[200, 5.0]]]]},
        {"curves": [[12, []]]},
        {"curves": [[12, [[40, 5.0], [40, 6.0]]]]},
        {"curves": [[12, [[40]]]]},
        [1, 2, 3],
    ],
)
def test_from_polar_json_rejects_bad_shapes(obj) -> None:
    with pytest.raises(ValueError):
        PolarGrid.from_polar_json(obj)


def test_from_polar_json_round_trip(polar_curves) -> None:
    obj = {"name": "X35", "curves": [[t, [list(p) for p in pts]] for t, pts in polar_curves]}
    p = PolarGrid.from_polar_json(obj, eff=0.92)
    assert p.name == "X35"
    assert curves_from_json(obj) == polar_curves
    assert float(p.speed(12, 37.7)) == pytest.approx(6.5 * 0.92, abs=0.02)
    assert math.isfinite(float(p.vmg_up[12])) and float(p.vmg_up[12]) == pytest.approx(5.14, 0.01)


def test_worker_caches_are_bounded(mask, env_factory, sample_wind, polar_curves) -> None:
    """03-REVIEW LO-03: one polar grid per efficiency change and one geofield per moved mark
    were kept for 36 h; both caches are now LRU (CACHE_MAX entries)."""
    from collections import OrderedDict

    from jabuka.route.isochrone import CACHE_MAX, RouterEnv, _lru_get, _lru_put

    env = RouterEnv(mask, env_factory(sample_wind).fields)
    assert isinstance(env.geo_cache, OrderedDict) and isinstance(env.polar_cache, OrderedDict)
    first = env.polar_for(polar_curves, 0.80)
    for k in range(1, 12):
        env.polar_for(polar_curves, 0.80 + 0.01 * k)
    assert len(env.polar_cache) == CACHE_MAX
    assert env.polar_for(polar_curves, 0.80) is not first  # evicted, rebuilt
    recent = env.polar_for(polar_curves, 0.80)
    env.polar_for(polar_curves, 0.95)
    assert env.polar_for(polar_curves, 0.80) is recent  # used recently: kept
    lru: OrderedDict = OrderedDict()
    for k in range(CACHE_MAX + 3):
        _lru_put(lru, k, str(k))
    assert list(lru) == list(range(3, CACHE_MAX + 3))
    assert _lru_get(lru, 3) == "3" and list(lru)[-1] == 3
