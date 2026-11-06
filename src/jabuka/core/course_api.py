"""REST seams for the course: GET, one-tap Course A/B select, next/prev (CRSE-01/03).

Each mutation returns the course JSON (version bumped on change) and publishes a fresh nav message
so every tablet sees it within one round trip. Plan 02-04 adds mark editing here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jabuka.nav.settings import VersionConflict

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext


class SelectIn(BaseModel):
    template: Literal["A", "B"]
    base_version: int | None = None


def router(ctx: CoreContext) -> APIRouter:
    r = APIRouter()

    def mutate(fn: Callable[[], dict]) -> dict | JSONResponse:
        try:
            out = fn()
        except VersionConflict as e:
            return JSONResponse(e.current, status_code=409)
        except OSError:  # disk full / read-only: nothing changed
            return JSONResponse({"ok": False, "error": "course write failed"}, status_code=503)
        ctx.publish_nav()
        return out

    @r.get("/api/course")
    async def api_course() -> dict:
        return ctx.nav.course.to_api()

    @r.post("/api/course/select", response_model=None)
    async def api_course_select(body: SelectIn) -> dict | JSONResponse:
        return mutate(lambda: ctx.nav.course.select(body.template, body.base_version))

    @r.post("/api/course/next", response_model=None)
    async def api_course_next() -> dict | JSONResponse:
        return mutate(ctx.nav.course.next)

    @r.post("/api/course/prev", response_model=None)
    async def api_course_prev() -> dict | JSONResponse:
        return mutate(ctx.nav.course.prev)

    return r
