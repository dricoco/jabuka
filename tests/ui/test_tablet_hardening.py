"""Tablet hardening for spray, night and wet fingers (04-12) in a real browser:

- G-4-R09: the primary label (what the big number is) is glanceable: at least 20 px, in the
  number's colour, and floored at rgb(110, 0, 0) at the lowest night brightness.
- G-4-R10: Diag never flashes white at night. The iframe background is black, diag.html carries
  html.theme-night from its first paint (classic diag-theme.js in <head>), every visible element
  of the frame is black, pure red or transparent, and a theme switch reaches the loaded frame.
- G-4-R11: the helm surfaces refuse text selection, the long-press callout and pull-to-refresh,
  while the form inputs keep text selection.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import jabuka
from jabuka.nav import geo

STATIC = Path(jabuka.__file__).resolve().parent / "web" / "static"
PLIC_SESTRE = (43.684627, 15.811626)

# every visible element of the Diag document: colour, background, borders and outline are black,
# pure red or transparent (same rule as tests/ui/test_night.py COLORS_JS)
FRAME_COLORS_JS = """() => {
  const ok = (c) => {
    const skip = ["none", "auto", "transparent", "currentcolor"];
    if (!c || skip.includes(c)) return true;
    const m = /^rgba?\\(([^)]+)\\)$/.exec(c);
    if (!m) return false;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);
    return p[1] === 0 && p[2] === 0;
  };
  const props = ["color", "backgroundColor", "borderTopColor", "borderRightColor",
    "borderBottomColor", "borderLeftColor", "outlineColor"];
  const bad = [];
  let checked = 0;
  for (const el of document.querySelectorAll("html, body, body *")) {
    if (el.tagName !== "HTML" && !el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") continue;
    checked += 1;
    for (const p of props) {
      if (!ok(cs[p])) bad.push(`${el.tagName}#${el.id}.${el.className} ${p}=${cs[p]}`);
    }
  }
  return {bad, checked, body: getComputedStyle(document.body).backgroundColor,
          night: document.documentElement.classList.contains("theme-night")};
}"""

USER_SELECT_JS = """(sel) => {
  const cs = getComputedStyle(document.querySelector(sel));
  return cs.userSelect || cs.webkitUserSelect;
}"""


def _near_plic_sestre(feeder) -> None:
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon, twd=161.0, tws_kn=12.0, twa=45.0, bsp_kn=6.0)
    feeder.wait_nav(lambda n: n["wind"]["source"] == "LIVE" and n["layline"] is not None)


def _helm_ready(pg) -> None:
    pg.wait_for_function(
        "() => { const t = document.getElementById('primary').textContent; "
        "return t && t !== '—'; }",
        timeout=15000,
    )


def _diag_frame(pg):
    for _ in range(100):
        for fr in pg.frames:
            if fr.url.endswith("/diag.html"):
                fr.wait_for_load_state("load")
                return fr
        pg.wait_for_timeout(100)
    raise AssertionError([fr.url for fr in pg.frames])


def test_primary_label_is_glanceable(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _helm_ready(pg)
    label = pg.evaluate(
        "() => { const l = getComputedStyle(document.getElementById('primary-label'));"
        " const p = getComputedStyle(document.getElementById('primary'));"
        " return {size: parseFloat(l.fontSize), color: l.color, primary: p.color}; }"
    )
    assert label["size"] >= 20, label
    assert label["color"] == label["primary"], label

    pg.click("#night-toggle")
    pg.locator("#night-brightness").fill("40")
    assert pg.evaluate(
        "() => getComputedStyle(document.getElementById('primary-label')).color"
    ) == ("rgb(110, 0, 0)")
    assert page.external_requests == []


def test_diag_follows_the_night_theme_without_a_white_flash(page, feeder) -> None:
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_selector("#night-toggle")
    pg.click("#night-toggle")
    pg.click("button[data-tab=diag]")
    assert pg.evaluate(
        "() => getComputedStyle(document.getElementById('diag-frame')).backgroundColor"
    ) == ("rgb(0, 0, 0)")
    frame = _diag_frame(pg)
    frame.wait_for_function("() => document.documentElement.classList.contains('theme-night')")
    frame.wait_for_function("() => document.querySelectorAll('#values-body tr').length > 0")
    res = frame.evaluate(FRAME_COLORS_JS)
    assert res["night"] is True
    assert res["checked"] > 10, res
    assert res["body"] == "rgb(0, 0, 0)"
    assert res["bad"] == [], res["bad"][:10]

    # back to day while Diag stays loaded: the frame follows without a reload
    pg.click("#night-toggle")
    frame.wait_for_function(
        "() => !document.documentElement.classList.contains('theme-night')", timeout=3000
    )
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


def test_diag_theme_script_runs_before_the_module(page, feeder) -> None:
    html = (STATIC / "diag.html").read_text()
    head = html[: html.index("</head>")]
    tags = re.findall(r"<script\b[^>]*>", head)
    theme = [t for t in tags if "diag-theme.js" in t]
    module = [t for t in tags if "diag.js" in t and "diag-theme.js" not in t]
    assert len(theme) == 1 and len(module) == 1, tags
    assert "module" not in theme[0], theme[0]
    assert head.index("diag-theme.js") < head.index('src="diag.js"')
    assert head.index("diag.css") < head.index("diag-theme.js")

    pg = page.page
    pg.goto(page.base_url + "/")
    pg.evaluate("() => localStorage.setItem('jabuka.theme', 'night')")
    pg.goto(page.base_url + "/diag.html")
    assert pg.evaluate("() => document.documentElement.classList.contains('theme-night')")
    assert pg.evaluate("() => getComputedStyle(document.body).backgroundColor") == "rgb(0, 0, 0)"
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


def test_helm_surfaces_refuse_selection_and_pull_to_refresh(page, feeder) -> None:
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_selector("#map-ctrls", state="attached", timeout=30000)
    for sel in ("#helm-col", "#topbar", "#map-ctrls"):
        assert pg.evaluate(USER_SELECT_JS, sel) == "none", sel
    for sel in ("html", "body"):
        assert (
            pg.evaluate(
                f"() => getComputedStyle(document.querySelector('{sel}')).overscrollBehaviorY"
            )
            == "none"
        ), sel

    pg.click("button[data-tab=reglages]")
    pg.wait_for_selector("#manual-wind-form input[name=twd]")
    assert pg.evaluate(USER_SELECT_JS, "#manual-wind-form input[name=twd]") != "none"

    # Chromium desktop does not expose -webkit-touch-callout in the computed style: static check
    css = (STATIC / "app.css").read_text()
    rules = [
        body
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if all(s in sel for s in ("#helm-col", "#topbar", ".map-ctrls"))
    ]
    assert any("-webkit-touch-callout: none" in body for body in rules), rules
    assert page.external_requests == []
