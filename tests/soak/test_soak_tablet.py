"""The soak tablet's message handling (no server): liveness transitions from diag rows, error
counter increases, route land re-validation once the matching nav arrives."""

from __future__ import annotations

import json
from pathlib import Path

from jabuka.soak.tablet import TabletClient

MASK = Path(__file__).resolve().parents[1] / "fixtures" / "route" / "landmask_race_25m.npz"


def _diag(wind: bool, pos: bool, uptime: float, nav_errors: int = 0) -> str:
    rows = [
        {
            "path": "environment.wind.angleApparent",
            "src": "fastnet",
            "value": 0.5,
            "stale": not wind,
        },
        {
            "path": "navigation.position",
            "src": "gpsd",
            "value": {"latitude": 43.7},
            "stale": not pos,
        },
    ]
    core = {"uptime_s": uptime, "nav_errors": nav_errors}
    return json.dumps({"type": "diag", "values": rows, "core": core, "clock": {"time_valid": True}})


def _route(version: int, pts: list[tuple[float, float]]) -> str:
    coords = [[lon, lat] for lat, lon in pts]
    feat = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"role": "route", "version": version},
    }
    return json.dumps(
        {
            "type": "route",
            "version": version,
            "kind": "optimal",
            "geojson": {"type": "FeatureCollection", "features": [feat]},
        }
    )


def _nav(version: int, margin: bool = False) -> str:
    return json.dumps(
        {
            "type": "nav",
            "layline": {"state": "normal"},
            "route": {"state": "ok", "version": version, "start_in_margin": margin},
        }
    )


def test_liveness_counters_and_land_check() -> None:
    tb = TabletClient("ws://127.0.0.1:9/ws", MASK)
    tb._on_text(_diag(True, True, 10.0))
    assert tb.live()
    tb._on_text(_diag(False, True, 11.0))
    assert tb.live()  # one stale row is debounced
    tb._on_text(_diag(False, True, 12.0, nav_errors=1))
    tb._on_text(_diag(False, True, 13.0, nav_errors=1))
    assert not tb.live() and tb.wind.transitions[-1][1] is False
    assert [i["counter"] for i in tb.counter_increases] == ["nav_errors"]
    assert tb.tick_ratio() == 1.0

    tb._on_text(_route(1, [(43.60, 15.70), (43.55, 15.75)]))  # open water
    assert tb.routes == []  # validated when the nav carrying its version arrives
    tb._on_text(_nav(1))
    tb._on_text(_route(2, [(43.75, 15.70), (43.65, 15.95)]))  # across the islands
    tb._on_text(_nav(2))
    assert [(r["version"], r["land_ok"]) for r in tb.routes] == [(1, True), (2, False)]
    assert tb.routes[1]["bad_index"] == 0
    assert tb.max_route_version() == 2
