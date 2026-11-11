"""Units of the soak's run path (plan 04-01). The tracer's end-to-end run is folded into
tests/soak/test_ci_soak.py (Task 3); scenarios/tracer.json stays for manual smoke runs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from jabuka.soak import faults
from jabuka.soak.pack import build_pack, write_wind
from jabuka.soak.scenario import load_scenario
from jabuka.tools import soak

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"


def _args(**kw) -> argparse.Namespace:
    a = soak.build_arg_parser().parse_args([])
    a.fixtures = FIXTURES
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_tracer_scenario_is_one_kill_core() -> None:
    sc = load_scenario("tracer")
    assert [(f["kind"], f["at"]) for f in sc.faults] == [("kill-core", 300)]


def test_children_are_spawned_as_python_modules(tmp_path: Path) -> None:
    run = soak.make_run_dir(tmp_path / "out", "tracer")
    h = soak.Harness(run, load_scenario("tracer"), _args())
    try:
        for argv, mod in (
            (h.core_argv(), "jabuka.core.main"),
            (h.ingest_argv(), "jabuka.ingest.fastnet_main"),
            (h._synth_argv(), "jabuka.sim.synth"),
        ):
            assert argv[:3] == [sys.executable, "-m", mod]
        synth = h._synth_argv()
        for flag in ("--control", "--clock-udp", "--progress", "--follow-nowait", "--follow"):
            assert flag in synth
        assert h.core_argv()[h.core_argv().index("--clock") + 1] == "sim"
        assert "--http-host" in h.core_argv() and "127.0.0.1" in h.core_argv()
    finally:
        h._tl.close()


def test_run_dir_rules(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="/var/lib/jabuka"):
        soak.make_run_dir(Path("/var/lib/jabuka/soak"), "ci")
    run = soak.make_run_dir(tmp_path, "ci")
    assert run.is_dir() and run.name.endswith("-ci")
    with pytest.raises(FileExistsError):
        run.parent.joinpath(run.name).mkdir(exist_ok=False)
    rc = soak.main(["--scenario", "no-such-scenario", "--out", str(tmp_path)])
    assert rc == 2


def test_userns_probe_follows_unshare(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    exe = fake / "unshare"
    exe.write_text("#!/bin/sh\nexit 1\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake))
    assert soak.userns_available() is False
    exe.write_text("#!/bin/sh\nexit 0\n")
    assert soak.userns_available() is True
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert soak.userns_available() is False


class _FinishedCourseHarness:
    """04-03 full-run finding (f92 clock-jump): the boat finished the course inside the fault
    window, the route state became "no_course" and stayed there until the run loop's course
    upkeep (which only ran between faults) selected the next template: the fault waited for a
    route that no router could compute."""

    def __init__(self) -> None:
        import threading

        class Sc:
            def budget(self, key: str) -> float:
                return 1.5

        class Tablet:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.routes: list[dict] = []
                self.last_nav = {"route": {"state": "no_course"}, "course": {"finished": True}}

            def routes_after(self, t: float) -> list[dict]:
                return [r for r in self.routes if r["t_wall"] >= t]

            def route_block(self) -> dict:
                return dict(self.last_nav["route"])

        self.sc = Sc()
        self.tablet = Tablet()
        self.upkeeps = 0

    def poll_abort(self) -> None:
        pass

    def course_upkeep(self) -> bool:
        import time

        if self.tablet.last_nav["course"]["finished"]:
            self.upkeeps += 1
            self.tablet.last_nav = {"route": {"state": "ok"}, "course": {"finished": False}}
            self.tablet.routes.append({"version": 206, "t_wall": time.time()})
            return True
        return False


def test_route_wait_selects_the_next_course_when_the_boat_finished_during_a_fault() -> None:
    import time

    h = _FinishedCourseHarness()
    rec: dict = {"notes": ""}
    assert faults._route_after(h, rec, time.time(), 205)  # type: ignore[arg-type]
    assert rec["route_version"] == 206 and h.upkeeps == 1
    assert "course finished" in rec["notes"]


class _NoTmpfs:
    tmpfs = False


def test_disk_full_is_skipped_without_a_namespace() -> None:
    from jabuka.soak.scenario import FaultSpec

    out = faults.disk_full(_NoTmpfs(), FaultSpec("f01", "disk-full", 10.0, 60.0))  # type: ignore[arg-type]
    assert "skip" in out and "namespace" in out["skip"]


def test_short_wind_cube_ends_when_asked(tmp_path: Path) -> None:
    run = tmp_path / "run"
    pack = run / "racepack"
    t0 = 1_794_596_400.0  # 2026-11-13T19:00Z
    build_pack(pack, run, FIXTURES, t0, t0 + 48 * 3600, {"twd": 161, "tws_kn": 12}, {})
    with np.load(pack / "wind.npz") as z:
        full_end = int(z["t"][-1])
    assert full_end >= t0 + 48 * 3600
    write_wind(pack, run, t0, t0 + 2 * 3600 + 3600, twd=161.0, tws_kn=12.0)
    with np.load(pack / "wind.npz") as z:
        t = z["t"]
        u, v = z["u"], z["v"]
    assert int(t[-1]) == t0 + 3 * 3600 and int(t[0]) == t0 - 2 * 3600
    twd = (np.degrees(np.arctan2(-u[0, 0, 0], -v[0, 0, 0])) + 360.0) % 360.0
    assert twd == pytest.approx(161.0, abs=0.01)
    assert (pack / "landmask.npz").is_file() and (pack / "wind.json").is_file()
    with pytest.raises(ValueError, match="outside the soak run dir"):
        write_wind(tmp_path / "elsewhere", run, t0, t0 + 3600, twd=1.0, tws_kn=1.0)


@pytest.mark.skipif(sys.platform != "linux", reason="bash wrapper")
def test_soak_sh_refuses_an_out_outside_var(tmp_path: Path) -> None:
    for out in (str(tmp_path), "var/../../outside"):
        r = subprocess.run(
            ["bash", str(REPO / "scripts" / "soak.sh"), "--scenario", "tracer", "--out", out],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO,
            env=dict(os.environ),
        )
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "must" in r.stderr and "var" in r.stderr
