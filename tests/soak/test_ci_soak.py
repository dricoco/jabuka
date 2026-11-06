"""CI soak inside the normal gate (plan 04-01): ``python -m jabuka.tools.soak --scenario ci`` (every
fault kind of the compressed schedule, SimClock at 60x) and ``--scenario gpsclock-ci`` (the
production GPS clock at 1x: GPS time late after boot, +1 h / -1 h step) run side by side against
the real stack and must both exit 0.

Wall time is bounded and enforced here (04-01 checker W1: about 3 min per interpreter for the
soak tests); every child is killed on failure (the harness's own stop_all, then a /proc sweep of
anything still mentioning the run dir)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jabuka.soak.scenario import FAULT_KINDS

WALL_S = {"ci": 165.0, "gpsclock-ci": 90.0}  # each run; the test fails beyond it

pytestmark = [
    pytest.mark.soak,
    pytest.mark.skipif(sys.platform != "linux", reason="ptys + /proc: Linux only"),
]


def _sweep(out: Path, leftovers) -> list:
    left = leftovers(out)
    for pid, _cmd in left:  # never leave a harness child behind, even on a failure
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return left


def _report(scenario: str, out: Path, proc: subprocess.Popen, stdout: str) -> dict:
    runs = sorted(out.glob(f"*-{scenario}"))
    assert runs, f"{scenario}: no run dir; output: {stdout[-3000:]}"
    report = json.loads((runs[-1] / "report.json").read_text())
    if proc.returncode != 0:
        failing = {k: v for k, v in report["checks"].items() if v.get("ok") is False}
        pytest.fail(
            f"{scenario} soak FAIL (report {runs[-1] / 'report.md'}): {report['fail_reasons']}\n"
            f"failing checks: {failing}\noutput: {stdout[-2500:]}"
        )
    return report


def test_ci_soaks(tmp_path: Path, leftovers) -> None:
    procs: dict[str, tuple[subprocess.Popen, Path, float]] = {}
    outs: dict[str, str] = {}
    walls: dict[str, float] = {}
    try:
        for name in WALL_S:
            out = tmp_path / name
            log = open(tmp_path / f"{name}.out", "w")  # noqa: SIM115 - closed below
            p = subprocess.Popen(
                [sys.executable, "-m", "jabuka.tools.soak", "--scenario", name, "--out", str(out)],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            log.close()
            procs[name] = (p, out, time.monotonic())
        # both run side by side: each one's own wall time, each one's own hard limit
        while len(walls) < len(procs):
            for name, (p, _out, t0) in procs.items():
                if name in walls:
                    continue
                if p.poll() is not None:
                    walls[name] = time.monotonic() - t0
                    print(f"\n{name} soak: {walls[name]:.1f} s wall")
                elif time.monotonic() - t0 > WALL_S[name] + 60.0:
                    p.terminate()  # the harness stops its children on SIGTERM
                    p.wait(timeout=30)
                    pytest.fail(f"{name} soak exceeded {WALL_S[name] + 60:.0f} s")
            time.sleep(0.2)
        for name in procs:
            outs[name] = (tmp_path / f"{name}.out").read_text(errors="replace")
            assert walls[name] <= WALL_S[name], (
                f"{name} took {walls[name]:.0f} s > {WALL_S[name]:.0f} s"
            )
    finally:
        for name, (p, out, _t0) in procs.items():
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
            left = _sweep(out, leftovers)
            assert not left, f"{name}: harness processes survived: {left}"

    ci = _report("ci", procs["ci"][1], procs["ci"][0], outs["ci"])
    gps = _report(
        "gpsclock-ci", procs["gpsclock-ci"][1], procs["gpsclock-ci"][0], outs["gpsclock-ci"]
    )

    # ci: every CONTEXT fault kind ran ok, or is SKIPPED with a host reason
    assert ci["verdict"] == "PASS"
    ran = {f["kind"] for f in ci["faults"]}
    skipped = {s["kind"]: s["reason"] for s in ci["skipped"]}
    assert set(FAULT_KINDS) <= ran | set(skipped), set(FAULT_KINDS) - ran - set(skipped)
    assert all(f["ok"] is True for f in ci["faults"]), [f for f in ci["faults"] if not f["ok"]]
    assert all(r and r != "not implemented" for r in skipped.values()), skipped
    if _userns_available():  # the full log partition must really have been played here
        assert "disk-full" in ran, skipped
    pulls = [f for f in ci["faults"] if f["kind"] == "power-pull"]
    assert any(p.get("corrupt") for p in pulls) and any(not p.get("corrupt") for p in pulls)
    assert all(p["logcheck_ok"] is not False for p in pulls)
    assert ci["checks"]["persistence"]["ok"] is True
    wd = [f for f in ci["faults"] if f["kind"] == "watchdog-hang"]
    assert wd and wd[0]["watchdog_fired_s"] is not None
    for name in (
        "rss_core",
        "rss_worker",
        "fd_growth",
        "thread_growth",
        "cpu_per_sim_s",
        "tick_ratio",
        "log_disk",
        "land",
        "tracebacks",
        "error_counters",
    ):
        assert ci["checks"][name]["ok"] is not False, (name, ci["checks"][name])
    leak = ci["checks"]["leak_slope"]
    assert leak["ok"] is not False and (leak["ok"] is True or "insufficient" in leak["detail"])

    # gpsclock-ci: the production clock path
    assert gps["verdict"] == "PASS"
    kinds = [f["kind"] for f in gps["faults"]]
    assert kinds == ["gps-loss", "clock-jump"], kinds
    late, jump = gps["faults"]
    assert late["blocked_seen"] is True and late["recovery_s"] <= 10.0 and late["route_s"] <= 30.0
    assert jump["jumps"][1] >= (jump["jumps"][0] or 0) + 2


def _userns_available() -> bool:
    from jabuka.tools.soak import userns_available

    return userns_available()
