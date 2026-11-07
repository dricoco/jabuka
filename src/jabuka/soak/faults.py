"""Soak fault actions: each one injects a fault into the running stack, waits for its recovery as
the tablet sees it, and returns its timeline record (CONTEXT §Soak harness: Faults).

A fault function takes the running harness (jabuka.tools.soak.Harness) and a FaultSpec and
returns a dict with at least: t_wall (injection), cleared_wall (fault removed), end_wall (end of
its window for the traceback classifier), recovery_s, budget_s, ok, notes. Faults run one after
the other: the next one starts after this one's recovery is confirmed plus a settle time, so
attribution is never ambiguous.

State corruption (power-pull "corrupt") is a set of pure functions over the run's data dir; every
one asserts its target is inside the run dir (T-04-01-01).
"""

from __future__ import annotations

import os
import random
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jabuka.soak import probes
from jabuka.soak.pack import inside
from jabuka.soak.scenario import CORRUPT_TARGETS, FaultSpec

if TYPE_CHECKING:
    from jabuka.tools.soak import Harness

FaultFn = Callable[["Harness", FaultSpec], dict[str, Any]]

ALERT_COURSE = "Parcours illisible : Parcours A par défaut"
ALERT_SETTINGS = "Réglages illisibles : valeurs par défaut"
ALERT_MANUAL = "Vent manuel illisible : ignoré"
ALERT_ROUTE = "Route sauvegardée illisible : ignorée"
OK_EXITS = (0, -signal.SIGTERM)


# -- state corruption (pure) -------------------------------------------------------------------
def truncate_half(path: Path, root: Path) -> str:
    """Keep the first half of the file (a torn write the atomic writer should make impossible)."""
    p = inside(path, root)
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])
    return f"{p.name}: truncated {len(data)} -> {len(data) // 2} bytes"


def garbage(path: Path, root: Path, rng: random.Random | None = None) -> str:
    """Replace the file with random bytes of the same length (SD-card corruption)."""
    p = inside(path, root)
    n = max(16, p.stat().st_size if p.exists() else 64)
    p.write_bytes((rng or random.Random(0)).randbytes(n))
    return f"{p.name}: {n} random bytes"


def drop_main(path: Path, root: Path) -> str:
    """Remove NAME, keep NAME.bak (a crash between the two renames of an older writer)."""
    p = inside(path, root)
    existed = p.exists()
    p.unlink(missing_ok=True)
    bak = p.with_name(p.name + ".bak")
    return f"{p.name}: removed (existed {existed}), {bak.name} present {bak.exists()}"


def stray_tmp(path: Path, root: Path) -> str:
    """Leave a half-written .NAME.tmp next to NAME (power cut during the temp-file write)."""
    p = inside(path, root)
    tmp = inside(p.with_name(f".{p.name}.tmp"), root)
    data = p.read_bytes() if p.exists() else b'{"version":'
    tmp.write_bytes(data[: max(1, len(data) // 3)])
    return f"{tmp.name}: stray partial temp file"


CORRUPT_FNS: dict[str, Callable[..., str]] = {
    "truncate_half": truncate_half,
    "garbage": garbage,
    "drop_main": drop_main,
    "stray_tmp": stray_tmp,
}


def corrupt(action: str, data_dir: Path, root: Path, rng: random.Random) -> tuple[str, str]:
    """Apply one corruption action to its target file. Returns (target name, description)."""
    target = CORRUPT_TARGETS[action]
    fn = CORRUPT_FNS[action]
    path = Path(data_dir) / target
    if action == "garbage":
        return target, fn(path, root, rng)
    return target, fn(path, root)


# -- helpers -----------------------------------------------------------------------------------
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


def _fail(rec: dict[str, Any], text: str) -> None:
    rec["ok"] = False
    _note(rec, text)


def _route_after(
    h: Harness, rec: dict[str, Any], t_from: float, v_before: int, *, restarted: bool = False
) -> bool:
    """A newly adopted route (land-checked by the tablet) within the route budget: version >
    v_before, or after a core restart any version other than the restored one (a saved route
    computed for an earlier course version is rightly not restored, and the numbering restarts
    at 1; the helm app redraws on any version change)."""
    budget = h.sc.budget("route")
    deadline = max(time.time(), t_from) + budget

    def new(r: dict) -> bool:
        v = r.get("version") or 0
        return v > v_before or (restarted and v != v_before)

    upkept = False
    while time.time() < deadline:
        newer = [r for r in h.tablet.routes_after(t_from) if new(r)]
        if newer:
            r = newer[0]
            rec["route_version"] = r["version"]
            rec["route_s"] = round(r["t_wall"] - t_from, 2)
            return True
        h.poll_abort()
        if h.tablet.route_block().get("state") == "no_course":
            # the boat finished the course inside the fault window (04-03 full run, f92): no
            # router can compute a route until the next template is selected, which the run loop
            # otherwise does only between faults
            h.course_upkeep()
            if not upkept:
                upkept = True
                _note(rec, "course finished during the fault: next course selected")
        time.sleep(0.05)
    _note(rec, f"no new route (version > {v_before}) within {budget:g} s")
    rec["route_s"] = None
    return False


def _wait_conn_drop(h: Harness, t: float, timeout: float) -> float | None:
    return h.tablet.wait(
        lambda tb: next((tt for tt, v in tb.conn.transitions if tt >= t and not v), None), timeout
    )


def _wait_signal_drop(h: Harness, what: str, t: float, timeout: float) -> float | None:
    sig = h.tablet.signal(what)
    return h.tablet.wait(
        lambda tb: next((tt for tt, v in sig.transitions if tt >= t and not v), None), timeout
    )


def _restart_recovery(
    h: Harness,
    rec: dict[str, Any],
    t_kill: float,
    budget_key: str,
    *,
    route: bool = True,
    budget: float | None = None,
    drop_timeout: float = 15.0,
) -> float | None:
    """After the core went down at t_kill: the tablet loses it, then wind + position are live
    again; then (route=True) a newer route is adopted. Returns the live time."""
    budget = h.sc.budget(budget_key) if budget is None else budget
    rec["budget_s"] = budget
    t_dead = _wait_conn_drop(h, t_kill, drop_timeout)
    if t_dead is None:
        _fail(rec, "the tablet never lost the core (fault not effective?)")
        return None
    t_live = h.tablet.wait_live(t_dead, budget * 2.0 + 10.0)
    if rec.get("cleared_wall") is None:
        rec["cleared_wall"] = t_kill
    if t_live is None:
        _fail(rec, "live data never came back")
        rec["end_wall"] = time.time()
        return None
    rec["recovery_s"] = round(t_live - t_kill, 2)
    rec["end_wall"] = t_live
    if route:
        if not _route_after(h, rec, t_live, rec.get("route_version_before", 0), restarted=True):
            rec["ok"] = False
        rec["end_wall"] = time.time()
    return t_live


def _ingest_recovery(h: Harness, rec: dict[str, Any], t_kill: float, budget_key: str) -> None:
    budget = h.sc.budget(budget_key)
    rec["budget_s"] = budget
    t_dead = _wait_signal_drop(h, "wind", t_kill, 10.0)
    if t_dead is None:
        _fail(rec, "live wind never dropped (fault not effective?)")
        return
    t_live = h.tablet.wait_live(t_dead, budget * 2.0 + 10.0, ("wind",))
    rec["cleared_wall"] = rec.get("cleared_wall") or t_kill
    rec["end_wall"] = t_live or time.time()
    if t_live is None:
        _fail(rec, "live wind never came back")
        return
    rec["recovery_s"] = round(t_live - t_kill, 2)


def _exit_codes(h: Harness, role: str, since: float) -> list[int | None]:
    return h.sup.exit_codes(role, since)


# -- process faults ----------------------------------------------------------------------------
def kill_core(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """SIGKILL of the core's main pid: restarted after RestartSec; live data within the process
    budget; the saved route.json is restored (shown "outdated" until checked) and a newer route
    is adopted after the first cycle."""
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before)
    pid = h.sup.kill("core", signal.SIGKILL)
    rec["t_wall"] = time.time()
    rec["pid"] = pid
    if pid is None:
        _fail(rec, "core not running")
        return rec
    t_live = _restart_recovery(h, rec, rec["t_wall"], "process")
    if t_live is not None and v_before:
        # restored: the saved route itself shown again (state "outdated" until the first cycle
        # checks it), or at least its version carried on (a fresh core without route.json
        # would number from 1; a tablet reconnecting late may miss the restored snapshot)
        after = h.tablet.routes_after(rec["t_wall"])
        seen = any(r.get("version") == v_before for r in after)
        carried = bool(after) and min(r.get("version") or 0 for r in after) >= v_before
        rec["route_restored"] = "shown" if seen else ("version carried on" if carried else None)
        # a route computed for an earlier course version (the mark was rounded since) is rightly
        # not restored (RouterService.restore)
        with h.tablet.lock:
            adopted = [r["t_wall"] for r in h.tablet.routes if r.get("version") == v_before]
            changes = [t for t, _cv in h.tablet.course_versions]
        course_moved = bool(adopted) and any(adopted[0] < t < rec["t_wall"] for t in changes)
        if not (seen or carried):
            if course_moved:
                rec["route_restored"] = "not expected: course changed since that route"
            else:
                _fail(rec, f"route.json (version {v_before}) not restored after the restart")
    return rec


def kill_ingest(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """SIGKILL of the ingest: restarted, it re-opens the SAME pty (01-04 EINVAL re-check) and the
    tablet shows live wind again within the process budget."""
    rec = _rec(spec, h)
    pid = h.sup.kill("ingest", signal.SIGKILL)
    rec["t_wall"] = time.time()
    rec["pid"] = pid
    if pid is None:
        _fail(rec, "ingest not running")
        return rec
    _ingest_recovery(h, rec, rec["t_wall"], "process")
    rec["ingest_starts"] = h.sup.starts("ingest")
    return rec


def _pool(tb: Any) -> dict[str, Any]:
    return dict((((tb.last_nav or {}).get("route") or {}).get("health")) or {})


def kill_worker(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """SIGKILL of the router worker only (child of the forkserver child of the core), while it
    computes a forced reroute: the core keeps its pid, the pool counts the crash, and a new route
    version arrives within the route budget."""
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before)
    core = h.sup.main_pid("core")
    if core is None:
        _fail(rec, "core not running")
        return rec
    workers = probes.router_tree(core)["workers"]  # located BEFORE the job
    if not workers:
        _fail(rec, "no router worker under the core")
        return rec
    p0 = _pool(h.tablet)
    crashes0, ok0 = int(p0.get("crashes") or 0), int(p0.get("ok") or 0)
    # an L0 job takes ~50 ms: freeze the worker first so the forced job is surely in flight
    # when the SIGKILL lands (a stopped process dies on SIGKILL, no SIGCONT needed)
    for w in workers:
        try:
            os.kill(w, signal.SIGSTOP)
        except ProcessLookupError:
            pass
    h.http("POST", "/api/route/recompute", {})
    running = h.tablet.wait(lambda tb: _pool(tb).get("running"), 10.0)
    rec["t_wall"] = time.time()
    for w in workers:
        try:
            os.kill(w, signal.SIGKILL)
        except ProcessLookupError:
            pass
    rec["worker_pids"] = workers
    rec["while_running"] = bool(running)
    rec["cleared_wall"] = rec["t_wall"]
    rec["budget_s"] = h.sc.budget("route")
    outcome = h.tablet.wait(
        lambda tb: (
            "crash"
            if int(_pool(tb).get("crashes") or 0) > crashes0
            else "done"
            if int(_pool(tb).get("ok") or 0) > ok0
            else None
        ),
        15.0,
    )
    rec["crash_counted"] = outcome == "crash"
    rec["job_ms"] = _pool(h.tablet).get("last_ms")
    if outcome == "done":
        _note(rec, f"the job finished before the kill ({rec['job_ms']} ms): idle worker killed")
    elif outcome is None:
        _fail(rec, "the pool counted neither a crash nor a finished job")
    h.http("POST", "/api/route/recompute", {})
    if _route_after(h, rec, rec["t_wall"], v_before):
        rec["recovery_s"] = rec["route_s"]
    else:
        rec["ok"] = False
    if h.sup.main_pid("core") != core:
        _fail(rec, "the core restarted (it must survive a worker crash)")
    rec["new_workers"] = probes.router_tree(core)["workers"]
    rec["end_wall"] = time.time()
    return rec


def sigterm_storm(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """N SIGTERMs 100 ms apart to the core, then to the ingest: both come back via the shim;
    exit codes 0 or SIGTERM only."""
    n = int(spec.params.get("n", 5))
    gap = float(spec.params.get("gap_s", 0.1))
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before, n=n)
    t0 = rec["t_wall"] = time.time()
    for _ in range(n):
        h.sup.kill("core", signal.SIGTERM)
        time.sleep(gap)
    t_live = _restart_recovery(h, rec, t0, "process", route=False)
    core_rec = rec.get("recovery_s")
    t1 = time.time()
    for _ in range(n):
        h.sup.kill("ingest", signal.SIGTERM)
        time.sleep(gap)
    sub: dict[str, Any] = {"notes": "", "ok": None}
    _ingest_recovery(h, sub, t1, "process")
    codes = {"core": _exit_codes(h, "core", t0), "ingest": _exit_codes(h, "ingest", t1)}
    rec["exit_codes"] = codes
    for role, cs in codes.items():
        if not cs:
            _fail(rec, f"{role} did not exit")
        bad = [c for c in cs if c not in OK_EXITS]
        if bad:
            _fail(rec, f"{role} exit codes {bad} (expected 0 or -15)")
    if sub.get("ok") is False:
        _fail(rec, "ingest: " + sub["notes"])
    rec["recovery_s"] = (
        None
        if core_rec is None or sub.get("recovery_s") is None
        else round(max(core_rec, sub["recovery_s"]), 2)
    )
    rec["cleared_wall"] = t0
    rec["end_wall"] = time.time()
    if t_live is not None and not _route_after(h, rec, t_live, v_before, restarted=True):
        rec["ok"] = False
    return rec


def _snapshot(h: Harness) -> dict[str, Any]:
    out = {}
    for key, path in (
        ("course", "/api/course"),
        ("settings", "/api/settings"),
        ("manual", "/api/wind/manual"),
    ):
        st, body = h.http("GET", path)
        out[key] = body if st == 200 else None
    return out


def _wait_http(h: Harness, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, _ = h.http("GET", "/api/settings", timeout=1.0)
        if st == 200:
            return True
        time.sleep(0.05)
    return False


def _read_json(path: Path) -> Any:
    import json

    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _persistence(
    h: Harness, rec: dict[str, Any], snap: dict[str, Any], files: dict[str, Any], target: str | None
) -> bool:
    """First answers after the boot equal the snapshot (clean pull, CRSE-05/REL-01); for the
    corrupted file, the .bak version or the default with its alert."""
    after = _snapshot(h)
    alerts = set((h.http("GET", "/api/nav")[1] or {}).get("alerts") or [])
    checks: dict[str, str] = {}
    ok = True
    for key, fname, alert in (
        ("course", "course.json", ALERT_COURSE),
        ("settings", "settings.json", ALERT_SETTINGS),
        ("manual", "wind_manual.json", ALERT_MANUAL),
    ):
        a, b = after.get(key), snap.get(key)
        if a == b:
            checks[key] = "same"
            continue
        if key == "course" and a and b and a.get("version", 0) > b.get("version", 0):
            checks[key] = "advanced (rounding after the boot)"
            continue
        if fname == target:
            bak = files.get(fname + ".bak")
            if bak is not None and key == "settings" and a == bak:
                checks[key] = "from .bak"
                continue
            if bak is not None and key == "course" and a and a.get("version") == bak.get("version"):
                checks[key] = "from .bak"
                continue
            if bak is not None and key == "manual" and (a or {}).get("manual") == bak:
                checks[key] = "from .bak"
                continue
            if alert in alerts:
                checks[key] = "default + alert"
                continue
            checks[key] = f"LOST: neither the .bak version nor the alert {alert!r}"
        else:
            checks[key] = "CHANGED by a clean pull"
        ok = False
    rec["persistence"] = checks
    rec["alerts_after"] = sorted(alerts)
    h.persistence.append({"id": rec["id"], "corrupt": target, "ok": ok, "checks": checks})
    if not ok:
        _fail(rec, "persistence: " + ", ".join(f"{k} {v}" for k, v in checks.items()))
    return ok


def _reapply(h: Harness, snap: dict[str, Any]) -> None:
    """After a corrupted pull: the scenario's course and settings again, so later pulls compare."""
    st, cur = h.http("GET", "/api/settings")
    want = (snap.get("settings") or {}).get("settings")
    if st == 200 and want and cur.get("settings") != want:
        h.http("PUT", "/api/settings", {"base_version": cur["version"], "patch": want})
    st, c = h.http("GET", "/api/course")
    want_c = snap.get("course") or {}
    if st == 200 and want_c and c.get("template") != want_c.get("template"):
        st, c = h.http(
            "POST",
            "/api/course/select",
            {"template": want_c["template"], "base_version": c["version"]},
        )
    if st == 200 and want_c and c.get("active_idx") != want_c.get("active_idx"):
        h.http(
            "POST",
            "/api/course/activate",
            {"idx": want_c["active_idx"], "base_version": c["version"]},
        )


def power_pull(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """SIGKILL every supervised group at once, "power off" for off_s sim seconds, an optional
    seeded corruption of one state file, then a boot (ingest + core). Persistence of course,
    settings and manual wind is checked on the first answers; logcheck runs after every pull."""
    off_s = float(spec.params.get("off_s", 60.0))
    action = spec.params.get("corrupt")
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before, off_s=off_s, corrupt=action)
    # a manual wind to carry over the pull (cleared after the check)
    h.http("POST", "/api/wind/manual", {"twd": 150.0, "tws_kn": 11.5, "ref": "T"})
    snap = _snapshot(h)
    rec["t_wall"] = t_pull = time.time()
    files: dict[str, Any] = {}
    target = None

    def off(pids: list[int]) -> None:
        """Power is off (no process, no auto-restart): logcheck, the corruption, the off time."""
        nonlocal files, target
        rec["pids"] = pids
        deadline = time.time() + 10.0
        while any(h.sup.main_pid(r) is not None for r in ("core", "ingest")):
            if time.time() > deadline:
                _fail(rec, "processes survived the pull")
                break
            time.sleep(0.02)
        if _wait_conn_drop(h, t_pull, 10.0) is None:
            _fail(rec, "the tablet never lost the core")
        files = {
            name: _read_json(h.data_dir / name)
            for base in ("course.json", "settings.json", "wind_manual.json", "route.json")
            for name in (base, base + ".bak")
        }
        lc = h.run_logcheck(f"after power pull {spec.id}")
        rec["logcheck_ok"] = lc["ok"]
        if lc["ok"] is False:
            _fail(rec, f"logcheck after the pull: {lc['errors'][:3]}")
        if action:
            target, desc = corrupt(action, h.data_dir, h.state_root, h.rng)
            h.own_state(h.data_dir)
            rec["corruption"] = desc
            h.log("corrupt", id=spec.id, action=action, detail=desc)
        off_wall = off_s / h.speed
        time.sleep(max(0.0, off_wall - (time.time() - t_pull)))
        rec["cleared_wall"] = time.time()

    h.sup.power_pull(off)  # kill all, stop (no auto-restart), off(), then start ingest + core
    t_on = rec["cleared_wall"] or time.time()
    budget = h.sc.budget("power")
    rec["budget_s"] = budget
    t_live = h.tablet.wait_live(t_on, budget * 2.0 + 10.0)
    if t_live is None:
        _fail(rec, "live data never came back after the boot")
        rec["end_wall"] = time.time()
        return rec
    rec["recovery_s"] = round(t_live - t_on, 2)
    if not _wait_http(h, 10.0):
        _fail(rec, "core HTTP not answering after the boot")
    else:
        _persistence(h, rec, snap, files, target)
        if target is not None:
            _reapply(h, snap)
        h.http("DELETE", "/api/wind/manual")
    if not _route_after(h, rec, t_live, v_before, restarted=True):
        rec["ok"] = False
    rec["end_wall"] = time.time()
    return rec


def watchdog_hang(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """SIGSTOP of the core for longer than WatchdogSec: the shim (as systemd) sees no WATCHDOG=1,
    sends SIGABRT then SIGKILL, and restarts it. SIGCONT is never needed."""
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before)
    wd = h.sup.watchdog_sec("core")
    if not wd:
        _fail(rec, "no WatchdogSec on the core")
        return rec
    kills0 = h.sup.watchdog_kills("core")
    pid = h.sup.kill("core", signal.SIGSTOP)
    rec["t_wall"] = t0 = time.time()
    rec["pid"] = pid
    rec["watchdog_sec"] = wd
    # shim: its own watchdog; systemd: SubState *-watchdog seen, then the frozen pid is SIGCONTed
    # so systemd's WatchdogSignal lands (a real hang is signalable)
    fired = h.sup.wait_watchdog("core", pid, kills0, wd + 15.0)
    if not fired:
        _fail(rec, f"no watchdog restart within {wd + 15:.0f} s")
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
    rec["watchdog_fired_s"] = round(time.time() - t0, 2) if fired else None
    _restart_recovery(
        h, rec, t0, "process", budget=wd + h.sc.budget("process"), drop_timeout=wd + 15.0
    )
    return rec


# -- synth-driven faults (--control) ------------------------------------------------------------
def _hold(h: Harness, t_on: float, dur_sim: float) -> None:
    """Keep a window open for dur_sim simulated seconds (converted to wall at the run speed)."""
    end = t_on + dur_sim / h.speed
    while time.time() < end:
        h.poll_abort()
        time.sleep(0.05)


def _health(h: Harness, src: str) -> dict[str, Any]:
    with h.tablet.lock:
        return dict(((h.tablet.last_diag or {}).get("health") or {}).get(src) or {})


def _window_on(h: Harness, spec: FaultSpec, rec: dict[str, Any]) -> float:
    """Switch the synth fault on (unless the harness already did before the boot)."""
    pre = h.preapplied.get(spec.id)
    if pre is not None:
        rec["preapplied"] = True
        return pre
    h.control(spec.kind, True)
    return time.time()


def _synth_window(
    h: Harness,
    spec: FaultSpec,
    what: tuple[str, ...],
    budget_key: str,
    *,
    must_drop: bool,
    during: Callable[[dict[str, Any], float], None] | None = None,
) -> dict[str, Any]:
    rec = _rec(spec, h)
    restarts0 = {r: h.sup.restarts(r) for r in ("core", "ingest")}
    rec["t_wall"] = t_on = _window_on(h, spec, rec)
    if must_drop:
        t_drop = _wait_signal_drop(h, what[0], t_on - 0.001, min(15.0, spec.dur / h.speed + 10.0))
        rec["dropped_s"] = None if t_drop is None else round(t_drop - t_on, 2)
        if t_drop is None:
            _fail(rec, f"{what[0]} never went stale (fault not effective?)")
    if during is not None:
        during(rec, t_on)
    _hold(h, t_on, spec.dur)
    h.control(spec.kind, False)
    rec["cleared_wall"] = t_off = time.time()
    budget = h.sc.budget(budget_key)
    rec["budget_s"] = budget
    t_live = h.tablet.wait_live(t_off, budget * 2.0 + 10.0, what)
    rec["end_wall"] = t_live or time.time()
    if t_live is None:
        _fail(rec, f"{'+'.join(what)} never live again")
    else:
        rec["recovery_s"] = round(t_live - t_off, 2)
    restarted = {r: h.sup.restarts(r) - n for r, n in restarts0.items() if h.sup.restarts(r) > n}
    if restarted:
        _fail(rec, f"processes restarted during a data fault: {restarted}")
    return rec


def bus_silent(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """Fastnet silent: live wind stale, the wind source falls back to GRIB within the fallback
    budget (WIND-05), then live again within the bus budget once the bus talks."""

    def during(rec: dict[str, Any], t_on: float) -> None:
        budget = h.sc.budget("bus_fallback")
        t = h.tablet.wait(
            lambda tb: next(
                (tt for tt, src in tb.wind_sources if tt >= t_on and src == "GRIB"), None
            ),
            budget,
        )
        rec["grib_fallback_s"] = None if t is None else round(t - t_on, 2)
        if t is None:
            _fail(rec, f"no GRIB wind within {budget:g} s of the bus going silent")

    return _synth_window(h, spec, ("wind",), "bus", must_drop=True, during=during)


def _bus_noise(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """Garbage bytes / bit flips on the bus: the decoder rejects them, keeps the good frames, and
    nothing restarts; live wind at the end of the window."""
    before = int(_health(h, "fastnet").get("bytes_discarded") or 0)

    def during(rec: dict[str, Any], t_on: float) -> None:
        pass

    rec = _synth_window(h, spec, ("wind",), "bus", must_drop=False, during=during)
    time.sleep(1.2)  # one ingest heartbeat
    after = int(_health(h, "fastnet").get("bytes_discarded") or 0)
    rec["bytes_discarded"] = after - before
    if after <= before:
        _fail(rec, "the decoder discarded nothing (fault not effective?)")
    return rec


def unplug(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """USB unplug: the pty closes (EIO), the ingest reports the device missing and retries every
    1-2 s; after the replug (fresh pty, link re-pointed) live wind within the bus budget."""
    rec = _synth_window(h, spec, ("wind",), "bus", must_drop=True)
    rec["ingest_health"] = {
        k: _health(h, "fastnet").get(k) for k in ("device", "reconnects", "last_error")
    }
    return rec


def gps_loss(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """GPS silent: position stale, live again within the GPS budget. With --clock gps (the
    gpsclock leg, from t=0): the routing gate is blocked while no GPS time was ever seen, nav keeps
    publishing with the bus wind, then the time becomes valid and a route is adopted."""
    if h.sc.clock != "gps":
        return _synth_window(h, spec, ("pos",), "gps", must_drop=True)
    rec = _rec(spec, h)
    rec["t_wall"] = t_on = _window_on(h, spec, rec)
    nav0 = h.tablet.nav_count
    blocked = h.tablet.wait(
        lambda tb: ((tb.last_nav or {}).get("route") or {}).get("state") == "blocked_clock",
        spec.dur / h.speed,
    )
    with h.tablet.lock:
        valid = ((h.tablet.last_diag or {}).get("clock") or {}).get("time_valid")
    rec["blocked_seen"] = bool(blocked)
    rec["time_valid_in_window"] = valid
    if not blocked:
        _fail(rec, "routing gate not blocked while GPS time was missing")
    if valid:
        _fail(rec, "diag clock time_valid true without any GPS fix")
    _hold(h, t_on, spec.dur)
    if h.tablet.nav_count <= nav0:
        _fail(rec, "nav stopped publishing without GPS time")
    if not h.tablet.wind.value:
        _fail(rec, "no live bus wind while GPS time was missing")
    h.control(spec.kind, False)
    rec["cleared_wall"] = t_off = time.time()
    budget = h.sc.budget("gps")
    rec["budget_s"] = budget
    t_valid = h.tablet.wait(lambda tb: tb.clock_valid_since(t_off), budget * 2.0)
    if t_valid is None:
        _fail(rec, "GPS time never became valid")
    else:
        rec["recovery_s"] = round(t_valid - t_off, 2)
    rb = h.sc.budget("route")
    r = h.tablet.wait(lambda tb: [x for x in tb.routes if x["t_wall"] >= t_off], rb)
    rec["route_s"] = None if not r else round(r[0]["t_wall"] - t_off, 2)
    if not r:
        _fail(rec, f"no route within {rb:g} s of valid GPS time")
    rec["end_wall"] = time.time()
    return rec


def clock_jump(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """GPS time steps +jump_s, then back. SimClock: the forward step moves sim time, the step back
    is ignored by mono; the tick loop keeps running, no traceback, a route after the window.
    GpsClock: the jumps are counted, time stays valid (holdover, re-anchor), route ok at the end."""
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before)
    with h.tablet.lock:
        clk0 = dict((h.tablet.last_diag or {}).get("clock") or {})
        diag0 = h.tablet.diag_count
    invalid0 = h.tablet.clock_invalid_count
    rec["t_wall"] = t_on = _window_on(h, spec, rec)
    _hold(h, t_on, spec.dur)
    h.control(spec.kind, False)
    rec["cleared_wall"] = t_off = time.time()
    if h.tablet.diag_count <= diag0:
        _fail(rec, "the tick loop stopped during the clock jump")
    budget = h.sc.budget("route")
    rec["budget_s"] = budget
    if h.sc.clock == "gps":
        time.sleep(4.0)  # the step back needs required_fixes consistent fixes to re-anchor
        with h.tablet.lock:
            clk = dict((h.tablet.last_diag or {}).get("clock") or {})
        rec["jumps"] = (clk0.get("jumps"), clk.get("jumps"))
        if not (clk.get("jumps") or 0) >= (clk0.get("jumps") or 0) + 2:
            _fail(rec, f"GpsClock did not count both steps: jumps {rec['jumps']}")
        if h.tablet.clock_invalid_count > invalid0:
            _fail(rec, "time_valid went false during the jump (holdover expected)")
        ok = h.tablet.wait(
            lambda tb: ((tb.last_nav or {}).get("route") or {}).get("state") == "ok", budget
        )
        rec["recovery_s"] = round(time.time() - t_off, 2) if ok else None
        if not ok:
            _fail(rec, f"route state not ok after the jump: {h.tablet.route_block().get('state')}")
    else:
        if _route_after(h, rec, t_off, v_before):
            rec["recovery_s"] = rec["route_s"]
        else:
            rec["ok"] = False
    rec["end_wall"] = time.time()
    return rec


# -- harness faults ------------------------------------------------------------------------------
def _dir_bytes(d: Path) -> int:
    n = 0
    for p in Path(d).rglob("*"):
        try:
            if p.is_file():
                n += p.stat().st_size
        except OSError:
            continue
    return n


def disk_full(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """Full log partition (namespaced tmpfs only): live data keeps reaching the tablet, nothing
    stays down, the retention reserve prunes, and the derived log grows again once space is freed.
    ENOSPC tracebacks are expected inside this window only."""
    if not h.tmpfs:
        return {
            "skip": getattr(
                h,
                "disk_full_skip",
                "no user namespace / tmpfs for data/logs: never filled on the real disk",
            )
        }
    rec = _rec(spec, h)
    logs = h.data_dir / "logs"
    ballast = inside(logs / "ballast.bin", h.state_root)
    restarts0 = {r: h.sup.restarts(r) for r in ("core", "ingest")}
    with h.tablet.lock:
        disk0 = dict(((h.tablet.last_diag or {}).get("core") or {}).get("disk") or {})
    rec["t_wall"] = t_on = time.time()
    written = 0
    chunk = b"\1" * (1 << 20)
    fd = os.open(ballast, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        while written < 1 << 30:  # never more than the 512M tmpfs cap allows anyway
            try:
                n = os.write(fd, chunk)  # unbuffered: ENOSPC surfaces here, not at close
            except OSError:
                break
            if n <= 0:
                break
            written += n
        while True:  # the last free pages, below one chunk
            try:
                if os.write(fd, b"\1" * 4096) <= 0:
                    break
                written += 4096
            except OSError:
                break
    finally:
        os.close(fd)
    rec["ballast_mb"] = round(written / 1e6, 1)
    dead: list[float] = []
    end = t_on + spec.dur / h.speed
    while time.time() < end:
        h.poll_abort()
        if not h.tablet.live():
            dead.append(time.time())
        time.sleep(0.1)
    with h.tablet.lock:
        disk1 = dict(((h.tablet.last_diag or {}).get("core") or {}).get("disk") or {})
    rec["retention"] = {
        "deleted": (disk0.get("deleted"), disk1.get("deleted")),
        "reserve_deletions": (disk0.get("reserve_deletions"), disk1.get("reserve_deletions")),
        "state": disk1.get("state"),
    }
    derived = logs / "derived"
    size0 = _dir_bytes(derived)
    ballast.unlink()
    rec["cleared_wall"] = t_free = time.time()
    budget = h.sc.budget("disk_resume")
    rec["budget_s"] = budget
    deadline = t_free + budget * 2.0
    grown = None
    while time.time() < deadline:
        if _dir_bytes(derived) > size0:
            grown = time.time()
            break
        time.sleep(0.1)
    if grown is None:
        _fail(rec, "the derived log never grew again after the space was freed")
    else:
        rec["recovery_s"] = round(grown - t_free, 2)
    restarted = {r: h.sup.restarts(r) - n for r, n in restarts0.items() if h.sup.restarts(r) > n}
    if restarted:
        _note(rec, f"restarted during the full disk: {restarted}")
    if dead:
        span = dead[-1] - dead[0]
        rec["dead_s"] = round(span, 2)
        if span > h.sc.budget("process"):
            _fail(rec, f"live data lost for {span:.1f} s with the log partition full")
    if not h.tablet.wait_live(time.time(), 10.0):
        _fail(rec, "no live data after the disk was freed")
    rec["end_wall"] = time.time()
    return rec


def _alerts_now(h: Harness) -> list[str]:
    with h.tablet.lock:
        nav = h.tablet.last_nav or {}
    r = nav.get("route") or {}
    return list(nav.get("alerts") or []) + list((r.get("pack") or {}).get("alerts") or [])


def grib_gap(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """A wind cube ending 1 sim-hour after now is copied in and the core restarted (race-day
    "copy the pack, restart the core"): the coverage alert shows, routing goes on (ok or horizon
    hold), the laylines publish on every nav message. The full cube is restored at the end."""
    from jabuka.soak.pack import write_wind

    rec = _rec(spec, h)
    hours = float(spec.params.get("hours_after_now", 1.0))
    now_utc = h.start_utc + h.sim_now()
    write_wind(
        h.pack_dir,
        h.state_root,
        h.start_utc,
        now_utc + hours * 3600.0,
        **h.wind_kw(),
    )
    rec["t_wall"] = t0 = time.time()
    h.sup.kill("core", signal.SIGTERM)
    _restart_recovery(h, rec, t0, "process", route=False)
    t_live = rec.get("end_wall") or time.time()
    al = h.tablet.wait(
        lambda _tb: [a for a in _alerts_now(h) if "MÉTÉO" in a.upper() or "MÉTÉO" in a], 15.0
    )
    rec["coverage_alerts"] = al or []
    if not al:
        _fail(rec, "no coverage alert with the short wind cube")
    st = h.tablet.wait(
        lambda tb: ((tb.last_nav or {}).get("route") or {}).get("state") in ("ok",),
        h.sc.budget("route"),
    )
    rb = h.tablet.route_block()
    rec["route_state"] = (rb.get("state"), rb.get("horizon_hold"), rb.get("reason"))
    if not st:
        _fail(rec, f"route state {rb.get('state')} ({rb.get('reason')}) with the short cube")
    n0, legs0 = h.tablet.layline_missing, h.tablet.layline_legs
    _hold(h, t_live, spec.dur)
    missing = h.tablet.layline_missing - n0
    rec["nav_without_laylines"] = missing
    rec["nav_beat_run"] = h.tablet.layline_legs - legs0  # reach legs have no laylines
    if missing:
        _fail(rec, f"{missing} nav messages without laylines during the GRIB gap")
    # restore the full cube with another restart
    h.write_full_wind()
    t1 = time.time()
    h.sup.kill("core", signal.SIGTERM)
    sub: dict[str, Any] = {"notes": "", "ok": None}
    if _restart_recovery(h, sub, t1, "process", route=False) is None:
        _fail(rec, "restore restart: " + sub["notes"])
    cleared = h.tablet.wait(lambda _tb: not [a for a in _alerts_now(h) if "MÉTÉO" in a], 15.0)
    if not cleared:
        _fail(rec, f"coverage alert still shown with the full cube: {_alerts_now(h)}")
    rec["cleared_wall"] = t1
    rec["end_wall"] = time.time()
    return rec


def course_change(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """Course template changed mid-leg: a route for the new course version within the route
    budget (the follow helm steers to the new mark)."""
    v_before = h.tablet.max_route_version()
    rec = _rec(spec, h, route_version_before=v_before)
    st, c = h.http("GET", "/api/course")
    if st != 200:
        _fail(rec, f"GET /api/course -> {st}")
        return rec
    other = spec.params.get("template") or ("B" if c["template"] == "A" else "A")
    rec["t_wall"] = t0 = time.time()
    st, out = h.http(
        "POST", "/api/course/select", {"template": other, "base_version": c["version"]}
    )
    rec["template"] = (c["template"], other)
    if st != 200:
        _fail(rec, f"course select -> {st} {out}")
        return rec
    rec["cleared_wall"] = t0
    rec["budget_s"] = h.sc.budget("route")
    if _route_after(h, rec, t0, v_before):
        rec["recovery_s"] = rec["route_s"]
        rb = h.tablet.route_block()
        rec["route_state"] = rb.get("state")
    else:
        rec["ok"] = False
    rec["end_wall"] = time.time()
    return rec


def stay_toggle(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """ "On reste" switched on right after a forced reroute, off a few sim minutes later: the
    route block follows, and an optimal route is shown again afterwards."""
    rec = _rec(spec, h)
    h.http("POST", "/api/route/recompute", {})
    rec["t_wall"] = t_on = time.time()
    st, out = h.http("POST", "/api/route/stay", {"active": True})
    if st == 409:  # tack unknown right now (e.g. mid-tack): once more a second later
        time.sleep(1.0)
        st, out = h.http("POST", "/api/route/stay", {"active": True})
    rec["stay_on_status"] = st
    if st != 200:
        _fail(rec, f"stay on -> {st} {out}")
        return rec

    def stay(tb: Any) -> Any:
        return (((tb.last_nav or {}).get("route") or {}).get("stay") or {}).get("active")

    if not h.tablet.wait(lambda tb: stay(tb) is True, 5.0):
        _fail(rec, "route.stay.active never true")
    _hold(h, t_on, spec.dur)
    stay_routes = [r for r in h.tablet.routes_after(t_on) if r.get("kind") == "stay"]
    rec["stay_routes"] = len(stay_routes)
    v_off = h.tablet.max_route_version()
    st, out = h.http("POST", "/api/route/stay", {"active": False})
    rec["cleared_wall"] = t_off = time.time()
    if st != 200:
        _fail(rec, f"stay off -> {st} {out}")
    if not h.tablet.wait(lambda tb: stay(tb) is False, 5.0):
        _fail(rec, "route.stay.active never false again")
    budget = h.sc.budget("route")
    rec["budget_s"] = budget

    def optimal_again(tb: Any) -> Any:
        if not tb.routes:
            return None
        last = tb.routes[-1]
        if last.get("kind") != "optimal":
            return None
        if stay_routes and (last.get("version") or 0) <= v_off:
            return None
        return last["t_wall"] if last["t_wall"] >= t_off else t_off

    t_opt = h.tablet.wait(optimal_again, budget)
    if t_opt is None:
        _fail(rec, "no optimal route after On reste was switched off")
    else:
        rec["recovery_s"] = round(t_opt - t_off, 2)
    rec["end_wall"] = time.time()
    return rec


def _ws_handshake(port: int) -> Any:
    import base64
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    s.settimeout(5.0)
    s.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(
        (
            f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        part = s.recv(1)  # byte by byte: nothing of the stream after the headers is read
        if not part:
            raise OSError("closed during the handshake")
        buf += part
    if b" 101 " not in buf.split(b"\r\n", 1)[0]:
        raise OSError(f"no upgrade: {buf[:80]!r}")
    return s


def ws_stall(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """A tablet that sleeps with its socket open (never reads): the hub drops its oldest messages,
    core RSS stays within budget, the real tablet stays live."""
    rec = _rec(spec, h)
    core = h.sup.main_pid("core")
    r0 = probes.read(core) if core else None
    if r0 is None:
        _fail(rec, "core not running")
        return rec
    try:
        sock = _ws_handshake(h.http_port)
    except OSError as exc:
        _fail(rec, f"stalled client could not connect: {exc}")
        return rec
    rec["t_wall"] = t_on = time.time()
    peak = r0["rss_kb"]
    end = t_on + spec.dur / h.speed
    dead = 0
    try:
        while time.time() < end:
            h.poll_abort()
            r = probes.read(core)
            if r is not None:
                peak = max(peak, r["rss_kb"])
            if not h.tablet.live():
                dead += 1
            time.sleep(0.1)
    finally:
        sock.close()
    rec["cleared_wall"] = time.time()
    growth = (peak - r0["rss_kb"]) / 1024.0
    budget = h.sc.budget("ws_stall_rss_mb")
    rec["rss_growth_mb"] = round(growth, 1)
    rec["rss_budget_mb"] = budget
    if growth > budget:
        _fail(rec, f"core RSS grew {growth:.1f} MB with a stalled client (budget {budget:g})")
    if h.sup.main_pid("core") != core:
        _fail(rec, "the core restarted with a stalled client")
    if dead > 10:
        _fail(rec, f"the real tablet was not live for ~{dead / 10:.1f} s")
    rec["recovery_s"] = 0.0
    rec["end_wall"] = time.time()
    return rec


def ws_churn(h: Harness, spec: FaultSpec) -> dict[str, Any]:
    """Wi-Fi flapping: 50 WebSocket connect/close cycles; the core's fd count returns to its
    baseline."""
    from websockets.sync.client import connect

    rec = _rec(spec, h)
    n = int(spec.params.get("n", 50))
    core = h.sup.main_pid("core")
    r0 = probes.read(core) if core else None
    if r0 is None:
        _fail(rec, "core not running")
        return rec
    rec["t_wall"] = time.time()
    errors = 0
    for _ in range(n):
        try:
            with connect(f"ws://127.0.0.1:{h.http_port}/ws", open_timeout=2.0) as ws:
                ws.recv(timeout=2.0)
        except Exception:  # noqa: BLE001 - counted
            errors += 1
    rec["cleared_wall"] = t_off = time.time()
    rec["connect_errors"] = errors
    tol = 3
    back = None
    deadline = t_off + 10.0
    fds = None
    while time.time() < deadline:
        r = probes.read(core)
        fds = None if r is None else r["fds"]
        if fds is not None and fds <= r0["fds"] + tol:
            back = time.time()
            break
        time.sleep(0.1)
    rec["fds"] = (r0["fds"], fds)
    if back is None:
        _fail(rec, f"core fds {r0['fds']} -> {fds} after {n} connect/close cycles")
    else:
        rec["recovery_s"] = round(back - t_off, 2)
    if errors > n // 10:
        _fail(rec, f"{errors}/{n} connects failed")
    rec["end_wall"] = time.time()
    return rec


FAULTS: dict[str, FaultFn] = {
    "kill-core": kill_core,
    "kill-ingest": kill_ingest,
    "kill-worker": kill_worker,
    "sigterm-storm": sigterm_storm,
    "power-pull": power_pull,
    "watchdog-hang": watchdog_hang,
    "bus-silent": bus_silent,
    "garbage": _bus_noise,
    "noise": _bus_noise,
    "unplug": unplug,
    "gps-loss": gps_loss,
    "clock-jump": clock_jump,
    "disk-full": disk_full,
    "grib-gap": grib_gap,
    "course-change": course_change,
    "stay-toggle": stay_toggle,
    "ws-stall": ws_stall,
    "ws-churn": ws_churn,
}
