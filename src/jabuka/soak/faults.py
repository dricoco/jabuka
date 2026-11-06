"""Soak fault actions: each one injects a fault into the running stack, waits for its recovery as
the tablet sees it, and returns its timeline record (CONTEXT §Soak harness: Faults).

A fault function takes the running harness (jabuka.tools.soak.Harness) and a FaultSpec and
returns a dict with at least: t_wall (injection), cleared_wall (fault removed), end_wall (end of
its window for the traceback classifier), recovery_s, budget_s, ok, notes. Faults run one after
the other: the next one starts after this one's recovery is confirmed plus a settle time, so
attribution is never ambiguous.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from jabuka.soak.scenario import FaultSpec

if TYPE_CHECKING:
    from jabuka.tools.soak import Harness

FaultFn = Callable[["Harness", FaultSpec], dict[str, Any]]


def _rec(spec: FaultSpec, h: Harness, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": spec.id,
        "kind": spec.kind,
        "t_sim": round(h.sim_now(), 1),
        "t_wall": time.time(),
        "cleared_wall": None,
        "end_wall": None,
        "recovery_s": None,
        "budget_s": None,
        "ok": None,
        "expected_tracebacks": [],
        "notes": "",
        "random": spec.random,
    }
    base.update(kw)
    return base


def _note(rec: dict[str, Any], text: str) -> None:
    rec["notes"] = (rec["notes"] + "; " if rec["notes"] else "") + text


def _route_after(h: Harness, rec: dict[str, Any], t_from: float, v_before: int) -> bool:
    """A route with version > v_before adopted (and land-checked) within the route budget."""
    budget = h.sc.budget("route")
    deadline = max(time.time(), t_from) + budget
    while time.time() < deadline:
        newer = [r for r in h.tablet.routes_after(t_from) if (r.get("version") or 0) > v_before]
        if newer:
            r = newer[0]
            rec["route_version"] = r["version"]
            rec["route_s"] = round(r["t_wall"] - t_from, 2)
            return True
        h.poll_abort()
        time.sleep(0.05)
    _note(rec, f"no new route (version > {v_before}) within {budget:g} s")
    rec["route_s"] = None
    return False


def _restart_recovery(
    h: Harness, rec: dict[str, Any], t_kill: float, budget_key: str, *, route: bool = True
) -> None:
    """After a kill: the tablet goes dead (disconnect), then wind + position live again."""
    budget = h.sc.budget(budget_key)
    rec["budget_s"] = budget
    t_dead = h.tablet.wait(
        lambda tb: next((t for t, v in tb.conn.transitions if t >= t_kill and not v), None),
        min(10.0, budget),
    )
    if t_dead is None:
        _note(rec, "the tablet never lost the core (kill not effective?)")
        rec["ok"] = False
        return
    t_live = h.tablet.wait_live(t_dead, budget * 2.0 + 10.0)
    rec["cleared_wall"] = t_kill
    if t_live is None:
        _note(rec, "live data never came back")
        rec["ok"] = False
        rec["end_wall"] = time.time()
        return
    rec["recovery_s"] = round(t_live - t_kill, 2)
    rec["end_wall"] = t_live
    if route:
        v_before = rec.get("route_version_before", 0)
        ok = _route_after(h, rec, t_live, v_before)
        rec["end_wall"] = time.time()
        if not ok:
            rec["ok"] = False


def kill_core(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """SIGKILL of the core's main pid: the shim restarts it after RestartSec; the tablet must see
    live data within the process budget and a newer route afterwards."""
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before)
    pid = h.sup.kill("core", signal.SIGKILL)
    rec["t_wall"] = time.time()
    rec["pid"] = pid
    if pid is None:
        rec["ok"] = False
        _note(rec, "core not running")
        return rec
    _restart_recovery(h, rec, rec["t_wall"], "process")
    return rec


FAULTS: dict[str, FaultFn] = {
    "kill-core": kill_core,
}
