"""The soak tablet's message handling (no server): liveness transitions from diag rows, error
counter increases, route land re-validation once the matching nav arrives."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from jabuka.route.frame import NM_M, Frame
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


# -- Pi soak 20261110T220521Z, check land "versions [121] at segments [4]" ----------------------
# The core publishes [round(lon, 6), round(lat, 6)] (router_service.route_message): up to 4.0 cm
# (x) / 5.6 cm (y) from the polyline the router validated. Two routes the router accepted on the
# soak pack rebuilt locally (course A, Blitvenica -> Vodice, near v121's time), published here
# verbatim: the unrounded segment clears the 100 m margin by 1.2 mm (route 1, segment 7, start in
# the margin) and 35.4 mm (route 2, segment 6); rounded, it touches it. Raw land >= 92 m away.
_GRAZE_MARGIN_START = [
    [15.644283, 43.673188], [15.644531, 43.672818], [15.667202, 43.665644],
    [15.694091, 43.662597], [15.719388, 43.656196], [15.747034, 43.658119],
    [15.772692, 43.664954], [15.778394, 43.680204], [15.77859, 43.695515],
    [15.782682, 43.711003], [15.776926, 43.747103], [15.78, 43.75],
]  # fmt: skip
_GRAZE_OPEN_START = [
    [15.64884, 43.675772], [15.636322, 43.690672], [15.633494, 43.707017],
    [15.643296, 43.719727], [15.669176, 43.724906], [15.722948, 43.728256],
    [15.749457, 43.731444], [15.78, 43.75],
]  # fmt: skip


def _latlon(coords: list[list[float]]) -> list[tuple[float, float]]:
    return [(lat, lon) for lon, lat in coords]


def test_a_rounding_graze_of_the_published_route_is_not_a_land_crossing() -> None:
    tb = TabletClient("ws://127.0.0.1:9/ws", MASK)
    tb._on_text(_route(1, _latlon(_GRAZE_MARGIN_START)))
    tb._on_text(_nav(1, margin=True))
    tb._on_text(_route(2, _latlon(_GRAZE_OPEN_START)))
    tb._on_text(_nav(2))
    assert [(r["version"], r["land_ok"], r["bad_index"]) for r in tb.routes] == [
        (1, True, None),
        (2, True, None),
    ]
    for r in tb.routes:  # how deep the published line went, for the report
        assert 0.0 < r["graze_m"] <= 0.0687, r
    # the exact zero-tolerance check (the old re-validation) does flag both
    xs, ys = tb.mask.frame.to_xy(*np.array(_latlon(_GRAZE_MARGIN_START)).T)
    assert tb.mask.validate_polyline(xs[1:], ys[1:]) == (False, 6)


def _strip_tablet() -> tuple[TabletClient, Frame, float]:
    """A 1 x 1 km mask in the race frame: rows >= 20 (y >= 500 m) blocked, the rest clear."""
    from jabuka.route.landmask import LandMask

    cell = 25.0 / NM_M
    grid = np.zeros((40, 40), dtype=bool)
    grid[20:, :] = True
    frame = Frame(lat0=43.4, lon0=15.65)
    tb = TabletClient("ws://127.0.0.1:9/ws")
    tb.mask = LandMask(grid, None, x0_nm=0.0, y0_nm=0.0, cell_nm=cell, frame=frame)
    return tb, frame, 20 * cell


@pytest.mark.parametrize(
    ("depth_m", "land_ok"),
    [
        (-0.5, True),  # clear: half a metre short of the blocked rows
        (0.0, True),  # on the boundary line (the exact check counts it blocked)
        (0.03, True),  # inside by less than the 6-decimal rounding (6.87 cm here)
        (0.068, True),
        (0.075, False),  # just past what rounding can explain
        (0.5, False),
        (100.0, False),  # a real crossing
    ],
)
def test_only_a_graze_within_the_publication_precision_is_tolerated(
    depth_m: float, land_ok: bool
) -> None:
    tb, frame, edge = _strip_tablet()
    y = edge + depth_m / NM_M
    lat, lon = frame.to_ll(np.array([125.0, 375.0]) / NM_M, np.array([y, y]))
    tb._on_text(_route(1, [(float(lat[0]), float(lon[0])), (float(lat[1]), float(lon[1]))]))
    tb._on_text(_nav(1))
    assert tb.routes[0]["land_ok"] is land_ok, tb.routes[0]
    assert tb.routes[0]["bad_index"] == (None if land_ok else 0)


def test_publication_precision_in_the_race_frame() -> None:
    from jabuka.soak.tablet import COORD_DECIMALS, publication_precision_nm

    assert COORD_DECIMALS == 6
    tol_m = publication_precision_nm(Frame(lat0=43.4, lon0=15.65)) * NM_M
    assert 0.0686 < tol_m < 0.0688  # hypot(4.04 cm east, 5.56 cm north)


def test_the_core_publishes_route_coordinates_at_the_tolerated_precision() -> None:
    """The tolerance is tied to router_service.route_message's rounding: if the core ever
    publishes coarser coordinates, this fails before a soak does."""
    import inspect

    from jabuka.core import router_service
    from jabuka.soak.tablet import COORD_DECIMALS

    src = inspect.getsource(router_service.RouterService.route_message)
    assert f"[round(p.lon, {COORD_DECIMALS}), round(p.lat, {COORD_DECIMALS})]" in src
