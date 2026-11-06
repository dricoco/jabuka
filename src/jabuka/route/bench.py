"""Pi benchmark gate (2026-11-09): routing cycle time per degraded level, worker RSS and
event-loop jitter while routing (CONTEXT §Router, RESEARCH "Benchmark & Pi Extrapolation").

    PYTHONPATH=src python -m jabuka.route.bench --fixture            # committed fixture pack
    PYTHONPATH=src python -m jabuka.route.bench --pack var/racepack  # real race pack
    options: --levels L0,...,L5  --runs 3  --start ISO  --quick  --json OUT  --inprocess

numpy + stdlib + jabuka.route only (runs in a Pi venv holding only numpy). Each cycle is the
real worker job (``cycle.run_cycle``: optimal whole course + forced current leg) for Courses A
and B from Vodice, run through the forkserver ``RouterPool`` while an asyncio ticker on this
loop records its lateness every 100 ms. PASS rule: the first level whose p95 cycle time is
<= 30 s with a loop jitter <= 200 ms is the recommended ``route_level``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from jabuka.route import cycle
from jabuka.route.frame import NM_M
from jabuka.route.landmask import LandMask, compute_geofield, save_geofields
from jabuka.route.polar_grid import curves_from_json
from jabuka.route.pool import RouterPool
from jabuka.route.racepack import load_pack, read_marks_file
from jabuka.route.types import LEVELS, CourseMark, CycleRequest, RouteRequest

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures"
GATE_P95_S = 30.0
GATE_JITTER_MS = 200.0
TICK_S = 0.1
DEFAULT_EFF = 0.92  # Phase 2 default polar efficiency
COURSES = ("A", "B")


# --------------------------------------------------------------------------- helpers
def parse_levels(text: str) -> list[str]:
    out = [p.strip().upper() for p in text.split(",") if p.strip()]
    bad = [p for p in out if p not in LEVELS]
    if bad or not out:
        print(f"niveaux inconnus : {', '.join(bad) or text!r} (L0..L5)", file=sys.stderr)
        raise SystemExit(2)
    return out


def percentile(values: list[float], q: float) -> float:
    v = sorted(values)
    if not v:
        return math.nan
    pos = (len(v) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def duty(level: str, opt_s: list[float], forced_s: list[float]) -> float | None:
    """Average busy fraction of the worker per cadence (L4/L5 only): (optimal + forced /
    forced_every_n) / cadence."""
    if level not in ("L4", "L5") or not opt_s:
        return None
    s = LEVELS[level]
    f = statistics.fmean(forced_s) if forced_s else 0.0
    return (statistics.fmean(opt_s) + f / s.forced_every_n) / s.cadence_s


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return None


def platform_info() -> dict[str, Any]:
    keys: dict[str, str] = {}
    for line in (_read("/proc/cpuinfo") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            keys.setdefault(k.strip(), v.strip())  # case-sensitive: Pi "Model" = the board
    cpu = keys.get("model name") or keys.get("Hardware") or platform.processor()
    cpu = cpu or platform.machine()
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    throttled = None
    vc = shutil.which("vcgencmd")
    if vc:
        try:
            throttled = subprocess.run(
                [vc, "get_throttled"], capture_output=True, text=True, timeout=2, check=False
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            throttled = None
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "machine": platform.machine(),
        "cpu": cpu,
        "board": keys.get("Model"),
        "cpus": os.cpu_count(),
        "cpu_temp_c": round(int(temp) / 1000.0, 1) if temp and temp.isdigit() else None,
        "throttled": throttled,
    }


# --------------------------------------------------------------------------- pack
def default_marks() -> Path:
    for p in (
        FIXTURES / "route" / "marks.json",
        REPO / "src" / "jabuka" / "nav" / "data" / "marks.json",
    ):
        if p.is_file():
            return p
    raise SystemExit("marks.json introuvable : --marks FICHIER")


def assemble_fixture_pack(
    dest: str | Path, with_geofields: bool = True, marks_path: str | Path | None = None
) -> Path:
    """Race pack from the committed fixtures: real ICON-EU/EWAM samples (24 h), the 25 m land
    mask, the X35 polar and (optionally) 200 m geofields for the marks."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rp = FIXTURES / "racepack"
    rt = FIXTURES / "route"
    pairs = [
        (rp / "wind_icon_eu_sample", "wind"),
        (rp / "waves_ewam_sample", "waves"),
        (rt / "landmask_race_25m", "landmask"),
    ]
    for src, stem in pairs:
        if not src.with_suffix(".npz").is_file():
            raise SystemExit(f"fixture absente : {src.with_suffix('.npz')}")
        shutil.copy(src.with_suffix(".npz"), dest / f"{stem}.npz")
        shutil.copy(src.with_suffix(".json"), dest / f"{stem}.json")
    shutil.copy(rt / "x35_polar.json", dest / "polar.json")
    if with_geofields:
        mask = LandMask.load(dest / "landmask.npz")
        doc = read_marks_file(marks_path or default_marks())
        g = 200.0 / NM_M
        fields = {}
        for m in doc.marks.values():
            x, y = mask.frame.to_xy(m.lat, m.lon)
            fields[(m.lat, m.lon, m.radius_nm)] = compute_geofield(
                mask, [(x, y)], g, "centre", seed_radius_nm=m.radius_nm + g
            )
        save_geofields(dest / "geofields.npz", fields)
    return dest


def build_requests(
    pack_dir: Path, marks_path: Path, polar_path: Path, start: float | None, eff: float
):
    """One base RouteRequest per course (from the start mark, tack +1) for every level."""
    doc = read_marks_file(marks_path)
    curves = curves_from_json(json.loads(polar_path.read_text(encoding="utf-8")))
    pack = load_pack(pack_dir)
    if pack.wind is None:
        raise SystemExit(f"pack sans vent : {'; '.join(pack.errors)}")
    t0 = start if start is not None else float(pack.wind.t[0]) + 3600.0
    out = {}
    for key in COURSES:
        if key not in doc.templates:
            continue
        cms = []
        for mid, side in doc.templates[key]:
            m = doc.marks[mid]
            cms.append(CourseMark(m.id, m.name, m.lat, m.lon, side, m.radius_nm))
        start_mark, marks = cms[0], tuple(cms[1:])
        out[key] = RouteRequest(
            request_id=f"bench-{key}",
            t0=t0,
            lat=start_mark.lat,
            lon=start_mark.lon,
            tack0=1,
            prev_mark=start_mark,
            marks=marks,
            polar_curves=curves,
            eff=eff,
            eff_up=None,
            eff_down=None,
            bias=None,
            settings=LEVELS["L0"],
        )
    if not out:
        raise SystemExit("aucun parcours A/B dans les marques")
    return out, t0


# --------------------------------------------------------------------------- run
class _Ticker:
    """Lateness of a 100 ms asyncio ticker (the core's 1 Hz loop proxy)."""

    def __init__(self) -> None:
        self.max_ms = 0.0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        nxt = loop.time() + TICK_S
        while True:
            await asyncio.sleep(max(0.0, nxt - loop.time()))
            late = loop.time() - nxt
            self.max_ms = max(self.max_ms, late * 1000.0)
            nxt += TICK_S
            if late > TICK_S:
                nxt = loop.time() + TICK_S

    def start(self) -> None:
        self.max_ms = 0.0
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> float:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return self.max_ms


def _summary(level: str, cycles: list[dict]) -> dict[str, Any]:
    secs = [c["cycle_s"] for c in cycles]
    opt = [c["optimal_ms"] / 1000.0 for c in cycles if c.get("optimal_ms") is not None]
    frc = [c["forced_ms"] / 1000.0 for c in cycles if c.get("forced_ms") is not None]
    etas = [c["eta_h"] for c in cycles if c.get("eta_h") is not None]
    return {
        "runs": len(cycles),
        "p50_s": round(percentile(secs, 50), 3),
        "p95_s": round(percentile(secs, 95), 3),
        "max_s": round(max(secs), 3),
        "optimal_ms_p50": round(percentile([o * 1000 for o in opt], 50), 1) if opt else None,
        "forced_ms_p50": round(percentile([f * 1000 for f in frc], 50), 1) if frc else None,
        "rss_kb": max((c.get("rss_kb") or 0) for c in cycles),
        "steps": max((c.get("steps") or 0) for c in cycles),
        "eta_h": round(statistics.fmean(etas), 2) if etas else None,
        "failures": [c["reason"] for c in cycles if not c["ok"]],
        "duty": duty(level, opt, frc),
    }


def _cycle_row(res, cycle_s: float, req: RouteRequest) -> dict[str, Any]:
    opt = res.optimal
    w = res.worker or {}
    return {
        "cycle_s": cycle_s,
        "ok": bool(opt.ok),
        "reason": opt.reason,
        "optimal_ms": w.get("optimal_ms"),
        "forced_ms": w.get("forced_ms"),
        "rss_kb": w.get("rss_kb"),
        "steps": w.get("steps"),
        "eta_h": (opt.eta - req.t0) / 3600.0 if opt.ok and opt.eta else None,
        "cost_s": res.cost_s,
    }


async def run_levels(pack_dir: Path, reqs: dict, levels: list[str], runs: int, inprocess: bool):
    import dataclasses

    results: dict[str, Any] = {}
    ticker = _Ticker()
    env = None
    pool = None
    if inprocess:
        env = cycle.build_env(pack_dir)
    else:
        pool = RouterPool(cycle.init_worker, (str(pack_dir),), timeout_s=120.0)
    loop = asyncio.get_running_loop()

    async def one(creq: CycleRequest):
        t = loop.time()
        if inprocess:
            res = cycle.cycle_with_env(env, creq)
        else:
            out = await pool.run_latest(cycle.run_cycle, creq)
            if out.status != "ok":
                raise RuntimeError(f"cycle {out.status}: {out.error}")
            res = out.value
        return res, loop.time() - t

    try:
        first = next(iter(reqs.values()))
        warm, _ = await one(CycleRequest(first))  # worker start + pack load, not measured
        if not warm.optimal.ok:
            raise SystemExit(f"routage impossible : {warm.optimal.reason}")
        for level in levels:
            settings = LEVELS[level]
            ticker.start()
            rows = []
            k = 0
            for _run in range(runs):
                for _key, base in reqs.items():
                    req = dataclasses.replace(base, settings=settings)
                    want = k % settings.forced_every_n == 0
                    k += 1
                    res, secs = await one(CycleRequest(req, want_forced=want))
                    rows.append(_cycle_row(res, secs, req))
            jitter = await ticker.stop()
            summary = _summary(level, rows)
            summary["jitter_ms"] = None if inprocess else round(jitter, 1)
            summary["pass"] = bool(
                not summary["failures"]
                and summary["p95_s"] <= GATE_P95_S
                and (inprocess or jitter <= GATE_JITTER_MS)
            )
            summary["cycles"] = rows
            results[level] = summary
    finally:
        if pool is not None:
            pool.close()
    return results


def format_table(results: dict[str, Any]) -> str:
    head = (
        "Niveau  p50 s  p95 s  max s  optimal ms  forcé ms  RSS Mo  étapes  ETA h  gigue ms"
        "  charge  OK"
    )
    lines = [head]
    for level, r in results.items():
        duty_txt = f"{r['duty']:.2%}" if r.get("duty") is not None else "-"
        jit = f"{r['jitter_ms']:.0f}" if r.get("jitter_ms") is not None else "-"
        lines.append(
            f"{level:6s} {r['p50_s']:6.2f} {r['p95_s']:6.2f} {r['max_s']:6.2f}"
            f" {r['optimal_ms_p50'] or 0:10.0f} {r['forced_ms_p50'] or 0:9.0f}"
            f" {r['rss_kb'] / 1024:7.0f} {r['steps']:7d} {r['eta_h'] or 0:6.2f} {jit:>8s}"
            f" {duty_txt:>7s}  {'oui' if r['pass'] else 'NON'}"
        )
        for why in r["failures"][:3]:
            lines.append(f"       échec : {why}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="jabuka-route-bench", description="Banc d'essai du routage (porte Pi du 2026-11-09)"
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--pack", default=None, help="pack de course (wind.npz, landmask.npz, ...)")
    src.add_argument("--fixture", action="store_true", help="pack des fixtures du dépôt")
    ap.add_argument("--marks", default=None, help="marks.json (défaut : fixture / jabuka.nav)")
    ap.add_argument("--polar", default=None, help="polaire JSON (défaut : polar.json du pack)")
    ap.add_argument("--levels", default="L0,L1,L2,L3,L4,L5")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--start", default=None, help="départ ISO UTC (défaut : 1re échéance + 1 h)")
    ap.add_argument("--eff", type=float, default=DEFAULT_EFF, help="efficacité polaire")
    ap.add_argument("--quick", action="store_true", help="1 passage, L0 et L1, pack fixture")
    ap.add_argument("--json", default=None, help="écrire les résultats en JSON")
    ap.add_argument("--inprocess", action="store_true", help="sans pool (pas de mesure de gigue)")
    args = ap.parse_args(argv)
    levels = parse_levels(args.levels)
    runs = max(1, int(args.runs))
    if args.quick:
        levels, runs = ["L0", "L1"], 1
        if args.pack is None:
            args.fixture = True
    if args.pack is None and not args.fixture:
        ap.error("--pack DIR ou --fixture requis")
    start = None
    if args.start:
        dt = datetime.fromisoformat(args.start)
        start = (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()
    tmp = None
    try:
        if args.fixture:
            tmp = tempfile.mkdtemp(prefix="jabuka-bench-")
            t = time.perf_counter()
            pack_dir = assemble_fixture_pack(tmp, True, args.marks)
            print(f"Pack fixture assemblé dans {pack_dir} ({time.perf_counter() - t:.1f} s)")
        else:
            pack_dir = Path(args.pack)
        marks = Path(args.marks) if args.marks else default_marks()
        polar = Path(args.polar) if args.polar else pack_dir / "polar.json"
        if not polar.is_file():
            polar = FIXTURES / "route" / "x35_polar.json"
        reqs, t0 = build_requests(pack_dir, marks, polar, start, args.eff)
        plat = platform_info()
        print(
            f"Python {plat['python']}, numpy {plat['numpy']}, {plat['cpu']} ({plat['machine']})"
            + (f", {plat['cpu_temp_c']} °C" if plat["cpu_temp_c"] is not None else "")
        )
        print(
            f"Parcours {', '.join(reqs)} depuis {next(iter(reqs.values())).marks[-1].name}, "
            f"départ {datetime.fromtimestamp(t0, UTC):%Y-%m-%d %H:%MZ}, {runs} passage(s), "
            f"niveaux {', '.join(levels)}"
        )
        results = asyncio.run(run_levels(pack_dir, reqs, levels, runs, args.inprocess))
        plat_end = platform_info()
        recommended = next((lv for lv, r in results.items() if r["pass"]), None)
        print(format_table(results))
        print(
            f"Règle : p95 <= {GATE_P95_S:g} s et gigue <= {GATE_JITTER_MS:g} ms."
            f" NIVEAU RECOMMANDÉ : {recommended or 'AUCUN (routage désactivé, laylines Phase 2)'}"
        )
        if args.json:
            doc = {
                "platform": plat,
                "platform_end": {
                    "cpu_temp_c": plat_end["cpu_temp_c"],
                    "throttled": plat_end["throttled"],
                },
                "pack": str(args.pack or "fixture"),
                "start_utc": t0,
                "courses": list(reqs),
                "runs": runs,
                "gate": {"p95_s": GATE_P95_S, "jitter_ms": GATE_JITTER_MS},
                "levels": results,
                "recommended": recommended,
            }
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Résultats : {out}")
        return 0 if recommended else 1
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
