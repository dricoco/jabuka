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
