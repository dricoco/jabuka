"""CourseStore editing operations (CRSE-01/02/04) and the rounding state machine (CRSE-03)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from jabuka.nav import geo
from jabuka.nav.course import CourseError, CourseStore, UnknownMark, load_library
from jabuka.nav.settings import VersionConflict

PLIC = (43.684627, 15.811626)


def ids(cs: CourseStore) -> list[str]:
    return [leg.mark_id for leg in cs.course.seq]


def active_id(cs: CourseStore) -> str:
    return cs.course.seq[cs.course.active_idx].mark_id


# -- editing ------------------------------------------------------------------------------------
def test_add_mark_positions_and_active_kept(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.add_mark("Bouée", 43.68, 15.79)  # default: right after the active mark
    assert ids(cs) == ["vodice", "plic-sestre", "m1", "jabuka", "blitvenica", "vodice"]
    cs.add_mark("Avant", 43.70, 15.79, insert_at=1)  # before the active one: active follows
    assert ids(cs)[1] == "m2"
    assert active_id(cs) == "plic-sestre" and cs.course.active_idx == 2
    assert cs.course.template == "custom"
    assert cs.version == 2
    with pytest.raises(CourseError):
        cs.add_mark("x", 43.7, 15.8, insert_at=0)
    with pytest.raises(VersionConflict):
        cs.add_mark("x", 43.7, 15.8, base_version=0)


def test_move_builtin_mark_is_an_override_that_survives_a_template_switch(tmp_path: Path) -> None:
    lib_before = json.dumps(load_library(), sort_keys=True)
    cs = CourseStore(tmp_path)
    cs.edit_mark("vodice", lat=43.74, lon=15.77, name="Ligne IC")
    assert cs.marks["vodice"].lat == 43.74 and cs.marks["vodice"].name == "Ligne IC"
    api = cs.to_api()
    assert api["marks"]["vodice"]["moved"] is True and api["marks"]["vodice"]["builtin"] is True
    assert api["marks"]["jabuka"]["moved"] is False
    cs.select("B")
    assert cs.marks["vodice"].lat == 43.74 and cs.marks["vodice"].name == "Ligne IC"
    assert json.dumps(load_library(), sort_keys=True) == lib_before  # marks.json untouched
    with pytest.raises(UnknownMark):
        cs.edit_mark("nope", lat=43.7, lon=15.8)
    with pytest.raises(CourseError):
        cs.edit_mark("vodice", lat=43.7)  # lat without lon
    with pytest.raises(ValueError):
        cs.edit_mark("vodice", lat=41.0, lon=15.8)


def test_move_custom_mark_in_place(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.add_mark("Bouée", 43.68, 15.79)
    cs.edit_mark("m1", lat=43.681, lon=15.791)
    assert (cs.marks["m1"].lat, cs.marks["m1"].lon) == (43.681, 15.791)
    assert "m1" not in cs.course.overrides


def test_set_leg_moves_the_anchor(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    t0 = cs.active_target()
    cs.set_leg(1, side="port", radius_nm=0.5)
    t1 = cs.active_target()
    assert (t1.side, t1.radius_nm) == ("port", 0.5)
    b, d = geo.bearing_distance(t1.mark.lat, t1.mark.lon, t1.anchor_lat, t1.anchor_lon)
    assert d == pytest.approx(0.5, abs=1e-6)
    expected = (t1.leg_bearing + math.pi / 2) % (2 * math.pi)
    assert math.degrees(math.remainder(b - expected, 2 * math.pi)) == pytest.approx(0, abs=1e-6)
    assert (t1.anchor_lat, t1.anchor_lon) != (t0.anchor_lat, t0.anchor_lon)
    with pytest.raises(CourseError):
        cs.set_leg(0, side="port")  # the start has no rounding side
    with pytest.raises(CourseError):
        cs.set_leg(9, side="port")
    with pytest.raises(ValueError):
        cs.set_leg(1, side="left")


def test_delete_leg_rules(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    with pytest.raises(CourseError):
        cs.delete_leg(0)
    cs.next()  # active = jabuka (2)
    cs.delete_leg(1)  # before the active one: index decrements, same mark
    assert active_id(cs) == "jabuka" and cs.course.active_idx == 1
    cs.delete_leg(1)  # the active one: the following mark becomes active
    assert active_id(cs) == "blitvenica" and cs.course.active_idx == 1
    cs.add_mark("Bouée", 43.68, 15.79, insert_at=2)
    assert "m1" in cs.marks
    cs.delete_leg(2)
    assert "m1" not in cs.marks  # custom mark no longer referenced leaves the library
    assert "jabuka" in cs.marks  # builtin marks stay
    assert ids(cs) == ["vodice", "blitvenica", "vodice"]
    cs.delete_leg(1)
    assert ids(cs) == ["vodice", "vodice"] and cs.course.active_idx == 1
    with pytest.raises(CourseError):
        cs.delete_leg(1)  # a course needs a start and one mark


def test_delete_last_leg_clamps_active(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.activate(4)
    cs.delete_leg(4)
    assert cs.course.active_idx == 3 and active_id(cs) == "blitvenica"


def test_reorder_keeps_the_active_mark(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.next()  # jabuka active (2)
    cs.reorder(2, 1)  # jabuka up
    assert ids(cs) == ["vodice", "jabuka", "plic-sestre", "blitvenica", "vodice"]
    assert active_id(cs) == "jabuka" and cs.course.active_idx == 1
    cs.reorder(3, 2)  # blitvenica up, past the (now later) plic
    assert active_id(cs) == "jabuka"
    for bad in ((0, 1), (1, 0), (1, 5), (7, 1), (2, 2)):
        with pytest.raises(CourseError):
            cs.reorder(*bad)


def test_finish_here_shortens_and_restores(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.set_finish(3)  # Blitvenica
    assert cs.course.finish_idx == 3 and cs.status()["finish_idx"] == 3
    for _ in range(5):
        cs.next()
    assert cs.course.active_idx == 3  # next() stops at the finish
    with pytest.raises(CourseError):
        cs.activate(4)  # beyond the finish
    cs.set_finish(None)
    assert cs.course.finish_idx is None
    cs.next()
    assert cs.course.active_idx == 4
    cs.set_finish(2)  # shortening behind the boat brings the active mark back to the finish
    assert cs.course.active_idx == 2
    with pytest.raises(CourseError):
        cs.set_finish(0)


def test_activate_and_confirm_sides(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.activate(3)
    assert active_id(cs) == "blitvenica"
    with pytest.raises(CourseError):
        cs.activate(0)
    assert cs.course.sides_confirmed is False
    v = cs.version
    cs.confirm_sides(base_version=v)
    assert cs.course.sides_confirmed is True and cs.version == v + 1


def test_select_after_edits_restores_the_template(tmp_path: Path) -> None:
    cs = CourseStore(tmp_path)
    cs.add_mark("Bouée", 43.68, 15.79)
    cs.delete_leg(3)
    cs.set_leg(1, side="port", radius_nm=1.0)
    cs.set_finish(2)
    api = cs.select("B")
    assert api["template"] == "B"
    assert [leg["mark_id"] for leg in api["seq"]] == [
        "vodice",
        "plic-sestre",
        "jabuka",
        "mulo",
        "vodice",
    ]
    assert api["seq"][1] == {"mark_id": "plic-sestre", "side": "port", "radius_nm": 0.3}
    assert api["finish_idx"] is None and api["active_idx"] == 1
    assert "m1" not in api["marks"]
    cs.add_mark("Encore", 43.68, 15.79)
    assert "m2" in cs.marks  # ids are never reused
