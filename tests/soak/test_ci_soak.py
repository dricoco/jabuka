"""CI soak inside the normal gate (plan 04-01): ``python -m jabuka.tools.soak --scenario ci``
runs every fault kind of the compressed schedule against the real stack and must exit 0.

Wall time is bounded and enforced here (04-01 checker W1: about 3 min per interpreter for the
soak tests); every child is killed on failure (the harness's own stop_all, then a /proc sweep)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

CI_WALL_S = 150.0  # the ci scenario alone; the test fails beyond it

pytestmark = [
    pytest.mark.soak,
    pytest.mark.skipif(sys.platform != "linux", reason="ptys + /proc: Linux only"),
]


def _run(
    scenario: str, out: Path, wall_s: float, leftovers
) -> tuple[subprocess.CompletedProcess, dict, float]:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "jabuka.tools.soak", "--scenario", scenario, "--out", str(out)],
            capture_output=True,
            text=True,
            timeout=wall_s + 60.0,
        )
    finally:
        left = leftovers(out)
        for pid, _cmd in left:  # never leave a harness child behind, even on a failure
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    wall = time.monotonic() - t0
    runs = sorted(out.glob(f"*-{scenario}"))
    assert runs, proc.stdout[-3000:] + proc.stderr[-3000:]
    report = json.loads((runs[-1] / "report.json").read_text())
    assert not left, f"harness processes survived: {left}"
    if proc.returncode != 0:
        failing = {k: v for k, v in report["checks"].items() if v.get("ok") is False}
        pytest.fail(
            f"{scenario} soak FAIL (report {runs[-1] / 'report.md'}): {report['fail_reasons']}\n"
            f"failing checks: {failing}\n"
            f"stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
        )
    return proc, report, wall


def test_ci_soak(tmp_path: Path, leftovers) -> None:
    proc, report, wall = _run("ci", tmp_path / "soak", CI_WALL_S, leftovers)
    print(f"\nci soak: {wall:.1f} s wall, {report['sim_s']} sim s, {report['speed_achieved']}x")
    assert wall <= CI_WALL_S, f"ci soak took {wall:.0f} s > {CI_WALL_S:.0f} s (gate budget)"
    assert report["verdict"] == "PASS"
    kinds = {f["kind"] for f in report["faults"]}
    process = {
        "kill-ingest",
        "kill-core",
        "kill-worker",
        "sigterm-storm",
        "power-pull",
        "watchdog-hang",
    }
    assert process <= kinds, process - kinds
    for f in report["faults"]:
        assert f["ok"] is True, f
    pulls = [f for f in report["faults"] if f["kind"] == "power-pull"]
    assert any(p.get("corrupt") for p in pulls) and any(not p.get("corrupt") for p in pulls)
    assert all(p["logcheck_ok"] is not False for p in pulls)
    assert report["checks"]["persistence"]["ok"] is True
    wd = [f for f in report["faults"] if f["kind"] == "watchdog-hang"]
    assert wd and wd[0]["watchdog_fired_s"] is not None
    for name in (
        "rss_core",
        "rss_worker",
        "fd_growth",
        "thread_growth",
        "cpu_per_sim_s",
        "tick_ratio",
    ):
        assert report["checks"][name]["ok"] is not False, (name, report["checks"][name])
    leak = report["checks"]["leak_slope"]
    assert leak["ok"] is not False and (leak["ok"] is True or "insufficient" in leak["detail"])
