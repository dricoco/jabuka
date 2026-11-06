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
    t = run(cs, at(51, 0.8), t, 11)  # left the zone without abeam: advanced
    assert cs.course.active_idx == 2
    cs.undo(cs.status()["banner"]["token"], t)
    t = run(cs, at(51, 0.8), t, 30)  # still outside: nothing
    assert cs.course.active_idx == 1 and cs.course.suppress_idx is None
    t = run(cs, at(61, 0.4), t, 2)  # entered again
    t = run(cs, at(51, 0.8), t, 11)  # and left: fires again
    assert cs.course.active_idx == 2


def test_hairpin_annuler_then_real_rounding_advances(tmp_path: Path) -> None:
    """CR-02 scenario: Jabuka (Course A) advances early (the boat swung wide out of the zone on
    the approach side), comes back into the zone, the helmsman taps Annuler, rounds the island
    inside the zone and heads north: the exit advances to Blitvenica."""
    cs, _ = store(tmp_path)
    cs.activate(2)
    jab = (cs.marks["jabuka"].lat, cs.marks["jabuka"].lon)
    t = run(cs, at(23, 0.7, mark=jab), 0.0, 3)  # approaching from the NNE, in the zone
    t = run(cs, at(113, 0.9, mark=jab), t, 11)  # wide on the east side, out of the zone
    assert cs.course.active_idx == 3
    t = run(cs, at(150, 0.6, mark=jab), t, 2)  # back in the zone
    cs.undo(cs.status()["banner"]["token"], t)
    assert cs.course.active_idx == 2
    t = run(cs, at(203, 0.6, mark=jab), t, 20)  # rounding inside the zone: suppressed
    t = run(cs, at(300, 0.7, mark=jab), t, 20)
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
    """IN-07: radius 2 nm -> zone 2.25 nm, past the 2 nm gate: leaving the zone (without abeam)
    still counts, the gate follows the zone."""
    cs, _ = store(tmp_path)
    cs.set_leg(1, radius_nm=2.0)
    t = run(cs, at(61, 2.1), 0.0, 3)  # inside the 2.25 nm zone, in front of the abeam line
    t = run(cs, at(51, 2.4), t, 10)  # left the zone, not abeam
    assert cs.course.active_idx == 1
    cs.on_tick(*at(51, 2.4), t)
    assert cs.course.active_idx == 2


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
