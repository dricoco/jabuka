"""Laptop land-mask prep: coastline -> land, rasterisation, npz round trip, hostile npz files."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
    import shapely
else:  # Phase 2 worktrees without numpy/shapely skip instead of failing
    np = pytest.importorskip("numpy")
    shapely = pytest.importorskip("shapely")

from jabuka.prep import land  # noqa: E402
from jabuka.route.frame import DEFAULT_FRAME, NM_M  # noqa: E402
from jabuka.route.landmask import LandMask  # noqa: E402

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "route" / "osm" / "coastline_mini.json"
MINI_BBOX = (15.05, 42.90, 15.15, 43.00)  # lon_min, lat_min, lon_max, lat_max


def _mini() -> dict:
    return land.validate_overpass(json.loads(MINI.read_text()))


def _contains(geom, lat: float, lon: float) -> bool:
    x, y = DEFAULT_FRAME.to_m(lat, lon)
    return bool(shapely.contains_xy(geom, x, y))


def test_coastline_to_land_mini() -> None:
    geom, info = land.coastline_to_land(_mini()["elements"], DEFAULT_FRAME, MINI_BBOX)
    assert info["unclassified"] == 0
    assert info["land_faces"] == 2  # the island and the mainland north of the chain
    assert _contains(geom, 42.9475, 15.10)  # island centre
    assert _contains(geom, 42.995, 15.10)  # north of the chain
    assert not _contains(geom, 42.965, 15.10)  # between island and mainland
    assert not _contains(geom, 42.92, 15.06)  # south of everything


def test_unclassified_face_is_an_error() -> None:
    # A broken coastline chain that never reaches the frame edge does not split the rectangle:
    # the only face is bounded by the frame alone, so land/water cannot be decided.
    elements = [
        {
            "type": "way",
            "id": 9,
            "tags": {"natural": "coastline"},
            "geometry": [{"lat": 42.95, "lon": 15.07}, {"lat": 42.95, "lon": 15.12}],
        }
    ]
    with pytest.raises(land.LandPrepError, match="non classées"):
        land.coastline_to_land(elements, DEFAULT_FRAME, MINI_BBOX)


def test_rasterize_matches_shapely_on_mini() -> None:
    geom, _ = land.coastline_to_land(_mini()["elements"], DEFAULT_FRAME, MINI_BBOX)
    x0, y0, nx, ny = land.grid_for(MINI_BBOX, 25.0, DEFAULT_FRAME)
    r = land.rasterize(geom, x0, y0, 25.0, nx, ny)
    assert r.shape == (ny, nx) and r.any() and not r.all()
    rng = np.random.default_rng(7)
    rows = rng.integers(0, ny, 2000)
    cols = rng.integers(0, nx, 2000)
    cx = x0 + (cols + 0.5) * 25.0
    cy = y0 + (rows + 0.5) * 25.0
    exact = shapely.contains_xy(geom, cx, cy)
    assert np.array_equal(exact, r[rows, cols])


def test_rasterize_uses_cell_centres() -> None:
    x0, y0, cell = 1000.0, -500.0, 25.0
    c, r = 7, 4
    sq = shapely.box(x0 + c * cell, y0 + r * cell, x0 + (c + 1) * cell, y0 + (r + 1) * cell)
    out = land.rasterize(sq, x0, y0, cell, 20, 10)
    assert out.sum() == 1 and out[r, c]
    assert not land.rasterize(shapely.Polygon(), x0, y0, cell, 20, 10).any()


def test_validate_overpass_rejects_bad_payloads() -> None:
    for bad in (
        [],
        {"elements": {}},
        {"elements": [{"type": "way"}]},
        {"elements": [{"type": "node", "id": 1, "lat": float("nan"), "lon": 15.0}]},
        {"elements": [{"type": "way", "id": 1, "geometry": [{"lat": 43.0, "lon": "x"}]}]},
    ):
        with pytest.raises(land.LandPrepError):
            land.validate_overpass(bad)


def test_offline_without_cache_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(land.LandPrepError, match="hors ligne"):
        land.fetch_overpass(land.COASTLINE_QUERY, tmp_path, offline=True)


def test_cache_is_reused(tmp_path: Path) -> None:
    path = land._cache_path(tmp_path, "q")
    path.write_text(MINI.read_text())
    assert land.fetch_overpass("q", tmp_path, offline=True)["elements"]


def _build_mini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(land, "fetch_overpass", lambda q, *a, **k: _mini())
    return land.build_mask(tmp_path, cell_m=25.0, shore_margin_m=100.0, bbox=MINI_BBOX)


def test_build_mask_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    side = _build_mini(tmp_path, monkeypatch)
    npz = tmp_path / "landmask.npz"
    disk = json.loads((tmp_path / "landmask.json").read_text())
    assert disk["sha256"] == hashlib.sha256(npz.read_bytes()).hexdigest() == side["sha256"]
    assert disk["bytes"] == npz.stat().st_size
    assert disk["osm_base"] == "2026-01-01T00:00:00Z" and disk["cell_m"] == 25.0
    assert disk["frame"] == {"lat0": 43.4, "lon0": 15.65}
    lm = LandMask.load(npz)
    _, _, nx, ny = land.grid_for(MINI_BBOX, 25.0, DEFAULT_FRAME)
    assert lm.shape == (ny, nx)
    assert lm.cell_nm == pytest.approx(25.0 / NM_M)
    assert lm.frame == DEFAULT_FRAME
    assert lm.margin_m == 100.0
    f = lm.frame
    island = f.to_xy(42.9475, 15.10)
    assert not lm.points_clear(*island)[0] and not lm.raw_points_clear(*island)[0]
    # 60 m south of the island's south shore: raw water, inside the 100 m margin
    near = f.to_xy(42.940 - 60 / NM_M / 60, 15.10)
    assert lm.raw_points_clear(*near)[0] and not lm.points_clear(*near)[0]
    assert lm.points_clear(*f.to_xy(42.965, 15.10))[0]
    assert land.check(tmp_path) == 0


def _arrays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    _build_mini(tmp_path, monkeypatch)
    with np.load(tmp_path / "landmask.npz") as z:
        return {k: z[k] for k in z.files}


def _save(path: Path, arrays: dict) -> Path:
    buf = io.BytesIO()
    np.savez(buf, **arrays)  # savez pickles object arrays: exactly the hostile case
    path.write_bytes(buf.getvalue())
    return path


def test_load_rejects_pickled_object_array(tmp_path: Path, monkeypatch) -> None:
    a = _arrays(tmp_path, monkeypatch)
    a["source"] = np.array([{"evil": 1}], dtype=object)
    bad = _save(tmp_path / "obj.npz", a)
    with pytest.raises(ValueError):
        LandMask.load(bad)


def test_load_rejects_missing_key(tmp_path: Path, monkeypatch) -> None:
    a = _arrays(tmp_path, monkeypatch)
    del a["raw"]
    with pytest.raises(ValueError, match="raw"):
        LandMask.load(_save(tmp_path / "missing.npz", a))


def test_load_rejects_packed_size_mismatch(tmp_path: Path, monkeypatch) -> None:
    a = _arrays(tmp_path, monkeypatch)
    a["mask"] = a["mask"][:, :-1]
    with pytest.raises(ValueError, match="mask"):
        LandMask.load(_save(tmp_path / "short.npz", a))
    a = _arrays(tmp_path, monkeypatch)
    a["shape"] = np.array([a["shape"][0], a["shape"][1] + 64], dtype=np.int64)
    with pytest.raises(ValueError):
        LandMask.load(_save(tmp_path / "shape.npz", a))


def test_load_rejects_non_npz(tmp_path: Path) -> None:
    junk = tmp_path / "junk.npz"
    junk.write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        LandMask.load(junk)
    with pytest.raises(ValueError):
        LandMask.load(tmp_path / "absent.npz")


def test_check_reports_cell_and_osm_base(tmp_path, monkeypatch, capsys) -> None:
    _build_mini(tmp_path, monkeypatch)
    assert land.main(["check", str(tmp_path / "landmask.npz")]) == 0
    out = capsys.readouterr().out
    assert "cellule 25 m" in out and "2026-01-01T00:00:00Z" in out
    # tampered file: the sidecar sha256 no longer matches
    (tmp_path / "landmask.json").write_text(json.dumps({"sha256": "0" * 64}))
    assert land.main(["check", str(tmp_path)]) == 1
