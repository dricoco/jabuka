"""Routing worker entry points (CONTEXT §Router, §Tack advice; RESEARCH Patterns 7 and 9).

``init_worker(pack_dir)`` runs once per worker process (RouterPool initializer, nice +10): it
loads the race pack, the land mask, the precomputed geofields and the weather fields into module
globals. It never raises: an init problem is kept as a French string and every later
``run_cycle`` returns ``ok False`` with it, so a bad pack cannot crash-loop the pool.

``run_cycle(CycleRequest)`` = ONE snapshot -> both routings (never two jobs, the cost would be
inconsistent):
- optimal: the whole remaining course from the request;
- forced (when wanted and the optimal route changes side): the current leg only, held on the
  boat's tack until max(t0, first side change) + stay_extra_s ("On reste"), released when the
  held tack runs into land;
- cost of not tacking = max(0, forced leg ETA - optimal leg ETA);
- the old route re-evaluated under the new wind (hysteresis input) when given.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path
from typing import Any

from jabuka.route.evaluate import evaluate_path
from jabuka.route.fields import fields_from_pack
from jabuka.route.isochrone import RouterEnv, route
from jabuka.route.landmask import LandMask, load_geofields
from jabuka.route.racepack import RacePack, load_pack, verify_landmask
from jabuka.route.types import FAIL_ENGINE, FAIL_PACK, CycleRequest, CycleResult, RouteResult

_ENV: RouterEnv | None = None
_INIT_ERROR: str | None = None
_INIT_NOTES: list[str] = []
_PACK_DIR: str | None = None
_PACK_FP: tuple | None = None  # pack fingerprint this worker loaded (MD-05)

# The core loaded another pack than this worker (replaced on disk without a core restart).
PACK_CHANGED = "pack de course modifié depuis le démarrage du cœur"


def rss_kb() -> int:
    """Resident set size of this process (kB), from /proc (Linux), else the peak RSS."""
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    try:
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:  # noqa: BLE001 - diagnostics only
        return 0


def build_env(pack_dir: str | Path, notes: list[str] | None = None) -> RouterEnv:
    """RouterEnv from a race-pack directory (in-process use: tests, bench --inprocess).
    ValueError with a French reason when the pack cannot route."""
    return _build(pack_dir, notes)[0]


def _build(pack_dir: str | Path, notes: list[str] | None = None) -> tuple[RouterEnv, RacePack]:
    pack_dir = Path(pack_dir)
    pack = load_pack(pack_dir)
    if pack.wind is None:
        why = "; ".join(e for e in pack.errors if e.startswith("wind")) or "wind.npz absent"
        raise ValueError(f"pack {pack_dir} sans vent utilisable ({why})")
    if pack.landmask_path is None:
        raise ValueError(f"landmask.npz absent du pack {pack_dir}")
    verify_landmask(pack.landmask_path)  # MD-05: never route on an altered land mask
    mask = LandMask.load(pack.landmask_path)
    geofields = {}
    if pack.geofields_path is not None:
        try:
            geofields = load_geofields(pack.geofields_path)
        except ValueError as exc:
            if notes is not None:
                notes.append(f"geofields ignorés ({exc}) : champs calculés à la demande")
    for err in pack.errors:
        if notes is not None:
            notes.append(err)
    fields = fields_from_pack(pack, mask.frame)
    return RouterEnv(mask, fields, geofields=geofields), pack


def init_worker(pack_dir: str) -> None:
    """Worker initializer: load everything once; never raises (errors kept as strings)."""
    global _ENV, _INIT_ERROR, _INIT_NOTES, _PACK_DIR, _PACK_FP
    _ENV, _INIT_ERROR, _INIT_NOTES, _PACK_DIR, _PACK_FP = None, None, [], str(pack_dir), None
    try:
        _ENV, pack = _build(pack_dir, _INIT_NOTES)
        _PACK_FP = pack.fingerprint
    except Exception as exc:  # noqa: BLE001 - any init failure becomes a reason string
        _INIT_ERROR = f"routeur non initialisé : {exc}"


def _failed(req, reason: str, kind: str = FAIL_ENGINE) -> RouteResult:
    return RouteResult(
        ok=False,
        reason=reason,
        request_id=req.request_id,
        t0=req.t0,
        level=req.settings.level,
        fail_kind=kind,
    )


def cycle_with_env(env: RouterEnv, creq: CycleRequest) -> CycleResult:
    """One cycle on an explicit environment (pure apart from timing diagnostics)."""
    base = creq.base
    s = base.settings
    opt = route(base, env)
    forced: RouteResult | None = None
    cost: float | None = None
    if creq.want_forced and opt.ok and opt.path:
        tack0 = int(base.tack0) or int(opt.path[0].tack)
        tp = next((tk for tk in opt.tacks if tk.t >= base.t0), None)
        if tp is not None and tack0 != 0:
            freq = dataclasses.replace(
                base,
                tack0=tack0,
                force_tack_until=max(base.t0, tp.t) + s.stay_extra_s,
                leg_only=True,
            )
            forced = route(freq, env)
            if creq.stay_active:
                forced = dataclasses.replace(forced, notes=(*forced.notes, "on_reste"))
            if (
                forced.ok
                and forced.legs
                and opt.legs
                and forced.legs[0].mark_id == opt.legs[0].mark_id
            ):
                cost = max(0.0, forced.legs[0].eta - opt.legs[0].eta)
    eta_old = old_valid = old_reason = None
    if creq.old_path:
        try:
            polar = env.polar_for(base.polar_curves, base.eff, base.eff_up, base.eff_down)
            eta_old, old_valid, old_reason = evaluate_path(
                creq.old_path,
                base.lat,
                base.lon,
                base.t0,
                env,
                polar,
                base.bias,
                s,
                t_hint=creq.old_t_here,
            )
        except ValueError as exc:
            eta_old, old_valid, old_reason = None, False, str(exc)
    worker: dict[str, Any] = {
        "level": s.level,
        "optimal_ms": round(opt.compute_ms, 1),
        "forced_ms": round(forced.compute_ms, 1) if forced is not None else None,
        "steps": opt.steps + (forced.steps if forced is not None else 0),
        "rss_kb": rss_kb(),
        "pid": os.getpid(),
    }
    return CycleResult(opt, forced, cost, eta_old, old_valid, old_reason, worker)


def run_cycle(creq: CycleRequest) -> CycleResult:
    """Worker job (RouterPool.run_latest(run_cycle, creq))."""
    t0 = time.perf_counter()
    if _ENV is None:
        reason = _INIT_ERROR or "routeur non initialisé (init_worker non appelé)"
        return CycleResult(
            _failed(creq.base, reason),
            None,
            None,
            None,
            None,
            None,
            {"level": creq.base.settings.level, "rss_kb": rss_kb(), "pid": os.getpid()},
        )
    if creq.pack_fp is not None and _PACK_FP is not None and tuple(creq.pack_fp) != _PACK_FP:
        # the core routes the helm on another pack than this (restarted) worker loaded
        return CycleResult(
            _failed(creq.base, f"{PACK_CHANGED} : redémarrer jabuka-core", FAIL_PACK),
            None,
            None,
            None,
            None,
            None,
            {"level": creq.base.settings.level, "rss_kb": rss_kb(), "pid": os.getpid()},
        )
    res = cycle_with_env(_ENV, creq)
    res.worker["cycle_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    if _INIT_NOTES:
        res.worker["init_notes"] = list(_INIT_NOTES)
    return res
