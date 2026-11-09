"""Night mode end to end (HELM-03) and the helm overlays over the map (HELM-01): the toggle
persists per tablet, every visible colour is black or pure red, the overlays keep their data
across theme switches, the seamarks load, and the course overlay steps aside on the Carte tab."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import jabuka
from jabuka.nav import geo

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
PLIC_SESTRE = (43.684627, 15.811626)

IDLE_JS = """() => new Promise((resolve) => {
  const m = window.jabuka && window.jabuka.map;
  if (!m) return resolve(false);
  if (m.loaded() && !m.isMoving()) return resolve(true);
  m.once("idle", () => resolve(true));
})"""

SOURCE_JS = """async (id) => {
  const s = window.jabuka.map.getSource(id);
  if (!s) return null;
  const data = typeof s.getData === "function" ? await s.getData() : s.serialize().data;
  return (data.features || []).map((f) => ({type: f.geometry.type, props: f.properties || {},
    n: f.geometry.type === "LineString" ? f.geometry.coordinates.length : 1}));
}"""

# every visible element of the helm chrome and the MapLibre controls: colour, background,
# borders, outline, SVG paint and accent are black, pure red or transparent
COLORS_JS = """() => {
  const ok = (c) => {
    const skip = ["none", "auto", "transparent", "currentcolor"];
    if (!c || skip.includes(c)) return true;
    const m = /^rgba?\\(([^)]+)\\)$/.exec(c);
    if (!m) return false;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);
    return p[1] === 0 && p[2] === 0;
  };
  const sel = "#topbar, #topbar *, #badges *, #tab-barre, #tab-barre *, "
    + ".maplibregl-control-container *";
  const props = ["color", "backgroundColor", "borderTopColor", "borderRightColor",
    "borderBottomColor", "borderLeftColor", "outlineColor", "fill", "stroke", "accentColor"];
  const bad = [];
  let checked = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") continue;
    checked += 1;
    for (const p of props) {
      if (!ok(cs[p])) bad.push(`${el.tagName}#${el.id}.${el.className} ${p}=${cs[p]}`);
    }
  }
  return {bad, checked, body: getComputedStyle(document.body).backgroundColor,
          html: getComputedStyle(document.documentElement).backgroundColor};
}"""

BODY_PROPS_JS = """() => {
  const cs = getComputedStyle(document.body);
  return {dim: cs.getPropertyValue('--dim').trim(), line: cs.getPropertyValue('--line').trim(),
          mapK: cs.getPropertyValue('--map-k').trim()};
}"""

OVERLAY_COLORS_JS = """() => {
  const ids = ["helm-course", "helm-live", "seamarks"];
  const layers = window.jabuka.map.getStyle().layers
    .filter((l) => ids.includes((l.metadata || {})["jabuka:overlay"]));
  return layers.map((l) => ({id: l.id, overlay: l.metadata["jabuka:overlay"],
    paint: l.paint || {}, layout: l.layout || {}}));
}"""


def _near_plic_sestre(feeder) -> None:
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon, twd=161.0, tws_kn=12.0, twa=45.0, bsp_kn=6.0)
    feeder.wait_nav(lambda n: n["wind"]["source"] == "LIVE" and n["layline"] is not None)


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


def _wait_overlays(pg) -> None:
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    pg.wait_for_function(
        f"async () => {{ const t = await ({SOURCE_JS})('laylines'); return t && t.length === 2; }}",
        timeout=15000,
    )
    pg.wait_for_function(
        f"async () => {{ const t = await ({SOURCE_JS})('helm-course-marks'); "
        "return t && t.length >= 4; }",
        timeout=15000,
    )
    pg.wait_for_function(
        f"async () => {{ const t = await ({SOURCE_JS})('seamarks'); return t && t.length === 3; }}",
        timeout=15000,
    )


def _style_name(pg) -> str:
    return pg.evaluate("() => window.jabuka.map.getStyle().name")


def _assert_overlays_hold_data(pg, course: dict) -> None:
    lay = pg.evaluate(SOURCE_JS, "laylines")
    assert [f["type"] for f in lay] == ["LineString", "LineString"]
    line = pg.evaluate(SOURCE_JS, "helm-course-line")
    assert [f["type"] for f in line] == ["LineString"]
    assert line[0]["n"] == len(course["seq"])
    marks = pg.evaluate(SOURCE_JS, "helm-course-marks")
    ids = {leg["mark_id"] for leg in course["seq"]}
    assert {f["props"]["name"] for f in marks} == {course["marks"][i]["name"] for i in ids}
    radius = pg.evaluate(SOURCE_JS, "helm-course-radius")
    with_radius = [leg for leg in course["seq"] if leg["radius_nm"] > 0]
    assert len(radius) == len(with_radius) > 0
    assert all(f["type"] == "LineString" and f["n"] == 49 for f in radius)
    assert {f["props"]["side"] for f in radius} == {leg["side"] for leg in with_radius}
    assert [f["type"] for f in pg.evaluate(SOURCE_JS, "boat")] == ["Point"]
    heading = pg.evaluate(SOURCE_JS, "helm-heading")
    assert [f["type"] for f in heading] == ["LineString"]
    assert [f["type"] for f in pg.evaluate(SOURCE_JS, "mark")] == ["Point"]
    assert len(pg.evaluate(SOURCE_JS, "seamarks")) == 3


def test_night_style_file_has_no_icons_and_only_red() -> None:
    night = json.loads((STATIC / "style-night.json").read_text())
    colors: list[str] = []
    for layer in night["layers"]:
        assert "icon-image" not in layer.get("layout", {}), layer["id"]
        _colors(layer.get("paint", {}), colors)
        _colors(layer.get("layout", {}), colors)
    assert colors
    assert sorted({c for c in colors if not _pure_red_or_black(c)}) == []


def test_night_land_stands_out_from_the_sea() -> None:
    """Islands and coast must stay visible at night: the earth fill is the designed #260000, not
    the near-black #040000 a second red conversion produced (build-styles.mjs toRed twice)."""
    night = json.loads((STATIC / "style-night.json").read_text())
    paint = {layer["id"]: layer.get("paint", {}) for layer in night["layers"]}
    assert paint["water"]["fill-color"] == "#000000"
    assert paint["background"]["background-color"] == "#000000"
    earth = paint["earth"]["fill-color"]
    assert earth == "#260000"
    assert int(earth[1:3], 16) >= 0x20
    ids = [layer["id"] for layer in night["layers"]]
    coast = night["layers"][ids.index("earth_coastline")]
    assert ids.index("earth_coastline") == ids.index("earth") + 1
    assert coast["source-layer"] == "earth"
    assert coast["paint"]["line-color"] == "#600000"


def test_night_toggle_is_red_only_and_persists(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _wait_overlays(pg)
    assert pg.evaluate("() => document.body.classList.contains('theme-day')")
    toggle = pg.locator("#night-toggle")
    assert toggle.get_attribute("aria-label") == "Mode nuit"
    box = toggle.bounding_box()
    assert box and box["width"] >= 48 and box["height"] >= 48
    toggle.click()
    assert pg.evaluate("() => document.body.classList.contains('theme-night')")
    assert pg.evaluate("() => localStorage.getItem('jabuka.theme')") == "night"
    assert (
        pg.evaluate(
            "() => document.querySelector('meta[name=theme-color]').getAttribute('content')"
        )
        == "#000000"
    )
    pg.wait_for_function("() => window.jabuka.map.getStyle().name === 'jabuka-night'")
    assert pg.evaluate(IDLE_JS) is True
    assert pg.locator("#night-brightness").is_visible()

    # reload: the tablet remembers night mode, map included
    pg.reload()
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    assert pg.evaluate("() => document.body.classList.contains('theme-night')")
    assert _style_name(pg) == "jabuka-night"
    _wait_overlays(pg)
    pg.wait_for_function(
        "() => { const t = document.getElementById('primary').textContent; "
        "return t && t !== '—'; }",
        timeout=15000,
    )
    # open the compact attribution too: it is white by default
    pg.evaluate(
        "() => document.querySelector('.maplibregl-ctrl-attrib')?.classList"
        ".add('maplibregl-compact-show')"
    )
    res = pg.evaluate(COLORS_JS)
    assert res["checked"] > 20
    assert res["body"] == "rgb(0, 0, 0)"
    assert res["bad"] == [], res["bad"][:10]

    # dimmer: still pure red, just less of it; text never below rgb(110, 0, 0) (G-4-R09), while
    # the borders and the map still dim freely
    pg.locator("#night-brightness").fill("40")
    assert pg.evaluate("() => localStorage.getItem('jabuka.brightness')") == "0.4"
    assert pg.evaluate("() => getComputedStyle(document.getElementById('primary')).color") == (
        "rgb(110, 0, 0)"
    )
    assert pg.evaluate(BODY_PROPS_JS) == {
        "dim": "rgb(110, 0, 0)",
        "line": "rgb(26, 0, 0)",
        "mapK": "0.4",
    }
    assert pg.evaluate(COLORS_JS)["bad"] == []
    pg.locator("#night-brightness").fill("100")
    assert pg.evaluate(BODY_PROPS_JS)["dim"] == "rgb(128, 0, 0)"
    assert pg.evaluate("() => getComputedStyle(document.getElementById('primary')).color") == (
        "rgb(255, 0, 0)"
    )
    assert pg.evaluate(COLORS_JS)["bad"] == []

    # overlay layers at night: red shades only, labels from text-field, no sprite; the one icon
    # is the boat, drawn at runtime in red and black only (checked pixel by pixel)
    layers = pg.evaluate(OVERLAY_COLORS_JS)
    assert {lay["overlay"] for lay in layers} == {"helm-course", "helm-live", "seamarks"}
    colors: list[str] = []
    for lay in layers:
        _colors(lay["paint"], colors)
        icon = lay["layout"].get("icon-image")
        assert icon in (None, "jabuka-boat-night", "jabuka-heading-night"), lay["id"]
    for image in ("jabuka-boat-night", "jabuka-heading-night"):
        pg.wait_for_function(f"() => window.jabuka.map.hasImage('{image}')", timeout=15000)
        non_red = pg.evaluate(
            """(id) => { const d = window.jabuka.map.style.getImage(id).data.data;
              let bad = 0, red = 0;
              for (let i = 0; i < d.length; i += 4) {
                if (d[i + 3] === 0) continue;
                if (d[i + 1] !== 0 || d[i + 2] !== 0) bad++; else if (d[i] > 0) red++;
              }
              return {bad, red}; }""",
            image,
        )
        assert non_red["bad"] == 0 and non_red["red"] > 100, (image, non_red)
    assert colors
    assert sorted({c for c in colors if not _pure_red_or_black(c)}) == []
    labels = [lay for lay in layers if "text-field" in lay["layout"]]
    assert {lay["id"] for lay in labels} >= {"seamarks-label", "helm-mark-label"}
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


BOAT_JS = """() => {
  const m = window.jabuka.map;
  const ids = m.getStyle().layers.map((l) => l.id);
  const lay = m.getStyle().layers.find((l) => l.id === "helm-boat");
  return {tail: ids.slice(-3), type: lay && lay.type, image: lay && lay.layout["icon-image"],
          loaded: m.hasImage("jabuka-boat-day") || m.hasImage("jabuka-boat-night")};
}"""


def _assert_boat_icon_on_top(pg, theme: str) -> None:
    """The boat is a heading-rotated hull icon drawn above every overlay (route included), and
    its image is re-added after a day/night style switch."""
    pg.wait_for_function(f"() => window.jabuka.map.hasImage('jabuka-boat-{theme}')", timeout=15000)
    info = pg.evaluate(BOAT_JS)
    assert info["tail"] == ["helm-heading-ray", "helm-boat-dot", "helm-boat"]
    assert info["type"] == "symbol"
    assert info["image"] == f"jabuka-boat-{theme}"


def test_boat_icon_on_top_in_both_themes(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _wait_overlays(pg)
    _assert_boat_icon_on_top(pg, "day")
    pg.click("#night-toggle")
    pg.wait_for_function("() => window.jabuka.map.getStyle().name === 'jabuka-night'")
    _assert_boat_icon_on_top(pg, "night")
    assert page.external_requests == []


def test_overlays_survive_theme_switches_and_carte_tab(page, feeder) -> None:
    _near_plic_sestre(feeder)
    course = feeder.server.get("/api/course")
    pg = page.page
    pg.goto(page.base_url + "/")
    _wait_overlays(pg)
    _assert_overlays_hold_data(pg, course)
    for theme in ("night", "day"):
        pg.click("#night-toggle")
        pg.wait_for_function(f"() => window.jabuka.map.getStyle().name === 'jabuka-{theme}'")
        assert pg.evaluate(IDLE_JS) is True
        _assert_overlays_hold_data(pg, course)
    assert pg.evaluate("() => localStorage.getItem('jabuka.theme')") == "day"
    _assert_boat_icon_on_top(pg, "day")

    vis_js = """(overlay) => window.jabuka.map.getStyle().layers
      .filter((l) => (l.metadata || {})["jabuka:overlay"] === overlay)
      .map((l) => (l.layout || {}).visibility || "visible")"""
    pg.click("button[data-tab=carte]")
    pg.wait_for_function(f"() => ({vis_js})('helm-course').every((v) => v === 'none')")
    assert set(pg.evaluate(vis_js, "helm-live")) == {"visible"}
    assert set(pg.evaluate(vis_js, "seamarks")) == {"visible"}
    pg.click("button[data-tab=barre]")
    pg.wait_for_function(f"() => ({vis_js})('helm-course').every((v) => v === 'visible')")
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


SLOW_DAY_STYLE_JS = """() => {
  const f = window.fetch;
  window.fetch = (u, ...a) => String(u).includes("style-day.json")
    ? new Promise((r) => setTimeout(r, 1200)).then(() => f(u, ...a))
    : f(u, ...a);
}"""


def test_double_tap_night_toggle_never_leaves_the_day_map(page, feeder) -> None:
    """WR-04: at night a fast double tap (Jour, then Nuit) while the day style is still loading
    ends with the night UI AND the night map, never the bright day basemap under the night UI."""
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _wait_overlays(pg)
    pg.click("#night-toggle")
    pg.wait_for_function("() => window.jabuka.map.getStyle().name === 'jabuka-night'")
    pg.evaluate(SLOW_DAY_STYLE_JS)
    pg.evaluate(
        "() => { const b = document.getElementById('night-toggle'); b.click(); b.click(); }"
    )
    pg.wait_for_timeout(2500)  # the slow day style has arrived by now
    assert pg.evaluate("() => document.body.classList.contains('theme-night')")
    assert pg.evaluate("() => localStorage.getItem('jabuka.theme')") == "night"
    assert _style_name(pg) == "jabuka-night"
    # and a single tap still switches (the queue is not stuck)
    pg.click("#night-toggle")
    pg.wait_for_function("() => window.jabuka.map.getStyle().name === 'jabuka-day'", timeout=5000)
    assert page.bad_responses == [], page.bad_responses
