"""Start mode in a real browser (quick 261110-cuk): DÉPART opens the panel, « Ping comité » stores
the GPS position, a typed pin (degrees + decimal minutes, decimal comma), 5:00 counts down on the
Pi and survives a page reload, STOP, « Fermer le départ » closes start mode on the Pi.

The core runs with the system clock (no trusted UTC): the timer lives in memory on the Pi, which
is exactly the page-reload case."""

from __future__ import annotations

import math
import re

from jabuka.nav import geo

READY_JS = "() => window.jabuka && window.jabuka.lastNav && document.getElementById('start-open')"
PANEL_JS = "() => { const p = document.getElementById('start-panel'); return p && !p.hidden; }"
HIDDEN_JS = "() => { const p = document.getElementById('start-panel'); return p && p.hidden; }"
TIMER_RE = re.compile(r"^(\d+):(\d\d)$")
SOURCE_JS = """async (id) => {
  const m = window.jabuka && window.jabuka.map;
  const s = m && m.getSource(id);
  if (!s) return null;
  const data = typeof s.getData === "function" ? await s.getData() : s.serialize().data;
  return (data.features || []).map((f) => f.geometry.type);
}"""


def dm(value: float) -> str:
    """43.716 -> "43 42,960" (degrees + decimal minutes, decimal comma)."""
    deg = int(value)
    return f"{deg} {(value - deg) * 60:06.3f}".replace(".", ",")


def _seconds(text: str) -> int:
    m = TIMER_RE.match(text)
    assert m, text
    return int(m.group(1)) * 60 + int(m.group(2))


def _open_start(page, feeder):
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_function(READY_JS, timeout=30000)
    pg.click("#start-open")
    pg.wait_for_function(PANEL_JS, timeout=5000)
    feeder.wait_nav(lambda n: n["start"]["open"] is True)
    return pg


def _set_line(pg, feeder) -> tuple[float, float]:
    b = feeder.boat
    feeder.wait_nav(lambda n: n["boat"]["lat"] is not None)
    pg.click("#start-ping-committee")
    nav = feeder.wait_nav(lambda n: n["start"]["line"]["committee"] is not None)
    assert nav["start"]["line"]["committee"]["src"] == "ping"
    pg.wait_for_function(
        "() => document.getElementById('start-end-committee').textContent.includes('ping')"
    )
    lat, lon = geo.offset(b["lat"], b["lon"], math.radians(90.0), 0.2)
    pg.click("#start-type-pin")
    pg.fill("#start-lat", dm(lat))
    pg.fill("#start-lon", dm(lon))
    pg.click("#start-form-ok")
    nav = feeder.wait_nav(lambda n: (n["start"]["line"]["pin"] or {}).get("src") == "typed")
    pin = nav["start"]["line"]["pin"]
    assert abs(pin["lat"] - lat) < 1e-4 and abs(pin["lon"] - lon) < 1e-4
    pg.wait_for_function("() => document.getElementById('start-form').hidden")
    return lat, lon


def test_start_mode_ping_typed_timer_reload_close(page, feeder) -> None:
    pg = _open_start(page, feeder)
    _set_line(pg, feeder)

    pg.click("#start-go")
    pg.wait_for_function(
        "() => /^[45]:\\d\\d$/.test(document.getElementById('start-timer').textContent)",
        timeout=5000,
    )
    rem = feeder.wait_nav(lambda n: n["start"]["timer"]["state"] == "running")["start"]["timer"]
    assert 290.0 <= rem["remaining_s"] <= 300.0

    pg.reload()
    pg.wait_for_function(READY_JS, timeout=30000)
    pg.wait_for_function(PANEL_JS, timeout=5000)
    pg.wait_for_function(
        "() => /^\\d+:\\d\\d$/.test(document.getElementById('start-timer').textContent)",
        timeout=5000,
    )
    shown = _seconds(pg.text_content("#start-timer"))
    server = feeder.server.get("/api/nav")["start"]["timer"]
    assert server["state"] == "running"
    assert abs(shown - server["remaining_s"]) <= 2.0, (shown, server)

    pg.click("#start-stop")
    feeder.wait_nav(lambda n: n["start"]["timer"]["state"] == "off")
    pg.wait_for_function("() => document.getElementById('start-timer').textContent === '—:—'")
    pg.click("#start-close")
    pg.wait_for_function(HIDDEN_JS, timeout=5000)
    feeder.wait_nav(lambda n: "start" not in n)
    assert pg.is_visible("#start-open")

    assert page.console_errors == []
    assert page.external_requests == []
    assert page.bad_responses == []


def test_start_zone_and_times_on_the_map(page, feeder) -> None:
    pg = _open_start(page, feeder)
    _set_line(pg, feeder)
    pg.click("#start-go")
    nav = feeder.wait_nav(lambda n: n["start"]["zone"] is not None)
    assert nav["start"]["zone"][0] == nav["start"]["zone"][-1]
    pg.wait_for_function(
        "async () => { const f = await (" + SOURCE_JS + ")('start-zone');"
        " return Array.isArray(f) && f.includes('Polygon'); }",
        timeout=10000,
    )
    assert pg.evaluate(SOURCE_JS, "start-line") == ["LineString"]
    assert pg.evaluate(SOURCE_JS, "start-ends") == ["Point", "Point"]
    pg.wait_for_function(
        "() => document.querySelector('#start-now .start-side-value').textContent.length > 0"
    )
    text = pg.text_content("#start-now .start-side-value")
    assert text == "—" or re.match(r"^\d+:\d\d", text), text
    assert pg.is_visible("#start-line-info")
    pg.click("#start-close")
    pg.wait_for_function(HIDDEN_JS, timeout=5000)
    pg.wait_for_function(
        "() => window.jabuka.map.getLayoutProperty('start-zone-fill', 'visibility') === 'none'"
    )
    assert page.console_errors == []
    assert page.external_requests == []


# -- Task 3: layout and night (HELM-03, night start at 20:00) --------------------------------------
LAYOUT_JS = """() => {
  const r = (id) => document.getElementById(id).getBoundingClientRect();
  const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1
    && a.top < b.bottom - 1 && b.top < a.bottom - 1;
  const p = r("start-panel"), col = r("helm-col"), ctrls = r("map-ctrls"), bar = r("topbar");
  return {
    visible: p.width > 0 && p.height > 0,
    hitCol: hit(p, col), hitCtrls: hit(p, ctrls),
    bottom: p.bottom, mapMid: (bar.bottom + window.innerHeight) / 2,
    right: p.right, W: window.innerWidth,
    scrollX: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}"""

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
    "borderBottomColor", "borderLeftColor", "outlineColor", "fill", "stroke", "caretColor"];
  const bad = [];
  let checked = 0;
  for (const el of document.querySelectorAll(
    "#start-panel, #start-panel *, #start-ctrls, #start-ctrls *")) {
    if (!el.getClientRects().length) continue;
    checked += 1;
    const cs = getComputedStyle(el);
    for (const p of props) if (!ok(cs[p])) bad.push(`${el.id || el.className} ${p}=${cs[p]}`);
  }
  return {bad, checked};
}"""


def test_start_panel_layout(page, feeder) -> None:
    pg = _open_start(page, feeder)
    _set_line(pg, feeder)
    pg.click("#start-go")
    feeder.wait_nav(lambda n: n["start"]["timer"]["state"] == "running")
    for w, h in ((1280, 800), (1024, 600)):
        pg.set_viewport_size({"width": w, "height": h})
        pg.wait_for_timeout(300)
        lay = pg.evaluate(LAYOUT_JS)
        assert lay["visible"], (w, h, lay)
        assert not lay["hitCol"] and not lay["hitCtrls"], (w, h, lay)
        assert lay["bottom"] < lay["mapMid"], (w, h, lay)
        assert lay["right"] <= lay["W"] and not lay["scrollX"], (w, h, lay)
    pg.set_viewport_size({"width": 600, "height": 1024})
    pg.wait_for_timeout(300)
    lay = pg.evaluate(LAYOUT_JS)
    assert lay["visible"] and not lay["hitCol"] and not lay["hitCtrls"], lay
    assert not lay["scrollX"], lay
    assert page.console_errors == []


def test_start_panel_night_is_red_only(page, feeder) -> None:
    pg = _open_start(page, feeder)
    _set_line(pg, feeder)
    pg.click("#start-go")
    feeder.wait_nav(lambda n: n["start"]["timer"]["state"] == "running")
    pg.click("#night-toggle")
    pg.wait_for_function("() => document.body.classList.contains('theme-night')")
    pg.click("#start-type-pin")  # the typed form (inputs) too
    pg.wait_for_function("() => !document.getElementById('start-form').hidden")
    res = pg.evaluate(NIGHT_JS)
    assert res["checked"] > 15 and res["bad"] == [], res
    pg.click("#start-form-cancel")
    pg.click("#start-close")
    pg.wait_for_function(HIDDEN_JS, timeout=5000)
    res = pg.evaluate(NIGHT_JS)  # the DÉPART button alone
    assert res["checked"] >= 2 and res["bad"] == [], res
    assert page.console_errors == []
