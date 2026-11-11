"""Self-test: render every screen to PNG and replay the tracer scenario.

    cd touch && python3 -m jabuka_touch selftest --out DIR      (system python with Pillow)

The tracer scenario (also used in-process by the tests with a fake renderer): raw touch events
for SYSTÈME -> REDÉMARRER SERVICES -> OUI written to a file read by TouchReader, a file
framebuffer, a FakeRunner and a manual clock; the restart argv must be the only command run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import actions, config, touchin
from .app import App
from .fb import FileFrameBuffer
from .status import KEYS, LABELS, Item, Snapshot
from .ui import UI

RESTART_ARGV = [
    "systemctl",
    "restart",
    "jabuka-ingest-fastnet.service",
    "jabuka-core.service",
]


class ManualClock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeConsole:
    def __init__(self):
        self.calls: list[str] = []

    def graphics(self) -> bool:
        self.calls.append("graphics")
        return True

    def text(self) -> bool:
        self.calls.append("text")
        return True


class StaticCollector:
    """Collector stand-in: a fixed snapshot."""

    def __init__(self, snap: Snapshot | None):
        self.snap = snap
        self.extra: set[str] = set()

    def latest(self) -> Snapshot | None:
        return self.snap

    def set_extra(self, names: set[str]) -> None:
        self.extra = set(names)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


SAMPLE = {
    "bus": ("ok", "ok 42 tr/s", "Fastnet ok, 42 trames/s"),
    "gps": ("ok", "3D 9 sat", "gpsd 127.0.0.1:2947, 9 satellites, chrony GPS Normal"),
    "wind": ("warn", "GRIB", "vent du fichier météo (bus muet)"),
    "pack": ("ok", "ICON-EU 06Z", "pack météo ok"),
    "route": ("ok", "v12 · 3 min", "route v12 calculée il y a 3 min"),
    "wifi": ("ok", "AP · 2", "point d'accès jabuka, 2 clients"),
    "power": ("bad", "sous-tension !", "throttled=0x50005"),
    "temp": ("warn", "72 °C", "CPU 72,4 °C"),
    "disk": ("ok", "11,2 Go libres", "/var/lib/jabuka : 11,2 Go libres (78 %)"),
    "services": ("unknown", "?", "systemctl muet"),
}


def sample_snapshot(t: float = 100.0, demo: bool = False, version: int = 1) -> Snapshot:
    items = tuple(Item(k, LABELS[k], *SAMPLE[k]) for k in KEYS)
    return Snapshot(items, version, t, demo=demo)


def tap_bytes(cal: touchin.Calibration, x: float, y: float, w: int = 480, h: int = 320) -> bytes:
    """Raw ADS7846-like events of one press at screen (x, y): 3 samples + release."""
    rx, ry = cal.screen_to_raw(x, y, w, h)
    ev = touchin.pack_event
    out = [
        ev(touchin.EV_ABS, touchin.ABS_X, rx),
        ev(touchin.EV_ABS, touchin.ABS_Y, ry),
        ev(touchin.EV_ABS, touchin.ABS_PRESSURE, 200),
        ev(touchin.EV_KEY, touchin.BTN_TOUCH, 1),
        ev(touchin.EV_SYN, touchin.SYN_REPORT, 0),
        ev(touchin.EV_ABS, touchin.ABS_X, rx + 3),
        ev(touchin.EV_SYN, touchin.SYN_REPORT, 0),
        ev(touchin.EV_ABS, touchin.ABS_X, rx - 2),
        ev(touchin.EV_ABS, touchin.ABS_Y, ry + 2),
        ev(touchin.EV_SYN, touchin.SYN_REPORT, 0),
        ev(touchin.EV_ABS, touchin.ABS_X, rx + 900),  # release glitch, dropped
        ev(touchin.EV_SYN, touchin.SYN_REPORT, 0),
        ev(touchin.EV_KEY, touchin.BTN_TOUCH, 0),
        ev(touchin.EV_ABS, touchin.ABS_PRESSURE, 0),
        ev(touchin.EV_SYN, touchin.SYN_REPORT, 0),
    ]
    return b"".join(out)


def centre_of(ui: UI, bid: str) -> tuple[float, float]:
    b = next(b for b in ui.buttons() if b.id == bid)
    return b.centre


def run_tracer(out_dir: Path | str, renderer) -> dict:
    """SYSTÈME -> REDÉMARRER SERVICES -> OUI through raw events, file fb, FakeRunner."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = config.Config()
    clock = ManualClock(100.0)
    runner = actions.FakeRunner()
    console = FakeConsole()
    registry = actions.build_registry(runner, console, cfg, out / "touch.json")
    worker = actions.Worker(registry)
    ui = UI(clock, cfg, worker.submit, worker.is_busy, state=worker.state, wall=lambda: 0.0)
    cal = touchin.Calibration()
    events = out / "touch-events.bin"
    events.write_bytes(b"")
    det = touchin.TapDetector(cal, 480, 320, cfg.touch.debounce_s)
    reader = touchin.TouchReader(lambda: str(events), det, clock=clock, sleep=lambda s: None)
    fbpath = out / "fb.raw"
    if fbpath.exists():
        fbpath.unlink()
    app = App(
        display_factory=lambda: FileFrameBuffer(fbpath),
        touch_reader=reader,
        collector=StaticCollector(sample_snapshot(clock())),
        worker=worker,
        ui=ui,
        renderer=renderer,
        console=console,
        clock=clock,
    )
    app.step(0)
    screens = [ui.screen]
    for bid in ("system", "restart_services", "yes"):
        clock.advance(1.0)
        x, y = centre_of(ui, bid)
        with events.open("ab") as f:
            f.write(tap_bytes(cal, x, y))
        app.step(0)
        screens.append(ui.screen)
    worker.wait(10.0)
    clock.advance(1.0)
    app.step(0)
    if app.fb is not None:
        app.fb.close()
    return {
        "calls": runner.calls,
        "screens": screens,
        "fb": fbpath,
        "frames": app.frames,
        "result": worker.state(),
    }


def screen_views(clock: ManualClock | None = None) -> list[tuple[str, object]]:
    """(name, View) of every screen state."""
    clock = clock or ManualClock(100.0)
    out: list[tuple[str, object]] = []

    def make(night=False, demo=False, state=None):
        cfg = config.Config(night=night)
        ui = UI(
            clock,
            cfg,
            lambda a: True,
            lambda: False,
            state=lambda: state,
            wall=lambda: 0.0,
        )
        return ui, sample_snapshot(clock(), demo=demo)

    ui, snap = make()
    out.append(("home", ui.view(snap)))
    ui, snap = make(night=True)
    out.append(("home-night", ui.view(snap)))
    ui, snap = make(demo=True)
    out.append(("home-demo", ui.view(snap)))
    for screen in ("details", "prep", "journal", "demo", "system"):
        ui, snap = make()
        ui.go(screen)
        out.append((screen, ui.view(snap)))
    ui, snap = make(night=True)
    ui.go("system")
    out.append(("system-night", ui.view(snap)))
    for action in ("restart_services", "terminal", "reboot", "poweroff"):
        ui, snap = make()
        ui.go("system")
        ui.open_confirm(action)
        out.append((f"confirm-{action}", ui.view(snap)))
    return out


def main(out_dir: str) -> int:
    import numpy as np
    from PIL import Image

    from . import render

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        views = screen_views()
        for name, view in views:
            arr = render.render(view)
            assert arr.shape == (view.h, view.w, 3), arr.shape
            Image.fromarray(arr).save(out / f"{name}.png")
        demo_view = dict(views)["home-demo"]
        px = render.render(demo_view)[2, 2]
        assert tuple(int(v) for v in px) == render.DAY["demo"], f"bandeau DÉMO : {px}"
        res = run_tracer(out / "tracer", render.render)
        assert res["calls"] == [RESTART_ARGV], f"commandes du traceur : {res['calls']}"
        assert res["screens"] == ["home", "system", "confirm", "system"], res["screens"]
        raw = np.frombuffer(res["fb"].read_bytes(), dtype="<u2")
        assert raw.size == 480 * 320 and raw.any(), "framebuffer non écrit"
    except Exception as e:  # noqa: BLE001 - a selftest reports every failure as text
        print(f"selftest : ÉCHEC : {type(e).__name__}: {e}")
        return 1
    print(f"selftest : ok ({len(views)} écrans) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "selftest-out"))
