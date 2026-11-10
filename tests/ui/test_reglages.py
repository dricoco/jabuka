"""Réglages tab in a headless browser: with the bus silent, the "Vent manuel" form brings the
laylines back with source MANUEL (WIND-04); the schema-driven settings form saves a field."""

from __future__ import annotations

import math

from jabuka.nav import geo

PLIC_SESTRE = (43.684627, 15.811626)


def test_manual_wind_form_and_settings(page, feeder) -> None:
    # bus silent, GPS alive, boat 2 nm downwind of Plić Sestre for a 204.7°T wind
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(24.7), 2.0)
    feeder.boat.update(lat=lat, lon=lon, send_wind=False, send_gps=True)
    feeder.wait_nav(lambda n: n["wind"]["source"] == "NONE" and n["boat"]["lat"] is not None)

    pg = page.page
    pg.goto(page.base_url + "/")
    pg.click("button[data-tab=reglages]")
    pg.wait_for_selector("#manual-wind-form")
    pg.wait_for_function(
        "() => document.getElementById('manual-wind-source').textContent === 'PAS DE VENT'"
    )
    assert pg.locator("#manual-wind-form select[name=ref]").input_value() == "M"  # Pitfall 6

    # client-side check, nothing sent
    pg.fill("#manual-wind-form input[name=twd]", "400")
    pg.fill("#manual-wind-form input[name=tws_kn]", "12")
    pg.click("#manual-wind-form button[type=submit]")
    pg.wait_for_function(
        "() => document.getElementById('manual-wind-error').textContent.includes('TWD')"
    )
    assert feeder.server.get("/api/nav")["wind"]["source"] == "NONE"

    pg.fill("#manual-wind-form input[name=twd]", "200")
    pg.fill("#manual-wind-form input[name=tws_kn]", "12")
    with pg.expect_response(
        lambda r: r.url.endswith("/api/wind/manual") and r.request.method == "POST"
    ) as post:
        pg.click("#manual-wind-form button[type=submit]")
    assert post.value.status == 200, (post.value.status, post.value.text())
    nav = feeder.wait_nav(lambda n: n["wind"]["source"] == "MANUEL", timeout=3.0)
    assert nav["wind"]["twd_t"] == 204.7
    feeder.wait_nav(lambda n: n["layline"] is not None, timeout=3.0)
    pg.wait_for_function(
        "() => document.getElementById('manual-wind-source').dataset.source === 'MANUEL'"
    )
    assert pg.locator("#manual-wind-error").inner_text() == ""
    # the stored entry is re-read after the POST (async): wait for it
    pg.wait_for_function(
        "() => document.getElementById('manual-wind-stored').textContent.includes('200°M')"
    )
    # the source badge in the top bar says so too, with the entry's age (02-05 sourceBadge:
    # "MANUEL 0 min"; "MANUEL âge ?" when the core has no trusted UTC, as here with
    # --clock system, WR-03)
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#badges .badge[data-badge=wind]')].some(b => "
        "/^MANUEL( \\d+ min| âge \\?)$/.test(b.textContent))"
    )

    # settings form: one field saved, version bumped
    before = feeder.server.get("/api/settings")
    pg.wait_for_function(
        "() => document.querySelectorAll('#settings-form .reglages-row').length > 10"
    )
    eff = pg.locator("#settings-form input[name=efficiency]")
    with pg.expect_response(
        lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT"
    ) as put:
        eff.fill("0.9")
        eff.dispatch_event("change")
    assert put.value.status == 200, (put.value.status, put.value.text())
    after = feeder.server.get("/api/settings")
    assert after["settings"]["efficiency"] == 0.9
    assert after["version"] > before["version"]

    # Effacer: back to no wind while the bus is silent
    with pg.expect_response(
        lambda r: r.url.endswith("/api/wind/manual") and r.request.method == "DELETE"
    ) as dele:
        pg.click("#manual-wind-form button.manual-clear")
    assert dele.value.status == 200
    feeder.wait_nav(lambda n: n["wind"]["source"] == "NONE", timeout=3.0)

    assert page.external_requests == [], page.external_requests
    assert page.bad_responses == [], page.bad_responses


def test_settings_help(page) -> None:
    """Réglages "?" help (quick 261110-kxm): a toggle next to the label, collapsed by default,
    expanding a short help and the schema's range/default line; the input keeps its label."""
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.click("button[data-tab=reglages]")
    pg.wait_for_function(
        "() => document.querySelectorAll('#settings-form .reglages-row').length > 10"
    )
    row = pg.locator("#settings-form .reglages-row[data-key=heading_offset_deg]")
    btn = row.locator(".help-btn")
    panel = pg.locator("#reglages-help-heading_offset_deg")
    assert btn.get_attribute("aria-expanded") == "false"
    assert btn.get_attribute("aria-controls") == "reglages-help-heading_offset_deg"
    assert btn.get_attribute("aria-label") == "Aide : Décalage compas (°)"
    assert btn.inner_text() == "?"
    assert panel.is_hidden()
    label = pg.evaluate(
        "() => document.querySelector('#settings-form input[name=heading_offset_deg]')"
        ".labels[0].textContent"
    )
    assert label == "Décalage compas (°)"

    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    assert panel.is_visible()
    text = panel.inner_text()
    assert "COG" in text, text
    assert "Plage : -30 à 30 · Défaut : 0" in text, text

    btn.click()
    assert btn.get_attribute("aria-expanded") == "false"
    assert panel.is_hidden()

    assert page.external_requests == [], page.external_requests
    assert page.bad_responses == [], page.bad_responses


# Same rule as tests/ui/test_night.py COLORS_JS: only black, pure red or transparent at night.
HELP_COLORS_JS = """() => {
  const ok = (c) => {
    const skip = ["none", "auto", "transparent", "currentcolor"];
    if (!c || skip.includes(c)) return true;
    const m = /^rgba?\\(([^)]+)\\)$/.exec(c);
    if (!m) return false;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);
    return p[1] === 0 && p[2] === 0;
  };
  const sel = "#tab-reglages .help-btn, #tab-reglages .reglages-help, "
    + "#tab-reglages .reglages-help *";
  const props = ["color", "backgroundColor", "borderTopColor", "borderRightColor",
    "borderBottomColor", "borderLeftColor", "outlineColor"];
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
  return {bad, checked};
}"""

HELP_STATE_JS = """() => {
  const btns = [...document.querySelectorAll('#settings-form .help-btn')];
  return {
    rows: document.querySelectorAll('#settings-form .reglages-row').length,
    btns: btns.length,
    expanded: btns.filter((b) => b.getAttribute('aria-expanded') !== 'false').length,
    open: [...document.querySelectorAll('#settings-form .reglages-help')]
      .filter((p) => !p.hidden).length,
    small: btns.map((b) => b.getBoundingClientRect())
      .filter((r) => r.width < 48 || r.height < 48).length,
  };
}"""


def test_settings_help_every_row_night_and_layout(page) -> None:
    """Every setting has its "?" (48 px, collapsed), an open help survives a save, night colours
    stay red on black and every help open at 800 px wide does not scroll sideways."""
    from jabuka.nav.settings import Settings

    pg = page.page
    pg.goto(page.base_url + "/")
    pg.click("button[data-tab=reglages]")
    pg.wait_for_function(
        "() => document.querySelectorAll('#settings-form .reglages-row').length > 10"
    )
    n = len(Settings.model_fields)
    state = pg.evaluate(HELP_STATE_JS)
    assert state == {"rows": n, "btns": n, "expanded": 0, "open": 0, "small": 0}, state

    # an open help stays open after a save (render) and the input keeps its label
    eff_btn = pg.locator("#settings-form .reglages-row[data-key=efficiency] .help-btn")
    eff_btn.click()
    eff = pg.locator("#settings-form input[name=efficiency]")
    with pg.expect_response(
        lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT"
    ) as put:
        eff.fill("0.9")
        eff.dispatch_event("change")
    assert put.value.status == 200, (put.value.status, put.value.text())
    pg.wait_for_function(
        "() => document.querySelector('#settings-form input[name=efficiency]').value === '0.9'"
    )
    eff_btn = pg.locator("#settings-form .reglages-row[data-key=efficiency] .help-btn")
    assert eff_btn.get_attribute("aria-expanded") == "true"
    assert pg.locator("#reglages-help-efficiency").is_visible()
    assert "0,87" in pg.locator("#reglages-help-efficiency").inner_text()
    label = pg.evaluate(
        "() => document.querySelector('#settings-form input[name=efficiency]')"
        ".labels[0].textContent"
    )
    assert label == "Efficacité polaire"

    # night: the "?" buttons and the open helps are red on black
    pg.click("#night-toggle")
    pg.wait_for_function("() => document.body.classList.contains('theme-night')")
    pg.locator("#settings-form .reglages-row[data-key=variation_deg] .help-btn").click()
    assert pg.locator("#reglages-help-variation_deg").is_visible()
    res = pg.evaluate(HELP_COLORS_JS)
    assert res["bad"] == [], res["bad"]
    assert res["checked"] > n, res
    pg.click("#night-toggle")
    pg.wait_for_function("() => document.body.classList.contains('theme-day')")

    # layout: every help open on a portrait tablet, no sideways scroll
    pg.set_viewport_size({"width": 800, "height": 1280})
    pg.evaluate(
        "() => document.querySelectorAll('#settings-form .help-btn[aria-expanded=false]')"
        ".forEach((b) => b.click())"
    )
    state = pg.evaluate(HELP_STATE_JS)
    assert state["open"] == n and state["expanded"] == n, state
    pg.wait_for_timeout(200)
    sizes = pg.evaluate(
        "() => { const t = document.getElementById('tab-reglages'); return {"
        "tab: t.scrollWidth - t.clientWidth, "
        "doc: document.documentElement.scrollWidth - window.innerWidth}; }"
    )
    assert sizes["tab"] <= 1 and sizes["doc"] <= 1, sizes
    pg.set_viewport_size({"width": 1280, "height": 800})

    assert page.external_requests == [], page.external_requests
    assert page.bad_responses == [], page.bad_responses
