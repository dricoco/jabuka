"""Soak finding (plan 04-01, power pull with a corrupted state file): a state file that exists
but cannot be read, with no readable .bak (first write ever has no .bak), must never be replaced
by the defaults silently. The store serves the default AND raises its "illisible" alert, as it
already does for a readable but invalid file.

Plan 04-05 (04-REVIEW WR-04): a state file restored from NAME.bak is never silent either ("restauré"
alert), and a main file that decodes but fails validation falls through to a valid .bak before the
defaults. A valid main file loads exactly as before, with no alert."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from jabuka.common.atomicio import atomic_write_json, load_json_status, load_json_with_bak
from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.nav.course import CourseStore
from jabuka.nav.settings import ManualWindStore, Settings, SettingsStore

GARBAGE = random.Random(7).randbytes(300)


def test_load_json_status_tells_unreadable_from_missing(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    assert load_json_status(p, None) == (None, "missing")
    atomic_write_json(p, {"v": 1})
    assert load_json_status(p, None) == ({"v": 1}, "main")
    atomic_write_json(p, {"v": 2})
    p.write_bytes(b"{torn")
    assert load_json_status(p, None) == ({"v": 1}, "bak")
    p.with_name("x.json.bak").write_bytes(GARBAGE)
    assert load_json_status(p, 42) == (42, "unreadable")
    p.with_name("x.json.bak").unlink()
    assert load_json_status(p, 42) == (42, "unreadable")
    assert load_json_with_bak(p, 42) == 42  # the historical helper keeps its contract


def test_settings_garbage_without_bak_alerts(tmp_path: Path) -> None:
    st = SettingsStore(tmp_path)
    st.update({"efficiency": 0.85}, base_version=0)  # first write: no settings.json.bak
    assert not (tmp_path / "settings.json.bak").exists()
    (tmp_path / "settings.json").write_bytes(GARBAGE)
    again = SettingsStore(tmp_path)
    assert again.settings == Settings()
    assert "Réglages illisibles : valeurs par défaut" in again.alerts


def test_course_truncated_without_bak_alerts(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.select("B")  # first write: no course.json.bak
    data = (tmp_path / "course.json").read_bytes()
    (tmp_path / "course.json").write_bytes(data[: len(data) // 2])
    again = CourseStore(tmp_path)
    assert again.course.template == "A"
    assert "Parcours illisible : Parcours A par défaut" in again.alerts


def test_manual_wind_garbage_without_bak_alerts(tmp_path: Path) -> None:
    ms = ManualWindStore(tmp_path)
    ms.set(160.0, 12.0, "T", 4.7, None)
    (tmp_path / "wind_manual.json").write_bytes(GARBAGE)
    again = ManualWindStore(tmp_path)
    assert again.entry is None
    assert "Vent manuel illisible : ignoré" in again.alerts


@pytest.mark.parametrize("name", ["settings.json", "course.json", "wind_manual.json"])
def test_missing_file_is_still_silent(tmp_path: Path, name: str) -> None:
    """A file that never existed is a first boot, not a corruption: no alert."""
    assert not (tmp_path / name).exists()
    stores = {
        "settings.json": SettingsStore,
        "course.json": CourseStore,
        "wind_manual.json": ManualWindStore,
    }
    assert stores[name](tmp_path).alerts == []


# -- load_json_status(validate=...) ---------------------------------------------------------------
COURSE_FROM_BAK = "Parcours restauré depuis la sauvegarde : vérifier la marque active"


def _ok_only(raw: object) -> object:
    if not (isinstance(raw, dict) and raw.get("ok") is True):
        raise ValueError("not ok")
    return raw


def test_load_json_status_validate_falls_through_to_bak(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    atomic_write_json(p, {"ok": True, "n": 1})
    atomic_write_json(p, {"ok": False, "n": 2})  # decodes, does not validate
    assert load_json_status(p, None, validate=_ok_only) == ({"ok": True, "n": 1}, "bak")
    assert load_json_status(p, None) == ({"ok": False, "n": 2}, "main")  # no validate: as before


def test_load_json_status_validate_both_invalid_is_unreadable(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    atomic_write_json(p, {"ok": False})
    atomic_write_json(p, {"ok": "no"})
    assert load_json_status(p, 42, validate=_ok_only) == (42, "unreadable")


def test_load_json_status_validate_main_and_missing(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    assert load_json_status(p, 42, validate=_ok_only) == (42, "missing")
    atomic_write_json(p, {"ok": True})
    assert load_json_status(p, None, validate=lambda raw: ("parsed", raw)) == (
        ("parsed", {"ok": True}),
        "main",
    )


# -- course.json -----------------------------------------------------------------------------------
def _course_two_writes(data_dir: Path) -> CourseStore:
    cs = CourseStore(data_dir)
    cs.select("B")  # version 1, active 1
    cs.next()  # course.json = version 2, course.json.bak = version 1
    return cs


def test_course_torn_main_restored_from_bak_with_alert(tmp_path: Path) -> None:
    _course_two_writes(tmp_path)
    data = (tmp_path / "course.json").read_bytes()
    (tmp_path / "course.json").write_bytes(data[: len(data) // 2])
    again = CourseStore(tmp_path)
    assert again.course.template == "B"
    assert again.version == 1
    assert again.course.active_idx == 1
    assert again.alerts == [COURSE_FROM_BAK]


def test_course_schema_invalid_main_falls_through_to_bak(tmp_path: Path) -> None:
    _course_two_writes(tmp_path)
    (tmp_path / "course.json").write_text(json.dumps({"version": 3, "course": {"seq": []}}))
    again = CourseStore(tmp_path)
    assert again.course.template == "B"
    assert again.version == 1
    assert again.course.active_idx == 1
    assert again.alerts == [COURSE_FROM_BAK]


def test_course_both_invalid_gives_default_with_illisible(tmp_path: Path) -> None:
    _course_two_writes(tmp_path)
    (tmp_path / "course.json").write_text(json.dumps({"version": 3, "course": {"seq": []}}))
    (tmp_path / "course.json.bak").write_bytes(GARBAGE)
    again = CourseStore(tmp_path)
    assert again.course.template == "A"
    assert again.version == 0
    assert again.alerts == ["Parcours illisible : Parcours A par défaut"]


def test_course_valid_main_loads_unchanged_without_alert(tmp_path: Path) -> None:
    cs = _course_two_writes(tmp_path)
    again = CourseStore(tmp_path)
    assert again.version == 2
    assert again.to_api() == cs.to_api()
    assert again.alerts == []


def test_core_shows_the_course_restored_alert(tmp_data_dir: Path, free_udp_port: int) -> None:
    _course_two_writes(tmp_data_dir)
    data = (tmp_data_dir / "course.json").read_bytes()
    (tmp_data_dir / "course.json").write_bytes(data[: len(data) // 2])
    clock = SimClock(start_utc=1_794_600_000.0)
    ctx = CoreContext.create(clock, tmp_data_dir, udp_port=free_udp_port)
    assert COURSE_FROM_BAK in ctx.nav.update()["alerts"]


# -- settings.json ---------------------------------------------------------------------------------
SETTINGS_FROM_BAK = "Réglages restaurés depuis la sauvegarde : vérifier les réglages"


def _settings_two_writes(data_dir: Path) -> SettingsStore:
    st = SettingsStore(data_dir)
    st.update({"efficiency": 0.85}, base_version=0)
    st.update({"efficiency": 0.80}, base_version=1)  # settings.json.bak = 0.85, version 1
    return st


def test_settings_garbage_main_restored_from_bak_with_alert(tmp_path: Path) -> None:
    _settings_two_writes(tmp_path)
    (tmp_path / "settings.json").write_bytes(GARBAGE)
    again = SettingsStore(tmp_path)
    assert again.settings.efficiency == 0.85
    assert again.version == 1
    assert again.alerts == [SETTINGS_FROM_BAK]


def test_settings_schema_invalid_main_falls_through_to_bak(tmp_path: Path) -> None:
    _settings_two_writes(tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"version": 5, "settings": {"efficiency": 7}})
    )
    again = SettingsStore(tmp_path)
    assert again.settings.efficiency == 0.85
    assert again.version == 1
    assert again.alerts == [SETTINGS_FROM_BAK]


def test_settings_both_invalid_gives_defaults_with_illisible(tmp_path: Path) -> None:
    _settings_two_writes(tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"version": 5, "settings": {"efficiency": 7}})
    )
    (tmp_path / "settings.json.bak").write_bytes(GARBAGE)
    again = SettingsStore(tmp_path)
    assert again.settings == Settings()
    assert again.version == 0
    assert again.alerts == ["Réglages illisibles : valeurs par défaut"]


def test_settings_valid_main_loads_unchanged_without_alert(tmp_path: Path) -> None:
    st = _settings_two_writes(tmp_path)
    again = SettingsStore(tmp_path)
    assert again.settings == st.settings
    assert again.settings.efficiency == 0.80
    assert again.version == 2
    assert again.alerts == []


# -- wind_manual.json ------------------------------------------------------------------------------
MANUAL_FROM_BAK = "Vent manuel restauré depuis la sauvegarde : vérifier le vent"


def _manual_two_writes(data_dir: Path) -> ManualWindStore:
    ms = ManualWindStore(data_dir)
    ms.set(160.0, 12.0, "T", 4.7, None)
    ms.set(170.0, 14.0, "T", 4.7, None)  # wind_manual.json.bak = 160°
    return ms


def test_manual_garbage_main_restored_from_bak_with_alert(tmp_path: Path) -> None:
    _manual_two_writes(tmp_path)
    (tmp_path / "wind_manual.json").write_bytes(GARBAGE)
    again = ManualWindStore(tmp_path)
    assert again.entry is not None
    assert again.entry.twd_t_deg == 160.0
    assert again.alerts == [MANUAL_FROM_BAK]


def test_manual_schema_invalid_main_falls_through_to_bak(tmp_path: Path) -> None:
    _manual_two_writes(tmp_path)
    (tmp_path / "wind_manual.json").write_text('{"twd_t_deg": 999}')
    again = ManualWindStore(tmp_path)
    assert again.entry is not None
    assert again.entry.twd_t_deg == 160.0
    assert again.alerts == [MANUAL_FROM_BAK]


def test_manual_schema_invalid_main_without_bak_is_ignored_with_illisible(tmp_path: Path) -> None:
    (tmp_path / "wind_manual.json").write_text('{"twd_t_deg": 999}')
    again = ManualWindStore(tmp_path)
    assert again.entry is None
    assert again.alerts == ["Vent manuel illisible : ignoré"]


def test_manual_cleared_is_silent(tmp_path: Path) -> None:
    ms = _manual_two_writes(tmp_path)
    ms.clear()  # wind_manual.json = {}
    again = ManualWindStore(tmp_path)
    assert again.entry is None
    assert again.alerts == []


def test_manual_valid_main_loads_unchanged_without_alert(tmp_path: Path) -> None:
    ms = _manual_two_writes(tmp_path)
    again = ManualWindStore(tmp_path)
    assert again.entry == ms.entry
    assert again.entry is not None and again.entry.twd_t_deg == 170.0
    assert again.alerts == []
