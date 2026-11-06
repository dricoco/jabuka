"""REST seams for the nav message and the settings (optimistic concurrency, 409 on stale version).

Mutating handlers are ``async def`` so they run on the event loop, serialized with the 1 Hz tick
(no threadpool race on the stores). Every change publishes a fresh nav message to every tablet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from jabuka.nav.settings import VersionConflict

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

PATCH_MAX_KEYS = 32


class SettingsPut(BaseModel):
    base_version: int
    patch: dict[str, Any] = Field(max_length=PATCH_MAX_KEYS)


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

    return r
