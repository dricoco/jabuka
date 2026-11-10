"""REST seams for start mode (quick 261110-cuk): open/close, the line ends (GPS ping or typed) and
the 5:00 timer (start / SYNC / STOP). The state lives on the Pi (nav/start.py StartStore) and is
pushed to every tablet in the nav message's optional "start" block.

Every mutation returns the fresh nav message (like nav_api's manual wind) and publishes it.
Bodies are strict (extra keys and NaN refused: 422). A ping without a fresh GPS position is 409
{"detail": "no_position"}, a SYNC without a running timer 409 {"detail": "no_timer"}, a disk
failure 503 (nothing changed). Handlers are ``async def``: serialized with the 1 Hz tick.

Event lines (events log, fsync'd): {"type": "start", "action": ...} for every change, written
through StartStore.on_event which this router installs.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from jabuka.common.clock import utc_epoch
from jabuka.core.nav_api import validation_response
from jabuka.nav import wind
from jabuka.nav.start import END_NAMES, NoTimer

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

log = logging.getLogger("jabuka.core.start")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class OpenIn(_Strict):
    open: bool


class PingIn(_Strict):
    end: Literal["committee", "pin"]


class LineIn(_Strict):
    lat: float
    lon: float


class TimerIn(_Strict):
    action: Literal["start", "sync", "stop"]


def _finite(x: object) -> float | None:
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def router(ctx: CoreContext) -> APIRouter:
    r = APIRouter()
    store = ctx.nav.start

    def write_event(rec: dict) -> None:
        if ctx.events_log is None:
            return
        line = {
            **rec,
            "t_mono": ctx.clock.monotonic(),
            "t_wall": ctx.clock.wall(),
            "utc": ctx.clock.status().get("utc"),
        }
        try:
            ctx.events_log.write_json(line, fsync_now=True)
        except (OSError, ValueError):
            ctx.stats["events_errors"] = ctx.stats.get("events_errors", 0) + 1
            log.exception("start event write failed")

    store.on_event = write_event

    def fresh_nav() -> dict:
        ctx.publish_nav()
        return ctx.nav.last if ctx.nav.last is not None else ctx.nav.update()

    def boat() -> tuple[float, float] | None:
        b = (ctx.nav.last or {}).get("boat") or {}
        lat, lon = _finite(b.get("lat")), _finite(b.get("lon"))
        return (lat, lon) if lat is not None and lon is not None else None

    def mutate(fn: Callable[[], object]) -> dict | JSONResponse:
        try:
            fn()
        except NoTimer:
            return JSONResponse({"detail": "no_timer"}, status_code=409)
        except ValidationError as e:
            return validation_response(e)
        except OSError:  # disk full / read-only: nothing changed
            return JSONResponse({"ok": False, "error": "start write failed"}, status_code=503)
        except ValueError as e:  # unknown line end
            return JSONResponse({"detail": str(e)[:200]}, status_code=422)
        return fresh_nav()

    @r.get("/api/start")
    async def api_start() -> dict:
        return store.to_api()

    @r.post("/api/start/open", response_model=None)
    async def api_start_open(body: OpenIn) -> dict | JSONResponse:
        return mutate(lambda: store.set_open(body.open))

    @r.post("/api/start/ping", response_model=None)
    async def api_start_ping(body: PingIn) -> dict | JSONResponse:
        # the same freshness rule as the helm's boat block (StateStore.latest)
        pos = ctx.nav.state.latest(wind.POSITION)
        value = pos.get("value") if pos is not None else None
        lat = _finite(value.get("latitude")) if isinstance(value, dict) else None
        lon = _finite(value.get("longitude")) if isinstance(value, dict) else None
        if lat is None or lon is None:
            return JSONResponse({"detail": "no_position"}, status_code=409)
        utc = utc_epoch(ctx.clock)
        return mutate(lambda: store.set_end(body.end, lat, lon, "ping", utc))

    @r.put("/api/start/line/{end}", response_model=None)
    async def api_start_line(end: str, body: LineIn) -> dict | JSONResponse:
        if end not in END_NAMES:
            return JSONResponse({"detail": "unknown line end"}, status_code=422)
        utc = utc_epoch(ctx.clock)
        return mutate(lambda: store.set_end(end, body.lat, body.lon, "typed", utc))

    @r.post("/api/start/timer", response_model=None)
    async def api_start_timer(body: TimerIn) -> dict | JSONResponse:
        t_mono = ctx.clock.monotonic()
        utc = utc_epoch(ctx.clock)
        if body.action == "start":
            return mutate(lambda: store.start_timer(t_mono, utc))
        if body.action == "sync":
            return mutate(lambda: store.sync(t_mono, utc, boat()))
        return mutate(store.stop)

    return r
