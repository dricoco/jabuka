"""Soak finding (plan 04-01, clock-jump): when the trusted UTC steps BACK (GPS time +1 h, then
back), the router kept its last request time and its route t0 in the "future": the reroute timer
(now - last request >= cadence) stayed silent and the route never aged, so routing froze for up to
an hour. A backward step must reroute at once, and a route computed for a future time is not
steered meanwhile."""

from __future__ import annotations

from jabuka.route.advice import TriggerInputs, Triggers


def test_triggers_fire_when_time_steps_back() -> None:
    tr = Triggers(cadence_s=300.0)
    inputs = TriggerInputs(has_route=True)
    tr.mark_requested(10_000.0, inputs)
    assert tr.check(10_100.0, inputs) == []  # within the cadence: nothing
    back = tr.check(10_000.0 - 3600.0, inputs)  # an hour back
    assert [t.reason for t in back] == ["clock"] and back[0].forced is True
    assert tr.check(10_000.0 - 5.0, inputs) == []  # small jitter is not a step


def _start(routing_core, fake_pool, rh):
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    core.sail(*pos, 157.0)
    core.tick(1.0)
    core.settle()
    nav = core.tick(1.0)
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] == 1, nav["route"]
    return core, pos


def _step(core, pos) -> dict:
    core.sail(*pos, 157.0)
    nav = core.tick(1.0)
    core.settle()
    return nav


def test_router_reroutes_after_a_backward_time_step(routing_core, fake_pool, rh) -> None:
    core, pos = _start(routing_core, fake_pool, rh)
    t = core.clock.now_utc().timestamp()
    core.clock.observe_utc(t + 3600.0)  # GPS time +1 h (SimClock: mono moves forward)
    for _ in range(5):
        nav = _step(core, pos)
    v_fwd = nav["route"]["version"]
    assert v_fwd >= 2, nav["route"]  # the forward step outdated the route: rerouted
    core.clock.observe_utc(t + 10.0)  # ... and back: UTC an hour earlier than the route's t0
    versions = []
    states = []
    for _ in range(10):  # ten seconds, nowhere near an hour
        nav = _step(core, pos)
        versions.append(nav["route"]["version"])
        states.append(nav["route"]["state"])
    assert max(versions) > v_fwd, (versions, nav["route"])
    req_t = [rt for rt, _reasons in core.router.request_log][-1]
    assert abs(req_t - (t + 10.0)) < 30.0  # the new route is computed for the real time
    assert states[-1] == "ok", states
