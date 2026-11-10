"""Start mode store and nav block (quick 261110-cuk, nav/start.py): start.json round trip and
.bak fallback, write-then-commit, the 5:00 timer (SYNC rounding, STOP, the gun closing start mode),
the restart rules of the timer (gun UTC persisted, "clock" state) and start_block on literal nav
messages."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from jabuka.nav import geo
from jabuka.nav import start as start_mod
from jabuka.nav.polar import default_polar, efficiency_for
from jabuka.nav.settings import Settings
from jabuka.nav.start import (
    START_FILE,
    LineEnd,
    NoTimer,
    StartState,
    StartStore,
    convex_hull,
    course_normal,
    ray_to_line,
    start_block,
    tack_headings,
    tack_now,
    zone_ring,
)

C = (43.7000, 15.7900)
P = (43.7000, 15.7960)


def _store(d: Path) -> tuple[StartStore, list[dict]]:
    s = StartStore(d)
    events: list[dict] = []
    s.on_event = events.append
    return s, events


# -- persistence ----------------------------------------------------------------------------------
def test_round_trip(tmp_path: Path) -> None:
    s, ev = _store(tmp_path)
    assert not s.open and s.restored is None
    s.set_open(True)
    s.set_end("committee", *C, "ping", 1000.0)
    s.set_end("pin", *P, "typed")
    s.start_timer(100.0, 1000.0)
    again = StartStore(tmp_path)
    assert again.open
    assert again.state.committee == LineEnd(lat=C[0], lon=C[1], src="ping", utc=1000.0)
    assert again.state.pin is not None and again.state.pin.src == "typed"
    assert again.state.gun_utc == 1300.0
    assert again.restored is None
    assert [e["action"] for e in ev] == ["open", "ping", "typed", "timer_start"]
    assert all(e["type"] == "start" for e in ev)
    assert ev[1]["end"] == "committee" and ev[1]["lat"] == C[0]


def test_torn_file_falls_back_to_bak_then_defaults(tmp_path: Path) -> None:
    s, _ = _store(tmp_path)
    s.set_end("committee", *C, "ping")
    s.set_open(True)  # start.json.bak now holds the committee end
    (tmp_path / START_FILE).write_text('{"open": tr')
    again = StartStore(tmp_path)
    assert again.restored == "bak"
    assert again.state.committee is not None
    (tmp_path / (START_FILE + ".bak")).write_text("garbage")
    worst = StartStore(tmp_path)
    assert worst.restored == "unreadable"
    assert worst.state == StartState()


def test_write_failure_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s, ev = _store(tmp_path)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(start_mod, "atomic_write_json", boom)
    with pytest.raises(OSError):
        s.set_open(True)
    with pytest.raises(OSError):
        s.set_end("pin", *P, "typed")
    with pytest.raises(OSError):
        s.start_timer(0.0, None)
    assert s.state == StartState() and s.gun_mono is None and ev == []


def test_bad_ends_refused(tmp_path: Path) -> None:
    s, ev = _store(tmp_path)
    with pytest.raises(ValueError):
        s.set_end("boat", *C, "ping")
    with pytest.raises(ValidationError):
        s.set_end("pin", 50.0, 15.0, "typed")
    with pytest.raises(ValidationError):
        s.set_end("pin", float("nan"), 15.0, "typed")
    assert s.state.pin is None and ev == []


# -- timer ----------------------------------------------------------------------------------------
def test_timer_sync_stop(tmp_path: Path) -> None:
    s, ev = _store(tmp_path)
    s.start_timer(100.0, None)
    assert s.open
    assert s.remaining(130.0, None) == ("running", 270.0)
    for rem, want in ((280.0, 300.0), (260.0, 240.0), (270.0, 300.0)):
        s.start_timer(0.0, None, seconds=rem)
        assert s.sync(0.0, None) == want
        assert s.remaining(0.0, None) == ("running", want)
    s.stop()
    assert s.remaining(10.0, None) == ("off", None)
    assert s.open
    with pytest.raises(NoTimer):
        s.sync(10.0, None)
    s.start_timer(0.0, None)
    s.set_open(False)
    assert s.remaining(1.0, None) == ("off", None)
    actions = [e["action"] for e in ev]
    assert actions.count("sync") == 3 and "stop" in actions and actions[-1] == "close"


def test_sync_under_half_a_minute_is_the_gun(tmp_path: Path) -> None:
    s, ev = _store(tmp_path)
    s.start_timer(0.0, 1000.0, seconds=20.0)
    assert s.sync(0.0, 1000.0, (43.7, 15.79)) == 0.0
    assert not s.open and s.remaining(0.0, 1000.0) == ("off", None)
    gun = ev[-1]
    assert gun["action"] == "gun" and gun["via"] == "sync" and gun["boat"] == [43.7, 15.79]
    assert gun["gun_utc"] == 1020.0
    assert not StartStore(tmp_path).open


def test_tick_past_the_gun_closes_once(tmp_path: Path) -> None:
    s, ev = _store(tmp_path)
    s.start_timer(0.0, None)
    s.tick(299.0, None, (43.7, 15.79))
    assert s.open
    s.tick(300.5, None, (43.7, 15.79))
    assert not s.open
    s.tick(301.5, None, (43.7, 15.79))
    guns = [e for e in ev if e["action"] == "gun"]
    assert len(guns) == 1 and guns[0]["via"] == "timer" and guns[0]["boat"] == [43.7, 15.79]
    assert json.loads((tmp_path / START_FILE).read_text())["open"] is False


def test_gun_with_a_failed_write_still_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, ev = _store(tmp_path)
    s.start_timer(0.0, None)

    def boom(*_a, **_k):
        raise OSError("read-only")

    monkeypatch.setattr(start_mod, "atomic_write_json", boom)
    s.tick(400.0, None, None)
    assert not s.open and ev[-1]["action"] == "gun" and ev[-1]["boat"] is None


def test_restart_keeps_the_timer_from_gps_utc(tmp_path: Path) -> None:
    s, _ = _store(tmp_path)
    s.start_timer(100.0, 1000.0)
    again = StartStore(tmp_path)
    assert again.remaining(5.0, 1100.0) == ("running", 200.0)
    third = StartStore(tmp_path)
    assert third.remaining(5.0, None) == ("clock", None)
    assert third.remaining(7.0, 1150.0) == ("running", 150.0)
    late, ev = _store(tmp_path)
    late.tick(5.0, 1400.0, None)
    assert not late.open and ev[-1]["action"] == "gun"


def test_timer_without_utc_records_the_gun_utc_once_known(tmp_path: Path) -> None:
    s, _ = _store(tmp_path)
    s.start_timer(100.0, None)
    assert StartStore(tmp_path).state.gun_utc is None  # memory only so far
    assert s.remaining(110.0, 5000.0) == ("running", 290.0)
    assert s.state.gun_utc == 5290.0
    assert StartStore(tmp_path).remaining(0.0, 5100.0) == ("running", 190.0)


# -- nav block ------------------------------------------------------------------------------------
def _msg(**boat: object) -> dict:
    return {"boat": {"lat": 43.69, "lon": 15.793, "hdg_t": 0.0, **boat}, "wind": None}


def test_start_block_closed_and_open(tmp_path: Path) -> None:
    s, _ = _store(tmp_path)
    polar, settings = default_polar(), Settings()
    assert start_block(s, _msg(), polar, settings, 0.0, None) is None
    s.set_open(True)
    b = start_block(s, _msg(), polar, settings, 0.0, None)
    assert b is not None
    assert b["open"] is True and b["error"] is False and b["restored"] is None
    assert b["timer"] == {"state": "off", "remaining_s": None, "gun_utc": None}
    assert b["line"]["committee"] is None and b["line"]["pin"] is None
    assert b["reason"] == "no_line" and b["zone"] is None and b["tack_now"] is False
    s.set_end("committee", *C, "ping")
    s.start_timer(10.0, 1_794_600_000.0)
    b = start_block(s, _msg(), polar, settings, 12.34, 1_794_600_002.34)
    assert b["timer"]["state"] == "running" and b["timer"]["remaining_s"] == 297.7
    assert b["timer"]["gun_utc"] == "2026-11-13T20:05:00Z"
    assert b["line"]["committee"] == {"lat": C[0], "lon": C[1], "src": "ping"}
    # the gun inside the block: start mode closes and the block disappears
    assert start_block(s, _msg(), polar, settings, 400.0, None) is None


# -- Task 2: geometry, time to the line, the zone (D-03a/b/c, O-01) ------------------------------
CENTRE = (43.70, 15.80)


def _line(length_nm: float = 0.5, bearing: float = 90.0):
    """Committee west, pin east of CENTRE (bearing committee -> pin)."""
    half = length_nm / 2.0
    com = geo.offset(*CENTRE, math.radians(bearing + 180.0), half)
    pin = geo.offset(*CENTRE, math.radians(bearing), half)
    return com, pin


def _wind(twd: float = 0.0, tws: float = 12.0, **kw: object) -> dict:
    return {"source": "LIVE", "stale": False, "twd_t": twd, "tws_kn": tws, **kw}


def _nav(boat: tuple[float, float] | None, hdg: float | None, wind: dict | None, mark=None):
    lat, lon = boat if boat is not None else (None, None)
    return {"boat": {"lat": lat, "lon": lon, "hdg_t": hdg}, "wind": wind, "mark": mark}


def _open_store(tmp_path: Path, length_nm: float = 0.5, seconds: float | None = 120.0):
    s, ev = _store(tmp_path)
    com, pin = _line(length_nm)
    s.set_end("committee", *com, "typed")
    s.set_end("pin", *pin, "typed")
    s.set_open(True)
    if seconds is not None:
        s.start_timer(0.0, None, seconds=seconds)
    return s, ev


def test_tack_headings() -> None:
    assert tack_headings(45.0, 0.0, 40.0) == ((45.0, -45.0), (315.0, 45.0))
    assert tack_headings(20.0, 0.0, 40.0) == ((40.0, -40.0), (320.0, 40.0))
    assert tack_headings(0.0, 0.0, 40.0) == ((320.0, 40.0), (40.0, -40.0))
    (h, a), (ho, ao) = tack_headings(200.0, 10.0, 40.0)  # downwind: no clamp, mirrored gybe
    assert (h, a) == (200.0, 170.0) and (ho, ao) == (180.0, -170.0)


def test_ray_to_line() -> None:
    a, b = (-0.05, 0.0), (0.05, 0.0)
    d, on = ray_to_line(0.0, -0.2, 0.0, *a, *b)
    assert d == pytest.approx(0.2) and on is True
    assert ray_to_line(0.0, -0.2, 90.0, *a, *b) == (None, False)
    assert ray_to_line(0.0, -0.2, 180.0, *a, *b) == (None, False)
    d, on = ray_to_line(0.0, -0.2, 45.0, *a, *b)
    assert d == pytest.approx(0.2 * math.sqrt(2.0)) and on is False


def test_course_normal_mark_side_else_windward() -> None:
    a, b = (-0.05, 0.0), (0.05, 0.0)
    assert course_normal(a, b, None, 0.0) == pytest.approx((0.0, 1.0))
    assert course_normal(a, b, None, 180.0) == pytest.approx((0.0, -1.0))
    assert course_normal(a, b, (0.3, -2.0), 0.0) == pytest.approx((0.0, -1.0))
    assert course_normal(b, a, (0.0, 5.0), 180.0) == pytest.approx((0.0, 1.0))


def test_convex_hull() -> None:
    pts = [(0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5), (0.5, 0.0)]
    assert sorted(convex_hull(pts)) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def _ttl(dist_nm: float, twa: float, settings: Settings, tws: float = 12.0) -> float:
    polar = default_polar()
    s = settings
    eff = efficiency_for(abs(twa), s.efficiency, s.efficiency_up, s.efficiency_down)
    return dist_nm / (eff * polar.speed(tws, abs(twa))) * 3600.0


def test_start_block_times_and_margins(tmp_path: Path) -> None:
    s, _ = _open_store(tmp_path)
    polar, settings = default_polar(), Settings()
    up = polar.targets(12.0).up_twa
    boat = geo.offset(*CENTRE, math.pi, 0.2)
    b = start_block(s, _nav(boat, (360.0 - up) % 360.0, _wind()), polar, settings, 0.0, None)
    assert b is not None and b["reason"] is None
    assert b["line"]["length_nm"] == pytest.approx(0.5, abs=1e-3)
    assert b["line"]["bearing_t"] == pytest.approx(90.0, abs=0.1)
    dist = 0.2 / math.cos(math.radians(up))
    t_now = _ttl(dist, up, settings)
    now, other = b["now"], b["other"]
    assert now["twa"] == pytest.approx(up) and now["on_line"] is True
    assert now["t_s"] == pytest.approx(t_now, abs=0.1)
    assert other["hdg_t"] == pytest.approx(up) and other["twa"] == pytest.approx(-up)
    assert other["t_s"] == pytest.approx(t_now + settings.start_tack_s, abs=0.1)
    assert now["margin_s"] == pytest.approx(120.0 - now["t_s"], abs=0.11)
    assert other["margin_s"] == pytest.approx(120.0 - other["t_s"], abs=0.11)
    assert b["start_tack_s"] == 10.0
    assert b["tack_now"] is False
    # the router's tack penalty is not start mode's: nothing moves
    same = start_block(
        s,
        _nav(boat, (360.0 - up) % 360.0, _wind()),
        polar,
        settings.model_copy(update={"tack_penalty_s": 90.0}),
        0.0,
        None,
    )
    assert same["other"] == other and same["zone"] == b["zone"]
    for tack_s in (0.0, 30.0):
        alt = start_block(
            s,
            _nav(boat, (360.0 - up) % 360.0, _wind()),
            polar,
            settings.model_copy(update={"start_tack_s": tack_s}),
            0.0,
            None,
        )
        assert alt["other"]["t_s"] == pytest.approx(other["t_s"] - 10.0 + tack_s, abs=0.11)
        assert alt["now"] == now
        assert alt["start_tack_s"] == tack_s


def test_tack_now_window() -> None:
    assert tack_now({"on_line": True, "margin_s": 0.0}) is True
    assert tack_now({"on_line": True, "margin_s": -9.9}) is True
    assert tack_now({"on_line": True, "margin_s": -10.0}) is False
    assert tack_now({"on_line": True, "margin_s": -11.0}) is False
    assert tack_now({"on_line": True, "margin_s": 1.0}) is False
    assert tack_now({"on_line": False, "margin_s": -2.0}) is False
    assert tack_now({"on_line": True, "margin_s": None}) is False
    assert tack_now(None) is False


def test_tack_now_in_the_block(tmp_path: Path) -> None:
    polar, settings = default_polar(), Settings()
    up = polar.targets(12.0).up_twa
    boat = geo.offset(*CENTRE, math.pi, 0.2)
    msg = _nav(boat, (360.0 - up) % 360.0, _wind())
    s, _ = _open_store(tmp_path, seconds=None)
    s.start_timer(0.0, None, seconds=600.0)
    other_t = start_block(s, msg, polar, settings, 0.0, None)["other"]["t_s"]
    for delta, want in ((-3.0, True), (1.0, False), (-11.0, False)):
        s.start_timer(0.0, None, seconds=other_t + delta)
        b = start_block(s, msg, polar, settings, 0.0, None)
        assert b["tack_now"] is want, (delta, b["other"])
    # the other tack crossing outside the segment never asks for a tack
    short, _ = _open_store(tmp_path / "short", length_nm=0.1, seconds=None)
    short.start_timer(0.0, None, seconds=other_t - 3.0)
    b = start_block(short, msg, polar, settings, 0.0, None)
    assert b["other"]["on_line"] is False and b["tack_now"] is False


def test_reason_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    polar, settings = default_polar(), Settings()
    boat = geo.offset(*CENTRE, math.pi, 0.2)
    s, _ = _store(tmp_path)
    s.start_timer(0.0, None)

    def reason(msg: dict) -> dict:
        b = start_block(s, msg, polar, settings, 10.0, None)
        assert b["timer"] == {"state": "running", "remaining_s": 290.0, "gun_utc": None}
        return b

    b = reason(_nav(None, None, None))
    assert b["reason"] == "no_line" and b["now"] is None and b["other"] is None
    assert b["zone"] is None and b["tack_now"] is False
    com, pin = _line()
    s.set_end("committee", *com, "typed")
    assert reason(_nav(boat, 322.0, _wind()))["reason"] == "no_line"
    s.set_end("pin", *pin, "typed")
    assert reason(_nav(None, 322.0, _wind()))["reason"] == "no_position"
    assert reason(_nav(boat, None, _wind()))["reason"] == "no_heading"
    for w in (
        None,
        _wind(source="NONE"),
        _wind(stale=True),
        _wind(twd=None),
        _wind(tws=None),
    ):
        b = reason(_nav(boat, 322.0, w))
        assert b["reason"] == "no_wind" and b["now"] is None and b["zone"] is None, w
    # the zone needs the line and the wind, not the position
    b = reason(_nav(None, None, _wind()))
    assert b["reason"] == "no_position" and b["zone"] is not None

    def boom(*_a, **_k):
        raise ZeroDivisionError("geometry bug")

    monkeypatch.setattr(start_mod, "tack_headings", boom)
    b = reason(_nav(boat, 322.0, _wind()))
    assert b["reason"] == "calc_error" and b["now"] is None and b["other"] is None
    assert b["zone"] is None and b["tack_now"] is False


def _zone(remaining: float, tack_s: float = 0.0, length_nm: float = 0.1, tws: float = 12.0):
    com, pin = _line(length_nm)
    a = geo.to_local(*com, *CENTRE)
    b = geo.to_local(*pin, *CENTRE)
    n = course_normal(a, b, None, 0.0)
    settings = Settings().model_copy(update={"start_tack_s": tack_s})
    return zone_ring(a, b, n, 0.0, tws, default_polar(), settings, remaining, *CENTRE)


def _local(ring: list[list[float]]) -> list[tuple[float, float]]:
    return [geo.to_local(lat, lon, *CENTRE) for lon, lat in ring]


def _area(pts: list[tuple[float, float]]) -> float:
    pairs = zip(pts[:-1], pts[1:], strict=True)
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs)) / 2.0


def test_zone_ring_shape_and_size() -> None:
    ring = _zone(300.0)
    assert ring is not None and ring[0] == ring[-1] and len(ring) >= 5
    pts = _local(ring)
    assert all(y <= 1e-6 for _, y in pts)
    hull = convex_hull(pts[:-1])
    assert len(hull) >= len(pts) - 1 - 2  # convex (collinear line points may drop)
    polar, s = default_polar(), Settings()
    t = polar.targets(12.0)
    eff = efficiency_for(t.up_twa, s.efficiency, s.efficiency_up, s.efficiency_down)
    deepest = -min(y for _, y in pts)
    want = 300.0 / 3600.0 * t.up_bsp * math.cos(math.radians(t.up_twa)) * eff
    assert deepest == pytest.approx(want, rel=0.03)
    ratio = _area(_local(_zone(150.0))) / _area(pts)
    assert 0.2 <= ratio <= 0.35, ratio
    assert _zone(300.0, tack_s=10.0) == _zone(290.0, tack_s=0.0)


def test_zone_ring_none_cases() -> None:
    assert _zone(10.0, tack_s=10.0) is None
    assert _zone(5.0, tack_s=10.0) is None
    assert _zone(300.0, tws=0.0) is None
    com, pin = _line(0.1)
    a = geo.to_local(*com, *CENTRE)
    b = geo.to_local(*pin, *CENTRE)
    n = course_normal(a, b, None, 0.0)
    args = (default_polar(), Settings(), 300.0, *CENTRE)
    assert zone_ring(a, b, n, 0.0, None, *args) is None
    assert zone_ring(a, b, n, None, 12.0, *args) is None


def test_zone_only_while_the_timer_runs_and_towards_the_mark(tmp_path: Path) -> None:
    polar, settings = default_polar(), Settings()
    s, _ = _open_store(tmp_path, seconds=None)
    msg = _nav(None, None, _wind())
    assert start_block(s, msg, polar, settings, 0.0, None)["zone"] is None
    s.start_timer(0.0, None)
    north = start_block(s, msg, polar, settings, 0.0, None)["zone"]
    assert north is not None
    assert all(geo.to_local(lat, lon, *CENTRE)[1] <= 1e-6 for lon, lat in north)
    # the active mark to the south: the course side is south, the zone on the north side
    mark = {"lat": CENTRE[0] - 0.05, "lon": CENTRE[1]}
    south = start_block(s, {**msg, "mark": mark}, polar, settings, 0.0, None)["zone"]
    assert south is not None
    assert all(geo.to_local(lat, lon, *CENTRE)[1] >= -1e-6 for lon, lat in south)
