"""Soak finding (plan 04-01, power pull with a corrupted state file): a state file that exists
but cannot be read, with no readable .bak (first write ever has no .bak), must never be replaced
by the defaults silently. The store serves the default AND raises its "illisible" alert, as it
already does for a readable but invalid file."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from jabuka.common.atomicio import atomic_write_json, load_json_status, load_json_with_bak
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
