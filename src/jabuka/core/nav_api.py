"""REST seams for the nav message, the settings (optimistic concurrency, 409 on stale version) and
the manual wind (WIND-04: POST/DELETE /api/wind/manual, every change logged in the events log).

Mutating handlers are ``async def`` so they run on the event loop, serialized with the 1 Hz tick
(no threadpool race on the stores). Every change publishes a fresh nav message to every tablet.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jabuka.common.clock import utc_epoch
from jabuka.nav.settings import VersionConflict

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

log = logging.getLogger("jabuka.nav")

PATCH_MAX_KEYS = 32


class SettingsPut(BaseModel):
    base_version: int
    patch: dict[str, Any] = Field(max_length=PATCH_MAX_KEYS)


class ManualWindIn(BaseModel):
    """What the helmsman reads off the B&G display: TWD in °M (default on the form) or °T."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    twd: float = Field(ge=0.0, lt=360.0)
    tws_kn: float = Field(ge=0.0, le=80.0)
    ref: Literal["M", "T"]


def validation_response(e: ValidationError) -> JSONResponse:
    return JSONResponse(
        {"detail": e.errors(include_url=False, include_context=False, include_input=False)},
        status_code=422,
    )


def router(ctx: CoreContext) -> APIRouter:
    r = APIRouter()

    @r.get("/api/nav")
    async def api_nav() -> dict:
        nav = ctx.nav
        return nav.last if nav.last is not None else nav.update()

    @r.get("/api/settings")
    async def api_settings() -> dict:
        return ctx.nav.settings_store.to_api()

    @r.get("/api/settings/schema")
    async def api_settings_schema() -> dict:
        return ctx.nav.settings_store.schema()

    @r.put("/api/settings", response_model=None)
    async def api_settings_put(body: SettingsPut) -> dict | JSONResponse:
        store = ctx.nav.settings_store
        try:
            out = store.update(body.patch, body.base_version)
        except VersionConflict as e:
            return JSONResponse(e.current, status_code=409)
        except ValidationError as e:
            return validation_response(e)
        except OSError:  # disk full / read-only: nothing changed
            return JSONResponse({"ok": False, "error": "settings write failed"}, status_code=503)
        ctx.publish_nav()
        return out

    # -- manual wind (WIND-04) ---------------------------------------------------------------
    def log_manual(action: str, entry: dict | None) -> None:
        """Event line (type wind_manual) for every change; never rate-limited, never fatal."""
        rec = {
            "type": "wind_manual",
            "action": action,
            "manual": entry,
            "t_mono": ctx.clock.monotonic(),
            "t_wall": ctx.clock.wall(),
            "utc": ctx.clock.status().get("utc"),
        }
        try:
            if ctx.events_log is not None:
                ctx.events_log.write_json(rec, fsync_now=True)
        except (OSError, ValueError):
            ctx.stats["events_errors"] = ctx.stats.get("events_errors", 0) + 1
            log.exception("wind_manual event write failed")

    def fresh_nav() -> dict:
        ctx.publish_nav()
        return ctx.nav.last if ctx.nav.last is not None else ctx.nav.update()

    @r.get("/api/wind/manual")
    async def api_wind_manual_get() -> dict:
        return {"manual": ctx.nav.manual.to_api()}

    @r.post("/api/wind/manual", response_model=None)
    async def api_wind_manual_post(body: ManualWindIn) -> dict | JSONResponse:
        nav = ctx.nav
        try:
            entry = nav.manual.set(
                body.twd, body.tws_kn, body.ref, nav.settings.variation_deg, utc_epoch(ctx.clock)
            )
        except ValidationError as e:
            return validation_response(e)
        except OSError:
            return JSONResponse({"ok": False, "error": "manual wind write failed"}, status_code=503)
        log_manual("set", entry.model_dump())
        return fresh_nav()

    @r.delete("/api/wind/manual", response_model=None)
    async def api_wind_manual_delete() -> dict | JSONResponse:
        try:
            ctx.nav.manual.clear()
        except OSError:
            return JSONResponse({"ok": False, "error": "manual wind write failed"}, status_code=503)
        log_manual("clear", None)
        return fresh_nav()

    return r
