"""GRIB-02 coverage rules 2, 4, 5 (rules 1 and 3 are in test_pack_load.py)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:
    np = pytest.importorskip("numpy")

from jabuka.prep import cli  # noqa: E402
from jabuka.prep.wxpack import write_npz  # noqa: E402
from jabuka.route.racepack import (  # noqa: E402
    RaceWindow,
    course_points_legs,
    coverage,
    format_report,
    load_pack,
    read_marks_file,
)

REPO_MARKS = Path(__file__).resolve().parents[2] / "src" / "jabuka" / "nav" / "data" / "marks.json"


def _ts(*a: int) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp())


WINDOW = RaceWindow(_ts(2026, 11, 13, 17), _ts(2026, 11, 15, 9))
POINTS = [("Vodice", 43.75, 15.78), ("Jabuka", 43.09153, 15.46054)]
LEGS = [("A Vodice → Jabuka", (43.75, 15.78), (43.09153, 15.46054))]


def _wind(pack: Path, grid) -> None:
    t, lat, lon, u, v = grid
    write_npz(pack, "wind", {"u": u, "v": v, "t": t, "lat": lat, "lon": lon}, {})


def _waves(pack: Path, grid, hs: float = 1.0) -> None:
    t, lat, lon, u, _v = grid
    write_npz(pack, "waves", {"hs": np.full_like(u, hs), "mwd": np.full_like(u, 200.0), "t": t,
                              "lat": lat, "lon": lon}, {})  # fmt: skip


def _current(pack: Path, grid) -> None:
    t, lat, lon, u, v = grid
    write_npz(pack, "current", {"u": u * 0 + 0.1, "v": v * 0, "t": t, "lat": lat, "lon": lon}, {})


def test_full_pack_ok_without_infos(rp, tmp_path) -> None:
    g = rp.synthetic_grid()
    _wind(tmp_path, g)
    _waves(tmp_path, g)
    _current(tmp_path, g)
    rep = coverage(load_pack(tmp_path), POINTS, LEGS, WINDOW)
    assert rep.ok and rep.alerts == [] and rep.warnings == [] and rep.infos == []
    assert rep.details["waves_ok"] and rep.details["current_ok"]
    assert rep.details["horizon_hold"] is False


def test_three_hourly_gap_is_a_warning_not_an_alert(rp, tmp_path) -> None:
    _wind(tmp_path, rp.synthetic_grid(hours=17, step_s=3 * 3600))  # 13 Nov 12Z .. 15 Nov 12Z
    rep = coverage(load_pack(tmp_path), POINTS, LEGS, WINDOW)
    assert rep.ok and rep.alerts == []
    assert any("pas de temps de 3 h" in w for w in rep.warnings)


def test_nan_wind_at_a_mark_is_an_alert(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    u = u.copy()
    j = int(np.searchsorted(lat, 43.09153)) - 1
    i = int(np.searchsorted(lon, 15.46054)) - 1
    u[20, j, i] = np.nan  # inside the window (13 Nov 12Z + 20 h)
    _wind(tmp_path, (t, lat, lon, u, v))
    pack = load_pack(tmp_path)
    assert pack.errors == []  # the loader accepts partial NaN; coverage flags it
    rep = coverage(pack, POINTS, [], WINDOW)
    assert not rep.ok
    assert any(
        "NaN" in a and "Jabuka" in a and a.startswith("MÉTÉO INCOMPLÈTE") for a in rep.alerts
    )


def test_nan_outside_window_is_ignored(rp, tmp_path) -> None:
    t, lat, lon, u, v = rp.synthetic_grid()
    u = u.copy()
    j = int(np.searchsorted(lat, 43.09153)) - 1
    i = int(np.searchsorted(lon, 15.46054)) - 1
    u[0, j, i] = np.nan  # 13 Nov 12Z, before the window bracket (16Z..17Z)
    _wind(tmp_path, (t, lat, lon, u, v))
    assert coverage(load_pack(tmp_path), POINTS, [], WINDOW).ok


def test_waves_and_current_failures_are_warnings_disabling_the_factor(rp, tmp_path) -> None:
    _wind(tmp_path, rp.synthetic_grid())
    short = rp.synthetic_grid(hours=20)  # ends 14 Nov 07Z
    _waves(tmp_path, short)
    _current(tmp_path, short)
    rep = coverage(load_pack(tmp_path), POINTS, LEGS, WINDOW)
    assert rep.ok and rep.alerts == []
    assert any(w.startswith("vagues jusqu'au") and "facteur vagues désactivé" in w
               for w in rep.warnings)  # fmt: skip
    assert any(w.startswith("courant jusqu'au") and "courant désactivé" in w for w in rep.warnings)
    assert rep.details["waves_ok"] is False and rep.details["current_ok"] is False


def test_missing_waves_and_current_are_info_lines(rp, tmp_path) -> None:
    _wind(tmp_path, rp.synthetic_grid())
    rep = coverage(load_pack(tmp_path), POINTS, LEGS, WINDOW)
    assert rep.ok
    assert "Vagues absentes : vitesse réduite d'après le vent" in rep.infos
    assert "Courant absent : routage sans courant" in rep.infos
    text = format_report(rep)
    assert "Info : Vagues absentes : vitesse réduite d'après le vent" in text


def test_invalid_waves_file_is_a_warning(rp, tmp_path) -> None:
    g = rp.synthetic_grid()
    _wind(tmp_path, g)
    _waves(tmp_path, g)
    (tmp_path / "waves.npz").write_bytes(b"tampered")
    pack = load_pack(tmp_path)
    assert pack.waves is None and any(e.startswith("waves.npz") for e in pack.errors)
    rep = coverage(pack, POINTS, LEGS, WINDOW)
    assert rep.ok
    assert any(w.startswith("Vagues invalides") and "désactivé" in w for w in rep.warnings)


def test_horizon_hold_flagged_when_wind_ends_early(rp, tmp_path) -> None:
    _wind(tmp_path, rp.synthetic_grid(hours=40))  # ends 15 Nov 03Z < 09Z
    rep = coverage(load_pack(tmp_path), POINTS, LEGS, WINDOW)
    assert not rep.ok and rep.details["horizon_hold"] is True
    assert "garde le dernier champ de vent" in format_report(rep)


def test_missing_wind_is_an_alert(tmp_path) -> None:
    rep = coverage(load_pack(tmp_path), POINTS, LEGS, WINDOW)
    assert not rep.ok and rep.alerts[0].startswith("MÉTÉO INCOMPLÈTE : pas de vent utilisable")


def test_course_points_and_legs_from_marks_file() -> None:
    doc = read_marks_file(REPO_MARKS)
    points, legs = course_points_legs(doc)
    assert {p[0] for p in points} == {"Vodice", "Plić Sestre", "Jabuka", "Blitvenica", "Mulo"}
    assert len(legs) == 6  # A: 4 legs, B: 4 legs, Vodice-Plić Sestre-Jabuka shared
    assert all(a != b for _n, a, b in legs)


def test_check_command_reports_ok_for_full_pack(rp, tmp_path, capsys) -> None:
    g = rp.synthetic_grid()
    _wind(tmp_path, g)
    _waves(tmp_path, g)
    _current(tmp_path, g)
    rc = cli.main(["check", "--out", str(tmp_path), "--marks", str(REPO_MARKS)])
    assert rc == 0
    assert (
        (tmp_path / "coverage.txt").read_text(encoding="utf-8").startswith("COUVERTURE MÉTÉO : OK")
    )
    assert "Rapport :" in capsys.readouterr().out
