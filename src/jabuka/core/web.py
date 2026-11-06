"""FastAPI app: GET /api/state, WS /ws (1 Hz diag push), static diagnostics page (mounted last)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from jabuka.core.main import CoreContext

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
WS_QUEUE_MAX = 4


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

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = ctx.hub.register()
        try:
            # immediate snapshot so a fresh page does not wait for the next tick
            Hub._put_drop_oldest(q, json.dumps(ctx.diag_message(), separators=(",", ":")))
            while True:
                await websocket.send_text(await q.get())
        except WebSocketDisconnect:
            pass
        except (RuntimeError, OSError):  # send on a socket the client already closed
            pass
        finally:
            ctx.hub.unregister(q)

    # Static files LAST so they never shadow the API routes.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
