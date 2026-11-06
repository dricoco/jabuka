"""EWAM waves: north-to-south rows, land bitmap, nearest-sea fill, mwd in degrees FROM."""

from __future__ import annotations

import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
    import pygrib
else:
    np = pytest.importorskip("numpy")
    pygrib = pytest.importorskip("pygrib")

from jabuka.prep import cli  # noqa: E402
from jabuka.prep.grib import decode_wave_files, fill_nearest  # noqa: E402
from jabuka.prep.wxpack import default_crop  # noqa: E402
from jabuka.route.racepack import load_pack  # noqa: E402

# EWAM-like grid: 0.1 deg lon x 0.05 deg lat, rows stored north to south
GRID = {"lat_first": 44.5, "lat_last": 42.4, "lon_first": 14.5, "lon_last": 16.8,
        "dlat": 0.05, "dlon": 0.1}  # fmt: skip


def _land_mask(lats, lons):
    m = np.zeros((lats.size, lons.size), dtype=bool)
    # an "island" near 43.5N 15.5E (3x2 cells) and a single masked cell near 43.0N 16.0E
    ri = np.flatnonzero(np.isclose(lats, 43.5))[0]
    ci = np.flatnonzero(np.isclose(lons, 15.5))[0]
    m[ri - 1 : ri + 2, ci : ci + 2] = True
    rj = np.flatnonzero(np.isclose(lats, 43.0))[0]
    cj = np.flatnonzero(np.isclose(lons, 16.0))[0]
    m[rj, cj] = True
    return m


def _messages(rp, lats, lons, mask):
    hs = 1.0 + (lats[:, None] - 42.0) + 0.01 * np.arange(lons.size)[None, :]  # varies N-S, E-W
    msgs = []
    for hour in (0, 1):
        msgs.append(rp.grib_message(template=rp.ewam_template, short_name="swh", forecast=hour,
                                    values=hs + hour, missing=mask, **GRID))  # fmt: skip
        msgs.append(rp.grib_message(template=rp.ewam_template, short_name="mwd", forecast=hour,
                                    values=270.0, missing=mask, **GRID))  # fmt: skip
    return msgs, hs


def test_ewam_template_keeps_bitmap_and_row_order(rp) -> None:
    assert rp.ewam_template.stat().st_size < 4096
    g = pygrib.open(str(rp.ewam_template)).message(1)
    assert g.shortName == "swh" and g["bitmapPresent"] == 1 and g["jScansPositively"] == 0
    assert np.ma.getmaskarray(g.values).sum() == 1


def test_ewam_decode_flips_rows_and_fills_land(rp, write_grib, tmp_path) -> None:
    lats, lons = rp.grid_axes(**GRID)
    mask = _land_mask(lats, lons)
    msgs, hs_stored = _messages(rp, lats, lons, mask)
    f = write_grib(tmp_path / "ewam.grib2", msgs)
    # sanity: the generated file really is EWAM-like (N->S rows, masked land)
    g = pygrib.open(str(f)).message(1)
    assert g["jScansPositively"] == 0 and np.ma.getmaskarray(g.values).sum() == mask.sum()

    cube = decode_wave_files([f], default_crop())
    hs, mwd = cube.fields["hs"], cube.fields["mwd"]
    assert hs.dtype == np.float32 and set(cube.fields) == {"hs", "mwd"}
    assert cube.t[1] - cube.t[0] == 3600
    assert np.all(np.diff(cube.lat) > 0)
    assert cube.lon[1] < 15.0 and cube.lon[-2] > 16.3  # margin keeps the 15.0E column interior
    assert not np.isnan(hs).any() and not np.isnan(mwd).any()
    assert np.allclose(mwd, 270.0)  # degrees FROM, untouched

    # map the cropped ascending grid back to the stored (N->S) grid
    rows = [int(np.argmin(np.abs(lats - la))) for la in cube.lat]
    cols = [int(np.argmin(np.abs(lons - lo))) for lo in cube.lon]
    stored = hs_stored[np.ix_(rows, cols)]
    sub_mask = mask[np.ix_(rows, cols)]
    assert np.allclose(hs[0][~sub_mask], stored[~sub_mask], atol=1e-4)  # sea cells unchanged
    assert np.allclose(hs[1][~sub_mask], stored[~sub_mask] + 1.0, atol=1e-4)
    for r, c in zip(*np.nonzero(sub_mask), strict=True):
        neighbours = [stored[rr, cc] for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
                      if 0 <= rr < stored.shape[0] and 0 <= cc < stored.shape[1]
                      and not sub_mask[rr, cc]]  # fmt: skip
        if neighbours:  # cells touching the sea take exactly one sea neighbour's value
            assert any(np.isclose(hs[0][r, c], n, atol=1e-4) for n in neighbours)
    # the single isolated masked cell: equal to one of its 4 sea neighbours
    rj = int(np.argmin(np.abs(cube.lat - 43.0)))
    cj = int(np.argmin(np.abs(cube.lon - 16.0)))
    assert sub_mask[rj, cj]
    expect = {
        round(float(stored[rj + dr, cj + dc]), 4) for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
    }
    assert round(float(hs[0][rj, cj]), 4) in expect


def test_fill_nearest_keeps_valid_and_fills_masked_row() -> None:
    a = np.arange(20, dtype=np.float64).reshape(4, 5)
    a[2, :] = np.nan  # an all-masked row
    a[0, 0] = np.nan
    out = fill_nearest(a)
    valid = ~np.isnan(a)
    assert np.array_equal(out[valid], a[valid])
    assert not np.isnan(out).any()
    assert np.array_equal(out[2], a[1]) or np.array_equal(out[2], a[3])
    assert out[0, 0] in (a[1, 0], a[0, 1])


def test_fill_nearest_3d_slices_independent_and_all_nan_slice_stays_nan() -> None:
    a = np.full((2, 3, 3), np.nan)
    a[0, 1, 1] = 7.0
    out = fill_nearest(a)
    assert np.all(out[0] == 7.0)
    assert np.isnan(out[1]).all()


def test_cli_waves_from_files_writes_valid_pack(rp, write_grib, tmp_path, capsys) -> None:
    lats, lons = rp.grid_axes(**GRID)
    msgs, _ = _messages(rp, lats, lons, _land_mask(lats, lons))
    write_grib(tmp_path / "src" / "ewam.grib2", msgs)
    out = tmp_path / "pack"
    rc = cli.main(["waves", "--from-files", str(tmp_path / "src"), "--out", str(out),
                   "--marks", str(rp.fixtures.parents[1].parent / "src" / "jabuka" / "nav"
                                  / "data" / "marks.json")])  # fmt: skip
    assert rc == 3  # no wind in this pack: coverage alerts
    pack = load_pack(out)
    assert pack.waves is not None and "mwd" in pack.waves.arrays
    assert not any(e.startswith("waves") for e in pack.errors)
    assert "Vagues : run" in capsys.readouterr().out
