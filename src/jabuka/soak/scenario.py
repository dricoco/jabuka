"""Soak scenarios: seeded, versioned JSON fault schedules (plan 04-01 <interfaces>).

A scenario is a JSON object::

    {"name", "seed", "clock": "sim"|"gps", "speed", "duration_s" (sim), "start": [lat, lon],
     "start_utc": ISO | "now", "wind": {"twd", "tws_kn", "shift_deg_h", "gust_kn"},
     "grib": {"tws_factor", "hours_before", "hours_after"}, "course": "A"|"B", "settings": {...},
     "logs_fs": "auto"|"tmpfs:SIZE"|"none", "budgets": {...}, "shim": {...},
     "faults": [{"kind", "at" (sim s), "dur" (sim s, windowed kinds), ...params}],
     "random": {"count", "kinds", "min_gap_s", "until_s"} | null, "quiet_tail_s",
     "expected_tracebacks": {KIND: [{"pattern": regex, "why": str}]}}

Packaged scenarios live next to this module (``scenarios/NAME.json``) and load by name; a path is
accepted too. ``compile_timeline`` turns the fixed and the seeded random faults into one ordered
list, identical for the same seed.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

# Every fault kind the harness knows (CONTEXT §Soak harness + two discretion additions). A kind the
# running harness cannot do is reported SKIPPED with a reason, never silently dropped.
FAULT_KINDS: tuple[str, ...] = (
    # process level (Task 2)
    "kill-core",
    "kill-ingest",
    "kill-worker",
    "sigterm-storm",
    "power-pull",
    "watchdog-hang",
    # synth driven (--control)
    "bus-silent",
    "garbage",
    "noise",
    "unplug",
    "gps-loss",
    "clock-jump",
    # harness driven
    "disk-full",
    "grib-gap",
    "course-change",
    "stay-toggle",
    "ws-stall",
    "ws-churn",
)
# kinds with a duration window ("dur", sim seconds)
WINDOWED: frozenset[str] = frozenset(
    {
        "bus-silent",
        "garbage",
        "noise",
        "unplug",
        "gps-loss",
        "clock-jump",
        "disk-full",
        "grib-gap",
        "stay-toggle",
        "ws-stall",
    }
)
# kinds that restart a process (excluded from the quiet tail: the leak fit needs one long segment)
RESTARTING: frozenset[str] = frozenset(
    {
        "kill-core",
        "kill-ingest",
        "kill-worker",
        "sigterm-storm",
        "power-pull",
        "watchdog-hang",
        "grib-gap",
    }
)
CORRUPTIONS: tuple[str, ...] = ("truncate_half", "garbage", "drop_main", "stray_tmp")
CORRUPT_TARGETS: dict[str, str] = {
    "truncate_half": "course.json",
    "garbage": "settings.json",
    "drop_main": "route.json",
    "stray_tmp": "course.json",
}

DEFAULT_BUDGETS: dict[str, float] = {
    "bus": 10.0,  # wall s: live wind again after a bus fault clears
    "gps": 10.0,  # wall s: live position again after a GPS fault clears
    "process": 30.0,  # wall s: live data again after a process restart
    "power": 60.0,  # wall s: live data again after a power pull
    "route": 60.0,  # wall s: a new route adopted after a restart
    "bus_fallback": 15.0,  # wall s: GRIB wind shown once the bus is silent (WIND-05)
    "disk_resume": 30.0,  # wall s: the derived log grows again once space is freed
    "rss_core_mb": 250.0,
    "rss_worker_mb": 250.0,
    "leak_mb_36h": 20.0,  # RSS slope over the longest restart-free segment
    "min_segment_s": 10800.0,  # sim s: shorter segments are "insufficient data" for the fit
    "warmup_s": 1800.0,  # sim s skipped at the start of a segment before the fit
    "fd_growth": 8.0,
    "thread_growth": 4.0,
    "cpu_per_sim_s": 0.10,  # CPU s per sim s (10 % of a core at real time)
    "tick_ratio": 0.95,  # diag messages per sim second
    "ws_stall_rss_mb": 20.0,
    "settle_s": 2.0,  # wall s between a confirmed recovery and the next fault
    "margin_s": 5.0,  # wall s after a recovery still inside the fault window (tracebacks)
}

LOGS_FS_MAX_BYTES = 512 * 1024 * 1024
LOOP_FS_MAX_BYTES = 1024 * 1024 * 1024
_SIZE = re.compile(r"^(\d+)([KMG]?)$")


def parse_size(text: str) -> int:
    """'64M' -> bytes (K, M, G binary multiples)."""
    m = _SIZE.match(text.strip().upper())
    if not m:
        raise ValueError(f"bad size {text!r} (expected e.g. 64M)")
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2)]
    return int(m.group(1)) * mult


def parse_logs_fs(text: str) -> tuple[str, int | None]:
    """'auto' | 'none' | 'tmpfs:SIZE' | 'loop:SIZE' -> (mode, bytes). The tmpfs is capped at
    512M; loop (an ext4 image in the soak dir, --systemd system only) at 1G (T-04-03-04)."""
    if text in ("auto", "none"):
        return text, None
    kind, _, size = text.partition(":")
    if kind not in ("tmpfs", "loop") or not size:
        raise ValueError(f"logs_fs must be auto, none, tmpfs:SIZE or loop:SIZE, got {text!r}")
    n = parse_size(size)
    cap, cap_s = (LOGS_FS_MAX_BYTES, "512M") if kind == "tmpfs" else (LOOP_FS_MAX_BYTES, "1G")
    if not 0 < n <= cap:
        raise ValueError(f"logs_fs {kind} size {size} out of range (max {cap_s})")
    return kind, n


@dataclass(frozen=True)
class FaultSpec:
    """One scheduled fault: ``at`` and ``dur`` in sim seconds (dur 0 for instant kinds)."""

    id: str
    kind: str
    at: float
    dur: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    random: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "at": self.at,
            "dur": self.dur,
            "params": dict(self.params),
            "random": self.random,
        }


@dataclass
class Scenario:
    name: str
    seed: int
    clock: str
    speed: float
    duration_s: float
    start: tuple[float, float]
    start_utc: str
    wind: dict[str, float]
    grib: dict[str, float]
    course: str
    settings: dict[str, Any]
    logs_fs: str
    budgets: dict[str, float]
    shim: dict[str, float]
    faults: list[dict[str, Any]]
    random: dict[str, Any] | None
    quiet_tail_s: float
    expected_tracebacks: dict[str, list[dict[str, str]]]
    source: str = "<dict>"

    def budget(self, key: str) -> float:
        return float(self.budgets.get(key, DEFAULT_BUDGETS[key]))


def _num(doc: dict, key: str, default: Any = None, *, positive: bool = False) -> float:
    v = doc.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise ValueError(f"{key!r} must be a number, got {v!r}")
    if positive and v <= 0:
        raise ValueError(f"{key!r} must be > 0, got {v!r}")
    return float(v)


def _check_fault(i: int, f: Any) -> dict[str, Any]:
    if not isinstance(f, dict):
        raise ValueError(f"faults[{i}] must be an object")
    kind = f.get("kind")
    if kind not in FAULT_KINDS:
        raise ValueError(
            f"faults[{i}]: unknown fault kind {kind!r} (known: {', '.join(FAULT_KINDS)})"
        )
    if "at" not in f:
        raise ValueError(f"faults[{i}] ({kind}): missing required key 'at'")
    at = _num(f, "at")
    if at < 0:
        raise ValueError(f"faults[{i}] ({kind}): 'at' must be >= 0")
    if kind in WINDOWED:
        if "dur" not in f:
            raise ValueError(f"faults[{i}] ({kind}): missing required key 'dur'")
        _num(f, "dur", positive=True)
    corrupt = f.get("corrupt")
    if corrupt is not None and corrupt != "random" and corrupt not in CORRUPTIONS:
        raise ValueError(f"faults[{i}] ({kind}): unknown corruption {corrupt!r}")
    return dict(f)


def parse_scenario(doc: Any, source: str = "<dict>") -> Scenario:
    """Validate a scenario document. Raises ValueError naming the offending key or kind."""
    if not isinstance(doc, dict):
        raise ValueError(f"{source}: a scenario must be a JSON object")
    for key in ("name", "speed", "duration_s", "faults"):
        if key not in doc:
            raise ValueError(f"{source}: missing required key {key!r}")
    name = doc["name"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise ValueError(f"{source}: bad name {name!r}")
    clock = doc.get("clock", "sim")
    if clock not in ("sim", "gps"):
        raise ValueError(f"{source}: clock must be sim or gps, got {clock!r}")
    start = doc.get("start", [43.70, 15.80])
    if (
        not isinstance(start, list | tuple)
        or len(start) != 2
        or not all(isinstance(x, int | float) and not isinstance(x, bool) for x in start)
    ):
        raise ValueError(f"{source}: start must be [lat, lon]")
    faults = doc["faults"]
    if not isinstance(faults, list):
        raise ValueError(f"{source}: faults must be a list")
    rnd = doc.get("random")
    if rnd is not None:
        if not isinstance(rnd, dict):
            raise ValueError(f"{source}: random must be an object or null")
        for key in ("count", "kinds", "min_gap_s", "until_s"):
            if key not in rnd:
                raise ValueError(f"{source}: random: missing required key {key!r}")
        for k in rnd["kinds"]:
            if k not in FAULT_KINDS:
                raise ValueError(f"{source}: random: unknown fault kind {k!r}")
    budgets = doc.get("budgets", {})
    if not isinstance(budgets, dict):
        raise ValueError(f"{source}: budgets must be an object")
    for k in budgets:
        if k not in DEFAULT_BUDGETS:
            raise ValueError(f"{source}: unknown budget {k!r}")
        _num(budgets, k)
    shim = doc.get("shim", {})
    if not isinstance(shim, dict) or not set(shim) <= {"watchdog_sec", "restart_sec", "why"}:
        raise ValueError(f"{source}: shim accepts watchdog_sec, restart_sec and why only")
    if (set(shim) - {"why"}) and not shim.get("why"):
        raise ValueError(f"{source}: a shim override needs a 'why' (it is shown in the report)")
    exp = doc.get("expected_tracebacks", {})
    if not isinstance(exp, dict):
        raise ValueError(f"{source}: expected_tracebacks must be an object")
    for kind, rules in exp.items():
        if kind not in FAULT_KINDS:
            raise ValueError(f"{source}: expected_tracebacks: unknown fault kind {kind!r}")
        for r in rules:
            if not isinstance(r, dict) or not r.get("pattern") or not r.get("why"):
                raise ValueError(
                    f"{source}: expected_tracebacks[{kind}]: each entry needs pattern and why"
                )
            re.compile(r["pattern"])
    logs_fs = doc.get("logs_fs", "auto")
    parse_logs_fs(logs_fs)
    course = doc.get("course", "A")
    if course not in ("A", "B"):
        raise ValueError(f"{source}: course must be A or B")
    start_utc = doc.get("start_utc", "2026-11-13T19:00:00Z")
    if not isinstance(start_utc, str):
        raise ValueError(f"{source}: start_utc must be an ISO string or 'now'")
    return Scenario(
        name=name,
        seed=int(doc.get("seed", 0)),
        clock=clock,
        speed=_num(doc, "speed", positive=True),
        duration_s=_num(doc, "duration_s", positive=True),
        start=(float(start[0]), float(start[1])),
        start_utc=start_utc,
        wind={"twd": 161.0, "tws_kn": 12.0, "shift_deg_h": 0.0, "gust_kn": 0.0}
        | dict(doc.get("wind", {})),
        grib={"tws_factor": 1.0, "hours_before": 2.0, "hours_after": 48.0}
        | dict(doc.get("grib", {})),
        course=course,
        settings=dict(doc.get("settings", {})),
        logs_fs=logs_fs,
        budgets={k: float(v) for k, v in budgets.items()},
        shim=dict(shim),
        faults=[_check_fault(i, f) for i, f in enumerate(faults)],
        random=dict(rnd) if rnd is not None else None,
        quiet_tail_s=float(doc.get("quiet_tail_s", 0.0)),
        expected_tracebacks={k: list(v) for k, v in exp.items()},
        source=source,
    )


def scenario_dir() -> Any:
    return resources.files("jabuka.soak") / "scenarios"


def list_scenarios() -> list[str]:
    return sorted(
        p.name[: -len(".json")] for p in scenario_dir().iterdir() if p.name.endswith(".json")
    )


def load_scenario(name_or_path: str | Path) -> Scenario:
    """A packaged scenario by name ("ci"), or a JSON file path."""
    text = str(name_or_path)
    path = Path(text)
    if text.endswith(".json") or "/" in text:
        if not path.is_file():
            raise ValueError(f"scenario file not found: {text}")
        return parse_scenario(json.loads(path.read_text(encoding="utf-8")), str(path))
    res = scenario_dir() / f"{text}.json"
    if not res.is_file():
        raise ValueError(f"unknown scenario {text!r} (packaged: {', '.join(list_scenarios())})")
    return parse_scenario(json.loads(res.read_text(encoding="utf-8")), f"scenarios/{text}.json")


def compile_timeline(sc: Scenario, seed: int | None = None) -> list[FaultSpec]:
    """Fixed faults plus the seeded random draws, ordered by time. Deterministic for a seed.

    Random faults are drawn in [0, until_s], at least min_gap_s (sim) from every other random
    fault and min(min_gap_s / 4, 300 s) from a fixed one; a draw that cannot be placed after 200
    tries is dropped (the report's timeline shows what was placed). Kinds that restart a process
    are never drawn inside the quiet tail."""
    rng = random.Random(sc.seed if seed is None else seed)
    items: list[tuple[float, int, dict[str, Any], bool]] = []
    for i, f in enumerate(sc.faults):
        items.append((float(f["at"]), i, f, False))
    if sc.random:
        r = sc.random
        kinds = list(r["kinds"])
        gap = float(r["min_gap_s"])
        guard = min(gap / 4.0, 300.0)
        until = float(r["until_s"])
        tail0 = sc.duration_s - sc.quiet_tail_s if sc.quiet_tail_s > 0 else math.inf
        fixed = [float(f["at"]) for f in sc.faults]
        drawn: list[float] = []
        for j in range(int(r["count"])):
            kind = kinds[rng.randrange(len(kinds))]
            for _try in range(200):
                at = round(rng.uniform(0.0, until), 1)
                if kind in RESTARTING and at >= tail0:
                    continue
                if all(abs(at - t) >= gap for t in drawn) and all(
                    abs(at - t) >= guard for t in fixed
                ):
                    break
            else:
                continue
            drawn.append(at)
            doc: dict[str, Any] = {"kind": kind, "at": at}
            if kind in WINDOWED:
                doc["dur"] = float(r.get("dur_s", {}).get(kind, 120.0))
            if kind == "power-pull":
                doc["off_s"] = float(r.get("off_s", 60.0))
                doc["corrupt"] = "random" if rng.random() < 0.5 else None
            items.append((at, len(sc.faults) + j, doc, True))
    items.sort(key=lambda x: (x[0], x[1]))
    out: list[FaultSpec] = []
    for n, (at, _i, doc, is_random) in enumerate(items, start=1):
        params = {k: v for k, v in doc.items() if k not in ("kind", "at", "dur")}
        if params.get("corrupt") == "random":
            params["corrupt"] = CORRUPTIONS[rng.randrange(len(CORRUPTIONS))]
        out.append(
            FaultSpec(
                id=f"f{n:02d}",
                kind=doc["kind"],
                at=at,
                dur=float(doc.get("dur", 0.0)),
                params=params,
                random=is_random,
            )
        )
    return out
