"""Waves slow the boat (ROUT-03), current carries it (ROUT-04)."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.fields import hs_from_tws  # noqa: E402
from jabuka.route.isochrone import route, wave_factor  # noqa: E402
from jabuka.route.polar_grid import PolarGrid  # noqa: E402
from jabuka.route.types import RouterSettings  # noqa: E402

T0 = 1793923200.0
OPEN = (43.25, 15.20)
KN_MS = 1852.0 / 3600.0
PEN_H = 45.0 / 3600.0


def _north(nm: float = 8.0):
    return OPEN[0] + nm / 60.0, OPEN[1]


def _hours(env, make_request, mark_point, target, **kw) -> tuple[float, object]:
    r = route(make_request(*OPEN, [mark_point(*target)], **kw), env)
    assert r.ok, r.reason
    return (r.eta - T0) / 3600.0, r


def test_wave_factor_table() -> None:
    s = RouterSettings()
    assert float(wave_factor(2.0, 40.0, s)) == pytest.approx(0.90)
    assert float(wave_factor(2.0, 90.0, s)) == pytest.approx(0.94)
    assert float(wave_factor(2.0, 150.0, s)) == pytest.approx(0.97)
    assert float(wave_factor(10.0, 40.0, s)) == pytest.approx(0.70)  # floor
    assert float(wave_factor(0.0, 40.0, s)) == 1.0


def test_uniform_hs_lengthens_a_beat(
    env_factory, uniform_wind, uniform_grid, make_request, mark_point
) -> None:
    wind = uniform_wind(0.0, 12.0)
    calm = env_factory(wind)
    rough = env_factory(wind, waves=uniform_grid({"hs": 2.0}))
    off = RouterSettings(use_waves=False)
    h0, _ = _hours(calm, make_request, mark_point, _north(), settings=off)
    h2, _ = _hours(rough, make_request, mark_point, _north())
    assert (h2 - PEN_H) / (h0 - PEN_H) == pytest.approx(1.0 / (1.0 - 0.05 * 2.0), rel=0.02)
    # floor: 10 m of Hs never slows the boat below 70 %
    huge = env_factory(wind, waves=uniform_grid({"hs": 10.0}))
    h10, _ = _hours(huge, make_request, mark_point, _north())
    assert (h10 - PEN_H) / (h0 - PEN_H) == pytest.approx(1.0 / 0.70, rel=0.02)
    # use_waves False disables the factor even with a wave file
    hoff, _ = _hours(rough, make_request, mark_point, _north(), settings=off)
    assert hoff == pytest.approx(h0, abs=1e-9)


def test_hs_from_tws_without_wave_file(env_factory, uniform_wind, make_request, mark_point) -> None:
    env = env_factory(uniform_wind(0.0, 12.0))
    h_on, _ = _hours(env, make_request, mark_point, _north())
    h_off, _ = _hours(
        env, make_request, mark_point, _north(), settings=RouterSettings(use_waves=False)
    )
    factor = 1.0 - 0.05 * float(hs_from_tws(12.0))  # 0.56 m at 12 kn
    assert (h_on - PEN_H) / (h_off - PEN_H) == pytest.approx(1.0 / factor, rel=0.005)


def test_current_vector_sum_on_a_reach(
    env_factory, uniform_wind, uniform_grid, make_request, mark_point, polar_curves
) -> None:
    # wind from the west, 1 kn current setting east, target 8 nm due north
    wind = uniform_wind(270.0, 12.0)
    cur = uniform_grid({"u": 1.0 * KN_MS, "v": 0.0})
    env = env_factory(wind, current=cur)
    h, r = _hours(env, make_request, mark_point, _north(), settings=RouterSettings(use_waves=False))
    # water-referenced wind: 11 kn from the west; crab into the current: v sin(h) = -1
    pg = PolarGrid.from_curves(polar_curves)
    v = float(pg.speed(11.0, 90.0))
    for _ in range(5):
        crab = math.degrees(math.asin(1.0 / v))
        v = float(pg.speed(11.0, 90.0 - crab))
    expect = 8.0 / math.sqrt(v * v - 1.0)
    assert h == pytest.approx(expect, rel=0.02)
    assert r.path[0].tws_kn == pytest.approx(11.0, abs=0.01)
    # use_current False ignores it: plain 12 kn beam reach
    h_off, _ = _hours(
        env,
        make_request,
        mark_point,
        _north(),
        settings=RouterSettings(use_waves=False, use_current=False),
    )
    assert h_off == pytest.approx(8.0 / float(pg.speed(12.0, 90.0)), rel=0.01)


def test_water_referenced_wind_feeds_the_polar(
    env_factory, uniform_wind, uniform_grid, make_request, mark_point
) -> None:
    # wind from 000 at 12 kn, current towards 180 at 1 kn: 11 kn over the water
    env = env_factory(uniform_wind(0.0, 12.0), current=uniform_grid({"u": 0.0, "v": -KN_MS}))
    _h, r = _hours(env, make_request, mark_point, (OPEN[0], OPEN[1] + 0.15))
    assert r.path[0].tws_kn == pytest.approx(11.0, abs=0.01)
    assert r.path[0].twd_deg % 360.0 == pytest.approx(0.0, abs=0.01)


def test_current_helps_downstream(
    env_factory, uniform_wind, uniform_grid, make_request, mark_point
):
    wind = uniform_wind(90.0, 12.0)  # beam reach to the north
    fair = env_factory(wind, current=uniform_grid({"u": 0.0, "v": 1.5 * KN_MS}))
    foul = env_factory(wind, current=uniform_grid({"u": 0.0, "v": -1.5 * KN_MS}))
    s = RouterSettings(use_waves=False)
    hf, _ = _hours(fair, make_request, mark_point, _north(), settings=s)
    hb, _ = _hours(foul, make_request, mark_point, _north(), settings=s)
    assert hf < hb
