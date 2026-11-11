"""Screen state machine, layouts and hit-testing (no Pillow: tested in the dev venvs).

Rects are (x0, y0, x1, y1), end-exclusive, in screen pixels. A risky action always opens the
confirmation screen first (OUI/NON, auto-cancel); taps are ignored for tap_guard_s after any
screen change, and no OUI button lies under the centre of a button that opens a confirmation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

HEADER = 36

SCREENS = ("home", "details", "prep", "journal", "demo", "system", "confirm")

RISKY = frozenset(
    {
        "prerace",
        "wifi_ap",
        "wifi_phone",
        "demo_start",
        "race_mode",
        "restart_services",
        "terminal",
        "reboot",
        "poweroff",
    }
)

CONFIRM_TEXTS: dict[str, tuple[str, str]] = {
    "restart_services": ("Redémarrer les services Jabuka ?", "Navigation coupée ~30 s."),
    "terminal": (
        "Quitter le menu pour le terminal ?",
        "Retour au menu : sudo jabuka-touch (clavier USB) ou redémarrer le Pi.",
    ),
    "reboot": ("Redémarrer le Pi ?", "~1 min sans navigation."),
    "poweroff": ("ÉTEINDRE le Pi ?", "Attendre ~20 s avant de couper le courant."),
}

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Button:
    id: str
    rect: Rect
    label: str
    kind: str  # nav | action | area | toggle
    target: str = ""  # screen id (nav) or action id (action)
    enabled: bool = True

    @property
    def risky(self) -> bool:
        return self.kind == "action" and self.target in RISKY

    @property
    def opens_confirm(self) -> bool:
        return self.risky

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.rect
        return x0 <= x < x1 and y0 <= y < y1

    @property
    def centre(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.rect
        return ((x0 + x1) / 2, (y0 + y1) / 2)


@dataclass(frozen=True)
class View:
    """Everything the renderer draws; equal views draw identical frames (the view key)."""

    screen: str
    w: int
    h: int
    buttons: tuple[Button, ...]
    clock: str
    night: bool
    demo: bool
    stale: bool
    version: int
    busy: str | None = None
    tiles: tuple[tuple[str, str, str], ...] = ()
    lines: tuple[str, ...] = ()
    title: str = ""
    detail: str = ""
    countdown: int | None = None
    result: tuple[str, str, tuple[str, ...]] | None = None
    mono: bool = False


class Layout:
    """Button rects for a W x H screen (designed for 480 x 320, scaled proportionally)."""

    def __init__(self, w: int = 480, h: int = 320):
        self.w, self.h = w, h
        self.sx, self.sy = w / 480.0, h / 320.0

    def r(self, x0: float, y0: float, x1: float, y1: float) -> Rect:
        return (
            round(x0 * self.sx),
            round(y0 * self.sy),
            round(x1 * self.sx),
            round(y1 * self.sy),
        )

    def row(self, y0: float, y1: float, specs: list[tuple]) -> list[Button]:
        n = len(specs)
        out = []
        for i, spec in enumerate(specs):
            bid, label, kind, target = spec
            out.append(
                Button(bid, self.r(480 * i / n, y0, 480 * (i + 1) / n, y1), label, kind, target)
            )
        return out

    # bands (480x320 design units)
    TILES = (HEADER, 236)
    BOTTOM = (238, 320)
    CONFIRM_BTN = (150, 240)  # OUI/NON band: no confirmation-opening centre falls in OUI


def _nav(bid: str, label: str, target: str) -> tuple:
    return (bid, label, "nav", target)


def _act(bid: str, label: str) -> tuple:
    return (bid, label, "action", bid)


class UI:
    def __init__(
        self,
        clock: Callable[[], float],
        cfg,
        submit: Callable[[str], bool],
        is_busy: Callable[[], bool],
        *,
        state: Callable[[], object] | None = None,
        set_extra: Callable[[set[str]], None] | None = None,
        wall: Callable[[], float] = time.time,
        w: int = 480,
        h: int = 320,
    ):
        self.clock, self.cfg, self.submit_fn, self.is_busy = clock, cfg, submit, is_busy
        self.state = state or (lambda: None)
        self.set_extra = set_extra or (lambda names: None)
        self.wall = wall
        self.resize(w, h)
        self.screen = "home"
        self.prev = "home"
        self.confirm_action: str | None = None
        self.confirm_since = 0.0
        self.changed_at = clock()
        self.snapshot = None
        self.journal_mode = "journal"  # journal | result
        self.seen_seq = 0

    def resize(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.layout = Layout(w, h)

    # -- navigation --------------------------------------------------------------------------
    def go(self, screen: str) -> None:
        if screen not in SCREENS:
            raise ValueError(screen)
        self.screen = screen
        self.changed_at = self.clock()
        self.set_extra(self.extra_for(screen))

    def extra_for(self, screen: str) -> set[str]:
        if screen == "prep":
            return {"wifi_status"}
        if screen == "journal":
            return {"journal_prerace" if self.journal_mode == "journal" else "prerace_status"}
        return set()

    def open_confirm(self, action: str) -> None:
        self.prev = self.screen
        self.confirm_action = action
        self.confirm_since = self.clock()
        self.go("confirm")

    def close_confirm(self) -> None:
        self.confirm_action = None
        self.go(self.prev if self.prev != "confirm" else "home")

    # -- buttons -----------------------------------------------------------------------------
    def demo_active(self) -> bool:
        return bool(getattr(self.snapshot, "demo", False))

    def specs(self, screen: str) -> list[Button]:
        L = self.layout
        busy = self.is_busy()
        out: list[Button] = []
        if screen == "home":
            tiles = L.r(0, L.TILES[0], 480, L.TILES[1])
            out.append(Button("details", tiles, "", "area", "details"))
            out += L.row(
                *L.BOTTOM,
                [
                    _nav("prep", "MÉTÉO /\nWI-FI", "prep"),
                    _nav("demo", "DÉMO", "demo"),
                    _nav("system", "SYSTÈME", "system"),
                ],
            )
        elif screen == "system":
            night = "JOUR" if self.cfg.night else "NUIT"
            out += L.row(
                76,
                198,
                [
                    _act("restart_services", "REDÉMARRER SERVICES"),
                    _act("terminal", "TERMINAL"),
                    ("night_toggle", night, "action", "night_toggle"),
                ],
            )
            out += L.row(
                198,
                320,
                [
                    _nav("back", "RETOUR", "home"),
                    _act("reboot", "REDÉMARRER LE PI"),
                    _act("poweroff", "ÉTEINDRE"),
                ],
            )
        elif screen == "confirm":
            y0, y1 = L.CONFIRM_BTN
            out.append(Button("no", L.r(0, y0, 240, y1), "NON", "nav", "back"))
            out.append(Button("yes", L.r(240, y0, 480, y1), "OUI", "nav", "yes"))
        elif screen == "details":
            out += L.row(*L.BOTTOM, [_nav("back", "RETOUR", "home")])
        elif screen == "prep":
            out += L.row(
                120,
                202,
                [
                    _act("prerace", "LANCER PRERACE"),
                    _nav("journal", "JOURNAL", "journal"),
                ],
            )
            out += L.row(
                202,
                320,
                [
                    _act("wifi_ap", "WI-FI BATEAU"),
                    _act("wifi_phone", "WI-FI TÉLÉPHONE"),
                    _nav("back", "RETOUR", "home"),
                ],
            )
        elif screen == "journal":
            label = "RÉSULTAT" if self.journal_mode == "journal" else "JOURNAL"
            out += L.row(
                *L.BOTTOM,
                [
                    ("toggle", label, "toggle", ""),
                    _nav("back", "RETOUR", "prep"),
                ],
            )
        elif screen == "demo":
            specs = [
                _act("race_mode", "MODE COURSE")
                if self.demo_active()
                else _act("demo_start", "LANCER LA DÉMO")
            ]
            if self.reboot_hint():
                specs.append(_act("reboot", "REDÉMARRER LE PI"))
            specs.append(_nav("back", "RETOUR", "home"))
            out += L.row(*L.BOTTOM, specs)
        if busy:
            out = [
                Button(b.id, b.rect, b.label, b.kind, b.target, False) if b.kind == "action" else b
                for b in out
            ]
        return out

    def buttons(self) -> list[Button]:
        return self.specs(self.screen)

    def reboot_hint(self) -> bool:
        st = self.state()
        return bool(
            st is not None
            and getattr(st, "id", "") in ("demo_start", "race_mode")
            and getattr(st, "state", "") == "fail"
            and any("redémarrer le Pi" in ln for ln in getattr(st, "lines", ()))
        )

    def hit(self, x: float, y: float) -> Button | None:
        return next((b for b in self.buttons() if b.contains(x, y)), None)

    # -- input -------------------------------------------------------------------------------
    def on_tap(self, x: float, y: float) -> bool:
        """True when the tap did something."""
        now = self.clock()
        if now - self.changed_at < self.cfg.tap_guard_s:
            return False
        b = self.hit(x, y)
        if b is None or not b.enabled:
            return False
        if self.screen == "confirm":
            action = self.confirm_action
            if b.id == "yes" and action is not None:
                self.close_confirm()
                if self.is_busy():
                    return False
                return bool(self.submit_fn(action))
            self.close_confirm()
            return True
        if b.kind in ("nav", "area"):
            if b.target == "journal":
                self.journal_mode = "journal"
            self.go(b.target)
            return True
        if b.kind == "toggle":
            self.journal_mode = "result" if self.journal_mode == "journal" else "journal"
            self.go(self.screen)
            return True
        if b.kind == "action":
            if self.is_busy():
                return False
            if b.risky:
                self.open_confirm(b.target)
                return True
            return bool(self.submit_fn(b.target))
        return False

    def tick(self) -> None:
        now = self.clock()
        if self.screen == "confirm" and now - self.confirm_since >= self.cfg.confirm_timeout_s:
            self.close_confirm()
        st = self.state()
        seq = getattr(st, "seq", 0) or 0
        if st is not None and seq != self.seen_seq and getattr(st, "state", "") != "running":
            self.seen_seq = seq
            if st.id == "prerace" and st.state == "ok" and self.screen == "prep":
                self.journal_mode = "journal"
                self.go("journal")

    # -- view --------------------------------------------------------------------------------
    def countdown(self) -> int | None:
        if self.screen != "confirm":
            return None
        left = self.cfg.confirm_timeout_s - (self.clock() - self.confirm_since)
        return max(0, int(left + 0.999))

    def tiles(self, snap) -> tuple[tuple[str, str, str], ...]:
        if snap is None:
            from .status import KEYS, LABELS

            return tuple((LABELS[k], "unknown", "…") for k in KEYS)
        return tuple((i.label, i.level, i.short) for i in snap.items)

    def lines(self, snap) -> tuple[str, ...]:
        """Screen-specific text lines (filled by the screens of tasks 2 and 3)."""
        return ()

    def view(self, snap=None) -> View:
        if snap is not None:
            self.snapshot = snap
        snap = self.snapshot
        st = self.state()
        busy = getattr(st, "title", None) if getattr(st, "state", "") == "running" else None
        if busy is None and self.is_busy():
            busy = "action en cours"
        result = None
        if st is not None:
            result = (st.state, st.title, tuple(st.lines))
        title = detail = ""
        if self.screen == "confirm" and self.confirm_action:
            title, detail = CONFIRM_TEXTS.get(self.confirm_action, (self.confirm_action + " ?", ""))
        stale = snap is not None and self.clock() - snap.t > 10.0
        return View(
            screen=self.screen,
            w=self.w,
            h=self.h,
            buttons=tuple(self.buttons()),
            clock=time.strftime("%H:%M", time.localtime(self.wall())),
            night=bool(self.cfg.night),
            demo=self.demo_active(),
            stale=stale,
            version=getattr(snap, "version", 0),
            busy=busy,
            tiles=self.tiles(snap) if self.screen == "home" else (),
            lines=self.lines(snap),
            title=title,
            detail=detail,
            countdown=self.countdown(),
            result=result,
            mono=self.screen == "journal",
        )

    def view_key(self, snap=None) -> View:
        """Hashable key of everything drawn: render only when it changes."""
        return self.view(snap)
