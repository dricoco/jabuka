"""The tablet page renders the offline map from vendored assets with laylines, the active mark and
the boat over it; no request leaves the core; the helm numbers survive a missing map (HELM-01)."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import jabuka
from jabuka.nav import geo

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
NODE = shutil.which("node")
PLIC_SESTRE = (43.684627, 15.811626)
IDLE_JS = """() => new Promise((resolve) => {
  const m = window.jabuka && window.jabuka.map;
  if (!m) return resolve(false);
  if (m.loaded() && m.areTilesLoaded()) return resolve(true);
  m.once("idle", () => resolve(true));
})"""
SOURCE_JS = """async (id) => {
  const s = window.jabuka.map.getSource(id);
  if (!s) return null;
  const data = typeof s.getData === "function" ? await s.getData() : s.serialize().data;
  return (data.features || []).map((f) => f.geometry.type);
}"""


def _near_plic_sestre(feeder) -> None:
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon, twd=161.0, tws_kn=12.0, twa=45.0, bsp_kn=6.0)
    feeder.wait_nav(lambda n: n["wind"]["source"] == "LIVE" and n["layline"] is not None)


# -- generated styles ---------------------------------------------------------------------------
def _colors(obj, out: list[str]) -> list[str]:
    if isinstance(obj, str):
        if re.match(r"^(#|rgb|hsl)", obj.strip(), re.I):
            out.append(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            _colors(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _colors(v, out)
    return out


def _pure_red_or_black(c: str) -> bool:
    c = c.lower().replace(" ", "")
    if re.fullmatch(r"#[0-9a-f]{2}0000", c) or c in ("#000", "#000000"):
        return True
    m = re.fullmatch(r"rgba?\((\d+),(\d+),(\d+)(,[\d.]+)?\)", c)
    return bool(m) and m.group(2) == "0" and m.group(3) == "0"


def test_styles_are_offline_and_night_is_red_only() -> None:
    for name in ("style-day.json", "style-night.json"):
        text = (STATIC / name).read_text()
        assert "http" not in text, name
        style = json.loads(text)
        assert style["glyphs"] == "/glyphs/{fontstack}/{range}.pbf"
        assert style["sources"]["protomaps"]["tiles"] == ["/tiles/{z}/{x}/{y}.mvt"]
        assert any(layer["id"] == "earth" for layer in style["layers"])
    night = json.loads((STATIC / "style-night.json").read_text())
    ids = {layer["id"] for layer in night["layers"]}
    assert not ids & {"roads_shields", "roads_oneway", "pois"}
    colors = []
    for layer in night["layers"]:
        _colors(layer.get("paint", {}), colors)
        _colors(layer.get("layout", {}), colors)
    assert colors, "night style has no colours?"
    bad = sorted({c for c in colors if not _pure_red_or_black(c)})
    assert bad == [], f"non-red colours in the night style: {bad[:10]}"
    for layer in night["layers"]:
        assert "icon-image" not in layer.get("layout", {}), layer["id"]


def test_vendored_assets_present() -> None:
    for rel in (
        "vendor/maplibre-gl.js",
        "vendor/maplibre-gl.css",
        "vendor/NoSleep.min.js",
        "vendor/VENDOR.md",
        "glyphs/Noto Sans Regular/0-255.pbf",
        "glyphs/Noto Sans Regular/256-511.pbf",
        "glyphs/Noto Sans Medium/256-511.pbf",
        "glyphs/Noto Sans Italic/8192-8447.pbf",
        "sprites/light.json",
        "sprites/light@2x.png",
        "sprites/dark.png",
    ):
        assert (STATIC / rel).is_file(), rel
    assert "5.24.0" in (STATIC / "vendor" / "VENDOR.md").read_text()


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_absolutize_style() -> None:
    style = {
        "glyphs": "/glyphs/{fontstack}/{range}.pbf",
        "sprite": "/sprites/light",
        "sources": {
            "protomaps": {"type": "vector", "tiles": ["/tiles/{z}/{x}/{y}.mvt"]},
            "ext": {"type": "vector", "tiles": ["http://other/{z}/{x}/{y}.mvt"]},
            "gj": {"type": "geojson", "data": {"type": "FeatureCollection", "features": []}},
        },
        "layers": [],
    }
    code = (
        f"import {{ absolutizeStyle }} from {json.dumps((STATIC / 'map.js').as_uri())};\n"
        f"const s = absolutizeStyle({json.dumps(style)}, 'http://h:1');\n"
        "process.stdout.write(JSON.stringify(s));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["glyphs"] == "http://h:1/glyphs/{fontstack}/{range}.pbf"
    assert out["sprite"] == "http://h:1/sprites/light"
    assert out["sources"]["protomaps"]["tiles"] == ["http://h:1/tiles/{z}/{x}/{y}.mvt"]
    assert out["sources"]["ext"]["tiles"] == ["http://other/{z}/{x}/{y}.mvt"]


def test_style_maxzoom_follows_a_degraded_pack() -> None:
    """WR-06: a race pack extracted at maxzoom 10 (prep fallback) overzooms z10 tiles instead
    of going blank above it: every vector source gets the pack's maxzoom."""
    style = json.loads((STATIC / "style-day.json").read_text())
    code = (
        f"import {{ fitStyleToPack }} from {json.dumps((STATIC / 'map.js').as_uri())};\n"
        f"const s = {json.dumps(style)};\n"
        "const out = [fitStyleToPack(structuredClone(s), {tiles: true, maxzoom: 10}),\n"
        "  fitStyleToPack(structuredClone(s), {tiles: true, maxzoom: null}),\n"
        "  fitStyleToPack(structuredClone(s), {tiles: false, maxzoom: 10})]\n"
        "  .map((st) => Object.values(st.sources).filter((x) => x.type === 'vector')\n"
        "  .map((x) => x.maxzoom));\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    degraded, unknown, no_tiles = json.loads(proc.stdout)
    assert degraded and set(degraded) == {10}
    assert set(unknown) == {14} and set(no_tiles) == {14}  # untouched


# -- browser -----------------------------------------------------------------------------------
def test_map_renders_offline_with_overlays(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    assert pg.evaluate(IDLE_JS) is True
    n_earth = pg.evaluate(
        "() => window.jabuka.map.querySourceFeatures('protomaps', {sourceLayer: 'earth'}).length"
    )
    assert n_earth > 0
    pg.wait_for_function(
        f"async () => {{ const t = await ({SOURCE_JS})('laylines'); return t && t.length === 2; }}",
        timeout=15000,
    )
    assert pg.evaluate(SOURCE_JS, "laylines") == ["LineString", "LineString"]
    assert pg.evaluate(SOURCE_JS, "mark") == ["Point"]
    assert pg.evaluate(SOURCE_JS, "boat") == ["Point"]
    pg.wait_for_function(
        "() => { const t = document.getElementById('primary').textContent; "
        "return t && t !== '—'; }",
        timeout=15000,
    )
    assert pg.locator("#primary").is_visible()
    pg.wait_for_timeout(1500)  # a few more ticks and tile loads
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses
    assert "CARTE INDISPONIBLE" not in pg.locator("#badges").inner_text()


def test_tabs_course_and_settings(page, feeder) -> None:
    """Only the active tab shows; Carte lists the course and switches A/B in one tap (CRSE-01);
    Réglages renders the schema form (modules mounted after the first events still get them)."""
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_function("() => document.getElementById('primary').textContent !== '—'")
    pg.click("button[data-tab=carte]")
    assert not pg.locator("#tab-barre").is_visible()
    pg.wait_for_function("() => document.querySelectorAll('#course-list li').length === 5")
    pg.wait_for_function(
        "() => document.querySelector('#course-list li.active .name')?.textContent "
        "=== 'Plić Sestre'"
    )
    assert pg.locator("#sides-warning").is_visible()
    # wait for each POST's own response: the list may already show the change through the
    # WebSocket refetch while the button's request is still in flight
    pg.click("button[data-template=B]")  # WR-05: first tap asks for confirmation
    with pg.expect_response(lambda r: r.url.endswith("/api/course/select")) as sel:
        pg.click("button[data-template=B]")
    assert sel.value.status == 200, sel.value.status
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#course-list .name')].map(e => e.textContent)"
        ".join(',') === 'Vodice,Plić Sestre,Jabuka,Mulo,Vodice'"
    )
    assert feeder.server.get("/api/course")["template"] == "B"
    with pg.expect_response(lambda r: r.url.endswith("/api/course/next")) as nxt:
        pg.click("#course-next")
    assert nxt.value.status == 200, nxt.value.status
    pg.wait_for_function(
        "() => document.querySelector('#course-list li.active .name')?.textContent === 'Jabuka'"
    )
    pg.click("button[data-tab=reglages]")
    pg.wait_for_function(
        "() => document.querySelectorAll('#settings-form .reglages-row').length > 10"
    )
    assert "Efficacité polaire" in pg.locator("#settings-form").inner_text()
    eff = pg.locator("#settings-form input[name=efficiency]")
    with pg.expect_response(
        lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT"
    ) as put:
        eff.fill("0.85")
        eff.dispatch_event("change")
    assert put.value.status == 200, (put.value.status, put.value.text())
    feeder.wait_nav(lambda n: n["polar"]["eff"] == 0.85)
    pg.click("button[data-tab=barre]")
    assert pg.locator("#tab-barre").is_visible()
    assert page.external_requests == [], page.external_requests
    assert page.bad_responses == [], page.bad_responses


def test_helm_survives_without_webgl(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.route(
        "**/vendor/maplibre-gl.js",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body="window.maplibregl = { supported: () => false };",
        ),
    )
    pg.goto(page.base_url + "/")
    pg.wait_for_function(
        "() => document.getElementById('badges').textContent.includes('CARTE INDISPONIBLE')",
        timeout=15000,
    )
    pg.wait_for_function(
        "() => { const t = document.getElementById('primary').textContent; "
        "return t && t !== '—'; }",
        timeout=15000,
    )
    assert page.external_requests == []
