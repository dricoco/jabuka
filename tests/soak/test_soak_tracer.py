"""Tracer soak (plan 04-01 Task 1): one command runs the real stack under SimClock, kills the core
once, and the tablet gets live data and a new route back. Marker soak, Linux only."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

TRACER_WALL_S = 90.0

pytestmark = [
    pytest.mark.soak,
    pytest.mark.skipif(sys.platform != "linux", reason="ptys + /proc: Linux only"),
]


def test_tracer_soak_kill_core_recovers(tmp_path: Path, leftovers) -> None:
    out = tmp_path / "soak"
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "jabuka.tools.soak", "--scenario", "tracer", "--out", str(out)],
            capture_output=True,
            text=True,
            timeout=TRACER_WALL_S + 60.0,
        )
    finally:
        left = leftovers(out)
    wall = time.monotonic() - t0
    runs = sorted(out.glob("*-tracer"))
    assert runs, proc.stdout + proc.stderr
    report = json.loads((runs[-1] / "report.json").read_text())
    assert proc.returncode == 0, (proc.stdout[-3000:], proc.stderr[-3000:], report["fail_reasons"])
    assert wall < TRACER_WALL_S
    assert not left, f"harness processes survived: {left}"

    assert report["verdict"] == "PASS" and report["scenario"] == "tracer"
    [kill] = report["faults"]
    assert kill["kind"] == "kill-core" and kill["ok"] is True
    assert kill["recovery_s"] <= 30.0
    assert kill["route_version"] > kill["route_version_before"]
    routes = report["routes"]
    assert routes and all(r["land_ok"] for r in routes), routes
    assert report["checks"]["land"]["ok"] is True
    assert report["checks"]["tracebacks"]["ok"] is True
    assert report["checks"]["logcheck"]["ok"] is True
    md = (runs[-1] / "report.md").read_text()
    assert "kill-core" in md and "PASS" in md
