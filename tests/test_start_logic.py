"""Pure formatting of the start block (web/static/start_logic.js, quick 261110-cuk), run through
node on literal nav.start blocks, in French and English; plus a parse check of start.js and
start_logic.js and the no-innerHTML rule (textContent only)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
I18N = STATIC / "i18n.js"
LOGIC = STATIC / "start_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def js(expr: str, lang: str = "fr") -> object:
    code = (
        f"import * as I from {json.dumps(I18N.as_uri())};\n"
        f"import * as L from {json.dumps(LOGIC.as_uri())};\n"
        f"I.setLang({json.dumps(lang)}, {{persist: false}});\n"
        f"const f = new Function(...Object.keys(L), {json.dumps('return (' + expr + ');')});\n"
        "process.stdout.write(JSON.stringify(f(...Object.values(L))));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def block(**kw: object) -> dict:
    b: dict = {
        "open": True,
        "error": False,
        "restored": None,
        "timer": {"state": "running", "remaining_s": 120.0, "gun_utc": "2026-11-13T19:00:00Z"},
        "line": {
            "committee": {"lat": 43.7161, "lon": 15.7967, "src": "ping"},
            "pin": None,
        },
    }
    b.update(kw)
    return b


def test_fmt_timer_and_signed() -> None:
    assert js("[fmtTimer(300), fmtTimer(4.2), fmtTimer(null), fmtTimer(0), fmtTimer(59.5)]") == [
        "5:00",
        "0:05",
        "—:—",
        "0:00",
        "1:00",
    ]
    signed = "[fmtSigned(35.4), fmtSigned(-5), fmtSigned(0.2), fmtSigned(null), fmtSigned(-75)]"
    assert js(signed) == [
        "+0:35",
        "−0:05",
        "0:00",
        "",
        "−1:15",
    ]


def test_remaining_at_interpolates_and_clamps() -> None:
    b = json.dumps(block())
    assert js(f"remainingAt({b}, 1000, 3500)") == 117.5
    assert js(f"remainingAt({b}, 1000, 1000 + 200000)") == 0
    off = json.dumps(block(timer={"state": "off", "remaining_s": None, "gun_utc": None}))
    assert js(f"remainingAt({off}, 0, 1)") is None
    assert js("remainingAt(null, 0, 1)") is None


def test_coord_error_keys() -> None:
    assert js("['empty', 'minutes', 'nope'].map(coordErrorKey)") == [
        "carte.errEmpty",
        "carte.errMinutes",
        "carte.errFormat",
    ]


def test_start_view_fr_and_en() -> None:
    b = json.dumps(block())
    fr = js(f"startView({b}, 117.2)")
    assert fr["visible"] is True and fr["timer"] == {"text": "1:58", "state": "running"}
    assert fr["status"] == ""
    assert fr["ends"]["committee"] == {
        "label": "Comité",
        "text": "43°42,966' N  15°47,802' E (ping)",
        "ok": True,
    }
    assert fr["ends"]["pin"] == {"label": "Bouée", "text": "non défini", "ok": False}
    assert fr["buttons"] == {"syncDisabled": False, "stopDisabled": False}
    en = js(f"startView({b}, null)", "en")
    assert en["timer"]["text"] == "2:00"
    assert en["ends"]["committee"]["text"] == "43°42.966' N  15°47.802' E (ping)"
    assert en["ends"]["pin"] == {"label": "Pin", "text": "not set", "ok": False}

    off = json.dumps(block(timer={"state": "off", "remaining_s": None, "gun_utc": None}))
    v = js(f"startView({off}, null)")
    assert v["status"] == "Chrono arrêté" and v["timer"]["text"] == "—:—"
    assert v["buttons"] == {"syncDisabled": True, "stopDisabled": True}
    clk = json.dumps(
        block(timer={"state": "clock", "remaining_s": None, "gun_utc": "x"}, restored="bak")
    )
    v = js(f"startView({clk}, null)", "en")
    assert v["status"] == "Line restored from the backup: check it · Timer: waiting for GPS time"
    assert v["buttons"] == {"syncDisabled": True, "stopDisabled": False}
    pin = {"lat": 43.7, "lon": 15.8, "src": "typed"}
    typed = json.dumps(block(line={"committee": None, "pin": pin}))
    assert js(f"startView({typed}, null).ends.pin.text").endswith("(saisie)")


def test_start_view_hidden_and_error() -> None:
    assert js("startView(null, null).visible") is False
    assert js("startView({open: false}, null).visible") is False
    err = js("startView({open: true, error: true}, null)")
    assert err["visible"] is True and err["error"] is True
    assert err["status"] == "Mode départ indisponible"


def test_no_inner_html() -> None:
    for name in ("start.js", "start_logic.js"):
        p = STATIC / name
        lines = [ln for ln in p.read_text().splitlines() if not ln.strip().startswith("//")]
        assert "innerHTML" not in "\n".join(lines), name
        assert "insertAdjacentHTML" not in "\n".join(lines), name


def test_start_modules_parse(tmp_path: Path) -> None:
    for name in ("start.js", "start_logic.js"):
        copy = tmp_path / (Path(name).stem + ".mjs")
        copy.write_text((STATIC / name).read_text())
        proc = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
        assert proc.returncode == 0, (name, proc.stderr)


# -- Task 2: rows, reasons, beep, map --------------------------------------------------------
def side(t_s, margin, on_line=True) -> dict:
    return {"hdg_t": 322.3, "twa": 37.7, "t_s": t_s, "on_line": on_line, "margin_s": margin}


def test_rows_classes_and_suffix() -> None:
    b = block(
        now=side(95.0, 25.0),
        other=side(118.0, -3.0, on_line=False),
        line={"committee": None, "pin": None, "length_nm": 0.35, "bearing_t": 75.0},
        reason=None,
        tack_now=False,
    )
    v = js(f"startView({json.dumps(b)}, 120, {{heading_ref: 'T', variation: 0}})")
    assert v["now"] == {
        "label": "Ligne au cap",
        "time": "1:35",
        "margin": "+0:25",
        "cls": "",
        "offLine": False,
        "text": "1:35 · marge +0:25",
    }
    assert v["other"]["cls"] == "good" and v["other"]["offLine"] is True
    assert v["other"]["text"] == "1:58 · marge −0:03 · hors ligne"
    assert v["lineInfo"] == "Ligne 0,35 nm · 075°T"
    late = js(f"startView({json.dumps(block(now=side(130.0, -10.0)))}, 120).now")
    assert late["cls"] == "bad"
    en = js(f"startView({json.dumps(b)}, 120)", "en")
    assert en["other"]["text"] == "1:58 · margin −0:03 · off the line"
    assert en["now"]["label"] == "Line on heading" and en["other"]["label"] == "Other tack"
    assert js(f"startView({json.dumps(block(now=None))}, 1).now.text") == "—"


def test_reasons_fr_en() -> None:
    for reason, fr, en in (
        ("no_line", "Ligne incomplète", "Line incomplete"),
        ("no_position", "Pas de position GPS", "No GPS position"),
        ("no_heading", "Cap inconnu", "Heading unknown"),
        ("no_wind", "Pas de vent", "No wind"),
        ("calc_error", "Erreur de calcul du départ", "Start computation error"),
    ):
        b = json.dumps(block(reason=reason))
        assert js(f"startView({b}, 1).reason") == fr
        assert js(f"startView({b}, 1).reason", "en") == en
        assert js(f"startView({b}, 1).status") == fr
    assert js(f"startView({json.dumps(block(reason=None))}, 1).reason") == ""
    assert js(f"startView({json.dumps(block(tack_now=True))}, 1).tackNow") is True


def test_beep_due_rising_edge_and_gap() -> None:
    seq = js(
        "(() => { let s = null; const out = [];"
        " for (const [on, ms] of [[false, 0], [true, 1000], [true, 2000], [false, 3000],"
        " [true, 4000], [false, 12000], [true, 12500], [true, 13000]]) {"
        " const r = beepDue(s, on, ms); s = r.state; out.push(r.beep); } return out; })()"
    )
    assert seq == [False, True, False, False, False, False, True, False]


def test_start_data_features() -> None:
    ring = [[15.79, 43.69], [15.81, 43.69], [15.80, 43.70], [15.79, 43.69]]
    b = block(
        line={
            "committee": {"lat": 43.70, "lon": 15.79, "src": "ping"},
            "pin": {"lat": 43.70, "lon": 15.81, "src": "typed"},
        },
        zone=ring,
    )
    d = js(f"startData({json.dumps(b)})")
    assert d["zone"]["features"][0]["geometry"] == {"type": "Polygon", "coordinates": [ring]}
    assert d["line"]["features"][0]["geometry"]["type"] == "LineString"
    assert [f["properties"]["role"] for f in d["ends"]["features"]] == ["committee", "pin"]
    assert all(f["geometry"]["type"] == "Point" for f in d["ends"]["features"])
    empty = js(f"startData({json.dumps(block(zone=None))})")
    assert empty["zone"]["features"] == [] and empty["line"]["features"] == []
    assert len(empty["ends"]["features"]) == 1
    assert js("startData(null).zone.features") == []


def _rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def test_start_layers_night_is_red_only() -> None:
    layers = js("startLayers('night')")
    assert {ly["id"] for ly in layers} == {
        "start-zone-fill",
        "start-zone-edge",
        "start-line",
        "start-ends",
    }
    assert {ly["source"] for ly in layers} == {"start-zone", "start-line", "start-ends"}
    for ly in layers:
        for key, value in ly["paint"].items():
            if key.endswith("color"):
                _, g, b = _rgb(value)
                assert g == 0 and b == 0, (ly["id"], key, value)
            if key == "fill-opacity":
                assert value <= 0.2
    day = js("startLayers('day')")
    assert [ly["id"] for ly in day] == [ly["id"] for ly in layers]
