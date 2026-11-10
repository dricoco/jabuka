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
    assert server["remaining_s"] < 300.0

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
