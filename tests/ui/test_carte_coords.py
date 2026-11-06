"""Typed mark coordinates in a real browser (quick 003): a VHF position in degrees + decimal minutes
adds a mark from the "＋ Marque (coordonnées)" button, moves an existing mark from its sheet, is
refused outside the race area, gets the "Marque à terre ?" check, works in Slovenian, and the lock
still blocks every write."""

from __future__ import annotations

import httpx
import pytest

CENTER = (43.690, 15.820)
VHF = ("43 45,2", "15 40,1")  # "bouée en 43°45,2'N 15°40,1'E"
VHF_LAT = 43 + 45.2 / 60  # 43.753333
VHF_LON = 15 + 40.1 / 60  # 15.668333
ZLARIN = ("43 41,7", "15 50,4")  # 43.695 N 15.840 E, on Zlarin island (test_carte.py)

IDLE_JS = """() => new Promise((resolve) => {
  const m = window.jabuka.map;
  if (m.loaded() && m.areTilesLoaded() && !m.isMoving()) return resolve(true);
  m.once("idle", () => resolve(true));
})"""
# the point is drawn by the pending layer and lies in the free map area (left of the panel,
# above the sheet)
VISIBLE_JS = """([lat, lon]) => { const m = window.jabuka.map;
  if (m.isMoving()) return false;
  const p = m.project([lon, lat]);
  const box = m.getContainer().getBoundingClientRect();
  const panel = document.querySelector(".carte-panel").getBoundingClientRect();
  const sheet = document.getElementById("carte-sheet").getBoundingClientRect();
  const x = box.left + p.x, y = box.top + p.y;
  const free = x > box.left && x < panel.left && y > box.top && (y < sheet.top || x > sheet.right);
  const drawn = m.queryRenderedFeatures([p.x, p.y], {layers: ["carte-pending"]}).length > 0;
  return free && drawn;
}"""


def open_carte(env, lang: str | None = None, legs: int = 5):
    pg = env.page
    if lang:
        pg.add_init_script(f"localStorage.setItem('jabuka.lang', '{lang}')")
    pg.goto(env.base_url + "/")
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    pg.click("button[data-tab=carte]")
    pg.wait_for_function(f"() => document.querySelectorAll('#course-list li').length === {legs}")
    pg.evaluate(
        "([lat, lon]) => window.jabuka.map.jumpTo({center: [lon, lat], zoom: 11})",
        list(CENTER),
    )
    pg.evaluate(IDLE_JS)
    pg.wait_for_function("() => window.jabuka.map.getLayer('carte-marks') !== undefined")
    return pg


def course(env) -> dict:
    return httpx.get(env.base_url + "/api/course", timeout=2.0).json()


def writes(pg) -> list[str]:
    """Every POST / PATCH / DELETE the page sends from now on."""
    out: list[str] = []
    pg.on(
        "request",
        lambda r: (
            out.append(f"{r.method} {r.url}") if r.method in ("POST", "PATCH", "DELETE") else None
        ),
    )
    return out


def type_into(pg, selector: str, text: str) -> None:
    """A tap on the field (selects the prefilled value) then the keys, as on the tablet."""
    pg.click(selector)
    pg.keyboard.type(text)


def test_button_typed_vhf_position_adds_the_mark(page, core_server) -> None:
    pg = open_carte(page)
    btn = pg.locator("#mark-coords")
    assert btn.inner_text() == "＋ Marque (coordonnées)"
    assert btn.bounding_box()["height"] >= 48
    btn.click()
    sheet = pg.locator("#carte-sheet")
    sheet.wait_for(state="visible")
    assert "Nouvelle marque" in sheet.inner_text()
    # no GPS: prefilled with the map centre, in degrees + decimal minutes (decimal comma in fr)
    assert pg.input_value("#coord-lat") == "43°41,400' N"
    assert pg.input_value("#coord-lon") == "15°49,200' E"
    for sel in ("#coord-lat", "#coord-lon"):
        assert pg.get_attribute(sel, "inputmode") == "decimal"
    assert "43 45,2" in sheet.inner_text()  # the format hint

    type_into(pg, "#coord-lat", VHF[0])
    type_into(pg, "#coord-lon", VHF[1])
    assert pg.input_value("#coord-lat") == VHF[0]  # the tap selected the prefilled value
    assert pg.input_value("#coord-lon") == VHF[1]
    assert pg.locator("#coord-lat-err").inner_text() == ""
    assert pg.locator("#mark-add").is_enabled()
    # the pending marker sits at the typed position and the map eased there
    pg.wait_for_function(VISIBLE_JS, arg=[VHF_LAT, VHF_LON], timeout=5000)

    pg.click("#carte-sheet [data-name=side] button[data-value=port]")
    with pg.expect_response(lambda r: r.url.endswith("/api/marks")) as resp:
        pg.click("#mark-add")
    assert resp.value.status == 200, resp.value.text()
    sheet.wait_for(state="hidden")
    c = course(page)
    # right after the active mark (Plić Sestre, leg 1)
    assert [leg["mark_id"] for leg in c["seq"]] == [
        "vodice",
        "plic-sestre",
        "m1",
        "jabuka",
        "blitvenica",
        "vodice",
    ]
    assert c["seq"][2]["side"] == "port"
    m = c["marks"]["m1"]
    assert m["lat"] == pytest.approx(VHF_LAT, abs=1e-5)
    assert m["lon"] == pytest.approx(VHF_LON, abs=1e-5)
    # the list shows it in the same format
    pg.wait_for_function(
        "() => document.querySelector('#course-list li[data-idx=\"2\"] .coord')?.textContent"
        " === \"43°45,200' N  15°40,100' E\""
    )
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


def test_mark_sheet_moves_custom_and_builtin_marks(page, core_server) -> None:
    c = course(page)
    r = httpx.post(
        core_server.base_url + "/api/marks",
        json={"name": "VHF", "lat": 43.70, "lon": 15.75, "base_version": c["version"]},
    )
    assert r.status_code == 200, r.text
    pg = open_carte(page, legs=6)
    sent = writes(pg)
    pg.click("#course-list li[data-idx='2']")  # VHF (m1)
    sheet = pg.locator("#carte-sheet")
    sheet.wait_for(state="visible")
    assert "VHF (n° 2)" in pg.locator("#carte-sheet .sheet-title").inner_text()
    assert pg.input_value("#coord-lat") == "43°42,000' N"
    assert pg.input_value("#coord-lon") == "15°45,000' E"
    move = pg.locator("#mark-move")
    assert move.inner_text() == "Déplacer ici"
    assert move.is_disabled()  # nothing typed yet

    type_into(pg, "#coord-lat", "43°45.2N")
    type_into(pg, "#coord-lon", "15 40.1 E")
    assert move.is_enabled()
    pg.wait_for_function(VISIBLE_JS, arg=[VHF_LAT, VHF_LON], timeout=5000)
    with pg.expect_response(lambda r: "/api/marks/m1" in r.url) as resp:
        move.click()
    assert resp.value.status == 200, resp.value.text()
    m = course(page)["marks"]["m1"]
    assert m["lat"] == pytest.approx(VHF_LAT, abs=1e-5)
    assert m["lon"] == pytest.approx(VHF_LON, abs=1e-5)
    # the sheet stays open on the mark, now showing where it is
    pg.wait_for_function("() => document.getElementById('coord-lat')?.value === \"43°45,200' N\"")
    assert pg.input_value("#coord-lon") == "15°40,100' E"
    assert pg.locator("#mark-move").is_disabled()
    assert [s for s in sent if "PATCH" in s] == [f"PATCH {core_server.base_url}/api/marks/m1"]

    # a builtin mark (Plić Sestre) moves too: the core keeps an override
    pg.click("#carte-sheet .sheet-close")
    pg.click("#course-list li[data-idx='1']")
    pg.wait_for_function(
        "() => document.querySelector('#carte-sheet .sheet-title')?.textContent"
        " === 'Plić Sestre (n° 1)'"
    )
    type_into(pg, "#coord-lat", "43 41")
    type_into(pg, "#coord-lon", "15 48")
    with pg.expect_response(lambda r: "/api/marks/plic-sestre" in r.url) as resp:
        pg.click("#mark-move")
    assert resp.value.status == 200, resp.value.text()
    ps = course(page)["marks"]["plic-sestre"]
    assert ps["lat"] == pytest.approx(43 + 41 / 60, abs=1e-6)
    assert ps["lon"] == pytest.approx(15.8, abs=1e-6)
    assert ps["moved"] is True
    assert page.bad_responses == [], page.bad_responses


def test_out_of_area_and_bad_input_are_refused(page, core_server) -> None:
    pg = open_carte(page)
    sent = writes(pg)
    v0 = course(page)["version"]
    pg.click("#mark-coords")
    pg.locator("#carte-sheet").wait_for(state="visible")
    add = pg.locator("#mark-add")

    pg.fill("#coord-lat", "42 30")  # 42°30' N: south of the race area (42°42' N)
    pg.fill("#coord-lon", VHF[1])
    area_err = pg.locator("#coord-area-err")
    assert area_err.inner_text() == "Hors zone de course (42°42' N à 44°06' N, 14°54' E à 16°24' E)"
    assert add.is_disabled()
    pg.fill("#coord-lat", VHF[0])
    pg.fill("#coord-lon", "16 30")  # east of the area
    assert area_err.inner_text().startswith("Hors zone de course")
    assert add.is_disabled()

    pg.fill("#coord-lon", "15 60")
    assert pg.locator("#coord-lon-err").inner_text() == "Minutes : de 0 à 59,999"
    assert area_err.inner_text() == ""
    assert add.is_disabled()
    pg.fill("#coord-lon", "15 40,1 N")
    assert pg.locator("#coord-lon-err").inner_text() == "Lettre attendue : E / W"
    pg.fill("#coord-lat", "quarante-trois")
    assert pg.locator("#coord-lat-err").inner_text() == "Format non reconnu (ex. 43 45,2)"
    assert pg.get_attribute("#coord-lat", "aria-invalid") == "true"
    pg.fill("#coord-lat", "")
    assert pg.locator("#coord-lat-err").inner_text() == "À remplir"
    # no pending marker for an invalid entry
    pg.wait_for_function(
        "() => window.jabuka.map.querySourceFeatures('carte-pending').length === 0"
    )
    add.click(force=True)  # disabled: nothing happens
    pg.wait_for_timeout(300)

    # fixed: accepted
    pg.fill("#coord-lat", VHF[0])
    pg.fill("#coord-lon", VHF[1])
    assert pg.locator("#coord-lat-err").inner_text() == ""
    assert add.is_enabled()
    assert sent == [] and course(page)["version"] == v0
    assert page.bad_responses == [], page.bad_responses


def test_typed_position_on_land_asks_first(page, core_server) -> None:
    pg = open_carte(page)
    pg.click("#mark-coords")
    pg.locator("#carte-sheet").wait_for(state="visible")
    pg.fill("#coord-lat", ZLARIN[0])
    pg.fill("#coord-lon", ZLARIN[1])
    sent = writes(pg)
    pg.click("#mark-add")
    land = pg.locator("#coord-land")
    land.wait_for(state="visible", timeout=5000)
    assert "Marque à terre ?" in land.inner_text()
    assert sent == []
    assert pg.input_value("#coord-lat") == ZLARIN[0]  # the typed values stay
    pg.click("#coord-land-cancel")
    land.wait_for(state="hidden")
    assert sent == [] and len(course(page)["seq"]) == 5

    pg.click("#mark-add")
    land.wait_for(state="visible", timeout=5000)
    with pg.expect_response(lambda r: r.url.endswith("/api/marks")) as resp:
        pg.click("#coord-land-keep")
    assert resp.value.status == 200, resp.value.text()
    m = course(page)["marks"]["m1"]
    assert m["lat"] == pytest.approx(43.695, abs=1e-6)
    assert m["lon"] == pytest.approx(15.840, abs=1e-6)
    assert page.bad_responses == [], page.bad_responses


def test_coordinates_in_slovenian(page, core_server) -> None:
    pg = open_carte(page, lang="sl")
    btn = pg.locator("#mark-coords")
    assert btn.inner_text() == "＋ Boja (koordinate)"
    btn.click()
    sheet = pg.locator("#carte-sheet")
    sheet.wait_for(state="visible")
    assert "Nova boja" in sheet.inner_text()
    assert "Zemljepisna širina" in sheet.text_content()
    assert "Stopinje in minute" in sheet.inner_text()
    assert pg.input_value("#coord-lat") == "43°41,400' N"  # decimal comma in sl too
    pg.fill("#coord-lat", "42 30")
    pg.fill("#coord-lon", VHF[1])
    assert (
        pg.locator("#coord-area-err").inner_text().startswith("Izven območja regate (42°42' N do")
    )
    pg.fill("#coord-lon", "15 75")
    assert pg.locator("#coord-lon-err").inner_text() == "Minute: od 0 do 59,999"
    pg.fill("#coord-lat", VHF[0])
    pg.fill("#coord-lon", VHF[1])
    with pg.expect_response(lambda r: r.url.endswith("/api/marks")) as resp:
        pg.click("#mark-add")
    assert resp.value.status == 200, resp.value.text()
    m = course(page)["marks"]["m1"]
    assert m["lat"] == pytest.approx(VHF_LAT, abs=1e-5)
    assert m["lon"] == pytest.approx(VHF_LON, abs=1e-5)
    pg.click("#course-list li[data-idx='2']")
    pg.locator("#mark-move").wait_for(state="visible")
    assert pg.locator("#mark-move").inner_text() == "Premakni sem"
    assert "Koordinate" in sheet.text_content()
    assert page.bad_responses == [], page.bad_responses


def test_lock_blocks_typed_coordinates(page, core_server) -> None:
    pg = open_carte(page)
    pg.click("#mark-coords")
    pg.locator("#carte-sheet").wait_for(state="visible")
    pg.fill("#coord-lat", VHF[0])
    pg.fill("#coord-lon", VHF[1])
    sent = writes(pg)
    v0 = course(page)["version"]
    pg.focus("#coord-lat")
    pg.click("#lock-btn")
    pg.wait_for_function("() => !document.getElementById('lock-overlay').hidden")
    assert pg.evaluate("() => document.activeElement === document.body")

    def centre(sel: str) -> tuple[float, float]:
        b = pg.locator(sel).bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    # taps on Ajouter, a field and the button land on the overlay; keys go nowhere
    pg.mouse.click(*centre("#mark-add"))
    pg.mouse.click(*centre("#coord-lat"))
    pg.keyboard.type("44 00")
    pg.keyboard.press("Enter")
    assert pg.input_value("#coord-lat") == VHF[0]
    pg.mouse.click(*centre("#mark-coords"))
    # even a script click on Ajouter writes nothing while locked (carte.js refuses too)
    pg.evaluate("() => document.getElementById('mark-add').click()")
    pg.wait_for_timeout(800)
    assert sent == []
    assert course(page)["version"] == v0
    assert page.bad_responses == [], page.bad_responses
