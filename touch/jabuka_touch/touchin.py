"""ADS7846 touch panel input (evdev, read raw: no X server, no libinput).

64-bit Linux input_event = struct timeval (2 x int64) + type u16 + code u16 + value s32 = 24 bytes.
A press is the samples between BTN_TOUCH 1 and 0; the tap is their median (the last sample is a
release glitch on resistive panels and is dropped), mapped through the calibration.
"""

from __future__ import annotations

import errno
import logging
import os
import select
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

log = logging.getLogger("jabuka_touch.touch")

EVENT_FMT = "=qqHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)
assert EVENT_SIZE == 24

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
ABS_X, ABS_Y, ABS_PRESSURE = 0, 1, 24
BTN_TOUCH = 330


class Event(NamedTuple):
    sec: int
    usec: int
    type: int
    code: int
    value: int


class Tap(NamedTuple):
    x: int
    y: int
    raw_x: int
    raw_y: int


def pack_event(type_: int, code: int, value: int, sec: int = 0, usec: int = 0) -> bytes:
    return struct.pack(EVENT_FMT, sec, usec, type_, code, value)


def parse_events(buf: bytes) -> tuple[list[Event], bytes]:
    """Whole events of ``buf`` and the trailing partial record (kept for the next read)."""
    n = len(buf) // EVENT_SIZE
    events = [Event(*struct.unpack_from(EVENT_FMT, buf, i * EVENT_SIZE)) for i in range(n)]
    return events, bytes(buf[n * EVENT_SIZE :])


@dataclass(frozen=True)
class Calibration:
    x_min: float = 3936
    x_max: float = 227
    y_min: float = 268
    y_max: float = 3880
    swap_xy: bool = True

    def map(self, raw_x: float, raw_y: float, w: int, h: int) -> tuple[int, int]:
        a, b = (raw_y, raw_x) if self.swap_xy else (raw_x, raw_y)
        x = (a - self.x_min) / (self.x_max - self.x_min) * (w - 1)
        y = (b - self.y_min) / (self.y_max - self.y_min) * (h - 1)
        return (min(max(round(x), 0), w - 1), min(max(round(y), 0), h - 1))

    def screen_to_raw(self, x: float, y: float, w: int, h: int) -> tuple[int, int]:
        a = self.x_min + x / (w - 1) * (self.x_max - self.x_min)
        b = self.y_min + y / (h - 1) * (self.y_max - self.y_min)
        return (round(b), round(a)) if self.swap_xy else (round(a), round(b))


def _median(values: list[int]) -> int:
    s = sorted(values)
    return s[len(s) // 2]


class TapDetector:
    """Turns input events into taps (one per press), with debounce."""

    def __init__(self, cal: Calibration, w: int, h: int, debounce_s: float = 0.25):
        self.cal, self.w, self.h, self.debounce_s = cal, w, h, debounce_s
        self.down = False
        self.saw_btn = False
        self.cur_x: int | None = None
        self.cur_y: int | None = None
        self.samples: list[tuple[int, int]] = []
        self.last_tap: float | None = None

    def _press(self) -> None:
        self.down = True
        self.samples = []

    def _release(self, now: float) -> Tap | None:
        self.down = False
        samples, self.samples = self.samples, []
        if not samples:
            return None
        if len(samples) >= 3:
            samples = samples[:-1]
        rx = _median([s[0] for s in samples])
        ry = _median([s[1] for s in samples])
        if self.last_tap is not None and now - self.last_tap < self.debounce_s:
            return None
        self.last_tap = now
        x, y = self.cal.map(rx, ry, self.w, self.h)
        return Tap(x, y, rx, ry)

    def feed(self, ev: Event, now: float) -> Tap | None:
        if ev.type == EV_KEY and ev.code == BTN_TOUCH:
            self.saw_btn = True
            if ev.value and not self.down:
                self._press()
            elif not ev.value and self.down:
                return self._release(now)
        elif ev.type == EV_ABS:
            if ev.code == ABS_X:
                self.cur_x = ev.value
            elif ev.code == ABS_Y:
                self.cur_y = ev.value
            elif ev.code == ABS_PRESSURE and not self.saw_btn:
                if ev.value > 0 and not self.down:
                    self._press()
                elif ev.value <= 0 and self.down:
                    return self._release(now)
        elif ev.type == EV_SYN and ev.code == SYN_REPORT:
            if self.down and self.cur_x is not None and self.cur_y is not None:
                self.samples.append((self.cur_x, self.cur_y))
        return None


def find_device(
    sys_input: Path | str, name: str, dev_input: Path | str = "/dev/input"
) -> str | None:
    """/dev/input/eventN of the input device whose sysfs name is ``name``."""
    root = Path(sys_input)
    try:
        nodes = sorted(
            (p for p in root.iterdir() if p.name.startswith("event")),
            key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 1 << 30,
        )
    except OSError:
        return None
    for node in nodes:
        try:
            if (node / "device" / "name").read_text().strip() == name:
                return str(Path(dev_input) / node.name)
        except OSError:
            continue
    return None


class TouchReader:
    """Non-blocking reader of the touch device; poll() returns taps. A missing or vanished
    device is retried every ``retry_s`` seconds and never raises into the display loop."""

    def __init__(
        self,
        find: Callable[[], str | None],
        detector: TapDetector,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        retry_s: float = 5.0,
    ):
        self.find, self.detector, self.clock, self.sleep = find, detector, clock, sleep
        self.retry_s = retry_s
        self.fd: int | None = None
        self.next_try = 0.0
        self.rest = b""
        self.warned = False

    def _open(self) -> None:
        now = self.clock()
        if now < self.next_try:
            return
        self.next_try = now + self.retry_s
        path = self.find()
        if path is None:
            if not self.warned:
                log.warning(
                    "toucher : périphérique introuvable, nouvel essai toutes les %g s", self.retry_s
                )
                self.warned = True
            return
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            self.rest = b""
            self.warned = False
            log.info("toucher : %s ouvert", path)
        except OSError as e:
            if not self.warned:
                log.warning("toucher : %s (%s)", path, e)
                self.warned = True

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def poll(self, timeout: float) -> list[Tap]:
        if self.fd is None:
            self._open()
            if self.fd is None:
                self.sleep(timeout)
                return []
        try:
            p = select.poll()
            p.register(self.fd, select.POLLIN)
            if not p.poll(int(timeout * 1000)):
                return []
            data = os.read(self.fd, EVENT_SIZE * 64)
        except BlockingIOError:
            return []
        except OSError as e:
            if e.errno != errno.EAGAIN:
                log.warning("toucher : lecture impossible (%s), réouverture", e)
                self.close()
            return []
        if not data:  # plain file (tests): end of the recorded events
            return []
        events, self.rest = parse_events(self.rest + data)
        now = self.clock()
        taps = []
        for ev in events:
            tap = self.detector.feed(ev, now)
            if tap is not None:
                taps.append(tap)
        return taps
