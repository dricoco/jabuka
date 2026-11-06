"""Manual wind (WIND-04): with the bus silent, TWD/TWS typed from the B&G display (°M or °T) keep
the laylines alive with source MANUEL; fresh instrument wind wins (LIVE) without deleting the entry;
the entry survives a core restart, ages into "stale", and every change is an event line.

In-process core on a SimClock (no lifespan, so no background tick): inputs through ctx.on_message,
nav computed by ctx.nav.update().
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
from jabuka.sim.synth import SynthBoat, SynthConfig, udp_values

PLIC_SESTRE = (43.684627, 15.811626)
START_UTC = 1_794_600_000.0  # 2026-11-13
GPS_PATHS = ("navigation.position", "navigation.courseOverGroundTrue", "navigation.speedOverGround")


def _boat_pos(twd_t: float) -> tuple[float, float]:
    """2 nm straight downwind of Plić Sestre: the mark is a beat whatever the tack."""
    return geo.offset(*PLIC_SESTRE, math.radians(twd_t + 180.0), 2.0)


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


def _feed_wind(ctx, twd: float = 161.0, tws: float = 12.0) -> None:
    s = SynthBoat(SynthConfig(twd=twd, tws=tws, twa=45.0)).state
    ctx.on_message({"src": "fastnet", "values": udp_values(s)})


def _events(data_dir: Path) -> list[dict]:
    out = []
    for f in sorted((data_dir / "logs" / "events").glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


def test_manual_wind_keeps_laylines_alive(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    lat, lon = _boat_pos(204.7)
    _feed_gps(ctx, lat, lon)
    nav = ctx.nav.update()
    assert nav["wind"]["source"] == "NONE"
    assert nav["layline"] is None
    assert "PAS DE VENT" in nav["alerts"]

    r = client.post("/api/wind/manual", json={"twd": 200, "tws_kn": 12, "ref": "M"})
    assert r.status_code == 200
    nav = r.json()
    assert nav["type"] == "nav"
    assert nav["wind"]["source"] == "MANUEL"
    assert nav["wind"]["twd_t"] == pytest.approx(204.7, abs=0.05)
    assert nav["wind"]["tws_kn"] == pytest.approx(12.0, abs=0.05)
    assert nav["wind"]["manual_age_s"] == 0
    assert nav["wind"]["stale"] is False
    assert nav["layline"] is not None and nav["leg"] == "beat"
    assert nav["polar"]["up"] is not None
    assert "PAS DE VENT" not in nav["alerts"]
    stored = client.get("/api/wind/manual").json()["manual"]
    assert stored["ref_entered"] == "M" and stored["twd_entered"] == 200
    assert stored["twd_t_deg"] == pytest.approx(204.7)

    # °T is stored unchanged
    nav = client.post("/api/wind/manual", json={"twd": 200, "tws_kn": 12, "ref": "T"}).json()
    assert nav["wind"]["twd_t"] == pytest.approx(200.0, abs=0.05)

    # every change is an event line
    ev = [e for e in _events(tmp_data_dir) if e.get("type") == "wind_manual"]
    assert [e["action"] for e in ev] == ["set", "set"]
    assert ev[-1]["manual"]["ref_entered"] == "T"


def test_live_wins_then_manual_returns_when_the_bus_goes_stale(
    tmp_data_dir: Path, free_udp_port: int
) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    lat, lon = _boat_pos(204.7)
    _feed_gps(ctx, lat, lon)
    client.post("/api/wind/manual", json={"twd": 200, "tws_kn": 12, "ref": "M"})

    _feed_wind(ctx, twd=161.0)
    nav = ctx.nav.update()
    assert nav["wind"]["source"] == "LIVE"
    assert nav["wind"]["twd_t"] == pytest.approx(161.0, abs=0.5)
    assert nav["wind"]["manual_age_s"] is None
    assert client.get("/api/wind/manual").json()["manual"] is not None  # still stored

    # 6 s without wind deltas (wind stale after 5 s), GPS still alive -> MANUEL again
    for _ in range(6):
        ctx.clock.advance(1.0)
        _feed_gps(ctx, lat, lon)
    nav = ctx.nav.update()
    assert nav["wind"]["source"] == "MANUEL"
    assert nav["wind"]["twd_t"] == pytest.approx(204.7, abs=0.05)
    assert nav["layline"] is not None

    # older than manual_wind_max_age_min (30 min): stale but still used
    ctx.clock.advance(31 * 60.0)
    _feed_gps(ctx, lat, lon)
    nav = ctx.nav.update()
    assert nav["wind"]["source"] == "MANUEL"
    assert nav["wind"]["stale"] is True
    assert nav["wind"]["manual_age_s"] == pytest.approx(31 * 60 + 6, abs=1)
    assert nav["layline"] is not None
    assert "Vent manuel ancien (> 30 min)" in nav["alerts"]

    # cleared: nothing left while the bus is silent
    r = client.delete("/api/wind/manual")
    assert r.status_code == 200
    assert r.json()["wind"]["source"] == "NONE"
    assert "PAS DE VENT" in r.json()["alerts"]
    assert client.get("/api/wind/manual").json()["manual"] is None
    ev = [e["action"] for e in _events(tmp_data_dir) if e.get("type") == "wind_manual"]
    assert ev == ["set", "clear"]


def test_manual_wind_survives_a_restart(tmp_data_dir: Path, free_udp_port: int) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    client.post("/api/wind/manual", json={"twd": 90.5, "tws_kn": 8, "ref": "M"})
    assert (tmp_data_dir / "wind_manual.json").exists()

    ctx2, _ = _make(tmp_data_dir, free_udp_port, start_utc=START_UTC + 120.0)
    nav = ctx2.nav.update()
    assert nav["wind"]["source"] == "MANUEL"
    assert nav["wind"]["twd_t"] == pytest.approx(95.2, abs=0.05)
    assert nav["wind"]["tws_kn"] == pytest.approx(8.0)
    assert nav["wind"]["manual_age_s"] == pytest.approx(120.0, abs=1.0)

    # a cleared entry stays cleared after a restart
    client.delete("/api/wind/manual")
    ctx3, _ = _make(tmp_data_dir, free_udp_port)
    assert ctx3.nav.update()["wind"]["source"] == "NONE"


class _FakeHwClock(SimClock):
    """GPS UTC from the sim, but a system wall clock stuck behind it (fake-hwclock after a
    power cut, chrony not locked yet)."""

    def __init__(self, start_utc: float | None, wall: float) -> None:
        super().__init__(start_utc=start_utc)
        self._fake_wall = wall

    def wall(self) -> float:
        return self._fake_wall


def test_manual_age_uses_gps_utc_not_the_system_clock(
    tmp_data_dir: Path, free_udp_port: int
) -> None:
    """WR-03: entered at 20:00, power cut, fake-hwclock restores 20:17 while the GPS says 21:05:
    the age is 65 min (stale), not 17 min."""
    ctx = CoreContext.create(
        _FakeHwClock(START_UTC, wall=START_UTC), tmp_data_dir, udp_port=free_udp_port
    )
    TestClient(create_app(ctx)).post(
        "/api/wind/manual", json={"twd": 200, "tws_kn": 12, "ref": "T"}
    )
    later = _FakeHwClock(START_UTC + 65 * 60.0, wall=START_UTC + 17 * 60.0)
    ctx2 = CoreContext.create(later, tmp_data_dir, udp_port=free_udp_port)
    nav = ctx2.nav.update()
    assert nav["wind"]["source"] == "MANUEL"
    assert nav["wind"]["manual_age_s"] == pytest.approx(65 * 60.0, abs=1.0)
    assert nav["wind"]["stale"] is True


def test_manual_age_unknown_without_trusted_utc(tmp_data_dir: Path, free_udp_port: int) -> None:
    """WR-03: no trusted UTC (GPS not synced): the entry carries no time and the age is unknown
    (null), never computed from the system clock."""
    ctx = CoreContext.create(
        _FakeHwClock(None, wall=START_UTC), tmp_data_dir, udp_port=free_udp_port
    )
    client = TestClient(create_app(ctx))
    nav = client.post("/api/wind/manual", json={"twd": 200, "tws_kn": 12, "ref": "T"}).json()
    assert nav["wind"]["source"] == "MANUEL"
    assert nav["wind"]["manual_age_s"] is None and nav["wind"]["stale"] is False
    assert client.get("/api/wind/manual").json()["manual"]["t_set_wall"] is None
    # synced later: still unknown (the entry time was never known)
    ctx2 = CoreContext.create(
        _FakeHwClock(START_UTC + 600.0, wall=START_UTC), tmp_data_dir, udp_port=free_udp_port
    )
    assert ctx2.nav.update()["wind"]["manual_age_s"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"twd": 360, "tws_kn": 12, "ref": "M"},
        {"twd": -1, "tws_kn": 12, "ref": "M"},
        {"twd": 200, "tws_kn": -1, "ref": "M"},
        {"twd": 200, "tws_kn": 100, "ref": "T"},
        {"twd": 200, "tws_kn": 12, "ref": "X"},
        {"twd": 200, "tws_kn": 12},
        {"twd": 200, "tws_kn": 12, "ref": "M", "extra": 1},
        {"twd": "NaN", "tws_kn": 12, "ref": "M"},
    ],
)
def test_manual_wind_rejects_bad_values(tmp_data_dir: Path, free_udp_port: int, body) -> None:
    ctx, client = _make(tmp_data_dir, free_udp_port)
    r = client.post("/api/wind/manual", json=body)
    assert r.status_code == 422
    assert ctx.nav.manual.entry is None
    assert not (tmp_data_dir / "wind_manual.json").exists()


def test_corrupt_manual_file_is_ignored_with_an_alert(
    tmp_data_dir: Path, free_udp_port: int
) -> None:
    tmp_data_dir.mkdir(parents=True, exist_ok=True)
    (tmp_data_dir / "wind_manual.json").write_text('{"twd_t_deg": 999}')
    ctx, _ = _make(tmp_data_dir, free_udp_port)
    nav = ctx.nav.update()
    assert nav["wind"]["source"] == "NONE"
    assert "Vent manuel illisible : ignoré" in nav["alerts"]
