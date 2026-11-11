"""Main loop: touch -> UI -> render (only when the view changed) -> framebuffer band write.

The loop never blocks on a command (actions run on the worker thread, status on the collector
thread). tty1 is in KD_GRAPHICS while it runs; KD_TEXT is restored on exit, SIGTERM and crash
(and by ExecStopPost). A missing framebuffer or touch device is retried, never fatal.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable

log = logging.getLogger("jabuka_touch.app")

FB_RETRY_S = 10.0
POLL_S = 0.2


class App:
    def __init__(
        self,
        *,
        display_factory: Callable[[], object | None],
        touch_reader,
        collector,
        worker,
        ui,
        renderer: Callable,
        console,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.display_factory = display_factory
        self.touch = touch_reader
        self.collector = collector
        self.worker = worker
        self.ui = ui
        self.renderer = renderer
        self.console = console
        self.clock = clock
        self.fb = None
        self.next_fb_try = 0.0
        self.last_view = None
        self.stop_ev = threading.Event()
        self.frames = 0

    def _ensure_display(self) -> None:
        if self.fb is not None:
            return
        now = self.clock()
        if now < self.next_fb_try:
            return
        self.next_fb_try = now + FB_RETRY_S
        fb = self.display_factory()
        if fb is None:
            return
        self.fb = fb
        if (fb.width, fb.height) != (self.ui.w, self.ui.h):
            self.ui.resize(fb.width, fb.height)
            det = getattr(self.touch, "detector", None)
            if det is not None:
                det.w, det.h = fb.width, fb.height
        self.last_view = None
        log.info("écran : %s %dx%d", getattr(fb, "path", "?"), fb.width, fb.height)

    def step(self, poll_s: float = POLL_S) -> None:
        for tap in self.touch.poll(poll_s):
            self.ui.on_tap(tap.x, tap.y)
        self.ui.tick()
        self._ensure_display()
        snap = self.collector.latest()
        view = self.ui.view_key(snap)
        if self.fb is None or view == self.last_view:
            return
        try:
            frame = self.renderer(view, self.ui.w, self.ui.h)
            self.fb.show(frame)
            self.frames += 1
            self.last_view = view
        except OSError as e:
            log.warning("écran : écriture impossible (%s), nouvel essai", e)
            try:
                self.fb.close()
            finally:
                self.fb = None

    def stop(self, *_args) -> None:
        self.stop_ev.set()

    def run(self) -> int:
        try:
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        except ValueError:  # not the main thread (tests)
            pass
        rc = 0
        try:
            self.console.graphics()
            self.collector.start()
            while not self.stop_ev.is_set():
                self.step()
        except Exception:  # noqa: BLE001 - logged, then exit 1 so Restart=on-failure applies
            log.exception("menu : erreur fatale")
            rc = 1
        finally:
            self.console.text()
            try:
                self.collector.stop()
            except Exception:  # noqa: BLE001
                pass
            if self.fb is not None:
                try:
                    self.fb.close()
                except OSError:
                    pass
        return rc
