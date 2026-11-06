"""Supervisor (plan 03-05 Task 2, ROUT-02/05/09, ROUT-11 runtime): triggers, hysteresis
max(3 min, 1 %), forced bypass, invalid-route discard, timeout/crash handling and persistence,
driven tick by tick with a scripted fake pool."""

from __future__ import annotations

import json
import math

import pytest

from jabuka.nav import geo
from jabuka.route.pool import PoolOutcome


def _start(routing_core, fake_pool, rh, **kw):
    core = routing_core(pool_factory=lambda: fake_pool, **kw)
    lat, lon = rh.boat_near_plic(2.0)
    core.sail(lat, lon, 157.0)
    core.tick(1.0)
    core.settle()
    nav = core.tick(1.0)
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] == 1, nav["route"]
    return core, (lat, lon)


def _run(core, pos, seconds: int, hdg: float = 157.0) -> dict:
    """seconds x (feed, tick +1 s, let the router's job finish), then a same-time tick so the
    returned nav message shows what the last job adopted."""
    for _ in range(seconds):
        core.sail(*pos, hdg)
        core.tick(1.0)
        core.settle()
    core.sail(*pos, hdg)
    return core.tick(0.0)


def _reasons(core) -> list[tuple[str, ...]]:
    return [r for _t, r in core.router.request_log]


def test_timer_fires_at_the_cadence(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    # the GRIB bias would become valid after 300 s of steady sailing and fire its own trigger
    v = core.client.get("/api/settings").json()["version"]
    core.client.put("/api/settings", json={"base_version": v, "patch": {"bias_enabled": False}})
    n = len(fake_pool.requests)
    fake_pool.eta_old_now = None  # identical routes: kept
    _run(core, pos, 297)
    assert len(fake_pool.requests) == n
    _run(core, pos, 4)
    assert len(fake_pool.requests) == n + 1
    assert "timer" in _reasons(core)[-1]


def test_identical_rerun_keeps_the_version_gain_rules(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    t_eta = fake_pool.requests[-1].base.t0 + fake_pool.eta_s

    def rerun_with_gain(gain_s: float) -> int:
        # the current route evaluated now arrives gain_s later than the new one
        fake_pool.script = lambda creq: _with_old(fake_pool, creq, gain_s)
        core.call(core.router.request, "timer", False)
        nav = _run(core, pos, 1)
        return nav["route"]["version"]

    assert rerun_with_gain(0.0) == 1  # identical: kept
    assert rerun_with_gain(120.0) == 1  # 2 min < max(3 min, 1 %): kept
    assert rerun_with_gain(360.0) == 2  # 6 min: replaced
    assert t_eta > 0


def _with_old(fake_pool, creq, gain_s: float, old_valid: bool = True):
    res = fake_pool.default(creq)
    import dataclasses

    return dataclasses.replace(res, eta_old_now=res.optimal.eta + gain_s, old_valid=old_valid)


def test_invalid_old_route_is_replaced(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, 0.0, old_valid=False)
    core.call(core.router.request, "timer", False)
    assert _run(core, pos, 1)["route"]["version"] == 2


def test_route_older_than_20_min_is_replaced(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, 0.0)
    nav = _run(core, pos, 1150)  # timers at 5, 10, 15 min: kept (identical)
    assert nav["route"]["version"] == 1
    nav = _run(core, pos, 60)  # 20 min timer: age exactly 20 min, still kept
    assert nav["route"]["version"] == 1
    nav = _run(core, pos, 300)  # 25 min timer, age > 20 min: replaced
    assert nav["route"]["version"] == 2


def test_course_change_forces_a_replacement(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, -600.0)  # new one is worse
    base = core.client.get("/api/course").json()["version"]
    resp = core.client.post("/api/course/next", json={"base_version": base})
    assert resp.status_code == 200, resp.text
    nav = _run(core, pos, 1)
    assert nav["route"]["version"] == 2
    assert "course" in _reasons(core)[-1]
    assert fake_pool.requests[-1].base.marks[0].mark_id == "jabuka"


def test_manual_wind_change_is_a_non_forced_trigger(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, 60.0)  # 1 min gain
    n = len(fake_pool.requests)
    resp = core.client.post("/api/wind/manual", json={"twd": 40.0, "tws_kn": 15.0, "ref": "T"})
    assert resp.status_code == 200
    nav = _run(core, pos, 1)
    assert len(fake_pool.requests) > n
    assert any("manual" in r for r in _reasons(core)[n:])
    assert nav["route"]["version"] == 1  # kept on a 1 min gain


def test_off_route_sustained_reroutes_and_replaces(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, 0.0)
    # 0.6 nm to the side of the route (route course ~157 deg), still sailing parallel to it
    off = geo.offset(*pos, math.radians(157.0 + 90.0), 0.6)
    nav = _run(core, off, 60)
    assert nav["route"]["off_route"] is False and nav["route"]["version"] == 1
    nav = _run(core, off, 62)
    assert any("off_route" in r for r in _reasons(core))
    assert nav["route"]["version"] == 2


def test_triggers_never_overlap(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.hold = True
    for _ in range(4):
        core.call(core.router.request, "manuel", True)
        core.sail(*pos, 157.0)
        core.tick(1.0)
    st = core.router.health()["pool"]
    assert st["running"] <= 1 and st["pending"] <= 1
    assert fake_pool.max_running == 1
    fake_pool.hold = False
    core.settle()
    nav = _run(core, pos, 1)
    # the running request completes, then only the latest pending one runs
    assert nav["route"]["version"] == 3
    assert fake_pool.superseded >= 2


def test_invalid_worker_route_is_discarded_with_an_alert(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)

    def invalid(creq):
        import dataclasses

        res = fake_pool.default(creq)
        return dataclasses.replace(res, optimal=dataclasses.replace(res.optimal, valid=False))

    fake_pool.script = invalid
    core.call(core.router.request, "manuel", True)
    nav = _run(core, pos, 1)
    assert nav["route"]["version"] == 1  # last good route kept
    assert any(a.startswith("ROUTE INVALIDE") for a in nav["alerts"])
    assert core.router.health()["invalid"] == 1

    def masked(creq):
        from jabuka.route.types import RouteResult

        b = creq.base
        res = fake_pool.default(creq)
        import dataclasses

        bad = RouteResult(
            ok=False, reason="route invalide (terre)", request_id=b.request_id, t0=b.t0
        )
        return dataclasses.replace(res, optimal=bad)

    fake_pool.script = masked
    core.call(core.router.request, "manuel", True)
    nav = _run(core, pos, 1)
    assert nav["route"]["version"] == 1
    assert "ROUTE INVALIDE : route invalide (terre)" in nav["alerts"]
    assert core.router.health()["invalid"] == 2
    # the alert lasts 5 minutes
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, 0.0)
    nav = _run(core, pos, 301)
    assert not any(a.startswith("ROUTE INVALIDE") for a in nav["alerts"])


@pytest.mark.parametrize("status", ["timeout", "crashed"])
def test_timeout_and_crash_keep_the_last_route(routing_core, fake_pool, rh, status) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: PoolOutcome(status, None, 60.0, "boom")
    core.call(core.router.request, "manuel", True)
    nav1 = _run(core, pos, 1)
    nav2 = _run(core, pos, 30)
    assert nav2["route"]["state"] == "ok" and nav2["route"]["version"] == 1
    assert nav2["route"]["age_s"] > nav1["route"]["age_s"]
    assert core.router.health()["failed"] >= 1


def test_route_persists_across_a_restart(routing_core, fake_pool, rh, tmp_path) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    saved = json.loads((tmp_path / "data" / "route.json").read_text())
    assert saved["version"] == 1 and saved["path"]
    core.__exit__(None, None, None)

    from jabuka.common.clock import SimClock

    fake2 = type(fake_pool)()
    fake2.hold = True  # no new cycle completes
    core2 = routing_core(pool_factory=lambda: fake2, clock=SimClock(start_utc=rh.T_START + 600))
    core2.sail(*pos, 157.0)
    nav = core2.tick(1.0)
    r = nav["route"]
    # 03-REVIEW MD-05: restored but not steerable until a worker cycle has re-checked it
    assert r["state"] == "outdated" and r["version"] == 1
    assert r["reason"] == "route sauvegardée : vérification en cours"
    assert r["age_s"] >= 600 and r["target_twa"] is None
    assert core2.client.get("/api/route").json()["version"] == 1  # drawn greyed on the map
    fake2.hold = False
    core2.settle()
    nav = core2.tick(0.0)
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] == 2


def test_corrupt_route_file_is_ignored_with_an_alert(routing_core, fake_pool, rh, tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "route.json").write_text('{"version": 3, "path": [[1, 2]]')
    fake_pool.hold = True
    core = routing_core(pool_factory=lambda: fake_pool)
    lat, lon = rh.boat_near_plic(2.0)
    core.sail(lat, lon, 157.0)
    nav = core.tick(1.0)
    assert nav["route"]["version"] == 0
    assert "Route sauvegardée illisible : ignorée" in nav["alerts"]
    fake_pool.hold = False


def test_request_carries_the_follower_route_time(routing_core, fake_pool, rh) -> None:
    # 03-REVIEW MD-03: the worker re-evaluates the old route from the helm's own projection
    core, pos = _start(routing_core, fake_pool, rh)
    assert fake_pool.requests[0].old_t_here is None  # no route yet
    core.call(core.router.request, "timer", False)
    _run(core, pos, 1)
    creq = fake_pool.requests[-1]
    assert creq.old_path is not None and creq.old_t_here is not None
    assert creq.old_path[0].t <= creq.old_t_here <= creq.old_path[-1].t


# -- detected tack / low-speed COG (03-REVIEW MD-02) ----------------------------------------------
def test_an_early_tack_reroutes_as_outdated(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    core.sail(*pos, 5.0)  # starboard (TWA +40), as the route's first leg
    core.tick(1.0)
    core.settle()
    assert core.tick(0.0)["route"]["version"] == 1
    fake_pool.script = lambda creq: _with_old(fake_pool, creq, 0.0)  # identical: kept if soft
    nav = _run(core, pos, 30, hdg=5.0)
    assert nav["route"]["version"] == 1
    nav = _run(core, pos, 40, hdg=85.0)  # tacks 25 min early, to port (TWA -40)
    tack_reqs = [r for r in _reasons(core) if "tack" in r]
    assert tack_reqs and "off_route" not in tack_reqs[0]  # before the 2 min off-route timer
    assert nav["route"]["version"] == 2  # replaced although identical: outdated for this boat


def test_tack_as_advised_does_not_reroute(routing_core, fake_pool, rh) -> None:
    fake_pool.tack_at_s = None  # one starboard leg: tacking onto it is no reason to reroute
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    core.sail(*pos, 85.0)  # port
    core.tick(1.0)
    core.settle()
    core.tick(0.0)
    nav = _run(core, pos, 40, hdg=5.0)  # tacks onto the route's starboard tack
    assert not any("tack" in r for r in _reasons(core))
    assert nav["route"]["version"] == 1


def test_low_speed_cog_noise_never_fires_off_route(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    v = core.client.get("/api/settings").json()["version"]
    core.client.put("/api/settings", json={"base_version": v, "patch": {"bias_enabled": False}})
    for _ in range(200):  # 1 kn in light air, COG 90 deg off the route, on the route
        core.sail(*pos, 247.0, bsp_kn=1.0)
        nav = core.tick(1.0)
        core.settle()
    assert nav["route"]["off_route"] is False
    assert not any("off_route" in r for r in _reasons(core))


def test_manual_wind_without_gps_time_is_observed(routing_core, fake_pool, rh) -> None:
    """03-REVIEW LO-01: entries made without trusted UTC (t_set_wall None) were never seen:
    no manual reroute trigger, no bias observation."""
    core, pos = _start(routing_core, fake_pool, rh)
    store = core.ctx.nav.manual
    seen = []
    for action in ("set", "clear", "set", "set"):
        if action == "set":
            core.call(store.set, 40.0, 15.0, "T", 0.0, None)
        else:
            core.call(store.clear)
        assert store.entry is None or store.entry.t_set_wall is None
        _run(core, pos, 1)
        seen.append(core.router.manual_version)
    assert seen == [1, 2, 3, 4]
    assert any("manual" in r for r in _reasons(core))


# -- one pack for the core and the worker (03-REVIEW MD-05) ---------------------------------------
def test_pack_replaced_on_disk_raises_a_restart_alert(routing_core, fake_pool, rh, route_pack):
    core, pos = _start(routing_core, fake_pool, rh)
    assert core.router.pack_fp == core.router.pack.fingerprint
    assert fake_pool.requests[-1].pack_fp == core.router.pack_fp
    rh.write_wind(route_pack, twd_deg=270.0)  # a new wind.npz + sidecar, core not restarted
    nav = _run(core, pos, 61)
    assert "PACK DE COURSE MODIFIÉ : redémarrer jabuka-core" in nav["alerts"]


def test_worker_pack_mismatch_raises_the_alert(routing_core, fake_pool, rh) -> None:
    from jabuka.route import cycle
    from jabuka.route.types import RouteResult

    core, pos = _start(routing_core, fake_pool, rh)

    def changed(creq):
        import dataclasses

        b = creq.base
        bad = RouteResult(
            ok=False, reason=f"{cycle.PACK_CHANGED} : x", request_id=b.request_id, t0=b.t0
        )
        return dataclasses.replace(fake_pool.default(creq), optimal=bad)

    fake_pool.script = changed
    core.call(core.router.request, "manuel", True)
    nav = _run(core, pos, 1)
    assert "PACK DE COURSE MODIFIÉ : redémarrer jabuka-core" in nav["alerts"]


# -- pool watchdog (03-REVIEW CR-01) --------------------------------------------------------------
def test_wedged_pool_is_recycled_with_an_alert(routing_core, rh) -> None:
    pools = [rh.FakePool(), rh.FakePool()]
    made: list = []

    def factory():
        made.append(pools[len(made)])
        return made[-1]

    pools[0].hold = True  # the first job never completes: a wedged pool
    core = routing_core(pool_factory=factory)
    pos = rh.boat_near_plic(2.0)
    nav = None
    for _ in range(int(2 * 60 + 5)):
        core.sail(*pos, 157.0)
        nav = core.tick(1.0)
        if len(made) > 1:
            break
    assert len(made) == 2, "the watchdog must replace a pool stuck on one job"
    assert core.router.pool is pools[1]
    assert core.router.health()["pool_recycled"] == 1
    for _ in range(3):
        core.sail(*pos, 157.0)
        nav = core.tick(1.0)
        core.settle()
    nav = core.tick(0.0)
    assert any(a.startswith("ROUTEUR RELANCÉ") for a in nav["alerts"]), nav["alerts"]
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] == 1
    assert not core.router.busy()
    pools[0].hold = False


def test_pool_fault_raises_a_routing_health_alert(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.stats_d.update(faults=1, last_fault="OSError(12, 'Cannot allocate memory')")
    nav = _run(core, pos, 1)
    alerts = [a for a in nav["alerts"] if a.startswith("ROUTEUR RELANCÉ")]
    assert alerts and "Cannot allocate memory" in alerts[0]
    assert core.router.health()["pool"]["faults"] == 1
    nav = _run(core, pos, 301)  # the alert lasts 5 minutes
    assert not any(a.startswith("ROUTEUR RELANCÉ") for a in nav["alerts"])
