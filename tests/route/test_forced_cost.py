"""Stay on this tack ("On reste") and the cost of not tacking (ROUT-07, ROUT-08, Pattern 7)."""

from __future__ import annotations

import dataclasses
import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.cycle import cycle_with_env  # noqa: E402

from jabuka.route.isochrone import route  # noqa: E402
from jabuka.route.types import CycleRequest, RouterSettings  # noqa: E402

T0 = 1793923200.0
OPEN = (43.25, 15.20)


def _offset(p, bearing_deg: float, nm: float):
    lat = p[0] + nm * math.cos(math.radians(bearing_deg)) / 60.0
    lon = p[1] + nm * math.sin(math.radians(bearing_deg)) / (60.0 * math.cos(math.radians(p[0])))
    return lat, lon


@pytest.fixture(scope="module")
def beat(env_factory, uniform_wind, make_request, mark_point):
    """Wind from the north, target 8 nm at 030: on starboard (heading NW) the optimal route
    tacks onto port immediately."""
    env = env_factory(uniform_wind(0.0, 12.0))
    tgt = mark_point(*_offset(OPEN, 30.0, 8.0))
    req = make_request(*OPEN, [tgt], tack0=1, settings=RouterSettings(use_waves=False))
    return env, req


def _with(req, **settings):
    return dataclasses.replace(req, settings=dataclasses.replace(req.settings, **settings))


def test_optimal_tacks_now(beat) -> None:
    env, req = beat
    r = route(req, env)
    assert r.ok, r.reason
    assert r.tacks and r.tacks[0].t == pytest.approx(req.t0) and r.tacks[0].to_tack == -1


def test_cost_of_holding_five_minutes(beat) -> None:
    env, req = beat
    res = cycle_with_env(env, CycleRequest(req))
    assert res.optimal.ok and res.forced is not None and res.forced.ok, res.forced
    assert 0.0 < res.cost_s <= 300.0
    f = res.forced
    until = req.t0 + req.settings.stay_extra_s
    # held on starboard until the advised tack + 5 min, current leg only
    assert all(p.tack == 1 for p in f.path if p.t < until - 1.0)
    assert f.tacks and f.tacks[0].t >= until - 1.0
    assert len(f.legs) == 1
    assert res.cost_s == pytest.approx(max(0.0, f.legs[0].eta - res.optimal.legs[0].eta), abs=1e-6)


def test_holding_longer_costs_more(beat) -> None:
    env, req = beat
    c5 = cycle_with_env(env, CycleRequest(req)).cost_s
    c60 = cycle_with_env(env, CycleRequest(_with(req, stay_extra_s=3600.0))).cost_s
    assert c60 >= c5 - 18.0
    assert c60 > c5


def test_stay_active_marks_the_forced_route(beat) -> None:
    env, req = beat
    res = cycle_with_env(env, CycleRequest(req, stay_active=True))
    assert "on_reste" in res.forced.notes
    nxt = res.forced.tacks[0]
    assert nxt.t >= req.t0 + req.settings.stay_extra_s - 1.0


def test_want_forced_false_skips_it(beat) -> None:
    env, req = beat
    res = cycle_with_env(env, CycleRequest(req, want_forced=False))
    assert res.optimal.ok and res.forced is None and res.cost_s is None


def test_no_side_change_no_forced_route(env_factory, uniform_wind, make_request, mark_point):
    env = env_factory(uniform_wind(0.0, 12.0))
    tgt = mark_point(*_offset(OPEN, 90.0, 6.0))  # beam reach on port
    req = make_request(*OPEN, [tgt], tack0=-1)
    res = cycle_with_env(env, CycleRequest(req))
    assert res.optimal.ok and not res.optimal.tacks
    assert res.forced is None and res.cost_s is None


def test_forced_route_released_when_the_held_tack_meets_land(
    env_factory, uniform_wind, make_request, course, course_geofields
) -> None:
    """Vodice start on port in the bora: the held tack runs into the shore within minutes, the
    constraint is released at the first fully blocked step, the route stays valid and the cost
    is about 0 (Pattern 7, Pitfall 8)."""
    env = env_factory(uniform_wind(45.0, 18.0), geofields=course_geofields)
    start, marks = course("A")
    req = make_request(
        43.7395, 15.8135, marks, prev_mark=start, tack0=-1, settings=RouterSettings(use_waves=False)
    )
    forced = route(dataclasses.replace(req, force_tack_until=req.t0 + 3600.0, leg_only=True), env)
    assert forced.ok and forced.valid, forced.reason
    assert forced.force_released_at is not None
    assert forced.force_released_at <= req.t0 + 1800.0
    assert any("virement imposé (terre)" in n for n in forced.notes)
    opt = route(dataclasses.replace(req, leg_only=True), env)
    assert opt.ok
    assert forced.legs[0].eta - opt.legs[0].eta <= 120.0
