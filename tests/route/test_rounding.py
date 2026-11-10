"""Rounding waypoints around marks on the required side (RESEARCH Pattern 6, CONTEXT §Land mask)."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.frame import DEFAULT_FRAME  # noqa: E402
from jabuka.route.rounding import expand  # noqa: E402
from jabuka.route.types import CourseMark  # noqa: E402


def _brg(mark: CourseMark, wp) -> float:
    mx, my = DEFAULT_FRAME.to_xy(mark.lat, mark.lon)
    x, y = DEFAULT_FRAME.to_xy(wp.lat, wp.lon)
    return math.degrees(math.atan2(x - mx, y - my)) % 360.0


def _dist(mark: CourseMark, wp) -> float:
    mx, my = DEFAULT_FRAME.to_xy(mark.lat, mark.lon)
    x, y = DEFAULT_FRAME.to_xy(wp.lat, wp.lon)
    return math.hypot(x - mx, y - my)


def _cw(a: float, b: float) -> float:
    return (b - a) % 360.0


def test_course_a_starboard_plic_sestre(course) -> None:
    start, marks = course("A")
    plic = marks[0]
    wps = [w for w in expand(start, marks, start.lat, start.lon) if w.mark_index == 0]
    assert [w.kind for w in wps] == ["rounding", "rounding"]  # 42 deg: start + one waypoint
    assert _brg(plic, wps[0]) == pytest.approx(71.0, abs=1.5)
    assert _brg(plic, wps[-1]) == pytest.approx(113.0, abs=1.5)
    assert _cw(_brg(plic, wps[0]), _brg(plic, wps[-1])) == pytest.approx(42.0, abs=1.5)
    for w in wps:
        assert _dist(plic, w) == pytest.approx(plic.radius_nm, abs=1e-6)
        assert w.mark_id == "plic-sestre"


def test_course_a_jabuka_hairpin_three_waypoints_clockwise(course) -> None:
    start, marks = course("A")
    jab = marks[1]
    wps = [w for w in expand(start, marks, start.lat, start.lon) if w.mark_index == 1]
    assert len(wps) == 3
    b = [_brg(jab, w) for w in wps]
    assert b[0] == pytest.approx(113.0, abs=1.5)  # b_in 203 - 90
    assert _cw(b[0], b[-1]) == pytest.approx(166.0, abs=1.5)
    assert _cw(b[0], b[1]) == pytest.approx(_cw(b[1], b[2]), abs=1e-6)  # evenly spread
    assert all(_dist(jab, w) == pytest.approx(0.6) for w in wps)


def test_port_rounding_sweeps_counter_clockwise(course) -> None:
    start, marks = course("B")
    jab = marks[1]  # B: Plić Sestre -> Jabuka (port) -> Mulo: a left turn of about 165 deg
    wps = [w for w in expand(start, marks, start.lat, start.lon) if w.mark_index == 1]
    assert len(wps) == 3
    b = [_brg(jab, w) for w in wps]
    assert b[0] == pytest.approx((203.0 + 90.0) % 360.0, abs=1.5)
    ccw = (b[0] - b[-1]) % 360.0
    assert ccw == pytest.approx(165.0, abs=2.0)


def test_pass_by_turning_away_from_the_mark_needs_no_loop(course) -> None:
    """Course B passes Plić Sestre to port while the course bends 42 deg to starboard: the
    string rule only requires passing on the right side (abeam waypoint, no 318 deg loop),
    entered from the right side (entry waypoint 45 deg before it, counter-clockwise)."""
    start, marks = course("B")
    plic = marks[0]
    wps = [w for w in expand(start, marks, start.lat, start.lon) if w.mark_index == 0]
    assert len(wps) == 2
    assert _brg(plic, wps[0]) == pytest.approx(161.0 + 90.0 + 45.0, abs=1.5)  # north-west
    assert _brg(plic, wps[1]) == pytest.approx(161.0 + 90.0, abs=1.5)  # west of the beacon


def test_previous_mark_not_the_boat_fixes_the_geometry(course) -> None:
    start, marks = course("A")
    a = expand(start, marks, start.lat, start.lon)
    b = expand(start, marks, start.lat - 0.02, start.lon + 0.01)  # boat moved towards Plić
    assert a == b


def test_finish_and_side_none_are_the_mark_itself(course) -> None:
    start, marks = course("A")
    wps = expand(start, marks, start.lat, start.lon)
    last = wps[-1]
    assert last.kind == "finish" and last.mark_id == "vodice"
    assert (last.lat, last.lon) == (marks[-1].lat, marks[-1].lon)
    none_mark = marks[0]._replace(side="none")
    wps2 = expand(start, (none_mark, *marks[1:]), start.lat, start.lon)
    first = [w for w in wps2 if w.mark_index == 0]
    assert len(first) == 1 and first[0].kind == "mark"
    assert (first[0].lat, first[0].lon) == (none_mark.lat, none_mark.lon)


def test_passed_waypoints_are_dropped(course) -> None:
    start, marks = course("A")
    jab = marks[1]
    remaining = marks[1:]
    prev = marks[0]
    full = [w for w in expand(prev, remaining, 43.3, 15.6) if w.mark_index == 0]
    assert len(full) == 3
    # boat inside the zone, just past the second waypoint (bearing ~200 deg from Jabuka)
    lat = jab.lat + 0.65 * math.cos(math.radians(205.0)) / 60.0
    lon = jab.lon + 0.65 * math.sin(math.radians(205.0)) / (60.0 * math.cos(math.radians(43.1)))
    left = [w for w in expand(prev, remaining, lat, lon) if w.mark_index == 0]
    assert len(left) == 1 and left[0] == full[-1]
    # approaching from the north (outside the arc): nothing dropped
    lat_n = jab.lat + 1.0 / 60.0
    assert [w for w in expand(prev, remaining, lat_n, jab.lon) if w.mark_index == 0] == full


def test_blocked_waypoint_pushed_outward_with_note(course, mask) -> None:
    start, marks = course("A")
    # Plić Sestre with a 0.05 nm radius: the waypoints fall inside the hazard margin
    small = marks[0]._replace(radius_nm=0.05)
    notes: list[str] = []
    wps = [
        w
        for w in expand(start, (small, *marks[1:]), start.lat, start.lon, mask, notes)
        if w.mark_index == 0
    ]
    for w in wps:
        x, y = mask.frame.to_xy(w.lat, w.lon)
        assert bool(mask.points_clear(x, y)[0])
        assert _dist(small, w) > 0.05
    assert any("Plić Sestre" in n for n in notes)


def test_unpushable_waypoint_fails_in_french(course, mask) -> None:
    start, marks = course("A")
    inland = CourseMark("x", "Intérieur", 43.80, 15.95, "stbd", 0.1)  # deep on the mainland
    with pytest.raises(ValueError, match="Intérieur"):
        expand(start, (inland, *marks[1:]), start.lat, start.lon, mask)


# --------------------------------------------------------------- last mark (quick 261110-klg)
def _brg_f(frame, mark: CourseMark, lat: float, lon: float) -> float:
    mx, my = frame.to_xy(mark.lat, mark.lon)
    x, y = frame.to_xy(lat, lon)
    return math.degrees(math.atan2(x - mx, y - my)) % 360.0


def _dist_f(frame, mark: CourseMark, lat: float, lon: float) -> float:
    mx, my = frame.to_xy(mark.lat, mark.lon)
    x, y = frame.to_xy(lat, lon)
    return math.hypot(x - mx, y - my)


def _adiff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _blit_plic(course):
    start, marks = course("A")
    plic, blit = marks[0], marks[2]
    assert (plic.mark_id, blit.mark_id) == ("plic-sestre", "blitvenica")
    return start, plic, blit


@pytest.mark.parametrize(("side", "radius"), [("stbd", 0.55), ("none", 0.55), ("none", 0.0)])
def test_last_islet_mark_targets_its_circle_on_the_approach_side(
    course, mask, side, radius
) -> None:
    """Blitvenica's centre is on the islet: the finish waypoint is a clear point of its radius
    circle facing the previous mark (Plić Sestre), pushed outward when the circle is on land."""
    start, plic, blit = _blit_plic(course)
    last = blit._replace(side=side, radius_nm=radius)
    notes: list[str] = []
    wps = expand(start, (plic, last), start.lat, start.lon, mask, notes)
    w = wps[-1]
    assert (w.kind, w.mark_id, w.mark_index) == ("finish", "blitvenica", 1)
    f = mask.frame
    x, y = f.to_xy(w.lat, w.lon)
    assert bool(mask.points_clear(x, y)[0])
    snap = mask.snap_clear(x, y, 1.0)
    assert snap is not None and snap[2] is False
    d = _dist_f(f, last, w.lat, w.lon)
    assert radius - 1e-6 <= d <= radius + 0.5 + 1e-6
    assert d > 0.0
    to_plic = _brg_f(f, last, plic.lat, plic.lon)
    assert _adiff(_brg_f(f, last, w.lat, w.lon), to_plic) <= 1.5
    if radius == 0.0:
        assert any("Blitvenica" in n for n in notes)


def test_last_buoy_with_a_side_targets_its_circle() -> None:
    plic = CourseMark("plic-sestre", "Plić Sestre", 43.684627, 15.811626, "stbd", 0.3)
    start = CourseMark("vodice", "Vodice", 43.75, 15.78, "none", 0.15)
    m2 = CourseMark("m2", "M2", 43.751111, 15.778849, "stbd", 0.1)
    w = expand(start, (plic, m2), start.lat, start.lon)[-1]
    assert (w.kind, w.mark_id) == ("finish", "m2")
    assert _dist(m2, w) == pytest.approx(0.1, abs=1e-6)
    to_plic = _brg_f(DEFAULT_FRAME, m2, plic.lat, plic.lon)
    assert _adiff(_brg(m2, w), to_plic) <= 1e-6


def test_vodice_finish_keeps_its_centre_with_the_mask(course, mask) -> None:
    start, marks = course("A")
    notes: list[str] = []
    w = expand(start, marks, start.lat, start.lon, mask, notes)[-1]
    assert w.kind == "finish" and w.mark_id == "vodice"
    assert (w.lat, w.lon) == (marks[-1].lat, marks[-1].lon)
    assert not any("Vodice" in n for n in notes)


def test_single_last_mark_faces_the_previous_mark_else_the_boat(course, mask) -> None:
    start, plic, blit = _blit_plic(course)
    f = mask.frame
    boat = (43.70, 15.50)  # north-west of Blitvenica, far from the Plić Sestre bearing
    w = expand(plic, (blit,), *boat, mask)[-1]
    assert _adiff(_brg_f(f, blit, w.lat, w.lon), _brg_f(f, blit, plic.lat, plic.lon)) <= 1.5
    w2 = expand(None, (blit,), *boat, mask)[-1]
    assert _adiff(_brg_f(f, blit, w2.lat, w2.lon), _brg_f(f, blit, *boat)) <= 1.5


def test_unplaceable_last_mark_keeps_its_centre(course, mask) -> None:
    """Deep inland: no circle point at sea on the approach bearing -> the centre (the router's
    snap then fails with "cible dans la terre"), never a rounding ValueError."""
    start, marks = course("A")
    inland = CourseMark("x", "Intérieur", 43.80, 15.95, "none", 0.0)
    w = expand(start, (marks[0], inland), start.lat, start.lon, mask)[-1]
    assert (w.kind, w.lat, w.lon) == ("finish", inland.lat, inland.lon)
