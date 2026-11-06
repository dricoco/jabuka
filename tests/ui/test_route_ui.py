"""The route on the tablet (plan 03-06) in a real browser against a real core that routes: the
route line and its tack points on the shared map, the route-driven primary number and countdown,
the route band (age, cost, bias, state), the "ON RESTE" button (lock-mode aware), the GRIB badge
when the bus is silent, night colours and the router row on Diag.

The core runs with --clock gps against a fake gpsd pushing TPVs stamped with the current UTC and
the boat's position (routing is blocked until the GPS clock gate is ok), on a race pack made of
the tile fixture plus the 25 m land mask fixture and a uniform wind.npz covering now +- 2 days.
The feeder sends the instruments over UDP (wind, heading, BSP); the GPS comes from gpsd only.
"""

from __future__ import annotations

import asyncio
import math
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jabuka.nav import geo
from jabuka.prep.wxpack import write_npz
from jabuka.sim.fake_gpsd import FakeGpsd, utc_iso

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MASK = FIXTURES / "route" / "landmask_race_25m"
PLIC_SESTRE = (43.684627, 15.811626)
KN = 1852.0 / 3600.0
TWD, TWS = 161.0, 12.0
RACE_END = datetime(2026, 11, 15, 12, tzinfo=UTC).timestamp()

SOURCE_JS = """async (id) => {
  const m = window.jabuka && window.jabuka.map;
  const s = m && m.getSource(id);
  if (!s) return null;
  const data = typeof s.getData === "function" ? await s.getData() : s.serialize().data;
  return (data.features || []).map((f) => f.geometry.type);
}"""


# -- race pack + fake gpsd -----------------------------------------------------------------------
def write_uniform_wind(dest: Path, twd_deg: float = TWD, tws_kn: float = TWS) -> Path:
    """Uniform wind FROM twd_deg at tws_kn, hourly, from now - 2 days to the later of now + 2 days
    and the end of the race window (so the coverage check stays quiet)."""
    now = time.time()
    t0 = int(now // 3600) * 3600 - 2 * 86400
    t_end = max(now + 2 * 86400, RACE_END)
    t = np.arange(t0, t_end + 3600, 3600, dtype=np.int64)
    lat = np.arange(42.5, 44.3, 0.25, dtype=np.float64)
    lon = np.arange(14.75, 16.6, 0.25, dtype=np.float64)
    ms = tws_kn * KN
    u = -ms * math.sin(math.radians(twd_deg))
    v = -ms * math.cos(math.radians(twd_deg))
    shape = (t.size, lat.size, lon.size)
    arrays = {
        "t": t,
        "lat": lat,
        "lon": lon,
        "u": np.full(shape, u, np.float32),
        "v": np.full(shape, v, np.float32),
        "model": "uniform",
        "run": "test",
    }
    return write_npz(dest, "wind", arrays, {"source": "test", "model": "uniform", "run": "test"})


@pytest.fixture
def racepack_extra():
    def add(d: Path) -> None:
        for suffix in (".npz", ".json"):
            shutil.copy(MASK.with_suffix(suffix), d / f"landmask{suffix}")
        write_uniform_wind(d)

    return add


class GpsdFeed:
    """A fake gpsd on a free port (own thread + event loop) pushing one TPV per second from
    ``boat`` (the feeder's dict once linked), stamped with the current UTC."""

    def __init__(self) -> None:
        self.boat: dict[str, Any] = {
            "lat": 43.7161,
            "lon": 15.7967,
            "twd": TWD,
            "twa": 45.0,
            "bsp_kn": 6.0,
        }
        self.port = 0
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def tpv(self) -> dict:
        b = self.boat
        return {
            "class": "TPV",
            "device": "/dev/gps",
            "mode": 3,
            "time": utc_iso(time.time()),
            "lat": round(float(b["lat"]), 7),
            "lon": round(float(b["lon"]), 7),
            "track": round((float(b["twd"]) - float(b["twa"])) % 360.0, 2),
            "speed": round(float(b["bsp_kn"]) * KN, 3),
            "eph": 3.5,
        }

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        gpsd = FakeGpsd()

        async def main() -> None:
            self.port = await gpsd.start()
            self._ready.set()
            while not self._stop.is_set():
                gpsd.push(self.tpv())
                await asyncio.sleep(1.0)
            await gpsd.close()

        try:
            loop.run_until_complete(main())
        finally:
            loop.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ui-fake-gpsd", daemon=True)
        self._thread.start()
        assert self._ready.wait(10), "fake gpsd did not start"

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


@pytest.fixture
def gpsd_feed():
    g = GpsdFeed()
    g.start()
    try:
        yield g
    finally:
        g.stop()


@pytest.fixture
def core_extra_args(gpsd_feed: GpsdFeed) -> list[str]:
    return ["--clock", "gps", "--gpsd", f"127.0.0.1:{gpsd_feed.port}"]


@pytest.fixture
def feeder(feeder, gpsd_feed: GpsdFeed):
    """The conftest feeder for the instruments; the GPS comes from the fake gpsd (same boat)."""
    feeder.boat["send_gps"] = False
    lat, lon = geo.offset(*PLIC_SESTRE, math.radians(341.0), 2.0)
    feeder.boat.update(lat=lat, lon=lon, twd=TWD, tws_kn=TWS, twa=45.0, bsp_kn=6.0)
    gpsd_feed.boat = feeder.boat
    return feeder


# -- helpers -------------------------------------------------------------------------------------
def _routed(feeder, timeout: float = 90.0) -> dict:
    """Wait until the core has adopted a route (state ok, version >= 1)."""
    return feeder.wait_nav(
        lambda n: (n.get("route") or {}).get("state") == "ok" and n["route"]["version"] >= 1,
        timeout=timeout,
    )


def _unexpected(bad: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """HTTP >= 400 responses other than GET /api/route's 404 before the first route."""
    return [(s, u) for s, u in bad if not (s == 404 and u.endswith("/api/route"))]


def _open(page) -> Any:
    pg = page.page
    pg.goto(page.base_url + "/")
    pg.wait_for_function("() => window.jabuka && window.jabuka.map", timeout=30000)
    return pg


def _route_features(pg, timeout_s: float = 30.0) -> tuple[list, list]:
    deadline = time.monotonic() + timeout_s
    line: list = []
    tacks: list = []
    while time.monotonic() < deadline:
        line = pg.evaluate(SOURCE_JS, "route") or []
        tacks = pg.evaluate(SOURCE_JS, "route-tack") or []
        if line == ["LineString"] and tacks:
            break
        pg.wait_for_timeout(300)
    return line, tacks


# -- Task 1: route on the map, route-driven helm -------------------------------------------------
def test_route_on_the_map_and_the_helm_steers_it(page, feeder) -> None:
    nav = _routed(feeder)
    assert nav["route"]["target_tack"] in ("stbd", "port")
    pg = _open(page)
    line, tacks = _route_features(pg)
    assert line == ["LineString"], line
    assert tacks and set(tacks) == {"Point"}, tacks
    pg.wait_for_function(
        "() => { const t = document.getElementById('route-band').textContent;"
        " return t.includes('Virement dans') || t.includes('Route :'); }",
        timeout=30000,
    )
    pg.wait_for_function(
        "() => document.getElementById('primary-label').textContent.includes('ROUTE')",
        timeout=30000,
    )
    countdown = pg.locator("#helm-countdown").inner_text()
    assert countdown == "" or "dans" in countdown or countdown in ("VIREZ", "EMPANNEZ"), countdown
    # the route layers are on the map and visible
    vis = pg.evaluate(
        "() => window.jabuka.map.getStyle().layers"
        ".filter((l) => (l.metadata || {})['jabuka:overlay'] === 'route')"
        ".map((l) => (l.layout || {}).visibility)"
    )
    assert vis and all(v == "visible" for v in vis), vis
    assert page.external_requests == []
    assert _unexpected(page.bad_responses) == [], page.bad_responses


# -- Task 2: ON RESTE (lock aware), night colours, Diag, GRIB badge ------------------------------
# computed colours of the route band and the button: black, pure red or transparent only
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
    "borderBottomColor", "borderLeftColor", "outlineColor"];
  const bad = [];
  let checked = 0;
  for (const el of document.querySelectorAll("#route-band, #route-band *, #stay-button")) {
    if (!el.getClientRects().length) continue;
    checked += 1;
    const cs = getComputedStyle(el);
    for (const p of props) if (!ok(cs[p])) bad.push(`${el.id || el.className} ${p}=${cs[p]}`);
  }
  const layers = window.jabuka.map.getStyle().layers
    .filter((l) => (l.metadata || {})["jabuka:overlay"] === "route");
  const colors = JSON.stringify(layers.map((l) => l.paint || {})).match(/#[0-9a-fA-F]{6}/g) || [];
  for (const c of colors) if (c.slice(3).toLowerCase() !== "0000") bad.push(`layer ${c}`);
  return {bad, checked, layers: layers.length};
}"""


def _label(pg) -> str:
    return pg.locator("#stay-button").inner_text().strip()


def _hold_unlock(pg, ms: int = 2400) -> None:
    box = pg.locator("#unlock-btn").bounding_box()
    assert box is not None
    pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.mouse.down()
    pg.wait_for_timeout(ms)
    pg.mouse.up()


def test_on_reste_lock_night_and_diag(page, feeder) -> None:
    _routed(feeder)
    pg = _open(page)
    posts: list[str] = []
    pg.on(
        "request",
        lambda r: (
            posts.append(r.post_data or "")
            if r.method == "POST" and r.url.endswith("/api/route/stay")
            else None
        ),
    )
    pg.wait_for_function(
        "() => { const b = document.getElementById('stay-button');"
        " return b && !b.disabled && b.textContent.trim() === 'ON RESTE'; }",
        timeout=30000,
    )
    box = pg.locator("#stay-button").bounding_box()
    band = pg.locator("#route-band").bounding_box()
    assert box and band and box["height"] >= 64 and box["width"] >= band["width"] - 2, (box, band)
    font = pg.evaluate(
        "() => parseFloat(getComputedStyle(document.getElementById('stay-button')).fontSize)"
    )
    assert font >= 24

    # locked: a tap on the button (lands on the lock overlay) and even a scripted click do nothing
    pg.click("#lock-btn")
    pg.wait_for_function("() => document.body.classList.contains('locked')", timeout=2000)
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    pg.mouse.click(x, y)
    pg.evaluate("() => document.getElementById('stay-button').click()")
    pg.wait_for_timeout(800)
    assert posts == []
    assert _label(pg) == "ON RESTE"
    _hold_unlock(pg)
    pg.wait_for_function("() => !document.body.classList.contains('locked')", timeout=3000)

    # unlocked: ON RESTE holds the tack, the core reroutes with the tack held
    pg.click("#stay-button")
    pg.wait_for_function(
        "() => document.getElementById('stay-button').textContent.trim() === 'ANNULER ON RESTE'",
        timeout=20000,
    )
    assert posts and '"active":true' in posts[0].replace(" ", ""), posts
    nav = feeder.wait_nav(lambda n: n["route"]["kind"] == "stay", timeout=60)
    assert nav["route"]["stay"]["active"] is True

    # night: the band, the active button and the route layers are red on black only
    pg.click("#night-toggle")
    pg.wait_for_function("() => window.jabuka.map.getStyle().name.includes('night')")
    pg.wait_for_function(
        "() => window.jabuka.map.getStyle().layers.some((l) => l.id === 'route-line')"
    )
    res = pg.evaluate(NIGHT_JS)
    assert res["checked"] >= 3 and res["layers"] == 3, res
    assert res["bad"] == [], res["bad"]

    # cancel
    pg.click("#stay-button")
    pg.wait_for_function(
        "() => document.getElementById('stay-button').textContent.trim() === 'ON RESTE'",
        timeout=20000,
    )
    assert len(posts) == 2 and '"active":false' in posts[1].replace(" ", ""), posts
    feeder.wait_nav(lambda n: n["route"]["stay"]["active"] is False, timeout=20)

    # Diag lists the router health row
    pg.goto(page.base_url + "/diag.html")
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#health h3')]"
        ".some((h) => h.textContent.startsWith('router'))",
        timeout=15000,
    )
    health = pg.locator("#health").inner_text()
    assert "pool" in health and "pack_ok" in health
    assert page.external_requests == []
    assert _unexpected(page.bad_responses) == [], page.bad_responses


def test_grib_badge_when_the_bus_is_silent(page, feeder) -> None:
    _routed(feeder)
    pg = _open(page)
    pg.wait_for_function(
        "() => document.getElementById('badges').textContent.includes('LIVE')", timeout=15000
    )
    feeder.boat["send_wind"] = False
    pg.wait_for_function(
        "() => [...document.querySelectorAll('#badges .badge')]"
        ".some((b) => b.textContent === 'GRIB')",
        timeout=20000,
    )
    n1 = feeder.wait_nav(lambda n: n["wind"]["source"] == "GRIB", timeout=10)
    assert n1["route"]["state"] == "ok"
    # the route keeps being followed on GRIB wind: its age is still counted and shown
    n2 = feeder.wait_nav(
        lambda n: (
            n["route"]["state"] == "ok"
            and n["route"]["age_s"] is not None
            and n["t_mono"] > n1["t_mono"] + 2
        ),
        timeout=15,
    )
    assert n2["wind"]["source"] == "GRIB"
    band = pg.locator("#route-band").inner_text()
    assert "Route :" in band, band
    assert page.external_requests == []
    assert _unexpected(page.bad_responses) == [], page.bad_responses
