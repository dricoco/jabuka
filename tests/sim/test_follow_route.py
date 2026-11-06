"""jabuka-sim --follow --follow-route (quick 001, the local demo's helmsman): with a valid route the
boat sails the route's tack and target TWA, tacks once when the route's countdown reaches 0, obeys
a route on the other tack (but not a lagging message just after its own tack), and falls back to
the layline helmsman without a valid route. Without --follow-route nothing changes."""

from __future__ import annotations

import math

import pytest

from jabuka.sim.synth import FollowHelm, SynthBoat, SynthConfig, build_arg_parser, config_from_args


def _nav(route: dict | None) -> dict:
    return {
        "type": "nav",
        "wind": {"twd_t": 161.0},
        "helm": {"primary": "twa_up", "target": 40.0},
        "layline": {"state": "normal", "tack": "stbd", "countdown_s": 600.0},
        "mark": {"btw_t": 170.0, "dtw_nm": 2.0},
        "route": route,
    }


def _route(**kw: object) -> dict:
    r = {
        "state": "ok",
        "version": 1,
        "primary": "twa",
        "target": 38.0,
        "target_tack": "stbd",
        "countdown_s": 300.0,
        "tack_lat": 43.70,
        "tack_lon": 15.80,
    }
    r.update(kw)
    return r


def test_sails_the_route_and_tacks_once_per_advised_tack() -> None:
    helm = FollowHelm("http://127.0.0.1:9", 45.0, follow_route=True)
    state = SynthBoat(SynthConfig(twd=161.0, twa=45.0)).state
    hdg, f = helm.command(_nav(_route()), state)
    assert hdg == pytest.approx(123.0) and f == 1.0 and helm.tacks == 0  # 161 - 38, starboard
    due = _nav(_route(countdown_s=0.0))
    hdg, f = helm.command(due, state)
    assert hdg == pytest.approx(199.0) and f == 0.5 and helm.tacks == 1  # 161 + 38, port
    for _ in range(30):  # the same (lagging) advice: no second tack
        hdg, _ = helm.command(due, state)
    assert hdg == pytest.approx(199.0) and helm.tacks == 1
    # a lagging message still on starboard just after the tack is not obeyed...
    helm.command(_nav(_route(countdown_s=200.0, version=2)), state)
    assert helm.tacks == 1
    # ...but a route that keeps wanting starboard is, once the boat has settled
    for _ in range(FollowHelm.ROUTE_SETTLE_S + 1):
        hdg, _ = helm.command(_nav(_route(countdown_s=200.0, version=2)), state)
    assert helm.tacks == 2 and hdg == pytest.approx(123.0)


def test_route_on_the_other_tack_at_start_and_reach_heading() -> None:
    helm = FollowHelm("http://127.0.0.1:9", 45.0, follow_route=True)
    state = SynthBoat(SynthConfig(twd=161.0, twa=45.0)).state
    hdg, _ = helm.command(_nav(_route(target_tack="port", countdown_s=900.0)), state)
    assert helm.tacks == 1 and hdg == pytest.approx(199.0)
    hdg, _ = helm.command(_nav(_route(primary="hdg", target=250.0)), state)
    assert hdg == pytest.approx(250.0)


def test_falls_back_to_the_laylines_without_a_valid_route() -> None:
    for follow_route, route in ((True, {"state": "computing"}), (True, None), (False, _route())):
        helm = FollowHelm("http://127.0.0.1:9", 45.0, follow_route=follow_route)
        state = SynthBoat(SynthConfig(twd=161.0, twa=45.0)).state
        hdg, _ = helm.command(_nav(route), state)
        assert hdg == pytest.approx(121.0), (follow_route, route)  # 161 - layline target 40


def test_cli_flag() -> None:
    cfg = config_from_args(build_arg_parser().parse_args(["--follow", "http://x:1"]))
    assert cfg.follow_route is False
    args = ["--follow", "http://x:1", "--follow-route"]
    assert config_from_args(build_arg_parser().parse_args(args)).follow_route is True
    assert math.isfinite(SynthConfig().twd)
