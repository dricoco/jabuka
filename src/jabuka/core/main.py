"""jabuka-core: state store, UDP bus listener, 1 Hz tick, diagnostics web app (one asyncio loop)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import signal
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn

from jabuka.common import messages, sdnotify
from jabuka.common.clock import Clock, SimClock, make_clock
from jabuka.core.bus import start_udp_listener
from jabuka.core.derived_log import DerivedLogger
from jabuka.core.state import StateStore
from jabuka.core.web import Hub, create_app
from jabuka.ingest.gpsd_client import run_gpsd_client, sky_to_values, tpv_epoch, tpv_to_values
from jabuka.ingest.rawlog import RotatingAppendLog

log = logging.getLogger("jabuka.core")


EVENT_MIN_INTERVAL_S = 1.0


@dataclass
class CoreContext:
    clock: Clock
    state: StateStore
    hub: Hub
    data_dir: Path
    bus_log: RotatingAppendLog | None = None
    derived: DerivedLogger | None = None
    events_log: RotatingAppendLog | None = None
    gps_log: RotatingAppendLog | None = None
    gpsd: tuple[str, int] | None = None
    udp_host: str = "127.0.0.1"
    udp_port: int = messages.DEFAULT_UDP_PORT
    stats: dict[str, int] = field(
        default_factory=lambda: {"udp_rx": 0, "udp_rejected": 0, "handler_errors": 0}
    )
    started_mono: float = 0.0
    ticks: int = 0
    events_written: int = 0
    last_event_mono: float | None = None
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
        gpsd: tuple[str, int] | None = None,
    ) -> CoreContext:
        data_dir = Path(data_dir)
        logs = data_dir / "logs"
        # Every core log runs on the injected clock, so sim replays rotate on sim time.
        bus_log = RotatingAppendLog(
            logs / "bus",
            "bus",
            mono=clock.monotonic,
            wall=clock.wall,
            guard_prefixes=("bus",),
        )
        events_log = RotatingAppendLog(
            logs / "events",
            "events",
            suffix=".jsonl",
            mono=clock.monotonic,
            wall=clock.wall,
            guard_prefixes=(),
        )
        gps_log = None
        if gpsd is not None:
            # raw gpsd JSON lines, written before parsing (raw-first)
            gps_log = RotatingAppendLog(
                logs / "gps",
                "gps",
                mono=clock.monotonic,
                wall=clock.wall,
                guard_prefixes=("gps",),
            )
        return cls(
            clock=clock,
            state=StateStore(clock),
            hub=Hub(),
            data_dir=data_dir,
            bus_log=bus_log,
            derived=DerivedLogger(logs / "derived", clock),
            events_log=events_log,
            gps_log=gps_log,
            gpsd=gpsd,
            udp_host=udp_host,
            udp_port=udp_port,
        )

    def logs(self) -> list[Any]:
        return [
            x for x in (self.bus_log, self.derived, self.events_log, self.gps_log) if x is not None
        ]

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

    # -- gps ---------------------------------------------------------------------------------
    def _discipline_clock(self, tpv: dict) -> None:
        """Feed a TPV to the clock BEFORE stamping t_rx (SimClock follows sane fix times)."""
        clock = self.clock
        if isinstance(clock, SimClock):
            mode = tpv.get("mode")
            if isinstance(mode, int) and not isinstance(mode, bool) and mode >= 2:
                epoch = tpv_epoch(tpv)
                if epoch is not None:
                    clock.observe_utc(epoch)

    def on_gps_object(self, obj: dict, _t_client: float = 0.0) -> None:
        """TPV/SKY from the gpsd client -> state (src "gpsd")."""
        cls = obj.get("class")
        if cls == "TPV":
            self._discipline_clock(obj)
            values = tpv_to_values(obj)
        elif cls == "SKY":
            values = sky_to_values(obj)
        else:
            return
        if values:
            self.state.update_values("gpsd", values, self.clock.monotonic())

    def on_gps_health(self, health: dict) -> None:
        self.state.update_health("gps", health, self.clock.monotonic())

    # -- events ------------------------------------------------------------------------------
    def record_event(self, label: str) -> dict | None:
        """Append an fsync'd event marker. Returns None when rate-limited (1 per second)."""
        now = self.clock.monotonic()
        if self.last_event_mono is not None and now - self.last_event_mono < EVENT_MIN_INTERVAL_S:
            return None
        status = self.clock.status()
        n = self.events_written + 1
        rec = {
            "type": "event",
            "n": n,
            "label": label,
            "t_mono": now,
            "t_wall": self.clock.wall(),
            "utc": status.get("utc"),
            "clock": status,
            "state_ref": self.derived.current_name if self.derived is not None else None,
        }
        assert self.events_log is not None
        self.events_log.write_json(rec, fsync_now=True)
        self.events_written = n
        self.last_event_mono = now
        return rec

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
            "log": {
                "derived": self.derived.current_name if self.derived is not None else None,
                "events_written": self.events_written,
            },
        }

    def tick_once(self) -> None:
        self.ticks += 1
        diag = self.diag_message()
        if self.derived is not None:
            try:
                self.derived.write(diag)  # derived line BEFORE publishing
                diag["log"]["derived"] = self.derived.current_name
            except Exception:
                log.exception("derived log write failed")
        for lg in self.logs():
            try:
                lg.maybe_flush()
            except Exception:
                log.exception("log flush failed")
        self.hub.publish(json.dumps(diag, separators=(",", ":")))

    async def _tick_loop(self, first_target: float) -> None:
        target = first_target
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
            self.udp_host,
            self.udp_port,
            self.on_message,
            stats=self.stats,
            bus_log=self.bus_log,
        )
        # first target computed now, not when the task first runs, so no second is skipped
        first = math.floor(self.clock.monotonic()) + 1
        self._tasks.append(asyncio.create_task(self._tick_loop(first), name="jabuka-tick"))
        if self.gpsd is not None:
            host, port = self.gpsd
            self._tasks.append(
                asyncio.create_task(
                    run_gpsd_client(
                        host,
                        port,
                        self.on_gps_object,
                        self.gps_log,
                        health=self.on_gps_health,
                        mono=self.clock.monotonic,
                    ),
                    name="jabuka-gpsd",
                )
            )
        interval = sdnotify.watchdog_interval()
        if interval is not None:
            self._tasks.append(
                asyncio.create_task(sdnotify.watchdog_loop(interval), name="jabuka-watchdog")
            )
        sdnotify.notify("READY=1")  # UDP listener bound, tick running

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
        self.close_logs()

    def close_logs(self) -> None:
        for lg in self.logs():
            try:
                lg.close()
            except Exception:
                log.exception("log close failed")


def parse_gpsd(text: str) -> tuple[str, int] | None:
    """--gpsd HOST:PORT | none"""
    if text.strip().lower() == "none":
        return None
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise argparse.ArgumentTypeError(f"expected HOST:PORT or none, got {text!r}")
    return host, int(port)


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
    p.add_argument(
        "--gpsd",
        type=parse_gpsd,
        default=None,
        metavar="HOST:PORT|none",
        help="gpsd to read GPS from (Pi: 127.0.0.1:2947; default none)",
    )
    p.add_argument("--log-level", default="WARNING")
    return p


class CoreServer(uvicorn.Server):
    """uvicorn.Server with our own SIGTERM/SIGINT handling.

    Stock uvicorn re-raises a captured SIGTERM with the default handler after its graceful
    shutdown, so the process would die with -15 instead of exiting 0. Here the signal sends
    STOPPING=1 and sets should_exit; the lifespan shutdown then closes (fsyncs) every log.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        try:
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(signum, self._on_signal, signum)
        except (RuntimeError, ValueError, NotImplementedError):  # not the main thread
            loop = None
        try:
            yield
        finally:
            if loop is not None:
                for signum in (signal.SIGTERM, signal.SIGINT):
                    loop.remove_signal_handler(signum)

    signalled = False

    def _on_signal(self, signum: int) -> None:
        self.signalled = True
        sdnotify.notify("STOPPING=1")
        if self.should_exit and signum == signal.SIGINT:
            self.force_exit = True
        self.should_exit = True


def build_context(args: argparse.Namespace) -> CoreContext:
    """CoreContext from parsed jabuka-core flags (also used by tests)."""
    return CoreContext.create(
        make_clock(args.clock),
        args.data_dir,
        udp_host=args.udp_host,
        udp_port=args.udp_port,
        gpsd=args.gpsd,
    )


async def serve(args: argparse.Namespace) -> int:
    ctx = build_context(args)
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
    server = CoreServer(config)
    try:
        await server.serve()
    finally:
        ctx.close_logs()  # idempotent; covers a failed startup too
    return 0 if server.started or server.signalled else 1


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(serve(args))


if __name__ == "__main__":
    sys.exit(main())
