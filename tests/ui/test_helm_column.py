"""The Barre tab as a left column (quick 002) in a real browser against a real core that routes.

Landscape (1280x800, 1024x600):
- #helm-col takes the left third and the map shows on the right two thirds.
- Blocks 1 (steer) and 2 (route/tack) are fully on screen and inside the column, in fr, en and
  sl, with long values forced (3-digit heading with °M, 178° plus the tack word, the longest
  countdown, status, bias and button label).
- ON RESTE sits in block 2 and nothing covers it.
- The map padding matches the column.

Portrait (800x1280): one top area (block 1 across the full width, blocks 2 and 3 side by side),
with the map below it and the padding on top.

Night: every visible element of the column and of the map buttons is black, pure red or
transparent.

The race pack, fake gpsd and feeder are those of test_route_ui.py (loaded from its file: the
tests are not a package). With JABUKA_SCREENS=<dir>, screenshots are saved there (day and night,
fr and sl).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_jabuka_route_ui", Path(__file__).with_name("test_route_ui.py")
)
assert _spec is not None and _spec.loader is not None
_route_ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_route_ui)

# the 03-06 fixtures: land mask + uniform wind in the race pack, --clock gps on a fake gpsd,
# instruments from the feeder
racepack_extra = _route_ui.racepack_extra
gpsd_feed = _route_ui.gpsd_feed
core_extra_args = _route_ui.core_extra_args
feeder = _route_ui.feeder
_routed = _route_ui._routed
_unexpected = _route_ui._unexpected

LANDSCAPE = ((1280, 800), (1024, 600))
PORTRAIT = (800, 1280)
SCREENS = os.environ.get("JABUKA_SCREENS")
CUE_WORD = {"fr": "EMPANNEZ", "en": "GYBE", "sl": "KRIŽAJ"}
NIGHT_VARIANTS = ("cue", "stale")

# The latest live nav message with long values forced in, rendered synchronously by every module
# listening on the bus. The next live message (within 1 s) puts the real values back.
LONG_NAV_JS = """(variant) => {
  const nav = JSON.parse(JSON.stringify(window.jabuka.lastNav));
  nav.display = {...(nav.display || {}), heading_ref: "M", variation: 0};
  const r = nav.route;
  Object.assign(r, {countdown_s: 7000, tack_kind: "gybe", cost_text: "+120 min", age_s: 7000,
    off_route: true, level: "L2", stale: true, last_fail: "délai dépassé",
    stay: {...(r.stay || {}), active: true, tack: "stbd"},
    bias: {enabled: true, valid: true, dir_deg: -12, ratio: 1.15, state: "gelé (Jabuka)"},
    wrong_tack: false});
  if (variant === "hdg") {
    Object.assign(r, {primary: "hdg", target: 358.4, target_twa: -178, target_tack: "stbd"});
  } else if (variant === "cue" || variant === "stale") {
    // G-4-R03: a due gybe takes over the primary box (EMPANNEZ / GYBE / KRIŽAJ + the tack)
    Object.assign(r, {primary: "twa", target: -178, target_twa: -178, target_tack: "stbd",
      countdown_s: -10, tack_kind: "gybe", wrong_tack: false, updating: false});
    // G-4-R01: the same due gybe on stale manual wind reads VENT PÉRIMÉ, dimmed, no cue
    if (variant === "stale") {
      nav.wind = {...(nav.wind || {}), source: "MANUEL", stale: true, manual_age_s: 3600};
    }
  } else {
    Object.assign(r, {primary: "twa", target: -178, target_tack: "stbd", target_hdg_t: 358.4});
  }
  nav.mark = {...(nav.mark || {}), name: "Blitvenica (n° 3)", dtw_nm: 12.3, ttw_s: 7300,
              btw_t: 358};
  nav.boat = {...nav.boat, bsp_kn: 10.5};
  nav.polar = {...(nav.polar || {}), target_bsp_kn: 10.8, pct: 103};
  window.jabuka.bus.dispatchEvent(new CustomEvent("nav", {detail: nav}));
  return document.getElementById("primary").textContent
    + document.getElementById("primary-unit").textContent;
}"""

# Geometry of the column, its blocks, the button and the map padding.
LAYOUT_JS = """() => {
  const W = window.innerWidth, H = window.innerHeight, bad = [];
  const rect = (id) => document.getElementById(id).getBoundingClientRect();
  const col = rect("helm-col"), bar = rect("topbar");
  for (const id of ["helm-steer", "helm-route"]) {
    const b = document.getElementById(id), r = b.getBoundingClientRect();
    if (r.top < bar.bottom - 1 || r.bottom > H + 1 || r.left < -1 || r.right > W + 1)
      bad.push(`${id} off screen [${r.left}, ${r.top}, ${r.right}, ${r.bottom}]`);
    if (r.left < col.left - 1 || r.right > col.right + 1 || r.bottom > col.bottom + 1)
      bad.push(`${id} outside the column`);
    if (b.scrollWidth > b.clientWidth + 1) bad.push(`${id} scrolls sideways ${b.scrollWidth}`);
    if (b.scrollHeight > b.clientHeight + 1) bad.push(`${id} clipped ${b.scrollHeight}`);
    for (const el of b.querySelectorAll("*")) {
      const e = el.getBoundingClientRect();
      if (!e.width || !e.height) continue;
      const name = el.id || el.className || el.tagName;
      const box = (q) => [q.left, q.right, q.bottom].map(Math.round).join(", ");
      if (e.left < r.left - 1 || e.right > r.right + 1 || e.bottom > r.bottom + 1)
        bad.push(`${name} [${box(e)}] outside ${id} [${box(r)}]`);
      if (el.clientWidth && el.scrollWidth > el.clientWidth + 1) bad.push(`${name} overflows`);
    }
  }
  if (document.documentElement.scrollWidth > W + 1) bad.push("page scrolls sideways");
  const stay = rect("stay-button"), route = rect("helm-route");
  const hit = document.elementFromPoint(stay.left + stay.width / 2, stay.top + stay.height / 2);
  const m = window.jabuka.map;
  const p = rect("primary"), u = rect("primary-unit");
  const cue = document.querySelector("#helm-steer .primary-box").classList.contains("cue");
  return {W, H, bad, cue, col: [col.left, col.top, col.right, col.bottom], barBottom: bar.bottom,
    primaryH: p.height, primaryRight: Math.max(p.right, u.right),
    stayInRoute: stay.top >= route.top - 1 && stay.bottom <= route.bottom + 1
      && stay.left >= route.left - 1 && stay.right <= route.right + 1,
    stayH: stay.height, stayW: stay.width, routeW: route.width,
    stayHit: hit && hit.id === "stay-button",
    pad: m.getPadding(), mapW: m.getContainer().clientWidth, mapH: m.getContainer().clientHeight};
}"""

# every visible element of the column and of the map buttons: black, pure red or transparent
NIGHT_JS = """() => {
  const ok = (c) => {
    const skip = ["none", "auto", "transparent", "currentcolor"];
    if (!c || skip.includes(c)) return true;
    const m = /^rgba?\\(([^)]+)\\)$/.exec(c);
    if (!m) return false;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);
    return p[1] === 0 && p[2] === 0;
  };
  const props = ["color", "backgroundColor", "borderTopColor", "borderRightColor",
    "borderBottomColor", "borderLeftColor", "outlineColor", "fill", "stroke"];
  const bad = [];
  let checked = 0;
  for (const el of document.querySelectorAll("#helm-col, #helm-col *, #map-ctrls, #map-ctrls *")) {
    if (!el.getClientRects().length) continue;
    checked += 1;
    const cs = getComputedStyle(el);
    for (const p of props) if (!ok(cs[p])) bad.push(`${el.id || el.className} ${p}=${cs[p]}`);
  }
  const colBg = getComputedStyle(document.getElementById("helm-col")).backgroundColor;
  return {bad, checked, colBg};
}"""

READY_JS = """() => {
  const b = document.getElementById('stay-button');
  const p = document.getElementById('primary').textContent;
  return window.jabuka && window.jabuka.map && window.jabuka.lastNav && b && !b.disabled
    && p && p !== '—';
}"""

# the padding helm.js asked for has reached the map
PAD_JS = """(landscape) => {
  const m = window.jabuka && window.jabuka.map;
  if (!m) return false;
  const col = document.getElementById("helm-col").getBoundingClientRect();
  const bar = document.getElementById("topbar").getBoundingClientRect();
  const p = m.getPadding();
  if (landscape) return Math.abs(p.left - col.right) <= 1 && Math.abs(p.top - bar.bottom) <= 1;
  return Math.abs(p.top - col.bottom) <= 1 && p.left === 0;
}"""


def _lang(pg, base_url: str, lang: str) -> None:
    if not pg.url.startswith(base_url):
        pg.goto(base_url + "/")
    pg.evaluate(f"() => localStorage.setItem('jabuka.lang', {lang!r})")
    pg.goto(base_url + "/")
    pg.wait_for_function(READY_JS, timeout=30000)
    assert pg.evaluate("() => document.documentElement.lang") == lang


def _size(pg, w: int, h: int) -> None:
    pg.set_viewport_size({"width": w, "height": h})
    pg.wait_for_function(PAD_JS, arg=w >= h, timeout=5000)
    pg.wait_for_timeout(200)


def _shot(pg, name: str) -> None:
    if SCREENS:
        Path(SCREENS).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(Path(SCREENS) / f"{name}.png"))


def _check_landscape(res: dict, w: int, h: int, where: str) -> None:
    left, top, right, bottom = res["col"]
    assert left <= 1 and abs(top - res["barBottom"]) <= 1 and bottom >= h - 1, (where, res)
    assert 0.30 <= right / w <= 0.36, (where, right / w)  # about a third, 300 px at least
    assert right >= 299, (where, right)
    visible = (w - right) / w  # the map's visible width
    assert 0.64 <= visible <= 0.70, (where, visible)
    assert abs(res["pad"]["left"] - right) <= 1, (where, res["pad"])
    assert abs(res["pad"]["top"] - res["barBottom"]) <= 1, (where, res["pad"])
    assert res["pad"]["right"] == 0 and res["pad"]["bottom"] == 0, (where, res["pad"])
    assert res["primaryRight"] <= right + 1, (where, res)


def _check_common(res: dict, where: str) -> None:
    assert res["bad"] == [], (where, res["bad"])
    # HELM-02's 20 % is about the number; the VIREZ/EMPANNEZ cue word is sized to the column
    if not res["cue"]:
        assert res["primaryH"] >= 0.2 * res["H"], (where, res["primaryH"], res["H"])  # HELM-02
    assert res["stayInRoute"] and res["stayHit"], (where, res)
    assert res["stayH"] >= 64 and res["stayW"] >= res["routeW"] - 2 * 10 - 2, (where, res)


def test_column_layout_fits_in_every_language(page, feeder) -> None:
    _routed(feeder)
    pg = page.page
    for lang in ("fr", "en", "sl"):
        _lang(pg, page.base_url, lang)
        for w, h in LANDSCAPE:
            _size(pg, w, h)
            where = f"{lang} {w}x{h}"
            res = pg.evaluate(LAYOUT_JS)
            _check_landscape(res, w, h, where)
            _check_common(res, where)
            if lang in ("fr", "sl"):
                _shot(pg, f"{lang}-day-{w}x{h}")
            for variant in ("hdg", "twa", "cue"):
                shown = pg.evaluate(LONG_NAV_JS, variant)
                want = {"hdg": "358°", "twa": "178°", "cue": CUE_WORD[lang]}[variant]
                assert shown.startswith(want), shown
                res = pg.evaluate(LAYOUT_JS)
                _check_landscape(res, w, h, f"{where} long {variant}")
                _check_common(res, f"{where} long {variant}")
                if variant == "cue":
                    assert res["cue"] is True, (where, res)
        w, h = PORTRAIT
        _size(pg, w, h)
        pg.wait_for_timeout(1200)  # the live values back after the forced ones
        where = f"{lang} {w}x{h}"
        if lang in ("fr", "sl"):
            _shot(pg, f"{lang}-day-{w}x{h}")
        for variant in (None, "hdg", "twa", "cue"):
            if variant:
                shown = pg.evaluate(LONG_NAV_JS, variant)
                if variant == "cue":
                    assert shown.startswith(CUE_WORD[lang]), shown
            res = pg.evaluate(LAYOUT_JS)
            _check_common(res, f"{where} {variant}")
            if variant == "cue":
                assert res["cue"] is True, (where, res)
            left, top, right, bottom = res["col"]
            # one top area across the width, the map below it, the padding on top
            assert left <= 1 and right >= w - 1 and abs(top - res["barBottom"]) <= 1, res
            # live values: > 38% of the height is map (the old bands left a ~30% strip); every
            # long value at once (a 4-line status, the countdown on 2 lines) still leaves > 28%
            assert (h - bottom) / h >= (0.38 if variant is None else 0.28), (where, variant, bottom)
            if variant is None:
                assert abs(res["pad"]["top"] - bottom) <= 1 and res["pad"]["left"] == 0, res["pad"]
            else:  # a taller top area moves the padding on the next frame (ResizeObserver)
                pg.wait_for_function(PAD_JS, arg=False, timeout=3000)
    assert page.external_requests == []
    assert _unexpected(page.bad_responses) == [], page.bad_responses


def test_on_reste_in_block_two_padding_per_tab_and_night(page, feeder) -> None:
    _routed(feeder)
    pg = page.page
    _lang(pg, page.base_url, "fr")
    _size(pg, 1024, 600)
    route = pg.locator("#helm-route")
    assert route.locator("#stay-button").count() == 1  # ON RESTE lives in block 2
    assert route.locator("#helm-countdown").count() == 1
    assert route.locator("#route-cost").count() == 1
    order = pg.evaluate(
        "() => [...document.querySelectorAll('#helm-route [id]')].map((e) => e.id)"
        ".filter((id) => ['helm-countdown', 'route-cost', 'route-status', 'route-age',"
        " 'route-target', 'route-bias', 'stay-button'].includes(id))"
    )
    assert order == [
        "helm-countdown",
        "route-cost",
        "route-status",
        "route-age",
        "route-target",
        "route-bias",
        "stay-button",
    ], order
    # one item per line: the age, target and bias lines are stacked, not side by side
    tops = pg.evaluate(
        "() => ['route-age', 'route-target', 'route-bias'].map((id) =>"
        " document.getElementById(id)).filter((e) => e.getClientRects().length)"
        ".map((e) => e.getBoundingClientRect().top)"
    )
    assert len(tops) >= 2 and tops == sorted(tops) and len(set(tops)) == len(tops), tops
    # a real tap holds the tack, a second one cancels it
    pg.click("#stay-button")
    pg.wait_for_function(
        "() => document.getElementById('stay-button').textContent.trim() === 'ANNULER ON RESTE'",
        timeout=20000,
    )
    pg.click("#stay-button")
    pg.wait_for_function(
        "() => document.getElementById('stay-button').textContent.trim() === 'ON RESTE'",
        timeout=20000,
    )

    # the padding is for Barre only; it comes back with the tab
    pg.click('#topbar [data-tab="carte"]')
    pg.wait_for_function(
        "() => { const p = window.jabuka.map.getPadding();"
        " return p.left === 0 && p.top === 0 && p.right === 0 && p.bottom === 0; }",
        timeout=3000,
    )
    pg.click('#topbar [data-tab="barre"]')
    pg.wait_for_function(PAD_JS, arg=True, timeout=3000)

    # map buttons over the map, right edge, clear of the column
    ctrls = pg.locator("#map-ctrls").bounding_box()
    col = pg.locator("#helm-col").bounding_box()
    assert ctrls and col and ctrls["x"] > col["x"] + col["width"], (ctrls, col)
    assert ctrls["x"] + ctrls["width"] >= 1024 - 16 and ctrls["y"] + ctrls["height"] <= 600

    # day: an opaque column, the map never ghosts behind the helm numbers
    col_bg = pg.evaluate(
        "() => getComputedStyle(document.getElementById('helm-col')).backgroundColor"
    )
    assert col_bg in ("rgb(255, 255, 255)", "rgba(255, 255, 255, 1)"), col_bg

    # night: red on black only, the column background included
    pg.click("#night-toggle")
    pg.wait_for_function("() => document.body.classList.contains('theme-night')")
    pg.wait_for_function("() => window.jabuka.map.getStyle().name.includes('night')")
    for lang in ("fr", "sl"):
        if lang != "fr":
            _lang(pg, page.base_url, lang)
        for w, h in (*LANDSCAPE, PORTRAIT):
            _size(pg, w, h)
            res = pg.evaluate(NIGHT_JS)
            assert res["checked"] >= 20, res
            assert res["bad"] == [], (lang, w, h, res["bad"])
            assert res["colBg"] in ("rgb(0, 0, 0)", "rgba(0, 0, 0, 1)"), res["colBg"]
            _shot(pg, f"{lang}-night-{w}x{h}")
            # the takeovers stay red on black (G-4-R03 cue box, G-4-R01 stale wind)
            for variant in NIGHT_VARIANTS:
                pg.evaluate(LONG_NAV_JS, variant)
                res = pg.evaluate(NIGHT_JS)
                assert res["bad"] == [], (lang, w, h, variant, res["bad"])
                _shot(pg, f"{lang}-night-{variant}-{w}x{h}")
    assert page.external_requests == []
    assert _unexpected(page.bad_responses) == [], page.bad_responses
