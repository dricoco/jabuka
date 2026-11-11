"""Touch calibration: three crosses, the median raw sample of each press, a linear solve.

    sudo jabuka-touch calibrate      (stops the menu, calibrates, starts the menu again)

The result goes into the "touch" section of /etc/jabuka-touch.json; every other key is kept.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from .config import write_json
from .touchin import Calibration

log = logging.getLogger("jabuka_touch.calibrate")

MARGIN = 40
INSTRUCTION = "Touchez le centre de la croix"


def targets(w: int, h: int) -> list[tuple[int, int]]:
    return [(MARGIN, MARGIN), (w - MARGIN, MARGIN), (MARGIN, h - MARGIN)]


def solve_calibration(
    tgts: list[tuple[float, float]], raws: list[tuple[float, float]], w: int, h: int
) -> Calibration:
    """Calibration from three presses at top-left, top-right and bottom-left targets.

    swap_xy: the raw axis that moves most between the first two targets (screen x changes)
    drives screen x. Each axis is then extrapolated linearly to pixel 0 and W-1 / H-1."""
    (x0, y0), (x1, _), (_, y2) = tgts
    r0, r1, r2 = raws
    swap = abs(r1[1] - r0[1]) > abs(r1[0] - r0[0])

    def a(r):
        return r[1] if swap else r[0]

    def b(r):
        return r[0] if swap else r[1]

    a_left, a_right = (a(r0) + a(r2)) / 2.0, a(r1)
    b_top, b_bottom = (b(r0) + b(r1)) / 2.0, b(r2)
    if x1 == x0 or y2 == y0 or a_right == a_left or b_bottom == b_top:
        raise ValueError("calibration impossible : appuis identiques")
    ka = (a_right - a_left) / (x1 - x0)
    kb = (b_bottom - b_top) / (y2 - y0)
    return Calibration(
        x_min=round(a_left - ka * x0),
        x_max=round(a_left + ka * (w - 1 - x0)),
        y_min=round(b_top - kb * y0),
        y_max=round(b_top + kb * (h - 1 - y0)),
        swap_xy=swap,
    )


def save_calibration(path: Path | str, cal: Calibration) -> None:
    """Write cal into the "touch" section of the config file, keeping every other key."""
    p = Path(path)
    data: dict = {}
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    touch = data.get("touch") if isinstance(data.get("touch"), dict) else {}
    touch.update(
        {
            "x_min": cal.x_min,
            "x_max": cal.x_max,
            "y_min": cal.y_min,
            "y_max": cal.y_max,
            "swap_xy": cal.swap_xy,
        }
    )
    data["touch"] = touch
    write_json(p, data)


def run_calibration(
    display,
    reader,
    cfg_path: Path | str,
    render_cross: Callable,
    *,
    night: bool = False,
    clock: Callable[[], float] = time.monotonic,
    timeout_s: float = 30.0,
    guard_s: float = 0.6,
) -> Calibration | None:
    """Draw each cross, wait for one press (raw sample), solve, save. None on timeout."""
    w, h = display.width, display.height
    tg = targets(w, h)
    raws: list[tuple[int, int]] = []
    for i, t in enumerate(tg, 1):
        display.show(render_cross(w, h, t, f"{INSTRUCTION} ({i}/3)", night))
        shown = clock()
        tap = None
        while clock() - shown < timeout_s:
            for got in reader.poll(0.2):
                if clock() - shown >= guard_s:
                    tap = got
            if tap is not None:
                break
        if tap is None:
            display.show(render_cross(w, h, (-100, -100), "Calibration abandonnée", night))
            return None
        raws.append((tap.raw_x, tap.raw_y))
        log.info("calibration : cible %s -> brut %s", t, raws[-1])
    cal = solve_calibration(tg, raws, w, h)
    save_calibration(cfg_path, cal)
    msg = f"Calibration enregistrée : {cal.x_min} {cal.x_max} {cal.y_min} {cal.y_max}"
    display.show(render_cross(w, h, (-100, -100), msg, night))
    return cal
