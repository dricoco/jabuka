"""Touch input: event parsing, calibration mapping, tap detection, device discovery."""

from __future__ import annotations

from pathlib import Path

from jabuka_touch import touchin
from jabuka_touch.selftest import ManualClock, tap_bytes
from jabuka_touch.touchin import (
    ABS_PRESSURE,
    ABS_X,
    ABS_Y,
    BTN_TOUCH,
    EV_ABS,
    EV_KEY,
    EV_SYN,
    Calibration,
    TapDetector,
    pack_event,
    parse_events,
)

CAL = Calibration()


def test_event_size_and_parse_with_remainder() -> None:
    assert touchin.EVENT_SIZE == 24
    buf = pack_event(EV_ABS, ABS_X, 1234, 5, 6) + pack_event(EV_SYN, 0, 0)
    events, rest = parse_events(buf + b"\x01\x02\x03")
    assert [(e.type, e.code, e.value) for e in events] == [(EV_ABS, ABS_X, 1234), (EV_SYN, 0, 0)]
    assert events[0].sec == 5 and events[0].usec == 6
    assert rest == b"\x01\x02\x03"
    events2, rest2 = parse_events(rest + pack_event(EV_KEY, BTN_TOUCH, 1)[3:])
    assert len(events2) == 1 and events2[0].code == BTN_TOUCH and rest2 == b""


def test_default_calibration_corners() -> None:
    assert CAL.map(268, 3936, 480, 320) == (0, 0)
    assert CAL.map(3880, 227, 480, 320) == (479, 319)
    assert CAL.map(0, 9999, 480, 320) == (0, 0)  # clamped
    assert CAL.map(9999, 0, 480, 320) == (479, 319)


def test_screen_to_raw_inverse() -> None:
    for x, y in ((0, 0), (40, 40), (240, 160), (479, 319), (400, 279), (13, 301)):
        rx, ry = CAL.screen_to_raw(x, y, 480, 320)
        mx, my = CAL.map(rx, ry, 480, 320)
        assert abs(mx - x) <= 1 and abs(my - y) <= 1
    flat = Calibration(100, 3900, 200, 3800, False)
    rx, ry = flat.screen_to_raw(240, 160, 480, 320)
    assert abs(flat.map(rx, ry, 480, 320)[0] - 240) <= 1


def _feed(det: TapDetector, data: bytes, now: float):
    events, _ = parse_events(data)
    return [t for t in (det.feed(e, now) for e in events) if t is not None]


def test_tap_at_median_sample() -> None:
    det = TapDetector(CAL, 480, 320, 0.25)
    taps = _feed(det, tap_bytes(CAL, 400, 279), 10.0)
    assert len(taps) == 1
    t = taps[0]
    assert abs(t.x - 400) <= 2 and abs(t.y - 279) <= 2
    rx, ry = CAL.screen_to_raw(400, 279, 480, 320)
    assert abs(t.raw_x - rx) <= 3 and abs(t.raw_y - ry) <= 3


def test_debounce_drops_close_second_tap() -> None:
    det = TapDetector(CAL, 480, 320, 0.25)
    assert len(_feed(det, tap_bytes(CAL, 100, 100), 10.0)) == 1
    assert _feed(det, tap_bytes(CAL, 100, 100), 10.1) == []
    assert len(_feed(det, tap_bytes(CAL, 100, 100), 10.5)) == 1


def test_press_without_coordinates_yields_nothing() -> None:
    det = TapDetector(CAL, 480, 320)
    data = (
        pack_event(EV_KEY, BTN_TOUCH, 1)
        + pack_event(EV_SYN, 0, 0)
        + pack_event(EV_KEY, BTN_TOUCH, 0)
        + pack_event(EV_SYN, 0, 0)
    )
    assert _feed(det, data, 1.0) == []


def test_pressure_fallback_without_btn_touch() -> None:
    det = TapDetector(CAL, 480, 320)
    rx, ry = CAL.screen_to_raw(240, 160, 480, 320)
    data = (
        pack_event(EV_ABS, ABS_X, rx)
        + pack_event(EV_ABS, ABS_Y, ry)
        + pack_event(EV_ABS, ABS_PRESSURE, 100)
        + pack_event(EV_SYN, 0, 0)
        + pack_event(EV_ABS, ABS_PRESSURE, 0)
        + pack_event(EV_SYN, 0, 0)
    )
    taps = _feed(det, data, 1.0)
    assert len(taps) == 1 and abs(taps[0].x - 240) <= 1


def test_find_device(fake_sys: Path) -> None:
    assert touchin.find_device(fake_sys / "input", "ADS7846 Touchscreen") == "/dev/input/event3"
    assert touchin.find_device(fake_sys / "input", "absent") is None
    assert touchin.find_device(fake_sys / "nope", "ADS7846 Touchscreen") is None


def test_reader_missing_device_retries(tmp_path: Path) -> None:
    clock = ManualClock(0.0)
    calls = []
    path = tmp_path / "ev.bin"

    def find():
        calls.append(clock())
        return str(path) if path.exists() else None

    r = touchin.TouchReader(find, TapDetector(CAL, 480, 320), clock=clock, sleep=lambda s: None)
    assert r.poll(0) == []
    clock.advance(1.0)
    assert r.poll(0) == [] and len(calls) == 1  # not before retry_s
    path.write_bytes(tap_bytes(CAL, 50, 60))
    clock.advance(5.0)
    taps = r.poll(0)
    assert len(calls) == 2 and len(taps) == 1 and abs(taps[0].x - 50) <= 2
    r.close()
