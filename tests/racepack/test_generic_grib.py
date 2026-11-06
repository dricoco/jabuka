"""Organiser / any GRIB1-GRIB2 wind import (GRIB-01): keys, speed/direction, projected grids."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
    import pygrib
else:
    np = pytest.importorskip("numpy")
    pygrib = pytest.importorskip("pygrib")

from jabuka.common.conventions import uv_from_wind_from, wind_from_uv  # noqa: E402
from jabuka.prep import cli  # noqa: E402
from jabuka.prep import grib as gribmod  # noqa: E402
from jabuka.prep.grib import import_generic  # noqa: E402
from jabuka.prep.wxpack import default_crop  # noqa: E402
from jabuka.route.racepack import load_pack  # noqa: E402

REPO_MARKS = Path(__file__).resolve().parents[2] / "src" / "jabuka" / "nav" / "data" / "marks.json"


def _ts(*a: int) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp())


def _grib_cli(path: Path, out: Path, *extra: str) -> int:
    return cli.main(["grib", str(path), "--out", str(out), "--marks", str(REPO_MARKS), *extra])


def test_grib1_fixture_is_small_and_not_named_10u(rp) -> None:
    f = rp.fixtures / "grib" / "sample_grib1.grb"
    assert f.stat().st_size < 8192
    msgs = list(pygrib.open(str(f)))
    assert [m.edition for m in msgs] == [1, 1]
    assert all(m.shortName != "10u" for m in msgs)
    assert [m["indicatorOfParameter"] for m in msgs] == [33, 34]


def test_grib1_imports_with_ascending_lat_and_from_direction(rp, tmp_path, capsys) -> None:
    out = tmp_path / "pack"
    rc = _grib_cli(rp.fixtures / "grib" / "sample_grib1.grb", out)
    assert rc == 3  # a single forecast time cannot cover the race window
    printed = capsys.readouterr().out
    assert "champs trouvés" in printed
    pack = load_pack(out)
    assert pack.errors == [] and pack.wind is not None
    w = pack.wind
    assert w.t.tolist() == [_ts(2026, 11, 13, 18)]  # 12Z + P1 6 h (GRIB1 time range)
    assert np.all(np.diff(w.lat) > 0) and w.lat[0] == pytest.approx(42.75)
    u, v = w.arrays["u"], w.arrays["v"]
    assert np.allclose(u, 4.0, atol=0.01) and np.allclose(v, 3.0, atol=0.01)
    d, s = wind_from_uv(float(u[0, 0, 0]), float(v[0, 0, 0]))
    assert math.degrees(d) == pytest.approx(233.13, abs=0.05) and s == pytest.approx(5.0, abs=0.01)
    assert pack.meta["wind"]["model"] == "sample_grib1"


def test_grib1_northwards_rows_values_follow_latitude(rp, tmp_path) -> None:
    cube = import_generic(rp.fixtures / "grib" / "sample_grib1.grb", default_crop())
    assert np.all(np.diff(cube.lat) > 0)
    assert cube.fields["u"].shape == (1, cube.lat.size, cube.lon.size)


def test_speed_direction_pair_converts_with_from_semantics(rp, write_grib, tmp_path) -> None:
    msgs = []
    for h in (0, 1):
        msgs.append(rp.grib_message(short_name="10si", forecast=h * 60, values=10.0))
        msgs.append(rp.grib_message(short_name="10wdir", forecast=h * 60, values=90.0))
    f = write_grib(tmp_path / "sd.grib2", msgs)
    cube = import_generic(f, default_crop())
    eu, ev = uv_from_wind_from(math.radians(90.0), 10.0)  # wind FROM east -> blows westwards
    assert np.allclose(cube.fields["u"], eu, atol=1e-4)
    assert np.allclose(cube.fields["v"], ev, atol=1e-4)
    assert cube.fields["u"][0, 0, 0] == pytest.approx(-10.0, abs=1e-4)
    assert cube.t[1] - cube.t[0] == 3600


def test_vectorised_speed_direction_matches_conventions() -> None:
    rng = np.random.default_rng(3)
    spd = rng.uniform(0, 20, 50)
    deg = rng.uniform(0, 360, 50)
    u, v = gribmod.uv_from_speed_dir(spd, deg)
    for i in range(50):
        eu, ev = uv_from_wind_from(math.radians(deg[i]), spd[i])
        assert u[i] == pytest.approx(eu, abs=1e-9) and v[i] == pytest.approx(ev, abs=1e-9)


def _rotated(short_name: str, value: float, forecast: int = 0) -> bytes:
    """A rotated_ll message (south pole -40N 10E) whose real coordinates cover the race area."""
    tpl = Path(__file__).resolve().parents[1] / "fixtures" / "racepack" / "grib"
    g = pygrib.open(str(tpl / "icon_template.grib2")).message(1)
    g["gridDefinitionTemplateNumber"] = 1
    g = pygrib.fromstring(g.tostring())
    g["latitudeOfSouthernPoleInDegrees"] = -40.0
    g["longitudeOfSouthernPoleInDegrees"] = 10.0
    a, b, c, d = -7.8, -5.2, 3.0, 5.2
    ni, nj = int(round((d - c) / 0.1)) + 1, int(round((b - a) / 0.1)) + 1
    g["Ni"], g["Nj"] = ni, nj
    g["latitudeOfFirstGridPointInDegrees"], g["latitudeOfLastGridPointInDegrees"] = a, b
    g["longitudeOfFirstGridPointInDegrees"], g["longitudeOfLastGridPointInDegrees"] = c, d
    g["iDirectionIncrementInDegrees"] = g["jDirectionIncrementInDegrees"] = 0.1
    g["shortName"] = short_name
    g["dataDate"], g["dataTime"] = 20261113, 1200
    g["forecastTime"] = forecast
    g.values = np.full((nj, ni), value)
    return g.tostring()


def test_rotated_grid_regridded_to_regular_0025(write_grib, tmp_path) -> None:
    f = write_grib(tmp_path / "rot.grib2", [_rotated("10u", 6.0), _rotated("10v", -2.0)])
    assert pygrib.open(str(f)).message(1).gridType == "rotated_ll"
    cube = import_generic(f, default_crop())
    assert np.allclose(np.diff(cube.lat), 0.025) and np.allclose(np.diff(cube.lon), 0.025)
    assert cube.lat[0] >= 42.55 - 1e-9 and cube.lat[-1] <= 44.25 + 1e-9
    assert cube.lon[0] <= 15.0 and cube.lon[-1] >= 16.3
    u, v = cube.fields["u"][0], cube.fields["v"][0]
    finite = np.isfinite(u)
    assert finite.mean() > 0.9  # only corners outside the rotated source grid may be NaN
    assert np.allclose(u[finite], 6.0, atol=1e-4) and np.allclose(v[finite], -2.0, atol=1e-4)
    j = int(np.argmin(np.abs(cube.lat - 43.09)))
    i = int(np.argmin(np.abs(cube.lon - 15.46)))
    assert np.isfinite(u[j, i])  # Jabuka is covered


def test_idw_regrid_interpolates_between_source_points() -> None:
    src_lat = np.array([43.0, 43.0, 43.1, 43.1])
    src_lon = np.array([15.0, 15.1, 15.0, 15.1])
    vals = np.array([[0.0, 1.0, 0.0, 1.0]])
    lat = np.array([43.05])
    lon = np.array([15.0, 15.05, 15.1])
    out = gribmod.idw_regrid(src_lat, src_lon, vals, lat, lon)
    assert out.shape == (1, 1, 3)
    assert out[0, 0, 0] == pytest.approx(0.0, abs=1e-6)
    assert out[0, 0, 1] == pytest.approx(0.5, abs=1e-6)
    assert out[0, 0, 2] == pytest.approx(1.0, abs=1e-6)


def test_no_wind_field_exits_2_listing_fields(rp, write_grib, tmp_path, capsys) -> None:
    f = write_grib(
        tmp_path / "t2m.grib2",
        [rp.grib_message(short_name="2t", values=285.0), rp.grib_message(short_name="msl")],
    )
    assert _grib_cli(f, tmp_path / "pack") == 2
    err = capsys.readouterr().err
    assert "aucun champ de vent 10 m trouvé ; champs présents : 2t, msl" in err
    assert not (tmp_path / "pack" / "wind.npz").exists()


def test_grid_outside_bbox_exits_2(rp, write_grib, tmp_path, capsys) -> None:
    kw = {"lat_first": 50.0, "lat_last": 52.0, "lon_first": 0.0, "lon_last": 2.0}
    f = write_grib(
        tmp_path / "far.grib2",
        [rp.grib_message(short_name="10u", **kw), rp.grib_message(short_name="10v", **kw)],
    )
    assert _grib_cli(f, tmp_path / "pack") == 2
    assert "ne recouvre pas la zone de course" in capsys.readouterr().err


def test_huge_file_refused_before_parsing(tmp_path, monkeypatch, capsys) -> None:
    big = tmp_path / "huge.grb"
    with open(big, "wb") as fh:
        fh.truncate(201 * 1024 * 1024)  # sparse: no disk cost

    def boom(*a, **k):
        raise AssertionError("pygrib must not open an oversized file")

    monkeypatch.setattr(pygrib, "open", boom)
    assert _grib_cli(big, tmp_path / "pack") == 2
    assert "trop gros" in capsys.readouterr().err


def test_missing_file_exits_2(tmp_path, capsys) -> None:
    assert _grib_cli(tmp_path / "nope.grb", tmp_path / "pack") == 2
    assert "introuvable" in capsys.readouterr().err


def test_custom_name_writes_alternate_wind_file(rp, tmp_path) -> None:
    out = tmp_path / "pack"
    rc = _grib_cli(rp.fixtures / "grib" / "sample_grib1.grb", out, "--name", "wind_organiser")
    assert rc in (0, 3)
    assert (out / "wind_organiser.npz").is_file() and (out / "wind_organiser.json").is_file()
    assert _grib_cli(rp.fixtures / "grib" / "sample_grib1.grb", out, "--name", "../evil") == 2
