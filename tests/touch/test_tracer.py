"""Tracer: raw touch events SYSTÈME -> REDÉMARRER SERVICES -> OUI run the whitelisted restart and
draw on a file framebuffer (fake renderer: no Pillow in the dev venvs). Also the console."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from jabuka_touch import console as console_mod
from jabuka_touch.selftest import RESTART_ARGV, run_tracer


def fake_render(view, w, h):
    arr = np.zeros((h, w, 3), np.uint8)
    arr[: 10 + 10 * len(view.screen)] = (255, 255, 255)
    return arr


def test_tracer_restart_through_raw_events(tmp_path: Path) -> None:
    res = run_tracer(tmp_path, fake_render)
    assert res["calls"] == [RESTART_ARGV]
    assert res["screens"] == ["home", "system", "confirm", "system"]
    assert res["result"].state == "ok"
    data = np.frombuffer(res["fb"].read_bytes(), dtype="<u2")
    assert data.size == 480 * 320 and data.any()
    assert res["frames"] >= 4


def test_console_modes_and_text_never_raises(tmp_path: Path) -> None:
    calls = []
    tty = tmp_path / "tty1"
    tty.write_text("")
    c = console_mod.Console(tty, ioctl=lambda fd, req, mode: calls.append((req, mode)))
    assert c.graphics() and c.text()
    assert calls == [(0x4B3A, 1), (0x4B3A, 0)]
    missing = console_mod.Console(tmp_path / "absent", ioctl=lambda *a: None)
    assert missing.text() is False
    assert missing.graphics() is False

    def bad(*a):
        raise OSError("ENOTTY")

    assert console_mod.Console(tty, ioctl=bad).text() is False


@pytest.mark.parametrize("fail_at", ["render"])
def test_app_crash_restores_console(tmp_path: Path, fail_at: str) -> None:
    from jabuka_touch.app import App
    from jabuka_touch.fb import FileFrameBuffer
    from jabuka_touch.selftest import FakeConsole, ManualClock, StaticCollector, sample_snapshot

    class Reader:
        def poll(self, t):
            return []

    class UIStub:
        w, h = 480, 320

        def tick(self):
            pass

        def view_key(self, snap):
            return 1

    def boom(view, w, h):
        raise RuntimeError("rendu cassé")

    con = FakeConsole()
    app = App(
        display_factory=lambda: FileFrameBuffer(tmp_path / "fb.raw"),
        touch_reader=Reader(),
        collector=StaticCollector(sample_snapshot()),
        worker=None,
        ui=UIStub(),
        renderer=boom,
        console=con,
        clock=ManualClock(),
    )
    assert app.run() == 1
    assert con.calls == ["graphics", "text"]
