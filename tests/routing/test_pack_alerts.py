"""Race pack on the Pi (plan 03-05 Task 2, GRIB-02 runtime): coverage alerts in the nav message
and on Diag, coverage re-run on a course change, the shipped marks file, and the routing settings
(French labels, bounds)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from jabuka.route.racepack import read_marks_file

SHIPPED_MARKS = (
    Path(__file__).resolve().parents[2] / "src" / "jabuka" / "nav" / "data" / "marks.json"
)


def _tick(core, rh) -> dict:
    core.sail(*rh.boat_near_plic(2.0), 157.0)
    return core.tick(1.0)


def test_short_wind_yields_meteo_incomplete(routing_core, rh, fake_pool, tmp_path) -> None:
    # wind from 13 Nov 00:00Z for 42 h: ends 14 Nov 18:00Z, before the window end (15 Nov 09:00Z)
    pack = rh.make_pack(tmp_path / "short", hours=42)
    core = routing_core(racepack_dir=pack, pool_factory=lambda: fake_pool)
    nav = _tick(core, rh)
    alerts = [a for a in nav["alerts"] if a.startswith("MÉTÉO INCOMPLÈTE")]
    assert alerts, nav["alerts"]
    assert any("14/11 19:00" in a for a in alerts)  # local time of the last wind step
    assert nav["route"]["pack"]["alerts"] == alerts
    health = core.client.get("/api/state").json()["health"]["router"]
    assert health["coverage"]["alerts"] == alerts
    assert len(nav["alerts"]) == len(set(nav["alerts"]))  # deduplicated


def test_course_b_reruns_coverage_with_mulo(routing_core, rh, fake_pool, tmp_path) -> None:
    # 0.1 deg grid ending at 16.0 E: the interpolation margin stops at 15.9 E, so Mulo (15.92 E,
    # Course B only) is outside while every Course A mark is inside
    lon = np.round(np.arange(14.9, 16.05, 0.1), 6)
    pack = rh.make_pack(tmp_path / "narrow", lon=lon)
    core = routing_core(racepack_dir=pack, pool_factory=lambda: fake_pool)
    nav = _tick(core, rh)
    assert not [a for a in nav["alerts"] if a.startswith("MÉTÉO INCOMPLÈTE")], nav["alerts"]
    resp = core.client.post("/api/course/select", json={"template": "B"})
    assert resp.status_code == 200, resp.text
    nav = _tick(core, rh)
    alerts = [a for a in nav["alerts"] if a.startswith("MÉTÉO INCOMPLÈTE")]
    assert any("Mulo" in a for a in alerts), nav["alerts"]


def test_shipped_marks_file_parses() -> None:
    doc = read_marks_file(SHIPPED_MARKS)
    assert {"A", "B"} <= set(doc.templates)
    assert "mulo" in doc.marks and "jabuka" in doc.marks


def test_routing_settings_schema_and_bounds(routing_core, fake_pool) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    props = core.client.get("/api/settings/schema").json()["properties"]
    expected = {
        "routing_enabled": "Routage actif",
        "route_level": "Niveau de routage (banc Pi)",
        "route_cadence_min": "Recalcul toutes les (min)",
        "tack_penalty_s": "Pénalité de virement (s)",
        "stay_extra_min": "On reste : marge (min)",
        "route_waves": "Vagues dans le routage",
        "route_current": "Courant dans le routage",
        "grib_wind_fallback": "Vent GRIB sans instruments",
        "bias_enabled": "Correction du GRIB (biais)",
        "bias_tau_decay_h": "Biais : décroissance (h)",
        "race_start_local": "Fenêtre météo : début",
        "race_end_local": "Fenêtre météo : fin",
    }
    for key, label in expected.items():
        assert props[key]["label"] == label, key
    settings = core.client.get("/api/settings").json()
    s = settings["settings"]
    assert s["route_level"] == "L0" and s["route_cadence_min"] == 5
    assert s["race_start_local"] == "2026-11-13T18:00"
    assert s["race_end_local"] == "2026-11-15T10:00"
    v = settings["version"]
    for patch in (
        {"route_cadence_min": 1},
        {"route_level": "L7"},
        {"race_end_local": "demain"},
        {"race_start_local": "2026-11-13 18h"},
        {"tack_penalty_s": 200},
        {"bias_tau_decay_h": 0.1},
    ):
        resp = core.client.put("/api/settings", json={"base_version": v, "patch": patch})
        assert resp.status_code == 422, patch
    resp = core.client.put(
        "/api/settings", json={"base_version": v, "patch": {"route_cadence_min": 10}}
    )
    assert resp.status_code == 200


def test_routing_disabled_in_settings(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    v = core.client.get("/api/settings").json()["version"]
    core.client.put("/api/settings", json={"base_version": v, "patch": {"routing_enabled": False}})
    nav = _tick(core, rh)
    assert nav["route"]["state"] == "disabled"
    assert fake_pool.requests == []
