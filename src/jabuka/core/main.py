"""jabuka-core: state store, UDP bus listener, 1 Hz tick, diagnostics web app (one asyncio loop)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn

from jabuka.common import messages
from jabuka.common.clock import Clock, SimClock, make_clock
from jabuka.core.bus import start_udp_listener
from jabuka.core.state import StateStore
from jabuka.core.web import Hub, create_app

log = logging.getLogger("jabuka.core")


@dataclass
class CoreContext:
    clock: Clock
    state: StateStore
    hub: Hub
    data_dir: Path
    udp_host: str = "127.0.0.1"
    udp_port: int = messages.DEFAULT_UDP_PORT
    stats: dict[str, int] = field(
        default_factory=lambda: {"udp_rx": 0, "udp_rejected": 0, "handler_errors": 0}
    )
    started_mono: float = 0.0
    ticks: int = 0
    _transport: Any = None
    _tasks: list[asyncio.Task] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        clock: Clock,
        data_dir: Path,
        *,
        udp_host: str = "127.0.0.1",
        udp_port: int = messages.DEFAULT_UDP_PORT,
    ) -> CoreContext:
        data_dir = Path(data_dir)
        return cls(
            clock=clock,
            state=StateStore(clock),
            hub=Hub(),
            data_dir=data_dir,
            udp_host=udp_host,
            udp_port=udp_port,
        )

    # -- message handling --------------------------------------------------------------------
    def on_message(self, msg: dict) -> None:
        t_sim = msg.get("t_sim")
        if t_sim is not None and isinstance(self.clock, SimClock):
            self.clock.observe_utc(float(t_sim))  # BEFORE stamping t_rx
        t_rx = self.clock.monotonic()
        src = msg["src"]
        values = msg.get("values")
        if values:
            self.state.update_values(src, values, t_rx)
        bus = msg.get("bus")
        if isinstance(bus, dict):
            self.state.update_health(src, bus, t_rx)
        health = msg.get("health")
        if isinstance(health, dict):
            self.state.update_health(src, health, t_rx)

    # -- diag --------------------------------------------------------------------------------
    def diag_message(self) -> dict:
        snap = self.state.snapshot()
        return {
            "type": "diag",
            "v": 1,
            "clock": self.clock.status(),
            "values": snap["values"],
            "health": snap["health"],
            "core": {
                "udp_rx": self.stats.get("udp_rx", 0),
                "udp_rejected": self.stats.get("udp_rejected", 0),
                "ws_clients": len(self.hub.clients),
                "uptime_s": round(max(0.0, self.clock.monotonic() - self.started_mono), 3),
            },
            "log": {"derived": None, "events_written": 0},
        }

    def tick_once(self) -> None:
        self.ticks += 1
        self.hub.publish(json.dumps(self.diag_message(), separators=(",", ":")))

    async def _tick_loop(self) -> None:
        target = math.floor(self.clock.monotonic()) + 1
        while True:
            await self.clock.sleep_until(target)
            try:
                self.tick_once()
            except Exception:
                log.exception("tick failed")
            # never back-fill skipped seconds after a sim-time jump
            target = math.floor(self.clock.monotonic()) + 1

    # -- lifecycle ---------------------------------------------------------------------------
    async def startup(self) -> None:
        self.started_mono = self.clock.monotonic()
        self._transport, _ = await start_udp_listener(
            self.udp_host, self.udp_port, self.on_message, stats=self.stats
        )
        self._tasks.append(asyncio.create_task(self._tick_loop(), name="jabuka-tick"))

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        if self._transport is not None:
            self._transport.close()
            self._transport = None


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-core", description="Jabuka core: state, logs, diagnostics web app."
    )
    p.add_argument("--http-host", default="0.0.0.0")
    p.add_argument("--http-port", type=int, default=8080)
    p.add_argument("--udp-host", default="127.0.0.1")
    p.add_argument("--udp-port", type=int, default=messages.DEFAULT_UDP_PORT)
    p.add_argument("--data-dir", type=Path, default=Path("./var"))
    p.add_argument("--clock", choices=("system", "sim"), default="system")
    p.add_argument("--log-level", default="WARNING")
    return p


async def serve(args: argparse.Namespace) -> int:
    ctx = CoreContext.create(
        make_clock(args.clock), args.data_dir, udp_host=args.udp_host, udp_port=args.udp_port
    )
    app = create_app(ctx)
    config = uvicorn.Config(
        app,
        host=args.http_host,
        port=args.http_port,
        workers=1,
        log_level="warning",
        ws="websockets",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    await server.serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(serve(args))


if __name__ == "__main__":
    sys.exit(main())
