"""Lock mode and screen awake in a real browser (HELM-04): while locked nothing on the screen
reacts (tabs, map drag, wheel), only a continuous 2 s press of the padlock unlocks, a second finger
or a short press never does, and the state survives a reload. The screen-awake badge says which
mechanism holds the screen: Wake Lock, the NoSleep video, or nothing (as an alert)."""

from __future__ import annotations

import math

from jabuka.nav import geo

PLIC_SESTRE = (43.684627, 15.811626)

DISPATCH_JS = """([type, id, primary]) => {
  const el = document.getElementById("unlock-btn");
  const r = el.getBoundingClientRect();
  el.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true, pointerId: id,
    isPrimary: primary, pointerType: "touch", clientX: r.x + r.width / 2,
    clientY: r.y + r.height / 2}));
}"""


def _centre(pg, selector: str) -> tuple[float, float]:
    box = pg.locator(selector).bounding_box()
    assert box is not None, selector
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _map_view(pg) -> dict:
    return pg.evaluate(
        "() => { const m = window.jabuka.map; const c = m.getCenter();"
        " return {lng: c.lng, lat: c.lat, zoom: m.getZoom()}; }"
    )


def _locked(pg) -> bool:
    return pg.evaluate(
        "() => !document.getElementById('lock-overlay').hidden && "
        "localStorage.getItem('jabuka.locked') === '1'"
    )


def _hold(pg, ms: int) -> None:
    x, y = _centre(pg, "#unlock-btn")
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.wait_for_timeout(ms)
    pg.mouse.up()


def test_lock_swallows_everything_and_unlocks_on_a_long_press(page, feeder) -> None:
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon)
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    btn = pg.locator("#lock-btn").bounding_box()
    assert btn and btn["width"] >= 64 and btn["height"] >= 64
    pg.click("#lock-btn")
    assert _locked(pg)
    ub = pg.locator("#unlock-btn").bounding_box()
    assert ub and ub["width"] >= 64 and ub["height"] >= 64
    pg.wait_for_function("() => window.jabuka.map.dragPan.isEnabled() === false", timeout=2000)

    # a tap on the Carte tab button lands on the overlay: no tab switch
    x, y = _centre(pg, "button[data-tab=carte]")
    pg.mouse.click(x, y)
    pg.wait_for_timeout(300)
    assert pg.locator("#tab-barre").is_visible()
    assert not pg.locator("#tab-carte").is_visible()

    # a drag and a wheel on the map change nothing
    before = _map_view(pg)
    pg.mouse.move(640, 450)
    pg.mouse.down()
    pg.mouse.move(400, 300, steps=8)
    pg.mouse.up()
    pg.mouse.wheel(0, -600)
    pg.wait_for_timeout(600)
    after = _map_view(pg)
    assert abs(after["lng"] - before["lng"]) < 1e-9 and abs(after["lat"] - before["lat"]) < 1e-9
    assert abs(after["zoom"] - before["zoom"]) < 1e-9

    # numbers keep updating underneath
    pg.wait_for_function(
        "() => document.getElementById('primary').textContent !== '—'", timeout=15000
    )

    # a 1 s hold does not unlock
    _hold(pg, 1000)
    pg.wait_for_timeout(1200)
    assert _locked(pg)

    # a non-primary touch held 2.1 s does not unlock, nor a press joined by a second finger
    pg.evaluate(DISPATCH_JS, ["pointerdown", 21, False])
    pg.wait_for_timeout(2100)
    pg.evaluate(DISPATCH_JS, ["pointerup", 21, False])
    assert _locked(pg)
    pg.evaluate(DISPATCH_JS, ["pointerdown", 31, True])
    pg.wait_for_timeout(300)
    pg.evaluate(DISPATCH_JS, ["pointerdown", 32, False])
    pg.wait_for_timeout(2000)
    pg.evaluate(DISPATCH_JS, ["pointerup", 32, False])
    pg.evaluate(DISPATCH_JS, ["pointerup", 31, True])
    assert _locked(pg)

    # the lock survives a reload
    pg.reload()
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    assert _locked(pg)
    pg.wait_for_function("() => window.jabuka.map.dragPan.isEnabled() === false")

    # a 2.1 s press unlocks; everything works again
    _hold(pg, 2100)
    pg.wait_for_function("() => document.getElementById('lock-overlay').hidden")
    assert pg.evaluate("() => localStorage.getItem('jabuka.locked')") == "0"
    assert pg.evaluate("() => window.jabuka.map.dragPan.isEnabled()") is True
    pg.click("button[data-tab=carte]")
    assert pg.locator("#tab-carte").is_visible()
    assert page.external_requests == []
    assert page.bad_responses == [], page.bad_responses


def _wake_badge(pg) -> tuple[str, str]:
    return pg.evaluate(
        "() => { const b = document.querySelector('#badges [data-badge=wake]');"
        " return b ? [b.textContent, b.className] : ['', '']; }"
    )


def _first_tap(pg) -> None:
    pg.wait_for_function("() => document.querySelector('#badges [data-badge=wake]')")
    pg.mouse.click(640, 450)


def test_wake_lock_on_a_secure_origin(page) -> None:
    pg = page.page
    pg.add_init_script(
        "(() => { const orig = WakeLock.prototype.request; window.__wl = 0;"
        " WakeLock.prototype.request = function (...a) { window.__wl += 1;"
        " return orig.apply(this, a); }; })();"
    )
    pg.goto(page.base_url + "/")
    _first_tap(pg)
    pg.wait_for_function(
        "() => document.querySelector('#badges [data-badge=wake]').textContent === 'ÉCRAN: verrou'"
    )
    text, cls = _wake_badge(pg)
    assert "good" in cls, cls
    assert pg.evaluate("() => window.__wl") == 1
    # hidden then visible again: the lock is requested again
    pg.evaluate(
        "() => { const set = (v) => Object.defineProperty(document, 'visibilityState',"
        " {configurable: true, get: () => v});"
        " set('hidden'); document.dispatchEvent(new Event('visibilitychange'));"
        " set('visible'); document.dispatchEvent(new Event('visibilitychange')); }"
    )
    pg.wait_for_function("() => window.__wl === 2")
    assert _wake_badge(pg)[0] == "ÉCRAN: verrou"


def test_wake_falls_back_to_the_nosleep_video(page) -> None:
    pg = page.page
    pg.add_init_script("delete Navigator.prototype.wakeLock;")
    pg.goto(page.base_url + "/")
    _first_tap(pg)
    pg.wait_for_function(
        "() => document.querySelector('#badges [data-badge=wake]').textContent === 'ÉCRAN: vidéo'"
    )
    assert "warn" in _wake_badge(pg)[1]
    assert page.external_requests == []


def test_wake_lock_rejected_is_an_alert(page) -> None:
    pg = page.page
    pg.add_init_script(
        "window.__wl = 0; WakeLock.prototype.request = () => { window.__wl += 1;"
        " return Promise.reject(new DOMException('denied', 'NotAllowedError')); };"
    )
    pg.goto(page.base_url + "/")
    _first_tap(pg)
    pg.wait_for_function("() => window.__wl >= 1")
    pg.wait_for_timeout(300)
    text, cls = _wake_badge(pg)
    assert text == "ÉCRAN: aucun"
    assert "bad" in cls, cls
