"""Commissioning rehearsal (REL-03): run the runbook's automatable steps on the laptop.

docs/COMMISSIONING.md is the 12–13 Nov runbook. Each automatable action there carries a tag such as
``[R2.swap]``; this module holds the same ids in STEPS and runs them against a replayed capture
(``--capture``, default the committed fixture) and, from §4 on, a synthetic boat. Steps that need
the boat, the Pi or the tablet print HUMAN with the observation to make on board.

    python -m jabuka.tools.rehearsal [--steps quick|all|ID,ID...] [--capture PATH] [--out DIR]
                                     [--online] [--json]

One line per step: ``[PASS|FAIL|SKIP|HUMAN] <id> §<n> <titre> : <détail>``. Exit 0 when no step
failed, 1 otherwise, 2 on a setup error (unknown step, missing capture).

Every tool runs as a subprocess ``[python, -m, module]`` with its existing flags only. Dev tool:
it may read the wall clock and binds 127.0.0.1 ports and ptys only. Like the other jabuka.tools
modules it never opens a file for writing itself (tests/bus/test_no_write_path.py): outputs go
through jabuka.common.atomicio, and tool output is kept in memory and saved to OUT/logs at the end.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from jabuka.common.atomicio import atomic_write_bytes, atomic_write_json
from jabuka.tools.probe import EXIT_CODES, VERDICT_TITLES

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CAPTURE = REPO / "tests" / "fixtures" / "fastnet" / "example2_fastnet_data.txt"
PROBE_LIVE_S = 5  # fastnet-probe LIVE_MIN_SECONDS
REPLAY_DEADLINE_S = 20.0
LOG_CAP_BYTES = 2_000_000  # per tool log kept in memory (the tail)

PASS, FAIL, SKIP, HUMAN = "PASS", "FAIL", "SKIP", "HUMAN"


# -- registry ----------------------------------------------------------------------------------
@dataclass
class Result:
    status: str
    detail: str = ""


@dataclass(frozen=True)
class Step:
    id: str
    section: int
    title: str
    kind: str  # "auto" | "human"
    quick: bool
    expected: str = ""
    fn: Callable[[Context], Result] | None = None
    verdict: str | None = None  # swap-wires drills: the fastnet-probe verdict expected


class SetupError(Exception):
    """Bad arguments or missing inputs: exit 2."""


# -- processes ---------------------------------------------------------------------------------
def free_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(pred: Callable[[], Any], timeout: float, interval: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        try:
            v = pred()
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            v = None
        if v:
            return v
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


@dataclass
class Context:
    out: Path
    capture: Path
    mode: str  # "quick" | "full"
    online: bool = False
    results: dict[str, Result] = field(default_factory=dict)
    procs: list[subprocess.Popen] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, bytearray] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # -- logs ----------------------------------------------------------------------------------
    def log(self, name: str, data: bytes | str) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        with self.lock:
            buf = self.logs.setdefault(name, bytearray())
            buf += data
            if len(buf) > LOG_CAP_BYTES:
                del buf[: len(buf) - LOG_CAP_BYTES]

    def save_logs(self) -> None:
        with self.lock:
            logs = {k: bytes(v) for k, v in self.logs.items()}
        for name, data in logs.items():
            atomic_write_bytes(self.log_path(name), data)

    def _drain(self, name: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for chunk in iter(partial(proc.stdout.read1, 65536), b""):
            self.log(name, chunk)

    # -- subprocesses --------------------------------------------------------------------------
    def log_path(self, name: str) -> Path:
        d = self.out / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{name}.log"

    def spawn(self, name: str, module: str, *args: str) -> subprocess.Popen:
        self.log(name, f"$ {module} {' '.join(args)}\n")
        proc = subprocess.Popen(
            [sys.executable, "-m", module, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=REPO,
        )
        drain = threading.Thread(target=self._drain, args=(name, proc), daemon=True)
        drain.start()
        proc._jabuka_drain = drain  # type: ignore[attr-defined]
        self.procs.append(proc)
        return proc

    def run(self, name: str, module: str, *args: str, timeout: float = 120) -> tuple[int, str]:
        """Run a tool to completion; (exit code, stdout+stderr). The output is also logged."""
        proc = subprocess.run(
            [sys.executable, "-m", module, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO,
        )
        text = proc.stdout + proc.stderr
        self.log(name, f"$ {module} {' '.join(args)}\n{text}\nexit {proc.returncode}\n")
        return proc.returncode, text

    def stop(self, proc: subprocess.Popen | None, sig: int = signal.SIGTERM) -> None:
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.send_signal(sig)
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            except ProcessLookupError:
                pass
        drain = getattr(proc, "_jabuka_drain", None)
        if drain is not None:
            drain.join(timeout=2.0)  # a child that kept the pipe open must not hang the run
        if proc in self.procs:
            self.procs.remove(proc)

    def stop_all(self) -> None:
        for proc in reversed(list(self.procs)):
            self.stop(proc)

    # -- shared probe of --capture ---------------------------------------------------------
    def probe_capture(self) -> dict:
        """fastnet-probe of --capture into OUT/probe (cached): --file in quick mode, a live
        jabuka-replay into a pty in full mode. Returns {code, text, inventory, capture}."""
        if "probe" in self.cache:
            return self.cache["probe"]
        pdir = self.out / "probe"
        if self.mode == "full":
            code, text = live_probe(self, "capture", ["--loop"], pdir)
        else:
            code, text = self.run(
                "probe-capture",
                "jabuka.tools.probe",
                "--file",
                str(self.capture),
                "--out",
                str(pdir),
            )
            if (pdir / "inventory.json").is_file():
                # --file mode analyses the capture in place: keep a copy as OUT/probe/capture.log,
                # the same file name the live probe on the boat writes
                shutil.copyfile(self.capture, pdir / "capture.log")
        inv: dict = {}
        try:
            inv = json.loads((pdir / "inventory.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        res = {"code": code, "text": text, "inventory": inv, "dir": pdir}
        self.cache["probe"] = res
        return res


def verdict_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("VERDICT:"):
            v = line[len("VERDICT:") :].strip()
            return v.split(" — ", 1)[1] if " — " in v else v  # the hint repeats the title
    lines = [x for x in text.splitlines() if x.strip()]
    return lines[-1].strip() if lines else ""


def live_probe(ctx: Context, name: str, replay_args: list[str], out: Path) -> tuple[int, str]:
    """jabuka-replay of --capture into a pty (with replay_args), then fastnet-probe --device on
    its link for PROBE_LIVE_S seconds, exactly like on the boat."""
    link = ctx.out / "pty" / f"{name}-fastnet"
    link.parent.mkdir(parents=True, exist_ok=True)
    replay = ctx.spawn(
        f"replay-{name}",
        "jabuka.sim.pty_replay",
        str(ctx.capture),
        "--link",
        str(link),
        *replay_args,
    )
    try:
        if not wait_for(link.is_symlink, 10):
            return 1, "jabuka-replay n'a pas créé le pty"
        return ctx.run(
            f"probe-{name}",
            "jabuka.tools.probe",
            "--device",
            str(link),
            "--seconds",
            str(PROBE_LIVE_S),
            "--out",
            str(out),
            timeout=60,
        )
    finally:
        ctx.stop(replay)


# -- §2 wiring: the swap-wires drill -----------------------------------------------------------
def _write_capture(path: Path, data: bytes, line: int = 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(data[i : i + line].hex() + "\n" for i in range(0, len(data), line))
    atomic_write_bytes(path, text.encode("ascii"))
    return path


def _garbage_laced(data: bytes, rate: float = 0.5, seed: int = 3) -> bytes:
    """Seeded garbage interleaved in 64-byte chunks (what jabuka-replay --garbage-rate does)."""
    rng = random.Random(seed)
    out = bytearray()
    for i in range(0, len(data), 64):
        part = data[i : i + 64]
        if rng.random() < rate:
            part = rng.randbytes(rng.randint(1, 32)) + part
        out += part
    return bytes(out)


# per drill: (bytes transform for --file mode, jabuka-replay flags for the live mode)
_DRILLS: dict[str, tuple[Callable[[bytes], bytes], list[str]]] = {
    "silent": (lambda d: b"", ["--silence", "0:3600"]),
    "no_frames": (lambda d: bytes(b ^ 0xFF for b in d), ["--loop", "--invert"]),
    "noisy": (_garbage_laced, ["--loop", "--garbage-rate", "0.5", "--seed", "3"]),
    "ok": (lambda d: d, ["--loop"]),
}


def drill(verdict: str) -> Callable[[Context], Result]:
    def fn(ctx: Context) -> Result:
        from jabuka.ingest.fastnet_framing import load_capture

        want = EXIT_CODES[verdict]
        out = ctx.out / "drills" / verdict
        transform, replay_args = _DRILLS[verdict]
        if ctx.mode == "full":
            how = "pty en direct"
            code, text = live_probe(ctx, f"drill-{verdict}", replay_args, out)
        else:
            how = "fichier"
            data = transform(load_capture(ctx.capture))
            cap = _write_capture(out / f"{verdict}.txt", data)
            code, text = ctx.run(
                f"drill-{verdict}", "jabuka.tools.probe", "--file", str(cap), "--out", str(out)
            )
        title = VERDICT_TITLES[verdict]
        got = verdict_line(text)
        detail = f"attendu {title} (code {want}), obtenu code {code} ({how}) : {got}"
        return Result(PASS if code == want else FAIL, detail)

    return fn


# -- §3 capture and inventory ------------------------------------------------------------------
def step_capture(ctx: Context) -> Result:
    p = ctx.probe_capture()
    pdir: Path = p["dir"]
    have = [n for n in ("capture.log", "inventory.json") if (pdir / n).is_file()]
    detail = f"probe code {p['code']} : {verdict_line(p['text'])} ; fichiers {have}"
    ok = p["code"] == EXIT_CODES["ok"] and len(have) == 2
    return Result(PASS if ok else FAIL, detail)


def _inventory_paths(inv: dict) -> set[str]:
    paths: set[str] = set()
    for c in (inv.get("channels") or {}).values():
        paths.update(c.get("paths") or [])
    return paths


def step_inventory(ctx: Context) -> Result:
    inv = ctx.probe_capture()["inventory"]
    chans = inv.get("channels") or {}
    decoded = {k: c for k, c in chans.items() if c.get("paths")}
    if not decoded:
        return Result(FAIL, f"aucun canal décodé ({len(chans)} canaux vus)")
    names = ", ".join(f"{k} {c.get('name', '')}".strip() for k, c in decoded.items())
    return Result(PASS, f"{len(decoded)} canaux décodés sur {len(chans)} vus : {names}")


def step_archive(ctx: Context) -> Result:
    p = ctx.probe_capture()
    pdir: Path = p["dir"]
    files = [pdir / n for n in ("capture.log", "inventory.json")]
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        return Result(FAIL, f"rien à archiver : {missing} absents")
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    adir = ctx.out / "archive"
    adir.mkdir(parents=True, exist_ok=True)
    tgz = adir / f"capture-{ts}.tar.gz"
    raw = io.BytesIO()
    with tarfile.TarFile(fileobj=raw, mode="w") as tar:
        for f in files:
            tar.add(f, arcname=f.name)
    data = gzip.compress(raw.getvalue(), mtime=0)
    atomic_write_bytes(tgz, data)
    digest = hashlib.sha256(data).hexdigest()
    atomic_write_bytes(Path(f"{tgz}.sha256"), f"{digest}  {tgz.name}\n".encode())
    return Result(PASS, f"{tgz} (sha256 {digest[:12]}…)")


def step_replay(ctx: Context) -> Result:
    """The capture replays cleanly through the live pipeline: jabuka-replay -> pty ->
    jabuka-ingest-fastnet -> UDP -> jabuka-core, every decoded path served by /api/state."""
    want = _inventory_paths(ctx.probe_capture()["inventory"])
    if not want:
        return Result(FAIL, "l'inventaire ne contient aucun chemin décodé")
    rdir = ctx.out / "replay"
    data_dir = rdir / "data"
    link = rdir / "fastnet-pty"
    http, udp = free_port(), free_port(socket.SOCK_DGRAM)
    replay = ingest = core = None
    t0 = time.monotonic()
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        replay = ctx.spawn(
            "replay",
            "jabuka.sim.pty_replay",
            str(ctx.capture),
            "--link",
            str(link),
            "--speed",
            "20",
            "--loop",
        )
        if not wait_for(link.is_symlink, 10):
            return Result(FAIL, "jabuka-replay n'a pas créé le pty")
        core = ctx.spawn(
            "replay-core",
            "jabuka.core.main",
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(http),
            "--udp-port",
            str(udp),
            "--data-dir",
            str(data_dir),
            "--clock",
            "system",
            "--gpsd",
            "none",
        )
        ingest = ctx.spawn(
            "replay-ingest",
            "jabuka.ingest.fastnet_main",
            "--device",
            str(link),
            "--udp",
            f"127.0.0.1:{udp}",
            "--data-dir",
            str(data_dir),
        )
        got: set[str] = set()

        def served() -> bool:
            nonlocal got
            r = httpx.get(f"http://127.0.0.1:{http}/api/state", timeout=1.0)
            got = {v["path"] for v in r.json()["values"] if v.get("src") == "fastnet"}
            return want <= got

        ok = wait_for(served, REPLAY_DEADLINE_S, 0.25)
        dt = time.monotonic() - t0
        ctx.cache["replay_data"] = data_dir
        if ok:
            return Result(
                PASS, f"{len(want)} chemins de l'inventaire servis par /api/state en {dt:.1f} s"
            )
        miss = sorted(want - got)
        return Result(FAIL, f"{len(miss)} chemins absents après {dt:.0f} s : {miss[:8]}")
    finally:
        for proc in (ingest, core, replay):
            ctx.stop(proc)


def step_logcheck(ctx: Context) -> Result:
    data_dir = ctx.cache.get("replay_data")
    if data_dir is None:
        res = step_replay(ctx)
        if res.status != PASS:
            return Result(FAIL, f"rejeu impossible : {res.detail}")
        data_dir = ctx.cache["replay_data"]
    logs = Path(data_dir) / "logs"
    code, text = ctx.run("logcheck", "jabuka.tools.logcheck", str(logs))
    last = [x for x in text.splitlines() if x.strip()]
    return Result(
        PASS if code == 0 else FAIL, f"jabuka-logcheck code {code} : {last[-1] if last else ''}"
    )


# -- §1 before leaving home --------------------------------------------------------------------
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def lock_pins(lock: Path) -> dict[str, str]:
    """name (PEP 503 normalised) -> pinned version, from a uv-compiled requirements lock."""
    pins: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)", line)
        if m:
            pins[_norm(m.group(1))] = m.group(2)
    return pins


def wheelhouse_problems(lock: Path, wheelhouse: Path) -> list[str]:
    """Same rule as scripts/build-wheelhouse.sh: exactly one wheel per pin, at the pinned version,
    plus one jabuka wheel."""
    if not wheelhouse.is_dir():
        return [f"{wheelhouse} absent"]
    by_name: dict[str, list[str]] = {}
    for w in sorted(wheelhouse.glob("*.whl")):
        name, version = w.name.split("-")[:2]
        by_name.setdefault(_norm(name), []).append(version)
    bad = []
    for name, version in sorted(lock_pins(lock).items()):
        found = by_name.get(name, [])
        if found != [version]:
            bad.append(f"{name}=={version} : trouvé {found}")
    if len(by_name.get("jabuka", [])) != 1:
        bad.append("il faut exactement une roue jabuka-*.whl")
    return bad


def step_wheelhouse(ctx: Context) -> Result:
    lock = REPO / "deploy" / "requirements.lock"
    wh = REPO / "deploy" / "wheelhouse"
    bad = wheelhouse_problems(lock, wh)
    if bad:
        return Result(FAIL, f"{'; '.join(bad[:4])} -> bash scripts/build-wheelhouse.sh")
    return Result(PASS, f"{len(lock_pins(lock))} paquets verrouillés, une roue chacun + jabuka")


def latest_soak_report(soak_dir: Path, scenario: str = "race-36h") -> tuple[Path, dict] | None:
    best: tuple[str, Path, dict] | None = None
    for path in soak_dir.glob("*/report.json"):
        try:
            rep = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rep, dict) or rep.get("scenario") != scenario:
            continue
        key = path.parent.name  # <UTC ts>-<scenario>: sorts by time
        if best is None or key > best[0]:
            best = (key, path, rep)
    return None if best is None else (best[1], best[2])


def step_soak(ctx: Context) -> Result:
    found = latest_soak_report(REPO / "var" / "soak")
    if found is None:
        return Result(
            HUMAN,
            "aucun rapport race-36h dans var/soak : bash scripts/soak.sh "
            "(docs/SOAK.md), puis le même essai sur le Pi",
        )
    path, rep = found
    host = (rep.get("host") or {}).get("machine")
    head = ((rep.get("git") or {}).get("head") or "?")[:10]
    detail = f"{path.relative_to(REPO)} : {rep.get('verdict')} ({host}, code {head})"
    return Result(PASS if rep.get("verdict") == "PASS" else FAIL, detail)


# -- the synthetic boat (§4–§8) ----------------------------------------------------------------
BOAT_START_UTC = datetime(2026, 11, 13, 18, 0, 0, tzinfo=UTC)
BOAT_TWD, BOAT_TWS, BOAT_TWA = 161.0, 12.0, 45.0  # starboard tack, true heading 116
BOAT_SPEED = 10.0  # sim seconds per real second
PLIC = (43.684627, 15.811626)
# bus-silent windows (sim seconds after the synth starts), placed after §6/§7 have run
GRIB_WINDOW = (900.0, 200.0)
MANUAL_WINDOW = (1300.0, 400.0)
ROUTE_DEADLINE_S = 60.0
DRILL_BUDGET_S = 30.0
MASK = REPO / "tests" / "fixtures" / "route" / "landmask_race_25m"


class StackError(Exception):
    pass


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def write_boat_pack(pack: Path, start: datetime) -> Path:
    """Rehearsal race pack: the committed 25 m land mask plus a uniform wind (the synth's wind)
    covering start - 1 day .. start + 3 days, written with the race-pack writer."""
    import numpy as np

    from jabuka.common.units import kn_to_ms
    from jabuka.prep.wxpack import write_npz

    pack.mkdir(parents=True, exist_ok=True)
    for suffix in (".npz", ".json"):
        src = MASK.with_suffix(suffix)
        if not src.is_file():
            raise StackError(f"masque terre de test absent : {src}")
        shutil.copyfile(src, pack / f"landmask{suffix}")
    t0 = int(start.timestamp()) - 86400
    t = np.arange(t0, t0 + 4 * 86400 + 1, 3600, dtype=np.int64)
    lat = np.arange(42.5, 44.3, 0.25, dtype=np.float64)
    lon = np.arange(14.75, 16.6, 0.25, dtype=np.float64)
    ms = kn_to_ms(BOAT_TWS)
    u = -ms * math.sin(math.radians(BOAT_TWD))
    v = -ms * math.cos(math.radians(BOAT_TWD))
    shape = (t.size, lat.size, lon.size)
    arrays = {
        "t": t,
        "lat": lat,
        "lon": lon,
        "u": np.full(shape, u, np.float32),
        "v": np.full(shape, v, np.float32),
        "model": "uniform",
        "run": start.strftime("%Y-%m-%dT%H:%MZ"),
    }
    return write_npz(
        pack, "wind", arrays, {"source": "rehearsal", "model": "uniform", "run": "rehearsal"}
    )


class BoatStack:
    """jabuka-sim (pty, fake gpsd) -> jabuka-ingest-fastnet -> jabuka-core (--clock sim, the
    synth's gpsd, the rehearsal race pack). Started once, on the first step that needs it."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.dir = ctx.out / "boat"
        self.data = self.dir / "data"
        self.pack = self.dir / "racepack"
        self.link = self.dir / "fastnet-pty"
        self.http = free_port()
        self.udp = free_port(socket.SOCK_DGRAM)
        self.gpsd = free_port()
        self.base = f"http://127.0.0.1:{self.http}"
        self.client = httpx.Client(base_url=self.base, timeout=5.0)
        self.core: subprocess.Popen | None = None
        self.ingest: subprocess.Popen | None = None
        self.synth: subprocess.Popen | None = None
        self.variation = 0.0
        self.start_epoch = BOAT_START_UTC.timestamp()
        self.restarts = 0

    # -- processes ---------------------------------------------------------------------------
    def _core_args(self) -> list[str]:
        return [
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(self.http),
            "--udp-port",
            str(self.udp),
            "--data-dir",
            str(self.data),
            "--racepack",
            str(self.pack),
            "--clock",
            "sim",
            "--gpsd",
            f"127.0.0.1:{self.gpsd}",
        ]

    def _ingest_args(self) -> list[str]:
        return [
            "--device",
            str(self.link),
            "--udp",
            f"127.0.0.1:{self.udp}",
            "--data-dir",
            str(self.data),
        ]

    def _spawn_core(self) -> None:
        self.restarts += 1
        self.core = self.ctx.spawn(
            f"boat-core-{self.restarts}", "jabuka.core.main", *self._core_args()
        )
        if not wait_for(lambda: self.client.get("/api/course").status_code == 200, 30, 0.1):
            raise StackError("jabuka-core ne répond pas sur /api/course")

    def _spawn_ingest(self) -> None:
        self.ingest = self.ctx.spawn(
            f"boat-ingest-{self.restarts}", "jabuka.ingest.fastnet_main", *self._ingest_args()
        )

    def start(self) -> None:
        from jabuka.nav import geo

        self.dir.mkdir(parents=True, exist_ok=True)
        write_boat_pack(self.pack, BOAT_START_UTC)
        self._spawn_core()
        self.variation = float(self.client.get("/api/settings").json()["settings"]["variation_deg"])
        lat, lon = geo.offset(*PLIC, math.radians(341.0), 1.5)
        faults = [
            f"bus-silent@{GRIB_WINDOW[0]:g}+{GRIB_WINDOW[1]:g}",
            f"bus-silent@{MANUAL_WINDOW[0]:g}+{MANUAL_WINDOW[1]:g}",
        ]
        self.synth = self.ctx.spawn(
            "boat-synth",
            "jabuka.sim.synth",
            "--mode",
            "pty",
            "--link",
            str(self.link),
            "--speed",
            f"{BOAT_SPEED:g}",
            "--duration",
            "36000",
            "--twd",
            f"{BOAT_TWD:g}",
            "--tws",
            f"{BOAT_TWS:g}",
            "--twa",
            f"{BOAT_TWA:g}",
            "--start",
            f"{lat:.6f},{lon:.6f}",
            "--start-utc",
            BOAT_START_UTC.isoformat(),
            "--variation",
            f"{self.variation:g}",
            "--gpsd-port",
            str(self.gpsd),
            "--wait-reader",
            "30",
            "--seed",
            "1",
            *[x for f in faults for x in ("--fault", f)],
        )
        if not wait_for(self.link.is_symlink, 15):
            raise StackError("jabuka-sim n'a pas créé le pty")
        self._spawn_ingest()
        if not self.wait_source("LIVE", 30):
            raise StackError(f"pas de vent LIVE après 30 s : {self.nav().get('wind')}")

    def stop(self) -> None:
        for proc in (self.ingest, self.core, self.synth):
            self.ctx.stop(proc)
        self.client.close()

    def power_pull(self) -> float:
        """SIGKILL ingest + core (the Pi losing power), then restart both from the data dir.
        Returns the seconds until the core answers again."""
        self.ctx.stop(self.ingest, signal.SIGKILL)
        self.ctx.stop(self.core, signal.SIGKILL)
        t0 = time.monotonic()
        self._spawn_core()
        self._spawn_ingest()
        return time.monotonic() - t0

    # -- HTTP --------------------------------------------------------------------------------
    def nav(self) -> dict:
        return self.client.get("/api/nav").json()

    def fastnet_rows(self) -> dict[str, dict]:
        vals = self.client.get("/api/state").json()["values"]
        return {v["path"]: v for v in vals if v.get("src") == "fastnet"}

    def sim_t(self) -> float | None:
        utc = self.nav().get("utc")
        if not utc:
            return None
        return datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp() - self.start_epoch

    def wait_sim(self, t: float) -> float | None:
        """Wait until the synth's clock reaches t sim seconds (bounded by the real time left)."""
        now = self.sim_t() or 0.0
        timeout = max(0.0, t - now) / BOAT_SPEED + 30.0
        return wait_for(lambda: (self.sim_t() or 0.0) >= t and (self.sim_t() or 0.0), timeout, 0.2)

    def wait_source(self, source: str, timeout: float) -> dict | None:
        def ok() -> dict | None:
            nav = self.nav()
            return nav if (nav.get("wind") or {}).get("source") == source else None

        return wait_for(ok, timeout, 0.1)


def boat(ctx: Context) -> BoatStack:
    err = ctx.cache.get("boat_error")
    if err is not None:
        raise StackError(f"bateau de synthèse indisponible : {err}")
    stack = ctx.cache.get("boat")
    if stack is None:
        stack = BoatStack(ctx)
        ctx.cache["boat"] = stack
        try:
            stack.start()
        except Exception as e:
            ctx.cache["boat_error"] = str(e)
            raise StackError(f"bateau de synthèse indisponible : {e}") from e
    return stack


def boat_step(fn: Callable[[Context, BoatStack], Result]) -> Callable[[Context], Result]:
    def wrapped(ctx: Context) -> Result:
        try:
            return fn(ctx, boat(ctx))
        except StackError as e:
            return Result(FAIL, str(e))

    return wrapped


def _settled(b: BoatStack) -> tuple[dict, dict[str, dict]]:
    nav = b.wait_source("LIVE", 30)
    if nav is None:
        raise StackError(f"vent pas LIVE : {b.nav().get('wind')}")
    time.sleep(1.0)  # one more second of filtered values
    return b.nav(), b.fastnet_rows()


# -- §4 instrument checks ----------------------------------------------------------------------
def step_variation(ctx: Context, b: BoatStack) -> Result:
    nav, rows = _settled(b)
    hdg_t = (nav.get("boat") or {}).get("hdg_t")
    row = rows.get("navigation.heading")
    if hdg_t is None or row is None:
        return Result(FAIL, f"cap absent (nav {hdg_t}, bus {row})")
    hdg_m = math.degrees(row["value"]) % 360.0
    bus_t = (hdg_m + b.variation) % 360.0
    exp_t = (BOAT_TWD - BOAT_TWA) % 360.0
    d1, d2 = angle_diff(hdg_t, bus_t), angle_diff(hdg_t, exp_t)
    detail = (
        f"cap bus {hdg_m:.1f}°{row.get('ref')} + variation {b.variation:g}° = {bus_t:.1f}°T,"
        f" nav {hdg_t:.1f}°T, bateau {exp_t:.1f}°T (écarts {d1:.1f}° / {d2:.1f}°)"
    )
    ok = row.get("ref") == "M" and d1 <= 1.0 and d2 <= 1.0
    return Result(PASS if ok else FAIL, detail)


def step_cog_hdg(ctx: Context, b: BoatStack) -> Result:
    nav, _ = _settled(b)
    bt = nav.get("boat") or {}
    hdg, cog = bt.get("hdg_t"), bt.get("cog_t")
    if hdg is None or cog is None:
        return Result(FAIL, f"cap {hdg} / COG {cog} absent")
    d = angle_diff(hdg, cog)
    return Result(
        PASS if d <= 3.0 else FAIL,
        f"COG {cog:.1f}°T, cap vrai {hdg:.1f}°T : écart {d:.1f}° (≤ 3°, sans courant)",
    )


def step_awa_sign(ctx: Context, b: BoatStack) -> Result:
    nav, rows = _settled(b)
    awa = rows.get("environment.wind.angleApparent")
    twa = (nav.get("wind") or {}).get("twa")
    if awa is None or twa is None:
        return Result(FAIL, f"AWA {awa} / TWA {twa} absent")
    awa_deg = math.degrees(awa["value"])
    ok = awa_deg > 0 and twa > 0
    return Result(
        PASS if ok else FAIL,
        f"tribord amures (TWA +{BOAT_TWA:g}) → AWA {awa_deg:+.0f}°, "
        f"TWA nav {twa:+.0f}° (convention : + = vent sur tribord)",
    )


def step_twd(ctx: Context, b: BoatStack) -> Result:
    nav, rows = _settled(b)
    twd = (nav.get("wind") or {}).get("twd_t")
    if twd is None:
        return Result(FAIL, "TWD calculé absent")
    d = angle_diff(twd, BOAT_TWD)
    parts = [f"TWD calculé {twd:.1f}°T contre {BOAT_TWD:g}°T scripté : écart {d:.1f}° (≤ 5°)"]
    ok = d <= 5.0
    inst = rows.get("environment.wind.direction")
    if inst is None:
        parts.append(
            "moitié instrument SKIP : le bateau de synthèse n'émet pas le canal TWD "
            "0x6D (à comparer à bord, R4.underway)"
        )
    else:
        from jabuka.common.units import wrap_2pi

        ref = inst.get("ref")
        tw = math.degrees(inst["value"]) + (b.variation if ref != "T" else 0.0)
        di = angle_diff(math.degrees(wrap_2pi(math.radians(tw))), twd)
        parts.append(f"TWD instrument {tw % 360:.1f}°T : écart {di:.1f}°")
        ok = ok and di <= 5.0
    return Result(PASS if ok else FAIL, " ; ".join(parts))


# -- §5 tablet ---------------------------------------------------------------------------------
class _Assets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        for key in ("src", "href"):
            url = a.get(key)
            if url and tag in ("script", "link", "img", "source", "iframe", "audio", "video"):
                self.urls.append(url)


def step_offline(ctx: Context, b: BoatStack) -> Result:
    r = b.client.get("/")
    if r.status_code != 200:
        return Result(FAIL, f"GET / -> {r.status_code}")
    parser = _Assets()
    parser.feed(r.text)
    external = []
    broken = []
    for url in parser.urls:
        parts = urlsplit(url)
        if parts.scheme in ("http", "https", "") and parts.netloc not in (
            "",
            f"127.0.0.1:{b.http}",
        ):
            external.append(url)
            continue
        if parts.scheme in ("data", "blob"):
            continue
        got = b.client.get(urljoin(b.base + "/", url))
        if got.status_code != 200:
            broken.append(f"{url} ({got.status_code})")
    if external or broken:
        return Result(FAIL, f"externes {external[:5]}, absents {broken[:5]}")
    return Result(
        PASS,
        f"{len(parser.urls)} ressources de la page, toutes servies par le Pi (aucun hôte externe)",
    )


# -- §6 race pack ------------------------------------------------------------------------------
def step_pack(ctx: Context, b: BoatStack) -> Result:
    t0 = time.monotonic()

    def adopted() -> dict | None:
        route = b.nav().get("route") or {}
        ok = (route.get("version") or 0) >= 1 and (route.get("pack") or {}).get("ok")
        return route if ok else None

    route = wait_for(adopted, ROUTE_DEADLINE_S, 0.25)
    dt = time.monotonic() - t0
    if route is None:
        last = b.nav().get("route") or {}
        return Result(
            FAIL,
            f"pas de route en {ROUTE_DEADLINE_S:.0f} s : état "
            f"{last.get('state')}, {last.get('reason')}",
        )
    pack = route.get("pack") or {}
    return Result(
        PASS,
        f"route version {route['version']} adoptée en {dt:.1f} s (état "
        f"{route.get('state')}, pack {pack.get('model')} ok)",
    )


def step_dryrun(ctx: Context) -> Result:
    if not ctx.online:
        return Result(SKIP, "hors ligne (--online lance scripts/racepack-dryrun.sh)")
    proc = subprocess.run(
        ["bash", "scripts/racepack-dryrun.sh"],
        cwd=REPO,
        env={**os.environ, "PY": sys.executable},
        capture_output=True,
        text=True,
        timeout=3600,
    )
    ctx.log("racepack-dryrun", proc.stdout + proc.stderr)
    last = [x for x in (proc.stdout + proc.stderr).splitlines() if x.strip()]
    return Result(
        PASS if proc.returncode == 0 else FAIL,
        f"racepack-dryrun code {proc.returncode} : {last[-1] if last else ''}",
    )


# -- §7 course ---------------------------------------------------------------------------------
def step_drill(ctx: Context, b: BoatStack) -> Result:
    """Course-change drill, as the tablet does it (each change carries base_version): switch to
    the other template, "Finir ici" at the last mark, cancel it, "Côtés confirmés", back."""
    course = b.client.get("/api/course").json()
    first = course["template"]
    other = "B" if first == "A" else "A"
    v = course["version"]
    done: list[str] = []
    t0 = time.monotonic()

    def call(label: str, path: str, body: dict) -> dict:
        nonlocal v
        r = b.client.post(path, json={**body, "base_version": v})
        if r.status_code != 200:
            raise StackError(f"{label} : HTTP {r.status_code} {r.text[:120]}")
        new = r.json()
        if new.get("version", -1) <= v:
            raise StackError(f"{label} : version {new.get('version')} pas plus récente que {v}")
        v = new["version"]
        done.append(label)
        return new

    try:
        c = call(f"parcours {other}", "/api/course/select", {"template": other})
        last = len(c["seq"]) - 2  # the last mark before the finish
        name = c["marks"][c["seq"][last]["mark_id"]]["name"]
        call(f"Finir ici à {name}", "/api/course/finish", {"idx": last})
        call("Finir ici annulé", "/api/course/finish", {"idx": None})
        call("Côtés confirmés", "/api/course/confirm-sides", {})
        call(f"parcours {first}", "/api/course/select", {"template": first})
    except StackError as e:
        return Result(FAIL, f"{e} (fait : {', '.join(done)})")
    dt = time.monotonic() - t0
    ok = dt < DRILL_BUDGET_S
    return Result(
        PASS if ok else FAIL,
        f"{' → '.join(done)} en {dt:.2f} s (< {DRILL_BUDGET_S:.0f} s), version {v}",
    )


# -- §8 degraded-mode drills -------------------------------------------------------------------
def _window_reachable(b: BoatStack, window: tuple[float, float]) -> str | None:
    now = b.sim_t() or 0.0
    if now > window[0] + window[1] - 30.0:
        return (
            f"fenêtre bus muet {window[0]:g}+{window[1]:g} s déjà passée (t = {now:.0f} s) : "
            "les étapes précédentes ont été trop lentes"
        )
    return None


def step_gribonly(ctx: Context, b: BoatStack) -> Result:
    start, dur = GRIB_WINDOW
    late = _window_reachable(b, GRIB_WINDOW)
    if late:
        return Result(FAIL, late)
    b.wait_sim(start)
    grib = wait_for(
        lambda: b.sim_t() < start + dur and b.wait_source("GRIB", 0.1), dur / BOAT_SPEED
    )
    if not grib:
        return Result(FAIL, f"pendant le bus muet la source reste {b.nav().get('wind')}")
    w = grib.get("wind") or {}
    alerts = [a for a in grib.get("alerts", []) if "GRIB" in a]
    b.wait_sim(start + dur)
    live = b.wait_source("LIVE", 30)
    if live is None:
        return Result(FAIL, f"après le bus muet, pas de retour LIVE : {b.nav().get('wind')}")
    return Result(
        PASS,
        f"bus muet → GRIB (TWD {w.get('twd_t')}°T, {w.get('tws_kn')} nd, alerte "
        f"{alerts[:1]}) → LIVE au retour du bus",
    )


def step_manual(ctx: Context, b: BoatStack) -> Result:
    start, dur = MANUAL_WINDOW
    late = _window_reachable(b, MANUAL_WINDOW)
    if late:
        return Result(FAIL, late)
    b.wait_sim(start)
    before = b.wait_source("GRIB", 30)
    if before is None:
        return Result(FAIL, f"bus muet sans source GRIB : {b.nav().get('wind')}")
    prev = before["wind"]["source"]
    twd_m, tws = 150.0, 14.0
    r = b.client.post("/api/wind/manual", json={"twd": twd_m, "tws_kn": tws, "ref": "M"})
    if r.status_code != 200:
        return Result(FAIL, f"POST /api/wind/manual -> {r.status_code} {r.text[:120]}")
    man = b.wait_source("MANUEL", 10)
    if man is None:
        return Result(FAIL, f"vent manuel saisi, source {b.nav().get('wind')}")
    twd_t = man["wind"].get("twd_t")
    exp = (twd_m + b.variation) % 360.0
    if twd_t is None or angle_diff(twd_t, exp) > 1.0:
        return Result(FAIL, f"MANUEL TWD {twd_t}°T, attendu {exp:.1f}°T ({twd_m:g}°M + var)")
    r = b.client.delete("/api/wind/manual")
    back = b.wait_source(prev, 10) if r.status_code == 200 else None
    if back is None:
        return Result(
            FAIL,
            f"vent manuel effacé (HTTP {r.status_code}), source "
            f"{b.nav().get('wind')} au lieu de {prev}",
        )
    return Result(
        PASS, f"{prev} → saisie {twd_m:g}°M {tws:g} nd → MANUEL {twd_t:.1f}°T → effacé → {prev}"
    )


def step_stay(ctx: Context, b: BoatStack) -> Result:
    def stay(active: bool) -> dict | None:
        r = b.client.post("/api/route/stay", json={"active": active})
        if r.status_code != 200:
            return None
        nav = r.json()
        got = ((nav.get("route") or {}).get("stay") or {}).get("active")
        return nav if got is active else None

    on = wait_for(lambda: stay(True), 30, 0.5)
    if on is None:
        r = b.client.post("/api/route/stay", json={"active": True})
        return Result(FAIL, f"ON RESTE refusé : HTTP {r.status_code} {r.text[:120]}")
    tack = on["route"]["stay"].get("tack")
    off = stay(False)
    if off is None:
        return Result(FAIL, "ANNULER ON RESTE sans effet")
    return Result(PASS, f"ON RESTE actif (bord {tack}) → ANNULER ON RESTE : inactif")


def step_powerpull(ctx: Context, b: BoatStack) -> Result:
    b.wait_sim(MANUAL_WINDOW[0] + MANUAL_WINDOW[1])  # the bus talks again
    s = b.client.get("/api/settings").json()
    r = b.client.put(
        "/api/settings", json={"base_version": s["version"], "patch": {"efficiency": 0.9}}
    )
    if r.status_code != 200:
        return Result(FAIL, f"PUT /api/settings -> {r.status_code}")
    b.client.post("/api/wind/manual", json={"twd": 200.0, "tws_kn": 10.0, "ref": "T"})
    snap = {k: b.client.get(f"/api/{k}").json() for k in ("course", "settings", "wind/manual")}
    if not snap["wind/manual"].get("manual"):
        return Result(FAIL, "vent manuel non enregistré avant la coupure")
    dt = b.power_pull()
    after = {k: b.client.get(f"/api/{k}").json() for k in snap}
    diff = [k for k in snap if snap[k] != after[k]]
    live = wait_for(lambda: "environment.wind.angleApparent" in b.fastnet_rows(), 30, 0.2)
    b.client.delete("/api/wind/manual")
    code, text = ctx.run("boat-logcheck", "jabuka.tools.logcheck", str(b.data / "logs"))
    problems = []
    if diff:
        problems.append(f"différent après redémarrage : {diff}")
    if not live:
        problems.append("pas de données du bus après redémarrage")
    if code != 0:
        problems.append(f"jabuka-logcheck code {code}")
    if problems:
        return Result(FAIL, "; ".join(problems))
    return Result(
        PASS,
        f"kill -9 ingest + cœur, redémarrage en {dt:.1f} s : parcours, réglages et "
        "vent manuel identiques, bus de retour, jabuka-logcheck OK",
    )


# -- §9 go / no-go -----------------------------------------------------------------------------
def step_summary(ctx: Context) -> Result:
    counts = {
        k: [sid for sid, r in ctx.results.items() if r.status == k]
        for k in (PASS, FAIL, SKIP, HUMAN)
    }
    text = (
        f"{len(counts[PASS])} PASS, {len(counts[FAIL])} FAIL, {len(counts[SKIP])} SKIP, "
        f"{len(counts[HUMAN])} HUMAN"
    )
    if counts[FAIL]:
        return Result(FAIL, f"{text} ; en échec : {', '.join(counts[FAIL])} -> pas de GO technique")
    return Result(PASS, f"{text} ; répétition sans échec (les HUMAN se font à bord)")


# -- the registry ------------------------------------------------------------------------------
def _human(sid: str, section: int, title: str, expected: str, quick: bool = False) -> Step:
    return Step(sid, section, title, "human", quick, expected)


def _auto(
    sid: str,
    section: int,
    title: str,
    fn: Callable[[Context], Result],
    quick: bool,
    verdict: str | None = None,
) -> Step:
    return Step(sid, section, title, "auto", quick, "", fn, verdict)


STEPS: tuple[Step, ...] = (
    # §1 Avant de partir (maison)
    _human(
        "R1.packing",
        1,
        "Sac de bord",
        "Liste de colisage du §1 cochée : Pi en boîtier, SD de secours étiquetée, DTECH et "
        "faisceau, VK-162, câbles USB et alimentation, convertisseur 12 V→USB (≥ 3 A), fusibles, "
        "outils, tablette + chargeur + support 3D, portable + chargeur, clé USB (pack, archive), "
        "carte du parcours et runbook imprimés",
    ),
    _auto("R1.wheelhouse", 1, "Wheelhouse complète", step_wheelhouse, False),
    _auto("R1.soak", 1, "Endurance race-36h", step_soak, False),
    # §2 Câblage du bus Fastnet
    _human(
        "R2.wiring",
        2,
        "Prise sur le bus",
        "Blanc = Data+ (A, T/R+), Vert = Data− (B, T/R−) sur le DTECH, masse (GND) reliée, "
        "écoute seule, aucune terminaison ajoutée ; photos du câblage ; contrôles réception seule "
        "PI-SETUP §4 b et d (/dev/fastnet crw-r----- root dialout, lsof : seul l'ingest)",
        quick=True,
    ),
    _auto("R2.silent", 2, "Bus muet → NO BYTES", drill("silent"), True, "silent"),
    _auto(
        "R2.swap", 2, "Fils inversés → croiser Blanc/Vert", drill("no_frames"), True, "no_frames"
    ),
    _auto("R2.noisy", 2, "Bus bruité → NOISY", drill("noisy"), True, "noisy"),
    _auto("R2.ok", 2, "Bon câblage → OK", drill("ok"), True, "ok"),
    # §3 Capture et inventaire
    _human(
        "R3.pages",
        3,
        "Pages B&G pendant la capture",
        "Capture brute AVANT toute autre action ; pendant la capture, faire défiler TOUTES les "
        "pages de TOUS les afficheurs B&G (cap vrai/magnétique, TWD, set/drift, VMG, cible) pour "
        "que chaque canal du bus apparaisse dans inventory.json ; puis archiver sur le portable",
        quick=True,
    ),
    _auto("R3.capture", 3, "Capture brute (fastnet-probe)", step_capture, True),
    _auto("R3.inventory", 3, "Inventaire des canaux", step_inventory, True),
    _auto("R3.archive", 3, "Archive de la capture", step_archive, True),
    _auto("R3.replay", 3, "Rejeu propre dans la chaîne", step_replay, True),
    _auto("R3.logcheck", 3, "Journaux du rejeu intacts", step_logcheck, True),
    # §4 Contrôles des instruments
    _auto(
        "R4.variation", 4, "Cap magnétique + variation = cap vrai", boat_step(step_variation), True
    ),
    _auto("R4.cog_hdg", 4, "COG contre cap vrai", boat_step(step_cog_hdg), True),
    _auto("R4.awa_sign", 4, "Signe de l'AWA", boat_step(step_awa_sign), True),
    _auto("R4.twd", 4, "TWD calculé contre scripté", boat_step(step_twd), True),
    _human(
        "R4.dock",
        4,
        "Contrôles au port / au moteur",
        "Au moteur en eau calme, cap stable : Diag cap vrai (cap °M + variation_deg) contre COG "
        "GPS, écart < 3° (sinon heading_offset_deg ou variation_deg) ; signe de l'AWA : vent sur "
        "tribord = AWA positif (sinon --awa-sign -1 par drop-in) ; BSP contre SOG à l'étale",
        quick=True,
    ),
    _human(
        "R4.underway",
        4,
        "Contrôles sous voiles",
        "Sur les deux bords : TWD Hercules contre TWD calculé (Diag, écart < 10°), symétrie "
        "bâbord/tribord du TWD, laylines plausibles ; choisir true_wind_source (computed par "
        "défaut, instrument si le TWD Hercules est plus stable) (02-UAT #8)",
        quick=True,
    ),
    # §5 Tablette
    _auto("R5.offline", 5, "Page de barre sans internet", boat_step(step_offline), True),
    _human(
        "R5.setup",
        5,
        "Réglage de la tablette",
        "TABLET-SETUP §1–§8 faits : réseau jabuka, mode avion + Wi-Fi, drapeau Chrome "
        "(ÉCRAN: verrou), Stay awake, plein écran, carte, mode nuit, verrouillage ; 02-UAT #1–#4 "
        "cochés ; tablette fixée dans le support 3D à la barre",
    ),
    # §6 Pack de course
    _auto("R6.pack", 6, "Route adoptée sur le pack", boat_step(step_pack), False),
    _auto("R6.dryrun", 6, "Répétition du pack réel", step_dryrun, False),
    _human(
        "R6.friday",
        6,
        "Pack final du vendredi",
        "WEATHER-PACK.md « Checklist vendredi 13 novembre » après ≈ 15:40 UTC : ICON-EU et EWAM du "
        "run 12Z, COUVERTURE MÉTÉO : OK, copie au Pi, redémarrage de jabuka-core, route visible "
        "sur la tablette en moins de 1 min",
    ),
    # §7 Parcours
    _auto("R7.drill", 7, "Changement de parcours", boat_step(step_drill), True),
    _human(
        "R7.si",
        7,
        "Parcours d'après les IC",
        "À l'inscription (13 nov. 12:00–18:00) : côtés de passage et ligne de départ/arrivée "
        "d'après les IC, demande sur l'électronique autorisée ; sur la tablette : parcours, côtés, "
        "« Côtés confirmés » ; exercice de changement de parcours en moins de 30 s (02-UAT #6)",
    ),
    # §8 Exercices en mode dégradé
    _auto("R8.gribonly", 8, "Bus muet → GRIB", boat_step(step_gribonly), False),
    _auto("R8.manual", 8, "Vent manuel", boat_step(step_manual), False),
    _auto("R8.stay", 8, "ON RESTE", boat_step(step_stay), False),
    _auto("R8.powerpull", 8, "Coupure d'alimentation", boat_step(step_powerpull), False),
    _human(
        "R8.boat",
        8,
        "Exercices à bord",
        "DTECH débranché : badge GRIB puis saisie du TWD/TWS lus sur le B&G (°M) → MANUEL ; "
        "ON RESTE puis ANNULER ON RESTE ; coupure d'alimentation du Pi : tout revient en ~2 min "
        "avec le même parcours (01-UAT #7, 02-UAT #9)",
    ),
    _human(
        "R8.sdswap",
        8,
        "Échange de carte SD",
        "SPARE-SD.md « Échange de carte en mer » : éteindre, changer de carte, rallumer, la "
        "tablette se reconnecte, recopier le pack, re-sélectionner le parcours, vérifier réglages",
    ),
    # §9 Go / no-go et plans B
    _auto("R9.summary", 9, "Bilan go / no-go", step_summary, True),
)


# -- runner ------------------------------------------------------------------------------------
def select_steps(spec: str) -> tuple[list[Step], str]:
    """(steps in registry order, mode). quick: steps flagged quick, probes on files; all: every
    step, live probe drills; ID,ID: those steps, probes on files."""
    if spec == "quick":
        return [s for s in STEPS if s.quick], "quick"
    if spec == "all":
        return list(STEPS), "full"
    wanted = [x.strip() for x in spec.split(",") if x.strip()]
    ids = {s.id for s in STEPS}
    unknown = [x for x in wanted if x not in ids]
    if unknown or not wanted:
        raise SetupError(f"étape inconnue : {unknown or spec!r} (connues : {sorted(ids)})")
    return [s for s in STEPS if s.id in wanted], "quick"


def format_line(step: Step, res: Result) -> str:
    return f"[{res.status}] {step.id} §{step.section} {step.title} : {res.detail}"


def run_steps(ctx: Context, steps: list[Step], echo: Callable[[str], None] = print) -> int:
    try:
        for step in steps:
            t0 = time.monotonic()
            if step.kind == "human":
                res = Result(HUMAN, step.expected)
            else:
                assert step.fn is not None
                try:
                    res = step.fn(ctx)
                except Exception as e:  # noqa: BLE001 - one broken step must not hide the rest
                    res = Result(FAIL, f"erreur interne : {type(e).__name__}: {e}")
            ctx.results[step.id] = res
            ctx.cache.setdefault("durations", {})[step.id] = round(time.monotonic() - t0, 1)
            echo(format_line(step, res))
    finally:
        stack = ctx.cache.get("boat")
        if stack is not None:
            stack.stop()
        ctx.stop_all()
        ctx.save_logs()
    return 1 if any(r.status == FAIL for r in ctx.results.values()) else 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-rehearsal",
        description=(
            "Répétition du runbook de mise en service (docs/COMMISSIONING.md) sur le portable : "
            "une ligne PASS/FAIL/SKIP/HUMAN par étape."
        ),
        epilog="Codes de sortie : 0 aucune étape en échec, 1 au moins un FAIL, 2 erreur de mise "
        "en place.",
    )
    p.add_argument(
        "--steps",
        default="quick",
        help="quick (défaut, la porte), all (répétition complète) ou une liste ID,ID",
    )
    p.add_argument(
        "--capture",
        default=str(DEFAULT_CAPTURE),
        help="capture Fastnet à rejouer (défaut : la capture de test ; le 12 nov. : celle du "
        "bateau, capture.log)",
    )
    p.add_argument("--out", default=None, help="dossier de sortie (défaut var/rehearsal/<UTC>)")
    p.add_argument("--online", action="store_true", help="avec internet : lance racepack-dryrun")
    p.add_argument("--json", action="store_true", help="écrit OUT/results.json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        steps, mode = select_steps(args.steps)
        capture = Path(args.capture)
        if not capture.is_file() and not capture.is_absolute() and (REPO / capture).is_file():
            capture = REPO / capture
        if not capture.is_file():
            raise SetupError(f"capture introuvable : {args.capture}")
    except SetupError as e:
        print(f"jabuka-rehearsal: {e}", file=sys.stderr)
        return 2
    out = (
        Path(args.out)
        if args.out
        else Path("var/rehearsal") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ctx = Context(out=out, capture=capture.resolve(), mode=mode, online=args.online)
    t0 = time.monotonic()
    print(
        f"jabuka-rehearsal: {len(steps)} étapes ({args.steps}, sondes {'en direct' if mode == 'full' else 'sur fichier'}), "  # noqa: E501
        f"capture {capture}, sortie {out}",
        flush=True,
    )

    def echo(line: str) -> None:
        print(line, flush=True)

    def on_term(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    old = signal.signal(signal.SIGTERM, on_term)
    try:
        code = run_steps(ctx, steps, echo)
    except KeyboardInterrupt:
        ctx.stop_all()
        print("jabuka-rehearsal: interrompu", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, old)
    total = time.monotonic() - t0
    counts = {
        k: sum(1 for r in ctx.results.values() if r.status == k) for k in (PASS, FAIL, SKIP, HUMAN)
    }
    print(
        f"jabuka-rehearsal: {counts[PASS]} PASS, {counts[FAIL]} FAIL, {counts[SKIP]} SKIP, "
        f"{counts[HUMAN]} HUMAN en {total:.0f} s -> {'OK' if code == 0 else 'ÉCHEC'}",
        flush=True,
    )
    if args.json:
        payload = {
            "v": 1,
            "utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "steps_arg": args.steps,
            "mode": mode,
            "capture": str(capture),
            "total_s": round(total, 1),
            "exit_code": code,
            "counts": counts,
            "results": [
                {
                    "id": s.id,
                    "section": s.section,
                    "title": s.title,
                    "kind": s.kind,
                    "status": ctx.results[s.id].status,
                    "detail": ctx.results[s.id].detail,
                    "duration_s": ctx.cache.get("durations", {}).get(s.id),
                }
                for s in steps
                if s.id in ctx.results
            ],
        }
        atomic_write_json(out / "results.json", payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
