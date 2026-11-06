"""Tack advice in the live core (plan 03-05 Task 2, ROUT-06..ROUT-10): "On reste", the cost of
not tacking, the degraded L5 cadence of the forced routing and the missed-tack recompute."""

from __future__ import annotations

import dataclasses
import math
import time

import pytest

from jabuka.nav import geo
from jabuka.route.types import CycleResult, LegResult, PathPoint, RouteResult, TackPoint

PORT_HDG = 157.0  # NE wind: TWA 45 - 157 = -112 (port)
STBD_HDG = 293.0  # TWA 45 - 293 = +112 (starboard)


def _start(routing_core, fake_pool, rh, **kw):
    core = routing_core(pool_factory=lambda: fake_pool, **kw)
    pos = rh.boat_near_plic(2.0)
    core.sail(*pos, PORT_HDG)
    core.tick(1.0)
    core.settle()
    nav = core.tick(1.0)
    assert nav["route"]["version"] == 1, nav["route"]
    return core, pos


def _run(core, pos, seconds: int, hdg: float = PORT_HDG) -> dict:
    nav = {}
    for _ in range(seconds):
        core.sail(*pos, hdg)
        nav = core.tick(1.0)
        core.settle()
    return nav


def _kept(fake_pool):
    def script(creq):
        res = fake_pool.default(creq)
        return dataclasses.replace(res, eta_old_now=res.optimal.eta, old_valid=True)

    return script


def test_stay_on_tack_shows_the_forced_route_and_cancels(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    for bad in ({}, {"active": "oui"}, {"active": True, "x": 1}):
        assert core.client.post("/api/route/stay", json=bad).status_code == 422
    resp = core.client.post("/api/route/stay", json={"active": True})
    assert resp.status_code == 200 and resp.json()["type"] == "nav"
    nav = _run(core, pos, 1)
    r = nav["route"]
    assert r["version"] == 2 and r["kind"] == "stay"
    assert r["stay"] == {
        "active": True,
        "tack": "port",
        "released_land": False,
        "release_in_s": None,
    }
    creq = fake_pool.requests[-1]
    assert creq.stay_active and creq.want_forced and creq.base.tack0 == -1
    # countdown = first side change of the forced route (tack_at_s + 600 in the fake)
    assert r["countdown_s"] == pytest.approx(fake_pool.tack_at_s + 600.0, abs=3.0)
    assert core.client.get("/api/route").json()["kind"] == "stay"

    resp = core.client.post("/api/route/stay", json={"active": False})
    assert resp.status_code == 200
    nav = _run(core, pos, 1)
    assert nav["route"]["kind"] == "optimal" and nav["route"]["version"] == 3
    assert nav["route"]["stay"]["active"] is False


def test_a_detected_tack_clears_stay_and_reroutes(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    core.client.post("/api/route/stay", json={"active": True})
    nav = _run(core, pos, 1)
    assert nav["route"]["stay"]["active"] is True
    nav = _run(core, pos, 20, STBD_HDG)
    assert nav["route"]["stay"]["active"] is True  # not confirmed yet (30 s)
    nav = _run(core, pos, 15, STBD_HDG)
    assert nav["route"]["stay"]["active"] is False
    assert nav["route"]["kind"] == "optimal"
    assert any("stay" in r for _t, r in core.router.request_log)
    assert fake_pool.requests[-1].base.tack0 == 1  # the detector's new side


def test_forced_route_released_at_land(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)

    def released(creq):
        res = fake_pool.default(creq)
        f = dataclasses.replace(res.forced, force_released_at=creq.base.t0 + 300.0)
        return dataclasses.replace(res, forced=f)

    fake_pool.script = released
    core.client.post("/api/route/stay", json={"active": True})
    nav = _run(core, pos, 1)
    st = nav["route"]["stay"]
    assert st["active"] is True and st["released_land"] is True
    assert st["release_in_s"] == pytest.approx(299.0, abs=2.0)


@pytest.mark.parametrize(("cost", "text"), [(240.0, "+4 min"), (30.0, "< 1 min")])
def test_cost_of_not_tacking(routing_core, fake_pool, rh, cost, text) -> None:
    fake_pool.cost_s = cost
    core, pos = _start(routing_core, fake_pool, rh)
    nav = _run(core, pos, 1)
    assert nav["route"]["cost_s"] == pytest.approx(cost)
    assert nav["route"]["cost_text"] == text


def test_l5_runs_the_forced_routing_every_other_cycle(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    v = core.client.get("/api/settings").json()["version"]
    resp = core.client.put(
        "/api/settings", json={"base_version": v, "patch": {"route_level": "L5"}}
    )
    assert resp.status_code == 200
    fake_pool.script = _kept(fake_pool)
    wants = []
    costs = []
    for i in range(4):
        fake_pool.cost_s = 60.0 * (i + 2)
        core.call(core.router.request, "timer", False)
        nav = _run(core, pos, 1)
        wants.append(fake_pool.requests[-1].want_forced)
        costs.append(nav["route"]["cost_s"])
    assert wants.count(True) == 2 and wants.count(False) == 2
    assert all(a != b for a, b in zip(wants, wants[1:], strict=False))
    for w, prev, c in zip(wants[1:], costs, costs[1:], strict=False):
        if not w:
            assert c == prev  # last cost kept between forced routings
    assert fake_pool.requests[-1].base.settings.level == "L5"


# -- missed tack --------------------------------------------------------------------------------
NORTH = 5.0  # starboard in the NE wind (TWA +40)


def _north_route(creq) -> CycleResult:
    """6 kn north for 600 s, tack to port (heading 085) for 1200 s."""
    b = creq.base
    t0 = b.t0
    a = (b.lat, b.lon)
    tb = geo.offset(*a, math.radians(NORTH), 1.0)
    c = geo.offset(*tb, math.radians(85.0), 2.0)
    path = (
        PathPoint(t0, *a, 40.0, 1, 6.0, 45.0, 18.0),
        PathPoint(t0 + 600.0, *tb, -40.0, -1, 6.0, 45.0, 18.0),
        PathPoint(t0 + 1800.0, *c, -40.0, -1, 6.0, 45.0, 18.0),
    )
    tacks = (TackPoint(t0 + 600.0, *tb, 1, -1, "tack"),)
    opt = RouteResult(
        ok=True,
        reason=None,
        request_id=b.request_id,
        t0=t0,
        path=path,
        tacks=tacks,
        legs=(LegResult("plic-sestre", t0 + 1800.0, *c),),
        eta=t0 + 1800.0,
        valid=True,
    )
    old = creq.old_path is not None
    return CycleResult(opt, None, None, opt.eta if old else None, True if old else None, None, {})


def test_missed_tack_reroutes_once(routing_core, fake_pool, rh) -> None:
    fake_pool.script = _north_route
    core = routing_core(pool_factory=lambda: fake_pool)
    start = rh.boat_near_plic(2.0)
    core.sail(*start, NORTH)
    core.tick(1.0)
    core.settle()
    t0 = fake_pool.requests[0].base.t0
    nav = core.tick(0.0)
    assert nav["route"]["version"] == 1

    def pos_now() -> tuple[float, float]:
        dt = core.router.now() - t0
        return geo.offset(*start, math.radians(NORTH), 6.0 * dt / 3600.0)

    def step() -> dict:
        core.sail(*pos_now(), NORTH)
        n = core.tick(1.0)
        core.settle()
        return n

    for _ in range(700):
        nav = step()
        assert nav["route"]["missed"] is False
    assert nav["route"]["countdown_s"] < 0  # overdue: still on starboard after the tack point
    fake_pool.hold = True
    for _ in range(30):
        core.sail(*pos_now(), NORTH)
        nav = core.tick(1.0)
        if nav["route"]["missed"]:
            break
    assert nav["route"]["missed"] is True and nav["route"]["updating"] is True
    assert nav["route"]["version"] == 1
    fake_pool.hold = False
    core.settle()
    nav = step()
    assert nav["route"]["version"] == 2
    assert nav["route"]["missed"] is False and nav["route"]["updating"] is False
    for _ in range(60):
        nav = step()
    missed = [r for _t, r in core.router.request_log if "missed" in r]
    assert len(missed) == 1


# -- one real-worker round trip ------------------------------------------------------------------
def test_stay_round_trip_through_the_real_worker(routing_core, rh, tmp_path) -> None:
    # SSE 12 kn: Plić Sestre is dead upwind of a boat 2 nm NNW of it (a beat with tacks)
    pack = rh.make_pack(tmp_path / "beat", twd_deg=157.0, tws_kn=12.0)
    core = routing_core(racepack_dir=pack)
    pos = rh.boat_near_plic(2.0)
    hdg = 117.0  # TWA +40, starboard

    def tick() -> dict:
        core.sail(*pos, hdg, twd_deg=157.0, tws_kn=12.0)
        return core.tick(0.0)

    deadline = time.monotonic() + 90.0
    nav = tick()
    while nav["route"]["version"] < 1:
        assert time.monotonic() < deadline, nav["route"]
        time.sleep(0.05)
        nav = tick()
    core.client.post("/api/route/stay", json={"active": True})
    while nav["route"]["version"] < 2:
        assert time.monotonic() < deadline, nav["route"]
        time.sleep(0.05)
        nav = tick()
    r = nav["route"]
    assert r["state"] == "ok"
    assert r["stay"]["active"] is True and r["stay"]["tack"] == "stbd"
    assert r["cost_s"] is not None and r["cost_s"] >= 0.0
    assert r["cost_text"] in ("< 1 min",) or r["cost_text"].startswith("+")
    req = core.router.last_request
    assert req.stay_active and req.base.tack0 == 1
    if r["kind"] == "stay":
        msg = core.client.get("/api/route").json()
        assert msg["kind"] == "stay" and msg["legs"][0]["mark_id"] == "plic-sestre"
