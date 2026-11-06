"""Old route re-evaluated under the new wind (hysteresis input, Pattern 9)."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.evaluate import evaluate_path, first_side_change  # noqa: E402
from jabuka.route.isochrone import route  # noqa: E402
from jabuka.route.types import PathPoint, RouterSettings  # noqa: E402

T0 = 1793923200.0
OPEN = (43.25, 15.20)


def _offset(p, bearing_deg: float, nm: float):
    lat = p[0] + nm * math.cos(math.radians(bearing_deg)) / 60.0
    lon = p[1] + nm * math.sin(math.radians(bearing_deg)) / (60.0 * math.cos(math.radians(p[0])))
    return lat, lon


@pytest.fixture(scope="module")
def beat(env_factory, uniform_wind, make_request, mark_point):
    env = env_factory(uniform_wind(0.0, 12.0))
    req = make_request(*OPEN, [mark_point(*_offset(OPEN, 10.0, 10.0))], tack0=1)
    r = route(req, env)
    assert r.ok
    pg = env.polar_for(req.polar_curves, req.eff)
    return env, req, r, pg


def _at(path, t):
    for a, b in zip(path, path[1:], strict=False):
        if a.t <= t <= b.t:
            f = (t - a.t) / (b.t - a.t)
            return a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon)
    raise AssertionError


def test_same_wind_same_eta(beat) -> None:
    env, req, r, pg = beat
    eta, valid, reason = evaluate_path(
        r.path, req.lat, req.lon, req.t0, env, pg, None, req.settings
    )
    assert valid and reason is None
    assert abs(eta - r.eta) <= 0.01 * (r.eta - req.t0)
    # from the boat's projection 20 min along the route
    t1 = req.t0 + 1200.0
    lat, lon = _at(r.path, t1)
    eta1, valid1, _ = evaluate_path(r.path, lat, lon, t1, env, pg, None, req.settings)
    assert valid1
    assert abs(eta1 - r.eta) <= 0.01 * (r.eta - t1)


def test_wind_rotation_below_30_deg_invalidates(beat, env_factory, uniform_wind) -> None:
    _env, req, r, pg = beat
    rotated = env_factory(uniform_wind(320.0, 12.0))  # starboard beat segments end up head to wind
    eta, valid, reason = evaluate_path(
        r.path, req.lat, req.lon, req.t0, rotated, pg, None, req.settings
    )
    assert not valid and eta is None
    assert "TWA" in reason


def test_slower_wind_later_eta(beat, env_factory, uniform_wind) -> None:
    _env, req, r, pg = beat
    light = env_factory(uniform_wind(0.0, 8.0))
    eta, valid, _ = evaluate_path(r.path, req.lat, req.lon, req.t0, light, pg, None, req.settings)
    assert valid and eta > r.eta


def test_path_through_land_invalid(env_factory, uniform_wind, polar_curves) -> None:
    env = env_factory(uniform_wind(270.0, 12.0))
    pg = env.polar_for(polar_curves, 1.0)
    path = (
        PathPoint(T0, 43.75, 15.78, -90.0, -1, 7.0, 270.0, 12.0),
        PathPoint(T0 + 3600, 43.705, 15.80, -90.0, -1, 7.0, 270.0, 12.0),
    )
    eta, valid, reason = evaluate_path(path, 43.75, 15.78, T0, env, pg, None, RouterSettings())
    assert not valid and eta is None and "terre" in reason


def test_first_side_change(beat) -> None:
    _env, req, r, _pg = beat
    assert r.tacks
    tp = first_side_change(r.path, req.t0, tack0=req.tack0)
    assert tp == r.tacks[0]
    later = first_side_change(r.path, tp.t + 1.0, tack0=req.tack0)
    assert later == (r.tacks[1] if len(r.tacks) > 1 else None)
    assert first_side_change(r.path[:1], req.t0) is None
