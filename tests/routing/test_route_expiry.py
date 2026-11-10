"""Route expiry (03-REVIEW CR-02): a displayed route goes stale, then is withdrawn ("outdated": no
target, no countdown, so the helm falls back to the Phase 2 laylines) when the worker keeps
failing, when the course changes under it, when the missed-tack reroute fails or hangs, and when
no routing cycle has confirmed it for 40 min. Regression tests from the reviewer's scripts
stale_route.py, course_change.py and missed_stuck2.py."""

from __future__ import annotations

import json

from jabuka.core.router_service import MISSED_MAX_S, ROUTE_STALE_S
from jabuka.route.pool import PoolOutcome


def _start(routing_core, fake_pool, rh, hdg: float = 157.0):
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    core.sail(*pos, hdg)
    core.tick(1.0)
    core.settle()
    nav = core.tick(1.0)
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] == 1, nav["route"]
    return core, pos


def _step(core, pos, hdg: float = 157.0, settle: bool = True) -> dict:
    core.sail(*pos, hdg)
    nav = core.tick(1.0)
    if settle:
        core.settle()
    return nav


def _withdrawn(r: dict) -> None:
    """Nothing the helm could steer: routeOk() is false, the laylines come back."""
    assert r["state"] == "outdated", r
    assert r["target_twa"] is None and r["target"] is None and r["countdown_s"] is None
    assert r["cost_text"] is None and r["updating"] is False


def test_failing_worker_goes_stale_then_is_withdrawn(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: PoolOutcome("timeout", None, 60.0, "no result after 60 s")
    nav = None
    for _ in range(301):  # first timer cycle fails
        nav = _step(core, pos)
    nav = core.tick(0.0)
    r = nav["route"]
    assert r["state"] == "ok" and r["stale"] is True
    assert r["last_fail"] == "timeout: no result after 60 s"
    assert r["target_twa"] is not None  # still steerable, flagged
    for _ in range(3 * 3600):
        nav = _step(core, pos)
        if nav["route"]["state"] != "ok":
            break
    r = nav["route"]
    _withdrawn(r)
    assert r["reason"].startswith("le routeur échoue") and "timeout" in r["reason"]
    assert r["age_s"] <= 15 * 60  # withdrawn within minutes, not hours
    assert r["version"] == 1 and r["computed_utc"] is not None
    # the worker recovers: the next retry adopts a fresh route (forced: the old one is withdrawn)
    fake_pool.script = None
    fake_pool.eta_old_now = None
    for _ in range(61):
        nav = _step(core, pos)
    nav = core.tick(0.0)
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] == 2
    assert nav["route"]["stale"] is False


def test_course_change_withdraws_the_route(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: PoolOutcome("crashed", None, 1.0, "BrokenProcessPool")
    base = core.client.get("/api/course").json()["version"]
    assert core.client.post("/api/course/next", json={"base_version": base}).status_code == 200
    nav = None
    for _ in range(120):
        nav = _step(core, pos)
    r = nav["route"]
    _withdrawn(r)
    # every cycle after the edit ran for the new course and failed: the helm sees why
    # (quick-261110-klg; it read "recalcul en cours" forever before)
    assert r["reason"] == "parcours modifié : crashed: BrokenProcessPool"


def test_course_change_reason_while_computing_then_failed(routing_core, fake_pool, rh) -> None:
    """quick-261110-klg: "recalcul en cours" while no cycle for the CURRENT course version has
    failed (an older-version failure is not shown), the real failure once one has."""
    core, pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: PoolOutcome("timeout", None, 60.0, "no result after 60 s")
    core.call(lambda: core.router.force("test"))
    _step(core, pos)
    assert core.call(lambda: core.router._last_fail) == "timeout: no result after 60 s"
    try:
        fake_pool.hold = True
        fake_pool.script = lambda creq: PoolOutcome("crashed", None, 1.0, "BrokenProcessPool")
        base = core.client.get("/api/course").json()["version"]
        assert core.client.post("/api/course/next", json={"base_version": base}).status_code == 200
        nav = None
        for _ in range(5):
            nav = _step(core, pos, settle=False)
        r = nav["route"]
        _withdrawn(r)
        assert r["reason"] == "parcours modifié : recalcul en cours"
    finally:
        fake_pool.hold = False
    core.settle()
    nav = _step(core, pos)
    r = nav["route"]
    _withdrawn(r)
    assert r["reason"] == "parcours modifié : crashed: BrokenProcessPool"


def test_rounding_the_mark_keeps_the_route(routing_core, fake_pool, rh) -> None:
    core, _pos = _start(routing_core, fake_pool, rh)
    fake_pool.script = lambda creq: PoolOutcome("crashed", None, 1.0, "BrokenProcessPool")
    at_mark = rh.PLIC_SESTRE  # the end of the route's first leg
    _step(core, at_mark)
    base = core.client.get("/api/course").json()["version"]
    assert core.client.post("/api/course/next", json={"base_version": base}).status_code == 200
    nav = None
    for _ in range(5):
        nav = _step(core, at_mark)
    assert nav["route"]["state"] == "ok", nav["route"]


def _along(rh, start):
    """The boat sails the route's first leg (towards Plić Sestre, 2 h) on the old tack."""
    mlat, mlon = rh.PLIC_SESTRE

    def pos(s: float) -> tuple[float, float]:
        f = min(1.0, s / 7200.0)
        return start[0] + f * (mlat - start[0]), start[1] + f * (mlon - start[1])

    return pos


def test_missed_tack_with_a_failing_reroute_is_withdrawn(routing_core, fake_pool, rh) -> None:
    fake_pool.tack_at_s = 60.0
    core, start = _start(routing_core, fake_pool, rh, hdg=5.0)
    pos = _along(rh, start)
    fake_pool.script = lambda creq: PoolOutcome("crashed", None, 1.0, "BrokenProcessPool")
    nav = None
    updating_at = None
    for i in range(1, 1800):
        nav = _step(core, pos(i), 5.0)
        if nav["route"]["updating"] and updating_at is None:
            updating_at = i
        if nav["route"]["state"] == "outdated":
            break
    r = nav["route"]
    _withdrawn(r)
    assert r["reason"].startswith("virement manqué : nouvelle route impossible"), r["reason"]
    assert "BrokenProcessPool" in r["reason"]
    assert r["missed"] is True
    assert any("missed" in reasons for _t, reasons in core.router.request_log)
    # "Route mise à jour…" is shown at most until the reroute's failure, never for 30 min
    assert updating_at is None or i - updating_at <= 5


def test_missed_tack_reroute_that_hangs_times_out(routing_core, fake_pool, rh) -> None:
    fake_pool.tack_at_s = 60.0
    core, start = _start(routing_core, fake_pool, rh, hdg=5.0)
    pos = _along(rh, start)
    nav = None
    s = 0
    while s < 400:
        s += 1
        nav = _step(core, pos(s), 5.0)
        if nav["route"]["countdown_s"] is not None and nav["route"]["countdown_s"] < -60:
            break
    fake_pool.hold = True  # the missed-tack reroute hangs
    end = s + 200
    while s < end and not nav["route"]["missed"]:
        s += 1
        nav = _step(core, pos(s), 5.0, settle=False)
    assert nav["route"]["updating"] is True and nav["route"]["state"] == "ok"
    for _ in range(int(MISSED_MAX_S) + 2):
        s += 1
        nav = _step(core, pos(s), 5.0, settle=False)
    _withdrawn(nav["route"])
    assert nav["route"]["reason"].startswith("virement manqué")
    fake_pool.hold = False


def test_unconfirmed_route_expires(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    # no cycle ever completes again (every answer is superseded): nothing confirms the route
    fake_pool.script = lambda creq: PoolOutcome("superseded", None, 0.0, None)
    nav = None
    for _ in range(int(ROUTE_STALE_S) - 10):
        nav = _step(core, pos)
    assert nav["route"]["state"] == "ok"
    for _ in range(20):
        nav = _step(core, pos)
    _withdrawn(nav["route"])
    assert nav["route"]["reason"].startswith("route périmée (40 min)")


def test_kept_route_is_confirmed(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    core.client.put(
        "/api/settings",
        json={
            "base_version": core.client.get("/api/settings").json()["version"],
            "patch": {"route_cadence_min": 30.0, "bias_enabled": False},
        },
    )

    def kept(creq):
        import dataclasses

        res = fake_pool.default(creq)
        return dataclasses.replace(res, eta_old_now=res.optimal.eta, old_valid=True)

    fake_pool.script = kept
    nav = None
    for _ in range(50 * 60):
        nav = _step(core, pos)
        assert nav["route"]["state"] == "ok", nav["route"]


def test_route_file_without_marks_still_loads(routing_core, fake_pool, rh, tmp_path) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    path = tmp_path / "data" / "route.json"
    doc = json.loads(path.read_text())
    assert doc["marks"] and doc["marks"][0][0] == "plic-sestre"
    core.__exit__(None, None, None)
    del doc["marks"]  # a route.json written before CR-02
    path.write_text(json.dumps(doc))
    path.with_name("route.json.bak").unlink(missing_ok=True)
    fake2 = type(fake_pool)()
    fake2.hold = True
    core2 = routing_core(pool_factory=lambda: fake2)
    core2.sail(*pos, 157.0)
    nav = core2.tick(1.0)
    assert nav["route"]["version"] == 1
    fake2.hold = False
