"""Mark library, Course A/B, next/prev, rounding-side anchor, persistence (CRSE-01/03/05)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from jabuka.nav import geo
from jabuka.nav.course import CourseStore, load_library
from jabuka.nav.settings import VersionConflict


def test_library_has_the_five_marks_and_two_courses() -> None:
    lib = load_library()
    ids = {m["id"] for m in lib["marks"]}
    assert ids == {"vodice", "plic-sestre", "jabuka", "blitvenica", "mulo"}
    names = {m["id"]: m["name"] for m in lib["marks"]}
    assert names["plic-sestre"] == "Plić Sestre"
    assert [e["mark_id"] for e in lib["templates"]["B"]][-3:] == ["jabuka", "mulo", "vodice"]
    assert {e["side"] for e in lib["templates"]["A"][1:-1]} == {"stbd"}
    assert {e["side"] for e in lib["templates"]["B"][1:-1]} == {"port"}
    assert lib["sides_confirmed"] is False


def test_empty_dir_defaults_to_course_a_at_plic_sestre(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    assert cs.course.template == "A"
    assert cs.course.active_idx == 1
    t = cs.active_target()
    assert t is not None and t.mark.name == "Plić Sestre"
    assert cs.status() == {
        "template": "A",
        "active_idx": 1,
        "finish_idx": None,
        "finished": False,
        "sides_confirmed": False,
        "banner": None,
    }
    assert not (tmp_path / "course.json").exists()  # nothing written until a change


def test_select_b_bumps_version_and_sets_sequence(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    v0 = cs.version
    api = cs.select("B")
    assert api["version"] == v0 + 1
    assert api["template"] == "B"
    assert [leg["mark_id"] for leg in api["seq"]] == [
        "vodice",
        "plic-sestre",
        "jabuka",
        "mulo",
        "vodice",
    ]
    assert api["active_idx"] == 1
    assert api["marks"]["mulo"]["builtin"] is True
    with pytest.raises(VersionConflict):
        cs.select("A", base_version=v0)
    with pytest.raises(ValueError):
        cs.select("Z")


def test_next_prev_clamp(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    assert cs.prev()["active_idx"] == 1  # the start (0) is never active
    for _ in range(10):
        cs.next()
    assert cs.course.active_idx == 4  # last index (finish at Vodice)
    v = cs.version
    cs.next()
    assert cs.version == v  # clamped: no change, no bump
    cs.prev()
    assert cs.course.active_idx == 3


def test_anchor_on_the_rounding_side(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)  # A: Plić Sestre to starboard
    t = cs.active_target()
    assert t.side == "stbd"
    b, d = geo.bearing_distance(t.mark.lat, t.mark.lon, t.anchor_lat, t.anchor_lon)
    assert d == pytest.approx(t.radius_nm, abs=1e-6)
    assert d == pytest.approx(0.3, abs=1e-6)
    expected = (t.leg_bearing - math.pi / 2) % (2 * math.pi)
    assert math.degrees(math.remainder(b - expected, 2 * math.pi)) == pytest.approx(0, abs=1e-6)
    # the leg bearing is Vodice -> Plić Sestre (161 deg)
    assert math.degrees(t.leg_bearing) == pytest.approx(161.0, abs=1.0)
    cs.select("B")  # port: +90
    t = cs.active_target()
    b, d = geo.bearing_distance(t.mark.lat, t.mark.lon, t.anchor_lat, t.anchor_lon)
    expected = (t.leg_bearing + math.pi / 2) % (2 * math.pi)
    assert math.degrees(math.remainder(b - expected, 2 * math.pi)) == pytest.approx(0, abs=1e-6)
    for _ in range(3):
        cs.next()
    t = cs.active_target()  # Vodice finish: side none -> the mark itself
    assert t.side == "none"
    assert (t.anchor_lat, t.anchor_lon) == (t.mark.lat, t.mark.lon)


def test_reload_from_same_dir(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.select("B")
    cs.next()
    again = CourseStore(tmp_path)
    assert again.course.template == "B"
    assert again.course.active_idx == 2
    assert again.version == cs.version == 2
    assert again.to_api() == cs.to_api()


def test_corrupt_file_falls_back_to_bak_then_defaults(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.select("B")
    cs.next()  # course.json = idx 2, course.json.bak = idx 1
    (tmp_path / "course.json").write_text("{torn")
    again = CourseStore(tmp_path)
    assert again.course.template == "B" and again.course.active_idx == 1
    (tmp_path / "course.json").write_text(json.dumps({"version": 3, "course": {"seq": []}}))
    (tmp_path / "course.json.bak").unlink()
    bad = CourseStore(tmp_path)
    assert bad.course.template == "A"
    assert bad.alerts and "Parcours" in bad.alerts[0]


def test_on_tick_records_position(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.on_tick(None, None, 1.0)
    assert cs.boat is None
    cs.on_tick(43.7, 15.8, 2.0)
    assert cs.boat == (43.7, 15.8, 2.0)
