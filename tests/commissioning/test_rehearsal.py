"""Commissioning rehearsal (REL-03, plan 04-02): the runbook's automatable steps run on the laptop
against a replayed capture and the synthetic boat, one PASS/FAIL/SKIP/HUMAN line per step.

The quick run is the gate's dry run. The full run (live probe drills, route on the rehearsal pack,
degraded-mode drills, power pull) is long and only runs with JABUKA_REHEARSAL_FULL=1.
"""

from __future__ import annotations

import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jabuka.tools import probe, rehearsal

REPO = Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "COMMISSIONING.md"
LINE = re.compile(r"^\[(PASS|FAIL|SKIP|HUMAN)\] (R\d\.[a-z_]+) §(\d) (.+?) : (.*)$")
TAG = re.compile(r"\[(R\d\.[a-z_]+)\]")
QUICK_BUDGET_S = 45.0

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="ptys + /proc: Linux only")


def _run(*args: str, timeout: float = 600) -> tuple[subprocess.CompletedProcess, dict, float]:
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "jabuka.tools.rehearsal", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=REPO,
    )
    wall = time.monotonic() - t0
    results: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        m = LINE.match(line)
        if m:
            results[m.group(2)] = (m.group(1), m.group(5))
    return proc, results, wall


# -- registry ----------------------------------------------------------------------------------
def test_registry_invariants() -> None:
    ids = [s.id for s in rehearsal.STEPS]
    assert len(ids) == len(set(ids)), "duplicate step ids"
    for s in rehearsal.STEPS:
        assert re.fullmatch(r"R\d\.[a-z_]+", s.id), s.id
        assert 1 <= s.section <= 9, s
        assert s.id.startswith(f"R{s.section}."), s
        assert s.kind in ("auto", "human"), s
        assert s.title.strip(), s
        if s.kind == "human":
            assert s.expected.strip(), f"{s.id}: a HUMAN step needs its expected observation"
        else:
            assert s.fn is not None, s.id
    # sections in runbook order
    sections = [s.section for s in rehearsal.STEPS]
    assert sections == sorted(sections)


def test_wiring_drills_use_the_probe_exit_codes() -> None:
    drills = {s.id: s.verdict for s in rehearsal.STEPS if s.verdict is not None}
    assert drills == {
        "R2.silent": "silent",
        "R2.swap": "no_frames",
        "R2.noisy": "noisy",
        "R2.ok": "ok",
    }
    for verdict in drills.values():
        assert verdict in probe.EXIT_CODES


def test_parser_contract() -> None:
    p = rehearsal.build_arg_parser()
    a = p.parse_args([])
    assert a.steps == "quick" and a.online is False and a.json is False
    assert Path(a.capture).name == "example2_fastnet_data.txt"
    a = p.parse_args(["--steps", "R2.ok,R3.capture", "--out", "var/x", "--online", "--json"])
    assert a.steps == "R2.ok,R3.capture" and a.online and a.json


def test_unknown_step_is_a_setup_error(tmp_path: Path) -> None:
    proc, _, _ = _run("--steps", "R2.nope", "--out", str(tmp_path / "o"))
    assert proc.returncode == 2, proc.stdout + proc.stderr


# -- quick run (the gate's dry run against the fixture capture) ------------------------------
@pytest.fixture(scope="module")
def quick_run(tmp_path_factory: pytest.TempPathFactory):
    out = tmp_path_factory.mktemp("rehearsal") / "quick"
    proc, results, wall = _run("--steps", "quick", "--out", str(out), "--json", timeout=300)
    return proc, results, wall, out


def test_quick_run_wiring_and_capture(quick_run) -> None:
    proc, results, wall, out = quick_run
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for sid in (
        "R2.silent",
        "R2.swap",
        "R2.noisy",
        "R2.ok",
        "R3.capture",
        "R3.inventory",
        "R3.archive",
        "R3.replay",
        "R3.logcheck",
    ):
        assert results.get(sid, ("missing",))[0] == "PASS", (sid, proc.stdout)
    for sid in ("R2.wiring", "R3.pages"):
        assert results[sid][0] == "HUMAN", (sid, proc.stdout)
        assert results[sid][1].strip()
    # the expected exit code printed is the probe's own table
    for sid, verdict in (("R2.silent", "silent"), ("R2.swap", "no_frames")):
        assert f"code {probe.EXIT_CODES[verdict]}" in results[sid][1], results[sid]
    assert (out / "results.json").is_file()
    archives = list((out / "archive").glob("capture-*.tar.gz"))
    assert len(archives) == 1 and Path(f"{archives[0]}.sha256").is_file()
    assert wall <= QUICK_BUDGET_S, f"quick rehearsal took {wall:.1f} s"


def test_quick_run_boat_checks(quick_run) -> None:
    """§4 instrument checks, §5 offline tablet page and §7 course drill on the synthetic boat."""
    proc, results, _, _ = quick_run
    for sid in ("R4.variation", "R4.cog_hdg", "R4.awa_sign", "R4.twd", "R5.offline", "R7.drill"):
        assert results.get(sid, ("missing",))[0] == "PASS", (sid, proc.stdout)
    for sid in ("R4.dock", "R4.underway"):
        assert results[sid][0] == "HUMAN", (sid, proc.stdout)
    m = re.search(r"en ([0-9.]+) s", results["R7.drill"][1])
    assert m and float(m.group(1)) < 30.0, results["R7.drill"]
    assert results["R9.summary"][0] == "PASS"
    # quick mode stays hermetic and short: no wheelhouse/soak lookups, no route, no drills
    for sid in ("R1.wheelhouse", "R1.soak", "R6.pack", "R8.gribonly", "R8.powerpull"):
        assert sid not in results, sid


def test_random_bytes_capture_fails(tmp_path: Path) -> None:
    rng = random.Random(20261112)
    data = rng.randbytes(6000)
    cap = tmp_path / "random.txt"
    cap.write_text("".join(data[i : i + 40].hex() + "\n" for i in range(0, len(data), 40)))
    proc, results, _ = _run(
        "--steps", "R3.capture", "--capture", str(cap), "--out", str(tmp_path / "o")
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    status, detail = results["R3.capture"]
    assert status == "FAIL"
    assert "BYTES BUT NO VALID FRAMES" in detail or "no_frames" in detail, detail


# -- runbook binding (§2–§3 here; test_runbook_docs.py binds the whole document) ---------------
def test_runbook_tags_match_the_registry() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    tags = set(TAG.findall(text))
    ids = {s.id for s in rehearsal.STEPS}
    assert tags <= ids, f"runbook tags not in the registry: {sorted(tags - ids)}"
    for s in rehearsal.STEPS:
        if s.section in (2, 3):
            assert s.id in tags, f"{s.id} is not tagged in docs/COMMISSIONING.md"


def test_runbook_tags_cover_every_step() -> None:
    tags = set(TAG.findall(RUNBOOK.read_text(encoding="utf-8")))
    missing = [s.id for s in rehearsal.STEPS if s.id not in tags]
    assert not missing, f"steps not tagged in docs/COMMISSIONING.md: {missing}"


# -- full run (long: live probe drills, route, degraded drills, power pull) --------------------
@pytest.mark.skipif(
    os.environ.get("JABUKA_REHEARSAL_FULL") != "1",
    reason="full rehearsal (about 4 min): set JABUKA_REHEARSAL_FULL=1",
)
def test_full_run(tmp_path: Path) -> None:
    proc, results, wall = _run("--steps", "all", "--out", str(tmp_path / "full"), timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for s in rehearsal.STEPS:
        assert s.id in results, (s.id, proc.stdout)
    assert results["R6.dryrun"][0] == "SKIP" and "hors ligne" in results["R6.dryrun"][1]
    for sid in (
        "R2.silent",
        "R2.swap",
        "R2.noisy",
        "R2.ok",
        "R3.capture",
        "R3.replay",
        "R4.variation",
        "R4.twd",
        "R6.pack",
        "R7.drill",
        "R8.gribonly",
        "R8.manual",
        "R8.stay",
        "R8.powerpull",
        "R9.summary",
    ):
        assert results[sid][0] == "PASS", (sid, results[sid], proc.stdout)
    print(f"full rehearsal: {wall:.0f} s")
