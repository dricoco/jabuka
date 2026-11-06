"""jabuka-core: state store, UDP bus listener, 1 Hz tick (nav + diag), helm web app (one asyncio
loop)."""

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
from jabuka.core.nav_service import NavService
from jabuka.core.state import StateStore
from jabuka.core.tiles import Racepack
from jabuka.core.web import Hub, create_app
from jabuka.ingest.gpsd_client import run_gpsd_client, sky_to_values, tpv_epoch, tpv_to_values
from jabuka.ingest.rawlog import RotatingAppendLog
from jabuka.ingest.retention import Retention

log = logging.getLogger("jabuka.core")


EVENT_MIN_INTERVAL_S = 1.0


@dataclass
class CoreContext:
    clock: Clock
    state: StateStore
    hub: Hub
    data_dir: Path
    nav: NavService
    racepack_dir: Path | None = None
    racepack: Racepack | None = None  # built by tiles.racepack_router (index once, at startup)
    bus_log: RotatingAppendLog | None = None
    derived: DerivedLogger | None = None
    events_log: RotatingAppendLog | None = None
    gps_log: RotatingAppendLog | None = None
    retention: Retention | None = None
    gpsd: tuple[str, int] | None = None
    udp_host: str = "127.0.0.1"
    udp_port: int = messages.DEFAULT_UDP_PORT
    stats: dict[str, int] = field(
        default_factory=lambda: {
            "udp_rx": 0,
            "udp_rejected": 0,
            "handler_errors": 0,
            # log write failures: the journal is volatile, so they must show on the page (WR-06)
            "derived_errors": 0,
            "bus_log_errors": 0,
            "events_errors": 0,
            "flush_errors": 0,
            "nav_errors": 0,
        }
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
        bus_log: bool = False,
        log_budget_bytes: int | None = None,
        racepack_dir: Path | None = None,
    ) -> CoreContext:
        """bus_log: also log every accepted datagram (logs/bus, ~4 GB/day at full bus load; the
        raw log plus the deterministic decoder reproduces it), so it is opt-in."""
        data_dir = Path(data_dir)
        racepack_dir = Path(racepack_dir) if racepack_dir is not None else data_dir / "racepack"
        logs = data_dir / "logs"
        # Every core log runs on the injected clock, so sim replays rotate on sim time.
        bus = None
        if bus_log:
            bus = RotatingAppendLog(logs / "bus", "bus", mono=clock.monotonic, wall=clock.wall)
        events_log = RotatingAppendLog(
            logs / "events",
            "events",
            suffix=".jsonl",
            mono=clock.monotonic,
            wall=clock.wall,
        )
        gps_log = None
        if gpsd is not None:
            # raw gpsd JSON lines, written before parsing (raw-first)
            gps_log = RotatingAppendLog(logs / "gps", "gps", mono=clock.monotonic, wall=clock.wall)
        # one retention policy for the whole data volume; the core owns the budgets
        retention = Retention(logs, budget_bytes=log_budget_bytes, mono=clock.monotonic)
        state = StateStore(clock)
        return cls(
            clock=clock,
            state=state,
            hub=Hub(),
            data_dir=data_dir,
            nav=NavService(state, clock, data_dir, racepack_dir),
            racepack_dir=racepack_dir,
            bus_log=bus,
            derived=DerivedLogger(logs / "derived", clock),
            events_log=events_log,
            gps_log=gps_log,
            retention=retention,
            gpsd=gpsd,
            udp_host=udp_host,
            udp_port=udp_port,
        )

    def logs(self) -> list[Any]:
        return [
            x for x in (self.bus_log, self.derived, self.events_log, self.gps_log) if x is not None
        ]

    def open_log_paths(self) -> list[Path]:
        out = []
        for lg in (self.bus_log, self.events_log, self.gps_log):
            if lg is not None and lg.current_path is not None:
                out.append(lg.current_path)
        if self.derived is not None and self.derived.log.current_path is not None:
            out.append(self.derived.log.current_path)
        return out

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
    def _discipline_clock(self, tpv: dict) -> bool:
        """Feed a TPV to the clock BEFORE stamping t_rx: GpsClock disciplines itself from it,
        SimClock follows the fix time. False when the GPS clock rejected the fix (no fix,
        rollover date, ...), so its time must not be published either."""
        clock = self.clock
        on_tpv = getattr(clock, "on_tpv", None)
        if callable(on_tpv):
            return bool(on_tpv(tpv, clock.monotonic()))
        if isinstance(clock, SimClock):
            mode = tpv.get("mode")
            if isinstance(mode, int) and not isinstance(mode, bool) and mode >= 2:
                epoch = tpv_epoch(tpv)
                if epoch is not None:
                    clock.observe_utc(epoch)
        return True

    def on_gps_object(self, obj: dict, _t_client: float = 0.0) -> None:
        """TPV/SKY from the gpsd client -> state (src "gpsd")."""
        cls = obj.get("class")
        if cls == "TPV":
            accepted = self._discipline_clock(obj)
            values = tpv_to_values(obj)
            if not accepted:  # IN-04: a rejected time (e.g. a 2006 rollover date) is not data
                values = [v for v in values if v["path"] != "navigation.datetime"]
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
        try:
            self.events_log.write_json(rec, fsync_now=True)
        except (OSError, ValueError):
            self.stats["events_errors"] = self.stats.get("events_errors", 0) + 1
            log.exception("event marker write failed")
            raise
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
                "handler_errors": self.stats.get("handler_errors", 0),
                "derived_errors": self.stats.get("derived_errors", 0),
                "bus_log_errors": self.stats.get("bus_log_errors", 0),
                "events_errors": self.stats.get("events_errors", 0),
                "flush_errors": self.stats.get("flush_errors", 0),
                "nav_errors": self.stats.get("nav_errors", 0),
                "ws_clients": len(self.hub.clients),
                "uptime_s": round(max(0.0, self.clock.monotonic() - self.started_mono), 3),
                "disk": self.retention.status() if self.retention is not None else None,
            },
            "log": {
                "derived": self.derived.current_name if self.derived is not None else None,
                "events_written": self.events_written,
            },
        }

    def update_nav(self) -> dict | None:
        """One nav computation (never raises; failures counted in stats nav_errors)."""
        try:
            msg = self.nav.update()
        except Exception:
            self.stats["nav_errors"] = self.stats.get("nav_errors", 0) + 1
            log.exception("nav update failed")
            return None
        self.stats["nav_errors"] = max(self.stats.get("nav_errors", 0), self.nav.errors)
        return msg

    def nav_text(self, msg: dict | None) -> str | None:
        if msg is None:
            return None
        try:
            return json.dumps(msg, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            self.stats["nav_errors"] = self.stats.get("nav_errors", 0) + 1
            log.exception("nav message not serializable")
            return None

    def publish_nav(self) -> None:
        """Fresh nav message to every client now (after a course/settings change)."""
        text = self.nav_text(self.update_nav())
        if text is not None:
            self.hub.publish(text)

    def record_racepack_health(self) -> None:
        """Race-pack state in the health table (src "racepack"), refreshed every tick."""
        if self.racepack is not None:
            self.state.update_health("racepack", self.racepack.info(), self.clock.monotonic())

    def tick_once(self) -> None:
        self.ticks += 1
        self.record_racepack_health()
        nav = self.update_nav()  # first: its nav.* rows go into this tick's derived line
        diag = self.diag_message()
        if self.derived is not None:
            try:
                self.derived.write(diag)  # derived line BEFORE publishing
                diag["log"]["derived"] = self.derived.current_name
            except Exception:
                self.stats["derived_errors"] = self.stats.get("derived_errors", 0) + 1
                log.exception("derived log write failed")
        for lg in self.logs():
            try:
                lg.maybe_flush()
            except Exception:
                self.stats["flush_errors"] = self.stats.get("flush_errors", 0) + 1
                log.exception("log flush failed")
        if self.retention is not None:
            self.retention.maybe_run(protect=self.open_log_paths())  # never raises
        self.hub.publish(json.dumps(diag, separators=(",", ":")))
        nav_text = self.nav_text(nav)
        if nav_text is not None:
            self.hub.publish(nav_text)

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
        if self.racepack is not None:
            self.racepack.close()

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
    p.add_argument(
        "--http-host",
        default="127.0.0.1",
        help="bind address (default 127.0.0.1; the Pi unit passes 0.0.0.0 for the AP)",
    )
    p.add_argument("--http-port", type=int, default=8080)
    p.add_argument("--udp-host", default="127.0.0.1")
    p.add_argument("--udp-port", type=int, default=messages.DEFAULT_UDP_PORT)
    p.add_argument("--data-dir", type=Path, default=Path("./var"))
    p.add_argument(
        "--racepack",
        type=Path,
        default=None,
        metavar="DIR",
        help="race pack directory (race.pmtiles, seamarks.geojson, coastline.geojson, "
        "polar.json; default <data-dir>/racepack)",
    )
    p.add_argument(
        "--clock",
        choices=("system", "sim", "gps"),
        default="system",
        help="time source: system (unvalidated), sim (replay/sim t_sim), gps (Pi: gpsd fixes)",
    )
    p.add_argument(
        "--gpsd",
        type=parse_gpsd,
        default=None,
        metavar="HOST:PORT|none",
        help="gpsd to read GPS from (Pi: 127.0.0.1:2947; default none)",
    )
    p.add_argument(
        "--bus-log",
        choices=("off", "on"),
        default="off",
        help="also log every accepted UDP datagram to logs/bus (~4 GB/day at full bus load; "
        "default off: the raw log reproduces it)",
    )
    p.add_argument(
        "--log-budget-gb",
        type=_positive_float,
        default=None,
        metavar="GB",
        help="total size budget for logs/ (default: half of the data filesystem)",
    )
    p.add_argument("--log-level", default="WARNING")
    return p


def _positive_float(text: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {text!r}") from None
    if not math.isfinite(v) or v <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive number, got {text!r}")
    return v


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
        bus_log=args.bus_log == "on",
        log_budget_bytes=(
            int(args.log_budget_gb * 1_000_000_000) if args.log_budget_gb is not None else None
        ),
        racepack_dir=getattr(args, "racepack", None),
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
