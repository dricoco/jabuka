"""FastAPI app: GET /api/state, nav/settings/course/route REST, WS /ws (1 Hz diag + nav push, route
push on adoption), the helm app shell and the diagnostics page (static files, mounted last)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jabuka.core import course_api, nav_api, route_api
from jabuka.core.tiles import racepack_router

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
WS_QUEUE_MAX = 4
EVENT_LABEL_MAX = 200


class EventIn(BaseModel):
    label: str = Field(default="", max_length=EVENT_LABEL_MAX)


def strip_control(text: str) -> str:
    """Drop ASCII control characters (code < 32 or 127). The label is only ever stored inside a
    JSON line, never used in a file path."""
    return "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127)


class Hub:
    """Fan-out of pre-serialized messages to WebSocket clients. Each client has a bounded queue;
    when it is full the oldest message is dropped, so a slow tablet never blocks the core."""

    def __init__(self, maxsize: int = WS_QUEUE_MAX) -> None:
        self.maxsize = maxsize
        self.clients: set[asyncio.Queue[str]] = set()
        self.dropped = 0

    def register(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self.maxsize)
        self.clients.add(q)
        return q

    def unregister(self, q: asyncio.Queue[str]) -> None:
        self.clients.discard(q)

    @staticmethod
    def _put_drop_oldest(q: asyncio.Queue[str], msg: str) -> bool:
        dropped = False
        if q.full():
            try:
                q.get_nowait()
                dropped = True
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(msg)
        return dropped

    def publish(self, msg: str) -> None:
        for q in list(self.clients):
            if self._put_drop_oldest(q, msg):
                self.dropped += 1


def create_app(ctx: CoreContext) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await ctx.startup()
        try:
            yield
        finally:
            await ctx.shutdown()

    app = FastAPI(title="Jabuka core", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.ctx = ctx

    @app.get("/api/state")
    async def api_state() -> dict:
        return ctx.diag_message()

    @app.post("/api/event", status_code=201, response_model=None)
    async def api_event(event: EventIn) -> dict | JSONResponse:
        label = strip_control(event.label)
        try:
            rec = ctx.record_event(label)
        except (OSError, ValueError):  # disk full / read-only: say so instead of a bare 500
            return JSONResponse({"ok": False, "error": "log write failed"}, status_code=503)
        if rec is None:
            return JSONResponse(
                {"ok": False, "error": "too fast", "min_interval_s": 1.0}, status_code=429
            )
        return {
            "ok": True,
            "n": rec["n"],
            "t_mono": rec["t_mono"],
            "t_wall": rec["t_wall"],
            "utc": rec["utc"],
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = ctx.hub.register()
        try:
            # immediate snapshot so a fresh page does not wait for the next tick
            Hub._put_drop_oldest(q, json.dumps(ctx.diag_message(), separators=(",", ":")))
            nav_text = ctx.nav_text(ctx.nav.last if ctx.nav.last is not None else ctx.update_nav())
            if nav_text is not None:
                Hub._put_drop_oldest(q, nav_text)
            route_text = ctx.router.route_text() if ctx.router is not None else None
            if route_text is not None:
                Hub._put_drop_oldest(q, route_text)
            while True:
                await websocket.send_text(await q.get())
        except WebSocketDisconnect:
            pass
        except (RuntimeError, OSError):  # send on a socket the client already closed
            pass
        finally:
            ctx.hub.unregister(q)

    app.include_router(nav_api.router(ctx))
    app.include_router(course_api.router(ctx))
    app.include_router(racepack_router(ctx))  # tile index built once, here
    app.include_router(route_api.router(ctx))

    # Static files LAST so they never shadow the API routes.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
