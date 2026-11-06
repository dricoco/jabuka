"""Pi-side race-pack loader: validation, corruptions, window, marks, base coverage rules."""

from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:
    np = pytest.importorskip("numpy")

from jabuka.prep.wxpack import write_npz  # noqa: E402
from jabuka.route.racepack import (  # noqa: E402
    DEFAULT_WINDOW_LOCAL,
    RaceWindow,
    coverage,
    load_pack,
    read_marks_file,
    window_from_local,
)


def _ts(*a: int) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp())


WINDOW = RaceWindow(_ts(2026, 11, 13, 17), _ts(2026, 11, 15, 9))
INSIDE = [("Vodice", 43.75, 15.78), ("Jabuka", 43.09153, 15.46054)]
LEGS = [("A Vodice → Jabuka", (43.75, 15.78), (43.09153, 15.46054))]


def _write(pack: Path, **over) -> Path:
    t, lat, lon, u, v = over.pop("grid")
    arrays = {"u": u, "v": v, "t": t, "lat": lat, "lon": lon, "model": "TEST", "run": "x"}
    arrays.update(over)
    return write_npz(pack, "wind", arrays, {"model": "TEST"})


def test_good_pack_loads_without_errors(rp, tmp_path) -> None:
    _write(tmp_path, grid=rp.synthetic_grid())
    pack = load_pack(tmp_path)
    assert pack.errors == [] and pack.wind is not None
    assert pack.waves is None and pack.current is None
    assert pack.landmask_path is None and pack.polar_path is None
    assert pack.wind.arrays["u"].dtype == np.float32
    assert pack.meta["wind"]["model"] == "TEST"


def test_missing_wind_is_an_error_not_an_exception(tmp_path) -> None:
    pack = load_pack(tmp_path)
    assert pack.wind is None
    assert any("wind.npz absent" in e for e in pack.errors)


def test_sha256_mismatch_rejected(rp, tmp_path) -> None:
    _write(tmp_path, grid=rp.synthetic_grid())
    side = json.loads((tmp_path / "wind.json").read_text(encoding="utf-8"))
    side["sha256"] = "0" * 64
    (tmp_path / "wind.json").write_text(json.dumps(side), encoding="utf-8")
    pack = load_pack(tmp_path)
    assert pack.wind is None
    assert any("sha256" in e for e in pack.errors)


def test_missing_sidecar_rejected(rp, tmp_path) -> None:
    _write(tmp_path, grid=rp.synthetic_grid())
    (tmp_path / "wind.json").unlink()
    pack = load_pack(tmp_path)
    assert pack.wind is None and any("wind.json" in e for e in pack.errors)


def test_non_monotonic_time_rejected(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    t = t.copy()
    t[5] = t[3]
    _write(tmp_path, grid=(t, lat, lon, u, v))
    pack = load_pack(tmp_path)
    assert pack.wind is None and any("temps non strictement croissants" in e for e in pack.errors)


def test_nan_only_slice_rejected(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    u = u.copy()
    u[7] = np.nan
    _write(tmp_path, grid=(t, lat, lon, u, v))
    pack = load_pack(tmp_path)
    assert pack.wind is None and any("sans aucune valeur valide" in e for e in pack.errors)


def test_wrong_dtype_rejected(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    _write(tmp_path, grid=(t, lat, lon, u.astype(np.float64), v))
    pack = load_pack(tmp_path)
    assert pack.wind is None and any("float32" in e for e in pack.errors)


def test_object_array_rejected_without_unpickling(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    obj = np.empty(u.shape, dtype=object)
    obj[...] = 0.0
    _write(tmp_path, grid=(t, lat, lon, obj, v))
    pack = load_pack(tmp_path)
    assert pack.wind is None
    assert any("refusé" in e for e in pack.errors)


def test_garbage_file_with_matching_sidecar_rejected(tmp_path) -> None:
    import hashlib

    data = b"not a zip archive at all"
    (tmp_path / "wind.npz").write_bytes(data)
    (tmp_path / "wind.json").write_text(
        json.dumps({"sha256": hashlib.sha256(data).hexdigest()}), encoding="utf-8"
    )
    pack = load_pack(tmp_path)
    assert pack.wind is None and any("illisible" in e for e in pack.errors)


def test_shape_mismatch_rejected(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    _write(tmp_path, grid=(t, lat[:-1], lon, u, v))
    pack = load_pack(tmp_path)
    assert pack.wind is None and any("forme" in e for e in pack.errors)


def test_window_from_local_converts_zagreb_to_utc() -> None:
    w = window_from_local("2026-11-13T18:00", "2026-11-15T10:00")
    assert (w.start_utc, w.end_utc) == (_ts(2026, 11, 13, 17), _ts(2026, 11, 15, 9))
    assert window_from_local(*DEFAULT_WINDOW_LOCAL) == w
    with pytest.raises(ValueError):
        window_from_local("2026-11-15T10:00", "2026-11-13T18:00")


def test_window_falls_back_to_fixed_offset_without_tzdata(monkeypatch, caplog) -> None:
    import zoneinfo

    def boom(key: str):
        raise zoneinfo.ZoneInfoNotFoundError(key)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", boom)
    w = window_from_local("2026-11-13T18:00", "2026-11-15T10:00")
    assert w.start_utc == _ts(2026, 11, 13, 17)
    assert "+01:00" in caplog.text


def test_read_marks_file_phase2_format(marks_file) -> None:
    doc = read_marks_file(marks_file)
    assert len(doc.marks) == 5
    assert doc.marks["jabuka"].lat == pytest.approx(43.09153)
    assert doc.marks["plic-sestre"].name == "Plić Sestre"
    assert doc.marks["mulo"].radius_nm == pytest.approx(0.5)
    assert [m for m, _ in doc.templates["A"]] == [
        "vodice",
        "plic-sestre",
        "jabuka",
        "blitvenica",
        "vodice",
    ]
    assert doc.templates["B"][3] == ("mulo", "port")


def test_read_marks_file_rejects_unknown_mark(tmp_path) -> None:
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {"marks": [{"id": "a", "lat": 43, "lon": 15}], "templates": {"A": [{"mark_id": "zz"}]}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="marque inconnue"):
        read_marks_file(p)


def test_coverage_ok_for_covering_pack(rp, tmp_path) -> None:
    # pack 13 Nov 12Z -> 15 Nov 12Z hourly, window 13 Nov 17Z -> 15 Nov 09Z
    _write(tmp_path, grid=rp.synthetic_grid())
    rep = coverage(load_pack(tmp_path), INSIDE, LEGS, WINDOW)
    assert rep.ok and rep.alerts == []
    assert rep.details["horizon_hold"] is False


def test_coverage_alerts_on_missing_end(rp, tmp_path) -> None:
    _write(tmp_path, grid=rp.synthetic_grid(hours=31))  # ends 14 Nov 18:00Z
    rep = coverage(load_pack(tmp_path), INSIDE, LEGS, WINDOW)
    assert not rep.ok
    assert rep.alerts[0].startswith("MÉTÉO INCOMPLÈTE")
    assert "14/11 19:00" in rep.alerts[0] and "15/11 10:00" in rep.alerts[0]
    assert rep.details["horizon_hold"] is True


def test_coverage_alerts_on_missing_start(rp, tmp_path) -> None:
    _write(tmp_path, grid=rp.synthetic_grid(t0=_ts(2026, 11, 13, 20)))
    rep = coverage(load_pack(tmp_path), INSIDE, LEGS, WINDOW)
    assert not rep.ok
    assert any("à partir du 13/11 21:00" in a and "13/11 18:00" in a for a in rep.alerts)


def test_coverage_alerts_on_point_outside_margin(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    _write(tmp_path, grid=(t, lat, lon, u, v))
    # lat[0] < 42.6 < lat[1]: on the grid but outside the interpolation margin
    outside = [("Hors grille", float(lat[0]) + 0.01, 15.5)]
    rep = coverage(load_pack(tmp_path), INSIDE + outside, LEGS, WINDOW)
    assert not rep.ok
    assert any(a.startswith("MÉTÉO INCOMPLÈTE") and "Hors grille" in a for a in rep.alerts)


def test_coverage_alerts_on_leg_leaving_grid(rp, tmp_path) -> None:
    _write(tmp_path, grid=rp.synthetic_grid())
    legs = [("Z Vodice → Large", (43.75, 15.78), (43.0, 17.5))]
    rep = coverage(load_pack(tmp_path), INSIDE, legs, WINDOW)
    assert not rep.ok and any("Vodice → Large" in a for a in rep.alerts)


def test_npz_written_in_memory_is_not_a_pickle(rp, tmp_path) -> None:
    path = _write(tmp_path, grid=rp.synthetic_grid())
    with np.load(io.BytesIO(path.read_bytes()), allow_pickle=False) as z:
        assert set(z.files) >= {"u", "v", "t", "lat", "lon", "model", "run"}


def test_real_dwd_samples_load_without_errors(rp, tmp_path) -> None:
    import shutil

    for src, dst in (("wind_icon_eu_sample", "wind"), ("waves_ewam_sample", "waves")):
        assert (rp.fixtures / f"{src}.npz").stat().st_size < 204800
        shutil.copyfile(rp.fixtures / f"{src}.npz", tmp_path / f"{dst}.npz")
        shutil.copyfile(rp.fixtures / f"{src}.json", tmp_path / f"{dst}.json")
    pack = load_pack(tmp_path)
    assert pack.errors == []
    assert pack.wind is not None and pack.waves is not None
    assert pack.wind.t.size == 24 and np.all(np.diff(pack.wind.t) == 3600)
    assert pack.waves.t.size == 24 and not np.isnan(pack.waves.arrays["hs"]).any()
    assert pack.meta["wind"]["model"] == "ICON-EU" and pack.meta["waves"]["model"] == "EWAM"
    # the 0.25 deg margin keeps the race bbox inside the interpolation margin of both grids
    for g in (pack.wind, pack.waves):
        assert g.lat[1] < 42.8 and g.lat[-2] > 44.0 and g.lon[1] < 15.0 and g.lon[-2] > 16.3


def _holes(rp, tmp_path, where) -> list[str]:
    t, lat, lon, u, v = rp.synthetic_grid()
    u[where(t, lat, lon)] = np.nan
    _write(tmp_path, grid=(t, lat, lon, u, v))
    pack = load_pack(tmp_path)
    assert pack.wind is not None  # the loader accepts partial NaN; coverage flags it
    holes = "vent sans valeur sur"
    return [a for a in coverage(pack, INSIDE, [], WINDOW).alerts if holes in a]


def test_wind_holes_in_the_race_area_are_an_alert(rp, tmp_path) -> None:
    """03-REVIEW MD-01: a pack whose wind is NaN west of 15.4 E (away from every mark and leg)
    loaded without any alert, and the router saw calms there."""
    alerts = _holes(rp, tmp_path, lambda t, lat, lon: np.s_[:, :, lon < 15.4])
    assert len(alerts) == 1 and alerts[0].startswith("MÉTÉO INCOMPLÈTE")
    assert "zone de course" in alerts[0]


@pytest.mark.parametrize("case", ["outside_area", "outside_window"])
def test_wind_holes_elsewhere_are_not_an_alert(rp, tmp_path, case) -> None:
    if case == "outside_area":  # southernmost row: beyond the stencil of the race bbox
        alerts = _holes(rp, tmp_path, lambda t, lat, lon: np.s_[:, 0, :])
    else:  # 13 Nov 12Z, before the bracket of the race window (16Z..17Z)
        alerts = _holes(rp, tmp_path, lambda t, lat, lon: np.s_[0, :, lon < 15.4])
    assert alerts == []
