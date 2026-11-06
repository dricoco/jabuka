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


def test_link_watchdog_thresholds() -> None:
    """WR-05: frozen data turns stale after 3 s without a message; the socket is recycled at 6 s."""
    assert js("[RX_STALE_MS, RX_CLOSE_MS]") == [3000, 6000]
    states = js("[0, 1000, 3000, 3001, 6000, 6001, 60000].map(linkState)")
    assert states == ["live", "live", "live", "stale", "stale", "reconnect", "reconnect"]
    assert js("linkState(NaN)") == "stale"  # nothing received yet: never "live"
    assert js("linkState(undefined)") == "stale"


def test_page_wires_the_watchdog() -> None:
    src = (LOGIC.parent / "diag.js").read_text()
    assert "setInterval(watchdog" in src
    assert "markAllStale" in src and "linkState(" in src


def test_error_counters_alert_while_increasing() -> None:
    """WR-06: raw/derived/bus/event log write failures turn the page red."""
    out = js(
        """(() => {
          const mem = {};
          const m = (raw, derived) => ({
            core: { derived_errors: derived, events_errors: 0 },
            health: { fastnet: { raw_errors: raw, send_errors: 0 } },
          });
          return [
            errorAlerts(m(0, 0), mem, 0),        // all zero: nothing
            errorAlerts(m(2, 0), mem, 1000),     // raw errors appear
            errorAlerts(m(2, 0), mem, 30000),    // still within 60 s
            errorAlerts(m(2, 0), mem, 62000),    // stopped increasing: fades
            errorAlerts(m(2, 1), mem, 63000),    // derived fails now
            errorAlerts(m(0, 0), mem, 64000),    // processes restarted: counters reset
          ];
        })()"""
    )
    assert out[0] == []
    assert out[1] == ["fastnet: raw log write failed (2 since start)"]
    assert out[2] == out[1]
    assert out[3] == []
    assert out[4] == ["Core: derived log write failed (1 since start)"]
    assert out[5] == []


def test_error_counter_seen_nonzero_on_page_load_alerts() -> None:
    out = js("errorAlerts({core: {events_errors: 3}}, {}, 5)")
    assert out == ["Core: event log write failed (3 since start)"]
