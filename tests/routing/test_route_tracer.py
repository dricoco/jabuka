"""Tracer (plan 03-05 Task 1): the live core routes the boat to the remaining marks of Course A in
the real forkserver worker, and every nav message carries the route's advice (ROUT-02, ROUT-06).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import pytest

from jabuka.common.clock import SimClock

def _wrap360(a: float) -> float:
    return a % 360.0


def test_core_routes_course_a_and_every_nav_carries_the_advice(routing_core, rh) -> None:
    core = routing_core()
    lat, lon = rh.boat_near_plic(2.0)
    # NE 18 kn, boat on starboard (TWA +45: heading = TWD - TWA = 0 deg)
    with core.client.websocket_connect("/ws") as ws:
        core.sail(lat, lon, 0.0)
        nav = core.tick(1.0)
        assert nav["route"]["state"] in ("computing", "ok")
        assert core.router.health()["jobs_submitted"] == 1
        seen_route_msgs: list[dict] = []

        def drain() -> dict:
            """Read until this tick's nav message (diag, [route], nav)."""
            while True:
                m = ws.receive_json()
                if m["type"] == "route":
                    seen_route_msgs.append(m)
                if m["type"] == "nav" and m["t_mono"] >= core.clock.monotonic() - 1e-9:
                    return m

        drain()
        ws_nav = None
        for _ in range(1200):
            core.sail(lat, lon, 0.0)
            nav = core.tick(0.0)
            ws_nav = drain()
            if nav["route"]["version"] >= 1:
                break
            time.sleep(0.05)
        assert nav["route"]["version"] == 1, nav["route"]
        # two more ticks: no second route message for the same version
        for _ in range(2):
            core.sail(lat, lon, 0.0)
            core.tick(1.0)
            ws_nav = drain()
    r = nav["route"]
    assert r["state"] == "ok" and r["reason"] is None
    assert r["kind"] == "optimal"
    assert r["target_twa"] is not None and r["target_tack"] in ("stbd", "port")
    assert (r["target_twa"] > 0) == (r["target_tack"] == "stbd")
    twd = nav["wind"]["twd_t"]
    assert r["target_hdg_t"] == pytest.approx(_wrap360(twd - r["target_twa"]), abs=0.15)
    assert r["countdown_s"] is None or r["countdown_s"] > 0
    assert r["age_s"] is not None and 0 <= r["age_s"] <= 2
    assert r["eta_utc"] and r["eta_utc"].endswith("Z")
    assert r["computed_utc"].endswith("Z")
    assert r["level"] == "L0"
    assert r["primary"] in ("twa", "hdg")
    assert r["health"]["jobs"] >= 1 and r["health"]["ok"] >= 1
    assert r["pack"]["ok"] is True
    assert ws_nav is not None and ws_nav["route"]["version"] == 1
    assert len(seen_route_msgs) == 1 and seen_route_msgs[0]["version"] == 1
    json.dumps(nav, allow_nan=False)

    api = core.client.get("/api/route")
    assert api.status_code == 200
    msg = api.json()
    assert msg["type"] == "route" and msg["v"] == 1 and msg["version"] == 1
    assert msg["kind"] == "optimal" and msg["legs"] and msg["legs"][0]["mark_id"] == "plic-sestre"
    lines = [f for f in msg["geojson"]["features"] if f["geometry"]["type"] == "LineString"]
    assert len(lines) == 1
    assert lines[0]["properties"]["version"] == 1
    assert len(lines[0]["geometry"]["coordinates"]) <= 300
    # the derived countdown goes to the state store (Diag)
    diag = core.client.get("/api/state").json()
    rows = {row["path"] for row in diag["values"] if row["src"] == "nav"}
    assert "nav.route.countdown" in rows
    assert "router" in diag["health"]


def test_clock_not_valid_blocks_routing_and_keeps_phase2(routing_core, rh) -> None:
    core = routing_core(clock=SimClock())  # no UTC observed
    lat, lon = rh.boat_near_plic(2.0)
    core.sail(lat, lon, 0.0)
    nav = core.tick(1.0)
    r = nav["route"]
    assert r["state"] == "blocked_clock"
    assert r["reason"] == "heure GPS non valide"
    assert core.router.health()["jobs_submitted"] == 0
    # Phase 2 fields are unchanged
    assert nav["wind"]["source"] == "LIVE"
    assert nav["mark"]["name"] == "Plić Sestre"
    assert nav["layline"] is not None


def test_pack_without_wind_reports_no_pack(routing_core, rh, tmp_path: Path) -> None:
    pack = rh.make_pack(tmp_path / "nowind", wind=False)
    core = routing_core(racepack_dir=pack)
    lat, lon = rh.boat_near_plic(2.0)
    core.sail(lat, lon, 0.0)
    nav = core.tick(1.0)
    r = nav["route"]
    assert r["state"] == "no_pack"
    assert "wind.npz absent" in r["reason"]
    assert r["pack"]["ok"] is False
    assert core.router.health()["jobs_submitted"] == 0
    assert nav["wind"]["source"] == "LIVE" and nav["layline"] is not None
    assert core.client.get("/api/route").status_code == 404
    assert core.client.get("/api/route").json()["state"] == "no_pack"


def test_router_exception_is_counted_and_nav_still_published(routing_core, rh) -> None:
    core = routing_core()

    def boom(msg):
        raise RuntimeError("boom")

    core.router._tick = boom  # type: ignore[method-assign]
    lat, lon = rh.boat_near_plic(2.0)
    core.sail(lat, lon, 0.0)
    nav = core.tick(1.0)
    assert nav["route"]["state"] == "failed"
    assert nav["wind"]["source"] == "LIVE"
    assert core.ctx.stats["router_errors"] >= 1
    assert core.client.get("/api/state").json()["core"]["router_errors"] >= 1
    assert math.isfinite(nav["t_mono"])


def test_utc_start_constant_is_inside_the_wind(rh) -> None:
    assert rh.T_WIND0 < rh.T_START < rh.T_WIND0 + 72 * 3600
