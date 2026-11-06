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


def _grid_relative(msg: bytes, flag: int = 1) -> bytes:
    g = pygrib.fromstring(msg)
    g["uvRelativeToGrid"] = flag
    return g.tostring()


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x))


def test_grid_relative_rotated_wind_is_turned_to_true_north(write_grib, tmp_path) -> None:
    """03-REVIEW HI-03: wind blowing FROM grid north on a rotated grid (south pole -40N 10E) must
    come out FROM the bearing of the rotated north pole (40N 170W), about 4 deg at the race area,
    not FROM 000."""
    msgs = [_grid_relative(_rotated("10u", 0.0)), _grid_relative(_rotated("10v", -10.0))]
    f = write_grib(tmp_path / "rot_rel.grib2", msgs)
    assert pygrib.open(str(f)).message(1)["uvRelativeToGrid"] == 1
    cube = import_generic(f, default_crop())
    u, v = cube.fields["u"][0], cube.fields["v"][0]
    for la, lo in ((43.09, 15.46), (43.68, 15.81), (43.0, 16.25)):
        j = int(np.argmin(np.abs(cube.lat - la)))
        i = int(np.argmin(np.abs(cube.lon - lo)))
        twd, tws = wind_from_uv(float(u[j, i]), float(v[j, i]))
        want = _bearing_deg(float(cube.lat[j]), float(cube.lon[i]), 40.0, -170.0)
        assert abs(want) > 3.0  # the error this fixes
        got = math.degrees(twd)
        got = got - 360.0 if got > 180.0 else got
        assert got == pytest.approx(want, abs=0.3), (la, lo)
        assert tws == pytest.approx(10.0, abs=0.05)
    # the same components flagged earth-relative are taken as they are (FROM 000)
    plain = import_generic(
        write_grib(tmp_path / "rot_abs.grib2", [_rotated("10u", 0.0), _rotated("10v", -10.0)]),
        default_crop(),
    )
    fu, fv = plain.fields["u"][0], plain.fields["v"][0]
    ok = np.isfinite(fu)
    assert np.allclose(fu[ok], 0.0, atol=1e-4) and np.allclose(fv[ok], -10.0, atol=1e-4)


def test_mixed_grid_relative_components_are_refused(write_grib, tmp_path) -> None:
    msgs = [_grid_relative(_rotated("10u", 1.0)), _rotated("10v", -10.0)]
    with pytest.raises(ValueError, match="relative à la grille"):
        import_generic(write_grib(tmp_path / "mixed.grib2", msgs), default_crop())


def _lambert(lat0: float, lon0: float, lat1: float, step_m: float, n_xy: int):
    """lat/lon of a regular Lambert conformal (tangent at lat1, LoV lon0, origin latitude lat0)
    grid centred on the race area (43.4 N 15.6 E), from the spherical inverse projection."""
    r_earth = 6_371_229.0
    p1, p0 = math.radians(lat1), math.radians(lat0)
    n = math.sin(p1)
    big_f = math.cos(p1) * math.tan(math.pi / 4 + p1 / 2) ** n / n
    rho0 = r_earth * big_f / math.tan(math.pi / 4 + p0 / 2) ** n
    rho_c = r_earth * big_f / math.tan(math.pi / 4 + math.radians(43.4) / 2) ** n
    th_c = n * math.radians(15.6 - lon0)
    xc, yc = rho_c * math.sin(th_c), rho0 - rho_c * math.cos(th_c)
    half = (n_xy - 1) / 2.0
    x = (np.arange(n_xy) - half) * step_m + xc
    y = (np.arange(n_xy) - half) * step_m + yc
    xx, yy = np.meshgrid(x, y)
    rho = np.hypot(xx, rho0 - yy)
    theta = np.arctan2(xx, rho0 - yy)
    lat = np.degrees(2.0 * np.arctan((r_earth * big_f / rho) ** (1.0 / n)) - math.pi / 2)
    lon = lon0 + np.degrees(theta / n)
    return lat, lon, n


@pytest.mark.parametrize("lov", [10.0, 0.0])
def test_lambert_grid_orientation_is_the_meridian_convergence(lov: float) -> None:
    lat, lon, n = _lambert(43.4, lov, 45.0, 10_000.0, 21)
    alpha = np.degrees(gribmod.grid_x_bearing(lat, lon))
    want = 90.0 + n * (lon - lov)  # x axis = east turned by the convergence angle
    assert np.allclose(alpha, want, atol=0.1)
    if lov == 0.0:
        assert np.abs(alpha - 90.0).max() > 8.0  # about 11 deg at the race area
    # stored westwards / southwards: same axes
    flipped = np.degrees(gribmod.grid_x_bearing(lat[::-1, ::-1], lon[::-1, ::-1]))
    assert np.allclose(flipped, want[::-1, ::-1], atol=0.1)
    # grid-north wind turned back to true north
    u, v = gribmod.rotate_grid_uv(0.0, -10.0, np.radians(alpha))
    twd = np.degrees(np.arctan2(-u, -v))
    assert np.allclose(twd, alpha - 90.0, atol=1e-6)


def test_unreliable_grid_orientation_is_refused() -> None:
    lat, lon, _n = _lambert(43.4, 10.0, 45.0, 10_000.0, 11)
    skew_lon = lon + 0.3 * np.arange(11)[:, None] * 0.09  # rows sheared: axes not perpendicular
    with pytest.raises(ValueError, match="non perpendiculaires"):
        gribmod.grid_x_bearing(lat, skew_lon)
    with pytest.raises(ValueError, match="orientation"):
        gribmod.grid_x_bearing(lat.ravel(), lon.ravel())
    north = np.repeat(np.linspace(43.0, 44.0, 5)[:, None], 5, axis=1).T  # x axis along a meridian
    with pytest.raises(ValueError, match="est-ouest"):
        gribmod.grid_x_bearing(north, np.full((5, 5), 15.0) + np.arange(5)[:, None] * 0.01)


def test_idw_regrid_interpolates_between_source_points() -> None:
    src_lat = np.array([43.0, 43.0, 43.1, 43.1])
    src_lon = np.array([15.0, 15.1, 15.0, 15.1])
    vals = np.array([[0.0, 1.0, 0.0, 1.0]])
    out = gribmod.idw_regrid(
        src_lat, src_lon, vals, np.array([43.05]), np.array([15.0, 15.05, 15.1])
    )
    assert out.shape == (1, 1, 3)
    # 4-point inverse distance: symmetric, midpoint exact, edges pulled towards the near column
    assert out[0, 0, 1] == pytest.approx(0.5, abs=1e-9)
    assert out[0, 0, 0] < 0.5 < out[0, 0, 2]
    assert out[0, 0, 0] + out[0, 0, 2] == pytest.approx(1.0, abs=1e-9)
    # a target on a source point takes that value exactly
    hit = gribmod.idw_regrid(src_lat, src_lon, vals, np.array([43.0]), np.array([15.1]))
    assert hit[0, 0, 0] == pytest.approx(1.0, abs=1e-12)
    # far from every source -> NaN, never extrapolated
    far = gribmod.idw_regrid(src_lat, src_lon, vals, np.array([44.0]), np.array([15.05]))
    assert np.isnan(far).all()


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


def test_fill_wind_fills_u_and_v_together(capsys) -> None:
    """03-REVIEW MD-01: masked / IDW-edge wind cells are filled from the nearest valid cell (u and
    v from the same one) and the filled fraction is reported."""
    from jabuka.prep.wxpack import Cube

    u = np.full((1, 3, 4), 2.0, np.float32)
    v = np.full((1, 3, 4), -3.0, np.float32)
    u[0, :, 0] = np.nan  # west column masked in u only
    v[0, 2, 3] = np.nan  # one cell masked in v only
    u[0, 1, 1], v[0, 1, 1] = 5.0, -7.0  # the nearest valid cell for (1, 0)
    cube = Cube(
        t=np.array([0], np.int64),
        lat=np.array([43.0, 43.1, 43.2]),
        lon=np.array([15.0, 15.1, 15.2, 15.3]),
        fields={"u": u, "v": v},
    )
    frac = gribmod.fill_wind(cube)
    assert frac == pytest.approx(4 / 12)
    fu, fv = cube.fields["u"][0], cube.fields["v"][0]
    assert np.isfinite(fu).all() and np.isfinite(fv).all()
    assert (fu[1, 0], fv[1, 0]) == (5.0, -7.0)  # both components from the same cell
    assert fu.dtype == np.float32
    assert "33.3%" in capsys.readouterr().out


def test_rotated_grid_edges_are_filled(write_grib, tmp_path) -> None:
    f = write_grib(tmp_path / "rot.grib2", [_rotated("10u", 6.0), _rotated("10v", -2.0)])
    cube = import_generic(f, default_crop())
    assert np.isfinite(cube.fields["u"]).all() and np.isfinite(cube.fields["v"]).all()
