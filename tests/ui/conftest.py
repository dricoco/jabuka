"""Headless-browser harness shared by the Phase 2 UI tests (plans 02-01, 02-04, 02-05).

- racepack_dir: tmp copy of the tile fixture (race.pmtiles) and the seamark fixture, then
  racepack_extra(dir) (default no-op; plan 03-06 adds the routing files: land mask + wind).
- core_server: the venv's jabuka-core as a subprocess (127.0.0.1, free HTTP/UDP ports, tmp data
  dir, --racepack, then core_extra_args: default --clock system --gpsd none; plan 03-06 runs
  --clock gps against a fake gpsd), stopped cleanly after the test.
- feeder: a thread sending schema-v1 UDP deltas every 0.5 s from a mutable boat dict (wind,
  heading and BSP under src "sim" with heading ref T; position/COG/SOG under src "sim-gps").
  Mutate feeder.boat between steps; feeder.wait_nav(pred) polls GET /api/nav.
- page: Playwright Chromium (system binary, SwiftShader WebGL), 1280x800, with a context route
  that aborts and records every request leaving the core origin and a listener recording every
  HTTP response >= 400.

JABUKA_REQUIRE_UI=1 turns a missing playwright package or chromium binary into a failure.
"""

from __future__ import annotations

import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from jabuka.common import messages
from jabuka.common.conventions import apparent_from_true
from jabuka.common.units import kn_to_ms, wrap_2pi, wrap_pi
from jabuka.ingest.gpsd_client import tpv_to_values
from jabuka.sim.synth import SynthState, gps_objects, udp_values

FIX = Path(__file__).parent.parent / "fixtures" / "map"
BIN = Path(sys.executable).parent
REQUIRE_UI = os.environ.get("JABUKA_REQUIRE_UI") == "1"
CHROMIUM = os.environ.get("JABUKA_CHROMIUM", "/usr/bin/chromium")
GPS_PATHS = ("navigation.position", "navigation.courseOverGroundTrue", "navigation.speedOverGround")


def _need(cond: bool, why: str) -> None:
    if not cond:
        if REQUIRE_UI:
            pytest.fail(f"UI test prerequisite missing (JABUKA_REQUIRE_UI=1): {why}")
        pytest.skip(why)


def _free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def racepack_extra() -> Callable[[Path], None]:
    """Hook: add files to the race pack before the core starts (override in a test module)."""
    return lambda _d: None


@pytest.fixture
def core_extra_args() -> list[str]:
    """Hook: the core's clock and gpsd arguments (override in a test module)."""
    return ["--clock", "system", "--gpsd", "none"]


@pytest.fixture
def racepack_dir(tmp_path: Path, racepack_extra: Callable[[Path], None]) -> Path:
    d = tmp_path / "racepack"
    d.mkdir()
    shutil.copy(FIX / "sibenik.pmtiles", d / "race.pmtiles")
    shutil.copy(FIX / "seamarks-mini.geojson", d / "seamarks.geojson")
    racepack_extra(d)
    return d


@dataclass
class CoreServer:
    base_url: str
    udp_port: int
    data_dir: Path
    proc: subprocess.Popen

    def get(self, path: str) -> Any:
        r = httpx.get(self.base_url + path, timeout=2.0)
        r.raise_for_status()
        return r.json()


@pytest.fixture
def core_server(
    tmp_path: Path, racepack_dir: Path, core_extra_args: list[str]
) -> Iterator[CoreServer]:
    http_port = _free_port(socket.SOCK_STREAM)
    udp_port = _free_port(socket.SOCK_DGRAM)
    data_dir = tmp_path / "data"
    proc = subprocess.Popen(
        [
            str(BIN / "jabuka-core"),
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(http_port),
            "--udp-port",
            str(udp_port),
            "--data-dir",
            str(data_dir),
            "--racepack",
            str(racepack_dir),
            *core_extra_args,
        ]
    )
    server = CoreServer(f"http://127.0.0.1:{http_port}", udp_port, data_dir, proc)
    try:
        deadline = time.monotonic() + 15
        while True:
            if proc.poll() is not None:
                pytest.fail(f"jabuka-core exited with {proc.returncode}")
            try:
                if httpx.get(server.base_url + "/api/state", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("jabuka-core did not answer /api/state within 15 s")
            time.sleep(0.1)
        yield server
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def boat_state(b: dict) -> SynthState:
    """SynthState (SI units) from the feeder's boat dict (degrees, knots)."""
    twd = wrap_2pi(math.radians(b["twd"]))
    twa = wrap_pi(math.radians(b["twa"]))
    hdg = wrap_2pi(twd - twa)
    tws, bsp = kn_to_ms(b["tws_kn"]), kn_to_ms(b["bsp_kn"])
    aw = apparent_from_true(twd=twd, tws=tws, bsp=bsp, hdg=hdg)
    return SynthState(0.0, twd, tws, twa, hdg, bsp, aw.awa, aw.aws, b["lat"], b["lon"])


@dataclass
class Feeder:
    server: CoreServer
    boat: dict = field(
        default_factory=lambda: {
            "lat": 43.7161,
            "lon": 15.7967,
            "twd": 161.0,
            "tws_kn": 12.0,
            "twa": 45.0,
            "bsp_kn": 6.0,
            "send_wind": True,
            "send_gps": True,
        }
    )
    interval_s: float = 0.5
    sent: int = 0
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def _send_once(self, sock: socket.socket) -> None:
        b = dict(self.boat)
        s = boat_state(b)
        mono, wall = time.monotonic(), time.time()
        addr = ("127.0.0.1", self.server.udp_port)
        if b.get("send_wind", True):
            msg = messages.delta_message("sim", udp_values(s), mono, wall)
            sock.sendto(messages.encode(msg), addr)
        if b.get("send_gps", True):
            tpv, _ = gps_objects(s, wall)
            values = [v for v in tpv_to_values(tpv) if v["path"] in GPS_PATHS]
            sock.sendto(
                messages.encode(messages.delta_message("sim-gps", values, mono, wall)), addr
            )
        self.sent += 1

    def _run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            while not self._stop.is_set():
                try:
                    self._send_once(sock)
                except OSError:
                    pass
                self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ui-feeder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def wait_nav(self, pred: Callable[[dict], object], timeout: float = 15.0) -> dict:
        """Poll GET /api/nav until pred(nav) is truthy; return that nav message."""
        deadline = time.monotonic() + timeout
        last: dict | None = None
        while time.monotonic() < deadline:
            try:
                last = self.server.get("/api/nav")
                if pred(last):
                    return last
            except (httpx.HTTPError, KeyError, TypeError):
                pass
            time.sleep(0.2)
        raise AssertionError(f"nav predicate not met within {timeout}s (last={last!r})")


@pytest.fixture
def feeder(core_server: CoreServer) -> Iterator[Feeder]:
    f = Feeder(core_server)
    f.start()
    try:
        yield f
    finally:
        f.stop()


@dataclass
class PageEnv:
    page: Any
    base_url: str
    external_requests: list[str]
    bad_responses: list[tuple[int, str]]
    console_errors: list[str]


@pytest.fixture
def page(core_server: CoreServer) -> Iterator[PageEnv]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _need(False, "playwright not installed (pip install -e .[dev])")
        raise
    _need(Path(CHROMIUM).exists(), f"chromium not found at {CHROMIUM} (set JABUKA_CHROMIUM)")
    origin = core_server.base_url
    external: list[str] = []
    bad: list[tuple[int, str]] = []
    console_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROMIUM,
            headless=True,
            args=[
                "--enable-unsafe-swiftshader",
                "--use-angle=swiftshader",
                "--ignore-gpu-blocklist",
            ],
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})

        def guard(route, request) -> None:
            url = request.url
            parts = urlsplit(url)
            if parts.scheme in ("http", "https", "ws", "wss"):
                if f"{parts.scheme}://{parts.netloc}" != origin:
                    external.append(url)
                    route.abort()
                    return
            route.continue_()

        context.route("**/*", guard)
        pg = context.new_page()
        pg.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
        pg.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        try:
            yield PageEnv(pg, origin, external, bad, console_errors)
        finally:
            context.close()
            browser.close()
