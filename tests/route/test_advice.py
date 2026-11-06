"""Tack advice: route following, heading sign, countdown, tack detection, missed tack."""

from __future__ import annotations

import math

import pytest

from jabuka.common.conventions import apparent_from_true, true_wind_from_apparent
from jabuka.route.advice import (
    LAT0,
    LON0,
    MissedTackWatch,
    RouteFollower,
    TackDetector,
    cost_text,
    from_xy,
    target_heading,
)

T0 = 1_800_000_000.0
SPEED_NM_MIN = 0.1  # 6 kn
TWD = 0.0  # wind from north: starboard (TWA +40) steers 320, port (TWA -40) steers 040


def _step(x: float, y: float, course_deg: float, nm: float) -> tuple[float, float]:
    c = math.radians(course_deg)
    return x + nm * math.sin(c), y + nm * math.cos(c)


def _pos(minute: float) -> tuple[float, float]:
    """Local (x, y) of the beat path at route minute ``minute`` (tack at 20 min)."""
    if minute <= 20.0:
        return _step(0.0, 0.0, 320.0, SPEED_NM_MIN * minute)
    px, py = _step(0.0, 0.0, 320.0, SPEED_NM_MIN * 20.0)
    return _step(px, py, 40.0, SPEED_NM_MIN * (minute - 20.0))


def _latlon(x: float, y: float) -> tuple[float, float]:
    return from_xy(x, y, LAT0, LON0)


def beat_path():
    minutes = [*range(0, 46, 2), 45]  # 0, 2, ..., 44, 45
    path = []
    for m in minutes:
        lat, lon = _latlon(*_pos(m))
        twa, tack = (40.0, 1) if m < 20 else (-40.0, -1)
        path.append((T0 + 60.0 * m, lat, lon, twa, tack))
    tlat, tlon = _latlon(*_pos(20.0))
    tacks = [(T0 + 1200.0, tlat, tlon, 1, -1, "tack")]
    return path, tacks


# ---- heading sign (golden against conventions.py) -----------------------------------------


@pytest.mark.parametrize(("twa", "hdg"), [(40.0, 160.0), (-40.0, 240.0)])
def test_target_heading_sign_matches_conventions(twa: float, hdg: float) -> None:
    twd = 200.0
    assert target_heading(twd, twa) == pytest.approx(hdg, abs=1e-9)
    tws, bsp = 7.0, 3.2  # m/s
    app = apparent_from_true(math.radians(twd), tws, bsp, math.radians(hdg))
    back = true_wind_from_apparent(app.awa, app.aws, bsp, math.radians(hdg))
    assert math.degrees(back.twa) == pytest.approx(twa, abs=1e-6)
    assert math.degrees(back.twd) == pytest.approx(twd, abs=1e-6)
    assert (app.awa > 0) == (twa > 0)  # same side apparent and true


# ---- following --------------------------------------------------------------------------


def test_on_route_target_and_countdown() -> None:
    path, tacks = beat_path()
    f = RouteFollower(path, tacks).follow(T0 + 300.0, *_latlon(*_pos(5.0)), 320.0, TWD)
    assert f.target_tack == 1
    assert f.target_twa == 40.0
    assert f.t_route_here == pytest.approx(T0 + 300.0, abs=1e-3)
    assert f.countdown_s == pytest.approx(900.0, abs=1.0)
    assert f.xte_nm == pytest.approx(0.0, abs=1e-6)
    assert f.seg_course_deg == pytest.approx(320.0, abs=1e-6)
    assert f.course_dev_deg == pytest.approx(0.0, abs=1e-6)
    assert f.target_hdg_t == pytest.approx(320.0, abs=1e-9)
    assert f.next_tack == tacks[0]
    assert not f.finished


def test_abeam_gives_xte_and_same_countdown() -> None:
    path, tacks = beat_path()
    x, y = _step(*_pos(5.0), 50.0, 0.2)  # 0.2 nm abeam (to starboard of a 320 course)
    f = RouteFollower(path, tacks).follow(T0 + 300.0, *_latlon(x, y), 330.0, TWD)
    assert f.xte_nm == pytest.approx(0.2, abs=0.01)
    assert f.countdown_s == pytest.approx(900.0, abs=1.0)
    assert f.course_dev_deg == pytest.approx(10.0, abs=1e-6)


def test_wind_shift_keeps_twa_and_moves_heading() -> None:
    path, tacks = beat_path()
    follower = RouteFollower(path, tacks)
    a = follower.follow(T0 + 300.0, *_latlon(*_pos(5.0)), 320.0, TWD)
    b = follower.follow(T0 + 301.0, *_latlon(*_pos(5.0)), 320.0, TWD + 15.0)
    assert b.target_twa == a.target_twa == 40.0
    assert b.target_hdg_t == pytest.approx(a.target_hdg_t + 15.0, abs=1e-9)
    assert follower.follow(T0 + 302.0, *_latlon(*_pos(5.0)), None, None).target_hdg_t is None


def test_projection_never_moves_backwards() -> None:
    path, tacks = beat_path()
    follower = RouteFollower(path, tacks)
    first = follower.follow(T0 + 600.0, *_latlon(*_pos(10.0)), 320.0, TWD)
    back = follower.follow(T0 + 610.0, *_latlon(*_pos(4.0)), 320.0, TWD)
    assert back.idx >= first.idx
    fresh = RouteFollower(path, tacks)
    assert fresh.idx == 0
    assert fresh.follow(T0, *_latlon(*_pos(0.0)), 320.0, TWD).idx == 0


def test_late_boat_eta_and_countdown_in_route_time() -> None:
    path, tacks = beat_path()
    end = path[-1][0]
    # 5 min late before the tack: countdown from route time (15 -> 20 min)
    f = RouteFollower(path, tacks).follow(T0 + 1200.0, *_latlon(*_pos(15.0)), 320.0, TWD)
    assert f.countdown_s == pytest.approx(300.0, abs=1.0)
    assert f.eta_now == pytest.approx(end + 300.0, abs=1.0)
    # 5 min late after the tack (route 25 min, wall 30 min)
    g = RouteFollower(path, tacks).follow(T0 + 1800.0, *_latlon(*_pos(25.0)), 40.0, TWD)
    assert g.t_route_here == pytest.approx(T0 + 1500.0, abs=1.0)
    assert g.eta_now == pytest.approx(end + 300.0, abs=1.0)
    assert g.remaining_s == pytest.approx(end - (T0 + 1500.0), abs=1.0)
    assert g.target_tack == -1


def test_no_tack_path_and_finish() -> None:
    path, _ = beat_path()
    straight = [p for p in path if p[0] >= T0 + 1200.0]
    follower = RouteFollower(straight, [])
    f = follower.follow(T0 + 1500.0, *_latlon(*_pos(25.0)), 40.0, TWD)
    assert f.next_tack is None and f.countdown_s is None
    assert not f.finished
    beyond = _step(*_pos(45.0), 40.0, 0.3)
    g = follower.follow(T0 + 2800.0, *_latlon(*beyond), 40.0, TWD)
    assert g.finished
    assert g.remaining_s == pytest.approx(0.0, abs=1e-6)


def test_tack_followed_moves_to_next() -> None:
    path, tacks = beat_path()
    follower = RouteFollower(path, tacks)
    assert follower.follow(T0 + 1140.0, *_latlon(*_pos(19.0)), 320.0, TWD).countdown_s == (
        pytest.approx(60.0, abs=1.0)
    )
    f = follower.follow(T0 + 1320.0, *_latlon(*_pos(22.0)), 40.0, TWD)  # tacked as advised
    assert f.next_tack is None and f.countdown_s is None
    assert f.target_tack == -1


def test_overdue_tack_counts_down_negative_and_fires_missed_once() -> None:
    path, tacks = beat_path()
    follower = RouteFollower(path, tacks)
    watch = MissedTackWatch()
    f = follower.follow(T0 + 1140.0, *_latlon(*_pos(19.0)), 320.0, TWD)
    assert not watch.update(T0 + 1140.0, f.countdown_s, None)
    fired = []
    for k in range(1, 20):  # keep sailing starboard past the tack point
        t = T0 + 1200.0 + 10.0 * k
        x, y = _step(*_pos(20.0), 320.0, SPEED_NM_MIN * (10.0 * k) / 60.0)
        f = follower.follow(t, *_latlon(x, y), 320.0, TWD)
        assert f.next_tack == tacks[0]
        assert f.countdown_s == pytest.approx(-(10.0 * k), abs=1.0)
        if watch.update(t, f.countdown_s, None):
            fired.append(t)
    assert fired == [T0 + 1330.0]  # first sample more than 120 s overdue, once


# ---- tack detector ----------------------------------------------------------------------


def _feed(det: TackDetector, samples):
    return [e for t, a in samples if (e := det.update(t, a)) is not None]


def test_tack_confirmed_after_30s_only() -> None:
    det = TackDetector()
    assert _feed(det, [(t, 40.0) for t in range(0, 10)]) == []
    assert det.side == 1
    assert _feed(det, [(t, -40.0) for t in range(10, 40)]) == []  # held 29 s
    assert det.side == 1
    det2 = TackDetector()
    _feed(det2, [(t, 40.0) for t in range(0, 10)])
    events = _feed(det2, [(t, -40.0) for t in range(10, 42)])  # held 31 s
    assert len(events) == 1
    assert events[0].t_change == 10
    assert events[0].new_side == -1
    assert events[0].kind == "tack"
    assert det2.side == -1 and det2.last_tack_t == 10


def test_gybe_kind() -> None:
    det = TackDetector()
    _feed(det, [(t, -150.0) for t in range(0, 5)])
    events = _feed(det, [(t, 150.0) for t in range(5, 40)])
    assert [e.kind for e in events] == ["gybe"]
    assert events[0].new_side == 1


@pytest.mark.parametrize("mag", [5.0, 170.0])
def test_oscillation_head_to_wind_or_downwind_never_confirms(mag: float) -> None:
    det = TackDetector()
    _feed(det, [(0, 40.0 if mag < 90 else 150.0)])
    samples = [(t, mag if t % 2 else -mag) for t in range(1, 200)]
    assert _feed(det, samples) == []
    assert det.side == 1


def test_none_pauses_without_reset() -> None:
    det = TackDetector()
    _feed(det, [(t, 40.0) for t in range(0, 10)])
    assert _feed(det, [(t, -40.0) for t in range(10, 25)]) == []  # held 14 s
    assert _feed(det, [(t, None) for t in range(25, 60)]) == []
    assert det.side == 1
    events = _feed(det, [(t, -40.0) for t in range(60, 80)])
    assert len(events) == 1
    assert events[0].t_change == 10  # continued, not restarted
    assert det.last_tack_t == 10


def test_back_on_current_side_resets_candidate() -> None:
    det = TackDetector()
    _feed(det, [(0, 40.0)])
    _feed(det, [(t, -40.0) for t in range(1, 20)])
    _feed(det, [(20, 40.0)])
    assert _feed(det, [(t, -40.0) for t in range(21, 45)]) == []  # 23 s since restart


# ---- missed tack ------------------------------------------------------------------------


def test_missed_tack_thresholds_and_once() -> None:
    w = MissedTackWatch()
    assert not w.update(1000.0, -119.0, None)
    assert w.update(1000.0, -121.0, None)
    assert not w.update(1001.0, -122.0, None)  # same advised tack: once
    assert not w.update(1002.0, None, None)
    assert w.update(5000.0, -125.0, None)  # another advised tack fires again


def test_missed_tack_suppressed_by_detected_tack() -> None:
    w = MissedTackWatch()
    advised = 1000.0 - 121.0
    assert not w.update(1000.0, -121.0, advised - 30.0)
    assert w.update(1000.0, -121.0, advised - 61.0)  # tack long before: still missed


def test_cost_text() -> None:
    assert cost_text(None) is None
    assert cost_text(0.0) == "< 1 min"
    assert cost_text(59.0) == "< 1 min"
    assert cost_text(-12.0) == "< 1 min"
    assert cost_text(-300.0) == "< 1 min"
    assert cost_text(240.0) == "+4 min"
    assert cost_text(61.0) == "+1 min"
