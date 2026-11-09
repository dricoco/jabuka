"""CourseStore editing operations (CRSE-01/02/04) and the rounding state machine (CRSE-03)."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable
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


def test_add_mark_before_the_active_finish_becomes_active(tmp_path: Path) -> None:
    """IN-03: on the final leg, "À la fin" inserts before the finish (insert_at = last index):
    the late committee mark is the next to round, not silently listed as done."""
    cs = CourseStore(tmp_path)
    cs.activate(4)  # Vodice finish active
    cs.add_mark("Comité", 43.70, 15.79, insert_at=4)
    assert ids(cs) == ["vodice", "plic-sestre", "jabuka", "blitvenica", "m1", "vodice"]
    assert cs.course.active_idx == 4 and active_id(cs) == "m1"
    # with "Finir ici" at Blitvenica (active), the same: the new mark comes before the finish
    cs2 = CourseStore(tmp_path / "b")
    cs2.set_finish(3)
    cs2.activate(3)
    cs2.add_mark("Comité", 43.70, 15.79, insert_at=3)
    assert active_id(cs2) == "m1" and cs2.course.finish_idx == 4
    assert cs2.course.seq[cs2.course.finish_idx].mark_id == "blitvenica"


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


def test_reselecting_the_template_in_use_is_a_no_op(tmp_path: Path) -> None:
    """WR-05: tapping the highlighted "Parcours A" mid-race keeps the race progress and the
    briefing's leg edits."""
    cs = CourseStore(tmp_path)
    cs.set_leg(2, side="port", radius_nm=1.0)
    cs.activate(3)  # past Jabuka
    v = cs.version
    api = cs.select("A", base_version=v)
    assert api["version"] == v and api["active_idx"] == 3
    assert cs.course.seq[2].side == "port" and cs.course.seq[2].radius_nm == 1.0
    with pytest.raises(VersionConflict):
        cs.select("A", base_version=v - 1)


def test_template_switch_keeps_the_active_mark_when_shared(tmp_path: Path) -> None:
    """A <-> B share Vodice, Plić Sestre and Jabuka: a template correction on the way to Jabuka
    keeps Jabuka active; past it (Blitvenica vs Mulo) the new course starts at its first mark."""
    cs = CourseStore(tmp_path)
    cs.activate(2)  # Jabuka
    cs.select("B")
    assert cs.course.active_idx == 2 and active_id(cs) == "jabuka"
    cs.activate(3)  # Mulo
    cs.select("A")
    assert cs.course.active_idx == 1 and active_id(cs) == "plic-sestre"


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


def test_leaving_the_zone_past_the_mark_advances(tmp_path: Path) -> None:
    """G-4-R02: the zone is left on the far side of the mark (past it along the incoming leg):
    the 10 s debounce then advances."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.5), 0.0, 3)
    t = run(cs, at(120, 0.8), t, 10)  # out of the zone, past the mark
    assert cs.course.active_idx == 1
    cs.on_tick(*at(120, 0.8), t)
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
    # CR-02: leaving the zone the boat was suppressed in is the real rounding: it is kept as
    # evidence (the boat never comes back), the 10 s "left the zone" debounce then advances
    t = run(cs, at(81, 0.8), t, 1)  # leaves the zone: suppression lifted
    assert cs.course.suppress_idx is None and cs.course.active_idx == 1
    t = run(cs, at(81, 0.8), t, 9)  # 9 s outside: not yet
    assert cs.course.active_idx == 1
    t = run(cs, at(81, 0.8), t, 1)  # 10 s held outside: advances
    assert cs.course.active_idx == 2
    adv = [e for e in log if e["type"] == "course_advance"]
    assert len(adv) == 2 and adv[-1]["from_idx"] == 1


def test_undo_outside_the_zone_needs_a_fresh_entry(tmp_path: Path) -> None:
    """An advance fired by a zone exit, then Annuler tapped outside the zone: the suppression
    lifts at once and nothing re-fires until the boat enters the zone again (no banner loop)."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.5), 0.0, 3)
    t = run(cs, at(120, 0.8), t, 11)  # left the zone past the mark: advanced
    assert cs.course.active_idx == 2
    cs.undo(cs.status()["banner"]["token"], t)
    t = run(cs, at(120, 0.8), t, 30)  # still outside: nothing
    assert cs.course.active_idx == 1 and cs.course.suppress_idx is None
    t = run(cs, at(61, 0.4), t, 2)  # entered again
    t = run(cs, at(120, 0.8), t, 11)  # and left past the mark: fires again
    assert cs.course.active_idx == 2


def test_hairpin_annuler_then_real_rounding_advances(tmp_path: Path) -> None:
    """CR-02 scenario: Jabuka (Course A) advances early (the far-side wedge fires _abeam while
    the boat is still inside the zone), the helmsman taps Annuler, finishes the rounding inside
    the zone and heads north: the exit advances to Blitvenica."""
    cs, _ = store(tmp_path)
    cs.activate(2)
    jab = (cs.marks["jabuka"].lat, cs.marks["jabuka"].lon)
    t = run(cs, at(23, 0.7, mark=jab), 0.0, 3)  # approaching from the NNE, in the zone
    t = run(cs, at(203, 0.6, mark=jab), t, 3)  # south of the island
    t = run(cs, at(285, 0.6, mark=jab), t, 11)  # the far-side wedge: _abeam
    assert cs.course.active_idx == 3
    cs.undo(cs.status()["banner"]["token"], t)
    assert cs.course.active_idx == 2
    t = run(cs, at(300, 0.7, mark=jab), t, 10)  # still in the zone: suppressed
    assert cs.course.active_idx == 2
    t = run(cs, at(9, 1.2, mark=jab), t, 11)  # heading north out of the zone
    assert cs.course.active_idx == 3 and active_id(cs) == "blitvenica"


def test_gps_gap_restarts_the_rounding_debounce(tmp_path: Path) -> None:
    """IN-05: 5 s of abeam evidence, a 30 s GPS outage, then one fix: no advance on that single
    sample; the 10 s must hold again from the first fix after the gap."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 5)  # abeam from t=2 to t=6
    for k in range(30):  # no position (stale GPS): the state machine does not run
        cs.on_tick(None, None, t + k)
    t += 30
    t = run(cs, at(81, 0.4), t, 10)  # back: 9 s of fresh evidence
    assert cs.course.active_idx == 1
    cs.on_tick(*at(81, 0.4), t)  # 10 s held after the gap
    assert cs.course.active_idx == 2


def test_large_radius_zone_exit_still_advances(tmp_path: Path) -> None:
    """IN-07: radius 2 nm -> zone 2.25 nm, past the 2 nm gate: leaving the zone past the mark
    still counts, the gate follows the zone. G-4-R02: leaving it on the approach side does not."""
    (tmp_path / "past").mkdir()
    cs, _ = store(tmp_path / "past")
    cs.set_leg(1, radius_nm=2.0)
    t = run(cs, at(61, 2.1), 0.0, 3)  # inside the 2.25 nm zone, in front of the abeam line
    t = run(cs, at(120, 2.4), t, 10)  # left the zone past the mark
    assert cs.course.active_idx == 1
    cs.on_tick(*at(120, 2.4), t)
    assert cs.course.active_idx == 2
    (tmp_path / "approach").mkdir()
    cs, _ = store(tmp_path / "approach")
    cs.set_leg(1, radius_nm=2.0)
    t = run(cs, at(61, 2.1), 0.0, 3)
    t = run(cs, at(51, 2.4), t, 30)  # left the zone on the approach side
    assert cs.course.active_idx == 1


def test_write_failure_alert_clears_after_a_successful_write(tmp_path: Path, monkeypatch) -> None:
    """IN-07: one transient disk failure during the tick must not show "Écriture du parcours
    impossible" for the rest of the race."""
    import jabuka.nav.course as course_mod

    cs, _ = store(tmp_path)
    real = course_mod.atomic_write_json

    def full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(course_mod, "atomic_write_json", full)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 11)  # advance applied in memory, write failed
    assert cs.course.active_idx == 2 and cs.alerts == ["Écriture du parcours impossible"]
    monkeypatch.setattr(course_mod, "atomic_write_json", real)
    cs.confirm_sides()
    assert cs.alerts == []


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


def _rounding_track(t_, out_deg: float, speed: float):
    """Positions, one per second, of a boat sailing down the incoming anchor line to abeam, then
    round the mark at its radius on the leg's side, then out along out_deg. Yields
    (lat, lon, phase, bearing from the mark in deg)."""
    m = (t_.mark.lat, t_.mark.lon)
    in_deg = math.degrees(t_.leg_bearing)
    sgn = 1.0 if t_.side == "stbd" else -1.0  # stbd: clockwise (bearing increases)
    for k in range(-400, 1):
        lat, lon = geo.offset(t_.anchor_lat, t_.anchor_lon, t_.leg_bearing, k * speed)
        yield lat, lon, "approach", math.degrees(geo.bearing_distance(*m, lat, lon)[0])
    b0 = in_deg - sgn * 90.0
    b1 = out_deg - sgn * 90.0
    sweep = ((b1 - b0) * sgn) % 360.0
    step = math.degrees(speed / t_.radius_nm)
    for k in range(1, int(sweep / step) + 1):
        b = b0 + sgn * k * step
        lat, lon = geo.offset(*m, math.radians(b), t_.radius_nm)
        yield lat, lon, "arc", b % 360.0
    start = geo.offset(*m, math.radians(b1), t_.radius_nm)
    for k in range(1, 600):
        lat, lon = geo.offset(*start, math.radians(out_deg), k * speed)
        yield lat, lon, "out", math.degrees(geo.bearing_distance(*m, lat, lon)[0])


@pytest.mark.parametrize(("template", "next_id"), [("A", "blitvenica"), ("B", "mulo")])
def test_hairpin_jabuka_advances_only_once_rounded(
    tmp_path: Path, template: str, next_id: str
) -> None:
    """WR-01: Jabuka is a hairpin (in 203 deg, out 009 deg starboard in A, 038 deg port in B).
    Abeam of the incoming leg is half a lap before the island is rounded: no advance on the
    approach side or during the rounding, only once the boat is on the far side (out along the
    next leg)."""
    cs, _ = store(tmp_path)
    if template == "B":
        cs.select("B")
    cs.activate(2)
    t_ = cs.active_target()
    assert math.degrees(t_.leg_bearing) == pytest.approx(203, abs=1.5)
    nxt = cs.marks[next_id]
    out_deg = math.degrees(geo.bearing_distance(t_.mark.lat, t_.mark.lon, nxt.lat, nxt.lon)[0])
    speed = 7.0 / 3600.0  # nm per second
    fired = None
    for k, (lat, lon, phase, b) in enumerate(_rounding_track(t_, out_deg, speed)):
        cs.on_tick(lat, lon, 1000.0 + k)
        if cs.course.active_idx == 3:
            fired = (phase, b, geo.bearing_distance(lat, lon, t_.mark.lat, t_.mark.lon)[1])
            break
    assert fired is not None
    phase, b, d = fired
    assert phase == "out", fired  # not abeam on the approach, not mid-rounding
    # on the far side: past the mark along the outgoing leg, still close to the island
    off = math.degrees(math.remainder(math.radians(b - out_deg), 2 * math.pi))
    assert abs(off) < 90.0 and d < 1.0, fired
    assert cs.active_target().mark.id == next_id


def test_gentle_turn_still_advances_when_abeam(tmp_path: Path) -> None:
    """Below 90 deg of course change (Plić Sestre: in ~161, out ~203 deg) abeam alone fires."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 11)
    assert cs.course.active_idx == 2


# -- a zone exit counts only past the mark (G-4-R02) ----------------------------------------------
def test_leaving_the_zone_on_the_approach_side_never_advances(tmp_path: Path) -> None:
    """Review repro (04-PROJECT-REVIEW R02): approach Plić Sestre from the NNW into its zone,
    then retreat on the same side (a tack away) and stay outside for 30 s: still on Plić, no
    course_advance event."""
    for name, track in (
        ("nnw", [(at(341, 1.0), 3), (at(341, 0.45), 5), (at(341, 0.8), 30)]),
        ("ene", [(at(61, 0.5), 3), (at(51, 0.8), 30)]),
    ):
        (tmp_path / name).mkdir()
        cs, log = store(tmp_path / name)
        t = 0.0
        for pos, n in track:
            t = run(cs, pos, t, n)
        assert cs.course.active_idx == 1, name
        assert [e for e in log if e["type"] == "course_advance"] == [], name


@pytest.mark.parametrize("template", ["A", "B"])
def test_hairpin_approach_side_retreat_never_advances(tmp_path: Path, template: str) -> None:
    """Jabuka entered from the NNE (approach side), then left to the north and wide to the east
    without ever getting past the island: Jabuka stays active in both courses."""
    cs, log = store(tmp_path)
    if template == "B":
        cs.select("B")
    cs.activate(2)
    jab = (cs.marks["jabuka"].lat, cs.marks["jabuka"].lon)
    t = run(cs, at(23, 0.7, mark=jab), 0.0, 3)  # in the zone, approach side
    t = run(cs, at(23, 1.2, mark=jab), t, 30)  # back out to the NNE
    t = run(cs, at(113, 0.9, mark=jab), t, 30)  # wide on the east side, out of the zone
    assert cs.course.active_idx == 2
    assert [e for e in log if e["type"] == "course_advance"] == []


def test_hairpin_wide_swing_then_rounding_advances(tmp_path: Path) -> None:
    """Course A: a wide swing east out of Jabuka's zone on the approach side no longer advances
    early; the real rounding (south of the island, then out north) does."""
    cs, _ = store(tmp_path)
    cs.activate(2)
    jab = (cs.marks["jabuka"].lat, cs.marks["jabuka"].lon)
    t = run(cs, at(23, 0.7, mark=jab), 0.0, 3)  # approaching from the NNE, in the zone
    t = run(cs, at(113, 0.9, mark=jab), t, 11)  # wide on the east side, out of the zone
    assert cs.course.active_idx == 2  # no early advance any more
    t = run(cs, at(150, 0.6, mark=jab), t, 2)  # back in the zone
    t = run(cs, at(203, 0.6, mark=jab), t, 20)  # rounding south of the island
    t = run(cs, at(300, 0.7, mark=jab), t, 5)
    assert cs.course.active_idx == 2
    t = run(cs, at(9, 1.2, mark=jab), t, 11)  # heading north out of the zone
    assert cs.course.active_idx == 3 and active_id(cs) == "blitvenica"


def test_hairpin_course_b_rounding_advances(tmp_path: Path) -> None:
    """Course B: Jabuka rounded to port (in 203 deg, out 038 deg), then out along the next leg:
    advances to Mulo."""
    cs, _ = store(tmp_path)
    cs.select("B")
    cs.activate(2)
    jab = (cs.marks["jabuka"].lat, cs.marks["jabuka"].lon)
    t = run(cs, at(23, 0.7, mark=jab), 0.0, 3)  # approaching, in the zone
    t = run(cs, at(203, 0.6, mark=jab), t, 5)  # south of the island
    t = run(cs, at(120, 0.7, mark=jab), t, 5)  # coming round the east side
    t = run(cs, at(38, 1.2, mark=jab), t, 11)  # out along the next leg
    assert cs.course.active_idx == 3 and active_id(cs) == "mulo"


# -- a real rounding always advances; the latch follows the geometry (CR-01, WR-01) ---------------
def _committee(cs: CourseStore, turn: float) -> tuple[tuple[float, float], float]:
    """A committee mark "Comité" (add_mark defaults: radius 0.05, side none) 3 nm short of Plić
    on the Vodice -> Plić line, then a next mark "N" 3 nm away at a course change of `turn` deg;
    the committee mark is active. Returns (its position, incoming bearing in deg)."""
    vod = cs.marks["vodice"]
    b, _ = geo.bearing_distance(vod.lat, vod.lon, PLIC[0], PLIC[1])
    b_in = math.degrees(b)
    mark = geo.offset(PLIC[0], PLIC[1], math.radians(b_in + 180), 3.0)
    cs.add_mark("Comité", mark[0], mark[1], insert_at=1)
    nxt = geo.offset(mark[0], mark[1], math.radians(b_in + turn), 3.0)
    cs.add_mark("N", nxt[0], nxt[1], insert_at=2)
    cs.activate(1)
    return mark, b_in


def _round(
    cs: CourseStore,
    buoy: tuple[float, float],
    b_in: float,
    heading_change: float,
    r: float,
    kn: float = 7.0,
) -> int | None:
    """Sail 1.5 nm along the incoming leg (b_in deg) to the real buoy, round it at r nm with a
    heading change of heading_change deg (+ right), then sail 1.5 nm out; one tick per second.
    Returns the out-tick k at which the course moved on (0: during the arc), or None."""
    v = kn / 3600.0
    sgn = 1.0 if heading_change > 0 else -1.0
    idx0 = cs.course.active_idx
    n = int(1.5 / v)
    t = 0.0
    for k in range(-n, 1):
        p = geo.offset(
            *geo.offset(*buoy, math.radians(b_in), k * v), math.radians(b_in - 90 * sgn), r
        )
        cs.on_tick(p[0], p[1], t)
        t += 1.0
    assert cs.course.active_idx == idx0, "advanced during the approach"
    steps = max(1, int(abs(math.radians(heading_change)) * r / v))
    last = buoy
    for k in range(1, steps + 1):
        last = geo.offset(*buoy, math.radians(b_in - 90 * sgn + heading_change * k / steps), r)
        cs.on_tick(last[0], last[1], t)
        t += 1.0
    found = 0 if cs.course.active_idx != idx0 else None
    for k in range(1, n + 1):
        q = geo.offset(*last, math.radians(b_in + heading_change), k * v)
        cs.on_tick(q[0], q[1], t)
        t += 1.0
        if found is None and cs.course.active_idx != idx0:
            found = k
    return found


def _advances(log: list[dict]) -> list[dict]:
    return [e for e in log if e["type"] == "course_advance"]


@pytest.mark.parametrize("err_nm", [0.011, 0.02, 0.03, 0.05, 0.09])
@pytest.mark.parametrize("turn,tack", [(45, 50), (60, 45), (75, 45), (90, 0), (90, 45)])
def test_committee_mark_entered_beyond_the_buoy_advances(
    tmp_path: Path, turn: float, tack: float, err_nm: float
) -> None:
    """CR-01: a committee mark entered up to about 0.1 nm (MARK_TOL_NM) beyond the real buoy
    along the incoming leg is never passed; rounding the buoy at 0.01 nm and leaving on a beat
    still advances, once. 0.09 nm pins the claimed coverage bound."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, turn)
    buoy = geo.offset(*mark, math.radians(b_in + 180), err_nm)
    k = _round(cs, buoy, b_in, turn + tack, 0.01)
    assert k is not None and k < 300
    assert len(_advances(log)) == 1


@pytest.mark.parametrize("turn,tack,err_nm", [(45, 50, 0.2), (90, 45, 0.2), (150, 0, 0.05)])
def test_committee_mark_beyond_the_bound_needs_a_manual_next(
    tmp_path: Path, turn: float, tack: float, err_nm: float
) -> None:
    """Accepted residuals R2 (a normal mark entered so far beyond the buoy that the boat never
    comes within radius + MARK_TOL_NM) and R3 (a hairpin mark entered beyond the buoy): no
    auto-advance; the Carte « Suiv. » button (CourseStore.next()) moves on."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, turn)
    buoy = geo.offset(*mark, math.radians(b_in + 180), err_nm)
    k = _round(cs, buoy, b_in, turn + tack, 0.01)
    assert k is None
    assert cs.course.active_idx == 1
    assert _advances(log) == []
    cs.next()
    assert cs.course.active_idx == 2


@pytest.mark.parametrize(
    "turn,tack,r,kn",
    [
        (60, 45, 0.005, 7),
        (75, 50, 0.005, 7),
        (85, 45, 0.005, 7),
        (89, 50, 0.005, 7),
        (70, 50, 0.008, 9),
        (85, 50, 0.008, 9),
    ],
)
def test_tight_rounding_then_a_beat_out_advances(
    tmp_path: Path, turn: float, tack: float, r: float, kn: float
) -> None:
    """CR-01: a rounding at a few boat lengths spends less than 10 s past the abeam line, then
    the beat out leaves the zone with dot_in < 0: it advances on the zone exit."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, turn)
    k = _round(cs, mark, b_in, turn + tack, r, kn)
    assert k is not None and k < 300
    assert len(_advances(log)) == 1


def test_inside_of_the_turn_retreat_never_advances(tmp_path: Path) -> None:
    """G-4-R02 on the inside of the turn (dot_out > 0, dot_in < 0) without ever coming within
    the leg radius + MARK_TOL_NM: Plić from 0.45 nm out to 255/270/290 deg, and a committee mark
    from 0.2 nm (turn 45, 60, 90). Never advances."""
    for b in (255, 270, 290):
        (tmp_path / f"plic{b}").mkdir()
        cs, log = store(tmp_path / f"plic{b}")
        t = run(cs, at(341, 1.0), 0.0, 3)
        t = run(cs, at(341, 0.45), t, 5)
        t = run(cs, at(b, 0.8), t, 30)
        assert cs.course.active_idx == 1, b
        assert _advances(log) == [], b
    for turn in (45, 60, 90):
        (tmp_path / f"comite{turn}").mkdir()
        cs, log = store(tmp_path / f"comite{turn}")
        m, b_in = _committee(cs, turn)
        t = run(cs, at(b_in + 180, 0.5, m), 0.0, 3)
        t = run(cs, at(b_in + 180, 0.2, m), t, 5)  # in the 0.3 nm zone, never within 0.15 nm
        t = run(cs, at(b_in + 90 + turn / 2, 0.5, m), t, 30)
        assert cs.course.active_idx == 1, turn
        assert _advances(log) == [], turn


@pytest.mark.parametrize("turn", [45, 60, 90])
def test_inside_of_the_turn_exit_after_coming_near_advances(tmp_path: Path, turn: float) -> None:
    """Accepted residual R1: within radius + MARK_TOL_NM on the approach side, then out on the
    inside of the turn, is the track of a mark entered up to 0.1 nm off: it advances after the
    10 s debounce."""
    cs, _ = store(tmp_path)
    m, b_in = _committee(cs, turn)
    t = run(cs, at(b_in + 180, 0.5, m), 0.0, 3)
    t = run(cs, at(b_in + 180, 0.1, m), t, 5)  # within 0.05 + 0.1
    t = run(cs, at(b_in + 90 + turn / 2, 0.5, m), t, 10)
    assert cs.course.active_idx == 1
    t = run(cs, at(b_in + 90 + turn / 2, 0.5, m), t, 1)
    assert cs.course.active_idx == 2


def test_moving_the_active_hairpin_mark_needs_the_corrected_mark_rounded(tmp_path: Path) -> None:
    """WR-01: Jabuka moved 1.5 nm south after the incoming-leg latch. Outside the corrected
    zone on its approach side nothing happens; rounding the corrected mark advances."""
    cs, log = store(tmp_path)
    cs.activate(2)
    jab = (cs.marks["jabuka"].lat, cs.marks["jabuka"].lon)
    t = run(cs, at(23, 0.7, mark=jab), 0.0, 3)
    t = run(cs, at(203, 0.6, mark=jab), t, 3)  # past along the incoming leg: the latch
    new = at(203, 1.5, mark=jab)
    cs.edit_mark("jabuka", lat=new[0], lon=new[1])
    t = run(cs, at(203, 0.6, mark=jab), t, 30)  # 0.9 nm on the approach side of the new mark
    assert cs.course.active_idx == 2
    assert _advances(log) == []
    t = run(cs, at(23, 0.7, mark=new), t, 3)
    t = run(cs, at(203, 0.6, mark=new), t, 5)
    t = run(cs, at(300, 0.7, mark=new), t, 5)
    t = run(cs, at(9, 1.2, mark=new), t, 11)
    assert cs.course.active_idx == 3 and active_id(cs) == "blitvenica"


def test_moving_the_active_mark_after_a_brief_abeam_needs_the_corrected_mark(
    tmp_path: Path,
) -> None:
    """WR-01: Plić moved 1 nm along the incoming leg after 5 s abeam: the old latch must not
    advance on the next zone exit; the corrected mark advances once passed."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 5)  # latch, no advance
    new = at(161, 1.0)
    cs.edit_mark("plic-sestre", lat=new[0], lon=new[1])
    t = run(cs, at(81, 0.4), t, 30)
    assert cs.course.active_idx == 1
    t = run(cs, at(61, 0.4, mark=new), t, 2)
    t = run(cs, at(81, 0.4, mark=new), t, 11)
    assert cs.course.active_idx == 2


def test_shrinking_the_radius_drops_the_near_latch(tmp_path: Path) -> None:
    """WR-01: "near" measured against a 1.0 nm radius is not valid for 0.3 nm."""
    cs, _ = store(tmp_path)
    cs.set_leg(1, radius_nm=1.0)
    t = run(cs, at(341, 1.0), 0.0, 5)  # entered, within 1.0 + 0.1
    cs.set_leg(1, radius_nm=0.3)
    t = run(cs, at(270, 0.8), t, 30)
    assert cs.course.active_idx == 1


def _geometry_edit(cs: CourseStore, kind: str) -> None:
    if kind == "active_moved":
        cs.edit_mark("plic-sestre", lat=at(250, 0.02)[0], lon=at(250, 0.02)[1])
    elif kind == "side":
        cs.set_leg(1, side="port")
    elif kind == "radius":
        cs.set_leg(1, radius_nm=0.35)
    elif kind in ("next_moved", "previous_moved"):
        mid = "jabuka" if kind == "next_moved" else "vodice"
        m = (cs.marks[mid].lat, cs.marks[mid].lon)
        p = at(90, 0.05, mark=m)
        cs.edit_mark(mid, lat=p[0], lon=p[1])
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["active_moved", "side", "radius", "next_moved", "previous_moved"])
def test_a_geometry_edit_restarts_the_rounding_debounce(tmp_path: Path, kind: str) -> None:
    """WR-01: a pending abeam candidate needs 10 fresh seconds after any geometry edit."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 6)  # pending candidate, 5 s held
    _geometry_edit(cs, kind)
    t = run(cs, at(81, 0.4), t, 6)
    assert cs.course.active_idx == 1
    t = run(cs, at(81, 0.4), t, 5)
    assert cs.course.active_idx == 2


def test_a_rename_keeps_the_rounding_debounce(tmp_path: Path) -> None:
    """A rename changes no geometry: the pending candidate keeps its 10 s."""
    cs, _ = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 6)
    cs.edit_mark("plic-sestre", name="Plić")
    t = run(cs, at(81, 0.4), t, 5)
    assert cs.course.active_idx == 2


# -- an outgoing edit after the rounding keeps the evidence (CR-01 of review 93cb8b3) -------------
NUDGE_NM = 0.00054  # about 1 m


def _round_edit(
    cs: CourseStore,
    buoy: tuple[float, float],
    mark: tuple[float, float],
    b_in: float,
    heading_change: float,
    r: float,
    edit: Callable[[CourseStore], None],
    *,
    kn: float = 7.0,
    edit_at_nm: float = 0.2,
    noise_m: float = 0.0,
    seed: int = 0,
    steer_to: Callable[[CourseStore], tuple[float, float]] | None = None,
) -> int | None:
    """Like _round, with a crew edit on the way out: on the first out tick at least edit_at_nm
    from the entered mark (still inside the 0.3 nm committee zone), edit(cs) runs once; then the
    boat steers straight to steer_to(cs), or holds its heading. noise_m: each fix is offset by a
    random direction, then abs(gauss(0, noise_m)) metres (seeded). Returns the out-tick k of the
    advance, or None."""
    rng = random.Random(seed)
    v = kn / 3600.0
    sgn = 1.0 if heading_change > 0 else -1.0
    idx0 = cs.course.active_idx
    n = int(1.5 / v)
    t = 0.0

    def tick(p: tuple[float, float]) -> None:
        nonlocal t
        q = p
        if noise_m:
            q = geo.offset(*p, rng.uniform(0, 2 * math.pi), abs(rng.gauss(0, noise_m)) / 1852.0)
        cs.on_tick(q[0], q[1], t)
        t += 1.0

    for k in range(-n, 1):
        tick(
            geo.offset(
                *geo.offset(*buoy, math.radians(b_in), k * v), math.radians(b_in - 90 * sgn), r
            )
        )
    assert cs.course.active_idx == idx0, "advanced during the approach"
    steps = max(1, int(abs(math.radians(heading_change)) * r / v))
    p = buoy
    for k in range(1, steps + 1):
        p = geo.offset(*buoy, math.radians(b_in - 90 * sgn + heading_change * k / steps), r)
        tick(p)
    found = 0 if cs.course.active_idx != idx0 else None
    edited = False
    target = None
    for k in range(1, n + 1):
        if not edited and geo.bearing_distance(*p, *mark)[1] >= edit_at_nm:
            assert found is None, "advanced before the edit"
            edit(cs)
            edited = True
            target = steer_to(cs) if steer_to is not None else None
        b = math.radians(b_in + heading_change)
        if target is not None:
            b, _ = geo.bearing_distance(*p, *target)
        p = geo.offset(*p, b, v)
        tick(p)
        if found is None and cs.course.active_idx != idx0:
            found = k
    assert edited, "the edit never ran"
    return found


def _after_next(cs: CourseStore, mark: tuple[float, float], b_in: float, turn: float) -> None:
    """A 4th leg "N2" right after "N", at a course change of turn - 10 deg from the active mark,
    so that deleting "N" leaves a usable next leg (the delete_next edit)."""
    q = geo.offset(*mark, math.radians(b_in + turn - 10), 3.0)
    cs.add_mark("N2", q[0], q[1], insert_at=3)


def _outgoing_edit(
    kind: str, mark: tuple[float, float], b_in: float, turn: float
) -> Callable[[CourseStore], None]:
    """An edit of the outgoing leg of the active committee mark (the next mark is "N" of
    _committee). Every new turn stays at 90 deg or less: an edit that turns the mark into a
    hairpin is residual R3, pinned separately."""

    def edit(cs: CourseStore) -> None:
        nid = cs.course.seq[2].mark_id
        if kind == "nudge_next":
            n = cs.marks[nid]
            q = geo.offset(n.lat, n.lon, 0.0, NUDGE_NM)
            cs.edit_mark(nid, lat=q[0], lon=q[1])
        elif kind == "move_next":
            q = geo.offset(*mark, math.radians(b_in + turn - 10), 3.0)
            cs.edit_mark(nid, lat=q[0], lon=q[1])
        elif kind == "add_default":  # no insert_at: the default position, active_idx + 1
            q = geo.offset(*mark, math.radians(b_in + turn - 10), 2.0)
            cs.add_mark("Nouvelle", q[0], q[1])
        elif kind == "side":
            cs.set_leg(1, side="port")
        elif kind == "delete_next":  # "N2" (_after_next) becomes the next mark
            cs.delete_leg(2)
        else:
            raise AssertionError(kind)

    return edit


# (turn, tack, r, kn, err_nm): an exact mark rounded at 0.01 nm advances by the abeam rule before
# the edit, so it is left out on purpose
OUTGOING_EDIT_CASES = [
    *[(75, 45, 0.005, 7.0, e) for e in (0.0, 0.011, 0.05, 0.09)],
    *[(89, 50, 0.008, 9.0, e) for e in (0.0, 0.011, 0.05, 0.09)],
    *[(60, 45, 0.01, 7.0, e) for e in (0.011, 0.05, 0.09)],
    *[(45, 50, 0.01, 7.0, e) for e in (0.011, 0.05, 0.09)],
]


@pytest.mark.parametrize("noise_m", [0.0, 3.0])
@pytest.mark.parametrize("kind", ["nudge_next", "move_next", "add_default", "side", "delete_next"])
@pytest.mark.parametrize("turn,tack,r,kn,err_nm", OUTGOING_EDIT_CASES)
def test_an_outgoing_edit_in_the_zone_after_the_rounding_still_advances(
    tmp_path: Path,
    turn: float,
    tack: float,
    r: float,
    kn: float,
    err_nm: float,
    kind: str,
    noise_m: float,
) -> None:
    """CR-01 (review 93cb8b3): moving the next mark (1 m or 10 deg further in), adding a mark at
    the default position, deleting the next mark or changing the side while still in the zone
    after the rounding keeps the rounding evidence and restarts only the 10 s debounce: the
    course advances once."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, turn)
    if kind == "delete_next":
        _after_next(cs, mark, b_in, turn)
    buoy = geo.offset(*mark, math.radians(b_in + 180), err_nm)
    k = _round_edit(
        cs,
        buoy,
        mark,
        b_in,
        turn + tack,
        r,
        _outgoing_edit(kind, mark, b_in, turn),
        kn=kn,
        noise_m=noise_m,
    )
    assert k is not None and k < 300
    assert len(_advances(log)) == 1


def test_an_edit_that_makes_an_off_buoy_mark_a_hairpin_needs_a_manual_next(
    tmp_path: Path,
) -> None:
    """Accepted residual R3 by edit (plan 04-14): a mark entered 0.05 nm off the buoy, and a new
    next mark added at the default position turns it into a hairpin (95 deg). The hairpin rule
    needs the latch, which an off-buoy mark never gets: the crew uses « Suiv. »."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, 85)
    buoy = geo.offset(*mark, math.radians(b_in + 180), 0.05)

    def edit(c: CourseStore) -> None:
        q = geo.offset(*mark, math.radians(b_in + 95), 2.0)
        c.add_mark("Nouvelle", q[0], q[1])

    k = _round_edit(cs, buoy, mark, b_in, 130, 0.01, edit)
    assert k is None and cs.course.active_idx == 1 and _advances(log) == []
    cs.next()
    assert cs.course.active_idx == 2
    assert cs.marks[cs.course.seq[2].mark_id].name == "Nouvelle"


@pytest.mark.parametrize("delta", [-60, -90, -120])
@pytest.mark.parametrize(
    "turn,tack,r,err_nm", [(60, 45, 0.01, 0.011), (60, 45, 0.01, 0.05), (75, 45, 0.005, 0.0)]
)
def test_after_a_big_next_mark_change_steering_to_the_new_mark_advances(
    tmp_path: Path, turn: float, tack: float, r: float, err_nm: float, delta: float
) -> None:
    """The next mark moved by 60 deg or more in the zone after the rounding: a boat that steers
    to the new mark advances once."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, turn)
    buoy = geo.offset(*mark, math.radians(b_in + 180), err_nm)
    new = geo.offset(*mark, math.radians(b_in + turn + delta), 3.0)

    def edit(c: CourseStore) -> None:
        c.edit_mark(c.course.seq[2].mark_id, lat=new[0], lon=new[1])

    k = _round_edit(cs, buoy, mark, b_in, turn + tack, r, edit, steer_to=lambda c: new)
    assert k is not None and k < 600
    assert len(_advances(log)) == 1


@pytest.mark.parametrize("delta", [-60, -90, -120])
def test_a_big_next_mark_change_while_sailing_the_old_leg_needs_a_manual_next(
    tmp_path: Path, delta: float
) -> None:
    """Accepted residual R8 (plan 04-14): a mark entered 0.05 nm off the buoy (no latch), the
    next mark moved by 60 deg or more in the zone after the rounding, and the boat keeps
    sailing the old leg: by the new outgoing leg it is on the approach side, so no advance; the
    crew uses « Suiv. »."""
    cs, log = store(tmp_path)
    mark, b_in = _committee(cs, 60)
    buoy = geo.offset(*mark, math.radians(b_in + 180), 0.05)
    new = geo.offset(*mark, math.radians(b_in + 60 + delta), 3.0)

    def edit(c: CourseStore) -> None:
        c.edit_mark(c.course.seq[2].mark_id, lat=new[0], lon=new[1])

    k = _round_edit(cs, buoy, mark, b_in, 105, 0.01, edit)
    assert k is None and _advances(log) == []
    cs.next()
    assert cs.course.active_idx == 2


# -- Annuler in the zone at a normal mark (WR-01) and the accepted WR-02 residual (R9) ------------
def test_annuler_in_the_zone_then_an_approach_side_retreat_never_advances(tmp_path: Path) -> None:
    """WR-01 (review 93cb8b3): Annuler after an abeam advance at Plić, back in front of the
    abeam line inside the zone, then the G-4-R02 NNW retreat: the mark stays, one advance."""
    cs, log = store(tmp_path)
    t = run(cs, at(61, 0.4), 0.0, 2)
    t = run(cs, at(81, 0.4), t, 11)
    assert cs.course.active_idx == 2
    cs.undo(cs.status()["banner"]["token"], t)
    t = run(cs, at(61, 0.4), t + 1, 5)  # in the zone, suppressed
    t = run(cs, at(341, 0.8), t, 30)
    assert cs.course.active_idx == 1
    assert len(_advances(log)) == 1


def _committee_advance_then_annuler(
    cs: CourseStore, turn: float
) -> tuple[tuple[float, float], float, float]:
    """An abeam advance inside the 0.3 nm zone of the committee mark, then Annuler. Returns
    (mark, b_in, next t)."""
    m, b_in = _committee(cs, turn)
    t = run(cs, at(b_in + 180, 0.5, m), 0.0, 3)
    t = run(cs, at(b_in + 210, 0.2, m), t, 3)
    t = run(cs, at(b_in - 80, 0.2, m), t, 11)
    assert cs.course.active_idx == 2
    cs.undo(cs.status()["banner"]["token"], t)
    return m, b_in, t + 1


@pytest.mark.parametrize("turn", [45, 60, 90])
def test_annuler_in_the_zone_at_a_committee_mark_then_an_approach_side_retreat_never_advances(
    tmp_path: Path, turn: float
) -> None:
    """WR-01: b_in + 210 deg is strictly inside the approach quadrant (dot_in < 0, dot_out < 0)
    for these turns: the suppressed-zone exit there never advances."""
    cs, log = store(tmp_path)
    m, b_in, t = _committee_advance_then_annuler(cs, turn)
    t = run(cs, at(b_in + 210, 0.2, m), t, 5)  # in the zone, suppressed
    t = run(cs, at(b_in + 210, 0.6, m), t, 30)
    assert cs.course.active_idx == 1
    assert len(_advances(log)) == 1


@pytest.mark.parametrize("turn", [45, 60, 90])
def test_annuler_in_the_zone_then_leaving_past_the_mark_along_the_next_leg_advances(
    tmp_path: Path, turn: float
) -> None:
    """CR-02 kept at normal marks: leaving the suppressed zone past the mark along the next leg
    (dot_out > 0, dot_in < 0) advances after the 10 s debounce."""
    cs, log = store(tmp_path)
    m, b_in, t = _committee_advance_then_annuler(cs, turn)
    out = b_in + 90 + turn / 2
    t = run(cs, at(out, 0.2, m), t, 5)  # in the zone, suppressed
    t = run(cs, at(out, 0.6, m), t, 10)
    assert cs.course.active_idx == 1
    t = run(cs, at(out, 0.6, m), t, 1)
    assert cs.course.active_idx == 2
    assert len(_advances(log)) == 2


def test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances(tmp_path: Path) -> None:
    """Accepted residual R9 (plan 04-14 "WR-02: decision with evidence"): the latch sets on one
    fix past the abeam line (here about 9 m past it, e.g. sailing a layline that is the abeam
    line), so a later approach-side zone exit advances. Every candidate fix measured either did
    not lower these false advances or added stuck roundings; the crew fallback is the 60 s
    banner (Annuler). A later fix changes this test together with the residual table."""
    cs, log = store(tmp_path)
    vod = cs.marks["vodice"]
    b, _ = geo.bearing_distance(vod.lat, vod.lon, PLIC[0], PLIC[1])
    b_in = math.degrees(b)
    t = run(cs, at(b_in + 180, 0.6), 0.0, 3)
    t = run(cs, at(b_in + 265, 0.28), t, 3)
    t = run(cs, at(b_in + 271, 0.28), t, 1)  # one fix past the abeam line
    t = run(cs, at(b_in + 265, 0.28), t, 3)
    t = run(cs, at(b_in + 210, 0.8), t, 30)
    assert cs.course.active_idx == 2
    assert len(_advances(log)) == 1
