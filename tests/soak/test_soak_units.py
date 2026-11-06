"""Unit tests of the soak harness pieces: scenarios, the supervisor shim (restart policy from the
shipped units, restart, KillMode=control-group, watchdog), the report verdict."""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

import pytest

from jabuka.soak import report as rep
from jabuka.soak.scenario import (
    FAULT_KINDS,
    compile_timeline,
    list_scenarios,
    load_scenario,
    parse_logs_fs,
    parse_scenario,
)
from jabuka.soak.supervisor import (
    EMBEDDED_POLICIES,
    UNITS,
    Policy,
    Supervisor,
    load_policy,
    parse_unit_policy,
)

REPO = Path(__file__).resolve().parents[2]
linux = pytest.mark.skipif(sys.platform != "linux", reason="process groups + /proc: Linux only")


# -- scenarios ---------------------------------------------------------------------------------
def _doc(**kw) -> dict:
    d = {
        "name": "t",
        "seed": 3,
        "speed": 60,
        "duration_s": 3600,
        "faults": [{"kind": "kill-core", "at": 100}, {"kind": "bus-silent", "at": 50, "dur": 30}],
    }
    d.update(kw)
    return d


def test_packaged_tracer_loads_by_name_and_by_path() -> None:
    assert "tracer" in list_scenarios()
    sc = load_scenario("tracer")
    assert sc.name == "tracer" and sc.speed == 60 and sc.clock == "sim"
    assert [f["kind"] for f in sc.faults] == ["kill-core"]
    path = REPO / "src" / "jabuka" / "soak" / "scenarios" / "tracer.json"
    assert load_scenario(str(path)).faults == sc.faults
    with pytest.raises(ValueError, match="unknown scenario"):
        load_scenario("no-such-scenario")


def test_unknown_kind_and_missing_keys_are_named() -> None:
    with pytest.raises(ValueError, match="volcano"):
        parse_scenario(_doc(faults=[{"kind": "volcano", "at": 1}]))
    with pytest.raises(ValueError, match="'duration_s'"):
        d = _doc()
        del d["duration_s"]
        parse_scenario(d)
    with pytest.raises(ValueError, match="'dur'"):
        parse_scenario(_doc(faults=[{"kind": "gps-loss", "at": 1}]))
    with pytest.raises(ValueError, match="'at'"):
        parse_scenario(_doc(faults=[{"kind": "kill-core"}]))
    with pytest.raises(ValueError, match="why"):
        parse_scenario(_doc(shim={"watchdog_sec": 5}))
    with pytest.raises(ValueError, match="why"):
        parse_scenario(_doc(expected_tracebacks={"kill-core": [{"pattern": "x", "why": ""}]}))


def test_logs_fs_validation_caps_the_tmpfs() -> None:
    assert parse_logs_fs("auto") == ("auto", None)
    assert parse_logs_fs("tmpfs:64M") == ("tmpfs", 64 * 1024 * 1024)
    with pytest.raises(ValueError):
        parse_logs_fs("tmpfs:1G")
    with pytest.raises(ValueError):
        parse_logs_fs("ramdisk:1M")


def test_timeline_is_ordered_and_deterministic() -> None:
    sc = parse_scenario(
        _doc(
            random={"count": 8, "kinds": list(FAULT_KINDS), "min_gap_s": 60, "until_s": 3000},
            quiet_tail_s=600,
        )
    )
    a, b = compile_timeline(sc), compile_timeline(sc)
    assert a == b
    assert [f.at for f in a] == sorted(f.at for f in a)
    assert [f.kind for f in a[:2]] == ["bus-silent", "kill-core"]
    assert len(a) >= 6
    assert compile_timeline(sc, seed=99) != a
    assert all(f.id == f"f{i:02d}" for i, f in enumerate(a, start=1))


# -- supervisor policy ---------------------------------------------------------------------------
def test_policy_from_the_shipped_units_and_drift_guard() -> None:
    for role, unit in UNITS.items():
        parsed = parse_unit_policy(REPO / "deploy" / "systemd" / unit)
        assert (parsed.restart, parsed.restart_sec, parsed.watchdog_sec) == ("always", 2.0, 30.0)
        emb = EMBEDDED_POLICIES[unit]
        assert (emb.restart, emb.restart_sec, emb.watchdog_sec) == (
            parsed.restart,
            parsed.restart_sec,
            parsed.watchdog_sec,
        ), f"{role}: embedded policy drifted from deploy/systemd/{unit}"
        assert load_policy(unit, REPO).source == f"deploy/systemd/{unit}"
        assert load_policy(unit, Path("/nonexistent")).source == "embedded"


CHILD = r"""
import subprocess, sys, time
from jabuka.common import sdnotify
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(f"grandchild {g.pid}", flush=True)
sdnotify.notify("READY=1")
mode = sys.argv[1]
while True:
    if mode == "ping":
        sdnotify.notify("WATCHDOG=1")
    time.sleep(0.1)
"""


def _grandchild(log: Path, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists():
            for line in log.read_text().splitlines():
                ts, _, text = line.partition(" ")
                if text.startswith("grandchild "):
                    float(ts)  # every line carries a wall timestamp
                    return int(text.split()[1])
        time.sleep(0.02)
    raise AssertionError(f"no grandchild line in {log}")


def _wait(pred, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("condition not met")


@linux
def test_supervisor_restarts_and_kills_the_group(tmp_path: Path, is_alive) -> None:
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    sup = Supervisor(tmp_path / "run")
    sup.add("svc", [sys.executable, str(script), "ping"], Policy("always", 0.3, None, "test"))
    try:
        sup.start("svc")
        assert sup.wait_ready("svc", 15)
        pid1 = sup.main_pid("svc")
        g1 = _grandchild(tmp_path / "run" / "proc" / "svc-1.log")
        assert is_alive(g1)
        t_kill = time.monotonic()
        sup.kill("svc", signal.SIGKILL)
        _wait(lambda: sup.restarts("svc") == 1 and sup.main_pid("svc") not in (None, pid1))
        assert time.monotonic() - t_kill >= 0.3  # RestartSec honoured
        assert sup.wait_ready("svc", 15, after_n=1)
        # KillMode=control-group: the grandchild left in the group died with its parent
        _wait(lambda: not is_alive(g1), 5)
        g2 = _grandchild(tmp_path / "run" / "proc" / "svc-2.log")
        events = [e["event"] for e in sup.events]
        assert events[:2] == ["start", "ready"] and "exit" in events and "restart" in events
        pid2 = sup.main_pid("svc")
    finally:
        sup.stop_all(timeout=3)
    assert not is_alive(pid2) and not is_alive(g2)
    sup.stop_all()  # idempotent


@linux
def test_supervisor_watchdog_aborts_a_silent_service(tmp_path: Path, is_alive) -> None:
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    sup = Supervisor(tmp_path / "run")
    sup.add("svc", [sys.executable, str(script), "silent"], Policy("always", 0.2, 0.6, "test"))
    try:
        sup.start("svc")
        assert sup.wait_ready("svc", 15)
        pid1 = sup.main_pid("svc")
        _wait(lambda: sup.services["svc"].watchdog_kills >= 1, 10)
        _wait(lambda: sup.main_pid("svc") not in (None, pid1), 10)
        wd = [e for e in sup.events if e["event"] == "watchdog"]
        assert wd and wd[0]["silent_s"] >= 0.6
        exits = sup.services["svc"].exits
        assert exits[0]["code"] in (-signal.SIGABRT, -signal.SIGKILL)
    finally:
        sup.stop_all(timeout=3)
    assert not is_alive(pid1)


# -- report ------------------------------------------------------------------------------------
def _report(recovery: float, budget: float = 30.0) -> dict:
    return {
        "scenario": "t",
        "mode": "shim",
        "host": rep.host_info(),
        "git": rep.git_info(REPO),
        "faults": [
            {
                "id": "f01",
                "kind": "kill-core",
                "t_sim": 300.0,
                "t_wall": 1000.0,
                "cleared_wall": 1000.0,
                "recovery_s": recovery,
                "budget_s": budget,
                "notes": "",
            }
        ],
        "checks": {"land": rep.check(True, 3, 0, "")},
        "t0_wall": 990.0,
    }


def test_verdict_fails_on_a_slow_recovery(tmp_path: Path) -> None:
    ok = rep.finalize(_report(3.0))
    assert ok["verdict"] == "PASS" and ok["faults"][0]["ok"] is True
    slow = rep.finalize(_report(31.0))
    assert slow["verdict"] == "FAIL" and slow["faults"][0]["ok"] is False
    assert any("kill-core" in r for r in slow["fail_reasons"])
    bad_check = _report(3.0)
    bad_check["checks"]["land"] = rep.check(False, 3, 0, "crossing")
    assert rep.finalize(bad_check)["verdict"] == "FAIL"
    unknown = _report(3.0)
    unknown["checks"]["leak_slope"] = rep.insufficient("segment 0.5 h < 3 h")
    assert rep.finalize(unknown)["verdict"] == "PASS"


def test_report_files_carry_the_frozen_keys(tmp_path: Path) -> None:
    r = rep.finalize(_report(4.2))
    jpath, mpath = rep.write_report(tmp_path, r)
    doc = json.loads(jpath.read_text())
    for key in ("schema", "verdict", "scenario", "mode"):
        assert key in doc
    assert doc["schema"] == 1 and doc["mode"] in ("shim", "systemd")
    assert "machine" in doc["host"]
    assert "head" in doc["git"] and "dirty" in doc["git"]
    md = mpath.read_text()
    assert "| f01 | kill-core |" in md and "4.2" in md


def test_traceback_classifier(tmp_path: Path) -> None:
    log = tmp_path / "core-1.log"
    log.write_text(
        "100.000 starting\n"
        "105.000 Traceback (most recent call last):\n"
        '105.000   File "x.py", line 1, in f\n'
        "105.001 OSError: [Errno 28] No space left on device\n"
        "200.000 Traceback (most recent call last):\n"
        '200.000   File "y.py", line 2, in g\n'
        "200.000 ValueError: boom\n"
        "300.000 Traceback (most recent call last):\n"
        "300.000 OSError: [Errno 28] No space left on device\n"
    )
    blocks = rep.scan_tracebacks([log])
    assert [b.t_wall for b in blocks] == [105.0, 200.0, 300.0]
    windows = [
        {"id": "f01", "kind": "disk-full", "t_wall": 100.0, "end_wall": 110.0},
        {"id": "f02", "kind": "kill-core", "t_wall": 195.0, "end_wall": 201.0},
    ]
    exp, unexp = rep.classify_tracebacks(blocks, windows, rep.merge_expected({}), margin_s=5.0)
    # in the disk-full window and matching ENOSPC: expected
    assert [e["t_wall"] for e in exp] == [105.0]
    # inside a window but no rule for that kind, and ENOSPC outside every window: unexpected
    assert [u["t_wall"] for u in unexp] == [200.0, 300.0]
