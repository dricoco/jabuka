"""System status at a glance: ten items collected on a background thread.

Every collect step is wrapped: an exception or a timeout only turns that item unknown, the
collector never raises and never blocks the display loop.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("jabuka_touch.status")

LEVELS = ("ok", "warn", "bad", "unknown")
SERVICE_UNITS = ("jabuka-core.service", "jabuka-ingest-fastnet.service", "gpsd.service")
KEYS = ("bus", "gps", "wind", "pack", "route", "wifi", "power", "temp", "disk", "services")
LABELS = {
    "bus": "BUS",
    "gps": "GPS",
    "wind": "VENT",
    "pack": "MÉTÉO",
    "route": "ROUTE",
    "wifi": "WI-FI",
    "power": "ALIM",
    "temp": "TEMP.",
    "disk": "DISQUE",
    "services": "SERVICES",
}


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    level: str = "unknown"
    short: str = "?"
    detail: str = ""


def unknown(key: str, detail: str = "inconnu") -> Item:
    return Item(key, LABELS[key], "unknown", "?", detail)


@dataclass(frozen=True)
class Snapshot:
    items: tuple[Item, ...]
    version: int
    t: float
    demo: bool = False
    prerace_running: bool = False
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    def item(self, key: str) -> Item | None:
        return next((i for i in self.items if i.key == key), None)


def parse_is_active(stdout: str, units: tuple[str, ...] | list[str]) -> dict[str, str]:
    """`systemctl is-active A B C` prints one state per line (rc != 0 when one is not active)."""
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    return {u: (lines[i] if i < len(lines) else "inconnu") for i, u in enumerate(units)}


def services_item(states: dict[str, str]) -> Item:
    down = [u.removesuffix(".service") for u, s in states.items() if s != "active"]
    detail = " ".join(f"{u.removesuffix('.service')}={s}" for u, s in states.items())
    if not down:
        return Item("services", LABELS["services"], "ok", "3 actifs", detail)
    return Item("services", LABELS["services"], "bad", "arrêt : " + ",".join(down), detail)


class Collector:
    """Background collection; latest() returns the newest immutable Snapshot (or None)."""

    def __init__(
        self,
        runner,
        clock: Callable[[], float] = time.monotonic,
        interval: float = 1.0,
        sys_every: float = 5.0,
    ):
        self.runner = runner
        self.clock = clock
        self.interval = interval
        self.sys_every = sys_every
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self._latest: Snapshot | None = None
        self._version = 0
        self._items: dict[str, Item] = {k: unknown(k) for k in KEYS}
        self._next_sys = 0.0
        self._extra_names: frozenset[str] = frozenset()

    # -- steps -----------------------------------------------------------------------------
    def _safe(self, key: str, fn: Callable[[], Item]) -> None:
        try:
            self._items[key] = fn()
        except Exception as e:  # noqa: BLE001 - one broken input turns one tile unknown
            log.warning("état %s : %s", key, e)
            self._items[key] = unknown(key, f"erreur : {e}")

    def _services(self) -> Item:
        res = self.runner.run(["systemctl", "is-active", *SERVICE_UNITS], 2.0)
        if not res.out.strip():
            return unknown("services", f"systemctl : {res.describe()}")
        return services_item(parse_is_active(res.out, SERVICE_UNITS))

    def collect_once(self, force_sys: bool = True) -> Snapshot:
        now = self.clock()
        if force_sys or now >= self._next_sys:
            self._next_sys = now + self.sys_every
            self._safe("services", self._services)
        items = tuple(self._items[k] for k in KEYS)
        return self._publish(items, now)

    def _publish(self, items: tuple[Item, ...], now: float, **kw) -> Snapshot:
        with self.lock:
            prev = self._latest
            same = (
                prev is not None
                and prev.items == items
                and all(getattr(prev, k) == v for k, v in kw.items() if k != "extra")
                and prev.extra == kw.get("extra", prev.extra)
            )
            if not same:
                self._version += 1
            snap = Snapshot(items, self._version, now, **kw)
            self._latest = snap
            return snap

    def set_extra(self, names: set[str]) -> None:
        """Extra queries the open screen needs (run only while requested)."""
        with self.lock:
            self._extra_names = frozenset(names)

    def latest(self) -> Snapshot | None:
        with self.lock:
            return self._latest

    # -- thread ----------------------------------------------------------------------------
    def _loop(self) -> None:
        while not self.stop_ev.is_set():
            try:
                self.collect_once(force_sys=False)
            except Exception:  # noqa: BLE001 - the collector thread never dies
                log.exception("collecte")
            self.stop_ev.wait(self.interval)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="collector", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
