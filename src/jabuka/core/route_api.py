"""REST seams of the live router (ROUT-02/07): GET /api/route (the adopted route as the WS "route"
message), POST /api/route/stay ("On reste" on/off) and POST /api/route/recompute (forced reroute).

Handlers are ``async def`` so they run on the event loop, serialized with the 1 Hz tick. Bodies
forbid extra fields (422); repeated taps cannot queue work because the RouterPool coalesces (one
running + one pending, latest wins), and every change is pushed to every tablet at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext


class StayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: StrictBool


def router(ctx: CoreContext) -> APIRouter:
    r = APIRouter()

    def fresh_nav() -> dict:
        ctx.publish_nav()  # the router reads the request at this tick: the job starts now
        nav = ctx.nav.last
        return nav if nav is not None else (ctx.update_nav() or {})

    @r.get("/api/route", response_model=None)
    async def api_route() -> dict | JSONResponse:
        msg = ctx.router.route_message()
        if msg is None:
            return JSONResponse(ctx.router.status_reason(), status_code=404)
        return msg

    @r.post("/api/route/stay", response_model=None)
    async def api_route_stay(body: StayIn) -> dict | JSONResponse:
        err = ctx.router.set_stay(body.active, ctx.nav.last)
        if err is not None:
            return JSONResponse({"ok": False, "error": err}, status_code=409)
        return fresh_nav()

    @r.post("/api/route/recompute", response_model=None)
    async def api_route_recompute() -> dict:
        ctx.router.request("manuel", True)
        return fresh_nav()

    return r
