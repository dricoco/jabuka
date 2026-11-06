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


def test_drag_a_mark_sends_one_patch(page, core_server) -> None:
    pg = open_carte(page)
    patches: list[str] = []
    pg.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)
    x0, y0 = xy(pg, 43.684627, 15.811626)  # Plić Sestre
    x1, y1 = x0 - 90, y0 + 40
    target = pg.evaluate(
        "([x, y]) => { const p = window.jabuka.map.unproject([x, y]); return [p.lat, p.lng]; }",
        [x1, y1],
    )
    center0 = pg.evaluate("() => window.jabuka.map.getCenter().toArray()")
    with pg.expect_response(lambda r: "/api/marks/plic-sestre" in r.url) as resp:
        pg.mouse.move(x0, y0)
        pg.mouse.down()
        pg.mouse.move(x0 - 30, y0 + 10, steps=4)
        pg.mouse.move(x1, y1, steps=6)
        pg.mouse.up()
    assert resp.value.status == 200, resp.value.text()
    pg.wait_for_timeout(500)
    assert len(patches) == 1, patches
    assert pg.evaluate("() => window.jabuka.map.getCenter().toArray()") == center0  # no pan
    assert pg.locator("#carte-sheet").is_hidden()  # the release is not a tap
    m = course(page)["marks"]["plic-sestre"]
    assert m["lat"] == pytest.approx(target[0], abs=1e-4)
    assert m["lon"] == pytest.approx(target[1], abs=1e-4)
    assert m["moved"] is True
    # a tap on the mark (now at its new place) opens its sheet
    pg.wait_for_function(
        """([lat, lon]) => { const m = window.jabuka.map;
        return m.queryRenderedFeatures(m.project([lon, lat]), {layers: ["carte-marks"]}).length;
        }""",
        arg=[m["lat"], m["lon"]],
    )
    pg.mouse.click(*xy(pg, m["lat"], m["lon"]))
    pg.locator("#carte-sheet").wait_for(state="visible")
    assert "Plić Sestre (n° 1)" in pg.locator("#carte-sheet .sheet-title").inner_text()
    assert page.bad_responses == [], page.bad_responses


def _click_and_wait(pg, selector: str, url_part: str, method: str) -> None:
    with pg.expect_response(lambda r: url_part in r.url and r.request.method == method) as resp:
        pg.click(selector)
    assert resp.value.status == 200, (selector, resp.value.status, resp.value.text())


def test_mark_sheet_side_reorder_finish_delete_and_course_b(page, core_server) -> None:
    pg = open_carte(page)
    pg.click("#course-list li[data-idx='2']")  # Jabuka
    pg.locator("#carte-sheet").wait_for(state="visible")
    assert "Jabuka (n° 2)" in pg.locator("#carte-sheet .sheet-title").inner_text()

    _click_and_wait(pg, "#carte-sheet [data-name=side] button[data-value=port]", "/legs/2", "PATCH")
    assert course(page)["seq"][2]["side"] == "port"

    _click_and_wait(pg, "#carte-sheet [data-name=radius] button[data-step='+']", "/legs/2", "PATCH")
    assert course(page)["seq"][2]["radius_nm"] == pytest.approx(0.65)

    _click_and_wait(pg, "#leg-up", "/api/course/reorder", "POST")
    c = course(page)
    assert [leg["mark_id"] for leg in c["seq"]][1:3] == ["jabuka", "plic-sestre"]
    assert c["seq"][c["active_idx"]]["mark_id"] == "plic-sestre"  # the active mark stays
    pg.wait_for_function(
        "() => document.querySelector('#carte-sheet .sheet-title')?.textContent === 'Jabuka (n° 1)'"
    )

    _click_and_wait(pg, "#leg-finish", "/api/course/finish", "POST")
    c = course(page)
    assert c["finish_idx"] == 1 and c["active_idx"] == 1
    pg.wait_for_function(
        "() => document.querySelector('#course-list li[data-idx=\"1\"] .tag.finish') !== null"
    )
    _click_and_wait(pg, "#leg-finish", "/api/course/finish", "POST")  # "Parcours complet"
    assert course(page)["finish_idx"] is None

    pg.click("#carte-sheet .sheet-close")
    pg.click("#course-list li[data-idx='3']")  # Blitvenica
    pg.locator("#leg-delete").wait_for(state="visible")
    pg.click("#leg-delete")  # the first tap only asks
    assert pg.locator("#leg-delete").inner_text() == "Confirmer la suppression"
    assert "blitvenica" in [leg["mark_id"] for leg in course(page)["seq"]]
    _click_and_wait(pg, "#leg-delete", "/api/course/legs/3", "DELETE")
    assert [leg["mark_id"] for leg in course(page)["seq"]] == [
        "vodice",
        "jabuka",
        "plic-sestre",
        "vodice",
    ]
    pg.locator("#carte-sheet").wait_for(state="hidden")

    _click_and_wait(pg, "button[data-template=B]", "/api/course/select", "POST")
    c = course(page)
    assert c["template"] == "B"
    names = ["vodice", "plic-sestre", "jabuka", "mulo", "vodice"]
    assert [leg["mark_id"] for leg in c["seq"]] == names
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#course-list .name')].map(e => e.textContent)"
        ".join(',') === 'Vodice,Plić Sestre,Jabuka,Mulo,Vodice'"
    )
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


def test_stale_tablet_gets_409_and_reloads(page, core_server) -> None:
    import httpx

    pg = open_carte(page)
    pg.route("**/api/course", lambda route: route.abort())  # this tablet misses the refetch
    r = httpx.post(core_server.base_url + "/api/course/confirm-sides", json={"base_version": 0})
    assert r.status_code == 200  # another tablet edits
    pg.click("#course-list li[data-idx='2']")
    with pg.expect_response(lambda r: "/legs/2" in r.url) as resp:
        pg.click("#carte-sheet [data-name=side] button[data-value=port]")
    assert resp.value.status == 409
    pg.wait_for_function(
        "() => document.getElementById('carte-status').textContent"
        " === 'Parcours modifié ailleurs — rechargé'"
    )
    assert pg.locator("#sides-warning").is_hidden()  # the 409 body is the current course
    assert course(page)["seq"][2]["side"] == "stbd"  # nothing overwritten


def test_advance_banner_on_the_helm_and_annuler(page, feeder) -> None:
    """The boat sits abeam of Plić Sestre inside its zone: after 10 s the course advances, the
    banner shows on the Barre tab with Annuler, and Annuler restores Plić Sestre."""
    import math

    from jabuka.nav import geo

    lat, lon = geo.offset(43.684627, 15.811626, math.radians(81.0), 0.4)
    feeder.boat.update(lat=lat, lon=lon, twd=161.0, tws_kn=12.0, twa=45.0, bsp_kn=6.0)
    pg = page.page
    pg.goto(page.base_url + "/")  # Barre tab
    nav = feeder.wait_nav(lambda n: n["course"]["active_idx"] == 2, timeout=30.0)
    assert nav["course"]["banner"]["text"] == "Marque suivante : Jabuka — Annuler"
    banner = pg.locator("#banner")
    banner.wait_for(state="visible")
    pg.wait_for_function(
        "() => document.getElementById('banner-text')?.textContent === 'Marque suivante : Jabuka'"
    )
    assert pg.locator("#tab-barre").is_visible()
    undo = pg.locator("#banner-undo")
    undo.wait_for(state="visible")
    box = undo.bounding_box()
    assert box["height"] >= 48
    with pg.expect_response(lambda r: r.url.endswith("/api/course/undo")) as resp:
        undo.click()
    assert resp.value.status == 200, resp.value.text()
    nav = feeder.wait_nav(lambda n: n["course"]["active_idx"] == 1 and not n["course"]["banner"])
    banner.wait_for(state="hidden")
    pg.wait_for_timeout(3000)  # still abeam in the zone: suppressed, no new advance
    assert feeder.server.get("/api/course")["active_idx"] == 1
    assert page.bad_responses == [], page.bad_responses
