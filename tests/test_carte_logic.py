"""Pure course helpers of the Carte page (web/static/carte.js), run through node: where "À la
fin" inserts a new mark (quick-261110-klg)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
CARTE = STATIC / "carte.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def js(expr: str) -> object:
    code = (
        f"import * as C from {json.dumps(CARTE.as_uri())};\n"
        f"const f = new Function(...Object.keys(C), {json.dumps('return (' + expr + ');')});\n"
        "process.stdout.write(JSON.stringify(f(...Object.values(C))));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


MARKS = {
    "vodice": {"kind": "start-finish", "builtin": True},
    "plic-sestre": {"kind": "mark", "builtin": True},
    "jabuka": {"kind": "mark", "builtin": True},
    "blitvenica": {"kind": "mark", "builtin": True},
    "m1": {"kind": "mark", "builtin": False},
}


def course(ids: list[str], finish_idx: int | None = None) -> dict:
    return {
        "marks": MARKS,
        "seq": [{"mark_id": i, "side": "stbd", "radius_nm": 0.3} for i in ids],
        "active_idx": 1,
        "finish_idx": finish_idx,
        "finished": False,
    }


def end_insert_at(c: dict) -> int:
    v = js(f"endInsertAt({json.dumps(c)})")
    assert isinstance(v, int)
    return v


def test_course_a_inserts_before_the_vodice_finish() -> None:
    assert end_insert_at(course(["vodice", "plic-sestre", "jabuka", "blitvenica", "vodice"])) == 4


def test_explicit_finish_index_wins() -> None:
    c = course(["vodice", "plic-sestre", "jabuka", "blitvenica", "vodice"], finish_idx=2)
    assert end_insert_at(c) == 2


def test_finish_deleted_appends_after_the_last_mark() -> None:
    assert end_insert_at(course(["vodice", "plic-sestre", "m1", "jabuka", "blitvenica"])) == 5


def test_custom_last_mark_appends() -> None:
    assert end_insert_at(course(["vodice", "plic-sestre", "m1"])) == 3


def test_only_the_start_left_appends() -> None:
    assert end_insert_at(course(["vodice"])) == 1
