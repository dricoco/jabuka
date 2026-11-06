"""Layline decomposition, leg type and the primary-number hysteresis (NAV-01/02, HELM-02)."""

from __future__ import annotations

import math

import pytest

from jabuka.nav import geo
from jabuka.nav.laylines import Anchor, BoatState, decompose, select_primary, solve
from jabuka.nav.polar import Targets
from jabuka.nav.wind import WindSolution

ANCHOR = Anchor(43.5, 15.6)
TARGETS = Targets(up_twa=45.0, up_bsp=6.0, down_twa=150.0, down_bsp=7.0)
A_H = 5.0 / (2 * 6.0 * math.cos(math.radians(45)))  # 0.5893 h


def _wind(twd_deg: float = 0.0, twa_deg: float = 45.0, tws_ms: float = 6.0) -> WindSolution:
    twd = math.radians(twd_deg)
    return WindSolution(source="LIVE", twd=twd, twd_lay=twd, tws=tws_ms, twa=math.radians(twa_deg))


def _boat_at(bearing_from_anchor_deg: float, dist_nm: float, **kw) -> BoatState:
    lat, lon = geo.offset(ANCHOR.lat, ANCHOR.lon, math.radians(bearing_from_anchor_deg), dist_nm)
    return BoatState(lat=lat, lon=lon, **kw)


def test_symmetric_beat_countdown() -> None:
    boat = _boat_at(180.0, 5.0, hdg=math.radians(315), sog_kn=6.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR)
    assert res.leg == "beat"
    lay = res.layline
    assert lay["state"] == "normal"
    assert lay["tack"] == "stbd"
    assert A_H == pytest.approx(0.5893, abs=1e-4)
    assert lay["countdown_s"] == pytest.approx(A_H * 3600, abs=1.0)
    assert lay["time_s"] - lay["countdown_s"] == pytest.approx(A_H * 3600, abs=1.0)
    assert lay["dist_nm"] == pytest.approx(A_H * 6.0, abs=0.01)
    assert lay["other_tack_hdg_t"] == pytest.approx(45.0)
    assert res.ttw_s == pytest.approx(2 * A_H * 3600, abs=1.0)
    assert res.dtw_nm == pytest.approx(5.0, abs=1e-6)
    assert res.helm["primary"] == "twa_up"
    assert res.helm["target"] == 45.0
    assert res.helm["deviation"] == 0.0
    assert res.target_bsp_kn == 6.0


def test_port_tack_swaps_roles() -> None:
    boat = _boat_at(180.0, 5.0)
    res = solve(boat, _wind(twa_deg=-45.0), TARGETS, ANCHOR)
    assert res.layline["tack"] == "port"
    assert res.layline["other_tack_hdg_t"] == pytest.approx(315.0)
    assert res.layline["countdown_s"] == pytest.approx(A_H * 3600, abs=1.0)


def test_overstood_on_starboard() -> None:
    """Starboard tack (heading 315) past the port layline: the anchor bears 048, beyond the 45 deg
    tack angle. Overstood only exists on a beat, so the boat comes from a beat (prev_leg) and
    stays in it inside the +5 deg leg hysteresis; a mark further abeam is a reach (CTS)."""
    boat = _boat_at(228.0, 6.0)  # anchor bears 048 from the boat
    res = solve(boat, _wind(), TARGETS, ANCHOR, prev_leg="beat")
    assert res.leg == "beat"
    lay = res.layline
    assert lay["state"] == "overstood"
    assert lay["countdown_s"] is None and lay["dist_nm"] is None
    assert lay["overstood_s"] > 0
    # the same geometry without a beat behind it is a (close) reach
    assert solve(boat, _wind(), TARGETS, ANCHOR).leg == "reach"
    # 6 nm abeam is a reach whatever came before
    assert solve(_boat_at(270.0, 6.0), _wind(), TARGETS, ANCHOR, prev_leg="beat").leg == "reach"


def test_fetching_on_current_tack() -> None:
    boat = _boat_at(132.0, 3.0)  # anchor bears 312: freer than the 315 starboard heading
    res = solve(boat, _wind(), TARGETS, ANCHOR, prev_leg="beat")
    assert res.leg == "beat"
    assert res.layline["state"] == "fetching"
    assert res.layline["countdown_s"] is None
    assert res.ttw_s == pytest.approx(3.0 / 6.0 * 3600, abs=1.0)


def test_reach_leg_has_no_layline_and_shows_cts() -> None:
    boat = _boat_at(270.0, 3.0, hdg=math.radians(80.0), sog_kn=7.0)  # anchor bears 090
    res = solve(boat, _wind(twa_deg=90.0), TARGETS, ANCHOR, reach_bsp_kn=7.5)
    assert res.leg == "reach"
    assert res.layline is None
    assert res.helm["primary"] == "cts"
    assert res.helm["cts_t"] == pytest.approx(math.degrees(res.btw), abs=0.05)
    assert res.helm["cts_t"] == pytest.approx(90.0, abs=0.1)
    assert res.helm["deviation"] == pytest.approx(-10.0, abs=0.1)
    assert res.ttw_s == pytest.approx(3.0 / 7.5 * 3600, abs=1.0)


def test_run_uses_downwind_angles() -> None:
    boat = _boat_at(0.0, 5.0)  # boat upwind of the anchor
    res = solve(boat, _wind(twa_deg=150.0), TARGETS, ANCHOR)
    assert res.leg == "run"
    assert res.helm["primary"] == "twa_down"
    assert res.layline["state"] == "normal"
    assert res.layline["other_tack_hdg_t"] == pytest.approx(150.0)


def test_layline_geojson_two_lines_ending_at_anchor() -> None:
    boat = _boat_at(180.0, 5.0)
    gj = solve(boat, _wind(), TARGETS, ANCHOR).layline["geojson"]
    assert gj["type"] == "FeatureCollection"
    feats = gj["features"]
    assert [f["properties"]["tack"] for f in feats] == ["stbd", "port"]
    for f in feats:
        assert f["geometry"]["type"] == "LineString"
        far, end = f["geometry"]["coordinates"]
        assert end == [ANCHOR.lon, ANCHOR.lat]
        b, d = geo.bearing_distance(end[1], end[0], far[1], far[0])
        assert d == pytest.approx(7.5, abs=0.01)  # 1.5 x DTW
    # the starboard layline runs back towards the south-east (reciprocal of 315)
    b_stbd, _ = geo.bearing_distance(
        ANCHOR.lat,
        ANCHOR.lon,
        feats[0]["geometry"]["coordinates"][0][1],
        feats[0]["geometry"]["coordinates"][0][0],
    )
    assert math.degrees(b_stbd) == pytest.approx(135.0, abs=0.1)


def test_no_wind_no_layline() -> None:
    res = solve(_boat_at(180.0, 5.0, sog_kn=5.0), WindSolution(), TARGETS, ANCHOR)
    assert res.leg is None and res.layline is None
    assert res.helm["primary"] is None
    assert res.ttw_s == pytest.approx(3600.0, abs=1.0)


def test_current_shifts_decomposition() -> None:
    boat = _boat_at(180.0, 5.0)
    res = solve(boat, _wind(), TARGETS, ANCHOR, current_kn=(1.0, 0.0))
    assert res.layline["current"] is True
    a = res.layline["countdown_s"] / 3600
    assert a != pytest.approx(A_H, abs=0.01)


def test_decompose_parallel_is_none() -> None:
    assert decompose((1.0, 1.0), (1.0, 0.0), (2.0, 0.0)) is None


def test_select_primary_hysteresis() -> None:
    seq, prev = [], None
    for twa in (68, 73, 76, 112, 116):
        prev = select_primary(prev, twa)
        seq.append(prev)
    assert seq == ["twa_up", "twa_up", "cts", "cts", "twa_down"]
    assert select_primary("twa_down", 106) == "twa_down"
    assert select_primary("twa_down", 104) == "cts"
    assert select_primary("cts", 66) == "cts"
    assert select_primary("cts", 64) == "twa_up"
    assert select_primary(None, 150) == "twa_down"
