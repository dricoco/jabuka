"""Tracer (plan 03-02 Task 1): a GRIB2 wind file -> wind.npz + sidecar -> load_pack -> coverage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
    import pygrib  # noqa: F401
else:
    np = pytest.importorskip("numpy")
    pytest.importorskip("pygrib")

from jabuka.common.conventions import wind_from_uv  # noqa: E402
from jabuka.prep import cli  # noqa: E402
from jabuka.prep.grib import decode_wind_files  # noqa: E402
from jabuka.prep.wxpack import default_crop, write_cube  # noqa: E402
from jabuka.route.racepack import load_pack  # noqa: E402

REPO_MARKS = Path(__file__).resolve().parents[2] / "src" / "jabuka" / "nav" / "data" / "marks.json"


def test_template_is_tiny_icon_eu_message(rp) -> None:
    import pygrib

    assert rp.icon_template.stat().st_size < 4096
    g = pygrib.open(str(rp.icon_template)).message(1)
    assert g.shortName == "10u" and g.typeOfLevel == "heightAboveGround" and g.level == 10
    assert g["indicatorOfUnitOfTimeRange"] == 0  # minutes, as in the real ICON-EU files


def test_generated_grib2_imports_with_hourly_valid_times(rp, write_grib, tmp_path) -> None:
    f = write_grib(tmp_path / "in" / "wind.grib2", rp.wind_run_messages([0, 1, 2]))
    cube = decode_wind_files([f], default_crop(), tmp_dir=tmp_path / "cache")

    run = int(rp.run_13_12z.timestamp())
    assert cube.run == run
    # forecastTime is coded in minutes (60, 120): validDate gives exact hours, never 12:01/12:02
    assert cube.t.tolist() == [run, run + 3600, run + 7200]
    assert np.all(np.diff(cube.lat) > 0) and np.all(np.diff(cube.lon) > 0)
    # 0.25 deg margin: the crop spans 14.75..16.5E (grid step 0.0625) so 16.3E is interior
    assert cube.lon[0] == pytest.approx(14.75) and cube.lon[-1] == pytest.approx(16.5)
    assert cube.lon[1] < 15.0 and cube.lon[-2] > 16.3
    assert cube.lat[1] < 42.8 and cube.lat[-2] > 44.0
    u, v = cube.fields["u"], cube.fields["v"]
    assert u.dtype == np.float32 and u.shape == (3, cube.lat.size, cube.lon.size)
    direction = np.degrees(np.arctan2(-u, -v)) % 360.0
    assert np.allclose(direction, 0.0)  # wind FROM north
    assert np.allclose(np.hypot(u, v), 5.0)
    d, s = wind_from_uv(float(u[0, 3, 4]), float(v[0, 3, 4]))
    assert math.degrees(d) % 360 == pytest.approx(0.0, abs=1e-9) and s == pytest.approx(5.0)


@pytest.mark.parametrize("north_to_south", [False, True])
def test_rows_normalised_to_ascending_latitude(rp, write_grib, tmp_path, north_to_south) -> None:
    lat_first, lat_last = (44.5, 42.5) if north_to_south else (42.5, 44.5)
    lats, lons = rp.grid_axes(lat_first, lat_last)
    field = np.repeat(lats[:, None], lons.size, axis=1)  # value = latitude of the stored row
    msgs = [
        rp.grib_message(short_name="10u", lat_first=lat_first, lat_last=lat_last, values=field),
        rp.grib_message(short_name="10v", lat_first=lat_first, lat_last=lat_last, values=-field),
    ]
    f = write_grib(tmp_path / "rows.grib2", msgs)
    cube = decode_wind_files([f], default_crop())
    u = cube.fields["u"][0]
    assert np.all(np.diff(cube.lat) > 0)
    # the north-only gradient stays north: every row carries its own latitude
    assert np.allclose(u, cube.lat[:, None], atol=1e-3)
    assert np.allclose(cube.fields["v"][0], -cube.lat[:, None], atol=1e-3)


def test_written_pack_matches_sidecar_and_loader(rp, write_grib, tmp_path) -> None:
    f = write_grib(tmp_path / "wind.grib2", rp.wind_run_messages([0, 1, 2]))
    cube = decode_wind_files([f])
    out = tmp_path / "pack"
    path = write_cube(out, "wind", cube, model="ICON-EU", source="test")
    side = json.loads((out / "wind.json").read_text(encoding="utf-8"))
    assert side["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert side["bytes"] == path.stat().st_size and side["model"] == "ICON-EU"
    assert side["run"] == "2026-11-13T12:00:00Z" and side["t_first"] == "2026-11-13T12:00:00Z"
    pack = load_pack(out)
    assert pack.errors == []
    assert pack.wind is not None
    assert np.array_equal(pack.wind.t, cube.t)
    assert np.array_equal(pack.wind.lat, cube.lat) and np.array_equal(pack.wind.lon, cube.lon)
    assert np.array_equal(pack.wind.arrays["u"], cube.fields["u"])
    assert np.array_equal(pack.wind.arrays["v"], cube.fields["v"])
    assert pack.meta["wind"]["model"] == "ICON-EU"
    with np.load(path, allow_pickle=False) as z:  # strings load without pickle
        assert str(z["model"]) == "ICON-EU" and z["t"].dtype == np.int64


def _cli(src: Path, out: Path, marks: Path) -> int:
    return cli.main(
        [
            "wind",
            "--from-files",
            str(src),
            "--out",
            str(out),
            "--marks",
            str(marks),
            "--cache",
            str(out.parent / "cache"),
            "--now",
            "2026-11-13T10:00Z",
        ]
    )


def test_cli_wind_covering_pack_exits_0(rp, write_grib, tmp_path, capsys) -> None:
    write_grib(tmp_path / "src" / "icon.grib2", rp.wind_run_messages(range(0, 49)))
    out = tmp_path / "pack"
    assert _cli(tmp_path / "src", out, REPO_MARKS) == 0
    for name in ("wind.npz", "wind.json", "coverage.txt"):
        assert (out / name).is_file()
    report = (out / "coverage.txt").read_text(encoding="utf-8")
    assert report.startswith("COUVERTURE MÉTÉO : OK")
    assert "COUVERTURE MÉTÉO : OK" in capsys.readouterr().out


def test_cli_wind_incomplete_pack_exits_3(rp, write_grib, tmp_path, capsys) -> None:
    # 12Z + 30 h = 14 Nov 18:00Z (19:00 local): the window needs 15 Nov 09:00Z (10:00 local)
    write_grib(tmp_path / "src" / "icon.grib2", rp.wind_run_messages(range(0, 31)))
    out = tmp_path / "pack"
    assert _cli(tmp_path / "src", out, REPO_MARKS) == 3
    assert (out / "wind.npz").is_file()  # files are still written
    report = (out / "coverage.txt").read_text(encoding="utf-8")
    assert (
        "MÉTÉO INCOMPLÈTE : vent jusqu'au 14/11 19:00 seulement, fin requise 15/11 10:00" in report
    )
    assert "MÉTÉO INCOMPLÈTE" in capsys.readouterr().out


def test_cli_rejects_missing_dir_with_exit_2(tmp_path, capsys) -> None:
    rc = cli.main(
        [
            "wind",
            "--from-files",
            str(tmp_path / "nope"),
            "--out",
            str(tmp_path / "o"),
            "--marks",
            str(REPO_MARKS),
        ]
    )
    assert rc == 2
    assert "dossier introuvable" in capsys.readouterr().err


def test_module_runnable_check(rp, write_grib, tmp_path) -> None:
    write_grib(tmp_path / "src" / "icon.grib2", rp.wind_run_messages(range(0, 49)))
    out = tmp_path / "pack"
    assert _cli(tmp_path / "src", out, REPO_MARKS) == 0
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "jabuka.prep.cli",
            "check",
            "--out",
            str(out),
            "--marks",
            str(REPO_MARKS),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "COUVERTURE MÉTÉO : OK" in proc.stdout


def test_land_dispatch_reports_missing_module(monkeypatch, capsys) -> None:
    import importlib

    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "jabuka.prep.land":
            raise ModuleNotFoundError("No module named 'jabuka.prep.land'")
        return real(name, *a, **k)

    monkeypatch.setattr(cli.importlib, "import_module", fake)
    assert cli.main(["land", "build"]) == 2
    assert "jabuka.prep.land" in capsys.readouterr().err
