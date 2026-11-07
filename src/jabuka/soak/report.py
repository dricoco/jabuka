"""Soak report: report.json (schema 1), report.md, the verdict, and the log traceback classifier.

Keys read by plan 04-02 scripts/freeze-check.sh (frozen): schema, verdict, scenario, mode,
host.machine, git.head, git.dirty. Check names are stable (04-03 reads leak_slope).

Verdict: FAIL when any fault is not ok or any check is ok False. A check that cannot be judged has
ok None ("insufficient data ..." / "skipped: ...") and never makes the verdict PASS on its own:
it is listed as such.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = 1
CHECK_NAMES = (
    "recovery_bus",
    "recovery_gps",
    "recovery_process",
    "recovery_power",
    "route_after_recovery",
    "land",
    "persistence",
    "logcheck",
    "rss_core",
    "rss_worker",
    "leak_slope",
    "fd_growth",
    "thread_growth",
    "cpu_per_sim_s",
    "tick_ratio",
    "log_disk",
    "tracebacks",
    "error_counters",
)
GIT = "/usr/bin/git"
# Built-in expected tracebacks: only the full log partition (Task 3). Scenario files may add
# entries, each with a one-line justification ("why"); every entry is copied into the report.
BUILTIN_EXPECTED: dict[str, list[dict[str, str]]] = {
    "disk-full": [
        {
            "pattern": r"No space left on device|ENOSPC|\[Errno 28\]",
            "why": "log partition full on purpose: write errors are logged with their traceback",
        }
    ]
}
TRACEBACK_START = "Traceback (most recent call last):"
_CHAIN = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)


def check(ok: bool | None, value: Any = None, budget: Any = None, detail: str = "") -> dict:
    return {"ok": ok, "value": value, "budget": budget, "detail": detail}


def insufficient(detail: str, value: Any = None, budget: Any = None) -> dict:
    return check(None, value, budget, f"insufficient data: {detail}")


def skipped(detail: str) -> dict:
    return check(None, None, None, f"skipped: {detail}")


# -- tracebacks --------------------------------------------------------------------------------
@dataclass
class TracebackBlock:
    file: str
    line: int
    t_wall: float | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "t_wall": self.t_wall, "text": self.text}


def _split_ts(line: str) -> tuple[float | None, str]:
    """'1762470000.123 text' (supervisor log format) -> (wall, text)."""
    head, sep, rest = line.partition(" ")
    if sep:
        try:
            return float(head), rest
        except ValueError:
            pass
    return None, line


def scan_tracebacks(paths: list[Path]) -> list[TracebackBlock]:
    """Every "Traceback (most recent call last):" block (chained ones merged) in the logs."""
    out: list[TracebackBlock] = []
    for path in paths:
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        i = 0
        while i < len(lines):
            t, text = _split_ts(lines[i])
            if not text.startswith(TRACEBACK_START):
                i += 1
                continue
            start, block = i, [text]
            i += 1
            while i < len(lines):
                _t, nxt = _split_ts(lines[i])
                if nxt.startswith((" ", "\t")) or nxt.startswith(TRACEBACK_START):
                    block.append(nxt)
                    i += 1
                    continue
                if nxt in _CHAIN or nxt == "":
                    block.append(nxt)
                    i += 1
                    continue
                # the exception line ends the block, unless a chained traceback follows
                block.append(nxt)
                i += 1
                j = i
                while j < len(lines) and _split_ts(lines[j])[1] == "":
                    j += 1
                if j < len(lines) and _split_ts(lines[j])[1] in _CHAIN:
                    i = j
                    continue
                break
            out.append(TracebackBlock(Path(path).name, start + 1, t, "\n".join(block)))
    return out


def classify_tracebacks(
    blocks: list[TracebackBlock],
    windows: list[dict[str, Any]],
    expected: dict[str, list[dict[str, str]]],
    margin_s: float = 5.0,
) -> tuple[list[dict], list[dict]]:
    """(expected, unexpected). A block is expected only when it falls inside a fault window
    [t_wall, end_wall + margin_s] AND its text matches one of that fault kind's patterns."""
    exp_out: list[dict] = []
    unexp: list[dict] = []
    for b in blocks:
        hit = None
        for w in windows:
            t0, t1 = w.get("t_wall"), w.get("end_wall")
            if b.t_wall is None or t0 is None:
                continue
            end = (t1 if t1 is not None else t0) + margin_s
            if not t0 <= b.t_wall <= end:
                continue
            for rule in expected.get(w["kind"], []):
                if re.search(rule["pattern"], b.text):
                    hit = {"fault": w.get("id"), "kind": w["kind"], "why": rule["why"]}
                    break
            if hit:
                break
        rec = b.to_dict() | ({"expected_by": hit} if hit else {})
        (exp_out if hit else unexp).append(rec)
    return exp_out, unexp


def merge_expected(scenario_rules: dict[str, list[dict[str, str]]]) -> dict[str, list[dict]]:
    out = {k: list(v) for k, v in BUILTIN_EXPECTED.items()}
    for k, v in scenario_rules.items():
        out.setdefault(k, []).extend(v)
    return out


# -- environment -------------------------------------------------------------------------------
def git_info(repo: Path | None) -> dict[str, Any]:
    """HEAD sha and dirty flag via /usr/bin/git when run inside a checkout, else nulls."""
    if repo is None or not (Path(repo) / ".git").exists() or not os.path.exists(GIT):
        return {"head": None, "dirty": None}
    try:
        head = subprocess.run(
            [GIT, "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            [GIT, "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {"head": None, "dirty": None}
    return {"head": head or None, "dirty": bool(status.strip())}


def host_info() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
    }


# -- verdict -----------------------------------------------------------------------------------
def fault_ok(f: dict[str, Any]) -> bool:
    """A fault passes when it recovered within budget and nothing else failed."""
    if f.get("ok") is False:
        return False
    r, b = f.get("recovery_s"), f.get("budget_s")
    if b is not None and (r is None or r > b):
        return False
    return f.get("ok", True) is not False


def decide(report: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = []
    for f in report.get("faults", []):
        if not fault_ok(f):
            reasons.append(
                f"fault {f.get('id')} {f.get('kind')}: recovery {f.get('recovery_s')} s "
                f"(budget {f.get('budget_s')} s) {f.get('notes') or ''}".strip()
            )
    for name, c in report.get("checks", {}).items():
        if c.get("ok") is False:
            reasons.append(f"check {name}: {c.get('detail') or c.get('value')}")
    if report.get("setup_error"):
        reasons.append(f"setup: {report['setup_error']}")
    return ("FAIL" if reasons else "PASS"), reasons


def finalize(report: dict[str, Any]) -> dict[str, Any]:
    for f in report.get("faults", []):
        f["ok"] = fault_ok(f)
    verdict, reasons = decide(report)
    report["schema"] = SCHEMA
    report["verdict"] = verdict
    report["fail_reasons"] = reasons
    return report


# -- rendering ---------------------------------------------------------------------------------
def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


# (row label, fault kinds, budget key; None: each fault's own budget_s, e.g. WatchdogSec + process)
RECOVERY_CLASSES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("recovery bus (s)", ("bus-silent", "garbage", "noise", "unplug"), "bus"),
    ("recovery GPS (s)", ("gps-loss",), "gps"),
    ("recovery process restart (s)", ("kill-core", "kill-ingest", "sigterm-storm"), "process"),
    ("recovery watchdog hang (s)", ("watchdog-hang",), None),
    ("recovery power pull (s)", ("power-pull",), "power"),
    (
        "route after fault (s)",
        ("kill-worker", "clock-jump", "course-change", "stay-toggle"),
        "route",
    ),
    ("restart with a short GRIB (s)", ("grib-gap",), "process"),
    ("log writes resume after disk full (s)", ("disk-full",), "disk_resume"),
)


def _num(v: Any, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{round(v, nd):g}"
    return str(v)


def _p95(xs: list[float]) -> float:
    s = sorted(xs)
    return s[max(0, -(-95 * len(s) // 100) - 1)]  # nearest rank


def _row(item: str, measured: str, budget: str, ok: bool | None) -> dict[str, Any]:
    return {"item": item, "measured": measured, "budget": budget, "ok": ok}


def budget_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The measured value next to each CONTEXT budget (report.md "Mesures et budgets")."""
    budgets = report.get("budgets") or {}
    faults = report.get("faults") or []
    checks = report.get("checks") or {}
    rows: list[dict[str, Any]] = []
    for label, kinds, key in RECOVERY_CLASSES:
        fs = [f for f in faults if f.get("kind") in kinds]
        if key is not None:
            b = budgets.get(key)
        else:
            b = max((f["budget_s"] for f in fs if f.get("budget_s") is not None), default=None)
        if not fs:
            rows.append(_row(label, "no fault", _num(b), None))
            continue
        rec = [float(f["recovery_s"]) for f in fs if f.get("recovery_s") is not None]
        missing = len(fs) - len(rec)
        measured = (
            f"worst {_num(max(rec), 2)}, p95 {_num(_p95(rec), 2)} ({len(fs)} faults)"
            if rec
            else f"none recovered ({len(fs)} faults)"
        )
        if missing and rec:
            measured += f", {missing} without recovery"
        rows.append(_row(label, measured, _num(b), all(fault_ok(f) for f in fs)))

    def from_check(item: str, name: str, *, scale: float = 1.0, fmt: int = 3, ge: bool = False):
        c = checks.get(name) or {}
        v, b = c.get("value"), c.get("budget")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = v / scale
        if isinstance(b, (int, float)) and not isinstance(b, bool):
            b = b / scale
        measured = _num(float(v), fmt) if isinstance(v, (int, float)) else str(c.get("detail"))
        budget = ("≥ " if ge else "") + _num(b if b is None else float(b), fmt)
        rows.append(_row(item, measured, budget, c.get("ok")))

    from_check("max RSS core (MB)", "rss_core", fmt=1)
    from_check("max RSS worker (MB)", "rss_worker", fmt=1)
    leak = checks.get("leak_slope") or {}
    from_check("leak slope core (MB/36 h)", "leak_slope", fmt=2)
    w = leak.get("worker") or {}
    if w:
        rows.append(
            _row(
                "leak slope worker (MB/36 h)",
                _num(w.get("value"), 2) if w.get("value") is not None else str(w.get("detail")),
                _num(w.get("budget")),
                w.get("ok"),
            )
        )
    from_check("fd growth", "fd_growth", fmt=1)
    from_check("thread growth", "thread_growth", fmt=1)
    from_check("CPU per sim s (CPU s)", "cpu_per_sim_s", fmt=4)
    from_check("tick ratio", "tick_ratio", ge=True)
    from_check("log usage (MB)", "log_disk", scale=1024 * 1024, fmt=0)
    routes = report.get("routes") or []
    bad = [r for r in routes if r.get("land_ok") is False]
    land = checks.get("land") or {}
    rows.append(_row("land crossings", f"{len(bad)} of {len(routes)} routes", "0", land.get("ok")))
    tb = checks.get("tracebacks") or {}
    rows.append(_row("unexpected tracebacks", _num(tb.get("value")), "0", tb.get("ok")))
    return rows


def render_md(report: dict[str, Any]) -> str:
    host, git = report.get("host") or {}, report.get("git") or {}
    lines = [
        f"# Soak {report.get('scenario')} — {report.get('verdict')}",
        "",
        f"- Démarré : {report.get('started_utc')} (mode {report.get('mode')})",
        f"- Hôte : {host.get('hostname')} ({host.get('machine')}, Python {host.get('python')})",
        f"- Git : {git.get('head')} (modifié : {git.get('dirty')})",
        f"- Vitesse : cible {_fmt(report.get('speed_target'))}×, atteinte "
        f"{_fmt(report.get('speed_achieved'))}× ; {_fmt(report.get('sim_s'))} s simulées en "
        f"{_fmt(report.get('wall_s'))} s réelles",
    ]
    shim = report.get("shim") or {}
    if shim.get("overrides"):
        lines.append(f"- Shim : {shim['overrides']} (raison : {shim.get('why')})")
    sysd = report.get("systemd") or {}
    if sysd:
        lines.append(
            f"- systemd : portée {sysd.get('scope')}, unités {sysd.get('units')}, NRestarts "
            f"{sysd.get('n_restarts')}, chiens de garde {sysd.get('watchdog_kills')}"
        )
        cl = sysd.get("cleanup") or {}
        if cl.get("scope") == "system":
            lines.append(
                f"- Nettoyage : drop-ins retirés {len(cl.get('removed') or [])}, démontés "
                f"{len(cl.get('unmounted') or [])}, lignes 50-jabuka-soak restantes "
                f"{cl.get('soak_lines_left')} (attendu 0)"
            )
    pi = report.get("pi") or {}
    if pi:
        lines.append(
            f"- Raspberry Pi : température max {_fmt(pi.get('temp_c_max'))} °C, throttling vu "
            f"{pi.get('throttled_bits_seen')} {pi.get('throttled_flags_seen') or ''}"
        )
    if report.get("fail_reasons"):
        lines += ["", "## Échecs", ""] + [f"- {r}" for r in report["fail_reasons"]]
    lines += [
        "",
        "## Mesures et budgets",
        "",
        "| mesure | mesuré | budget | ok |",
        "|---|---|---|---|",
    ]
    for row in budget_rows(report):
        ok = {True: "oui", False: "NON", None: "—"}[row["ok"]]
        measured = str(row["measured"]).replace("|", "/").replace("\n", " ")
        lines.append(f"| {row['item']} | {measured} | {row['budget']} | {ok} |")
    lines += [
        "",
        "## Chronologie des pannes",
        "",
        "| id | panne | t sim (s) | début (s) | fin (s) | rétabli (s) | budget (s) | ok | notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    t0 = report.get("t0_wall") or 0.0
    for f in report.get("faults", []):

        def rel(x: Any) -> str:
            return _fmt(None if x is None else x - t0)

        lines.append(
            f"| {f.get('id')} | {f.get('kind')} | {_fmt(f.get('t_sim'))} | {rel(f.get('t_wall'))} "
            f"| {rel(f.get('cleared_wall'))} | {_fmt(f.get('recovery_s'))} "
            f"| {_fmt(f.get('budget_s'))} | {'oui' if f.get('ok') else 'NON'} "
            f"| {(f.get('notes') or '').replace('|', '/')} |"
        )
    if report.get("skipped"):
        lines += ["", "## Pannes non jouées (SKIPPED)", ""]
        lines += [f"- {s['kind']} : {s['reason']}" for s in report["skipped"]]
    lines += [
        "",
        "## Contrôles",
        "",
        "| contrôle | ok | valeur | budget | détail |",
        "|---|---|---|---|---|",
    ]
    for name, c in report.get("checks", {}).items():
        ok = {True: "oui", False: "NON", None: "—"}[c.get("ok")]
        detail = str(c.get("detail") or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {name} | {ok} | {_fmt(c.get('value'))} | {_fmt(c.get('budget'))} | {detail} |"
        )
    if report.get("findings"):
        lines += ["", "## Constats", ""] + [f"- {x}" for x in report["findings"]]
    lines += [
        "",
        "Fichiers : report.json, samples.csv (mémoire/fd/threads/CPU par seconde), timeline.jsonl,"
        " proc/*.log (sorties horodatées des processus).",
        "",
    ]
    return "\n".join(lines)


def open_append(path: Path) -> Any:
    """A text file of the run dir opened for appending (timeline.jsonl, proc/synth.log). The
    harness's own files live here: jabuka.tools is scanned by the receive-only write guard."""
    return open(path, "a", encoding="utf-8")  # noqa: SIM115 - the caller closes it


def write_report(run_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    run_dir = Path(run_dir)
    jpath, mpath = run_dir / "report.json", run_dir / "report.md"
    jpath.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    mpath.write_text(render_md(report), encoding="utf-8")
    return jpath, mpath
