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
