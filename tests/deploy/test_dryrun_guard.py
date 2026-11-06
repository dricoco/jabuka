"""scripts/racepack-dryrun.sh writes only under var/ (03-REVIEW LO-07): the OUT guard resolves the
path, so ``var/../..`` tricks and symlinks out of var/ are refused before anything is written."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "racepack-dryrun.sh"

pytestmark = pytest.mark.skipif(shutil.which("realpath") is None, reason="realpath missing")


def _run(out: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "OUT": out, "PY": "/nonexistent/python"}
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30, cwd=REPO
    )


@pytest.mark.parametrize("out", ["var/../../tmp/jabuka-evil", "var/..", "var/./../x", "/tmp/x"])
def test_out_outside_var_is_refused(out: str) -> None:
    proc = _run(out)
    assert proc.returncode == 2, proc.stderr
    assert "OUT must" in proc.stderr
    assert not Path("/tmp/jabuka-evil").exists()


def test_symlink_out_of_var_is_refused(tmp_path: Path) -> None:
    var = REPO / "var"
    var.mkdir(exist_ok=True)
    link = var / f"dryrun-guard-link-{os.getpid()}"
    link.symlink_to(tmp_path)
    try:
        proc = _run(f"{link.relative_to(REPO)}/pack")
        assert proc.returncode == 2 and "OUT must resolve under" in proc.stderr
    finally:
        link.unlink()


def test_out_under_var_passes_the_guard() -> None:
    proc = _run("var/racepack-dryrun-guard-test")
    # the guard passes; the script then stops on the missing interpreter (exit 2, other text)
    assert proc.returncode == 2 and "missing" in proc.stderr and "OUT must" not in proc.stderr
