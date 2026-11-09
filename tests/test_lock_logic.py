"""Long-press unlock state machine of the helm lock (web/static/lock_logic.js), run through node
(HELM-04, T-02-05-03, G-4-R07): only lifting the primary pointer after a 2-4 s press unlocks; a
press that never lifts (a water drop), a press longer than 4 s, spray and second fingers never
do."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
LOGIC = STATIC / "lock_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def js(body: str) -> object:
    """Run body (statements ending in a return) with every export of lock_logic.js in scope."""
    code = (
        f"import * as L from {json.dumps(LOGIC.as_uri())};\n"
        f"const f = new Function(...Object.keys(L), {json.dumps(body)});\n"
        "process.stdout.write(JSON.stringify(f(...Object.values(L))));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_release_between_2_and_4_s_unlocks() -> None:
    # a hold alone never unlocks: only the release does (G-4-R07)
    assert js(
        "const lp = createLongPress({holdMs: 2000});"
        "const out = [lp.check(0)];"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "out.push(lp.check(1999), lp.check(2000), lp.check(2500));"
        "out.push(lp.up(2500, 1), lp.check(2500));"
        "return out;"
    ) == ["locked", "locked", "locked", "locked", True, "unlocked"]


def test_release_restarts_from_zero() -> None:
    assert js(
        "const lp = createLongPress({holdMs: 2000});"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "const out = [lp.up(1500, 1), lp.check(1500), lp.progress(1500)];"
        "lp.down(1600, {isPrimary: true, pointerId: 1});"
        "out.push(lp.up(3599, 1), lp.check(3599));"
        "lp.down(4000, {isPrimary: true, pointerId: 1});"
        "out.push(lp.up(6000, 1), lp.check(6000));"
        "return out;"
    ) == [False, "locked", 0, False, "locked", True, "unlocked"]


def test_a_press_that_never_lifts_never_unlocks() -> None:
    # the water drop: a single primary pointer resting on the padlock (G-4-R07)
    assert js(
        "const lp = createLongPress({holdMs: 2000, maxMs: 4000});"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "const out = [lp.check(2000), lp.check(3000), lp.check(4000), lp.pressing()];"
        "out.push(lp.check(4001), lp.pressing(), lp.progress(4001));"
        "out.push(lp.up(60000, 1), lp.check(60000));"
        "return out;"
    ) == ["locked", "locked", "locked", True, "locked", False, 0, False, "locked"]


def test_release_after_the_window_does_nothing() -> None:
    assert js(
        "const lp = createLongPress();"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "const out = [lp.up(4001, 1), lp.check(4001)];"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "out.push(lp.up(4000, 1), lp.check(4000));"
        "return out;"
    ) == [False, "locked", True, "unlocked"]


def test_ready_marks_the_release_window() -> None:
    assert js(
        "const lp = createLongPress({holdMs: 2000, maxMs: 4000});"
        "const out = [lp.ready(0)];"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "out.push(lp.ready(1999), lp.ready(2000), lp.ready(4000), lp.ready(4001));"
        "return out;"
    ) == [False, False, True, True, False]


def test_non_primary_pointer_never_progresses() -> None:
    assert js(
        "const lp = createLongPress({holdMs: 2000});"
        "lp.down(0, {isPrimary: false, pointerId: 7});"
        "return [lp.check(5000), lp.progress(5000)];"
    ) == ["locked", 0]


def test_second_finger_cancels_a_press() -> None:
    assert js(
        "const lp = createLongPress({holdMs: 2000});"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "lp.down(500, {isPrimary: false, pointerId: 2});"
        "return [lp.check(2500), lp.progress(2500)];"
    ) == ["locked", 0]


def test_up_of_another_pointer_does_not_end_the_press() -> None:
    assert js(
        "const lp = createLongPress({holdMs: 2000});"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "const out = [lp.up(800, 9), lp.check(2000)];"
        "out.push(lp.up(2000, 1), lp.check(2000));"
        "return out;"
    ) == [False, "locked", True, "unlocked"]


def test_cancel_resets_and_progress_runs_zero_to_one() -> None:
    assert js(
        "const lp = createLongPress({holdMs: 2000});"
        "const out = [lp.progress(0)];"
        "lp.down(100, {isPrimary: true, pointerId: 1});"
        "out.push(lp.progress(100), lp.progress(1100), lp.progress(2100), lp.progress(4100));"
        "lp.cancel();"
        "out.push(lp.progress(4100), lp.check(4100), lp.pressing());"
        "return out;"
    ) == [0, 0, 0.5, 1, 1, 0, "locked", False]


def test_reset_after_unlock_locks_again() -> None:
    assert js(
        "const lp = createLongPress();"
        "lp.down(0, {isPrimary: true, pointerId: 1});"
        "const out = [lp.up(2000, 1), lp.check(2000)];"
        "lp.reset();"
        "out.push(lp.check(2001), lp.check(10000));"
        "return out;"
    ) == [True, "unlocked", "locked", "locked"]


def test_lock_modules_parse(tmp_path: Path) -> None:
    for name in ("lock.js", "lock_logic.js", "wakelock.js"):
        copy = tmp_path / (Path(name).stem + ".mjs")
        copy.write_text((STATIC / name).read_text())
        proc = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
        assert proc.returncode == 0, (name, proc.stderr)
        assert "innerHTML" not in (STATIC / name).read_text(), name
