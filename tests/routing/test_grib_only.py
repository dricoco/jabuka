"""GPS + GRIB-only wind (plan 03-05 Task 3, WIND-05): with the Fastnet bus silent the wind source
becomes GRIB (TWD/TWS from the pack at the boat and GPS time, heading = COG, BSP = SOG) and the
laylines and the router keep working."""

from __future__ import annotations

import math

import pytest

from jabuka.nav import geo

ALERT_GRIB = "VENT GRIB (pas d'instruments)"


def _upwind_of_plic(rh) -> tuple[float, float]:
    """2 nm SW of Plić Sestre: in the NE wind the mark is dead upwind (a beat)."""
    return geo.offset(*rh.PLIC_SESTRE, math.radians(225.0), 2.0)


def _gps_only(core, pos, cog: float, sog: float, seconds: int) -> dict:
    for _ in range(seconds):
        core.feed_gps(*pos, cog, sog)
        core.tick(1.0)
        core.settle()
    core.feed_gps(*pos, cog, sog)
    return core.tick(0.0)


def test_silent_bus_gives_grib_wind_laylines_and_routes(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = _upwind_of_plic(rh)
    nav = _gps_only(core, pos, 0.0, 6.0, 3)  # COG 000 in NE 18: TWA +45 (starboard)
    w = nav["wind"]
    assert w["source"] == "GRIB"
    assert w["twd_t"] == pytest.approx(45.0, abs=0.1)
    assert w["tws_kn"] == pytest.approx(18.0, abs=0.1)
    assert w["twa"] == pytest.approx(45.0, abs=0.2)
    assert nav["boat"]["heading_src"] == "cog"
    assert nav["boat"]["hdg_t"] == pytest.approx(0.0, abs=0.1)
    assert ALERT_GRIB in nav["alerts"]
    assert "PAS DE VENT" not in nav["alerts"]
    assert nav["leg"] == "beat" and nav["layline"] is not None
    assert nav["helm"]["primary"] == "twa_up"
    assert nav["polar"]["pct"] is not None  # % polar from SOG
    assert nav["route"]["state"] == "ok" and nav["route"]["version"] >= 1
    assert fake_pool.requests[-1].base.tack0 == 1


def test_slow_boat_keeps_grib_wind_without_laylines(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = _upwind_of_plic(rh)
    nav = _gps_only(core, pos, 0.0, 0.5, 3)
    w = nav["wind"]
    assert w["source"] == "GRIB"
    assert w["twd_t"] == pytest.approx(45.0, abs=0.1) and w["tws_kn"] == pytest.approx(18.0)
    assert w["twa"] is None and w["heading_trusted"] is False
    assert nav["boat"]["heading_src"] is None
    assert nav["layline"] is None and nav["helm"]["primary"] is None


def test_grib_fallback_switch_off_gives_none(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    v = core.client.get("/api/settings").json()["version"]
    resp = core.client.put(
        "/api/settings", json={"base_version": v, "patch": {"grib_wind_fallback": False}}
    )
    assert resp.status_code == 200
    nav = _gps_only(core, _upwind_of_plic(rh), 0.0, 6.0, 2)
    assert nav["wind"]["source"] == "NONE"
    assert "PAS DE VENT" in nav["alerts"]
    assert ALERT_GRIB not in nav["alerts"]


def test_source_ranking_live_manual_grib(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = _upwind_of_plic(rh)
    assert _gps_only(core, pos, 0.0, 6.0, 1)["wind"]["source"] == "GRIB"
    # fresh instrument wind: LIVE again
    core.sail(*pos, 0.0, twd_deg=60.0, tws_kn=14.0)
    nav = core.tick(1.0)
    assert nav["wind"]["source"] == "LIVE"
    assert nav["wind"]["twd_t"] == pytest.approx(60.0, abs=0.2)
    # a manual entry outranks GRIB once the instruments are stale
    resp = core.client.post("/api/wind/manual", json={"twd": 90.0, "tws_kn": 10.0, "ref": "T"})
    assert resp.status_code == 200
    nav = _gps_only(core, pos, 0.0, 6.0, 12)  # stale (5 s) + live hold (5 s, WR-02)
    assert nav["wind"]["source"] == "MANUEL"
    assert core.client.delete("/api/wind/manual").status_code == 200
    nav = _gps_only(core, pos, 0.0, 6.0, 1)
    assert nav["wind"]["source"] == "GRIB"


def test_grib_outside_the_pack_is_none(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    nav = _gps_only(core, (45.5, 13.0), 0.0, 6.0, 1)  # far outside the wind grid
    assert nav["wind"]["source"] == "NONE"
