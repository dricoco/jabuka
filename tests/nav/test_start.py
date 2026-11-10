"""Start mode store and nav block (quick 261110-cuk, nav/start.py): start.json round trip and
.bak fallback, write-then-commit, the 5:00 timer (SYNC rounding, STOP, the gun closing start mode),
the restart rules of the timer (gun UTC persisted, "clock" state) and start_block on literal nav
messages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jabuka.nav import start as start_mod
from jabuka.nav.polar import default_polar
from jabuka.nav.settings import Settings
from jabuka.nav.start import (
    START_FILE,
    LineEnd,
    NoTimer,
    StartState,
    StartStore,
    start_block,
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
    assert b["line"] == {"committee": None, "pin": None}
    s.set_end("committee", *C, "ping")
    s.start_timer(10.0, 1_794_600_000.0)
    b = start_block(s, _msg(), polar, settings, 12.34, 1_794_600_002.34)
    assert b["timer"]["state"] == "running" and b["timer"]["remaining_s"] == 297.7
    assert b["timer"]["gun_utc"] == "2026-11-13T20:05:00Z"
    assert b["line"]["committee"] == {"lat": C[0], "lon": C[1], "src": "ping"}
    # the gun inside the block: start mode closes and the block disappears
    assert start_block(s, _msg(), polar, settings, 400.0, None) is None
