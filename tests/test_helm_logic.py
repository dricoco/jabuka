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
    assert v["primary"]["label"] == "TWA CIBLE ↑"
    assert v["primary"]["value"] == "38°"
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
    p = js(f"primaryView({json.dumps(cts)})")
    assert (p["label"], p["value"], p["main"], p["unit"]) == ("CAP À SUIVRE", "156°M", "156°", "M")
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
    assert js("sourceBadge({source: 'MANUEL', manual_age_s: 720})")["text"] == "MANUEL 12 min"
    assert js("sourceBadge({source: 'LIVE', stale: true})")["text"] == "PÉRIMÉ"
    assert js("sourceBadge({source: 'NONE'})")["text"] == "PAS DE VENT"
    assert js("[2, -5, 12, null].map(deviationClass)") == ["good", "warn", "bad", ""]


# -- 02-05 behaviour block (HELM-02) -------------------------------------------------------------
DISP_M = {"heading_ref": "M", "variation": 4.7}


def test_primary_view_by_point_of_sail() -> None:
    up = {"helm": {"primary": "twa_up", "target": 37.7}, "wind": {"source": "LIVE"}}
    assert js(f"primaryView({json.dumps(up)})")["label"] == "TWA CIBLE ↑"
    assert js(f"primaryView({json.dumps(up)})")["value"] == "38°"
    down = {"helm": {"primary": "twa_down", "target": 150.2}, "wind": {"source": "LIVE"}}
    assert js(f"primaryView({json.dumps(down)})")["label"] == "TWA CIBLE ↓"
    cts = {"helm": {"primary": "cts", "cts_t": 120.0}, "display": DISP_M, "wind": {}}
    p = js(f"primaryView({json.dumps(cts)})")
    assert (p["label"], p["value"]) == ("CAP À SUIVRE", "115°M")
    assert js("primaryView({helm: null, wind: {source: 'LIVE'}})")["value"] == "—"


def test_deviation_view() -> None:
    def dv(primary: str, dev: float | None) -> dict:
        return js(f"deviationView({json.dumps({'helm': {'primary': primary, 'deviation': dev}})})")

    assert dv("twa_up", 4) == {"text": "+4°", "hint": "LOFER", "cls": "warn"}
    assert dv("twa_up", -1.5) == {"text": "-2°", "hint": "ABATTRE", "cls": "good"}
    assert dv("twa_down", 4)["hint"] == "LOFER"
    assert dv("twa_down", -7)["cls"] == "bad"
    assert dv("twa_up", 5.5)["cls"] == "bad"
    assert dv("cts", 6)["hint"] == "◄ BÂBORD"
    assert dv("cts", -6)["hint"] == "TRIBORD ►"
    assert dv("cts", 0)["hint"] == ""
    assert dv("twa_up", None) == {"text": "—", "hint": "", "cls": ""}
    assert js("deviationView(null)") == {"text": "—", "hint": "", "cls": ""}


def test_countdown_behaviour() -> None:
    assert js("fmtCountdown({state: 'normal', countdown_s: 720}, 'beat')") == (
        "Virement dans 12 min"
    )
    assert js("fmtCountdown({state: 'normal', countdown_s: 270}, 'run')") == (
        "Empannage dans 4 min 30"
    )
    assert js("fmtCountdown({state: 'normal', countdown_s: 3900}, 'beat')") == (
        "Virement dans 1 h 05"
    )
    assert js("fmtCountdown({state: 'overstood', overstood_s: 180}, 'beat')") == ("DÉPASSÉE +3 min")
    assert js("fmtCountdown({state: 'fetching'}, 'beat')") == "ÇA PASSE"
    assert js("fmtCountdown({state: 'normal', countdown_s: 300}, 'reach')") == ""
    assert js("fmtCountdown(null, 'beat')") == ""
    assert js("fmtCountdown(undefined)") == ""


def test_source_badge_behaviour() -> None:
    assert js("sourceBadge({source: 'LIVE'})")["text"] == "LIVE"
    assert js("sourceBadge({source: 'LIVE_BG'})")["text"] == "LIVE B&G"
    assert js("sourceBadge({source: 'MANUEL', stale: true, manual_age_s: 3600})")["text"] == (
        "PÉRIMÉ"
    )
    assert js("sourceBadge({source: 'MANUEL', manual_age_s: 720})") == {
        "text": "MANUEL 12 min",
        "cls": "warn",
    }
    assert js("sourceBadge({source: 'NONE'})") == {"text": "PAS DE VENT", "cls": "bad"}
    assert js("sourceBadge(null)")["text"] == "PAS DE VENT"


def test_helm_flags() -> None:
    nav = {
        "wind": {"heading_trusted": False, "in_zone": True},
        "layline": {"current": True, "src": "sailed"},
    }
    flags = js(f"helmFlags({json.dumps(nav)})")
    texts = [f["text"] for f in flags]
    assert "CAP NON FIABLE" in texts and "COURANT" in texts and "ANGLES RÉELS" in texts
    assert all(f["cls"] in ("good", "warn", "bad") and f["key"] for f in flags)
    ok = {"wind": {"heading_trusted": True}, "layline": {"current": False, "src": "polar"}}
    assert js(f"helmFlags({json.dumps(ok)})") == []
    assert js("helmFlags(null)") == []
    assert js("helmFlags({})") == []


def test_headings_and_other_tack() -> None:
    assert js(f"fmtHeading(247.3, {json.dumps(DISP_M)})") == "243°M"
    assert js("fmtHeading(247.3, {heading_ref: 'T', variation: 4.7})") == "247°T"
    nav = {"layline": {"state": "normal", "other_tack_hdg_t": 247.3}, "display": DISP_M}
    assert js(f"helmView({json.dumps(nav)})")["otherTack"] == "Autre bord 243°M"
    assert js("helmView({layline: {other_tack_hdg_t: null}})")["otherTack"] == ""


def test_helm_view_bands() -> None:
    v = js(f"helmView({json.dumps(NAV)})")
    assert v["speed"] == "4,5 / 6,0 nds"
    assert v["pct"] == "72 %"
    assert v["markLine"] == "Plić Sestre 2,0 nm · 25 min"
    assert v["dev"] == {"text": "+7°", "hint": "LOFER", "cls": "bad"}
    assert v["flags"] == []
    # missing blocks never throw
    empty = js("helmView({})")
    assert empty["primary"]["value"] == "—" and empty["countdown"] == ""
    assert js("helmView(null)")["speed"] == "— / — nds"


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


def test_nav_alerts_are_listed_and_a_nav_failure_is_not_no_wind() -> None:
    """CR-01: every nav alert reaches the helm view; a crashed nav computation (wind null) reads
    "ERREUR CALCUL", never "PAS DE VENT"."""
    crashed = {
        "wind": None,
        "helm": {"primary": None},
        "alerts": ["Réglages illisibles", "Erreur de calcul nav"],
    }
    v = js(f"helmView({json.dumps(crashed)})")
    assert v["primary"]["label"] == "ERREUR CALCUL"
    assert v["badge"] == {"text": "ERREUR CALCUL", "cls": "bad"}
    assert v["alerts"] == ["Réglages illisibles", "Erreur de calcul nav"]
    assert js(f"windBadge({json.dumps(crashed)})")["text"] == "ERREUR CALCUL"
    # the B&G cross-check alert is shown; "PAS DE VENT" is the wind badge, not repeated
    live = dict(NAV, alerts=["Écart TWA calculé/B&G > 10°", "PAS DE VENT", "PAS DE VENT"])
    assert js(f"navAlerts({json.dumps(live)})") == ["Écart TWA calculé/B&G > 10°"]
    assert js(f"windBadge({json.dumps(live)})") == {"text": "LIVE", "cls": "good"}
    no_wind = {"wind": {"source": "NONE"}, "helm": {"primary": None}, "alerts": ["PAS DE VENT"]}
    assert js(f"primaryView({json.dumps(no_wind)})")["label"] == "PAS DE VENT"
    assert js("navAlerts({})") == [] and js("navAlerts(null)") == []
