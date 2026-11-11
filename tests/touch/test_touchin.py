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


def test_solve_calibration_recovers_default() -> None:
    from jabuka_touch.calibrate import solve_calibration, targets

    w, h = 480, 320
    tg = targets(w, h)
    assert tg == [(40, 40), (440, 40), (40, 280)]
    raws = [CAL.screen_to_raw(x, y, w, h) for x, y in tg]
    got = solve_calibration(tg, raws, w, h)
    assert got.swap_xy is True
    for k in ("x_min", "x_max", "y_min", "y_max"):
        assert abs(getattr(got, k) - getattr(CAL, k)) <= 2, k
    flat = Calibration(150, 3950, 3800, 250, False)
    got = solve_calibration(tg, [flat.screen_to_raw(x, y, w, h) for x, y in tg], w, h)
    assert got.swap_xy is False
    for k in ("x_min", "x_max", "y_min", "y_max"):
        assert abs(getattr(got, k) - getattr(flat, k)) <= 2, k


def test_save_calibration_keeps_other_keys(tmp_path: Path) -> None:
    import json

    from jabuka_touch import config
    from jabuka_touch.calibrate import save_calibration

    p = tmp_path / "jabuka-touch.json"
    p.write_text(json.dumps({"night": True, "custom": 1, "touch": {"device_name": "X"}}))
    save_calibration(p, Calibration(1, 2, 3, 4, False))
    data = json.loads(p.read_text())
    assert data["night"] is True and data["custom"] == 1
    assert data["touch"] == {
        "device_name": "X",
        "x_min": 1,
        "x_max": 2,
        "y_min": 3,
        "y_max": 4,
        "swap_xy": False,
    }
    cfg = config.load(p)
    assert cfg.night is True and cfg.touch.x_max == 2 and cfg.touch.swap_xy is False


def test_run_calibration_with_fake_display_and_reader(tmp_path: Path) -> None:
    from jabuka_touch.calibrate import run_calibration, targets

    clock = ManualClock(0.0)
    shown = []

    class Display:
        width, height = 480, 320

        def show(self, frame):
            shown.append(frame)

    pending = [touchin.Tap(0, 0, *CAL.screen_to_raw(x, y, 480, 320)) for x, y in targets(480, 320)]

    class Reader:
        def poll(self, timeout):
            clock.advance(1.0)
            return [pending.pop(0)] if pending else []

    cal = run_calibration(
        Display(), Reader(), tmp_path / "c.json", lambda w, h, t, txt, night: (t, txt), clock=clock
    )
    assert cal is not None and cal.swap_xy is True
    assert len(shown) == 4 and "enregistrée" in shown[-1][1]
    assert (tmp_path / "c.json").exists()

    clock2 = ManualClock(0.0)

    class Idle:
        def poll(self, timeout):
            clock2.advance(5.0)
            return []

    assert (
        run_calibration(Display(), Idle(), tmp_path / "d.json", lambda *a: a, clock=clock2) is None
    )
    assert not (tmp_path / "d.json").exists()
