"""Isochrone tracer: open-water accuracy against analytic VMG, Vodice to the open sea through a
real channel between the islands, failures as French reasons, decimation (ROUT-01, ROUT-11)."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.common.conventions import apparent_from_true, true_wind_from_apparent  # noqa: E402
from jabuka.route.isochrone import (  # noqa: E402
    MAX_PATH_POINTS,
    _decimate,
    _Pt,
    _Seg,
    heading_from_twa,
    tack_of,
)
from jabuka.route.polar_grid import PolarGrid  # noqa: E402

T0 = 1793923200.0
OPEN = (43.25, 15.20)  # open water west of the archipelago
VODICE = (43.75, 15.78)
OPEN_SEA_SW = (43.60, 15.60)
# Channel gates out of Vodice (checked on the 25 m mask): the Prvić-Tijat pinch, the gap between
# Prvić and the mainland, and the gap north of Tijat (between Tijat and the islet off Srima).
GATES = {
    "Prvić-Tijat": (43.7229, 15.7828),
    "Prvić-continent": (43.7360, 15.8100),
    "nord de Tijat": (43.7350, 15.7570),
}


def _nm(a, b) -> float:
    k = 60.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * 60.0, (a[1] - b[1]) * k)


def _dist_to_polyline_nm(p, path) -> float:
    k = 60.0 * math.cos(math.radians(p[0]))
    best = math.inf
    for a, b in zip(path, path[1:], strict=False):
        ax, ay = (a.lon - p[1]) * k, (a.lat - p[0]) * 60
        bx, by = (b.lon - p[1]) * k, (b.lat - p[0]) * 60
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        f = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        best = min(best, math.hypot(ax + f * dx, ay + f * dy))
    return best


def _offset(p, bearing_deg: float, nm: float):
    lat = p[0] + nm * math.cos(math.radians(bearing_deg)) / 60.0
    lon = p[1] + nm * math.sin(math.radians(bearing_deg)) / (60.0 * math.cos(math.radians(p[0])))
    return lat, lon


# --------------------------------------------------------------------------- golden sign
@pytest.mark.parametrize("twa_deg", [40.0, -40.0, 120.0, -150.0])
def test_golden_sign_heading_is_twd_minus_twa(twa_deg: float) -> None:
    twd = math.radians(200.0)
    hdg = float(heading_from_twa(twd, math.radians(twa_deg)))
    tack = int(tack_of(twa_deg))
    if twa_deg == 40.0:
        assert math.degrees(hdg) == pytest.approx(160.0)
        assert tack == 1
    assert tack == (1 if twa_deg > 0 else -1)
    # what the instruments would show sailing that heading in that wind
    app = apparent_from_true(twd, 6.0, 3.0, hdg)
    tw = true_wind_from_apparent(app.awa, app.aws, 3.0, hdg)
    assert math.degrees(tw.twa) == pytest.approx(twa_deg, abs=1e-6)
    assert math.degrees(tw.twd) == pytest.approx(200.0, abs=1e-6)
    # starboard = wind over the starboard side = positive TWA = positive AWA
    assert (app.awa > 0) == (tack == 1)


# --------------------------------------------------------------------------- open water
def _open_case(env_factory, uniform_wind, make_request, mark_point, bearing, twd, tws, **kw):
    env = env_factory(uniform_wind(twd, tws))
    tgt = _offset(OPEN, bearing, 8.0)
    req = make_request(*OPEN, [mark_point(*tgt)], **kw)
    r = route_ok(req, env)
    return r, (r.eta - T0) / 3600.0


def route_ok(req, env):
    from jabuka.route.isochrone import route

    r = route(req, env)
    assert r.ok, r.reason
    assert r.valid
    return r


def test_open_water_beat_matches_vmg(
    env_factory, uniform_wind, make_request, mark_point, polar_curves
) -> None:
    r, hours = _open_case(env_factory, uniform_wind, make_request, mark_point, 0.0, 0.0, 12.0)
    vmg = float(PolarGrid.from_curves(polar_curves).vmg_up[12])
    expect = 8.0 / vmg
    assert abs(hours - expect) <= 0.01 * expect + 45.0 / 3600.0  # 1 % + one tack penalty
    assert hours >= expect * 0.995  # cannot beat the VMG
    assert 1 <= len(r.tacks) <= 3
    assert all(abs(p.twa_deg) < 45 for p in r.path[:-1])


def test_open_water_reach_and_run_match_polar(
    env_factory, uniform_wind, make_request, mark_point, polar_curves
) -> None:
    pg = PolarGrid.from_curves(polar_curves)
    _r, hours = _open_case(env_factory, uniform_wind, make_request, mark_point, 90.0, 0.0, 12.0)
    assert hours == pytest.approx(8.0 / float(pg.speed(12, 90)), rel=0.01)
    # 20 kn: dead run is the downwind target
    _r, hours = _open_case(env_factory, uniform_wind, make_request, mark_point, 180.0, 0.0, 20.0)
    assert hours == pytest.approx(8.0 / float(pg.speed(20, 180)), rel=0.01)
    # 12 kn: gybing downwind at the VMG target beats the dead run
    r, hours = _open_case(env_factory, uniform_wind, make_request, mark_point, 180.0, 0.0, 12.0)
    expect = 8.0 / float(pg.vmg_down[12])
    assert abs(hours - expect) <= 0.01 * expect + 45.0 / 3600.0
    assert any(t.kind == "gybe" for t in r.tacks)


def test_identical_requests_identical_results(
    env_factory, uniform_wind, make_request, mark_point
) -> None:
    a, _ = _open_case(env_factory, uniform_wind, make_request, mark_point, 30.0, 0.0, 12.0)
    b, _ = _open_case(env_factory, uniform_wind, make_request, mark_point, 30.0, 0.0, 12.0)
    assert a.eta == b.eta and a.path == b.path and a.tacks == b.tacks


def test_tack_penalty_charged(env_factory, uniform_wind, make_request, mark_point) -> None:
    from jabuka.route.types import RouterSettings

    _a, h0 = _open_case(
        env_factory,
        uniform_wind,
        make_request,
        mark_point,
        0.0,
        0.0,
        12.0,
        settings=RouterSettings(tack_penalty_s=0.0),
    )
    _b, h1 = _open_case(
        env_factory,
        uniform_wind,
        make_request,
        mark_point,
        0.0,
        0.0,
        12.0,
        settings=RouterSettings(tack_penalty_s=300.0),
    )
    assert (h1 - h0) * 3600.0 >= 250.0  # at least one tack, about 300 s more


def test_efficiency_slows_the_boat(env_factory, uniform_wind, make_request, mark_point) -> None:
    _a, h1 = _open_case(env_factory, uniform_wind, make_request, mark_point, 90.0, 0.0, 12.0)
    _b, h2 = _open_case(
        env_factory, uniform_wind, make_request, mark_point, 90.0, 0.0, 12.0, eff=0.8
    )
    assert h2 == pytest.approx(h1 / 0.8, rel=0.005)


# --------------------------------------------------------------------------- Vodice
@pytest.mark.parametrize("wind", [(45.0, 18.0), (225.0, 12.0)], ids=["NE18", "SW12"])
def test_vodice_to_open_sea_through_a_channel(
    env_factory, uniform_wind, make_request, mark_point, mask, wind
) -> None:
    env = env_factory(uniform_wind(*wind))
    req = make_request(*VODICE, [mark_point(*OPEN_SEA_SW)])
    r = route_ok(req, env)
    xs, ys = mask.frame.to_xy(np.array([p.lat for p in r.path]), np.array([p.lon for p in r.path]))
    v0 = 1 if r.start_in_margin else 0
    ok, bad = mask.validate_polyline(xs[v0:], ys[v0:])
    assert ok, f"segment {bad} crosses the mask"
    gates = {name: _dist_to_polyline_nm(g, r.path) for name, g in GATES.items()}
    assert min(gates.values()) <= 0.5, gates
    assert r.steps < req.settings.max_steps // 4
    assert r.path[-1].lat == pytest.approx(OPEN_SEA_SW[0], abs=1e-6)
    assert r.legs and r.legs[-1].eta == r.eta
    assert r.compute_ms < 3000


def test_target_inside_an_island_fails_in_french(
    env_factory, uniform_wind, make_request, mark_point
) -> None:
    from jabuka.route.isochrone import route

    env = env_factory(uniform_wind(225.0, 12.0))
    r = route(make_request(*VODICE, [mark_point(43.7275, 15.80, "Prvić")]), env)
    assert not r.ok and not r.valid and r.path == ()
    assert "terre" in r.reason and "Prvić" in r.reason


def test_bad_request_fails_in_french(env_factory, uniform_wind, make_request, mark_point) -> None:
    from jabuka.route.isochrone import route
    from jabuka.route.types import RouterSettings

    env = env_factory(uniform_wind(225.0, 12.0))
    tgt = [mark_point(*OPEN_SEA_SW)]
    assert "invalide" in route(make_request(float("nan"), 15.0, tgt), env).reason
    assert "aucune marque" in route(make_request(*VODICE, []), env).reason
    r = route(make_request(*VODICE, tgt, settings=RouterSettings(hdg_step_deg=0.0)), env)
    assert not r.ok and "réglages" in r.reason
    r = route(make_request(*VODICE, tgt, polar_curves=((12.0, ((40.0, -2.0),)),)), env)
    assert not r.ok and "polaire" in r.reason
    r = route(make_request(*VODICE, tgt, eff=0.0), env)
    assert not r.ok and "efficacité" in r.reason


def test_unreachable_in_max_steps(env_factory, uniform_wind, make_request, mark_point) -> None:
    from jabuka.route.isochrone import route
    from jabuka.route.types import RouterSettings

    env = env_factory(uniform_wind(0.0, 12.0))
    req = make_request(*OPEN, [mark_point(*_offset(OPEN, 0.0, 8.0))])
    r = route(req.__class__(**{**req.__dict__, "settings": RouterSettings(max_steps=3)}), env)
    assert not r.ok and "étapes" in r.reason


# --------------------------------------------------------------------------- decimation
def test_decimation_keeps_tacks_and_arrival(mask) -> None:
    x0, y0 = mask.frame.to_xy(*OPEN)
    pts = []
    n = 1200
    for i in range(n):
        tack = 1 if (i // 150) % 2 == 0 else -1
        seg = _Seg(40.0 * tack, tack, 6.0, 0.0, 12.0)
        # zig-zag north: a tack every 150 points, tiny lateral noise
        x = x0 + (0.002 * (i % 150) if tack == 1 else 0.3 - 0.002 * (i % 150)) + 1e-4 * (i % 3)
        pts.append(_Pt(T0 + i * 60.0, x, y0 + 0.01 * i, seg, i == n - 1))
    protect = {0, n - 1} | {i for i in range(1, n) if pts[i].seg.tack != pts[i - 1].seg.tack}
    out = _decimate(pts, mask, 0.05, protect)
    assert len(out) <= MAX_PATH_POINTS
    kept = {(p.t, p.x, p.y) for p in out}
    for i in protect:
        assert (pts[i].t, pts[i].x, pts[i].y) in kept
    xs = np.array([p.x for p in out])
    ys = np.array([p.y for p in out])
    assert mask.validate_polyline(xs, ys)[0]


def test_route_path_bounded_and_tack_points_on_path(
    env_factory, uniform_wind, make_request, mark_point
) -> None:
    env = env_factory(uniform_wind(225.0, 12.0))
    r = route_ok(make_request(*VODICE, [mark_point(*OPEN_SEA_SW)], tack0=-1), env)
    assert 2 <= len(r.path) <= MAX_PATH_POINTS
    on_path = {(p.t, round(p.lat, 9), round(p.lon, 9)) for p in r.path}
    for tp in r.tacks:
        assert (tp.t, round(tp.lat, 9), round(tp.lon, 9)) in on_path
        assert tp.from_tack != tp.to_tack
    # path point i carries the TWA sailed to i+1: heading = TWD - TWA points to the next point
    for a, b in zip(r.path, r.path[1:], strict=False):
        assert np.sign(a.twa_deg) == a.tack
        assert abs(a.twa_deg) >= 30.0 - 1e-6
        dx = (b.lon - a.lon) * 60.0 * math.cos(math.radians(a.lat))
        dy = (b.lat - a.lat) * 60.0
        if math.hypot(dx, dy) > 0.3:
            course = math.degrees(math.atan2(dx, dy))
            hdg = a.twd_deg - a.twa_deg
            assert abs((course - hdg + 180.0) % 360.0 - 180.0) < 10.0
    assert all(b.t > a.t for a, b in zip(r.path, r.path[1:], strict=False))
