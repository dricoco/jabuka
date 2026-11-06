"""Tracer: synthetic live wind + GPS -> StateStore -> NavService -> WebSocket nav message.

In-process core (build_context, --clock sim, TestClient); inputs from the sim.synth helpers through
ctx.on_message / ctx.on_gps_object; SimClock.advance drives the 1 Hz tick.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import SimClock
from jabuka.core.main import build_arg_parser, build_context
from jabuka.core.web import create_app
from jabuka.nav import geo
from jabuka.sim.synth import SynthBoat, SynthConfig, gps_objects, udp_values

PLIC_SESTRE = (43.684627, 15.811626)
START_UTC = 1_794_600_000.0  # 2026-11-13
SHAPE_FIXTURE = Path(__file__).parent.parent / "fixtures" / "nav" / "tracer_nav.json"


def _start() -> tuple[float, float]:
    return geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)


def _feed(ctx, boat: SynthBoat) -> None:
    s = boat.state
    ctx.on_message({"src": "fastnet", "values": udp_values(s)})
    tpv, sky = gps_objects(s, START_UTC + s.t)
    ctx.on_gps_object(tpv)
    ctx.on_gps_object(sky)


def run_tracer(data_dir: Path, udp_port: int, seconds: int = 3) -> tuple[dict, dict]:
    """Returns (last nav message received on /ws, GET /api/nav)."""
    args = build_arg_parser().parse_args(
        ["--clock", "sim", "--data-dir", str(data_dir), "--udp-port", str(udp_port)]
    )
    ctx = build_context(args)
    clock = ctx.clock
    assert isinstance(clock, SimClock)
    boat = SynthBoat(SynthConfig(twd=161.0, tws=12.0, twa=45.0, start=_start()))
    with TestClient(create_app(ctx)) as client, client.websocket_connect("/ws") as ws:
        _feed(ctx, boat)
        last: dict | None = None
        for _ in range(seconds):
            boat.step(1.0)
            clock.advance(1.0)
            _feed(ctx, boat)
            # one diag + one nav per tick
            for _ in range(8):
                msg = ws.receive_json()
                if msg["type"] == "nav" and msg["t_mono"] >= clock.monotonic() - 1e-9:
                    last = msg
                    break
        assert last is not None, "no nav message after the ticks"
        api = client.get("/api/nav").json()
    return last, api


def _shape(obj):
    if isinstance(obj, dict):
        return {k: _shape(v) for k, v in obj.items() if k != "geojson"}
    return None


def test_live_wind_reaches_the_helm(tmp_path: Path, free_udp_port: int) -> None:
    nav, api = run_tracer(tmp_path / "data", free_udp_port)
    assert nav["type"] == "nav" and nav["v"] == 1
    assert nav["wind"]["source"] == "LIVE"
    assert nav["wind"]["twd_t"] == pytest.approx(161.0, abs=0.5)
    assert nav["wind"]["tws_kn"] == pytest.approx(12.0, abs=0.2)
    assert nav["wind"]["twa"] == pytest.approx(45.0, abs=0.5)
    assert nav["polar"]["up"]["twa"] == pytest.approx(37.7, abs=0.6)
    assert nav["polar"]["up"]["bsp_kn"] == pytest.approx(6.50 * 0.92, abs=0.05)
    assert nav["polar"]["eff"] == 0.92
    assert nav["polar"]["pct"] is not None and nav["polar"]["pct"] > 0
    assert nav["mark"]["name"] == "Plić Sestre"
    assert nav["mark"]["side"] == "stbd"
    assert nav["leg"] == "beat"
    lay = nav["layline"]
    assert lay["state"] == "normal"
    assert 0 < lay["countdown_s"] < nav["mark"]["ttw_s"]
    assert len(lay["geojson"]["features"]) == 2
    assert lay["other_tack_hdg_t"] == pytest.approx(161.0 + 37.7, abs=1.0)
    assert nav["helm"]["primary"] == "twa_up"
    assert nav["helm"]["deviation"] == pytest.approx(45.0 - nav["helm"]["target"], abs=0.6)
    assert nav["display"] == {"heading_ref": "M", "variation": 4.7}
    assert nav["boat"]["heading_src"] == "compass"
    assert nav["course"]["template"] == "A"
    assert nav["course_version"] == 0 and nav["settings_version"] == 0
    assert "PAS DE VENT" not in nav["alerts"]
    # strict JSON: no NaN anywhere
    json.dumps(nav, allow_nan=False)
    assert api["type"] == "nav" and api["wind"]["source"] == "LIVE"
    # the committed helm_logic fixture has exactly this message shape (no silent drift)
    assert _shape(json.loads(SHAPE_FIXTURE.read_text())) == _shape(nav)


def test_nav_rows_in_diag_and_no_wind_message(tmp_path: Path, free_udp_port: int) -> None:
    args = build_arg_parser().parse_args(
        ["--clock", "sim", "--data-dir", str(tmp_path), "--udp-port", str(free_udp_port)]
    )
    ctx = build_context(args)
    with TestClient(create_app(ctx)) as client:
        ctx.tick_once()
        nav = client.get("/api/nav").json()
        assert nav["wind"]["source"] == "NONE"
        assert "PAS DE VENT" in nav["alerts"]
        assert nav["layline"] is None and nav["helm"]["primary"] is None
        diag = client.get("/api/state").json()
        rows = {r["path"]: r for r in diag["values"] if r["src"] == "nav"}
        assert rows["nav.wind.source"]["value"] == "NONE"
        assert diag["core"]["nav_errors"] == 0


def test_nav_failure_never_crashes_the_tick(tmp_path: Path, free_udp_port: int) -> None:
    args = build_arg_parser().parse_args(
        ["--clock", "sim", "--data-dir", str(tmp_path), "--udp-port", str(free_udp_port)]
    )
    ctx = build_context(args)

    def boom(*a, **k):
        raise RuntimeError("boom")

    ctx.nav.wind.update = boom
    ctx.tick_once()
    assert ctx.stats["nav_errors"] == 1
    assert "Erreur de calcul nav" in ctx.nav.last["alerts"]
    assert ctx.diag_message()["core"]["nav_errors"] == 1
