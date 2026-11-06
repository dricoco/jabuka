"""Copernicus Med current NetCDF import (GRIB-03): uo/vo TOWARDS, land = 0, depth squeeze, times."""

from __future__ import annotations

import inspect
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:
    np = pytest.importorskip("numpy")
# netCDF4 is skipped even under JABUKA_REQUIRE_ROUTE: one interpreter without a wheel is accepted
netCDF4 = pytest.importorskip("netCDF4")

from jabuka.prep import cli  # noqa: E402
from jabuka.prep import current as current_mod  # noqa: E402
from jabuka.prep.current import import_copernicus  # noqa: E402
from jabuka.prep.wxpack import default_crop  # noqa: E402
from jabuka.route.racepack import load_pack  # noqa: E402

REPO_MARKS = Path(__file__).resolve().parents[2] / "src" / "jabuka" / "nav" / "data" / "marks.json"
LAT = np.round(np.arange(42.4, 44.4 + 1e-9, 1 / 24), 6)
LON = np.round(np.arange(14.5, 16.8 + 1e-9, 1 / 24), 6)


def _ts(*a: int) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp())


def _land(shape):
    m = np.zeros(shape, dtype=bool)
    m[10:14, 20:25] = True  # an island
    return m


def _write_nc(path: Path, *, depth: bool = False, names=("uo", "vo"), std_names=None,
              descending_lat: bool = False, hours=(0, 1, 2)) -> Path:  # fmt: skip
    lat = LAT[::-1] if descending_lat else LAT
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", len(hours))
        if depth:
            ds.createDimension("depth", 1)
        ds.createDimension("latitude", lat.size)
        ds.createDimension("longitude", LON.size)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "hours since 2026-11-13 00:00:00"
        t.calendar = "gregorian"
        t[:] = np.array(hours, dtype=np.float64) + 12.0  # 12Z, 13Z, 14Z
        la = ds.createVariable("latitude", "f4", ("latitude",))
        la[:] = lat
        lo = ds.createVariable("longitude", "f4", ("longitude",))
        lo[:] = LON
        dims = ("time", "depth", "latitude", "longitude") if depth else (
            "time", "latitude", "longitude")  # fmt: skip
        land = _land((lat.size, LON.size))
        for k, (name, value) in enumerate(zip(names, (0.2, -0.1), strict=True)):
            var = ds.createVariable(name, "f4", dims, fill_value=np.float32(1e20))
            var.units = "m s-1"
            if std_names:
                var.standard_name = std_names[k]
            data = np.full((len(hours), lat.size, LON.size), value, dtype=np.float32)
            data[:, land] = 1e20
            data = np.ma.masked_equal(data, np.float32(1e20))
            var[:] = data[:, None] if depth else data
    return path


def test_signature_has_no_credentials() -> None:
    assert list(inspect.signature(import_copernicus).parameters) == ["path", "crop"]
    src = inspect.getsource(current_mod).lower()
    assert "password" not in src and "getpass" not in src


@pytest.mark.parametrize("depth", [False, True])
def test_import_land_zero_towards_preserved_times(tmp_path, depth) -> None:
    f = _write_nc(tmp_path / "cur.nc", depth=depth)
    cube = import_copernicus(f, default_crop())
    assert cube.t.tolist() == [_ts(2026, 11, 13, 12), _ts(2026, 11, 13, 13), _ts(2026, 11, 13, 14)]
    assert np.all(np.diff(cube.lat) > 0) and np.all(np.diff(cube.lon) > 0)
    crop = default_crop()
    assert cube.lat[0] >= crop.lat1 - 1e-6 and cube.lat[-1] <= crop.lat2 + 1e-6
    assert cube.lon[0] >= crop.lon1 - 1e-6 and cube.lon[-1] <= crop.lon2 + 1e-6
    u, v = cube.fields["u"], cube.fields["v"]
    assert u.dtype == np.float32 and not np.isnan(u).any() and not np.isnan(v).any()
    zero = (u == 0) & (v == 0)
    assert zero.any()  # land cells are 0 (unknown = no current), never nearest-filled
    assert np.allclose(u[~zero], 0.2) and np.allclose(v[~zero], -0.1)  # TOWARDS kept as is
    assert zero[0].sum() == 20  # the 4 x 5 island inside the crop


def test_descending_latitude_and_standard_names(tmp_path) -> None:
    std = ("eastward_sea_water_velocity", "northward_sea_water_velocity")
    f = _write_nc(tmp_path / "c.nc", names=("u_cur", "v_cur"), descending_lat=True, std_names=std)
    cube = import_copernicus(f, default_crop())
    assert np.all(np.diff(cube.lat) > 0)
    nonzero = cube.fields["u"][0] != 0
    assert np.allclose(cube.fields["u"][0][nonzero], 0.2)


def test_missing_variables_is_a_french_error(tmp_path) -> None:
    f = _write_nc(tmp_path / "c.nc", names=("a", "b"))
    with pytest.raises(ValueError, match="uo/vo"):
        import_copernicus(f, default_crop())


def test_cli_current_writes_pack_component(tmp_path, capsys) -> None:
    f = _write_nc(tmp_path / "current_med.nc")
    out = tmp_path / "pack"
    rc = cli.main(["current", str(f), "--out", str(out), "--marks", str(REPO_MARKS)])
    assert rc == 3  # no wind in this pack
    pack = load_pack(out)
    assert pack.current is not None
    assert not any(e.startswith("current") for e in pack.errors)
    assert "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m" in pack.meta["current"]["source"]
    assert "Courant : " in capsys.readouterr().out


def test_cli_current_bad_file_exits_2(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.nc"
    bad.write_bytes(b"not netcdf")
    assert cli.main(["current", str(bad), "--out", str(tmp_path / "p"),
                     "--marks", str(REPO_MARKS)]) == 2  # fmt: skip
    assert "Erreur" in capsys.readouterr().err
