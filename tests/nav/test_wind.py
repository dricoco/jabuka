"""True wind the helm can trust (WIND-03/07): the TRUE boundary, vector damping without wrap
glitches, instrument (Hercules) fallback and cross-check, leeway, and the Jabuka magnetic zone.

Pure inputs: StateStore.latest()-shaped rows, no core."""

from __future__ import annotations

import math

import pytest

from jabuka.common.clock import SimClock
from jabuka.common.conventions import apparent_from_true, true_wind_from_apparent
from jabuka.common.units import kn_to_ms, ms_to_kn, wrap_2pi, wrap_pi
from jabuka.core.nav_service import NavService
from jabuka.core.state import StateStore
from jabuka.nav import geo
from jabuka.nav import wind as W
from jabuka.nav.settings import ManualWind, Settings
from jabuka.nav.wind import VectorEma, WindPipeline, heading_true

R = math.radians
D = math.degrees
ZONE = (43.09153, 15.46054)
FAR = (43.70, 15.80)  # Šibenik approach, far from the zone


def row(value, ref=None) -> dict:
    return {"value": value, "ref": ref}


def pos_row(lat: float, lon: float) -> dict:
    return {"value": {"latitude": lat, "longitude": lon}}


def computed_inputs(
    twd_deg: float = 161.0,
    tws_kn: float = 12.0,
    hdg_deg: float = 116.0,
    bsp_kn: float = 6.0,
    hdg_ref: str = "T",
    pos: tuple[float, float] = FAR,
) -> dict:
    """AWA/AWS/BSP/heading for a given true wind and TRUE heading (heading row in hdg_ref)."""
    hdg = R(hdg_deg)
    aw = apparent_from_true(R(twd_deg), kn_to_ms(tws_kn), kn_to_ms(bsp_kn), hdg)
    return {
        W.AWA: row(aw.awa),
        W.AWS: row(aw.aws),
        W.BSP: row(kn_to_ms(bsp_kn)),
        W.HEADING: row(hdg, hdg_ref),
        W.POSITION: pos_row(*pos),
    }


def instrument_rows(twa_deg: float, tws_kn: float, twd_deg: float | None = None, ref="T") -> dict:
    out = {W.TWA_INSTR: row(R(twa_deg)), W.TWS_INSTR: row(kn_to_ms(tws_kn))}
    if twd_deg is not None:
        out[W.TWD_INSTR] = row(R(twd_deg), ref)
    return out


# -- TRUE boundary --------------------------------------------------------------------------------
def test_heading_true_boundary() -> None:
    s = Settings(variation_deg=4.7, heading_offset_deg=2.0)
    assert D(heading_true(R(100.0), "M", s)) == pytest.approx(106.7)
    assert D(heading_true(R(100.0), "?", s)) == pytest.approx(106.7)  # A9: unknown -> M
    assert D(heading_true(R(100.0), None, s)) == pytest.approx(106.7)
    assert D(heading_true(R(100.0), "T", s)) == pytest.approx(102.0)  # offset only
    s_t = Settings(variation_deg=4.7, heading_offset_deg=2.0, heading_ref_unknown="T")
    assert D(heading_true(R(100.0), "?", s_t)) == pytest.approx(102.0)
    assert D(heading_true(R(358.0), "M", s)) == pytest.approx(4.7)  # wraps


def test_magnetic_heading_gives_true_wind() -> None:
    p = WindPipeline(Settings(variation_deg=4.7))
    mag = wrap_2pi(R(116.0 - 4.7))
    inp = computed_inputs(hdg_deg=116.0)
    inp[W.HEADING] = row(mag, "M")
    sol = p.update(inp, 0.0)
    assert sol.source == "LIVE"
    assert D(sol.twd) == pytest.approx(161.0, abs=0.01)
    assert D(sol.hdg) == pytest.approx(116.0, abs=0.01)


# -- VectorEma ------------------------------------------------------------------------------------
def test_vector_ema_wrap_safe() -> None:
    f = VectorEma(10.0)
    out = None
    for k in range(60):
        out = f.update(R(359.0 if k % 2 else 1.0), 1.0, float(k))
    deg = D(out)
    assert min(deg, 360.0 - deg) < 1.5  # near 0, never near 180


def test_vector_ema_step_response() -> None:
    tau = 10.0
    f = VectorEma(tau)
    f.update(0.0, 1.0, 0.0)
    out = 0.0
    for k in range(1, int(tau) + 1):
        out = f.update(R(90.0), 1.0, float(k))
    assert D(out) / 90.0 == pytest.approx(0.632, abs=0.05)


def test_vector_ema_clock_backwards_resets() -> None:
    f = VectorEma(10.0)
    f.update(0.0, 1.0, 100.0)
    f.update(R(90.0), 1.0, 101.0)
    assert D(f.update(R(200.0), 1.0, 50.0)) == pytest.approx(200.0)  # reset, no raise
    # the same instant twice is a no-op (an API push between ticks must not reset the filter)
    assert D(f.update(R(10.0), 1.0, 50.0)) == pytest.approx(200.0)


# -- damping in the pipeline ----------------------------------------------------------------------
def test_damping_helm_and_layline_taus() -> None:
    p = WindPipeline(Settings(tau_helm_s=10.0, tau_layline_s=60.0))
    p.update(computed_inputs(twd_deg=160.0), 0.0)
    sol = None
    for k in range(1, 11):
        sol = p.update(computed_inputs(twd_deg=180.0), float(k))
    # 10 s after a 20 deg shift: the helm filter is ~63 % there, the layline one ~15 %
    assert D(sol.twd) == pytest.approx(160.0 + 20.0 * 0.632, abs=1.0)
    assert D(sol.twd_lay) == pytest.approx(160.0 + 20.0 * (1 - math.exp(-10 / 60)), abs=1.0)
    # TWA in the message = helm-damped TWD - current heading
    assert D(sol.twa) == pytest.approx(D(sol.twd) - 116.0, abs=0.01)


def test_tws_scalar_ema() -> None:
    p = WindPipeline(Settings(tau_helm_s=10.0))
    p.update(computed_inputs(tws_kn=10.0), 0.0)
    sol = None
    for k in range(1, 11):
        sol = p.update(computed_inputs(tws_kn=20.0), float(k))
    assert ms_to_kn(sol.tws) == pytest.approx(10.0 + 10.0 * 0.632, abs=0.3)


def test_source_change_resets_filters() -> None:
    p = WindPipeline(Settings())
    for k in range(30):
        p.update(computed_inputs(twd_deg=161.0), float(k))
    manual = ManualWind(
        twd_t_deg=250.0, tws_kn=8.0, ref_entered="T", twd_entered=250.0, t_set_wall=0.0
    )
    # the live wind is held LIVE_HOLD_S (5 s) after its last sample (WR-02), then MANUEL
    sol = p.update({W.POSITION: pos_row(*FAR)}, 34.0, manual=manual, t_wall=10.0)
    assert sol.source == "LIVE" and D(sol.twd_lay) == pytest.approx(161.0, abs=0.01)
    sol = p.update({W.POSITION: pos_row(*FAR)}, 35.0, manual=manual, t_wall=10.0)
    assert sol.source == "MANUEL"
    assert D(sol.twd) == pytest.approx(250.0)
    assert D(sol.twd_lay) == pytest.approx(250.0)
    assert ms_to_kn(sol.tws) == pytest.approx(8.0)
    # and back to LIVE at once
    sol = p.update(computed_inputs(twd_deg=161.0), 36.0, manual=manual, t_wall=11.0)
    assert sol.source == "LIVE" and D(sol.twd_lay) == pytest.approx(161.0, abs=0.01)


def test_live_live_bg_flapping_keeps_the_layline_filter() -> None:
    """WR-02: BSP missing every other tick flips LIVE <-> LIVE_BG; both measure the same wind,
    so the 60 s layline filter is not re-seeded with a raw sample at each flip."""
    p = WindPipeline(Settings(tau_layline_s=60.0))
    for k in range(30):
        p.update(computed_inputs(twd_deg=160.0) | instrument_rows(44.0, 12.0, 160.0), float(k))
    sources = set()
    sol = None
    for k in range(30, 40):
        inp = computed_inputs(twd_deg=180.0) | instrument_rows(64.0, 12.0, 180.0)
        if k % 2:
            del inp[W.BSP]  # computed wind unavailable this tick: LIVE_BG
        sol = p.update(inp, float(k))
        sources.add(sol.source)
    assert sources == {"LIVE", "LIVE_BG"}
    # 10 s after a 20 deg shift the 60 s filter has moved ~15 %, not jumped to 180
    assert D(sol.twd_lay) == pytest.approx(160.0 + 20.0 * (1 - math.exp(-10 / 60)), abs=1.0)


def test_brief_live_dropout_is_held_not_reset() -> None:
    """WR-02: every live input missing for a couple of seconds keeps the live source and its
    filtered values (no MANUEL flip and no filter reset)."""
    p = WindPipeline(Settings(tau_layline_s=60.0))
    manual = ManualWind(
        twd_t_deg=250.0, tws_kn=8.0, ref_entered="T", twd_entered=250.0, t_set_wall=0.0
    )
    for k in range(30):
        p.update(computed_inputs(twd_deg=160.0), float(k), manual=manual, t_wall=0.0)
    lay = p.last.twd_lay
    for k in (30, 31, 32):
        sol = p.update({W.POSITION: pos_row(*FAR)}, float(k), manual=manual, t_wall=0.0)
        assert sol.source == "LIVE" and sol.twd_lay == lay and sol.alerts == []
    sol = p.update(computed_inputs(twd_deg=200.0), 33.0, manual=manual, t_wall=0.0)
    assert sol.source == "LIVE"
    assert D(sol.twd_lay) == pytest.approx(160.0 + 40.0 * (1 - math.exp(-4 / 60)), abs=1.0)


# -- sources --------------------------------------------------------------------------------------
def test_source_live_when_computed_inputs_fresh() -> None:
    inp = computed_inputs() | instrument_rows(45.0, 12.0, 161.0)
    sol = WindPipeline(Settings()).update(inp, 0.0)
    assert sol.source == "LIVE"
    assert D(sol.twd) == pytest.approx(161.0, abs=0.01)
    assert D(sol.twa) == pytest.approx(45.0, abs=0.01)


def test_source_live_bg_from_instrument_angle_only() -> None:
    inp = {
        W.HEADING: row(R(116.0), "T"),
        W.POSITION: pos_row(*FAR),
    } | instrument_rows(45.0, 12.0)
    sol = WindPipeline(Settings()).update(inp, 0.0)
    assert sol.source == "LIVE_BG"
    assert D(sol.twd) == pytest.approx(161.0, abs=0.01)
    assert ms_to_kn(sol.tws) == pytest.approx(12.0)


def test_source_live_bg_from_instrument_direction_magnetic() -> None:
    s = Settings(variation_deg=4.7)
    inp = {W.POSITION: pos_row(*FAR)} | instrument_rows(45.0, 12.0, 156.3, ref="M")
    sol = WindPipeline(s).update(inp, 0.0)
    assert sol.source == "LIVE_BG"
    assert D(sol.twd) == pytest.approx(161.0, abs=0.01)


def test_true_wind_source_instrument_prefers_hercules() -> None:
    inp = computed_inputs(twd_deg=161.0) | instrument_rows(40.0, 11.0, 170.0)
    sol = WindPipeline(Settings(true_wind_source="instrument")).update(inp, 0.0)
    assert sol.source == "LIVE_BG"
    assert D(sol.twd) == pytest.approx(170.0, abs=0.01)
    assert ms_to_kn(sol.tws) == pytest.approx(11.0)
    # computed by default
    sol = WindPipeline(Settings()).update(inp, 0.0)
    assert sol.source == "LIVE" and D(sol.twd) == pytest.approx(161.0, abs=0.01)


def test_manual_without_compass_uses_cog_for_twa() -> None:
    manual = ManualWind(
        twd_t_deg=200.0, tws_kn=12.0, ref_entered="T", twd_entered=200.0, t_set_wall=0.0
    )
    inp = {
        W.POSITION: pos_row(*FAR),
        W.COG: row(R(150.0), "T"),
        W.SOG: row(kn_to_ms(6.0)),
    }
    sol = WindPipeline(Settings()).update(inp, 0.0, manual=manual, t_wall=0.0)
    assert sol.source == "MANUEL"
    assert D(sol.twa) == pytest.approx(50.0, abs=0.01)
    assert sol.heading_src == "cog"


# -- cross-check ----------------------------------------------------------------------------------
def _run_check(seconds: int) -> tuple[W.WindSolution, list[str]]:
    p = WindPipeline(Settings())
    sol = None
    for k in range(seconds + 1):
        # computed TWA 45, Hercules says 33: 12 deg apart
        inp = computed_inputs(twd_deg=161.0) | instrument_rows(33.0, 11.0)
        sol = p.update(inp, float(k))
    return sol, sol.alerts


def test_cross_check_alert_after_60_s() -> None:
    sol, alerts = _run_check(59)
    assert sol.check["dtwa"] == pytest.approx(12.0, abs=0.1)
    assert sol.check["dtws_kn"] == pytest.approx(1.0, abs=0.1)
    assert sol.check["alert"] is False
    assert "Écart TWA calculé/B&G > 10°" not in alerts
    sol, alerts = _run_check(61)
    assert sol.check["alert"] is True
    assert "Écart TWA calculé/B&G > 10°" in alerts


def test_cross_check_absent_without_instrument() -> None:
    sol = WindPipeline(Settings()).update(computed_inputs(), 0.0)
    assert sol.check is None


def test_cross_check_rows_reach_diag(tmp_path) -> None:
    clock = SimClock()
    state = StateStore(clock)
    nav = NavService(state, clock, tmp_path)
    inp = computed_inputs(twd_deg=161.0) | instrument_rows(33.0, 11.0)
    values = [
        {"path": p, "value": r["value"], "ref": r.get("ref")}
        for p, r in inp.items()
        if p != W.POSITION
    ]
    values.append({"path": W.POSITION, "value": inp[W.POSITION]["value"]})
    state.update_values("fastnet", values, clock.monotonic())
    msg = nav.update()
    assert msg["wind"]["check"]["dtwa"] == pytest.approx(12.0, abs=0.1)
    rows = {r["path"]: r for r in state.rows() if r["src"] == "nav"}
    assert rows["nav.wind.dtwa"]["value"] == pytest.approx(12.0, abs=0.1)
    assert rows["nav.wind.dtws"]["value"] == pytest.approx(1.0, abs=0.1)
    assert rows["nav.heading.src"]["value"] == "compass"
    assert rows["nav.heading.true"]["value"] == pytest.approx(R(116.0))
    assert rows["nav.wind.inZone"]["value"] is False


# -- leeway ---------------------------------------------------------------------------------------
def test_leeway_rotates_the_water_track_to_leeward() -> None:
    inp = computed_inputs(twd_deg=161.0, hdg_deg=116.0)  # wind on starboard
    awa, aws, bsp = inp[W.AWA]["value"], inp[W.AWS]["value"], inp[W.BSP]["value"]
    hdg = R(116.0)
    no_lw = WindPipeline(Settings()).update(inp, 0.0)
    sol = WindPipeline(Settings(leeway_deg=5.0)).update(inp, 0.0)
    lam = R(5.0)
    expect = true_wind_from_apparent(awa + lam, aws, bsp, hdg - lam)
    assert sol.twd == pytest.approx(expect.twd, abs=1e-9)
    assert sol.tws == pytest.approx(expect.tws, abs=1e-9)
    assert D(sol.twd) != pytest.approx(D(no_lw.twd), abs=0.5)  # TWD changes
    assert sol.twa == pytest.approx(wrap_pi(expect.twd - hdg), abs=1e-9)  # TWA to the bow


def test_leeway_on_port_rotates_the_other_way() -> None:
    inp = computed_inputs(twd_deg=161.0, hdg_deg=206.0)  # TWA -45: port
    awa, aws, bsp = inp[W.AWA]["value"], inp[W.AWS]["value"], inp[W.BSP]["value"]
    assert awa < 0
    sol = WindPipeline(Settings(leeway_deg=5.0)).update(inp, 0.0)
    expect = true_wind_from_apparent(awa - R(5.0), aws, bsp, R(206.0) + R(5.0))
    assert sol.twd == pytest.approx(expect.twd, abs=1e-9)


# -- Jabuka zone ----------------------------------------------------------------------------------
def _zone_inputs(dist_nm: float) -> dict:
    lat, lon = geo.offset(*ZONE, R(90.0), dist_nm)
    inp = computed_inputs(twd_deg=161.0, hdg_deg=116.0, pos=(lat, lon))
    inp[W.COG] = row(R(110.0), "T")
    inp[W.SOG] = row(kn_to_ms(6.0))
    # Hercules direction (compass-derived): wildly off inside the anomaly
    inp |= instrument_rows(45.0, 12.0, 120.0)
    return inp


def test_jabuka_zone_uses_cog() -> None:
    p = WindPipeline(Settings(zone_radius_nm=3.0, true_wind_source="instrument"))
    sol = p.update(_zone_inputs(2.0), 0.0)
    assert sol.in_zone is True
    assert sol.heading_trusted is False
    assert sol.heading_src == "cog"
    assert D(sol.hdg) == pytest.approx(110.0)
    assert "CAP NON FIABLE (zone Jabuka)" in sol.alerts
    # the Hercules direction (120) is ignored: instrument TWD = COG + instrument TWA
    assert sol.source == "LIVE_BG"
    assert D(sol.twd) == pytest.approx(155.0, abs=0.01)

    sol = WindPipeline(Settings(zone_radius_nm=3.0)).update(_zone_inputs(2.0), 0.0)
    assert sol.source == "LIVE"  # computed with COG as the heading
    awa = _zone_inputs(2.0)[W.AWA]["value"]
    aws = _zone_inputs(2.0)[W.AWS]["value"]
    expect = true_wind_from_apparent(awa, aws, kn_to_ms(6.0), R(110.0))
    assert sol.twd == pytest.approx(expect.twd, abs=1e-9)


def test_outside_zone_trusts_the_compass_again() -> None:
    sol = WindPipeline(Settings(zone_radius_nm=3.0)).update(_zone_inputs(3.2), 0.0)
    assert sol.in_zone is False
    assert sol.heading_trusted is True
    assert sol.heading_src == "compass"
    assert D(sol.hdg) == pytest.approx(116.0)
    assert "CAP NON FIABLE (zone Jabuka)" not in sol.alerts


def test_zone_slow_boat_has_no_trusted_heading() -> None:
    inp = _zone_inputs(2.0)
    inp[W.SOG] = row(kn_to_ms(0.8))
    inp.pop(W.TWD_INSTR)
    inp.pop(W.TWA_INSTR)
    sol = WindPipeline(Settings(zone_radius_nm=3.0)).update(inp, 0.0)
    assert sol.in_zone is True and sol.hdg is None and sol.heading_src is None
    assert sol.source == "NONE"  # computed wind needs a trusted heading
