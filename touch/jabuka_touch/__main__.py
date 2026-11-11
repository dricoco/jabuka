"""python3 -m jabuka_touch [run | restore-console | selftest --out DIR | status | calibrate |
race-mode]  (system python, from /opt/jabuka-touch)."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from . import actions, config, fb, status, touchin
from .app import App
from .console import Console
from .ui import UI


def _logging() -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )


def calibration(cfg: config.Config) -> touchin.Calibration:
    t = cfg.touch
    return touchin.Calibration(t.x_min, t.x_max, t.y_min, t.y_max, t.swap_xy)


def make_reader(cfg: config.Config, paths: config.Paths, w: int = 480, h: int = 320):
    det = touchin.TapDetector(calibration(cfg), w, h, cfg.touch.debounce_s)
    return touchin.TouchReader(
        lambda: touchin.find_device(paths.sys_input, cfg.touch.device_name, paths.dev_input), det
    )


def make_display(cfg: config.Config, paths: config.Paths):
    return fb.open_display(paths.proc_fb, paths.sys_graphics, paths.dev, cfg.fb_name)


def make_collector(runner, cfg: config.Config, paths: config.Paths) -> status.Collector:
    return status.Collector(runner)


def make_registry(runner, console, cfg: config.Config, paths: config.Paths, collector):
    return actions.build_registry(runner, console, cfg, paths.config, save=config.save)


def build(paths: config.Paths | None = None) -> App:
    from . import render  # Pillow: only the real run needs it

    paths = paths or config.Paths()
    cfg = config.load(paths.config)
    runner = actions.Runner()
    console = Console(paths.tty)
    collector = make_collector(runner, cfg, paths)
    worker = actions.Worker(make_registry(runner, console, cfg, paths, collector))
    ui = UI(
        time.monotonic,
        cfg,
        worker.submit,
        worker.is_busy,
        state=worker.state,
        set_extra=collector.set_extra,
    )
    return App(
        display_factory=lambda: make_display(cfg, paths),
        touch_reader=make_reader(cfg, paths),
        collector=collector,
        worker=worker,
        ui=ui,
        renderer=render.render,
        console=console,
    )


def cmd_run(_args) -> int:
    try:
        app = build()
    except Exception:  # noqa: BLE001 - logged; exit 1 for Restart=on-failure
        logging.getLogger("jabuka_touch").exception("démarrage du menu impossible")
        Console().text()
        return 1
    return app.run()


def cmd_restore_console(_args) -> int:
    Console().text()
    return 0


def cmd_selftest(args) -> int:
    from . import selftest

    return selftest.main(args.out)


def cmd_status(_args) -> int:
    paths = config.Paths()
    cfg = config.load(paths.config)
    collector = make_collector(actions.Runner(), cfg, paths)
    snap = collector.collect_once()
    for it in snap.items:
        level = {"ok": "OK", "warn": "ATTENTION", "bad": "PROBLÈME"}.get(it.level, "INCONNU")
        print(f"{it.label:<9} {level:<10} {it.short}" + (f" — {it.detail}" if it.detail else ""))
    if snap.demo:
        print("DÉMO en cours (retour : sudo jabuka-touch course)")
    return 0


COMMANDS = {
    "run": cmd_run,
    "restore-console": cmd_restore_console,
    "selftest": cmd_selftest,
    "status": cmd_status,
}


def main(argv: list[str] | None = None) -> int:
    _logging()
    p = argparse.ArgumentParser(prog="jabuka_touch", description="menu tactile Jabuka")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="le menu (défaut)")
    sub.add_parser("restore-console", help="remet tty1 en mode texte")
    st = sub.add_parser("selftest", help="rend tous les écrans en PNG et rejoue le traceur")
    st.add_argument("--out", required=True)
    sub.add_parser("status", help="état du système en texte")
    args = p.parse_args(argv)
    return COMMANDS[args.cmd or "run"](args)


if __name__ == "__main__":
    sys.exit(main())
