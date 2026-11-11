"""DÉMO / MODE COURSE: a simulated boat the tablets see, through VOLATILE systemd drop-ins.

start_demo writes /run/systemd/system/{jabuka-core,jabuka-ingest-fastnet}.service.d/
zz-jabuka-touch-demo.conf: the EFFECTIVE installed ExecStart (``systemctl cat``, operator drop-ins
included) with only the demo inputs swapped (--data-dir/--racepack/--clock sim/--gpsd :2948 for
the core, --device <pty>/--data-dir for the ingest), plus ReadWritePaths=-/var/lib/jabuka-demo.
systemd applies the drop-ins of /etc and /run together in FILENAME order (a later ExecStart=
reset wins), hence the zz- prefix (after an operator override.conf and the soak's 50- files) AND
two checks: the effective ExecStart after daemon-reload must equal the demo argv before anything
is restarted, and each unit's main process must carry every demo argument after the restart.
Any mismatch rolls back to race mode: a demo is never half-applied.

The race data (/var/lib/jabuka: race pack, course.json, settings.json, bias.json) is only ever
read; the demo data lives in /var/lib/jabuka-demo (wiped on each start, marker-guarded). Since the
drop-ins live in /run, a reboot always comes back in race mode. The drop-in parsing and rendering
helpers are ported from src/jabuka/soak/systemd.py (_service_items, unit_execstart, _set_flag,
_quote, dropin_text): this package never imports jabuka.
"""

from __future__ import annotations

import math
import os
import re
import shlex
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .actions import CORE_UNIT, INGEST_UNIT, Outcome

DROPIN_NAME = "zz-jabuka-touch-demo.conf"
SOAK_DROPIN = "50-jabuka-soak.conf"
UNITS = {"core": CORE_UNIT, "ingest": INGEST_UNIT}
SIM_UNIT = "jabuka-demo-sim.service"
PRERACE_UNIT = "jabuka-prerace.service"
FAKE_GPSD_PORT = 2948
REAL_GPSD_PORT = 2947
MARKER = ".jabuka-touch-demo"
PACK_FILES = (
    "race.pmtiles",
    "coastline.geojson",
    "seamarks.geojson",
    "racepack.json",
    "polar.json",
    "landmask.npz",
    "landmask.json",
)
# map-derived routing aid (distance-by-water fields, sidecar-checked against the mask): copied
# when present, never weather
OPTIONAL_PACK_FILES = ("geofields.npz", "geofields.json")
NO_MASK_WARNING = "pas de masque terre : la route ne sera pas calculée"
REBOOT_HINT = "redémarrer le Pi rétablit le mode course"

# demo constants (src/jabuka/tools/demo.py and rehearsal.py): 2 nm downwind of Plić Sestre
PLIC = (43.684627, 15.811626)
START_BRG_DEG = 341.0
START_NM = 2.0
NM_PER_DEG = 60.0
DEMO_TWD, DEMO_TWS, DEMO_TWA = 161.0, 12.0, 45.0
DEMO_VARIATION = 4.7  # jabuka.nav.settings.Settings().variation_deg (fresh demo data dir)
DURATION_S = 4 * 86400.0

_SAFE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


@dataclass(frozen=True)
class DemoPaths:
    race_data: Path = Path("/var/lib/jabuka")
    race_pack: Path = Path("/var/lib/jabuka/racepack")
    demo_root: Path = Path("/var/lib/jabuka-demo")
    run_dir: Path = Path("/run/jabuka-demo")
    dropin_root: Path = Path("/run/systemd/system")
    etc_root: Path = Path("/etc/systemd/system")
    proc: Path = Path("/proc")
    venv: Path = Path("/opt/jabuka/venv")
    touch_root: Path = Path("/opt/jabuka-touch")

    @property
    def demo_data(self) -> Path:
        return self.demo_root / "data"

    @property
    def demo_pack(self) -> Path:
        return self.demo_root / "racepack"

    @property
    def pty(self) -> Path:
        return self.run_dir / "fastnet-pty"

    def dropin(self, unit: str) -> Path:
        return self.dropin_root / f"{unit}.d" / DROPIN_NAME


class DemoFailure(Exception):
    """A demo step failed; the message is shown after « ÉCHEC démo : »."""


# -- unit files (ported from src/jabuka/soak/systemd.py) ---------------------------------------
def service_items(text: str) -> list[tuple[str, str]]:
    """(key, value) of every [Service] line, in order (``systemctl cat`` output works too)."""
    section = None
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Service" and "=" in line:
            k, _, v = line.partition("=")
            out.append((k.strip(), v.strip()))
    return out


def unit_execstart(text: str) -> str:
    """The effective ExecStart= of a unit (+ drop-ins): an empty ExecStart= resets the list."""
    cur: list[str] = []
    for k, v in service_items(text):
        if k == "ExecStart":
            cur = [*cur, v] if v else []  # systemd appends; the soak port replaced
    if len(cur) != 1:
        raise ValueError(f"expected one effective ExecStart=, got {cur}")
    if cur[0][:1] in ("-", "@", "+", "!", ":"):
        raise ValueError(f"ExecStart with a prefix is not supported: {cur[0]}")
    return cur[0]


def effective_execstart(cat_text: str) -> list[str]:
    """The effective ExecStart argv of ``systemctl cat`` text (specifiers %% undone)."""
    return [t.replace("%%", "%") for t in shlex.split(unit_execstart(cat_text))]


def set_flag(argv: list[str], flag: str, value: str) -> list[str]:
    out = list(argv)
    for i, tok in enumerate(out):
        if tok == flag and i + 1 < len(out):
            out[i + 1] = value
            return out
        if tok.startswith(flag + "="):
            out[i] = f"{flag}={value}"
            return out
    return [*out, flag, value]


def get_flag(argv: list[str], flag: str) -> str | None:
    for i, tok in enumerate(argv):
        if tok == flag and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


def demo_argv(
    role: str, shipped: list[str], paths: DemoPaths, gpsd_port: int = FAKE_GPSD_PORT
) -> list[str]:
    """The installed ExecStart argv with only the demo inputs changed."""
    if int(gpsd_port) == REAL_GPSD_PORT:
        raise ValueError(f"the fake gpsd never uses the real gpsd port {REAL_GPSD_PORT}")
    data = str(paths.demo_data)
    if role == "core":
        argv = set_flag(shipped, "--data-dir", data)
        argv = set_flag(argv, "--racepack", str(paths.demo_pack))
        argv = set_flag(argv, "--clock", "sim")
        return set_flag(argv, "--gpsd", f"127.0.0.1:{int(gpsd_port)}")
    if role == "ingest":
        argv = set_flag(shipped, "--device", str(paths.pty))
        return set_flag(argv, "--data-dir", data)
    raise ValueError(f"unknown role {role!r}")


def quote(tok: str) -> str:
    if not _SAFE.match(tok):
        raise ValueError(f"unsupported character in ExecStart token {tok!r}")
    return tok.replace("%", "%%")  # systemd specifiers


def dropin_text(argv: list[str], demo_root: Path = Path("/var/lib/jabuka-demo")) -> str:
    return (
        "# jabuka-touch DÉMO: volatile (/run), removed by MODE COURSE or at reboot\n"
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart={' '.join(quote(t) for t in argv)}\n"
        f"ReadWritePaths=-{quote(str(demo_root))}\n"
    )


# -- demo constants --------------------------------------------------------------------------
def demo_start_point() -> tuple[float, float]:
    """jabuka.nav.geo.offset(PLIC, radians(341), 2.0 nm), same formula."""
    lat, lon = PLIC
    b = math.radians(START_BRG_DEG)
    lat2 = lat + START_NM * math.cos(b) / NM_PER_DEG
    k = math.cos(math.radians((lat + lat2) / 2.0))
    return lat2, lon + START_NM * math.sin(b) / (k * NM_PER_DEG)


def _num(v: float) -> str:
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"nombre invalide : {v}")
    return f"{f:.15g}"  # :g keeps only 6 digits (epochs!)


def start_epoch(cfg) -> float:
    dt = datetime.fromisoformat(cfg.demo.start_utc)
    if dt.tzinfo is None:
        raise ValueError("demo.start_utc sans fuseau")
    return dt.timestamp()


def sim_argv(cfg, paths: DemoPaths, http_port: int) -> list[str]:
    lat, lon = demo_start_point()
    start = datetime.fromisoformat(cfg.demo.start_utc).isoformat()
    return [
        "systemd-run",
        f"--unit={SIM_UNIT.removesuffix('.service')}",
        "--collect",
        "-p",
        "User=jabuka",
        "-p",
        "Group=jabuka",
        "-p",
        "Nice=5",
        "-p",
        "MemoryMax=200M",
        "-p",
        "Restart=on-failure",
        str(paths.venv / "bin" / "jabuka-sim"),
        "--mode",
        "pty",
        "--link",
        str(paths.pty),
        "--speed",
        _num(cfg.demo.speed),
        "--duration",
        _num(DURATION_S),
        "--twd",
        _num(DEMO_TWD),
        "--tws",
        _num(DEMO_TWS),
        "--twa",
        _num(DEMO_TWA),
        "--start",
        f"{lat:.6f},{lon:.6f}",
        "--start-utc",
        start,
        "--variation",
        _num(DEMO_VARIATION),
        "--gpsd-port",
        str(FAKE_GPSD_PORT),
        "--wait-reader",
        "30",
        "--seed",
        "1",
        "--shift",
        _num(cfg.demo.shift_deg_h),
        "--follow",
        f"http://127.0.0.1:{int(http_port)}",
        "--follow-route",
        "--follow-nowait",
    ]


def wind_argv(cfg, paths: DemoPaths) -> list[str]:
    t0 = start_epoch(cfg)
    return [
        "runuser",
        "-u",
        "jabuka",
        "--",
        str(paths.venv / "bin" / "python"),
        "-I",
        str(paths.touch_root / "jabuka_touch" / "demo_wind.py"),
        str(paths.demo_pack),
        str(paths.demo_root),
        _num(t0),
        _num(t0 + DURATION_S),
        _num(DEMO_TWD),
        _num(DEMO_TWS),
        _num(cfg.demo.shift_deg_h),
    ]


# -- filesystem ------------------------------------------------------------------------------
def _inside(p: Path, root: Path) -> bool:
    p, root = Path(os.path.realpath(p)), Path(os.path.realpath(root))
    return p == root or root in p.parents


def safe_wipe(path: Path, paths: DemoPaths) -> bool:
    """rm -rf path only when it carries the marker and is not the race data dir (nor inside
    it, nor containing it). False when nothing was wiped."""
    path = Path(path)
    if _inside(path, paths.race_data) or _inside(paths.race_data, path):
        raise DemoFailure(f"refus d'effacer {path} : données de course")
    if not path.exists():
        return False
    if not (path / MARKER).is_file():
        return False
    shutil.rmtree(path)
    return True


def fresh_dir(path: Path, paths: DemoPaths, owner: Callable[[Path], None] | None) -> None:
    """Wipe (marker-guarded) and recreate ``path`` with its marker, owned by jabuka."""
    path = Path(path)
    if path.exists() and not (path / MARKER).is_file() and any(path.iterdir()):
        raise DemoFailure(f"{path} existe sans marqueur démo : effacer à la main")
    safe_wipe(path, paths)
    path.mkdir(parents=True, exist_ok=True)
    (path / MARKER).write_text("jabuka-touch demo\n")
    if owner is not None:
        owner(path)


def build_demo_pack(race_pack: Path, demo_pack: Path) -> list[str]:
    """Copy the map/polar/mask files (never the weather) into the demo pack; warnings."""
    demo_pack.mkdir(parents=True, exist_ok=True)
    for name in (*PACK_FILES, *OPTIONAL_PACK_FILES):
        src = Path(race_pack) / name
        if src.is_file():
            shutil.copyfile(src, demo_pack / name)
    warnings = []
    if not (demo_pack / "landmask.npz").is_file():
        warnings.append(NO_MASK_WARNING)
    return warnings


def write_dropin(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def demo_active(paths: DemoPaths) -> bool:
    return paths.dropin(CORE_UNIT).exists()


def any_dropin(paths: DemoPaths) -> bool:
    return any(paths.dropin(u).exists() for u in UNITS.values())


def soak_dropins(paths: DemoPaths) -> list[Path]:
    return [
        root / f"{u}.d" / SOAK_DROPIN
        for root in (paths.dropin_root, paths.etc_root)
        for u in UNITS.values()
        if (root / f"{u}.d" / SOAK_DROPIN).exists()
    ]


def chown_jabuka(path: Path) -> None:
    import pwd

    pw = pwd.getpwnam("jabuka")
    os.chown(path, pw.pw_uid, pw.pw_gid)


# -- sequences -------------------------------------------------------------------------------
@dataclass
class Ctx:
    runner: object
    paths: DemoPaths
    progress: Callable[[str], None]
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def run(self, argv: list[str], timeout: float, step: str | None = None):
        res = self.runner.run(argv, timeout)
        if step is not None and not res.ok:
            tail = res.tail(1)
            raise DemoFailure(f"{step} ({res.describe()}{' : ' + tail[0] if tail else ''})")
        return res

    def cat(self, unit: str) -> str:
        res = self.run(["systemctl", "cat", unit], 10.0, f"systemctl cat {unit}")
        return res.out


def _stop_sim(ctx: Ctx) -> None:
    ctx.run(["systemctl", "stop", SIM_UNIT], 30.0)
    ctx.run(["systemctl", "reset-failed", SIM_UNIT], 10.0)


def _main_pid(ctx: Ctx, unit: str) -> int:
    res = ctx.run(["systemctl", "show", "-p", "MainPID", "--value", unit], 10.0)
    try:
        return int(res.out.strip() or 0)
    except ValueError:
        return 0


def runs_argv(proc: Path, pid: int, argv: list[str]) -> bool:
    """The process carries every argument argv[1:] (like the soak's runs_soak_argv)."""
    try:
        tokens = (Path(proc) / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    have = {t.decode("utf-8", "replace") for t in tokens}
    return all(a in have for a in argv[1:])


def _verify_processes(ctx: Ctx, argvs: dict[str, list[str]], wait_s: float = 20.0) -> None:
    for unit, argv in argvs.items():
        deadline = ctx.clock() + wait_s
        while True:
            pid = _main_pid(ctx, unit)
            if pid > 0 and runs_argv(ctx.paths.proc, pid, argv):
                break
            if ctx.clock() >= deadline:
                raise DemoFailure(f"le processus de {unit} ne tourne pas avec les arguments démo")
            ctx.sleep(1.0)


def _wait_live(ctx: Ctx, fetch: Callable[[str], dict | None], wait_s: float = 120.0) -> bool:
    deadline = ctx.clock() + wait_s
    while True:
        try:
            nav = fetch("/api/nav")
        except Exception:  # noqa: BLE001 - the core may still be starting
            nav = None
        wind = nav.get("wind") if isinstance(nav, dict) else None
        if isinstance(wind, dict) and wind.get("source") == "LIVE":
            return True
        if ctx.clock() >= deadline:
            return False
        ctx.sleep(2.0)


def start_demo(
    runner,
    paths: DemoPaths,
    cfg,
    fetch_for_port: Callable[[int], Callable[[str], dict | None]],
    progress: Callable[[str], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    owner: Callable[[Path], None] | None = None,
) -> Outcome:
    ctx = Ctx(runner, paths, progress, sleep, clock)
    # -- refusals: nothing changed yet, no rollback ---------------------------------------
    if any_dropin(paths):
        return Outcome(False, ("ÉCHEC démo : une démo est déjà active (MODE COURSE d'abord)",))
    soak = soak_dropins(paths)
    if soak:
        return Outcome(False, (f"ÉCHEC démo : soak en cours ({soak[0]})",))
    st = ctx.run(["systemctl", "is-active", PRERACE_UNIT], 10.0)
    if st.out.strip() in ("active", "activating", "reloading"):
        return Outcome(False, ("ÉCHEC démo : prerace en cours, attendre la fin",))
    if not paths.race_pack.is_dir():
        return Outcome(False, (f"ÉCHEC démo : pack de course absent ({paths.race_pack})",))
    lines: list[str] = []
    try:
        progress("Arrêt d'un bateau simulé précédent…")
        _stop_sim(ctx)
        progress("Préparation de /var/lib/jabuka-demo…")
        fresh_dir(paths.demo_root, paths, owner)
        for d in (paths.demo_data, paths.demo_pack):
            d.mkdir(parents=True, exist_ok=True)
            if owner is not None:
                owner(d)
        fresh_dir(paths.run_dir, paths, owner)
        progress("Copie de la carte et de la polaire (données de course lues seulement)…")
        lines += build_demo_pack(paths.race_pack, paths.demo_pack)
        progress("Vent de démo…")
        ctx.run(wind_argv(cfg, paths), 120.0, "vent démo")
        progress("Lecture des unités installées…")
        argvs: dict[str, list[str]] = {}
        for role, unit in UNITS.items():
            argvs[unit] = demo_argv(role, effective_execstart(ctx.cat(unit)), paths)
        http_port = int(get_flag(argvs[CORE_UNIT], "--http-port") or 80)
        for unit, argv in argvs.items():
            write_dropin(paths.dropin(unit), dropin_text(argv, paths.demo_root))
        ctx.run(["systemctl", "daemon-reload"], 30.0, "daemon-reload")
        progress("Vérification de l'ExecStart effectif…")
        for unit, argv in argvs.items():
            if effective_execstart(ctx.cat(unit)) != argv:
                raise DemoFailure(
                    f"ExecStart effectif de {unit} différent de la démo "
                    f"(drop-in appliqué après {DROPIN_NAME})"
                )
        progress("Démarrage du bateau simulé…")
        ctx.run(sim_argv(cfg, paths, http_port), 30.0, "bateau simulé")
        deadline = clock() + 20.0
        while not paths.pty.is_symlink():
            if clock() >= deadline:
                raise DemoFailure("le bateau simulé n'a pas créé son pty")
            sleep(0.5)
        progress("Redémarrage du cœur et de l'ingest en démo…")
        ctx.run(["systemctl", "restart", INGEST_UNIT, CORE_UNIT], 90.0, "redémarrage")
        progress("Vérification des processus…")
        _verify_processes(ctx, argvs)
    except (DemoFailure, ValueError, OSError) as e:
        progress(f"Échec : {e} ; retour en mode course…")
        rb = stop_demo(runner, paths, progress, sleep=sleep, clock=clock)
        out = [f"ÉCHEC démo : {e}", f"retour en mode course : {'OK' if rb.ok else 'ÉCHEC'}"]
        if not rb.ok:
            out += [ln for ln in rb.lines if ln]
        return Outcome(False, tuple(out))
    progress("Attente du vent LIVE simulé…")
    if _wait_live(ctx, fetch_for_port(http_port)):
        lines.insert(0, "Démo lancée : bateau simulé, tablette sur http://10.42.0.1")
    else:
        lines.insert(0, "démo lancée, vent LIVE pas encore là")
    return Outcome(True, tuple(lines))


def stop_demo(
    runner,
    paths: DemoPaths,
    progress: Callable[[str], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    active_wait_s: float = 30.0,
) -> Outcome:
    """MODE COURSE (and the rollback): remove only our drop-ins, restart, verify. Idempotent."""
    ctx = Ctx(runner, paths, progress, sleep, clock)
    lines: list[str] = []
    ok = True
    progress("Arrêt du bateau simulé…")
    _stop_sim(ctx)
    progress("Retrait des drop-ins démo…")
    for unit in UNITS.values():
        p = paths.dropin(unit)
        try:
            p.unlink(missing_ok=True)
            p.with_name(p.name + ".tmp").unlink(missing_ok=True)
            if p.parent.is_dir() and not any(p.parent.iterdir()):
                p.parent.rmdir()
        except OSError as e:
            ok = False
            lines.append(f"drop-in {p} : {e}")
    res = ctx.run(["systemctl", "daemon-reload"], 30.0)
    if not res.ok:
        ok = False
        lines.append(f"daemon-reload : {res.describe()}")
    progress("Redémarrage du cœur et de l'ingest en mode course…")
    res = ctx.run(["systemctl", "restart", INGEST_UNIT, CORE_UNIT], 90.0)
    if not res.ok:
        lines.append(f"redémarrage : {res.describe()}")
    progress("Vérification des services…")
    units = [INGEST_UNIT, CORE_UNIT]
    deadline = clock() + active_wait_s
    inactive = units
    while True:
        res = ctx.run(["systemctl", "is-active", *units], 10.0)
        states = [ln.strip() for ln in res.out.splitlines() if ln.strip()]
        inactive = [u for i, u in enumerate(units) if i >= len(states) or states[i] != "active"]
        if not inactive or clock() >= deadline:
            break
        sleep(1.0)
    cat = ctx.run(["systemctl", "cat", CORE_UNIT], 10.0)
    if DROPIN_NAME in cat.out:
        ok = False
        lines.append(f"{DROPIN_NAME} encore appliqué : {REBOOT_HINT}")
    for d in (paths.demo_root, paths.run_dir):
        try:
            safe_wipe(d, paths)
        except (DemoFailure, OSError) as e:
            lines.append(f"nettoyage {d} : {e}")
    if inactive:
        ok = False
        for u in inactive:
            lines.append(f"Drop-ins démo retirés, mais {u} pas actif : {REBOOT_HINT}")
    if ok:
        lines.insert(0, "Mode course : capteurs réels, données de course")
    return Outcome(ok, tuple(lines))


def demo_actions(
    runner,
    paths: DemoPaths,
    cfg,
    fetch_for_port: Callable[[int], Callable[[str], dict | None]],
    owner: Callable[[Path], None] | None = None,
) -> dict:
    """The demo_start and race_mode actions for the worker registry."""
    from .actions import Action

    def start(progress):
        return start_demo(runner, paths, cfg, fetch_for_port, progress, owner=owner)

    def stop(progress):
        return stop_demo(runner, paths, progress)

    return {
        "demo_start": Action("demo_start", "Démo", start),
        "race_mode": Action("race_mode", "Mode course", stop),
    }
