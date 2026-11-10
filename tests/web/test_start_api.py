"""Start mode REST (quick 261110-cuk, core/start_api.py): open/close, ping and typed line ends,
the 5:00 timer (start / SYNC / STOP), one events-log line per change, persistence across a core
restart, and isolation of the nav message (closed: no "start" key; a start failure never touches
the other blocks nor the tick).

In-process core on a SimClock (no lifespan, so no background tick), like test_manual_wind.py.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import SimClock
from jabuka.common.units import kn_to_ms
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
from jabuka.nav import geo
from jabuka.nav.polar import efficiency_for
from jabuka.sim.synth import SynthBoat, SynthConfig, udp_values

START_UTC = 1_794_600_000.0  # 2026-11-13
BOAT = (43.7161, 15.7967)


def _make(data_dir: Path, port: int, start_utc: float = START_UTC):
    ctx = CoreContext.create(SimClock(start_utc=start_utc), data_dir, udp_port=port)
    return ctx, TestClient(create_app(ctx))


def _feed_gps(ctx, lat: float, lon: float, cog_deg: float = 0.0, sog_kn: float = 6.0) -> None:
    values = [
        {
            "path": "navigation.position",
            "value": {"latitude": lat, "longitude": lon},
            "unit": "deg",
        },
        {
            "path": "navigation.courseOverGroundTrue",
            "value": math.radians(cog_deg),
            "unit": "rad",
            "ref": "T",
        },
        {"path": "navigation.speedOverGround", "value": kn_to_ms(sog_kn), "unit": "m/s"},
    ]
    ctx.on_message({"src": "sim-gps", "values": values})


def _events(data_dir: Path) -> list[dict]:
    out = []
    for f in sorted((data_dir / "logs" / "events").glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


def _start_events(data_dir: Path) -> list[dict]:
    return [e for e in _events(data_dir) if e.get("type") == "start"]


def test_closed_mode_has_no_start_key(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    nav = client.get("/api/nav").json()
    assert "start" not in nav
    assert client.get("/api/start").json()["open"] is False


def test_start_mode_end_to_end(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    r = client.post("/api/start/open", json={"open": True})
    assert r.status_code == 200
    b = r.json()["start"]
    assert b["open"] is True and b["error"] is False
    assert b["timer"]["state"] == "off" and b["line"]["committee"] is None
    assert b["line"]["pin"] is None

    # ping without GPS -> 409 no_position
    r = client.post("/api/start/ping", json={"end": "committee"})
    assert r.status_code == 409 and r.json() == {"detail": "no_position"}
    _feed_gps(ctx, *BOAT)
    r = client.post("/api/start/ping", json={"end": "committee"})
    assert r.status_code == 200
    com = r.json()["start"]["line"]["committee"]
    assert com == {"lat": BOAT[0], "lon": BOAT[1], "src": "ping"}

    r = client.put("/api/start/line/pin", json={"lat": 43.7161, "lon": 15.8037})
    assert r.status_code == 200
    assert r.json()["start"]["line"]["pin"]["src"] == "typed"

    for path, body in (
        ("/api/start/line/boat", {"lat": 43.7, "lon": 15.8}),
        ("/api/start/line/pin", {"lat": 50.0, "lon": 15.8}),
        ("/api/start/line/pin", {"lat": 43.7, "lon": 15.8, "x": 1}),
    ):
        assert client.put(path, json=body).status_code == 422, (path, body)
    # "NaN" as test_manual_wind sends it (allow_inf_nan=False refuses it)
    assert client.put("/api/start/line/pin", json={"lat": "NaN", "lon": 15.8}).status_code == 422
    assert client.post("/api/start/ping", json={"end": "boat"}).status_code == 422
    assert client.post("/api/start/timer", json={"action": "go"}).status_code == 422

    r = client.post("/api/start/timer", json={"action": "sync"})
    assert r.status_code == 409 and r.json() == {"detail": "no_timer"}
    r = client.post("/api/start/timer", json={"action": "start"})
    assert r.status_code == 200
    t = r.json()["start"]["timer"]
    assert t["state"] == "running" and abs(t["remaining_s"] - 300.0) <= 0.1
    assert t["gun_utc"] == "2026-11-13T20:05:00Z"
    ctx.clock.advance(25.0)
    r = client.post("/api/start/timer", json={"action": "sync"})
    assert r.status_code == 200 and r.json()["start"]["timer"]["remaining_s"] == 300.0
    r = client.post("/api/start/timer", json={"action": "stop"})
    assert r.json()["start"]["timer"]["state"] == "off"

    r = client.post("/api/start/open", json={"open": False})
    assert r.status_code == 200 and "start" not in r.json()
    assert "start" not in client.get("/api/nav").json()
    # the line ends survive closing start mode
    assert client.get("/api/start").json()["pin"]["src"] == "typed"

    actions = [e["action"] for e in _start_events(tmp_data_dir)]
    assert actions == ["open", "ping", "typed", "timer_start", "sync", "stop", "close"]
    ev = _start_events(tmp_data_dir)
    assert all({"t_mono", "t_wall", "utc"} <= set(e) for e in ev)


def test_the_gun_closes_start_mode_with_an_event(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    _feed_gps(ctx, *BOAT)
    client.post("/api/start/timer", json={"action": "start"})  # opens start mode too
    assert client.get("/api/nav").json()["start"]["open"] is True
    ctx.clock.advance(301.0)
    _feed_gps(ctx, *BOAT)
    ctx.tick_once()
    nav = client.get("/api/nav").json()
    assert "start" not in nav
    gun = _start_events(tmp_data_dir)[-1]
    assert gun["action"] == "gun" and gun["via"] == "timer"
    assert gun["boat"] == [BOAT[0], BOAT[1]]


def test_restart_keeps_line_and_timer(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    client.post("/api/start/open", json={"open": True})
    client.put("/api/start/line/committee", json={"lat": 43.7161, "lon": 15.7967})
    client.post("/api/start/timer", json={"action": "start"})
    # a new core 100 s later on the same data dir (trusted UTC from the start)
    ctx2, client2 = _make(tmp_data_dir, free_udp_port, start_utc=START_UTC + 100.0)
    b = client2.get("/api/nav").json()["start"]
    assert b["line"]["committee"]["src"] == "typed"
    assert b["timer"]["state"] == "running" and abs(b["timer"]["remaining_s"] - 200.0) <= 0.1


def test_write_failure_is_503_and_changes_nothing(
    tmp_data_dir: Path, free_udp_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jabuka.nav import start as start_mod

    ctx, client = _make(tmp_data_dir, free_udp_port)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(start_mod, "atomic_write_json", boom)
    r = client.post("/api/start/open", json={"open": True})
    assert r.status_code == 503 and r.json() == {"ok": False, "error": "start write failed"}
    assert "start" not in client.get("/api/nav").json()
    assert _start_events(tmp_data_dir) == []


def test_a_start_failure_never_touches_the_rest(
    tmp_data_dir: Path, free_udp_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    _feed_gps(ctx, *BOAT)
    client.post("/api/start/open", json={"open": True})
    good = ctx.nav.update()
    errors = ctx.nav.errors

    def boom(*_a, **_k):
        raise RuntimeError("start bug")

    monkeypatch.setattr("jabuka.core.nav_service.start_block", boom)
    bad = ctx.nav.update()
    assert bad["start"] == {"open": True, "error": True}
    assert {k: v for k, v in bad.items() if k != "start"} == {
        k: v for k, v in good.items() if k != "start"
    }
    assert ctx.nav.errors == errors and ctx.nav.start_errors == 1
    ctx.tick_once()  # the tick goes on
    assert ctx.nav.last is not None and ctx.nav.last["start"]["error"] is True


# -- Task 2: time to the line, margins, zone, start_tack_s (D-03, O-01) ---------------------------
TWD = 161.0


def _feed_wind(ctx, twd: float = TWD, tws: float = 12.0, twa: float = 45.0) -> None:
    s = SynthBoat(SynthConfig(twd=twd, tws=tws, twa=twa)).state
    ctx.on_message({"src": "fastnet", "values": udp_values(s)})


def _square_line(client) -> None:
    """A 0.6 nm line square to the wind, 0.2 nm upwind of BOAT (both tacks lay it)."""
    centre = geo.offset(*BOAT, math.radians(TWD), 0.2)
    com = geo.offset(*centre, math.radians(TWD - 90.0), 0.3)
    pin = geo.offset(*centre, math.radians(TWD + 90.0), 0.3)
    for end, (lat, lon) in (("committee", com), ("pin", pin)):
        r = client.put(f"/api/start/line/{end}", json={"lat": lat, "lon": lon})
        assert r.status_code == 200


def _expected_t(ctx, nav: dict, hdg: float, extra_s: float = 0.0) -> float:
    """Independent recomputation: distance along hdg to the line / (polar x efficiency)."""
    w, s = nav["wind"], ctx.nav.settings
    line = nav["start"]["line"]
    com, pin = line["committee"], line["pin"]
    lat0, lon0 = nav["boat"]["lat"], nav["boat"]["lon"]
    ax, ay = geo.to_local(com["lat"], com["lon"], lat0, lon0)
    bx, by = geo.to_local(pin["lat"], pin["lon"], lat0, lon0)
    # boat at the origin: solve t * u(hdg) = A + k (B - A)
    ux, uy = math.sin(math.radians(hdg)), math.cos(math.radians(hdg))
    ex, ey = bx - ax, by - ay
    t = (ax * ey - ay * ex) / (ux * ey - uy * ex)
    twa = abs((w["twd_t"] - hdg + 180.0) % 360.0 - 180.0)
    eff = efficiency_for(twa, s.efficiency, s.efficiency_up, s.efficiency_down)
    return t / (eff * ctx.nav.polar.speed(w["tws_kn"], twa)) * 3600.0 + extra_s


def _ready(tmp_data_dir: Path, port: int):
    ctx, client = _make(tmp_data_dir, port)
    _feed_wind(ctx)
    _feed_gps(ctx, *BOAT)
    client.post("/api/start/open", json={"open": True})
    _square_line(client)
    r = client.post("/api/start/timer", json={"action": "start"})
    return ctx, client, r.json()


def test_times_margins_and_zone(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client, nav = _ready(tmp_data_dir, free_udp_port)
    st = nav["start"]
    assert nav["wind"]["source"] != "NONE" and st["reason"] is None
    assert st["line"]["length_nm"] == pytest.approx(0.6, abs=2e-3)
    now, other = st["now"], st["other"]
    assert now["hdg_t"] == pytest.approx(nav["boat"]["hdg_t"], abs=0.1)
    assert now["on_line"] and other["on_line"]
    assert now["t_s"] == pytest.approx(_expected_t(ctx, nav, now["hdg_t"]), abs=0.2)
    assert other["t_s"] == pytest.approx(_expected_t(ctx, nav, other["hdg_t"], 10.0), abs=0.2)
    rem = st["timer"]["remaining_s"]
    assert now["margin_s"] == pytest.approx(rem - now["t_s"], abs=0.11)
    assert other["margin_s"] == pytest.approx(rem - other["t_s"], abs=0.11)
    zone = st["zone"]
    assert zone is not None and zone[0] == zone[-1] and len(zone) >= 5
    # the zone shrinks as the timer runs
    ctx.clock.advance(150.0)
    _feed_wind(ctx)
    _feed_gps(ctx, *BOAT)
    later = ctx.nav.update()["start"]["zone"]
    assert later is not None

    def span(ring):
        return max(p[1] for p in ring) - min(p[1] for p in ring)

    assert span(later) < span(zone)


def test_no_wind_gives_a_reason_and_no_zone(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    _feed_gps(ctx, *BOAT)
    client.post("/api/start/open", json={"open": True})
    _square_line(client)
    st = client.post("/api/start/timer", json={"action": "start"}).json()["start"]
    assert st["reason"] == "no_wind"
    assert st["now"] is None and st["other"] is None and st["zone"] is None
    assert st["tack_now"] is False
    ctx.clock.advance(10.0)
    _feed_gps(ctx, *BOAT)
    st = ctx.nav.update()["start"]
    assert st["timer"]["state"] == "running" and st["timer"]["remaining_s"] == pytest.approx(290.0)


def test_start_tack_s_setting(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client, nav = _ready(tmp_data_dir, free_udp_port)
    base = nav["start"]["other"]["t_s"]
    schema = client.get("/api/settings/schema").json()["properties"]["start_tack_s"]
    assert schema["label"] == "Départ : durée d'un virement (s)"
    assert schema["default"] == 10.0

    def put(patch: dict) -> int:
        v = client.get("/api/settings").json()["version"]
        return client.put("/api/settings", json={"base_version": v, "patch": patch}).status_code

    for bad in (-1, 61):
        before = client.get("/api/settings").json()
        assert put({"start_tack_s": bad}) == 422
        assert client.get("/api/settings").json() == before
    for ok in (0, 60):
        assert put({"start_tack_s": ok}) == 200
        other = client.get("/api/nav").json()["start"]["other"]
        assert other["t_s"] == pytest.approx(base - 10.0 + ok, abs=0.2)
    assert put({"start_tack_s": 10, "tack_penalty_s": 90}) == 200
    nav2 = client.get("/api/nav").json()
    assert nav2["start"]["other"]["t_s"] == pytest.approx(base, abs=0.2)
    assert ctx.nav.settings.tack_penalty_s == 90.0


def test_settings_file_without_start_tack_s_loads(tmp_data_dir: Path, free_udp_port: int) -> None:
    (tmp_data_dir / "settings.json").write_text(
        json.dumps({"version": 3, "settings": {"tack_penalty_s": 60.0}})
    )
    ctx, _ = _make(tmp_data_dir, free_udp_port)
    assert ctx.nav.settings.start_tack_s == 10.0 and ctx.nav.settings.tack_penalty_s == 60.0
    assert ctx.nav.settings_store.alerts == []
