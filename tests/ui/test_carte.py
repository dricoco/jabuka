"""Carte tab in a real browser (CRSE-01/02/04): tap the map to add a mark (land warning on the
"earth" layer), drag a mark, edit it from its sheet, Course B in one tap."""

from __future__ import annotations

import pytest

WATER = (43.680, 15.800)  # open water west of Plić Sestre (checked on the fixture below)
ZLARIN = (43.695, 15.840)  # on Zlarin island (checked on the fixture below)
CENTER = (43.690, 15.820)

IDLE_JS = """() => new Promise((resolve) => {
  const m = window.jabuka.map;
  if (m.loaded() && m.areTilesLoaded()) return resolve(true);
  m.once("idle", () => resolve(true));
})"""
XY_JS = "([lat, lon]) => { const p = window.jabuka.map.project([lon, lat]); return [p.x, p.y]; }"
EARTH_JS = """([lat, lon]) => { const m = window.jabuka.map;
  return m.queryRenderedFeatures(m.project([lon, lat]), {layers: ["earth"]}).length; }"""


def open_carte(env, center=CENTER, zoom=11.0):
    pg = env.page
    pg.goto(env.base_url + "/")
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    pg.click("button[data-tab=carte]")
    pg.wait_for_function("() => document.querySelectorAll('#course-list li').length === 5")
    pg.evaluate(
        "([lat, lon, z]) => window.jabuka.map.jumpTo({center: [lon, lat], zoom: z})",
        [center[0], center[1], zoom],
    )
    pg.evaluate(IDLE_JS)
    pg.wait_for_function("() => window.jabuka.map.getLayer('carte-marks') !== undefined")
    return pg


def xy(pg, lat: float, lon: float) -> tuple[float, float]:
    x, y = pg.evaluate(XY_JS, [lat, lon])
    return x, y


def course(env) -> dict:
    import httpx

    return httpx.get(env.base_url + "/api/course", timeout=2.0).json()


def test_tap_adds_a_mark_and_land_tap_warns(page, core_server) -> None:
    pg = open_carte(page)
    assert pg.evaluate(EARTH_JS, list(WATER)) == 0, "fixture: WATER is not water"
    assert pg.evaluate(EARTH_JS, list(ZLARIN)) > 0, "fixture: ZLARIN is not land"

    # open water: straight to the sheet
    pg.mouse.click(*xy(pg, *WATER))
    sheet = pg.locator("#carte-sheet")
    sheet.wait_for(state="visible")
    assert "Nouvelle marque" in sheet.inner_text()
    assert "Marque à terre" not in sheet.inner_text()
    pg.click("#carte-sheet [data-name=side] button[data-value=stbd]")
    with pg.expect_response(lambda r: r.url.endswith("/api/marks")) as resp:
        pg.click("#mark-add")
    assert resp.value.status == 200, resp.value.text()
    sheet.wait_for(state="hidden")
    c = course(page)
    assert c["seq"][2]["mark_id"] == "m1" and c["seq"][2]["side"] == "stbd"
    m = c["marks"]["m1"]
    assert m["lat"] == pytest.approx(WATER[0], abs=2e-3)
    assert m["lon"] == pytest.approx(WATER[1], abs=2e-3)
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#course-list .name')]"
        ".some(e => e.textContent === 'M1')"
    )

    # on Zlarin: "Marque à terre ?" first; Annuler adds nothing
    pg.mouse.click(*xy(pg, *ZLARIN))
    sheet.wait_for(state="visible")
    assert "Marque à terre ?" in sheet.inner_text()
    assert pg.locator("#mark-add").count() == 0
    pg.click("#land-cancel")
    sheet.wait_for(state="hidden")
    # Garder leads to the normal sheet
    pg.mouse.click(*xy(pg, *ZLARIN))
    pg.click("#land-keep")
    pg.locator("#mark-add").wait_for(state="visible")
    pg.click("#carte-sheet .sheet-close")
    assert len(course(page)["seq"]) == 6  # nothing else was added
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses
