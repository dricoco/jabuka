"""Pure formatting of the helm (web/static/helm_logic.js), run through node, on the nav message the
tracer produced (tests/fixtures/nav/tracer_nav.json, shape-checked by tests/nav/test_nav_tracer.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
LOGIC = STATIC / "helm_logic.js"
NAV = json.loads((Path(__file__).parent / "fixtures" / "nav" / "tracer_nav.json").read_text())
NODE = shutil.which("node")

# node is required: a skip would hide a broken helm (JABUKA_REQUIRE_UI-style strictness)
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def js(expr: str) -> object:
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


def test_tracer_message_renders_the_helm() -> None:
    v = js(f"helmView({json.dumps(NAV)})")
    assert v["primary"] == {"label": "TWA CIBLE ↑", "value": "38°", "unit": ""}
    assert v["countdown"].startswith("Virement dans")
    assert v["mark"] == "Plić Sestre"
    assert v["badge"] == {"text": "LIVE", "cls": "good"}
    assert v["deviation"] == "+7°"
    assert v["pct"].endswith("%")
    assert v["otherTack"].startswith("Autre bord ") and v["otherTack"].endswith("°M")
    assert v["dtw"] == "2,0 nm"


def test_primary_view_modes() -> None:
    disp = {"heading_ref": "M", "variation": 4.7}
    cts = {"helm": {"primary": "cts", "cts_t": 161.0}, "display": disp, "wind": {"source": "LIVE"}}
    assert js(f"primaryView({json.dumps(cts)})") == {
        "label": "CAP À SUIVRE",
        "value": "156°",
        "unit": "M",
    }
    down = {"helm": {"primary": "twa_down", "target": 158.9}, "wind": {"source": "LIVE"}}
    assert js(f"primaryView({json.dumps(down)})")["label"] == "TWA CIBLE ↓"
    none = {"helm": {"primary": None}, "wind": {"source": "NONE"}}
    assert js(f"primaryView({json.dumps(none)})")["label"] == "PAS DE VENT"
    assert js("primaryView(null)")["value"] == "—"


def test_fmt_heading() -> None:
    assert js("fmtHeading(2.0, {heading_ref: 'M', variation: 4.7})") == "357°M"
    assert js("fmtHeading(45.4, {heading_ref: 'T', variation: 4.7})") == "045°T"
    assert js("fmtHeading(359.6, {heading_ref: 'T'})") == "000°T"
    assert js("fmtHeading(null, {})") == "—"


def test_fmt_countdown_and_durations() -> None:
    assert js("fmtCountdown({state: 'normal', countdown_s: 720}, 'beat')") == (
        "Virement dans 12 min"
    )
    assert js("fmtCountdown({state: 'normal', countdown_s: 270}, 'run')") == (
        "Empannage dans 4 min 30"
    )
    assert js("fmtCountdown({state: 'overstood', overstood_s: 180}, 'beat')") == ("DÉPASSÉE +3 min")
    assert js("fmtCountdown({state: 'fetching'}, 'beat')") == "ÇA PASSE"
    assert js("fmtCountdown(null, 'reach')") == ""
    assert js("[45, 240, 3900].map(fmtDuration)") == ["45 s", "4 min", "1 h 05"]
    assert js("[0.35, 4.24, 38.8, null].map(fmtDistance)") == ["0,35 nm", "4,2 nm", "39 nm", "—"]


def test_source_badge_and_deviation_class() -> None:
    assert js("sourceBadge({source: 'LIVE_BG'})")["text"] == "LIVE B&G"
    assert js("sourceBadge({source: 'MANUEL'})") == {"text": "MANUEL", "cls": "warn"}
    assert js("sourceBadge({source: 'LIVE', stale: true})")["text"] == "PÉRIMÉ"
    assert js("sourceBadge({source: 'NONE'})")["text"] == "PAS DE VENT"
    assert js("[2, -5, 12, null].map(deviationClass)") == ["good", "warn", "bad", ""]


def test_static_modules_parse(tmp_path: Path) -> None:
    for name in (
        "app.js",
        "helm.js",
        "helm_logic.js",
        "carte.js",
        "reglages.js",
        "map.js",
        "overlays.js",
    ):
        copy = tmp_path / (Path(name).stem + ".mjs")
        copy.write_text((STATIC / name).read_text())
        proc = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
        assert proc.returncode == 0, (name, proc.stderr)
    html = (STATIC / "index.html").read_text()
    for dom_id in (
        "map",
        "topbar",
        "badges",
        "banner",
        "tab-barre",
        "tab-carte",
        "tab-reglages",
        "tab-diag",
        "lock-overlay",
        "primary",
        "primary-label",
        "helm-top",
        "helm-bottom",
    ):
        assert f'id="{dom_id}"' in html, dom_id
    for tab in ("barre", "carte", "reglages", "diag"):
        assert f'data-tab="{tab}"' in html
    assert "user-scalable=no" in html


def test_dom_built_without_inner_html() -> None:
    """T-02-01-02: data (mark names, alerts) is rendered with textContent only."""
    for name in ("app.js", "helm.js", "carte.js", "reglages.js", "map.js", "overlays.js"):
        assert "innerHTML" not in (STATIC / name).read_text(), name
