"""jabuka-prep-map overlay half (HELM-01): seamarks + coastline from OSM, the maxzoom fallback
chain and the coastline-only pack. Offline: osmium only reads the hand-written mini.osm."""

from __future__ import annotations

import datetime as dt
import gzip
import json
import math
from pathlib import Path

import pytest
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write as pmtiles_write

from jabuka.prep import map as pm

MINI_OSM = Path(__file__).resolve().parents[1] / "fixtures" / "osm" / "mini.osm"
BBOX = pm.DEFAULT_BBOX
NOLOG = lambda _m: None  # noqa: E731


# -- seamark_feature ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind",
    [
        "light_major",
        "light_minor",
        "beacon_isolated_danger",
        "beacon_cardinal",
        "buoy_lateral",
        "buoy_special_purpose",
        "rock",
        "wreck",
        "obstruction",
        "landmark",
        "marine_farm",
    ],
)
def test_seamark_kept_types(kind: str) -> None:
    f = pm.seamark_feature("node/1", {"seamark:type": kind}, 15.8, 43.7, BBOX)
    assert f is not None
    assert f["type"] == "Feature"
    assert f["geometry"] == {"type": "Point", "coordinates": [15.8, 43.7]}
    assert f["properties"]["type"] == kind
    assert f["properties"]["id"] == "node/1"


@pytest.mark.parametrize("kind", ["mooring", "small_craft_facility", "seagrass", "harbour", ""])
def test_seamark_dropped_types(kind: str) -> None:
    assert pm.seamark_feature("node/1", {"seamark:type": kind}, 15.8, 43.7, BBOX) is None


def test_seamark_outside_bbox_or_bad_position_dropped() -> None:
    tags = {"seamark:type": "light_minor"}
    assert pm.seamark_feature("node/1", tags, 15.22, 44.12, BBOX) is None
    assert pm.seamark_feature("node/1", tags, 14.9, 43.5, BBOX) is None
    assert pm.seamark_feature("node/1", tags, math.nan, 43.5, BBOX) is None


def test_seamark_name_is_cleaned_and_cut() -> None:
    name = "Hrid\x00 Mulo\x1b[31m " + "x" * 80
    f = pm.seamark_feature(
        "node/1", {"seamark:type": "landmark", "seamark:name": name}, 15.9, 43.5, BBOX
    )
    assert f is not None
    got = f["properties"]["name"]
    assert len(got) == 60
    assert got.startswith("Hrid Mulo[31m ")
    assert all(ord(c) >= 32 and ord(c) != 127 for c in got)
    # falls back to name=*
    g = pm.seamark_feature("node/2", {"seamark:type": "rock", "name": "Sestrica"}, 15.9, 43.5, BBOX)
    assert g is not None and g["properties"]["name"] == "Sestrica"


def test_seamark_light_properties() -> None:
    tags = {
        "seamark:type": "beacon_isolated_danger",
        "seamark:light:character": "Fl",
        "seamark:light:group": "2",
        "seamark:light:colour": "white",
        "seamark:light:period": "10",
        "seamark:light:range": "4",
    }
    p = pm.seamark_feature("node/498394251", tags, 15.811626, 43.684627, BBOX)["properties"]
    assert p["light_character"] == "Fl"
    assert p["light_colour"] == "white"
    assert p["light_period"] == "10"
    assert p["light_range"] == "4"
    assert p["light"] == "Fl(2)W 10s 4M"
    bare = pm.seamark_feature("node/2", {"seamark:type": "rock"}, 15.8, 43.7, BBOX)["properties"]
    assert bare["light_character"] is None and bare["light"] is None


# -- coastline geometry -------------------------------------------------------------------------
def test_coastline_closed_way_is_a_polygon_and_open_way_a_line() -> None:
    ring = [(15.83, 43.69), (15.832, 43.69), (15.832, 43.688), (15.83, 43.688), (15.83, 43.69)]
    line = [(15.77, 43.76), (15.775, 43.758), (15.775, 43.758), (15.78, 43.755)]
    feats = pm.coastline_features([([1, 2, 3, 4, 1], ring), ([5, 6, 7, 8], line)], BBOX)
    kinds = sorted(f["geometry"]["type"] for f in feats)
    assert kinds == ["LineString", "Polygon"]
    ls = next(f for f in feats if f["geometry"]["type"] == "LineString")
    assert ls["geometry"]["coordinates"] == [[15.77, 43.76], [15.775, 43.758], [15.78, 43.755]]


def test_coastline_open_ways_chain_into_an_island_polygon() -> None:
    a = ([1, 2, 3], [(15.5, 43.5), (15.6, 43.5), (15.6, 43.6)])
    b = ([3, 4, 1], [(15.6, 43.6), (15.5, 43.6), (15.5, 43.5)])
    feats = pm.coastline_features([b, a], BBOX)
    assert len(feats) == 1
    g = feats[0]["geometry"]
    assert g["type"] == "Polygon"
    assert len(g["coordinates"][0]) == 5 and g["coordinates"][0][0] == g["coordinates"][0][-1]


def test_coastline_far_away_way_dropped_and_crossing_way_clipped() -> None:
    far = ([1, 2], [(18.0, 42.0), (18.1, 42.1)])
    crossing = ([3, 4, 5, 6], [(14.0, 43.5), (15.1, 43.5), (15.2, 43.5), (17.5, 43.5)])
    feats = pm.coastline_features([far, crossing], BBOX)
    assert len(feats) == 1
    coords = feats[0]["geometry"]["coordinates"]
    assert coords == [[15.1, 43.5], [15.2, 43.5]]


def test_rdp_simplify_drops_points_within_tolerance() -> None:
    # 1 km straight line with 1 m wiggles + a 50 m corner
    pts = [(15.0 + i * 0.0001, 43.5 + (0.000005 if i % 2 else 0.0)) for i in range(100)]
    pts.append((15.01, 43.5005))
    out = pm.rdp_simplify(pts, 5.0)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert len(out) <= 4
    assert pm.rdp_simplify(pts[:2], 5.0) == pts[:2]


def test_oversized_coastline_is_simplified() -> None:
    n = 400
    ring = [
        (15.5 + 0.05 * math.cos(2 * math.pi * k / n), 43.5 + 0.05 * math.sin(2 * math.pi * k / n))
        for k in range(n)
    ]
    ring.append(ring[0])
    wiggly = [(15.2 + i * 1e-5, 43.3 + (2e-6 if i % 2 else 0.0)) for i in range(2000)]
    fc = pm.coastline_collection(
        pm.coastline_features(
            [(list(range(n)) + [0], ring), (list(range(1000, 3000)), wiggly)], BBOX
        ),
        max_bytes=10_000,
    )
    total = sum(
        len(
            f["geometry"]["coordinates"][0]
            if f["geometry"]["type"] == "Polygon"
            else f["geometry"]["coordinates"]
        )
        for f in fc["features"]
    )
    assert total < 1000
    poly = next(f for f in fc["features"] if f["geometry"]["type"] == "Polygon")
    assert poly["geometry"]["coordinates"][0][0] == poly["geometry"]["coordinates"][0][-1]


# -- osmium extraction on mini.osm --------------------------------------------------------------
def test_extract_overlays_from_mini_osm() -> None:
    pytest.importorskip("osmium")
    seamarks, coastline = pm.extract_overlays(MINI_OSM, BBOX, log=NOLOG)
    assert seamarks["type"] == "FeatureCollection"
    by_id = {f["properties"]["id"]: f for f in seamarks["features"]}
    assert set(by_id) == {"node/498394251", "way/900000100"}
    beacon = by_id["node/498394251"]
    assert beacon["geometry"]["coordinates"] == [15.811626, 43.684627]
    assert beacon["properties"]["name"] == "Plicina Sestre, in Zlarinski Kanal."
    assert beacon["properties"]["light"] == "Fl(2)W 10s 4M"
    light = by_id["way/900000100"]
    assert light["properties"]["type"] == "light_major"
    assert light["geometry"]["coordinates"] == pytest.approx([15.5745, 43.625], abs=1e-6)

    kinds = sorted(f["geometry"]["type"] for f in coastline["features"])
    assert kinds == ["LineString", "Polygon"]
    poly = next(f for f in coastline["features"] if f["geometry"]["type"] == "Polygon")
    ring = poly["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] == [15.83, 43.69]
    assert [15.832, 43.69] in ring
    for f in coastline["features"]:
        coords = f["geometry"]["coordinates"]
        flat = coords[0] if f["geometry"]["type"] == "Polygon" else coords
        assert all(round(v, 5) == v for pt in flat for v in pt)
    line = next(f for f in coastline["features"] if f["geometry"]["type"] == "LineString")
    assert len(line["geometry"]["coordinates"]) == 3  # duplicate position dropped


# -- fallback chain -----------------------------------------------------------------------------
def _synthetic_extract(url: str, out: Path, bbox, maxzoom: int) -> None:
    """A valid gzip-MVT archive with one tile at z0 and one at maxzoom over the bbox centre."""
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    tiles = []
    for z in sorted({0, maxzoom}):
        x0, y0, _, _ = pm.tile_range(z, (lon, lat, lon, lat))
        tiles.append((zxy_to_tileid(z, x0, y0), gzip.compress(b"tile %d" % z)))
    w, s, e, n = bbox
    header = {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.GZIP,
        "min_lon_e7": round(w * 1e7),
        "min_lat_e7": round(s * 1e7),
        "max_lon_e7": round(e * 1e7),
        "max_lat_e7": round(n * 1e7),
        "center_zoom": 0,
        "center_lon_e7": round(lon * 1e7),
        "center_lat_e7": round(lat * 1e7),
    }
    with pmtiles_write(out) as wr:
        for tid, data in sorted(tiles):
            wr.write_tile(tid, data)
        wr.finalize(header, {})


def _overlays(bbox):
    seamarks = {
        "type": "FeatureCollection",
        "features": [
            pm.seamark_feature("node/498394251", {"seamark:type": "rock"}, 15.81, 43.68, bbox)
        ],
    }
    ring = [(15.83, 43.69), (15.832, 43.69), (15.832, 43.688), (15.83, 43.688), (15.83, 43.69)]
    coast = pm.coastline_collection(pm.coastline_features([([1, 2, 3, 4, 1], ring)], bbox))
    return seamarks, coast, {"osm": "mini"}


def _build(out: Path, extract, overlays=_overlays) -> int:
    return pm.build_pack(
        out,
        today=dt.date(2026, 11, 6),
        extract=extract,
        probe=lambda u: u.endswith("20261105.pmtiles"),
        overlays=overlays,
        log=NOLOG,
    )


def test_build_pack_falls_back_to_maxzoom_12(tmp_path: Path) -> None:
    tried = []

    def extract(url, out, bbox, maxzoom):
        tried.append(maxzoom)
        if maxzoom > 12:
            raise OSError("simulated timeout")
        _synthetic_extract(url, out, bbox, maxzoom)

    out = tmp_path / "pack"
    assert _build(out, extract) == pm.EXIT_OK
    assert tried == [14, 12]
    m = json.loads((out / "racepack.json").read_text())
    assert m["maxzoom"] == 12 and m["fallback"] == "maxzoom-12"
    assert m["counts"] == {"seamarks": 1, "coastline_features": 1}
    assert set(m["files"]) == {"race.pmtiles", "seamarks.geojson", "coastline.geojson"}
    assert pm.check_pack(out) == []


def test_build_pack_coastline_only_when_every_extract_fails(tmp_path: Path, capsys) -> None:
    tried = []

    def extract(url, out, bbox, maxzoom):
        tried.append(maxzoom)
        raise OSError("simulated network failure")

    out = tmp_path / "pack"
    out.mkdir()
    (out / "race.pmtiles").write_bytes(b"stale")
    code = pm.build_pack(
        out,
        today=dt.date(2026, 11, 6),
        extract=extract,
        probe=lambda u: True,
        overlays=_overlays,
        log=print,
    )
    assert code == pm.EXIT_OK
    assert tried == [14, 12, 10]
    assert "COASTLINE-ONLY" in capsys.readouterr().out
    assert not (out / "race.pmtiles").exists()
    m = json.loads((out / "racepack.json").read_text())
    assert m["fallback"] == "coastline-only" and m["maxzoom"] is None
    assert set(m["files"]) == {"seamarks.geojson", "coastline.geojson"}
    assert pm.check_pack(out) == []


def test_build_pack_coastline_only_when_no_build_is_reachable(tmp_path: Path) -> None:
    out = tmp_path / "pack"
    code = pm.build_pack(
        out,
        today=dt.date(2026, 11, 6),
        extract=lambda *a: pytest.fail("no build: extract must not run"),
        probe=lambda u: False,
        overlays=_overlays,
        log=NOLOG,
    )
    assert code == pm.EXIT_OK
    assert json.loads((out / "racepack.json").read_text())["fallback"] == "coastline-only"


def test_build_pack_fails_without_tiles_and_without_coastline(tmp_path: Path) -> None:
    def extract(url, out, bbox, maxzoom):
        raise OSError("down")

    assert _build(tmp_path / "p1", extract, overlays=None) == pm.EXIT_BUILD

    def broken(bbox):
        raise OSError("geofabrik down")

    assert _build(tmp_path / "p2", extract, overlays=broken) == pm.EXIT_BUILD
    # tiles fine but the OSM step failed: the pack is written, the build is reported failed
    assert _build(tmp_path / "p3", _synthetic_extract, overlays=broken) == pm.EXIT_BUILD
    assert (tmp_path / "p3" / "race.pmtiles").exists()


# -- check_pack GeoJSON validation --------------------------------------------------------------
def _write_fc(path: Path, features) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _point(lon, lat):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {},
    }


def _coastline_pack(tmp_path: Path) -> Path:
    out = tmp_path / "pack"

    def extract(url, out_, bbox, maxzoom):
        raise OSError("down")

    assert _build(out, extract) == pm.EXIT_OK
    return out


@pytest.mark.parametrize(
    "features, needle",
    [
        ([_point(17.5, 43.5)], "outside the bbox"),
        (
            [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[15.5, 43.5], [15.6, 43.5]]},
                }
            ],
            "Point",
        ),
        (
            [{"type": "Feature", "geometry": {"type": "Point", "coordinates": ["15.5", 43.5]}}],
            "coordinates",
        ),
    ],
)
def test_check_pack_rejects_bad_seamarks(tmp_path: Path, features, needle: str) -> None:
    out = _coastline_pack(tmp_path)
    _write_fc(out / "seamarks.geojson", features)
    pm.write_manifest(out, json.loads((out / "racepack.json").read_text()))
    problems = pm.check_pack(out)
    assert any("seamarks.geojson" in p and needle in p for p in problems), problems


def test_check_pack_rejects_a_non_feature_collection(tmp_path: Path) -> None:
    out = _coastline_pack(tmp_path)
    (out / "seamarks.geojson").write_text(json.dumps({"type": "Feature"}))
    pm.write_manifest(out, json.loads((out / "racepack.json").read_text()))
    assert any("FeatureCollection" in p for p in pm.check_pack(out))


def test_check_pack_coastline_only_needs_a_coastline_feature(tmp_path: Path) -> None:
    out = _coastline_pack(tmp_path)
    _write_fc(out / "coastline.geojson", [])
    pm.write_manifest(out, json.loads((out / "racepack.json").read_text()))
    assert any("coastline" in p for p in pm.check_pack(out))
