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


# -- rounding state machine -----------------------------------------------------------------------
# Course A, Plić Sestre active (radius 0.3 -> zone 0.55 nm), incoming leg Vodice -> Plić ~161 deg.
# From the mark: bearing 61 deg is in front of the abeam line, 81 deg is past it.
def at(bearing_deg: float, dist_nm: float, mark=PLIC) -> tuple[float, float]:
    return geo.offset(mark[0], mark[1], math.radians(bearing_deg), dist_nm)


def store(tmp_path: Path) -> tuple[CourseStore, list[dict]]:
    log: list[dict] = []
    cs = CourseStore(tmp_path, on_event=log.append, wall=lambda: 1_000_000.0)
    return cs, log


def run(cs: CourseStore, pos: tuple[float, float], t0: float, n: int) -> float:
    """n ticks, one per second, at a fixed position; returns the next t."""
    for k in range(n):
        cs.on_tick(pos[0], pos[1], t0 + k)
    return t0 + n


def test_abeam_in_zone_for_10_s_advances_with_banner(tmp_path: Path) -> None:
    cs, log = store(tmp_path)
    t = run(cs, at(341, 1.0), 0.0, 3)  # approaching
    t = run(cs, at(61, 0.4), t, 2)  # in the zone, not yet abeam
    assert cs.course.active_idx == 1
    t = run(cs, at(81, 0.4), t, 10)  # abeam from t=5 to t=14: 9 s held
    assert cs.course.active_idx == 1
    cs.on_tick(*at(81, 0.4), t)  # t=15: 10 s held
    assert cs.course.active_idx == 2
    banner = cs.status()["banner"]
    assert banner["text"] == "Marque suivante : Jabuka — Annuler"
    assert banner["undo_until_s"] == pytest.approx(t + 60.0)
    assert banner["token"] and banner["kind"] == "advance"
    adv = [e for e in log if e["type"] == "course_advance"]
    assert len(adv) == 1 and adv[0]["from_idx"] == 1 and adv[0]["to_idx"] == 2
    # persisted with the banner
    again = CourseStore(tmp_path)
    assert again.course.active_idx == 2 and again.course.banner.token == banner["token"]
    # the banner goes away after 60 s
    cs.on_tick(*at(200, 5.0, mark=(43.09153, 15.46054)), t + 61)
    assert cs.status()["banner"] is None


def test_nine_seconds_then_back_does_not_advance(tmp_path: Path) -> None:
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 10)  # 9 s of abeam
    t = run(cs, at(61, 0.4), t, 1)  # back in front of the abeam line
    t = run(cs, at(81, 0.4), t, 10)  # a fresh 9 s
    assert cs.course.active_idx == 1


def test_enter_then_leave_without_abeam_advances(tmp_path: Path) -> None:
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.5), 0.0, 3)
    t = run(cs, at(51, 0.8), t, 10)  # out of the zone, still in front of the abeam line
    assert cs.course.active_idx == 1
    cs.on_tick(*at(51, 0.8), t)
    assert cs.course.active_idx == 2


def test_nothing_fires_beyond_2_nm_or_without_entering(tmp_path: Path) -> None:
    cs, _ = store(tmp_path)
    run(cs, at(161, 2.5), 0.0, 30)  # abeam but never entered, beyond the gate
    run(cs, at(120, 1.5), 30.0, 30)  # abeam, inside the gate, never entered
    assert cs.course.active_idx == 1
    t = run(cs, at(61, 0.4), 60.0, 2)  # entered
    run(cs, at(161, 2.5), t, 30)  # then beyond 2 nm: nothing
    assert cs.course.active_idx == 1


def test_start_index_never_auto_advances(tmp_path: Path) -> None:
    cs, log = store(tmp_path)
    cs.course = cs.course.model_copy(update={"active_idx": 0})
    vodice = (cs.marks["vodice"].lat, cs.marks["vodice"].lon)
    run(cs, at(90, 0.1, mark=vodice), 0.0, 5)
    run(cs, at(161, 0.5, mark=vodice), 5.0, 30)
    assert cs.course.active_idx == 0 and log == []


def test_undo_restores_and_suppresses_until_exit(tmp_path: Path) -> None:
    cs, log = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 11)
    assert cs.course.active_idx == 2
    token = cs.status()["banner"]["token"]
    from jabuka.nav.course import BannerGone

    with pytest.raises(BannerGone):
        cs.undo("wrong", t)
    cs.undo(token, t + 5)
    assert cs.course.active_idx == 1 and cs.status()["banner"] is None
    assert [e["type"] for e in log][-1] == "course_undo"
    with pytest.raises(BannerGone):
        cs.undo(token, t + 6)  # only once
    t = run(cs, at(81, 0.4), t + 6, 30)  # still abeam in the zone: suppressed
    assert cs.course.active_idx == 1
    t = run(cs, at(81, 0.8), t, 1)  # leaves the zone: suppression lifted, state reset
    assert cs.course.suppress_idx is None
    t = run(cs, at(81, 0.8), t, 15)  # outside without a fresh entry: nothing
    assert cs.course.active_idx == 1
    t = run(cs, at(81, 0.4), t, 11)  # entered again and abeam 10 s: fires again
    assert cs.course.active_idx == 2


def test_undo_after_60_s_is_gone(tmp_path: Path) -> None:
    from jabuka.nav.course import BannerGone

    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 11)
    token = cs.status()["banner"]["token"]
    with pytest.raises(BannerGone):
        cs.undo(token, t + 61)
    assert cs.course.active_idx == 2


def test_manual_step_clears_banner_and_pending(tmp_path: Path) -> None:
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 11)
    assert cs.status()["banner"] is not None
    cs.prev()
    assert cs.course.active_idx == 1 and cs.status()["banner"] is None
    cs.activate(1)
    t = run(cs, at(81, 0.4), t, 6)  # a pending candidate...
    cs.next()
    cs.prev()  # ...is forgotten by a manual step
    t = run(cs, at(81, 0.4), t, 6)
    assert cs.course.active_idx == 1
    t = run(cs, at(81, 0.4), t, 5)
    assert cs.course.active_idx == 2


def test_finish_on_entering_its_radius(tmp_path: Path) -> None:
    cs, log = store(tmp_path)
    cs.activate(4)  # Vodice finish, radius 0.15
    vodice = (cs.marks["vodice"].lat, cs.marks["vodice"].lon)
    run(cs, at(160, 0.3, mark=vodice), 0.0, 20)
    assert cs.course.finished is False
    cs.on_tick(*at(160, 0.1, mark=vodice), 20.0)
    assert cs.course.finished is True
    st = cs.status()
    assert st["finished"] is True
    assert st["banner"]["text"] == "ARRIVÉE — Vodice" and st["banner"]["undo_until_s"] is None
    assert cs.active_target() is None
    run(cs, at(160, 0.1, mark=vodice), 21.0, 20)
    assert cs.course.active_idx == 4
    assert log[-1]["action"] == "finish"


def test_finish_here_finishes_at_the_checkpoint(tmp_path: Path) -> None:
    cs, _ = store(tmp_path)
    cs.set_finish(3)
    cs.activate(3)  # Blitvenica, radius 0.55
    blit = (cs.marks["blitvenica"].lat, cs.marks["blitvenica"].lon)
    cs.on_tick(*at(0, 0.5, mark=blit), 0.0)
    assert cs.course.finished is True and cs.status()["banner"]["text"] == "ARRIVÉE — Blitvenica"
    cs.set_finish(None)  # undoing the shorten resumes the course
    assert cs.course.finished is False and cs.active_target().mark.id == "blitvenica"


def test_hairpin_jabuka_advances_when_abeam(tmp_path: Path) -> None:
    """Course A Jabuka: in 203 deg, out 009 deg, starboard rounding. The boat sails down the
    incoming leg past the island on its anchor line; the advance fires ~10 s after abeam (early
    but safe: the laylines then point to Blitvenica)."""
    cs, _ = store(tmp_path)
    cs.activate(2)
    t_ = cs.active_target()
    assert math.degrees(t_.leg_bearing) == pytest.approx(203, abs=1.5)
    jab = (t_.mark.lat, t_.mark.lon)
    u = t_.leg_bearing
    speed = 7.0 / 3600.0  # nm per second
    fired_at = None
    for k in range(-400, 200):
        s = k * speed  # along-track distance past abeam
        lat, lon = geo.offset(t_.anchor_lat, t_.anchor_lon, u, s)
        cs.on_tick(lat, lon, 1000.0 + k)
        if cs.course.active_idx == 3:
            fired_at = k
            break
    assert fired_at is not None and 10 <= fired_at <= 11
    assert geo.bearing_distance(lat, lon, *jab)[1] < 0.7
    assert cs.active_target().mark.id == "blitvenica"
