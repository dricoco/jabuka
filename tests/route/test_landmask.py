"""Hazards, margins and fast segment checks (ROUT-11): Plić Sestre and charted dangers are kept
at a distance; segment checks stay exact while skipping open water; snapping out of the margin."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
    import shapely  # noqa: F401  (prep needs it)
else:  # Phase 2 worktrees without numpy/shapely skip instead of failing
    np = pytest.importorskip("numpy")
    pytest.importorskip("shapely")

from jabuka.prep import land  # noqa: E402
from jabuka.route.frame import DEFAULT_FRAME, NM_M  # noqa: E402
from jabuka.route.landmask import LandMask, segments_touch  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "route" / "landmask_race_25m.npz"
BEACON = (43.684627, 15.811626)  # Plić Sestre, OSM node 498394251
F = DEFAULT_FRAME


def _off(p: tuple[float, float], dist_m: float, bearing_deg: float) -> tuple[float, float]:
    """Point dist_m from p on a true bearing (local flat earth, fine at these distances)."""
    b = math.radians(bearing_deg)
    dlat = dist_m * math.cos(b) / NM_M / 60
    dlon = dist_m * math.sin(b) / NM_M / 60 / math.cos(math.radians(p[0]))
    return p[0] + dlat, p[1] + dlon


def _blocked(lm: LandMask, p: tuple[float, float], raw: bool = False) -> bool:
    fn = lm.raw_points_clear if raw else lm.points_clear
    return not bool(fn(*lm.frame.to_xy(*p))[0])


def _node(i: int, p: tuple[float, float], **tags: str) -> dict:
    return {"type": "node", "id": i, "lat": p[0], "lon": p[1], "tags": tags}


def _build(tmp_path, monkeypatch, hazards: list[dict], bbox, **kw) -> LandMask:
    def fake(query, *a, **k):
        if "coastline" in query:
            return {"elements": [], "osm3s": {"timestamp_osm_base": "2026-01-01T00:00:00Z"}}
        return {"elements": hazards}

    monkeypatch.setattr(land, "fetch_overpass", fake)
    land.build_mask(tmp_path, bbox=bbox, **kw)
    return LandMask.load(tmp_path / "landmask.npz")


@pytest.fixture(scope="module")
def lm() -> LandMask:
    return LandMask.load(FIXTURE)


# ------------------------------------------------------------------ hazards (synthetic)
def test_plic_sestre_is_a_hazard_even_when_osm_omits_it(tmp_path, monkeypatch) -> None:
    m = _build(tmp_path, monkeypatch, [], (15.78, 43.66, 15.84, 43.71))
    assert _blocked(m, BEACON) and _blocked(m, _off(BEACON, 200, 90))
    assert not _blocked(m, BEACON, raw=True)
    assert not _blocked(m, _off(BEACON, 0.3 * NM_M, 90))
    side = json.loads((tmp_path / "landmask.json").read_text())
    assert side["hazards"]["hand"] == 2


HZ_CENTRE = (42.95, 15.10)
HZ_BBOX = (15.03, 42.90, 15.17, 43.00)
CLASSES = {
    # name: (bearing from HZ_CENTRE, tags, keeps the 200 m hazard margin)
    "awash": (0, {"seamark:type": "rock", "seamark:rock:water_level": "awash"}, True),
    "covers": (45, {"seamark:type": "rock", "seamark:rock:water_level": "covers"}, True),
    "beacon": (90, {"seamark:type": "beacon_isolated_danger"}, True),
    "buoy": (135, {"seamark:type": "buoy_isolated_danger"}, True),
    "wreck": (180, {"seamark:type": "wreck"}, True),
    "obstruction": (225, {"seamark:type": "obstruction"}, True),
    "reef": (270, {"natural": "reef"}, True),
    "submerged": (315, {"seamark:type": "rock", "seamark:rock:water_level": "submerged"}, False),
    "no_level": (20, {"seamark:type": "rock"}, False),
}


def _class_points():
    # one feature every 45 degrees on a 2 km circle (the "no_level" rock sits on a 3 km circle)
    return {
        k: _off(HZ_CENTRE, 3000 if k == "no_level" else 2000, b) for k, (b, _, _) in CLASSES.items()
    }


def _class_elements():
    pts = _class_points()
    return [_node(100 + i, pts[k], **CLASSES[k][1]) for i, k in enumerate(CLASSES)]


@pytest.mark.parametrize("submerged", [True, False])
def test_hazard_classes_and_submerged_flag(tmp_path, monkeypatch, submerged: bool) -> None:
    els = _class_elements()
    # natural=shoal as a polygon way (about 100 x 100 m) and an obstruction line way
    shoal_c = _off(HZ_CENTRE, 4500, 90)
    sq = [_off(shoal_c, 70, b) for b in (45, 135, 225, 315, 45)]
    els.append(
        {
            "type": "way",
            "id": 900,
            "tags": {"natural": "shoal"},
            "geometry": [{"lat": a, "lon": b} for a, b in sq],
        }
    )
    obs_a, obs_b = _off(HZ_CENTRE, 4500, 270), _off(HZ_CENTRE, 4500, 250)
    els.append(
        {
            "type": "way",
            "id": 901,
            "tags": {"seamark:type": "obstruction"},
            "geometry": [{"lat": p[0], "lon": p[1]} for p in (obs_a, obs_b)],
        }
    )
    m = _build(tmp_path, monkeypatch, els, HZ_BBOX, submerged_rocks=submerged)
    pts = _class_points()
    for name, (_, _, margin) in CLASSES.items():
        p = pts[name]
        assert not _blocked(m, p, raw=True), name
        if margin:
            # 50 m disc + 200 m hazard margin: blocked at 200 m, clear at 300 m
            assert _blocked(m, p) and _blocked(m, _off(p, 200, 10)), name
            assert not _blocked(m, _off(p, 300, 10)), name
        else:
            # submerged rock: a 50 m disc without margin, only with --submerged-rocks
            assert _blocked(m, p) is submerged, name
            assert _blocked(m, _off(p, 25, 10)) is submerged, name
            assert not _blocked(m, _off(p, 100, 10)), name
    # shoal polygon: inside and 200 m outside its edge are blocked, 320 m outside is clear
    assert _blocked(m, shoal_c) and _blocked(m, _off(shoal_c, 50 + 180, 0))
    assert not _blocked(m, _off(shoal_c, 50 + 320, 0))
    # obstruction way: 25 m line buffer + 200 m margin around its midpoint
    mid = ((obs_a[0] + obs_b[0]) / 2, (obs_a[1] + obs_b[1]) / 2)
    assert _blocked(m, mid) and _blocked(m, _off(mid, 200, 170))
    side = json.loads((tmp_path / "landmask.json").read_text())
    assert side["submerged_rocks"] is submerged
    assert side["hazards"]["rock_submerged"] == 2 and side["hazards"]["rock_awash"] == 2


def test_user_hazards_geojson(tmp_path, monkeypatch) -> None:
    pt = _off(HZ_CENTRE, 1500, 0)
    poly_c = _off(HZ_CENTRE, 1500, 180)
    ring = [_off(poly_c, 100, b) for b in (45, 135, 225, 315, 45)]
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [pt[1], pt[0]]},
            },
            {
                "type": "Feature",
                "properties": {"name": "plateau"},
                "geometry": {"type": "Polygon", "coordinates": [[[b, a] for a, b in ring]]},
            },
        ],
    }
    path = tmp_path / "extra.geojson"
    path.write_text(json.dumps(gj))
    m = _build(tmp_path / "out", monkeypatch, [], HZ_BBOX, hazards_file=path)
    assert _blocked(m, pt) and _blocked(m, _off(pt, 200, 0)) and not _blocked(m, _off(pt, 300, 0))
    assert _blocked(m, poly_c) and _blocked(m, _off(poly_c, 70 + 180, 0))
    assert not _blocked(m, _off(poly_c, 70 + 320, 0))


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        json.dumps({"type": "Feature", "geometry": {"type": "Circle", "coordinates": [15, 43]}}),
        json.dumps({"type": "Point", "coordinates": [15.1, "x"]}),
        json.dumps({"type": "Point", "coordinates": [15.1, float("inf")]}).replace(
            "Infinity", "1e999"
        ),
        json.dumps({"type": "Polygon", "coordinates": [[[15.1, 42.9], [15.2, 42.9]]]}),
        json.dumps({"type": "FeatureCollection", "features": "nope"}),
    ],
)
def test_invalid_user_hazards_are_rejected_in_french(tmp_path, payload: str) -> None:
    path = tmp_path / "bad.geojson"
    path.write_text(payload)
    with pytest.raises(land.LandPrepError, match="dangers"):
        land.load_user_hazards(path, F)


def test_user_hazards_file_size_cap(tmp_path) -> None:
    path = tmp_path / "big.geojson"
    path.write_bytes(b" " * (5 * 1024 * 1024 + 1))
    with pytest.raises(land.LandPrepError, match="trop gros"):
        land.load_user_hazards(path, F)


# ------------------------------------------------------------------ fast segment checks
def _brute_quarter(lm: LandMask, ax, ay, bx, by) -> np.ndarray:
    """Reference: sample every segment at a quarter of a cell; True = touches a blocked cell."""
    out = np.zeros(len(ax), dtype=bool)
    q = lm.cell_nm / 4
    for i in range(len(ax)):
        n = max(int(math.ceil(math.hypot(bx[i] - ax[i], by[i] - ay[i]) / q)), 1)
        t = np.linspace(0.0, 1.0, n + 1)
        out[i] = not lm.points_clear(ax[i] + t * (bx[i] - ax[i]), ay[i] + t * (by[i] - ay[i])).all()
    return out


def test_coarse_pass_is_exact_and_skips_open_water(lm: LandMask) -> None:
    rng = np.random.default_rng(20261112)
    n = 5000
    lat = rng.uniform(43.55, 43.80, n)
    lon = rng.uniform(15.6, 16.0, n)
    ax, ay = F.to_xy(lat, lon)
    length = rng.uniform(0.05, 3.0, n)
    brg = rng.uniform(0, 2 * math.pi, n)
    bx, by = ax + length * np.sin(brg), ay + length * np.cos(brg)

    fast = lm.segments_clear(ax, ay, bx, by)
    fine = ~segments_touch(lm.mask, lm.x0_nm, lm.y0_nm, lm.cell_nm, ax, ay, bx, by)
    assert np.array_equal(fast, fine)  # the coarse pass never changes an answer
    brute_blocked = _brute_quarter(lm, ax, ay, bx, by)
    # never report clear a segment that touches a blocked cell
    assert not np.any(fast & brute_blocked)
    # the exact traversal may only add corner clips shorter than a quarter cell
    assert np.mean(fast == ~brute_blocked) > 0.995
    skipped = ~lm.fine_pass_needed(ax, ay, bx, by)
    assert fast[skipped].all()  # skipped segments are clear by construction
    assert 0.05 < fast.mean() < 0.95  # the sample mixes clear and blocked segments
    # Only ~1/3 of random 0.05-3 nm segments in the archipelago are clear at all, so the
    # skip rate is measured on them: most open-water segments never reach the fine pass
    # (measured 77 % with 8 x 8 blocks on the land-only mask).
    assert skipped.sum() >= 0.60 * fast.sum(), (skipped.sum(), fast.sum())
    assert skipped.mean() >= 0.20, skipped.mean()


def test_near_land_zone(lm: LandMask) -> None:
    near = F.to_xy(43.7229, 15.7828)  # Prvić–Tijat pinch: land within 1 nm
    far = F.to_xy(43.30, 15.30)  # open sea SW
    assert lm.near_land(*near, within_nm=1.0)[0]
    assert not lm.near_land(*far, within_nm=1.0)[0]
    assert lm.near_land(*F.to_xy(42.0, 15.0), within_nm=1.0)[0]  # outside the grid


# ------------------------------------------------------------------ snapping, polylines
def test_snap_out_of_the_shore_margin(lm: LandMask) -> None:
    # find a raw-water cell 50 m off the Vodice shore: walk south from the town until raw water
    lat, lon = 43.76, 15.78
    while _blocked(lm, (lat, lon), raw=True):
        lat -= 5 / NM_M / 60
    p = _off((lat, lon), 50, 180)
    assert _blocked(lm, p) and not _blocked(lm, p, raw=True)
    x, y = F.to_xy(*p)
    snapped = lm.snap_clear(x, y)
    assert snapped is not None
    sx, sy, moved = snapped
    assert moved and math.hypot(sx - x, sy - y) <= 1.0
    assert lm.points_clear(sx, sy)[0] and lm.raw_segments_clear(x, y, sx, sy)[0]
    # nearest: no clear cell centre strictly closer has a land-free exit segment
    dist = math.hypot(sx - x, sy - y)
    r0, c0 = (int(v[0]) for v in lm.rc(x, y))
    k = int(dist / lm.cell_nm) + 2
    rr, cc = np.nonzero(~lm.mask[r0 - k : r0 + k + 1, c0 - k : c0 + k + 1])
    cx = lm.x0_nm + (cc + c0 - k + 0.5) * lm.cell_nm
    cy = lm.y0_nm + (rr + r0 - k + 0.5) * lm.cell_nm
    closer = np.hypot(cx - x, cy - y) < dist - 1e-9
    assert not lm.raw_segments_clear(x, y, cx[closer], cy[closer]).any()


def test_snap_clear_point_and_deep_inland(lm: LandMask) -> None:
    x, y = F.to_xy(43.60, 15.60)
    assert lm.snap_clear(x, y) == (x, y, False)
    inland = F.to_xy(43.80, 15.95)  # behind Šibenik, > 1 nm from the sea
    assert lm.snap_clear(*inland, max_nm=1.0) is None


def test_validate_polyline(lm: LandMask) -> None:
    # Vodice -> west along the shore -> straight through Tijat (segment 2)
    lats = np.array([43.75, 43.735, 43.735, 43.705])
    lons = np.array([15.78, 15.765, 15.75, 15.78])
    xs, ys = F.to_xy(lats, lons)
    assert lm.validate_polyline(xs, ys) == (False, 2)
    xs, ys = F.to_xy(np.array([43.60, 43.55, 43.50]), np.array([15.60, 15.65, 15.55]))
    assert lm.validate_polyline(xs, ys) == (True, None)
