"""Pure logic of the diagnostics page (web/static/diag_logic.js), run through node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

LOGIC = Path(jabuka.__file__).resolve().parent / "web" / "static" / "diag_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def js(expr: str) -> object:
    """Evaluate expr (with every export of diag_logic.js in scope) and return it as JSON."""
    code = (
        f"import * as L from {json.dumps(LOGIC.as_uri())};\n"
        f"const f = new Function(...Object.keys(L), {json.dumps('return (' + expr + ');')});\n"
        "process.stdout.write(JSON.stringify(f(...Object.values(L))));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_no_alerts_when_all_ok() -> None:
    msg = {
        "core": {"disk": {"state": "ok", "free_bytes": 5e9, "raw_floor_breaches": 0}},
        "health": {"fastnet": {"disk_state": "ok"}},
    }
    assert js(f"alertsFor({json.dumps(msg)})") == []
    assert js("alertsFor({})") == []


@pytest.mark.parametrize("state", ["low", "pruning", "error"])
def test_disk_states_raise_an_alert(state: str) -> None:
    msg = {"core": {"disk": {"state": state, "free_bytes": 2e8, "last_error": "EIO"}}}
    out = js(f"alertsFor({json.dumps(msg)})")
    assert len(out) == 1 and "200 MB free" in out[0]


def test_raw_floor_breach_and_ingest_disk_alerts() -> None:
    msg = {
        "core": {"disk": {"state": "ok", "raw_floor_breaches": 2}},
        "health": {"fastnet": {"disk_state": "low", "disk_free_bytes": 1e8}},
    }
    out = js(f"alertsFor({json.dumps(msg)})")
    assert any("36 h" in a for a in out)
    assert any(a.startswith("fastnet: disk low") for a in out)


def test_diag_page_scripts_parse_as_modules(tmp_path: Path) -> None:
    for name in ("diag.js", "diag_logic.js"):
        copy = tmp_path / (Path(name).stem + ".mjs")
        copy.write_text((LOGIC.parent / name).read_text())
        proc = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
        assert proc.returncode == 0, (name, proc.stderr)
    assert 'id="alerts"' in (LOGIC.parent / "index.html").read_text()
