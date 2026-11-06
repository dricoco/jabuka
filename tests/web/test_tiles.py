"""Offline race pack: PMTiles index (root + leaf directories), tile route, overlays, Diag health."""

from __future__ import annotations

import gzip
import json
import random
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, TileType, deserialize_header, tileid_to_zxy
from pmtiles.writer import write

from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.core.tiles import TileIndex
from jabuka.core.web import create_app

FIX = Path(__file__).parent.parent / "fixtures" / "map"
SIBENIK = FIX / "sibenik.pmtiles"
SEAMARKS = FIX / "seamarks-mini.geojson"


def _write_archive(path: Path, tiles: list[tuple[int, bytes]], **header) -> None:
    h = {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.GZIP,
        "min_lon_e7": 150000000,
        "min_lat_e7": 430000000,
        "max_lon_e7": 160000000,
        "max_lat_e7": 440000000,
        "center_zoom": 0,
        "center_lon_e7": 155000000,
        "center_lat_e7": 435000000,
        **header,
    }
    with write(path) as w:
        for tile_id, data in sorted(tiles):
            w.write_tile(tile_id, data)
        w.finalize(h, {"name": "synthetic"})


def _all(path: Path) -> dict[tuple[int, int, int], bytes]:
    with open(path, "rb") as f:
        return {zxy: bytes(d) for zxy, d in all_tiles(MmapSource(f))}


@pytest.fixture
def racepack(tmp_path: Path) -> Path:
    d = tmp_path / "racepack"
    d.mkdir()
    shutil.copy(SIBENIK, d / "race.pmtiles")
    shutil.copy(SEAMARKS, d / "seamarks.geojson")
    return d


@pytest.fixture
def client(tmp_path: Path, racepack: Path, free_udp_port: int):
    ctx = CoreContext.create(
        SimClock(), tmp_path / "data", udp_port=free_udp_port, racepack_dir=racepack
    )
    with TestClient(create_app(ctx)) as c:
        yield c, ctx


def test_index_matches_reader_on_the_fixture() -> None:
    idx = TileIndex(SIBENIK)
    try:
        with open(SIBENIK, "rb") as f:
            reader = Reader(MmapSource(f))
            expected = _all(SIBENIK)
            assert idx.count == len(expected) > 0
            for (z, x, y), data in expected.items():
                assert idx.get(z, x, y) == data == bytes(reader.get(z, x, y))
        assert idx.get(11, 0, 0) is None
        assert idx.get(30, 1, 1) is None
        assert idx.get(3, -1, 0) is None
        assert (idx.minzoom, idx.maxzoom) == (8, 11)
        assert idx.bounds == pytest.approx([15.70, 43.62, 15.95, 43.80])
    finally:
        idx.close()


def test_index_follows_leaf_directories(tmp_path: Path) -> None:
    rng = random.Random(7)
    tiles, tid = [], 0
    for _ in range(30000):
        tid += rng.randint(1, 40)
        tiles.append((tid, rng.randbytes(rng.randint(1, 60))))
    path = tmp_path / "leafy.pmtiles"
    _write_archive(path, tiles)
    with open(path, "rb") as f:
        h = deserialize_header(f.read(127))
    assert h["leaf_directory_length"] > 0, "fixture must exercise leaf directories"
    idx = TileIndex(path)
    try:
        with open(path, "rb") as f:
            reader = Reader(MmapSource(f))
            for tile_id, data in rng.sample(tiles, 500) + tiles[:5] + tiles[-5:]:
                z, x, y = tileid_to_zxy(tile_id)
                assert idx.get(z, x, y) == data == bytes(reader.get(z, x, y))
        assert idx.count == len(tiles)
    finally:
        idx.close()


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        ({"tile_type": TileType.PNG}, "PNG"),
        ({"tile_compression": Compression.NONE}, "NONE"),
    ],
)
def test_wrong_archive_kind_is_rejected(
    tmp_path: Path, free_udp_port: int, header: dict, reason: str
) -> None:
    d = tmp_path / "racepack"
    d.mkdir()
    _write_archive(d / "race.pmtiles", [(0, b"x"), (1, b"y")], **header)
    with pytest.raises(ValueError, match=reason):
        TileIndex(d / "race.pmtiles")
    ctx = CoreContext.create(SimClock(), tmp_path / "data", udp_port=free_udp_port, racepack_dir=d)
    with TestClient(create_app(ctx)) as c:
        info = c.get("/racepack/info").json()
        assert info["tiles"] is False and reason in info["error"]
        assert c.get("/tiles/0/0/0.mvt").status_code == 204


def test_garbage_file_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "race.pmtiles"
    bad.write_bytes(b"not a pmtiles archive at all" * 10)
    with pytest.raises(ValueError, match="PMTiles"):
        TileIndex(bad)
    bad.write_bytes(b"short")
    with pytest.raises(ValueError):
        TileIndex(bad)


def test_tile_route(client) -> None:
    c, _ = client
    expected = _all(SIBENIK)
    (z, x, y), data = max(expected.items(), key=lambda kv: kv[0][0])
    assert z == 11
    r = c.get(f"/tiles/{z}/{x}/{y}.mvt")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"].startswith("public")
    assert r.content == gzip.decompress(data)  # the client undoes Content-Encoding
    for url in ("/tiles/15/0/0.mvt", "/tiles/11/-1/0.mvt", "/tiles/3/8/0.mvt", "/tiles/11/0/0.mvt"):
        assert c.get(url).status_code == 204, url
    assert c.get("/tiles/a/0/0.mvt").status_code == 422


def test_racepack_info_and_overlays(client) -> None:
    c, ctx = client
    info = c.get("/racepack/info").json()
    assert info["tiles"] is True and info["seamarks"] is True and info["coastline"] is False
    assert info["maxzoom"] == 11 and info["count"] == 8 and info["error"] is None
    fc = c.get("/racepack/seamarks.geojson")
    assert fc.status_code == 200
    assert fc.headers["content-type"].startswith("application/geo+json")
    assert fc.json() == json.loads(SEAMARKS.read_text())
    assert c.get("/racepack/coastline.geojson").status_code == 404
    assert c.get("/racepack/../race.pmtiles").status_code in (404, 405)


def test_racepack_health_in_diag(client) -> None:
    c, ctx = client
    ctx.tick_once()
    health = c.get("/api/state").json()["health"]["racepack"]
    for key in ("tiles", "seamarks", "coastline", "count", "maxzoom", "error"):
        assert key in health
    assert health["tiles"] is True and health["count"] == 8


def test_missing_racepack(tmp_path: Path, free_udp_port: int) -> None:
    ctx = CoreContext.create(SimClock(), tmp_path, udp_port=free_udp_port)
    with TestClient(create_app(ctx)) as c:
        info = c.get("/racepack/info").json()
        assert info["tiles"] is False and info["seamarks"] is False
        assert "absent" in info["error"]
        assert c.get("/tiles/10/556/372.mvt").status_code == 204
        assert c.get("/racepack/seamarks.geojson").status_code == 404
    assert ctx.racepack_dir == tmp_path / "racepack"
