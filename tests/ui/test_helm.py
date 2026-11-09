"""The Barre view in a real browser (HELM-02): the primary number fills >= 20% of the screen in
landscape (1280x800, 1024x600, in the left column of quick 002) and portrait, every control is
>= 48 px, the helm blocks carry every number and badge from a live feed, frozen data is never
shown as live, and the map turns course-up / north-up and follows the boat in the middle of its
visible part (HELM-01; the map padding of quick 002)."""

from __future__ import annotations

import math

from jabuka.nav import geo

PLIC_SESTRE = (43.684627, 15.811626)

SIZES_JS = """() => {
  const small = [];
  const sel = "#topbar button, #topbar input, #tab-barre button, #tab-barre input";
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) continue;  // hidden
    const name = el.id || el.textContent;
    if (r.width < 48 || r.height < 48) small.push(`${name} ${r.width}x${r.height}`);
  }
  const p = document.getElementById("primary").getBoundingClientRect();
  return {small, primaryH: p.height, primaryW: p.width, innerH: window.innerHeight,
          innerW: window.innerWidth, count: document.querySelectorAll(sel).length};
}"""

# the boat's offset from the centre of the visible map (the container minus the padding the
# helm column covers), as a fraction of the visible size
BOAT_OFFSET_JS = """() => {
  const m = window.jabuka.map;
  const nav = window.jabuka.lastNav;
  if (!nav || !nav.boat) return null;
  const p = m.project([nav.boat.lon, nav.boat.lat]);
  const c = m.getContainer();
  const pad = m.getPadding();
  const w = c.clientWidth - pad.left - pad.right, h = c.clientHeight - pad.top - pad.bottom;
  return {dx: Math.abs(p.x - (pad.left + w / 2)) / w,
          dy: Math.abs(p.y - (pad.top + h / 2)) / h,
          lat: nav.boat.lat, padLeft: pad.left};
}"""


def _near_plic_sestre(feeder) -> None:
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon, twd=161.0, tws_kn=12.0, twa=45.0, bsp_kn=6.0)
    feeder.wait_nav(lambda n: n["wind"]["source"] == "LIVE" and n["layline"] is not None)


def _live(pg) -> None:
    pg.wait_for_function(
        "() => { const t = document.getElementById('primary').textContent; "
        "return t && t !== '—'; }",
        timeout=15000,
    )


def test_bands_sizes_and_numbers(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _live(pg)
    pg.wait_for_function(
        "() => document.getElementById('helm-countdown').textContent.startsWith('Virement dans')",
        timeout=15000,
    )
    assert pg.locator("#primary-label").inner_text() == "TWA CIBLE ↑"
    rest = pg.locator("#helm-rest").inner_text()  # block 3
    assert "nds" in rest and "/" in rest  # BSP / target BSP
    assert "%" in rest  # % polar
    assert "Plić Sestre" in rest and "nm" in rest and "min" in rest
    assert "Autre bord" in rest and "°M" in rest
    assert "Virement dans" in pg.locator("#helm-route").inner_text()  # block 2
    hint = pg.locator("#helm-hint").inner_text()
    assert hint in ("LOFER", "ABATTRE", "")
    badges = pg.locator("#badges").inner_text()
    assert "LIVE" in badges
    for w, h in ((1280, 800), (1024, 600), (800, 1280)):
        pg.set_viewport_size({"width": w, "height": h})
        pg.wait_for_timeout(300)
        res = pg.evaluate(SIZES_JS)
        assert res["count"] >= 7
        assert res["primaryH"] >= 0.2 * res["innerH"], res
        assert res["primaryW"] <= res["innerW"], res
        assert res["small"] == [], res["small"]
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


def test_frozen_numbers_turn_grey_when_the_core_dies(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _live(pg)
    pg.wait_for_function("() => !document.getElementById('tab-barre').classList.contains('stale')")
    live_color = pg.evaluate("() => getComputedStyle(document.getElementById('primary')).color")
    feeder.stop()
    feeder.server.proc.terminate()
    pg.wait_for_function(
        "() => document.getElementById('tab-barre').classList.contains('stale') && "
        "document.getElementById('helm-stale').textContent === 'PERTE DONNÉES' && "
        "document.getElementById('badges').textContent.includes('PERTE DONNÉES')",
        timeout=4000,
    )
    assert pg.locator("#helm-stale").is_visible()
    grey = pg.evaluate(
        "() => [getComputedStyle(document.getElementById('primary')).color, "
        "getComputedStyle(document.body).getPropertyValue('--dim').trim()]"
    )
    assert grey[0] != live_color
    assert grey[0] == "rgb(85, 85, 85)", grey  # --dim #555555 (day)


def test_course_up_north_up_and_centre(page, feeder) -> None:
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    _live(pg)
    hdg = feeder.server.get("/api/nav")["boat"]["hdg_t"]
    bearing_js = "() => ((window.jabuka.map.getBearing() % 360) + 360) % 360"

    pg.click("#map-course")
    assert pg.evaluate("() => localStorage.getItem('jabuka.mapMode')") == "course"
    pg.wait_for_function(
        f"() => {{ const b = ({bearing_js})(); const d = Math.abs(((b - {hdg}) + 540) % 360 - 180);"
        " return d <= 1 && !window.jabuka.map.isMoving(); }",
        timeout=5000,
    )
    assert pg.locator("#map-course").get_attribute("aria-pressed") == "true"

    pg.click("#map-north")
    assert pg.evaluate("() => localStorage.getItem('jabuka.mapMode')") == "north"
    pg.wait_for_function(
        f"() => {{ const b = ({bearing_js})(); return (b < 0.5 || b > 359.5) && "
        "!window.jabuka.map.isMoving(); }",
        timeout=5000,
    )

    pg.click("#map-centre")
    assert pg.evaluate("() => localStorage.getItem('jabuka.centred')") == "1"
    assert pg.locator("#map-centre").get_attribute("aria-pressed") == "true"
    # the boat moves 1.5 nm: the map follows it
    lat, lon = geo.offset(feeder.boat["lat"], feeder.boat["lon"], math.radians(250.0), 1.5)
    feeder.boat.update(lat=lat, lon=lon)
    feeder.wait_nav(lambda n: abs(n["boat"]["lat"] - lat) < 1e-4)
    pg.wait_for_function(
        f"() => {{ const o = ({BOAT_OFFSET_JS})(); return o && Math.abs(o.lat - {lat}) < 1e-4 "
        "&& o.padLeft > 0 && o.dx < 0.05 && o.dy < 0.05 && !window.jabuka.map.isMoving(); }",
        timeout=6000,
    )

    # choices persist on this tablet
    pg.click("#map-course")
    pg.reload()
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    assert pg.locator("#map-course").get_attribute("aria-pressed") == "true"
    assert pg.locator("#map-centre").get_attribute("aria-pressed") == "true"
    pg.wait_for_function(
        f"() => {{ const b = ({bearing_js})(); return Math.abs(((b - {hdg}) + 540) % 360 - 180)"
        " <= 1; }",
        timeout=6000,
    )
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


ALERTS_JS = """() => {
  const nav = {type: "nav", wind: null, helm: {primary: null},
               alerts: ["Écart TWA calculé/B&G > 10°", "Erreur de calcul nav"]};
  window.jabuka.bus.dispatchEvent(new CustomEvent("nav", {detail: nav}));
  const shown = [...document.querySelectorAll('#badges [data-badge^="alert-"]')]
    .filter((e) => e.getBoundingClientRect().height > 0).map((e) => e.textContent);
  const label = document.getElementById("primary-label").textContent;
  window.jabuka.bus.dispatchEvent(new CustomEvent("nav", {detail: {...nav, alerts: []}}));
  const after = document.querySelectorAll('#badges [data-badge^="alert-"]').length;
  return {shown, label, after};
}"""


def test_nav_alerts_are_visible_on_every_tab(page, feeder) -> None:
    """CR-01: nav alerts are red badges in the top bar (visible on every tab, here Carte) and a
    failed nav computation reads ERREUR CALCUL on the helm; the badges go with the alert."""
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _live(pg)
    pg.click('#topbar [data-tab="carte"]')
    res = pg.evaluate(ALERTS_JS)
    assert res["shown"] == ["Écart TWA calculé/B&G > 10°", "Erreur de calcul nav"], res
    assert res["label"] == "ERREUR CALCUL"
    assert res["after"] == 0


# The latest live message with one takeover forced in (G-4-R01/R03/R08), rendered synchronously by
# every module on the bus, read back in the same evaluate. The next live message (within 1 s) puts
# the live values back.
TAKEOVER_JS = """(variant) => {
  const nav = JSON.parse(JSON.stringify(window.jabuka.lastNav));
  // same version as the live route: no GET /api/route for a synthetic block
  const version = (nav.route && nav.route.version) || 0;
  const due = {state: "ok", reason: null, version, primary: "twa", target: 42, deviation: 1,
    target_twa: 42, target_tack: "stbd", target_hdg_t: 119, countdown_s: -5, tack_kind: "tack",
    wrong_tack: false, updating: false, missed: false, cost_text: null, age_s: 60, bias: null,
    stay: {active: false, tack: null, released_land: false, release_in_s: null}};
  if (variant === "cue") nav.route = due;
  if (variant === "wrong") {
    nav.route = {...due, wrong_tack: true, target_tack: "port", countdown_s: 300};
  }
  if (variant === "stale") {
    nav.wind = {...(nav.wind || {}), source: "MANUEL", stale: true, manual_age_s: 3600};
    nav.route = due;
  }
  if (variant === "nogps") {
    nav.boat = {...(nav.boat || {}), lat: null, lon: null};
    nav.helm = {primary: null, target: null, deviation: null, cts_t: null};
    nav.route = null;
  }
  window.jabuka.bus.dispatchEvent(new CustomEvent("nav", {detail: nav}));
  const $ = (id) => document.getElementById(id);
  const box = $("helm-steer").querySelector(".primary-box");
  return {
    label: $("primary-label").textContent,
    primary: $("primary").textContent,
    unit: $("primary-unit").textContent,
    cue: box.classList.contains("cue"),
    cueWord: $("primary").classList.contains("cue-word"),
    labelAlert: $("primary-label").classList.contains("alert"),
    windStale: $("tab-barre").classList.contains("wind-stale"),
    primaryColor: getComputedStyle($("primary")).color,
    labelColor: getComputedStyle($("primary-label")).color,
    countdown: $("helm-countdown").textContent,
    countdownAlert: $("helm-countdown").classList.contains("alert"),
    col: $("helm-col").textContent,
    badges: [...document.querySelectorAll("#badges .badge")].map((e) => e.textContent),
  };
}"""

BACK_LIVE_JS = """() => {
  const box = document.getElementById("helm-steer").querySelector(".primary-box");
  const badges = [...document.querySelectorAll("#badges .badge")].map((e) => e.textContent);
  return !document.getElementById("tab-barre").classList.contains("wind-stale")
    && !box.classList.contains("cue") && !badges.includes("PAS DE GPS")
    && document.getElementById("primary-label").textContent !== "PAS DE GPS";
}"""


def test_helm_takeovers_on_the_live_page(page, feeder) -> None:
    """G-4-R03: a due tack / the wrong tack turns the primary box into VIREZ + the tack, inverted.
    G-4-R01: stale manual wind reads VENT PÉRIMÉ, dimmed, with no tack cue anywhere.
    G-4-R08: no position reads PAS DE GPS (red badge and label). All go with the next live
    message."""
    _near_plic_sestre(feeder)
    pg = page.page
    pg.goto(page.base_url + "/")
    _live(pg)

    cue = pg.evaluate(TAKEOVER_JS, "cue")
    assert (cue["label"], cue["primary"], cue["unit"]) == ("MAINTENANT", "VIREZ", "bâbord"), cue
    assert cue["cue"] and cue["cueWord"], cue
    assert cue["primaryColor"] == "rgb(255, 255, 255)", cue  # day --bg on the inverted box
    pg.wait_for_function(BACK_LIVE_JS, timeout=3000)

    wrong = pg.evaluate(TAKEOVER_JS, "wrong")
    assert (wrong["label"], wrong["primary"], wrong["unit"]) == ("MAUVAIS BORD", "VIREZ", "bâbord")
    assert wrong["cue"] and wrong["cueWord"], wrong
    pg.wait_for_function(BACK_LIVE_JS, timeout=3000)

    stale = pg.evaluate(TAKEOVER_JS, "stale")
    assert stale["label"] == "VENT PÉRIMÉ" and stale["windStale"] and stale["labelAlert"], stale
    assert not stale["cue"] and not stale["cueWord"], stale
    assert stale["countdown"] == "VENT PÉRIMÉ" and not stale["countdownAlert"], stale
    assert "VIREZ" not in stale["col"] and "EMPANNEZ" not in stale["col"], stale["col"]
    assert stale["primaryColor"] == "rgb(85, 85, 85)", stale  # day --dim
    assert stale["labelColor"] == "rgb(192, 0, 0)", stale  # day --bad
    pg.wait_for_function(BACK_LIVE_JS, timeout=3000)

    nogps = pg.evaluate(TAKEOVER_JS, "nogps")
    assert (nogps["label"], nogps["primary"]) == ("PAS DE GPS", "—"), nogps
    assert "PAS DE GPS" in nogps["badges"] and nogps["labelAlert"], nogps
    pg.wait_for_function(BACK_LIVE_JS, timeout=3000)

    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses
