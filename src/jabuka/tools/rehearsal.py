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
it may read the wall clock and binds 127.0.0.1 ports and ptys only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from jabuka.tools.probe import EXIT_CODES, VERDICT_TITLES

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CAPTURE = REPO / "tests" / "fixtures" / "fastnet" / "example2_fastnet_data.txt"
PROBE_LIVE_S = 5  # fastnet-probe LIVE_MIN_SECONDS
REPLAY_DEADLINE_S = 20.0

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

    # -- subprocesses --------------------------------------------------------------------------
    def log_path(self, name: str) -> Path:
        d = self.out / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{name}.log"

    def spawn(self, name: str, module: str, *args: str) -> subprocess.Popen:
        log = open(self.log_path(name), "ab")  # noqa: SIM115 - closed with the process
        proc = subprocess.Popen(
            [sys.executable, "-m", module, *args],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=REPO,
        )
        proc._jabuka_log = log  # type: ignore[attr-defined]
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
        with open(self.log_path(name), "a", encoding="utf-8") as f:
            f.write(f"$ {module} {' '.join(args)}\n{text}\nexit {proc.returncode}\n")
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
        log = getattr(proc, "_jabuka_log", None)
        if log is not None:
            log.close()
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
    path.write_text("".join(data[i : i + line].hex() + "\n" for i in range(0, len(data), line)))
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
    with tarfile.open(tgz, "w:gz") as tar:
        for f in files:
            tar.add(f, arcname=f.name)
    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    Path(f"{tgz}.sha256").write_text(f"{digest}  {tgz.name}\n", encoding="utf-8")
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
        ctx.stop_all()
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
        (out / "results.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
