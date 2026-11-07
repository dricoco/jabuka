"""Heavy-weather polar reduction in the router (quick 261107-1ow, S-07): the route request carries
the curves of the SAME derated polar as the helm, follows heavy_wind_* settings changes (even two
of them between two requests), and keeps the efficiency as a separate factor on top."""

from __future__ import annotations

import numpy as np
import pytest

from jabuka.nav.polar import default_polar, derate_polar, polar_to_json
from jabuka.route.polar_grid import PolarGrid, normalize_curves


def _router_curves(polar):
    """What RouterService._polar_curves builds: TWA-0 points stripped, normalised."""
    curves = [
        (tws, [(a, b) for a, b in pts if 0.0 < a <= 180.0])
        for tws, pts in polar_to_json(polar)["curves"]
    ]
    return normalize_curves([c for c in curves if c[1]])


def _start(routing_core, fake_pool, rh):
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    core.sail(*pos, 157.0)
    core.tick(1.0)
    core.settle()
    core.tick(1.0)
    assert fake_pool.requests, "no route request submitted"
    return core, pos


def _put(core, patch: dict) -> int:
    v = core.client.get("/api/settings").json()["version"]
    resp = core.client.put("/api/settings", json={"base_version": v, "patch": patch})
    return resp.status_code


def _next_request(core, fake_pool, pos):
    n = len(fake_pool.requests)
    core.call(core.router.force, "test")
    core.sail(*pos, 157.0)
    core.tick(1.0)
    core.settle()
    assert len(fake_pool.requests) == n + 1
    return fake_pool.requests[-1].base


def test_request_carries_the_derated_curves(routing_core, fake_pool, rh) -> None:
    core, _pos = _start(routing_core, fake_pool, rh)
    base = fake_pool.requests[-1].base
    got = dict(base.polar_curves)
    raw = dict(_router_curves(core.ctx.nav.polar_raw))
    top_tws = max(raw)
    assert top_tws < 25.0
    assert 18.0 in got and 25.0 in got and 18.0 not in raw
    # the 25 kn knot is the top curve x 0.95, at the same angles
    assert [a for a, _ in got[25.0]] == [a for a, _ in raw[top_tws]]
    assert [b for _, b in got[25.0]] == pytest.approx([0.95 * b for _, b in raw[top_tws]])
    # the curves up to start are the raw ones
    for tws in (t for t in raw if t <= 18.0):
        assert got[tws] == raw[tws], tws
    # the efficiency stays a separate factor
    s = core.ctx.nav.settings
    assert base.eff == s.efficiency
    assert base.eff_up == s.efficiency_up and base.eff_down == s.efficiency_down


def test_request_follows_the_settings(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    raw = _router_curves(core.ctx.nav.polar_raw)
    assert _put(core, {"heavy_wind_reduction": 0.0}) == 200
    assert _next_request(core, fake_pool, pos).polar_curves == raw
    assert _put(core, {"heavy_wind_reduction": 0.05}) == 200
    assert 18.0 in dict(_next_request(core, fake_pool, pos).polar_curves)


def test_two_changes_between_requests_reach_the_next_one(routing_core, fake_pool, rh) -> None:
    """Regression: an id()-keyed cache could serve stale curves when a later derated polar is
    allocated at a freed one's address."""
    core, pos = _start(routing_core, fake_pool, rh)
    for k in range(20):  # address reuse is up to the allocator: give it many chances
        start = 15.0 + (k % 6)
        assert _put(core, {"heavy_wind_start_kn": start - 1.5}) == 200
        core.ctx.nav.polar  # noqa: B018 - build the intermediate polar, as a tick would
        assert _put(core, {"heavy_wind_start_kn": start}) == 200
        tws = dict(_next_request(core, fake_pool, pos).polar_curves)
        assert start in tws and start - 1.5 not in tws, (k, sorted(tws))
    # the router holds the polar its curves came from, so its address cannot be recycled
    assert core.router._curves_polar is core.ctx.nav.polar


def test_bad_order_is_refused_and_nothing_changes(routing_core, fake_pool, rh) -> None:
    core, _pos = _start(routing_core, fake_pool, rh)
    before = core.client.get("/api/settings").json()
    assert _put(core, {"heavy_wind_start_kn": 30.0}) == 422
    assert _put(core, {"heavy_wind_reduction": 0.4}) == 422
    assert core.client.get("/api/settings").json() == before


def test_router_grid_rows_and_angles() -> None:
    """S-05 on the router side: the dense grid built from the derated curves keeps the raw rows up
    to start, is 0.95 x raw from full, and never moves a VMG target angle."""
    raw = default_polar()
    g_raw = PolarGrid.from_curves(_router_curves(raw))
    g_der = PolarGrid.from_curves(_router_curves(derate_polar(raw, 18.0, 25.0, 0.05)))
    np.testing.assert_allclose(g_der.raw[:19], g_raw.raw[:19], rtol=0, atol=1e-9)
    np.testing.assert_allclose(g_der.raw[25], 0.95 * g_raw.raw[25], rtol=0, atol=1e-9)
    np.testing.assert_allclose(g_der.raw[30], 0.95 * g_raw.raw[30], rtol=0, atol=1e-9)
    np.testing.assert_array_equal(g_der.up_deg, g_raw.up_deg)
    np.testing.assert_array_equal(g_der.down_deg, g_raw.down_deg)
