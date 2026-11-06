"""gpsd JSON client (asyncio), runs inside jabuka-core.

Connects to gpsd, sends ``?WATCH={"enable":true,"json":true};`` and reads one JSON object per line.
Every line goes to the raw gps log FIRST, then parse_line, then on_object(obj, t_rx). VERSION,
DEVICES and WATCH only update health. Hostile input (invalid JSON, non-objects, missing "class",
lines over MAX_LINE bytes) is counted in health["rejected_lines"] and never raises. On EOF or a
socket error the client reports connected=False and reconnects forever with a 1 -> 5 s backoff.

gpsd field semantics (gpsd_json(5)): TPV mode 0/1 = no fix, 2 = 2D, 3 = 3D; time is ISO8601 UTC
and may be present but invalid without a fix; track = course over ground, degrees TRUE;
speed = m/s; eph = horizontal error (m). SKY uSat/nSat/hdop, satellites[].used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

log = logging.getLogger("jabuka.ingest.gpsd")

MAX_LINE = 8192
WATCH_CMD = b'?WATCH={"enable":true,"json":true};\n'
SRC = "gpsd"


class RawLog(Protocol):
    def write_line(self, text: str) -> None: ...


# -- pure helpers ------------------------------------------------------------------------------
def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite constant {name}")


def _num(x: Any) -> float | None:
    """A finite real number (bools excluded), else None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    return f if math.isfinite(f) else None


def parse_line(line: bytes) -> dict | None:
    """One gpsd line -> dict with a str "class", or None (invalid JSON/UTF-8, NaN/Infinity,
    non-object, missing class, longer than MAX_LINE)."""
    if not isinstance(line, (bytes, bytearray)) or len(line) > MAX_LINE:
        return None
    text = bytes(line).strip()
    if not text:
        return None
    try:
        obj = json.loads(text.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("class"), str):
        return None
    return obj


def tpv_epoch(tpv: dict) -> float | None:
    """UTC epoch of a TPV's "time" (None if absent/unparseable). No validity checks here: the
    clock decides whether to trust it."""
    t = tpv.get("time")
    if not isinstance(t, str):
        return None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


def _mode(obj: dict) -> int:
    m = obj.get("mode")
    if isinstance(m, bool) or not isinstance(m, int):
        return 0
    return m


def tpv_to_values(tpv: dict) -> list[dict]:
    """TPV -> value entries. Always gps.mode; position/COG/SOG/datetime/eph only with mode >= 2.

    navigation.position {latitude, longitude} deg; courseOverGroundTrue rad (gpsd track is
    degrees TRUE); speedOverGround m/s (gpsd speed is already m/s); navigation.datetime ISO str.
    """
    mode = _mode(tpv)
    out: list[dict] = [{"path": "gps.mode", "value": mode, "unit": None}]
    if mode < 2:
        return out
    lat, lon = _num(tpv.get("lat")), _num(tpv.get("lon"))
    if lat is not None and lon is not None and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
        out.append(
            {
                "path": "navigation.position",
                "value": {"latitude": lat, "longitude": lon},
                "unit": "deg",
            }
        )
    track = _num(tpv.get("track"))
    if track is not None:
        out.append(
            {
                "path": "navigation.courseOverGroundTrue",
                "value": math.radians(track % 360.0),
                "unit": "rad",
                "ref": "T",
            }
        )
    speed = _num(tpv.get("speed"))
    if speed is not None and speed >= 0.0:
        out.append({"path": "navigation.speedOverGround", "value": speed, "unit": "m/s"})
    t = tpv.get("time")
    if isinstance(t, str) and len(t) <= 64:
        out.append({"path": "navigation.datetime", "value": t, "unit": None})
    eph = _num(tpv.get("eph"))
    if eph is not None and eph >= 0.0:
        out.append({"path": "gps.eph", "value": eph, "unit": "m"})
    return out


def _sky_counts(sky: dict) -> tuple[int | None, int | None, float | None]:
    used = sky.get("uSat")
    seen = sky.get("nSat")
    used = used if isinstance(used, int) and not isinstance(used, bool) else None
    seen = seen if isinstance(seen, int) and not isinstance(seen, bool) else None
    sats = sky.get("satellites")
    if isinstance(sats, list):
        if used is None:
            used = sum(1 for s in sats if isinstance(s, dict) and s.get("used") is True)
        if seen is None:
            seen = sum(1 for s in sats if isinstance(s, dict))
    return used, seen, _num(sky.get("hdop"))


def sky_to_values(sky: dict) -> list[dict]:
    """SKY -> gps.satellitesUsed / gps.satellitesVisible / gps.hdop (uSat/nSat preferred,
    otherwise counted from satellites[].used)."""
    used, seen, hdop = _sky_counts(sky)
    out: list[dict] = []
    if used is not None:
        out.append({"path": "gps.satellitesUsed", "value": used, "unit": None})
    if seen is not None:
        out.append({"path": "gps.satellitesVisible", "value": seen, "unit": None})
    if hdop is not None:
        out.append({"path": "gps.hdop", "value": hdop, "unit": None})
    return out


# -- line splitting ----------------------------------------------------------------------------
class LineSplitter:
    """Bytes -> complete lines. A line longer than max_line is dropped (yielded as an
    ``Overlong`` marker carrying its first max_line bytes) and the stream resyncs at the next
    newline, so a hostile peer can never grow memory."""

    def __init__(self, max_line: int = MAX_LINE) -> None:
        self.max_line = max_line
        self.buf = bytearray()
        self._discarding = False
        self._discard_head = b""

    def feed(self, data: bytes) -> list[bytes | Overlong]:
        out: list[bytes | Overlong] = []
        self.buf += data
        while True:
            nl = self.buf.find(b"\n")
            if nl < 0:
                if len(self.buf) > self.max_line:
                    if not self._discarding:
                        self._discard_head = bytes(self.buf[: self.max_line])
                    self._discarding = True
                    self.buf.clear()
                break
            line = bytes(self.buf[:nl])
            del self.buf[: nl + 1]
            if self._discarding:
                self._discarding = False
                out.append(Overlong(self._discard_head))
                self._discard_head = b""
                continue
            line = line.rstrip(b"\r")
            if len(line) > self.max_line:
                out.append(Overlong(line[: self.max_line]))
                continue
            out.append(line)
        return out


class Overlong:
    __slots__ = ("head",)

    def __init__(self, head: bytes) -> None:
        self.head = head


# -- client ------------------------------------------------------------------------------------
class GpsdClient:
    def __init__(
        self,
        host: str,
        port: int,
        on_object: Callable[[dict, float], None],
        raw_log: RawLog | None,
        *,
        health: Callable[[dict], None] | None = None,
        mono: Callable[[], float] = time.monotonic,
        backoff_min: float = 1.0,
        backoff_max: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.on_object = on_object
        self.raw_log = raw_log
        self._health_cb = health
        self._mono = mono
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self.health: dict[str, Any] = {
            "connected": False,
            "device": None,
            "mode": None,
            "sats_used": None,
            "sats_visible": None,
            "hdop": None,
            "tpv_rx": 0,
            "sky_rx": 0,
            "rejected_lines": 0,
            "reconnects": 0,
            "last_error": None,
            "handler_errors": 0,
            "raw_errors": 0,
            "server": f"{host}:{port}",
        }
        self._ever_connected = False

    # -- health --------------------------------------------------------------------------------
    def _report(self) -> None:
        if self._health_cb is None:
            return
        try:
            self._health_cb(dict(self.health))
        except Exception:
            log.exception("gps health callback failed")

    # -- per line ------------------------------------------------------------------------------
    def _raw(self, text: str) -> None:
        if self.raw_log is None:
            return
        try:
            self.raw_log.write_line(text)
        except (OSError, ValueError) as e:  # disk full / closed log: keep live data flowing
            self.health["raw_errors"] += 1
            log.error("gps raw log write failed: %s", e)

    def handle_line(self, line: bytes | Overlong) -> None:
        """Raw log FIRST, then parse, then dispatch. Never raises."""
        if isinstance(line, Overlong):
            self._raw(line.head.decode("utf-8", errors="replace"))
            self.health["rejected_lines"] += 1
            self._report()
            return
        self._raw(line.decode("utf-8", errors="replace"))
        obj = parse_line(line)
        if obj is None:
            if line.strip():
                self.health["rejected_lines"] += 1
                self._report()
            return
        t_rx = self._mono()
        cls = obj["class"]
        h = self.health
        if cls == "TPV":
            h["tpv_rx"] += 1
            h["mode"] = _mode(obj)
        elif cls == "SKY":
            h["sky_rx"] += 1
            used, seen, hdop = _sky_counts(obj)
            if used is not None:
                h["sats_used"] = used
            if seen is not None:
                h["sats_visible"] = seen
            if hdop is not None:
                h["hdop"] = hdop
        elif cls == "DEVICES":
            devs = obj.get("devices")
            if isinstance(devs, list) and devs and isinstance(devs[0], dict):
                path = devs[0].get("path")
                if isinstance(path, str):
                    h["device"] = path[:128]
        elif cls == "DEVICE":
            path = obj.get("path")
            if isinstance(path, str) and h["device"] is None:
                h["device"] = path[:128]
        if cls in ("TPV", "SKY"):
            try:
                self.on_object(obj, t_rx)
            except Exception:
                h["handler_errors"] += 1
                log.exception("gps object handler failed")
        self._report()

    # -- connection loop -----------------------------------------------------------------------
    async def _session(self) -> None:
        # Lines are split by LineSplitter (bounded at MAX_LINE, resyncs after an overlong line)
        # rather than StreamReader.readline, whose overrun handling loses the resync point.
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(WATCH_CMD)
            await writer.drain()
            if self._ever_connected:
                self.health["reconnects"] += 1
            self._ever_connected = True
            self.health["connected"] = True
            self.health["last_error"] = None
            self._report()
            splitter = LineSplitter(MAX_LINE)
            while True:
                data = await reader.read(4096)
                if not data:
                    self.health["last_error"] = "EOF"
                    return
                for line in splitter.feed(data):
                    self.handle_line(line)
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1.0)
            except (OSError, TimeoutError, asyncio.CancelledError):
                pass

    async def run(self) -> None:
        """Connect, read, reconnect forever (until cancelled). Never raises otherwise."""
        delay = self.backoff_min
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                self._disconnected()
                raise
            except (OSError, ConnectionError, ValueError, asyncio.IncompleteReadError) as e:
                self.health["last_error"] = f"{type(e).__name__}: {e}"[:200]
            except Exception as e:  # defensive: the client must never die
                self.health["last_error"] = f"{type(e).__name__}: {e}"[:200]
                log.exception("gpsd client error")
            if self.health["connected"]:
                delay = self.backoff_min  # a session that came up resets the backoff
            self._disconnected()
            await asyncio.sleep(delay)
            delay = min(self.backoff_max, delay * 2)

    def _disconnected(self) -> None:
        if self.health["connected"]:
            self.health["connected"] = False
            self.health["mode"] = None
        self._report()


async def run_gpsd_client(
    host: str,
    port: int,
    on_object: Callable[[dict, float], None],
    raw_log: RawLog | None,
    *,
    health: Callable[[dict], None] | None = None,
    mono: Callable[[], float] = time.monotonic,
    backoff_min: float = 1.0,
    backoff_max: float = 5.0,
) -> None:
    """Run a GpsdClient forever (cancel the task to stop)."""
    client = GpsdClient(
        host,
        port,
        on_object,
        raw_log,
        health=health,
        mono=mono,
        backoff_min=backoff_min,
        backoff_max=backoff_max,
    )
    await client.run()
