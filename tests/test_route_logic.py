"""Pure formatting of the route block on the helm (web/static/route_logic.js), run through node on
literal nav messages (the 03-05 route block contract, see 03-05-SUMMARY.md)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
LOGIC = STATIC / "route_logic.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

DISP_M = {"heading_ref": "M", "variation": 4.7}


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


def route(**kw: object) -> dict:
    """A route block as the core sends it (state ok, starboard upwind, tack in 8 min 30)."""
    r: dict = {
        "state": "ok",
        "reason": None,
        "version": 3,
        "kind": "optimal",
        "age_s": 190,
        "computed_utc": "2026-11-13T18:00:00Z",
        "level": "L0",
        "eta_utc": "2026-11-14T20:00:00Z",
        "leg_eta_utc": "2026-11-13T19:00:00Z",
        "primary": "twa",
        "target": 42.0,
        "deviation": 3.0,
        "target_twa": 42.0,
        "target_tack": "stbd",
        "target_hdg_t": 119.0,
        "xte_nm": 0.1,
        "off_route": False,
        "countdown_s": 510,
        "tack_kind": "tack",
        "tack_lat": 43.7,
        "tack_lon": 15.8,
        "missed": False,
        "updating": False,
        "cost_s": 240,
        "cost_text": "+4 min",
        "stay": {"active": False, "tack": None, "released_land": False, "release_in_s": None},
        "horizon_hold": False,
        "start_in_margin": False,
        "bias": {
            "enabled": True,
            "valid": False,
            "state": "aucun",
            "dir_deg": None,
            "ratio": None,
            "text": None,
            "reason": None,
        },
        "pack": {"ok": True, "model": "icon-eu", "run": "2026-11-13T12:00Z", "alerts": []},
        "health": {"jobs": 4, "ok": 4, "timeouts": 0, "crashes": 0, "last_ms": 900},
    }
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(r.get(k), dict):
            r[k] = {**r[k], **v}
        else:
            r[k] = v
    return r


def nav(r: dict | None, **kw: object) -> dict:
    n = {
        "route": r,
        "layline": {"state": "normal", "countdown_s": 720},
        "leg": "beat",
        "display": DISP_M,
        "wind": {"source": "LIVE"},
    }
    n.update(kw)
    return n


def cd(r: dict | None, **kw: object) -> dict:
    return js(f"countdownView({json.dumps(nav(r, **kw))})")


# -- Task 1: countdown, band ---------------------------------------------------------------------
def test_countdown_from_the_route() -> None:
    assert cd(route()) == {"text": "Virement dans 08:30", "cls": "", "source": "route"}
    assert cd(route(tack_kind="gybe"))["text"] == "Empannage dans 08:30"
    assert cd(route(countdown_s=4000))["text"] == "Virement dans 1 h 07"
    assert cd(route(countdown_s=59))["text"] == "Virement dans 00:59"


def test_countdown_now_missed_and_land_release() -> None:
    for s in (0, -1, -119):
        v = cd(route(countdown_s=s))
        assert (v["text"], v["cls"], v["source"]) == ("VIREZ", "alert", "route")
    assert cd(route(updating=True, missed=True, countdown_s=-130))["text"] == ("Route mise à jour…")
    land = route(
        kind="stay",
        stay={"active": True, "tack": "stbd", "released_land": True, "release_in_s": 95},
    )
    assert cd(land)["text"] == "Virement imposé (terre) dans 01:35"
    # 03-REVIEW LO-08: once the release time has passed, the land-forced tack is VIREZ (red),
    # never "dans 00:00"
    for left, cdn in ((0, 0), (-30, -30)):
        due = route(
            kind="stay",
            countdown_s=cdn,
            stay={"active": True, "tack": "stbd", "released_land": True, "release_in_s": left},
        )
        assert (cd(due)["text"], cd(due)["cls"]) == ("VIREZ", "alert")


def test_countdown_falls_back_to_the_laylines() -> None:
    for r in (
        route(state="computing", countdown_s=None),
        route(state="no_pack", reason="pas de dossier de pack"),
        route(state="blocked_clock"),
        None,
    ):
        v = cd(r)
        assert v == {"text": "Virement dans 12 min", "cls": "", "source": "layline"}, r
    assert cd(None, layline=None)["text"] == ""
    assert js("countdownView(null)") == {"text": "", "cls": "", "source": "layline"}


def cue(r: dict | None) -> object:
    return js(f"tackCue({json.dumps(r)})")


def test_tack_cue() -> None:
    """G-4-R03: the advised tack is due (or the boat is on the wrong tack): the cue word, the
    tack to go to (due: the other tack; wrong tack: the route's tack) and the label."""
    want = {"word": "VIREZ", "tack": "bâbord", "label": "MAINTENANT", "kind": "due"}
    assert cue(route(countdown_s=0)) == want
    for s in (-1, -119):
        c = cue(route(countdown_s=s))
        assert (c["word"], c["kind"]) == ("VIREZ", "due"), s
    for s in (-120, 30):
        assert cue(route(countdown_s=s)) is None, s
    assert cue(route(countdown_s=-5, tack_kind="gybe"))["word"] == "EMPANNEZ"
    wrong = route(wrong_tack=True, target_tack="port", target_twa=-42.0, countdown_s=300)
    assert cue(wrong) == {
        "word": "VIREZ",
        "tack": "bâbord",
        "label": "MAUVAIS BORD",
        "kind": "wrong",
    }
    assert cue(dict(wrong, target_twa=150.0))["word"] == "EMPANNEZ"
    assert cue(route(countdown_s=0, updating=True)) is None
    assert cue(route(state="outdated", countdown_s=0)) is None
    assert cue(route(countdown_s=0, target_tack=None))["tack"] == ""
    assert js("tackCue(null)") is None


def test_route_band_lines() -> None:
    b = js(f"routeBand({json.dumps(nav(route()))})")
    assert b["visible"] is True
    assert b["lines"]["age"] == "Route : il y a 3 min"
    assert b["lines"]["cost"] == "Ne pas virer : +4 min"
    assert b["lines"]["countdown"] == "Virement dans 08:30"
    assert b["lines"]["status"] in ("", None)
    # upwind TWA steering: the band adds the heading of the route (display reference)
    assert b["lines"]["target"] == "Cap route 114°M"
    small = js(f"routeBand({json.dumps(nav(route(cost_text='< 1 min', cost_s=20)))})")
    assert small["lines"]["cost"] == "Ne pas virer : < 1 min"
    none = js(f"routeBand({json.dumps(nav(route(cost_text=None, cost_s=None)))})")
    assert none["lines"]["cost"] is None
    hdg = route(primary="hdg", target=119.0, target_twa=-95.0, target_tack="port")
    assert js(f"routeBand({json.dumps(nav(hdg))})")["lines"]["target"] == "TWA route 95° bâbord"
    hour = js(f"routeBand({json.dumps(nav(route(age_s=3900)))})")
    assert hour["lines"]["age"] == "Route : il y a 1 h 05"
    fresh = js(f"routeBand({json.dumps(nav(route(age_s=12)))})")
    assert fresh["lines"]["age"] == "Route : il y a < 1 min"


def test_route_band_states() -> None:
    def status(r: dict) -> str:
        return js(f"routeBand({json.dumps(nav(r))})")["lines"]["status"]

    assert status(route(state="blocked_clock", reason="heure GPS non valide")) == (
        "Routage bloqué : heure GPS non valide"
    )
    assert status(route(state="no_pack", reason="pas de dossier de pack")) == (
        "Pas de pack météo : pas de dossier de pack"
    )
    assert status(route(state="computing", reason=None)) == "Calcul de la route…"
    assert status(route(state="failed", reason="délai dépassé")) == (
        "Routage en échec : délai dépassé"
    )
    assert status(route(level="L2")) == "Route : niveau L2"
    assert status(route(updating=True, missed=True)) == "Route mise à jour…"
    blocked = js(f"routeBand({json.dumps(nav(route(state='blocked_clock')))})")
    assert blocked["visible"] is True and blocked["cls"] == "bad"
    assert blocked["lines"]["cost"] is None and blocked["lines"]["age"] is None
    assert js(f"routeBand({json.dumps(nav(None))})")["visible"] is False
    assert js("routeBand(null)")["visible"] is False


def test_route_geojson_split_and_layers() -> None:
    msg = {
        "type": "route",
        "version": 2,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[15.8, 43.7], [15.9, 43.6]]},
                    "properties": {"role": "route"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [15.85, 43.65]},
                    "properties": {"role": "tack", "kind": "tack"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [15.85, 43.65]},
                    "properties": {"role": "next_tack", "kind": "tack"},
                },
            ],
        },
    }
    d = js(f"routeData({json.dumps(msg)})")
    assert [f["geometry"]["type"] for f in d["line"]["features"]] == ["LineString"]
    assert len(d["tacks"]["features"]) == 1
    assert len(d["next"]["features"]) == 1
    assert js("routeData(null).line.features.length") == 0
    nxt = js("nextTackData({tack_lat: 43.6, tack_lon: 15.9})")
    assert nxt["features"][0]["geometry"]["coordinates"] == [15.9, 43.6]
    assert js("nextTackData({tack_lat: null, tack_lon: null}).features.length") == 0
    # night: only red on black in every paint colour of the route layers
    night = json.dumps(js("routeLayers('night')"))
    import re

    colors = set(re.findall(r"#[0-9a-fA-F]{6}", night))
    assert colors and all(c[3:] == "0000" for c in colors), colors
    day = js("routeLayers('day')")
    assert {ly["source"] for ly in day} == {"route", "route-tack", "route-next"}


def test_withdrawn_route_falls_back_to_the_laylines() -> None:
    # 03-REVIEW CR-02: an "outdated" route is not steerable: layline countdown, a clear reason
    out = route(
        state="outdated",
        reason="parcours modifié : recalcul en cours",
        target_twa=None,
        target=None,
        countdown_s=None,
        updating=False,
    )
    assert cd(out) == {"text": "Virement dans 12 min", "cls": "", "source": "layline"}
    b = js(f"routeBand({json.dumps(nav(out))})")
    assert b["visible"] is True and b["cls"] == "warn"
    assert b["lines"]["status"] == "Route retirée : parcours modifié : recalcul en cours"
    assert b["lines"]["cost"] is None and b["lines"]["countdown"] is None
    assert js(f"stayButton({json.dumps(out)})")["disabled"] is True
    assert js(f"routeVisible({json.dumps(out)})") is True
    assert js(f"routeVisible({json.dumps(route(state='failed'))})") is False
    # a still steerable route whose last recompute failed says so, in amber
    stale = route(stale=True, last_fail="timeout: no result after 60 s")
    sb = js(f"routeBand({json.dumps(nav(stale))})")
    assert sb["cls"] == "warn"
    assert sb["lines"]["status"] == "Recalcul en échec : timeout: no result after 60 s"
    assert sb["lines"]["countdown"] == "Virement dans 08:30"


def test_withdrawn_route_line_is_greyed() -> None:
    line = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[15.8, 43.7], [15.9, 43.6]]},
                "properties": {"role": "route", "version": 2},
            }
        ],
    }
    grey = js(f"staleLine({json.dumps(line)}, true)")
    assert grey["features"][0]["properties"] == {"role": "route", "version": 2, "stale": True}
    assert (
        js(f"staleLine({json.dumps(line)}, false)")["features"][0]["properties"]["stale"] is False
    )
    assert js("staleLine(null, true).features.length") == 0
    day = js("routeLayers('day')")[0]["paint"]["line-color"]
    assert day[0] == "case" and day[-2:] == ["#9e9e9e", "#8b008b"]
    night = js("routeLayers('night')")[0]["paint"]["line-color"]
    assert night[-2:] == ["#550000", "#ff0000"]


# -- Task 2: On reste, bias ----------------------------------------------------------------------
def test_stay_button() -> None:
    def sb(r: dict | None) -> dict:
        return js(f"stayButton({json.dumps(r)})")

    assert sb(route()) == {"label": "ON RESTE", "active": False, "disabled": False}
    on = route(kind="stay", stay={"active": True, "tack": "stbd"})
    assert sb(on) == {"label": "ANNULER ON RESTE", "active": True, "disabled": False}
    assert sb(route(state="computing"))["disabled"] is True
    assert sb(route(target_tack=None))["disabled"] is True
    assert sb(None) == {"label": "ON RESTE", "active": False, "disabled": True}
    # cancelling stays possible whatever the routing state
    blocked_on = route(state="blocked_clock", stay={"active": True, "tack": "port"})
    assert sb(blocked_on)["disabled"] is False


def test_bias_text() -> None:
    def bt(**kw: object) -> str | None:
        b = {"enabled": True, "valid": True, "state": "actif", "dir_deg": 12.3, "ratio": 1.152}
        b.update(kw)
        return js(f"biasText({json.dumps(b)})")

    assert bt() == "Biais GRIB +12° ×1.15"
    assert bt(dir_deg=-7.6, ratio=0.9) == "Biais GRIB -8° ×0.90"
    assert bt(state="s'estompe") == "Biais GRIB +12° ×1.15 (s'estompe)"
    assert bt(state="gelé (Jabuka)") == "Biais GRIB +12° ×1.15 (gelé, Jabuka)"
    assert bt(enabled=False) == "Biais GRIB désactivé"
    assert bt(valid=False, dir_deg=None, ratio=None, state="apprentissage") == (
        "Biais GRIB : apprentissage"
    )
    assert bt(valid=False, dir_deg=None, ratio=None, state="aucun") is None
    assert js("biasText(null)") is None
    bias = {"valid": True, "state": "actif", "dir_deg": 12.3, "ratio": 1.152}
    band = js(f"routeBand({json.dumps(nav(route(bias=bias)))})")
    assert band["lines"]["bias"] == "Biais GRIB +12° ×1.15"


def test_stay_status_line() -> None:
    on = route(kind="stay", stay={"active": True, "tack": "stbd"})
    assert js(f"routeBand({json.dumps(nav(on))})")["lines"]["status"] == "On reste (tribord)"
    both = route(off_route=True, level="L3")
    assert js(f"routeBand({json.dumps(nav(both))})")["lines"]["status"] == (
        "Hors route · Route : niveau L3"
    )


def test_no_inner_html() -> None:
    for name in ("route.js", "route_logic.js"):
        p = STATIC / name
        lines = [ln for ln in p.read_text().splitlines() if not ln.strip().startswith("//")]
        assert "innerHTML" not in "\n".join(lines), name


def test_route_modules_parse(tmp_path: Path) -> None:
    for name in ("route.js", "route_logic.js"):
        copy = tmp_path / (Path(name).stem + ".mjs")
        copy.write_text((STATIC / name).read_text())
        proc = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True)
        assert proc.returncode == 0, (name, proc.stderr)
