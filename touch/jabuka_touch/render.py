"""Pillow rendering of a ui.View into an HxWx3 uint8 array (the only Pillow module).

Long-stable Pillow/numpy APIs only (the Pi has Pillow 11.1 / numpy 2.2, the laptop newer):
ImageFont.truetype, ImageDraw.text/textlength/textbbox/rectangle/rounded_rectangle.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONTS = {
    "bold": "DejaVuSans-Bold.ttf",
    "regular": "DejaVuSans.ttf",
    "mono": "DejaVuSansMono.ttf",
}

DAY = {
    "bg": (12, 12, 14),
    "text": (255, 255, 255),
    "dim": (170, 170, 170),
    "header": (40, 40, 46),
    "demo": (192, 0, 192),
    "stale": (230, 40, 40),
    "ok": (0x1B, 0x7F, 0x3A),
    "warn": (0xD9, 0x77, 0x06),
    "bad": (0xC6, 0x28, 0x28),
    "unknown": (0x55, 0x55, 0x55),
    "nav": (38, 70, 110),
    "action": (60, 72, 80),
    "risky": (120, 40, 30),
    "disabled": (45, 45, 45),
    "disabled_text": (110, 110, 110),
    "yes": (0x1B, 0x7F, 0x3A),
    "no": (0x55, 0x55, 0x55),
    "tile_text": (255, 255, 255),
}
NIGHT = {
    "bg": (0, 0, 0),
    "text": (200, 30, 30),
    "dim": (120, 20, 20),
    "header": (20, 0, 0),
    "demo": (96, 0, 96),
    "stale": (255, 40, 40),
    "ok": (10, 50, 22),
    "warn": (90, 50, 4),
    "bad": (90, 14, 14),
    "unknown": (34, 34, 34),
    "nav": (30, 10, 10),
    "action": (36, 12, 12),
    "risky": (60, 10, 10),
    "disabled": (16, 16, 16),
    "disabled_text": (70, 20, 20),
    "yes": (10, 50, 22),
    "no": (34, 34, 34),
    "tile_text": (230, 60, 60),
}
DEMO_BANNER = "DÉMO — bateau simulé"


@lru_cache(maxsize=64)
def font(size: int, kind: str = "bold"):
    try:
        return ImageFont.truetype(str(FONT_DIR / FONTS[kind]), size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1
            return ImageFont.load_default()


def _w(draw: ImageDraw.ImageDraw, text: str, f) -> float:
    return draw.textlength(text, font=f)


def ellipsize(draw, text: str, f, maxw: float) -> str:
    if _w(draw, text, f) <= maxw:
        return text
    while text and _w(draw, text + "…", f) > maxw:
        text = text[:-1]
    return text + "…"


def fit_line(draw, text: str, maxw: float, sizes=(20, 17, 15, 13), kind="bold"):
    """(font, text) of the largest size that fits, else the smallest size ellipsized."""
    for s in sizes:
        f = font(s, kind)
        if _w(draw, text, f) <= maxw:
            return f, text
    f = font(sizes[-1], kind)
    return f, ellipsize(draw, text, f, maxw)


def wrap(draw, text: str, f, maxw: float) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            cand = f"{cur} {word}".strip()
            if _w(draw, cand, f) <= maxw or not cur:
                cur = cand
            else:
                out.append(cur)
                cur = word
        out.append(cur)
    return out


def _label_lines(draw, label: str, maxw: float, maxh: float):
    """Button label: 22 px on one line, else 16 px, else split on spaces (2 lines)."""
    if "\n" not in label:
        for s in (22, 16):
            f = font(s)
            if _w(draw, label, f) <= maxw:
                return f, [label]
    for s in (22, 18, 16, 14):
        f = font(s)
        lines = wrap(draw, label, f, maxw)
        if all(_w(draw, ln, f) <= maxw for ln in lines) and len(lines) * (s + 4) <= maxh:
            return f, lines
    f = font(14)
    return f, [ellipsize(draw, ln, f, maxw) for ln in wrap(draw, label, f, maxw)[:2]]


def _centered(draw, rect, lines, f, fill) -> None:
    x0, y0, x1, y1 = rect
    lh = f.size + 4 if hasattr(f, "size") else 18
    total = lh * len(lines)
    y = (y0 + y1) / 2 - total / 2
    for ln in lines:
        w = _w(draw, ln, f)
        draw.text(((x0 + x1) / 2 - w / 2, y), ln, font=f, fill=fill)
        y += lh


def _button(draw, b, pal) -> None:
    if b.kind == "area":
        return
    x0, y0, x1, y1 = b.rect
    rect = (x0 + 3, y0 + 3, x1 - 4, y1 - 4)
    if not b.enabled:
        fill, txt = pal["disabled"], pal["disabled_text"]
    elif b.id == "yes":
        fill, txt = pal["yes"], pal["text"]
    elif b.id == "no":
        fill, txt = pal["no"], pal["text"]
    elif b.kind == "action" and b.risky:
        fill, txt = pal["risky"], pal["text"]
    elif b.kind == "action":
        fill, txt = pal["action"], pal["text"]
    else:
        fill, txt = pal["nav"], pal["text"]
    draw.rounded_rectangle(rect, radius=8, fill=fill)
    f, lines = _label_lines(draw, b.label, rect[2] - rect[0] - 10, rect[3] - rect[1] - 6)
    _centered(draw, rect, lines, f, txt)


def _header(draw, view, pal) -> None:
    w = view.w
    if view.demo:
        draw.rectangle((0, 0, w - 1, 35), fill=pal["demo"])
        left = DEMO_BANNER
    else:
        draw.rectangle((0, 0, w - 1, 35), fill=pal["header"])
        left = "JABUKA · COURSE"
    f = font(20)
    draw.text((8, 6), left, font=f, fill=pal["text"])
    tw = _w(draw, view.clock, f)
    draw.text((w - 8 - tw, 6), view.clock, font=f, fill=pal["text"])
    mid_x0 = 8 + _w(draw, left, f) + 12
    mid_x1 = w - 8 - tw - 12
    mid = None
    color = pal["text"]
    if view.stale:
        mid, color = "ÉTAT FIGÉ", pal["stale"]
    elif view.busy:
        mid = f"… {view.busy}"
    if mid and mid_x1 - mid_x0 > 30:
        fm, txt = fit_line(draw, mid, mid_x1 - mid_x0, sizes=(18, 15, 13))
        draw.text((mid_x0, 8), txt, font=fm, fill=color)


def _tiles(draw, view, pal) -> None:
    top, bottom = 36, round(236 * view.h / 320)
    rows = 5
    th = (bottom - top) / rows
    cw = view.w / 2
    for i, (label, level, short) in enumerate(view.tiles):
        c, r = i % 2, i // 2
        x0, y0 = c * cw, top + r * th
        rect = (x0 + 2, y0 + 2, x0 + cw - 3, y0 + th - 3)
        draw.rounded_rectangle(rect, radius=5, fill=pal.get(level, pal["unknown"]))
        f, txt = fit_line(draw, f"{label} {short}", cw - 16, sizes=(20, 17, 15))
        h = f.size if hasattr(f, "size") else 16
        draw.text((x0 + 8, y0 + th / 2 - h / 2 - 2), txt, font=f, fill=pal["tile_text"])


def _text_lines(
    draw, view, pal, y0: float, y1: float, size: int = 15, kind="regular", wrap_lines=False
) -> None:
    f = font(size, kind)
    lh = size + 4
    y = y0 + 2
    maxw = view.w - 16
    lines = view.lines
    if wrap_lines:
        lines = [part for ln in view.lines for part in wrap(draw, ln, f, maxw)]
    for ln in lines:
        if y + lh > y1:
            break
        draw.text((8, y), ellipsize(draw, ln, f, maxw), font=f, fill=pal["text"])
        y += lh


def _result_line(view) -> str:
    if view.result is None:
        return ""
    state, title, lines = view.result
    tag = {"running": "…", "ok": "OK", "fail": "ÉCHEC"}.get(state, state)
    last = lines[-1] if lines else ""
    return f"{title} : {tag}" + (f" — {last}" if last else "")


def _confirm(draw, view, pal) -> None:
    w = view.w
    f = font(22)
    y = 42
    for ln in wrap(draw, view.title, f, w - 20)[:2]:
        draw.text((10, y), ln, font=f, fill=pal["text"])
        y += 27
    fd = font(16, "regular")
    for ln in wrap(draw, view.detail, fd, w - 20)[:3]:
        if y + 20 > 150 * view.h / 320:
            break
        draw.text((10, y), ln, font=fd, fill=pal["dim"])
        y += 20
    if view.countdown is not None:
        txt = f"Annulation automatique dans {view.countdown} s"
        fc = font(18, "regular")
        tw = _w(draw, txt, fc)
        draw.text((w / 2 - tw / 2, 270 * view.h / 320), txt, font=fc, fill=pal["dim"])


def render(view, w: int | None = None, h: int | None = None) -> np.ndarray:
    w = w or view.w
    h = h or view.h
    pal = NIGHT if view.night else DAY
    img = Image.new("RGB", (w, h), pal["bg"])
    draw = ImageDraw.Draw(img)
    _header(draw, view, pal)
    s = view.screen
    if s == "home":
        _tiles(draw, view, pal)
    elif s == "confirm":
        _confirm(draw, view, pal)
    elif s == "system":
        res = _result_line(view)
        if res:
            f, txt = fit_line(draw, res, w - 16, sizes=(17, 15, 13), kind="regular")
            draw.text((8, 46), txt, font=f, fill=pal["text"])
    elif s == "journal":
        _text_lines(draw, view, pal, 36, 236 * h / 320, size=14, kind="mono")
    elif s == "prep":
        _text_lines(draw, view, pal, 36, 152 * h / 320, size=14, kind="regular", wrap_lines=True)
    elif s == "demo":
        _text_lines(draw, view, pal, 38, 236 * h / 320, size=15, kind="regular", wrap_lines=True)
    else:
        _text_lines(draw, view, pal, 38, 236 * h / 320, size=15, kind="regular")
    for b in view.buttons:
        _button(draw, b, pal)
    return np.asarray(img, dtype=np.uint8).reshape(h, w, 3)


def render_cross(w: int, h: int, target: tuple[int, int], text: str, night: bool = False):
    """Calibration screen: a large cross at ``target`` and an instruction."""
    pal = NIGHT if night else DAY
    img = Image.new("RGB", (w, h), pal["bg"])
    draw = ImageDraw.Draw(img)
    x, y = target
    draw.line((x - 25, y, x + 25, y), fill=pal["text"], width=3)
    draw.line((x, y - 25, x, y + 25), fill=pal["text"], width=3)
    draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline=pal["stale"], width=2)
    f = font(20)
    lines = wrap(draw, text, f, w - 40)
    _centered(draw, (0, h / 2 - 40, w, h / 2 + 40), lines, f, pal["text"])
    return np.asarray(img, dtype=np.uint8).reshape(h, w, 3)
