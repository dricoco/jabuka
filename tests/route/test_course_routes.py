"""ROUT-11 route-level proof: courses A and B from Vodice, under two uniform winds and the real
ICON-EU sample at two start times (8 scenarios). Every route is valid, re-validated against the
mask, passes each mark on its side and keeps clear of the Plić Sestre beacon; ETAs are stable."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.isochrone import route  # noqa: E402
from jabuka.route.rounding import expand  # noqa: E402
from jabuka.route.types import LEVELS  # noqa: E402

T0 = 1793923200.0
WINDS = ["SW12", "NE18", "icon+0h", "icon+6h"]
SCENARIOS = [(c, w) for c in ("A", "B") for w in WINDS]
TABLE: dict[str, tuple] = {}


@pytest.fixture(scope="module")
def run(env_factory, uniform_wind, sample_wind, course, course_geofields, make_request):
    cache: dict = {}

    def go(key: str, wind: str):
        if (key, wind) in cache:
            return cache[(key, wind)]
        if wind == "SW12":
            grid, t0 = uniform_wind(225.0, 12.0), T0
        elif wind == "NE18":
            grid, t0 = uniform_wind(45.0, 18.0), T0
        else:
            grid = sample_wind
            t0 = float(sample_wind.t[0]) + (6 * 3600.0 if wind == "icon+6h" else 0.0)
        env = env_factory(grid, geofields=course_geofields)
        start, marks = course(key)
        req = make_request(start.lat, start.lon, marks, prev_mark=start, t0=t0, tack0=1)
        res = route(req, env)
        cache[(key, wind)] = (req, env, res)
        return req, env, res

    return go


@pytest.mark.parametrize(("key", "wind"), SCENARIOS)
def test_course_scenario(run, key, wind, mask, path_tools, plic_beacon) -> None:
    req, env, r = run(key, wind)
    assert r.ok, f"{key}/{wind}: {r.reason}"
    assert r.valid
    TABLE[f"{key} {wind}"] = ((r.eta - req.t0) / 3600.0, r.steps, r.compute_ms, len(r.path))
    # re-validate the shipped polyline against the mask
    xs, ys = mask.frame.to_xy(np.array([p.lat for p in r.path]), np.array([p.lon for p in r.path]))
    v0 = 1 if r.start_in_margin else 0
    ok, bad = mask.validate_polyline(xs[v0:], ys[v0:])
    assert ok, f"segment {bad} crosses the mask"
    # never within 200 m of the Plić Sestre beacon
    assert path_tools["min_dist_m"](r.path, mask, *plic_beacon) >= 200.0
    # every mark on its side: signed winding (counter-clockwise +) around each rounding mark
    etas = [req.t0, *(leg.eta for leg in r.legs)]
    for i, m in enumerate(req.marks):
        if m.side == "none":
            continue
        t_to = etas[i + 2] if i + 2 < len(etas) else None
        w = path_tools["winding"](
            r.path, mask, m.lat, m.lon, max(3.0 * m.radius_nm, 2.0), etas[i], t_to
        )
        if m.side == "stbd":
            assert w < -30.0, f"{m.name}: winding {w:.0f} deg, starboard needs clockwise"
        else:
            assert w > 30.0, f"{m.name}: winding {w:.0f} deg, port needs counter-clockwise"
    # one leg per mark, ETAs increasing, the last one is the route ETA
    assert [leg.mark_id for leg in r.legs] == [m.mark_id for m in req.marks]
    etas = [leg.eta for leg in r.legs]
    assert all(b > a for a, b in zip([req.t0, *etas], etas, strict=False))
    assert etas[-1] == r.eta
    assert r.steps < 0.8 * req.settings.max_steps
    # horizon_hold exactly when the ETA is beyond the last wind time
    assert r.horizon_hold == (r.eta > env.fields.wind.t_last)
    assert r.compute_ms < 3000.0
    assert len(r.path) <= 300


def test_print_scenario_table(run) -> None:
    lines = ["scenario      ETA h  steps  ms     points"]
    for key, wind in SCENARIOS:
        req, _env, r = run(key, wind)
        assert r.ok
        lines.append(
            f"{key} {wind:8s} {(r.eta - req.t0) / 3600:6.2f} {r.steps:6d} {r.compute_ms:6.0f}"
            f" {len(r.path):6d}"
        )
    print("\n" + "\n".join(lines))


def test_identical_requests_identical_eta(run, course, make_request, course_geofields) -> None:
    req, env, r = run("A", "icon+0h")
    again = route(req, env)
    assert again.eta == r.eta and again.path == r.path


def _position_at(path, t: float):
    for a, b in zip(path, path[1:], strict=False):
        if a.t <= t <= b.t:
            f = (t - a.t) / (b.t - a.t)
            return a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon), a.tack
    raise AssertionError("time outside the path")


@pytest.mark.parametrize("wind", ["SW12", "icon+0h"])
def test_rerun_from_ten_minutes_along_is_stable(run, wind) -> None:
    req, env, r = run("A", wind)
    t1 = req.t0 + 600.0
    lat, lon, tack = _position_at(r.path, t1)
    again = route(
        req.__class__(**{**req.__dict__, "t0": t1, "lat": lat, "lon": lon, "tack0": tack}), env
    )
    assert again.ok, again.reason
    remaining = r.eta - t1
    assert abs((again.eta - t1) - remaining) <= 0.03 * remaining


def test_max_marks_ahead_routes_next_two_marks(run, make_request) -> None:
    req, env, r = run("A", "SW12")
    lvl = req.__class__(**{**req.__dict__, "settings": LEVELS["L3"]})
    r3 = route(lvl, env)
    assert r3.ok, r3.reason
    assert [leg.mark_id for leg in r3.legs] == [m.mark_id for m in req.marks[:2]]
    assert any("2 prochaines marques" in n for n in r3.notes)
    assert r3.level == "L3"
    assert r3.eta == pytest.approx(r.legs[1].eta, rel=0.05)


def test_leg_eta_matches_mark(run, mask) -> None:
    req, _env, r = run("B", "NE18")
    for leg, m in zip(r.legs, req.marks, strict=True):
        d = math.hypot(
            (leg.lat - m.lat) * 60, (leg.lon - m.lon) * 60 * math.cos(math.radians(m.lat))
        )
        assert d <= m.radius_nm + 0.35  # at the mark's last waypoint (or the snapped finish)


# ------------------------------------------------- course ending on an islet (quick 261110-klg)
def _islet_marks(course, shape: str):
    start, marks = course("A")
    plic, jab, blit = marks[0], marks[1], marks[2]
    if shape == "plic-blit-stbd":
        return start, (plic, blit)
    if shape == "plic-blit-none":
        return start, (plic, blit._replace(side="none"))
    return start, (plic, jab, blit)  # Course A without its Vodice finish (reported shape)


@pytest.mark.parametrize("shape", ["plic-blit-stbd", "plic-blit-none", "a-without-finish"])
def test_course_ending_on_an_islet_routes_to_its_circle(
    shape, course, mask, env_factory, uniform_wind, course_geofields, make_request
) -> None:
    start, marks = _islet_marks(course, shape)
    env = env_factory(uniform_wind(225.0, 12.0), geofields=course_geofields)
    req = make_request(start.lat, start.lon, marks, prev_mark=start, t0=T0, tack0=1)
    r = route(req, env)
    assert r.ok, r.reason
    assert [leg.mark_id for leg in r.legs] == [m.mark_id for m in marks]
    xs, ys = mask.frame.to_xy(np.array([p.lat for p in r.path]), np.array([p.lon for p in r.path]))
    v0 = 1 if r.start_in_margin else 0
    ok, bad = mask.validate_polyline(xs[v0:], ys[v0:])
    assert ok, f"segment {bad} crosses the mask"
    fin = expand(start, marks, start.lat, start.lon, mask)[-1]
    fx, fy = mask.frame.to_xy(fin.lat, fin.lon)
    for lat, lon in ((r.path[-1].lat, r.path[-1].lon), (r.legs[-1].lat, r.legs[-1].lon)):
        x, y = mask.frame.to_xy(lat, lon)
        assert math.hypot(x - fx, y - fy) <= 0.05
    assert "cible dans la terre" not in (r.reason or "")
    assert not any("cible dans la terre" in n for n in r.notes)
