"""Laylines that match the water (NAV-01/02/03): current only when enabled and never twice, sailed
angles with a per-side polar fallback, leg hysteresis on the layline TWD, the countdown along the
boat's actual track, overstood time and the fetching course to steer.

Local frame: wind from 000, anchor at ANCHOR; RESEARCH Pattern 4 prototype numbers."""

from __future__ import annotations

import math

import pytest

from jabuka.common.clock import SimClock
from jabuka.common.conventions import apparent_from_true
from jabuka.common.units import kn_to_ms
from jabuka.core.nav_service import NavService
from jabuka.core.state import StateStore
from jabuka.nav import geo
from jabuka.nav.laylines import Anchor, BoatState, solve
from jabuka.nav.polar import Targets
from jabuka.nav.tacks import TackSample
from jabuka.nav.wind import INPUT_PATHS, WindSolution, current_true

R = math.radians
ANCHOR = Anchor(43.5, 15.6)
TARGETS = Targets(up_twa=45.0, up_bsp=6.0, down_twa=150.0, down_bsp=7.0)
A_H = 5.0 / (2 * 6.0 * math.cos(R(45)))  # 0.5893 h
EAST_1KN = (1.0, 0.0)


def _wind(twd_deg=0.0, twa_deg=45.0, in_zone=False) -> WindSolution:
    twd = R(twd_deg)
    return WindSolution(
        source="LIVE", twd=twd, twd_lay=twd, tws=6.0, twa=R(twa_deg), in_zone=in_zone
    )


def _boat_at(bearing_from_anchor_deg: float, dist_nm: float, **kw) -> BoatState:
    lat, lon = geo.offset(ANCHOR.lat, ANCHOR.lon, R(bearing_from_anchor_deg), dist_nm)
    return BoatState(lat=lat, lon=lon, **kw)


def _boat_local(x: float, y: float, **kw) -> BoatState:
    lat, lon = geo.from_local(x, y, ANCHOR.lat, ANCHOR.lon)
    return BoatState(lat=lat, lon=lon, **kw)


def _ab(res) -> tuple[float, float]:
    lay = res.layline
    a = lay["countdown_s"] / 3600.0
    return a, lay["time_s"] / 3600.0 - a


# -- current (NAV-03) -----------------------------------------------------------------------------
def test_prototype_with_and_without_current() -> None:
    boat = _boat_at(180.0, 5.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR, current_kn=EAST_1KN)
    a, b = _ab(res)
    assert a == pytest.approx(0.728, abs=0.002)
    assert b == pytest.approx(0.450, abs=0.002)
    assert res.layline["current"] is True
    res = solve(boat, _wind(), TARGETS, ANCHOR)
    a, b = _ab(res)
    assert a == pytest.approx(A_H, abs=0.002) and b == pytest.approx(A_H, abs=0.002)
    assert res.layline["current"] is False


def test_current_ignored_in_the_jabuka_zone() -> None:
    boat = _boat_at(180.0, 5.0)
    res = solve(boat, _wind(in_zone=True), TARGETS, ANCHOR, current_kn=EAST_1KN)
    a, _ = _ab(res)
    assert a == pytest.approx(A_H, abs=0.002)
    assert res.layline["current"] is False


# -- sailed angles (Pitfall 8) --------------------------------------------------------------------
def _sailed(up_stbd=None, up_port=None) -> dict:
    return {"up": {"stbd": up_stbd, "port": up_port}, "down": {"stbd": None, "port": None}}


def test_sailed_mode_never_adds_the_current() -> None:
    sailed = _sailed(TackSample(-50.0, 5.5), TackSample(49.0, 5.8))
    boat = _boat_at(180.0, 5.0)
    with_c = solve(boat, _wind(), TARGETS, ANCHOR, current_kn=EAST_1KN, src="sailed", sailed=sailed)
    no_c = solve(boat, _wind(), TARGETS, ANCHOR, src="sailed", sailed=sailed)
    assert with_c.layline["src"] == "sailed"
    assert with_c.layline["current"] is False
    assert _ab(with_c) == pytest.approx(_ab(no_c), abs=1e-6)
    # geometry: ground tracks 310 deg @ 5.5 kn (stbd) and 049 deg @ 5.8 kn (port)
    g_s = (5.5 * math.sin(R(-50.0)), 5.5 * math.cos(R(-50.0)))
    g_p = (5.8 * math.sin(R(49.0)), 5.8 * math.cos(R(49.0)))
    det = g_s[0] * g_p[1] - g_s[1] * g_p[0]
    a = (0.0 * g_p[1] - 5.0 * g_p[0]) / det
    b = (g_s[0] * 5.0 - g_s[1] * 0.0) / det
    assert _ab(no_c)[0] == pytest.approx(a, abs=1e-3)
    assert _ab(no_c)[1] == pytest.approx(b, abs=1e-3)


def test_sailed_side_without_sample_falls_back_to_polar() -> None:
    sailed = _sailed(TackSample(-50.0, 5.5), None)
    boat = _boat_at(180.0, 5.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR, current_kn=EAST_1KN, src="sailed", sailed=sailed)
    assert res.layline["src"] == "polar"  # only one side sailed
    assert res.layline["current"] is True  # the polar side carries the current
    g_s = (5.5 * math.sin(R(-50.0)), 5.5 * math.cos(R(-50.0)))
    g_p = (6.0 * math.sin(R(45.0)) + 1.0, 6.0 * math.cos(R(45.0)))
    det = g_s[0] * g_p[1] - g_s[1] * g_p[0]
    a = (0.0 * g_p[1] - 5.0 * g_p[0]) / det
    assert _ab(res)[0] == pytest.approx(a, abs=1e-3)
    # no samples at all: plain polar
    res = solve(boat, _wind(), TARGETS, ANCHOR, src="sailed", sailed=_sailed())
    assert res.layline["src"] == "polar"
    assert _ab(res)[0] == pytest.approx(A_H, abs=0.002)


def test_polar_mode_ignores_samples() -> None:
    sailed = _sailed(TackSample(-50.0, 5.5), TackSample(49.0, 5.8))
    res = solve(_boat_at(180.0, 5.0), _wind(), TARGETS, ANCHOR, src="polar", sailed=sailed)
    assert res.layline["src"] == "polar"
    assert _ab(res)[0] == pytest.approx(A_H, abs=0.002)


# -- leg type hysteresis on twd_lay ---------------------------------------------------------------
def test_leg_hysteresis_on_layline_twd() -> None:
    # beta = 45 + 3 -> still a beat when coming from a beat; 45 + 6 -> reach
    w = WindSolution(source="LIVE", twd=R(30.0), twd_lay=R(0.0), tws=6.0, twa=R(45.0))
    boat3 = _boat_at(180.0 + 48.0, 5.0)  # anchor bears 048 from the boat
    boat6 = _boat_at(180.0 + 51.0, 5.0)
    assert solve(boat3, w, TARGETS, ANCHOR, prev_leg="beat").leg == "beat"
    assert solve(boat6, w, TARGETS, ANCHOR, prev_leg="beat").leg == "reach"
    assert solve(boat3, w, TARGETS, ANCHOR).leg == "reach"


# -- countdown along the actual track --------------------------------------------------------------
def test_countdown_follows_the_actual_track() -> None:
    # starboard tack heading 315, the boat sails 5 deg lower: COG 310 at 6 kn
    boat = _boat_at(180.0, 5.0, hdg=R(315.0), cog=R(310.0), sog_kn=6.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR)
    # analytic: (0, -5) + s * u(310) meets the port layline t * u(045), t <= 0
    ux, uy = math.sin(R(310.0)), math.cos(R(310.0))
    gx, gy = math.sin(R(45.0)), math.cos(R(45.0))
    # s*ux - t*gx = 0 ; s*uy - t*gy = 5
    det = ux * (-gy) - uy * (-gx)
    s_nm = (0.0 * (-gy) - 5.0 * (-gx)) / det
    t = (ux * 5.0 - uy * 0.0) / det
    assert s_nm > 0 and t <= 0
    assert res.layline["countdown_s"] == pytest.approx(s_nm / 6.0 * 3600.0, abs=1.0)
    assert abs(res.layline["countdown_s"] - A_H * 3600.0) > 5.0  # not the polar a
    assert res.layline["dist_nm"] == pytest.approx(s_nm, abs=0.01)


def test_countdown_falls_back_to_polar_when_slow() -> None:
    boat = _boat_at(180.0, 5.0, hdg=R(315.0), cog=R(310.0), sog_kn=0.5)
    res = solve(boat, _wind(), TARGETS, ANCHOR)
    assert res.layline["countdown_s"] == pytest.approx(A_H * 3600.0, abs=1.0)
    # a track that never meets the layline (heading away) also falls back
    boat = _boat_at(180.0, 5.0, hdg=R(315.0), cog=R(200.0), sog_kn=6.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR)
    assert res.layline["countdown_s"] == pytest.approx(A_H * 3600.0, abs=1.0)


# -- overstood / fetching -------------------------------------------------------------------------
def test_overstood_time() -> None:
    # D = a * g_stbd + b * g_port with a = -0.118 h, b = 2 h (anchor bears ~048: a beat within
    # the +5 deg hysteresis)
    g_s = (6.0 * math.sin(R(315.0)), 6.0 * math.cos(R(315.0)))
    g_p = (6.0 * math.sin(R(45.0)), 6.0 * math.cos(R(45.0)))
    a, b = -0.118, 2.0
    dx, dy = a * g_s[0] + b * g_p[0], a * g_s[1] + b * g_p[1]
    boat = _boat_local(-dx, -dy)
    res = solve(boat, _wind(), TARGETS, ANCHOR, prev_leg="beat")
    assert res.leg == "beat"
    assert res.layline["state"] == "overstood"
    assert res.layline["overstood_s"] == pytest.approx(425.0, abs=2.0)
    assert res.layline["countdown_s"] is None


def test_fetching_gives_the_course_to_steer() -> None:
    boat = _boat_at(132.0, 3.0, hdg=R(315.0))  # anchor bears 312
    res = solve(boat, _wind(), TARGETS, ANCHOR, prev_leg="beat")
    assert res.layline["state"] == "fetching"
    assert res.helm["cts_t"] == pytest.approx(312.0, abs=0.1)
    assert res.helm["primary"] == "twa_up"


def test_fetching_cts_is_current_corrected() -> None:
    boat = _boat_at(132.0, 3.0, hdg=R(315.0), bsp_kn=6.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR, prev_leg="beat", current_kn=EAST_1KN)
    assert res.layline["state"] == "fetching"
    cts = R(res.helm["cts_t"])
    # water velocity at the CTS + current points at the anchor (312)
    gx, gy = 6.0 * math.sin(cts) + 1.0, 6.0 * math.cos(cts)
    assert math.degrees(math.atan2(gx, gy)) % 360.0 == pytest.approx(312.0, abs=0.2)
    assert res.helm["cts_t"] != pytest.approx(312.0, abs=1.0)


def test_reach_cts_is_current_corrected() -> None:
    boat = _boat_at(270.0, 3.0, hdg=R(80.0), sog_kn=7.0)  # anchor bears 090
    res = solve(_boat_at(270.0, 3.0), _wind(twa_deg=90.0), TARGETS, ANCHOR, reach_bsp_kn=7.0)
    assert res.helm["cts_t"] == pytest.approx(90.0, abs=0.1)
    res = solve(
        boat,
        _wind(twa_deg=90.0),
        TARGETS,
        ANCHOR,
        reach_bsp_kn=7.0,
        current_kn=(0.0, 1.0),  # 1 kn towards north: steer south of 090
    )
    cts = R(res.helm["cts_t"])
    gx, gy = 7.0 * math.sin(cts), 7.0 * math.cos(cts) + 1.0
    assert math.degrees(math.atan2(gx, gy)) % 360.0 == pytest.approx(90.0, abs=0.2)
    assert res.helm["cts_t"] > 90.0


# -- NavService wiring ----------------------------------------------------------------------------
def _nav_with_inputs(tmp_path, **settings) -> tuple[NavService, StateStore]:
    clock = SimClock()
    state = StateStore(clock)
    nav = NavService(state, clock, tmp_path)
    if settings:
        nav.settings_store.update(settings, nav.settings_store.version)
    target = nav.course.active_target()
    twd, hdg = R(161.0), R(116.0)
    lat, lon = geo.offset(target.anchor_lat, target.anchor_lon, twd + math.pi, 3.0)
    aw = apparent_from_true(twd, kn_to_ms(12.0), kn_to_ms(6.0), hdg)
    values = [
        {"path": "environment.wind.angleApparent", "value": aw.awa},
        {"path": "environment.wind.speedApparent", "value": aw.aws},
        {"path": "navigation.speedThroughWater", "value": kn_to_ms(6.0)},
        {"path": "navigation.heading", "value": hdg, "ref": "T"},
        {"path": "navigation.position", "value": {"latitude": lat, "longitude": lon}},
        {"path": "navigation.courseOverGroundTrue", "value": hdg, "ref": "T"},
        {"path": "navigation.speedOverGround", "value": kn_to_ms(6.0)},
        {"path": "environment.current.set", "value": R(85.3), "ref": "M"},  # 090 T
        {"path": "environment.current.drift", "value": kn_to_ms(1.0)},
    ]
    state.update_values("fastnet", values, clock.monotonic())
    return nav, state


def test_nav_service_applies_current_only_when_enabled(tmp_path) -> None:
    nav, _ = _nav_with_inputs(tmp_path / "a")
    msg = nav.update()
    assert msg["leg"] == "beat" and msg["layline"]["current"] is False
    nav, state = _nav_with_inputs(tmp_path / "b", use_current=True)
    msg_c = nav.update()
    assert msg_c["layline"]["current"] is True
    assert msg_c["layline"]["time_s"] != msg["layline"]["time_s"]
    rows = {r["path"]: r["value"] for r in state.rows() if r["src"] == "nav"}
    assert rows["nav.tacks.stbd"] == {"up": [], "down": []}
    assert rows["nav.tacks.port"] == {"up": [], "down": []}


def test_nav_service_current_set_is_converted_to_true(tmp_path) -> None:
    nav, state = _nav_with_inputs(tmp_path, use_current=True)
    cur = current_true({p: state.latest(p) for p in INPUT_PATHS}, nav.settings)
    assert math.degrees(cur[0]) == pytest.approx(90.0, abs=1e-6)  # 85.3 M + 4.7
    assert cur[1] == pytest.approx(kn_to_ms(1.0))


def test_nav_service_current_ignored_in_the_zone(tmp_path) -> None:
    nav, state = _nav_with_inputs(tmp_path, use_current=True)
    pos = state.latest("navigation.position")["value"]
    nav.settings_store.update(
        {"zone_lat": pos["latitude"], "zone_lon": pos["longitude"], "zone_radius_nm": 1.0},
        nav.settings_store.version,
    )
    msg = nav.update()
    assert msg["wind"]["in_zone"] is True
    assert msg["boat"]["heading_src"] == "cog"
    assert msg["layline"]["current"] is False
    assert "CAP NON FIABLE (zone Jabuka)" in msg["alerts"]


def test_nav_service_sailed_setting_without_samples_reports_polar(tmp_path) -> None:
    nav, _ = _nav_with_inputs(tmp_path, layline_source="sailed")
    assert nav.update()["layline"]["src"] == "polar"
