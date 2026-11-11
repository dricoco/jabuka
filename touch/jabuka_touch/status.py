"""System status at a glance: ten items collected on a background thread.

Every collect step is wrapped: an exception or a timeout only turns that item unknown, the
collector never raises and never blocks the display loop. The core API is read-only
(GET /api/state and /api/nav on 127.0.0.1, 1 s timeout); system commands have a 2 s timeout.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from .actions import ACTIVE_STATES, CURRENT_UNIT, PRERACE, WIFI
from .config import Paths

log = logging.getLogger("jabuka_touch.status")

LEVELS = ("ok", "warn", "bad", "unknown")
SERVICE_UNITS = ("jabuka-core.service", "jabuka-ingest-fastnet.service", "gpsd.service")
PRERACE_UNIT = "jabuka-prerace.service"
KEYS = ("bus", "gps", "wind", "pack", "route", "wifi", "power", "temp", "disk", "services")
API_KEYS = ("bus", "gps", "wind", "pack", "route")
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
CMD_TIMEOUT = 2.0
EXTRA_QUERIES = {
    "journal_prerace": [
        "journalctl",
        "-u",
        PRERACE_UNIT,
        "-u",
        CURRENT_UNIT,
        "-n",
        "10",
        "--no-pager",
        "-o",
        "cat",
    ],
    "prerace_status": [PRERACE, "status"],
    "wifi_status": [WIFI, "status"],
}


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    level: str = "unknown"
    short: str = "?"
    detail: str = ""


def item(key: str, level: str, short: str, detail: str = "") -> Item:
    return Item(key, LABELS[key], level, short, detail)


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


# -- helpers ---------------------------------------------------------------------------------
def _d(obj: object, *path: str) -> object:
    """obj[path[0]][path[1]]... or None, never raises (defensive JSON access)."""
    cur = obj
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _fr(v: float, nd: int = 1) -> str:
    return f"{v:.{nd}f}".replace(".", ",")


# -- system parsers --------------------------------------------------------------------------
def parse_is_active(stdout: str, units: tuple[str, ...] | list[str]) -> dict[str, str]:
    """`systemctl is-active A B C` prints one state per line (rc != 0 when one is not active)."""
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    return {u: (lines[i] if i < len(lines) else "inconnu") for i, u in enumerate(units)}


def services_item(states: dict[str, str]) -> Item:
    down = [u.removesuffix(".service") for u, s in states.items() if s != "active"]
    detail = " ".join(f"{u.removesuffix('.service')}={s}" for u, s in states.items())
    if not down:
        return item("services", "ok", "3 actifs", detail)
    return item("services", "bad", "arrêt : " + ",".join(down), detail)


def parse_throttled(text: str) -> Item:
    """`vcgencmd get_throttled` -> throttled=0x50005 (bit0 under-voltage now, bit16 occurred,
    bits 1-3 / 17-19 frequency capping, throttling, soft temperature limit)."""
    try:
        val = int(text.strip().split("=", 1)[1], 16)
    except (IndexError, ValueError, AttributeError):
        return unknown("power", f"vcgencmd : {text.strip()[:40] or 'muet'}")
    detail = f"throttled={hex(val)}"
    if val & 0x1:
        return item("power", "bad", "sous-tension !", detail + " : alimentation trop faible")
    if val & 0xE:
        return item("power", "warn", "CPU bridé", detail + " : fréquence réduite maintenant")
    if val & 0x10000:
        return item("power", "warn", "sous-tension passée", detail + " : depuis le démarrage")
    if val & 0xE0000:
        return item("power", "warn", "bridé (passé)", detail + " : depuis le démarrage")
    return item("power", "ok", "ok", detail)


def parse_iw_info(text: str) -> dict:
    """`iw dev wlan0 info` -> {"mode": ap|phone|none, "ssid": str|None}."""
    ssid = typ = None
    for line in (text or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0] == "ssid":
            ssid = parts[1].strip()
        elif len(parts) == 2 and parts[0] == "type":
            typ = parts[1].strip()
    if typ == "AP":
        return {"mode": "ap", "ssid": ssid}
    if typ == "managed" and ssid:
        return {"mode": "phone", "ssid": ssid}
    return {"mode": "none", "ssid": ssid}


def parse_station_dump(text: str) -> int:
    return sum(1 for line in (text or "").splitlines() if line.startswith("Station "))


def wifi_item(info: dict, clients: int) -> Item:
    ssid = info.get("ssid") or "?"
    if info.get("mode") == "ap":
        return item("wifi", "ok", f"AP · {clients}", f"point d'accès {ssid}, {clients} client(s)")
    if info.get("mode") == "phone":
        return item("wifi", "warn", f"tél. {ssid}", f"client du partage du téléphone « {ssid} »")
    return item("wifi", "bad", "aucun", "wlan0 sans point d'accès ni partage")


def parse_chrony_tracking(text: str) -> dict:
    """`chronyc -n -c tracking` CSV: 2nd field the reference name, last field the leap status."""
    fields = (text or "").strip().splitlines()[0].split(",") if (text or "").strip() else []
    if len(fields) < 3:
        return {"synced": None, "ref": None, "leap": None}
    leap = fields[-1].strip()
    return {"synced": leap == "Normal", "ref": fields[1].strip(), "leap": leap}


def parse_last(text: str, key: str) -> dict:
    """A result file (prerace-last.txt, current-last.txt) or its `status` output ->
    {running, date, result, code}; ``key`` names the first line's date field."""
    out: dict = {"running": False, "date": None, "result": None, "code": None}
    lines = (text or "").splitlines()
    if lines and lines[0].startswith(("en cours", "en attente")):
        out["running"] = True
    for line in lines:
        k, sep, v = line.partition(" : ")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if k == key and out["date"] is None:
            out["date"] = v
        elif k == "résultat" and out["result"] is None:
            out["result"] = v
        elif k == "code" and out["code"] is None:
            try:
                out["code"] = int(v)
            except ValueError:
                pass
    return out


def parse_prerace_last(text: str) -> dict:
    """prerace-last.txt (or `prerace status`) -> {running, date, result, code}."""
    return parse_last(text, "prerace")


def parse_current_last(text: str) -> dict:
    """current-last.txt (or `jabuka-current status`) -> {running, date, result, code}."""
    return parse_last(text, "courant")


def pack_current(it: Item, cur: dict | None) -> Item:
    """The MÉTÉO item with the Copernicus current state appended to its detail (level unchanged:
    the current is optional). ``cur`` = {"running", "present", "last"} from the collector."""
    cur = cur or {}
    last = cur.get("last") or {}
    if cur.get("running"):
        mention = "courant : téléchargement en cours"
    elif cur.get("present") and last.get("code") == 0 and last.get("date"):
        mention = f"courant : présent (téléchargé {last['date']})"
    elif cur.get("present"):
        mention = "courant : présent"
    else:
        mention = "courant : absent"
    return replace(it, detail=f"{it.detail} ; {mention}" if it.detail else mention)


def temp_item(milli: str) -> Item:
    c = int(milli.strip()) / 1000.0
    short = f"{c:.0f} °C"
    detail = f"CPU {_fr(c)} °C"
    if c >= 80:
        return item("temp", "bad", short, detail + " : surchauffe, bridage")
    if c >= 70:
        return item("temp", "warn", short, detail + " : chaud")
    return item("temp", "ok", short, detail)


def disk_item(st, path: str) -> Item:
    free = st.f_bavail * st.f_frsize
    total = st.f_blocks * st.f_frsize
    pct = 100.0 * st.f_bavail / st.f_blocks if st.f_blocks else 0.0
    go = free / 1e9
    short = f"{_fr(go)} Go libres"
    detail = f"{path} : {_fr(go)} Go libres sur {_fr(total / 1e9)} Go ({pct:.0f} %)"
    level = "ok" if pct > 20 else "warn" if pct >= 10 else "bad"
    return item("disk", level, short, detail)


# -- API items -------------------------------------------------------------------------------
BUS_WARN = {
    "silent": "muet",
    "few_bytes": "peu d'octets",
    "no_frames": "pas de trames",
    "noisy": "bruité",
}
BUS_BAD = {"missing": "absent", "busy": "port occupé"}


def bus_item(state: dict | None) -> Item:
    fn = _d(state, "health", "fastnet")
    if not isinstance(fn, dict):
        return item("bus", "bad", "pas d'info", "le cœur ne rapporte pas l'état du bus Fastnet")
    st = fn.get("state")
    fps = _num(fn.get("frames_per_s"))
    hint = fn.get("hint") if isinstance(fn.get("hint"), str) else ""
    detail = f"Fastnet {st}, {f'{fps:.0f}' if fps is not None else '?'} trames/s"
    detail += f", adaptateur {fn.get('device')}" + (f" — {hint}" if hint else "")
    if st in BUS_BAD:
        return item("bus", "bad", BUS_BAD[st], detail)
    if st in BUS_WARN:
        return item("bus", "warn", BUS_WARN[st], detail)
    if st == "ok" and fn.get("alive") is True:
        return item("bus", "ok", f"ok {fps:.0f} tr/s" if fps is not None else "ok", detail)
    return item("bus", "bad", "muet" if st == "ok" else str(st or "?"), detail)


def gps_item(state: dict | None, chrony: dict | None) -> Item:
    gps = _d(state, "health", "gps")
    chrony = chrony or {}
    ch = ""
    if chrony.get("ref") is not None:
        ch = f", chrony {chrony.get('ref')} {chrony.get('leap')}"
    if not isinstance(gps, dict):
        return item("gps", "bad", "pas d'info", "le cœur ne rapporte pas l'état du GPS" + ch)
    mode = _num(gps.get("mode")) or 0
    sats = _num(gps.get("sats_used"))
    nsat = f"{sats:.0f} sat" if sats is not None else "? sat"
    detail = f"gpsd {gps.get('server') or '?'}, mode {mode:.0f}, {nsat}" + ch
    if gps.get("connected") is not True:
        return item("gps", "bad", "gpsd absent", detail)
    if mode < 2:
        return item("gps", "bad", "pas de fix", detail)
    if _d(state, "clock", "time_valid") is not True:
        return item("gps", "warn", "horloge en attente", detail + " ; horloge pas encore valide")
    return item("gps", "ok", f"{'3D' if mode >= 3 else '2D'} {nsat}", detail)


def wind_item(nav: dict | None) -> Item:
    w = _d(nav, "wind")
    if not isinstance(w, dict):
        return item("wind", "bad", "aucun", "pas de vent (ni bus, ni GRIB, ni manuel)")
    src = w.get("source")
    tws = _num(w.get("tws_kn"))
    kn = f" {tws:.0f} kn" if tws is not None else ""
    detail = f"source {src}{kn}" + (" (périmé)" if w.get("stale") else "")
    if src in (None, "NONE"):
        return item("wind", "bad", "aucun", detail)
    if src in ("LIVE", "LIVE_BG") and not w.get("stale"):
        return item("wind", "ok", f"{src}{kn}", detail)
    return item("wind", "warn", f"{src}{kn}", detail)


def _short_run(run: object) -> str:
    s = str(run or "")
    if len(s) >= 13 and s[4] == "-" and s[10] == "T":
        return f"{s[8:10]}/{s[11:13]}Z"
    return s


def pack_item(nav: dict | None, state: dict | None) -> Item:
    pack = _d(nav, "route", "pack")
    if not isinstance(pack, dict):
        pack = _d(state, "health", "router", "pack")
    reason = _d(state, "health", "router", "pack_reason")
    if not isinstance(pack, dict):
        return item("pack", "unknown", "?", "pas d'info sur le pack météo")
    model, run = pack.get("model") or "?", pack.get("run") or "?"
    alerts = pack.get("alerts") if isinstance(pack.get("alerts"), list) else []
    name = f"{model} {_short_run(run)}"
    if pack.get("ok") is not True:
        why = str(reason) if reason else "pack météo invalide ou absent"
        return item("pack", "bad", "invalide", f"{why} (prerace pour le refaire)")
    if alerts:
        return item("pack", "warn", name, f"{model} run {run} : {alerts[0]}")
    return item("pack", "ok", name, f"{model} run {run}, couverture ok")


ROUTE_WARN = {
    "computing": "calcul…",
    "outdated": "périmée",
    "no_course": "pas de parcours",
    "disabled": "désactivée",
}
ROUTE_BAD = {
    "failed": "échec",
    "no_pack": "pas de pack",
    "no_position": "pas de position",
    "blocked_clock": "horloge",
}


def route_item(nav: dict | None) -> Item:
    r = _d(nav, "route")
    if not isinstance(r, dict):
        return item("route", "unknown", "?", "pas de bloc route")
    st = r.get("state")
    reason = r.get("reason") if isinstance(r.get("reason"), str) else ""
    ver = r.get("version")
    age = _num(r.get("age_s"))
    mins = f"{age / 60:.0f} min" if age is not None else "? min"
    detail = f"route {st}, v{ver}, âge {mins}" + (f" — {reason}" if reason else "")
    if st == "ok":
        return item("route", "ok", f"v{ver} · {mins}", detail)
    if st in ROUTE_WARN:
        return item("route", "warn", ROUTE_WARN[st], detail)
    if st in ROUTE_BAD:
        return item("route", "bad", ROUTE_BAD[st], detail)
    return item("route", "unknown", str(st or "?"), detail)


def api_items(state: dict | None, nav: dict | None, chrony: dict | None) -> dict[str, Item]:
    if state is None or nav is None:
        return {
            k: item(k, "bad", "cœur muet", "jabuka-core ne répond pas sur 127.0.0.1 (1 s)")
            for k in API_KEYS
        }
    return {
        "bus": bus_item(state),
        "gps": gps_item(state, chrony),
        "wind": wind_item(nav),
        "pack": pack_item(nav, state),
        "route": route_item(nav),
    }


def make_fetch(core_url: str, timeout: float = 1.0) -> Callable[[str], dict | None]:
    """GET core_url + path -> JSON object, None on any error (never raises)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = core_url.rstrip("/")

    def fetch(path: str) -> dict | None:
        try:
            with opener.open(base + path, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read(2_000_000).decode("utf-8"))
        except Exception:  # noqa: BLE001 - a silent core is a state, not an error
            return None
        return data if isinstance(data, dict) else None

    return fetch


# -- collector -------------------------------------------------------------------------------
class Collector:
    """Background collection; latest() returns the newest immutable Snapshot (or None).
    API every ``interval`` s, system commands every ``sys_every`` s, the extra queries
    requested by the open screen every ``extra_every`` s (and only while requested)."""

    def __init__(
        self,
        runner,
        fetch: Callable[[str], dict | None] | None = None,
        paths: Paths | None = None,
        clock: Callable[[], float] = time.monotonic,
        interval: float = 1.0,
        sys_every: float = 5.0,
        extra_every: float = 3.0,
        statvfs: Callable = os.statvfs,
    ):
        self.runner = runner
        self.fetch = fetch or (lambda path: None)
        self.paths = paths or Paths()
        self.clock = clock
        self.interval = interval
        self.sys_every = sys_every
        self.extra_every = extra_every
        self.statvfs = statvfs
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self._latest: Snapshot | None = None
        self._version = 0
        self._items: dict[str, Item] = {k: unknown(k) for k in KEYS}
        self._next_sys = 0.0
        self._next_extra = 0.0
        self._extra_names: frozenset[str] = frozenset()
        self._extra: dict = {}
        self._chrony: dict | None = None
        self._prerace_running = False
        self._prerace_last: dict = {}
        self._current: dict = {"running": False, "present": False, "last": {}}
        self._wifi: dict = {}

    # -- steps -----------------------------------------------------------------------------
    def _safe(self, key: str, fn: Callable[[], Item]) -> None:
        try:
            self._items[key] = fn()
        except Exception as e:  # noqa: BLE001 - one broken input turns one tile unknown
            log.warning("état %s : %s", key, e)
            self._items[key] = unknown(key, f"erreur : {e}")

    def _run(self, argv: list[str]):
        return self.runner.run(argv, CMD_TIMEOUT)

    def _services(self) -> Item:
        res = self._run(["systemctl", "is-active", *SERVICE_UNITS])
        if not res.out.strip():
            return unknown("services", f"systemctl : {res.describe()}")
        return services_item(parse_is_active(res.out, SERVICE_UNITS))

    def _power(self) -> Item:
        res = self._run(["vcgencmd", "get_throttled"])
        return parse_throttled(res.out if res.out.strip() else res.describe())

    def _wifi_item(self) -> Item:
        info = parse_iw_info(self._run(["iw", "dev", "wlan0", "info"]).out)
        clients = 0
        if info["mode"] == "ap":
            clients = parse_station_dump(self._run(["iw", "dev", "wlan0", "station", "dump"]).out)
        self._wifi = {**info, "clients": clients}
        return wifi_item(info, clients)

    def _temp(self) -> Item:
        return temp_item(Path(self.paths.thermal).read_text())

    def _disk(self) -> Item:
        return disk_item(self.statvfs(str(self.paths.data_dir)), str(self.paths.data_dir))

    def _chrony_step(self) -> None:
        try:
            self._chrony = parse_chrony_tracking(self._run(["chronyc", "-n", "-c", "tracking"]).out)
        except Exception as e:  # noqa: BLE001
            log.warning("chrony : %s", e)
            self._chrony = None

    def _prerace_step(self) -> None:
        try:
            res = self._run(["systemctl", "is-active", PRERACE_UNIT])
            self._prerace_running = res.out.strip() in ACTIVE_STATES
        except Exception as e:  # noqa: BLE001
            log.warning("prerace : %s", e)
            self._prerace_running = False
        try:
            text = Path(self.paths.prerace_last).read_text(encoding="utf-8", errors="replace")
            self._prerace_last = parse_prerace_last(text)
        except OSError:
            self._prerace_last = {}

    def _current_step(self) -> None:
        running = present = False
        last: dict = {}
        try:
            res = self._run(["systemctl", "is-active", CURRENT_UNIT])
            running = res.out.strip() in ACTIVE_STATES
        except Exception as e:  # noqa: BLE001
            log.warning("courant : %s", e)
        try:
            text = Path(self.paths.current_last).read_text(encoding="utf-8", errors="replace")
            last = parse_current_last(text)
        except OSError:
            last = {}
        try:
            present = Path(self.paths.current_npz).is_file()
        except OSError:
            present = False
        self._current = {"running": running, "present": present, "last": last}

    def _system(self) -> None:
        self._safe("services", self._services)
        self._safe("power", self._power)
        self._safe("wifi", self._wifi_item)
        self._safe("temp", self._temp)
        self._safe("disk", self._disk)
        self._chrony_step()
        self._prerace_step()
        self._current_step()

    def _api(self) -> None:
        try:
            state = self.fetch("/api/state")
            nav = self.fetch("/api/nav") if state is not None else None
        except Exception as e:  # noqa: BLE001
            log.warning("API : %s", e)
            state = nav = None
        try:
            self._items.update(api_items(state, nav, self._chrony))
        except Exception as e:  # noqa: BLE001
            log.warning("API : %s", e)
            for k in API_KEYS:
                self._items[k] = unknown(k, f"erreur : {e}")

    def _extras(self, names: frozenset[str]) -> None:
        out = {}
        for name in sorted(names):
            argv = EXTRA_QUERIES.get(name)
            if argv is None:
                continue
            try:
                res = self._run(list(argv))
                lines = tuple(res.tail(0)) or (f"({res.describe()})",)
            except Exception as e:  # noqa: BLE001
                lines = (f"(erreur : {e})",)
            out[name] = lines[-12:]
        self._extra = out

    def _demo_active(self) -> bool:
        try:
            return Path(self.paths.demo_flag).exists()
        except OSError:
            return False

    def collect_once(self, force_sys: bool = True) -> Snapshot:
        now = self.clock()
        if force_sys or now >= self._next_sys:
            self._next_sys = now + self.sys_every
            self._system()
        self._api()
        with self.lock:
            names = self._extra_names
        if not names:
            self._extra = {}
        elif force_sys or now >= self._next_extra or set(self._extra) != set(names):
            self._next_extra = now + self.extra_every
            self._extras(names)
        extra = {
            **{k: v for k, v in self._extra.items() if k in names},
            "prerace_last": dict(self._prerace_last),
            "current": {**self._current, "last": dict(self._current.get("last") or {})},
            "wifi": dict(self._wifi),
        }
        items = tuple(self._items[k] for k in KEYS)
        try:
            items = tuple(pack_current(i, self._current) if i.key == "pack" else i for i in items)
        except Exception as e:  # noqa: BLE001 - the mention is optional
            log.warning("courant (MÉTÉO) : %s", e)
        return self._publish(
            items,
            now,
            demo=self._demo_active(),
            prerace_running=self._prerace_running,
            extra=extra,
        )

    def _publish(self, items: tuple[Item, ...], now: float, **kw) -> Snapshot:
        with self.lock:
            prev = self._latest
            same = (
                prev is not None
                and prev.items == items
                and prev.demo == kw.get("demo", False)
                and prev.prerace_running == kw.get("prerace_running", False)
                and prev.extra == kw.get("extra", {})
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
