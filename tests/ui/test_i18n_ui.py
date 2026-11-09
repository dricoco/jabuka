"""Tablet language switch in a real browser (quick 001): Réglages FR / EN / SL changes the helm,
the tabs, the badges and the lock texts, the choice is kept on this device across reloads, the
lock and night mode keep working, and the longer Slovenian words do not push the helm blocks out
of the screen or out of the helm column (quick 002) at the tablet sizes of test_helm.py (1280x800
and 1024x600 landscape, 800x1280 portrait)."""

from __future__ import annotations

import math
import re

from jabuka.nav import geo

PLIC_SESTRE = (43.684627, 15.811626)

# every visible element of the helm blocks inside the viewport and inside its block, no block
# scrolling sideways, blocks 1 and 2 fully on screen, the big number >= 20% of the height (as in
# test_helm.py)
FIT_JS = """() => {
  const vw = window.innerWidth, vh = window.innerHeight, out = [];
  for (const id of ["helm-steer", "helm-route", "helm-rest"]) {
    const block = document.getElementById(id), b = block.getBoundingClientRect();
    if (block.scrollWidth > block.clientWidth + 1) out.push(`${id} scrolls ${block.scrollWidth}`);
    if (id !== "helm-rest" && b.bottom > vh + 1) out.push(`${id} below the screen ${b.bottom}`);
    for (const el of block.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.right > Math.min(vw, b.right) + 1 || r.left < Math.max(0, b.left) - 1) {
        const name = el.id || el.className || el.tagName;
        out.push(`${name} [${Math.round(r.left)}, ${Math.round(r.right)}]`);
      }
    }
  }
  if (document.documentElement.scrollWidth > vw + 1) out.push("page scrolls sideways");
  const p = document.getElementById("primary").getBoundingClientRect();
  return {bad: out, primaryH: p.height, innerH: window.innerHeight};
}"""


def _near_plic_sestre(feeder) -> None:
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon, twd=161.0, tws_kn=12.0, twa=45.0, bsp_kn=6.0)
    feeder.wait_nav(lambda n: n["wind"]["source"] == "LIVE" and n["layline"] is not None)


def _text(pg, selector: str) -> str:
    return pg.locator(selector).inner_text().strip()


def _wait_text(pg, element_id: str, prefix: str, timeout: int = 15000) -> None:
    js = f"(document.getElementById({element_id!r})?.textContent ?? '').startsWith({prefix!r})"
    pg.wait_for_function(f"() => {js}", timeout=timeout)


def _switch(pg, lang: str, tab_label: str) -> None:
    """Réglages -> language button -> the page reloads back on Réglages, in that language."""
    pg.click("button[data-tab=reglages]")
    pg.wait_for_selector(f"#lang-select button[data-lang={lang}]")
    with pg.expect_navigation():
        pg.click(f"#lang-select button[data-lang={lang}]")
    pg.wait_for_function(
        f"() => document.querySelector('button[data-tab=reglages]').textContent === {tab_label!r}"
    )
    assert pg.locator("#tab-reglages").is_visible()  # back on the tab that was open
    assert pg.evaluate("() => localStorage.getItem('jabuka.lang')") == lang
    assert pg.evaluate("() => document.documentElement.lang") == lang
    pressed = pg.locator(f"#lang-select button[data-lang={lang}]").get_attribute("aria-pressed")
    assert pressed == "true"


def _hold(pg, ms: int) -> None:
    box = pg.locator("#unlock-btn").bounding_box()
    assert box is not None
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down()
    pg.wait_for_timeout(ms)
    pg.mouse.up()


def _fits(pg) -> None:
    for w, h in ((1280, 800), (1024, 600), (800, 1280)):
        pg.set_viewport_size({"width": w, "height": h})
        pg.wait_for_timeout(400)
        res = pg.evaluate(FIT_JS)
        assert res["bad"] == [], (w, h, res["bad"])
        assert res["primaryH"] >= 0.2 * res["innerH"], (w, h, res)
    pg.set_viewport_size({"width": 1280, "height": 800})


def test_switch_to_slovenian_then_english_persists_and_fits(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _wait_text(pg, "helm-countdown", "Virement dans")
    assert _text(pg, "button[data-tab=barre]") == "Barre"  # French by default
    assert _text(pg, "#primary-label") == "TWA CIBLE ↑"

    # -- Slovenian ------------------------------------------------------------------------------
    _switch(pg, "sl", "Nastavitve")
    assert "Ročni veter" in _text(pg, "#tab-reglages")
    assert pg.locator("#settings-form").inner_text().count("Izkoristek polare") == 1
    pg.click("button[data-tab=barre]")
    _wait_text(pg, "primary-label", "CILJNI TWA")
    _wait_text(pg, "helm-countdown", "Obrat čez")
    assert _text(pg, "button[data-tab=carte]") == "Karta"
    assert pg.evaluate("() => document.title") == "Jabuka — Krmilo"
    bottom = _text(pg, "#helm-rest")
    assert re.search(r"\d,\d / \d,\d kn", bottom), bottom  # decimal comma, knots as "kn"
    assert "Po obratu" in bottom and "Plić Sestre" in bottom
    assert _text(pg, "#map-centre") == "Centriraj"
    _fits(pg)

    # kept on this device across a reload
    pg.reload()
    _wait_text(pg, "helm-countdown", "Obrat čez")
    assert _text(pg, "button[data-tab=barre]") == "Krmilo"

    # night mode and the lock still work, in Slovenian
    assert _text(pg, "#night-toggle") == "☾ Noč"
    pg.click("#night-toggle")
    pg.wait_for_function("() => document.body.classList.contains('theme-night')")
    assert _text(pg, "#night-toggle") == "Dan"
    pg.click("#lock-btn")
    assert pg.locator("#lock-overlay").is_visible()
    assert _text(pg, "#lock-overlay .lock-hint") == "ZAKLENJENO · pridrži 2 s, nato spusti"
    assert pg.locator("#lock-btn").get_attribute("aria-label") == "Zakleni zaslon"
    pg.reload()  # still locked after the reload, still in Slovenian, still at night
    _wait_text(pg, "helm-countdown", "Obrat čez")
    assert pg.locator("#lock-overlay").is_visible()
    assert pg.evaluate("() => document.body.classList.contains('theme-night')")
    pg.wait_for_selector("#unlock-btn")
    _hold(pg, 2400)
    pg.wait_for_function("() => document.getElementById('lock-overlay').hidden")
    pg.click("#night-toggle")
    pg.wait_for_function("() => document.body.classList.contains('theme-day')")

    # -- English --------------------------------------------------------------------------------
    _switch(pg, "en", "Settings")
    pg.click("button[data-tab=barre]")
    _wait_text(pg, "primary-label", "TARGET TWA")
    _wait_text(pg, "helm-countdown", "Tack in")
    bottom = _text(pg, "#helm-rest")
    assert re.search(r"\d\.\d / \d\.\d kn", bottom), bottom  # decimal point in English
    assert _text(pg, "#helm-hint") in ("HEAD UP", "BEAR AWAY", "")
    assert "LIVE" in _text(pg, "#badges")
    _fits(pg)

    # the diagnostics page follows the device language
    pg.goto(page.base_url + "/diag.html")
    pg.wait_for_function("() => document.getElementById('conn').textContent === 'live'")
    assert _text(pg, "#event-btn") == "Event marker"

    # back to French
    pg.goto(page.base_url + "/")
    _switch(pg, "fr", "Réglages")
    pg.click("button[data-tab=barre]")
    _wait_text(pg, "helm-countdown", "Virement dans")
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses
