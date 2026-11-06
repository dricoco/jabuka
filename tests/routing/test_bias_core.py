"""GRIB bias in the live core (plan 03-05 Task 3, WIND-06): learned while sailing steadily,
applied to the router and to the GRIB-only wind, shown with its state, frozen in the Jabuka zone,
switched off in Réglages, fed by manual wind entries, persisted in bias.json."""

from __future__ import annotations

import json
import math

import pytest

from jabuka.common.clock import SimClock

HDG = 157.0  # port reach in the NE wind, outside the Jabuka zone


def _steady(core, pos, seconds: int, *, twd=55.0, tws=21.6, hdg=HDG) -> dict:
    """LIVE sailing with measured TWD = GRIB + 10 deg and TWS = 1.2 x GRIB (pack: NE 18 kn)."""
    for _ in range(seconds):
        core.sail(*pos, hdg, twd_deg=twd, tws_kn=tws)
        core.tick(1.0)
        core.settle()
    core.sail(*pos, hdg, twd_deg=twd, tws_kn=tws)
    return core.tick(0.0)


def _gps_only(core, pos, seconds: int, cog: float = HDG) -> dict:
    for _ in range(seconds):
        core.feed_gps(*pos, cog, 6.0)
        core.tick(1.0)
        core.settle()
    core.feed_gps(*pos, cog, 6.0)
    return core.tick(0.0)


def test_bias_is_learned_shown_and_applied(routing_core, fake_pool, rh, tmp_path) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    nav = _steady(core, pos, 60)
    b = nav["route"]["bias"]
    assert b["valid"] is False and b["state"] == "apprentissage"
    nav = _steady(core, pos, 300)
    b = nav["route"]["bias"]
    assert b["valid"] is True and b["state"] == "actif"
    assert b["dir_deg"] == pytest.approx(10.0, abs=0.2)
    assert b["ratio"] == pytest.approx(1.2, abs=0.01)
    assert b["text"] == "+10° ×1.20"
    # the bias trigger fired and the request carries the parameters
    assert any("bias" in r for _t, r in core.router.request_log)
    p = fake_pool.requests[-1].base.bias
    assert p is not None
    assert math.degrees(p.d_dir_rad) == pytest.approx(10.0, abs=0.2)
    assert p.k == pytest.approx(1.2, abs=0.01)
    diag = core.client.get("/api/state").json()
    rows = {r["path"]: r["value"] for r in diag["values"] if r["src"] == "nav"}
    assert rows["nav.bias.dir"] == pytest.approx(10.0, abs=0.2)
    assert rows["nav.bias.ratio"] == pytest.approx(1.2, abs=0.01)
    # the GRIB-only wind uses the same parameters (bus silent)
    nav = _gps_only(core, pos, 12)  # stale (5 s) + live hold (5 s, WR-02)
    assert nav["wind"]["source"] == "GRIB"
    assert nav["wind"]["twd_t"] == pytest.approx(55.0, abs=0.3)
    assert nav["wind"]["tws_kn"] == pytest.approx(21.6, abs=0.2)
    assert nav["route"]["bias"]["state"] == "s'estompe"
    # persisted
    saved = json.loads((tmp_path / "data" / "bias.json").read_text())
    assert saved["gated_s"] >= 300


def test_bias_frozen_in_the_jabuka_zone(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    near_jabuka = (43.10, 15.48)  # ~1 nm from the island: inside the 3 nm zone
    nav = _steady(core, near_jabuka, 30)
    assert nav["wind"]["in_zone"] is True
    b = nav["route"]["bias"]
    assert b["state"] == "gelé (Jabuka)"
    assert core.router.bias.status(core.router.now())["gated_s"] == 0.0


def test_no_learning_right_after_a_tack(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    _steady(core, pos, 40, hdg=HDG)  # port
    nav = _steady(core, pos, 40, hdg=293.0)  # starboard: tack confirmed after 30 s
    assert core.router.detector.last_tack_t is not None
    gated = core.router.bias.status(core.router.now())["gated_s"]
    nav = _steady(core, pos, 60, hdg=293.0)  # 1.5 min after the tack
    assert core.router.bias.status(core.router.now())["gated_s"] == gated
    assert nav["route"]["bias"]["reason"] == "virement récent"


def test_bias_switch_off_and_on(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    _steady(core, pos, 330)

    def put(patch):
        v = core.client.get("/api/settings").json()["version"]
        resp = core.client.put("/api/settings", json={"base_version": v, "patch": patch})
        assert resp.status_code == 200

    put({"bias_enabled": False})
    nav = _gps_only(core, pos, 12)  # stale (5 s) + live hold (5 s, WR-02)
    assert nav["route"]["bias"]["state"] == "désactivé"
    assert nav["route"]["bias"]["enabled"] is False
    assert nav["wind"]["twd_t"] == pytest.approx(45.0, abs=0.1)  # GRIB unbiased
    core.call(core.router.request, "timer", False)
    _gps_only(core, pos, 1)
    assert fake_pool.requests[-1].base.bias is None
    put({"bias_enabled": True})
    nav = _gps_only(core, pos, 60)  # the helm damping (10 s) follows the restored bias
    assert nav["route"]["bias"]["valid"] is True
    assert nav["wind"]["twd_t"] == pytest.approx(55.0, abs=0.5)


def test_manual_wind_entry_sets_the_bias(routing_core, fake_pool, rh, tmp_path) -> None:
    pack = rh.make_pack(tmp_path / "sw8", twd_deg=200.0, tws_kn=8.0)
    core = routing_core(racepack_dir=pack, pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    _gps_only(core, pos, 2, cog=0.0)
    n = len(core.router.request_log)
    resp = core.client.post("/api/wind/manual", json={"twd": 210.0, "tws_kn": 10.0, "ref": "T"})
    assert resp.status_code == 200
    nav = _gps_only(core, pos, 1, cog=0.0)
    b = nav["route"]["bias"]
    assert b["valid"] is True
    assert b["dir_deg"] == pytest.approx(10.0, abs=0.1)
    assert b["ratio"] == pytest.approx(1.25, abs=0.01)
    assert any("manual" in r for _t, r in list(core.router.request_log)[n:])


def test_bias_survives_a_restart(routing_core, fake_pool, rh) -> None:
    core = routing_core(pool_factory=lambda: fake_pool)
    pos = rh.boat_near_plic(2.0)
    nav = _steady(core, pos, 330)
    assert nav["route"]["bias"]["state"] == "actif"
    core.__exit__(None, None, None)
    t_later = core.clock.wall() + 60.0
    core2 = routing_core(pool_factory=lambda: type(fake_pool)(), clock=SimClock(start_utc=t_later))
    nav = _gps_only(core2, pos, 1)
    b = nav["route"]["bias"]
    assert b["valid"] is True and b["state"] == "s'estompe"
    assert b["dir_deg"] == pytest.approx(10.0, abs=0.3)
