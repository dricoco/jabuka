"""In-process core + router fixtures for the Phase 3 integration suite (plan 03-05).

- ``route_pack(tmp_path)``: a race pack assembled from the committed fixtures (25 m land mask) plus
  a generated uniform wind.npz with its sha256 sidecar (prep.wxpack.write_npz).
- ``RoutingCore``: CoreContext + TestClient with the 1 Hz tick loop disabled; the test drives the
  ticks itself, inside the event loop thread (``client.portal.call``), so the router's tasks are
  scheduled exactly as in production.
- ``FakePool``: scripted stand-in for RouterPool (deterministic CycleResults, no process).
"""

from __future__ import annotations

import asyncio
import math
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from jabuka.common.clock import Clock, SimClock
from jabuka.common.units import kn_to_ms
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
from jabuka.nav import geo
from jabuka.prep.wxpack import write_npz
from jabuka.route.pool import PoolOutcome
from jabuka.route.types import CycleResult, LegResult, PathPoint, RouteResult, TackPoint

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MASK = FIXTURES / "route" / "landmask_race_25m"

T_WIND0 = 1_794_528_000  # 2026-11-13T00:00Z, first time of the generated wind
T_START = T_WIND0 + 3600.0  # SimClock UTC: wind start + 1 h
PLIC_SESTRE = (43.684627, 15.811626)
KN = 1852.0 / 3600.0


def boat_near_plic(dist_nm: float = 2.0, bearing_deg: float = 337.5) -> tuple[float, float]:
    """A position dist_nm from Plić Sestre on the given bearing (default NNW)."""
    return geo.offset(*PLIC_SESTRE, math.radians(bearing_deg), dist_nm)


def write_wind(
    dest: Path,
    twd_deg: float = 45.0,
    tws_kn: float = 18.0,
    t0: int = T_WIND0,
    hours: int = 72,
    step_h: int = 1,
) -> Path:
    """Uniform wind (FROM twd_deg, tws_kn) wind.npz + sidecar in dest."""
    lat = np.arange(42.5, 44.3, 0.25, dtype=np.float64)
    lon = np.arange(14.75, 16.6, 0.25, dtype=np.float64)
    t = np.arange(t0, t0 + hours * 3600 + 1, step_h * 3600, dtype=np.int64)
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
        "run": "2026-11-13T00:00Z",
    }
    return write_npz(dest, "wind", arrays, {"source": "test", "model": "uniform", "run": "test"})


def make_pack(dest: Path, *, wind: bool = True, **wind_kw: Any) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for suffix in (".npz", ".json"):
        shutil.copy(MASK.with_suffix(suffix), dest / f"landmask{suffix}")
    if wind:
        write_wind(dest, **wind_kw)
    return dest


@pytest.fixture
def route_pack(tmp_path: Path) -> Path:
    return make_pack(tmp_path / "racepack")


# --------------------------------------------------------------------------------------------
# Fake pool
# --------------------------------------------------------------------------------------------


def straight_route(
    t0: float,
    lat: float,
    lon: float,
    *,
    eta_s: float = 7200.0,
    twa: float = 40.0,
    tack_at_s: float | None = None,
    to_mark: tuple[float, float] = PLIC_SESTRE,
    request_id: str = "fake",
    level: str = "L0",
    valid: bool = True,
    ok: bool = True,
    reason: str | None = None,
    force_released_at: float | None = None,
    mark_id: str = "plic-sestre",
) -> RouteResult:
    """A two- or three-point route from (lat, lon) to the mark: one tack at tack_at_s."""
    tack = 1 if twa > 0 else -1
    eta = t0 + eta_s
    if not ok:
        return RouteResult(ok=False, reason=reason, request_id=request_id, t0=t0, level=level)
    pts = [PathPoint(t0, lat, lon, twa, tack, 6.0, 45.0, 18.0)]
    tacks: tuple[TackPoint, ...] = ()
    if tack_at_s is not None:
        f = tack_at_s / eta_s
        mlat, mlon = lat + f * (to_mark[0] - lat), lon + f * (to_mark[1] - lon)
        pts.append(PathPoint(t0 + tack_at_s, mlat, mlon, -twa, -tack, 6.0, 45.0, 18.0))
        tacks = (TackPoint(t0 + tack_at_s, mlat, mlon, tack, -tack, "tack"),)
    pts.append(PathPoint(eta, to_mark[0], to_mark[1], pts[-1].twa_deg, pts[-1].tack, 6.0, 45.0, 18.0))
    return RouteResult(
        ok=True,
        reason=None,
        request_id=request_id,
        t0=t0,
        path=tuple(pts),
        tacks=tacks,
        legs=(LegResult(mark_id, eta, *to_mark),),
        eta=eta,
        valid=valid,
        level=level,
        force_released_at=force_released_at,
    )


class FakePool:
    """RouterPool stand-in. ``script(creq) -> PoolOutcome | CycleResult`` builds each answer;
    the default answers a straight valid route with the configured eta/tack. Jobs resolve when
    ``hold`` is False (set it True to keep one running and test coalescing)."""

    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.script: Callable[[Any], Any] | None = None
        self.eta_s = 7200.0
        self.tack_at_s: float | None = 1800.0
        self.cost_s: float | None = 120.0
        self.eta_old_now: float | None = None
        self.old_valid: bool | None = True
        self.hold = False
        self.closed = False
        self.started = False
        self._busy = 0
        self.max_busy = 0
        self.stats_d = {"jobs": 0, "ok": 0, "timeouts": 0, "crashes": 0, "last_ms": 1.0}

    @property
    def stats(self) -> dict:
        return {**self.stats_d, "running": self._busy, "pending": 0}

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def default(self, creq) -> CycleResult:
        b = creq.base
        opt = straight_route(
            b.t0, b.lat, b.lon, eta_s=self.eta_s, tack_at_s=self.tack_at_s, request_id=b.request_id
        )
        forced = None
        if creq.want_forced and self.tack_at_s is not None:
            forced = straight_route(
                b.t0,
                b.lat,
                b.lon,
                eta_s=self.eta_s + (self.cost_s or 0.0),
                tack_at_s=self.tack_at_s + 600.0,
                request_id=b.request_id,
            )
        eta_old = self.eta_old_now
        return CycleResult(
            opt,
            forced,
            self.cost_s if forced is not None else None,
            eta_old if creq.old_path else None,
            self.old_valid if creq.old_path else None,
            None,
            {"level": b.settings.level},
        )

    async def run_latest(self, fn, creq) -> PoolOutcome:
        self.requests.append(creq)
        self._busy += 1
        self.max_busy = max(self.max_busy, self._busy)
        try:
            while self.hold:
                await asyncio.sleep(0.01)
            ans = self.script(creq) if self.script is not None else self.default(creq)
            self.stats_d["jobs"] += 1
            if isinstance(ans, PoolOutcome):
                return ans
            self.stats_d["ok"] += 1
            return PoolOutcome("ok", ans, 0.001, None)
        finally:
            self._busy -= 1


# --------------------------------------------------------------------------------------------
# In-process core driven tick by tick
# --------------------------------------------------------------------------------------------


class RoutingCore:
    """CoreContext + TestClient; ticks run in the event-loop thread via the portal."""

    def __init__(
        self,
        data_dir: Path,
        racepack_dir: Path,
        udp_port: int,
        *,
        clock: Clock | None = None,
        utc: float | None = T_START,
        pool_factory: Callable[..., Any] | None = None,
        tick_loop: bool = False,
    ) -> None:
        self.clock = clock if clock is not None else SimClock(start_utc=utc)
        self.ctx = CoreContext.create(
            self.clock, data_dir, udp_port=udp_port, racepack_dir=racepack_dir
        )
        if pool_factory is not None:
            self.ctx.router.pool_factory = pool_factory
        if not tick_loop:

            async def _no_tick_loop(first_target: float) -> None:
                return None

            self.ctx._tick_loop = _no_tick_loop  # type: ignore[method-assign]
        self.client = TestClient(create_app(self.ctx))
        self.navs: list[dict] = []

    def __enter__(self) -> RoutingCore:
        self.client.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.client.__exit__(*exc)

    @property
    def router(self):
        return self.ctx.router

    def call(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Run fn in the event-loop thread (where the core's tick runs)."""
        return self.client.portal.call(fn, *args)

    # -- inputs --------------------------------------------------------------------------------
    def feed_gps(self, lat: float, lon: float, cog_deg: float | None, sog_kn: float | None):
        t = self.clock.monotonic()
        vals: list[dict] = [
            {"path": "gps.mode", "value": 3, "unit": None},
            {"path": "navigation.position", "value": {"latitude": lat, "longitude": lon}},
        ]
        if cog_deg is not None:
            vals.append(
                {
                    "path": "navigation.courseOverGroundTrue",
                    "value": math.radians(cog_deg % 360.0),
                    "unit": "rad",
                    "ref": "T",
                }
            )
        if sog_kn is not None:
            vals.append({"path": "navigation.speedOverGround", "value": kn_to_ms(sog_kn)})
        self.ctx.state.update_values("gpsd", vals, t)

    def feed_wind(
        self, twd_deg: float, tws_kn: float, hdg_deg: float, bsp_kn: float = 6.0
    ) -> None:
        """Instrument true wind (TWD, TWS, TWA) + heading + BSP, as the B&G would send it."""
        from jabuka.common.conventions import apparent_from_true

        twd, hdg = math.radians(twd_deg), math.radians(hdg_deg)
        tws, bsp = kn_to_ms(tws_kn), kn_to_ms(bsp_kn)
        twa = math.atan2(math.sin(twd - hdg), math.cos(twd - hdg))
        aw = apparent_from_true(twd=twd, tws=tws, bsp=bsp, hdg=hdg)
        self.ctx.on_message(
            {
                "src": "fastnet",
                "values": [
                    {"path": "environment.wind.angleApparent", "value": aw.awa, "unit": "rad"},
                    {"path": "environment.wind.speedApparent", "value": aw.aws, "unit": "m/s"},
                    {"path": "environment.wind.angleTrueWater", "value": twa, "unit": "rad"},
                    {"path": "environment.wind.speedTrue", "value": tws, "unit": "m/s"},
                    {"path": "environment.wind.direction", "value": twd, "unit": "rad", "ref": "T"},
                    {"path": "navigation.heading", "value": hdg, "unit": "rad", "ref": "T"},
                    {"path": "navigation.speedThroughWater", "value": bsp, "unit": "m/s"},
                ],
            }
        )

    def sail(
        self,
        lat: float,
        lon: float,
        hdg_deg: float,
        *,
        twd_deg: float = 45.0,
        tws_kn: float = 18.0,
        bsp_kn: float = 6.0,
        wind: bool = True,
    ) -> None:
        """Feed one second of a boat sailing hdg_deg (COG = heading, SOG = BSP)."""
        if wind:
            self.feed_wind(twd_deg, tws_kn, hdg_deg, bsp_kn)
        self.feed_gps(lat, lon, hdg_deg, bsp_kn)

    # -- ticks ---------------------------------------------------------------------------------
    def tick(self, dt: float = 0.0) -> dict:
        if dt and isinstance(self.clock, SimClock):
            self.clock.advance(dt)
        self.call(self.ctx.tick_once)
        nav = self.ctx.nav.last
        assert nav is not None
        self.navs.append(nav)
        return nav

    def settle(self, timeout: float = 5.0) -> None:
        """Let the router's pending tasks run (real time, the clock does not move)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            busy = self.call(lambda: bool(self.router.busy()))
            if not busy:
                return
            time.sleep(0.01)
        raise AssertionError("router still busy")

    def wait_version(self, version: int, timeout: float = 60.0, dt: float = 0.0) -> dict:
        """Tick (every 50 ms of real time, sim time + dt per tick) until the nav message shows
        route.version >= version."""
        deadline = time.monotonic() + timeout
        nav = self.tick(dt)
        while (nav.get("route") or {}).get("version", 0) < version:
            if time.monotonic() > deadline:
                raise AssertionError(f"no route version {version}: {nav.get('route')}")
            time.sleep(0.05)
            nav = self.tick(dt)
        return nav


@pytest.fixture
def routing_core(tmp_path: Path, route_pack: Path, free_udp_port: int) -> Iterator[Callable]:
    """factory(**kw) -> entered RoutingCore (data dir tmp_path/data, pack route_pack)."""
    made: list[RoutingCore] = []

    def make(**kw: Any) -> RoutingCore:
        kw.setdefault("racepack_dir", route_pack)
        data_dir = kw.pop("data_dir", tmp_path / "data")
        port = kw.pop("udp_port", free_udp_port)
        core = RoutingCore(data_dir, kw.pop("racepack_dir"), port, **kw)
        core.__enter__()
        made.append(core)
        return core

    yield make
    for core in reversed(made):
        try:
            core.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - teardown best effort
            pass


@pytest.fixture
def fake_pool() -> FakePool:
    return FakePool()


@pytest.fixture
def rh():
    """This module (helpers and constants): tests run with --import-mode=importlib, so they cannot
    import the conftest directly."""
    return sys.modules[__name__]
