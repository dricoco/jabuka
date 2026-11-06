"""REST seams of the live router: GET /api/route (the adopted route as the WS "route" message).

Handlers are ``async def`` so they run on the event loop, serialized with the 1 Hz tick.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext


def router(ctx: CoreContext) -> APIRouter:
    r = APIRouter()

    @r.get("/api/route", response_model=None)
    async def api_route() -> dict | JSONResponse:
        msg = ctx.router.route_message()
        if msg is None:
            return JSONResponse(ctx.router.status_reason(), status_code=404)
        return msg

    return r
