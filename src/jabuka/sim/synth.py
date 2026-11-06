"""jabuka-sim: L2 synthetic boat with fault injection, through the same pipeline as live data.

Scripted true wind (TWD + linear shift, TWS + sinusoidal gust) and a simple boat (fixed heading or
fixed TWA, placeholder BSP curve; the real X35 polar is Phase 2's WIND-01). Apparent wind comes
from jabuka.common.conventions.apparent_from_true; position from dead reckoning (COG = heading,
SOG = BSP). One emission per simulated second, sleeping 1/speed real seconds.

Outputs:
- udp mode: schema-v1 deltas (src "fastnet", SI units, t_sim = sim UTC) plus a 1 Hz health
  heartbeat that also carries t_sim, so a core on --clock sim keeps advancing while the bus is
  silent.
- pty mode: encoded Fastnet Broadcast frames into a pty, read by the real jabuka-ingest-fastnet.
- GPS (both modes): an embedded FakeGpsd on --gpsd-port (default 2948, never the real 2947).

Faults ``KIND@START+DUR`` (sim seconds, active while START <= t < START+DUR): bus-silent,
gps-loss, garbage, clock-jump.

Closed loop (``--follow URL``, plan 02-04): each simulated second the boat reads the core's own
GET URL/api/nav and steers to it like a helmsman: on twa_up/twa_down it holds the target TWA on
its current tack (heading = TWD - s * target, starting on starboard); it tacks (10 s at half speed)
when the layline is overstood or the countdown reaches 0; when fetching or on a reach it steers the
bearing to the mark; it never turns back to a mark it has just passed (holds its heading while the
core decides the rounding). Boat speed comes from the X35 polar x the core's efficiency. Without
--follow nothing changes.

Dev tool only (never in a systemd unit); it may read the wall clock.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import socket
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jabuka.common import messages
from jabuka.common.conventions import apparent_from_true, true_to_mag
from jabuka.common.units import kn_to_ms, ms_to_kn, wrap_2pi, wrap_pi
from jabuka.ingest.fastnet_encode import frame, rec01, rec08
from jabuka.nav.polar import Polar, default_polar
from jabuka.sim.fake_gpsd import DEVICE_PATH, FakeGpsd, utc_iso
from jabuka.sim.pty_replay import PtyFeeder

FAULT_KINDS = ("bus-silent", "gps-loss", "garbage", "clock-jump")
EARTH_R = 6371000.0
BSP_MAX_KN = 8.5


# -- configuration -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Fault:
    kind: str
    start: float
    dur: float

    def active(self, t: float) -> bool:
        return self.start <= t < self.start + self.dur

    def __str__(self) -> str:
        return f"{self.kind}@{self.start:g}+{self.dur:g}"


def parse_fault(text: str) -> Fault:
    """``KIND@START+DUR`` in sim seconds, e.g. ``gps-loss@120+30``."""
    kind, sep, rest = text.partition("@")
    start, sep2, dur = rest.partition("+")
    if not sep or not sep2 or kind not in FAULT_KINDS:
        raise ValueError(f"bad fault {text!r}: expected KIND@START+DUR, KIND in {FAULT_KINDS}")
    s, d = float(start), float(dur)
    if not (math.isfinite(s) and math.isfinite(d)) or s < 0 or d <= 0:
        raise ValueError(f"bad fault window in {text!r}")
    return Fault(kind, s, d)


@dataclass
class SynthConfig:
    mode: str = "udp"  # udp | pty
    speed: float = 1.0
    duration: float = 600.0  # sim seconds
    twd: float = 330.0  # deg true, FROM
    tws: float = 12.0  # kn
    shift: float = 0.0  # deg per hour (veer positive)
    gust: float = 0.0  # kn amplitude, 120 s period
    heading: float | None = None  # deg true; None -> steer a fixed TWA
    twa: float = 45.0  # deg, signed, starboard positive
    start: tuple[float, float] = (43.73, 15.75)
    variation: float = 5.0  # deg, East-positive
    udp: tuple[str, int] = ("127.0.0.1", messages.DEFAULT_UDP_PORT)
    gpsd_host: str = "127.0.0.1"
    gpsd_port: int = 2948
    link: Path | None = None
    faults: list[Fault] = field(default_factory=list)
    jump_s: float = 3600.0
    seed: int = 0
    start_utc: float | None = None  # sim UTC epoch at t=0 (default: now, whole second)
    wait_gpsd_s: float = 0.0  # wait for a gpsd client to WATCH before starting
    wait_reader_s: float = 0.0  # pty mode: wait for a reader to open the pty before starting
    follow: str | None = None  # core base URL: closed-loop steering from its /api/nav


# -- boat model --------------------------------------------------------------------------------
def synthetic_bsp(tws_kn: float, twa_abs: float) -> float:
    """Placeholder BSP (kn): 0 at TWA 0, peak on a reach, monotone non-decreasing in TWS, at most
    8.5 kn. Not the X35 polar (Phase 2 WIND-01)."""
    a = min(abs(twa_abs), math.pi)
    a_deg = math.degrees(a)
    if a_deg <= 100.0:
        angle = math.sin(math.radians(a_deg * 0.9))
    else:  # ease off towards a run: 1.0 at 100 deg -> 0.8 at 180 deg
        angle = 1.0 - 0.2 * (a_deg - 100.0) / 80.0
    speed = 1.0 - math.exp(-max(0.0, tws_kn) / 7.0)
    return BSP_MAX_KN * speed * max(0.0, angle)


@dataclass
class SynthState:
    t: float  # sim seconds since start
    twd: float  # rad true FROM
    tws: float  # m/s
    twa: float  # rad signed
    hdg: float  # rad true
    bsp: float  # m/s
    awa: float  # rad signed
    aws: float  # m/s
    lat: float  # deg
    lon: float  # deg


class SynthBoat:
    def __init__(self, cfg: SynthConfig) -> None:
        self.cfg = cfg
        self.t = 0.0
        self.lat, self.lon = cfg.start
        # closed loop (--follow): commanded heading and the polar speed model
        self.hdg_cmd: float | None = None  # rad true
        self.polar: Polar | None = None
        self.eff = 1.0
        self.bsp_factor = 1.0
        self.state = self._compute()

    def _compute(self) -> SynthState:
        cfg, t = self.cfg, self.t
        twd = wrap_2pi(math.radians(cfg.twd + cfg.shift * t / 3600.0))
        tws_kn = max(0.0, cfg.tws + cfg.gust * math.sin(2.0 * math.pi * t / 120.0))
        if self.hdg_cmd is not None:
            hdg = wrap_2pi(self.hdg_cmd)
        elif cfg.heading is not None:
            hdg = wrap_2pi(math.radians(cfg.heading))
        else:
            hdg = wrap_2pi(twd - math.radians(cfg.twa))
        twa = wrap_pi(twd - hdg)
        if self.polar is not None:
            bsp_kn = self.polar.speed(tws_kn, abs(math.degrees(twa))) * self.eff * self.bsp_factor
            bsp = kn_to_ms(bsp_kn)
        else:
            bsp = kn_to_ms(synthetic_bsp(tws_kn, abs(twa)))
        tws = kn_to_ms(tws_kn)
        aw = apparent_from_true(twd=twd, tws=tws, bsp=bsp, hdg=hdg)
        return SynthState(t, twd, tws, twa, hdg, bsp, aw.awa, aw.aws, self.lat, self.lon)

    def step(self, dt: float = 1.0) -> SynthState:
        """Advance sim time by dt: dead-reckon on the current COG/SOG, then recompute."""
        s = self.state
        dn = s.bsp * math.cos(s.hdg) * dt
        de = s.bsp * math.sin(s.hdg) * dt
        self.lat += math.degrees(dn / EARTH_R)
        self.lon += math.degrees(de / (EARTH_R * math.cos(math.radians(self.lat))))
        self.t += dt
        self.state = self._compute()
        return self.state


# -- closed loop -------------------------------------------------------------------------------
def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x)


def _angle_diff(a_deg: float, b_deg: float) -> float:
    """Signed a - b in degrees, wrapped to (-180, 180]."""
    return math.degrees(wrap_pi(math.radians(a_deg - b_deg)))


class FollowHelm:
    """A helmsman steering to the core's nav message (``--follow``)."""

    TACK_S = 10  # manoeuvre: sim seconds at half speed
    HOLD_NM = 0.5  # a mark this close and behind the bow was just passed: hold the heading

    def __init__(self, base_url: str, start_twa_deg: float) -> None:
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"--follow expects http://HOST:PORT, got {base_url!r}")
        self.url = base_url.rstrip("/") + "/api/nav"
        self.sign = 1 if start_twa_deg >= 0 else -1  # +1 starboard tack, -1 port
        self.start_twa = abs(start_twa_deg)
        self.tack_left = 0
        self.tacks = 0
        self.fetch_errors = 0
        self.last: dict | None = None

    def fetch(self) -> dict | None:
        """GET /api/nav (1 s timeout); None on any failure (the last command is kept)."""
        try:
            with urllib.request.urlopen(self.url, timeout=1.0) as r:  # noqa: S310 (dev tool)
                obj = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError):
            self.fetch_errors += 1
            return None
        return obj if isinstance(obj, dict) and obj.get("type") == "nav" else None

    def command(self, nav: dict | None, state: SynthState) -> tuple[float, float]:
        """(heading deg true, speed factor) for the next simulated second."""
        if nav is not None:
            self.last = nav
        nav = self.last or {}
        hdg_now = math.degrees(state.hdg)
        wind = nav.get("wind") or {}
        twd = _num(wind.get("twd_t"))
        if twd is None:
            twd = math.degrees(state.twd)
        factor = 1.0
        if self.tack_left > 0:
            self.tack_left -= 1
            factor = 0.5
        helm = nav.get("helm") or {}
        lay = nav.get("layline") or {}
        mark = nav.get("mark") or {}
        btw, dtw = _num(mark.get("btw_t")), _num(mark.get("dtw_nm"))
        primary, target = helm.get("primary"), _num(helm.get("target"))

        if btw is not None and dtw is not None and dtw < self.HOLD_NM:
            if abs(_angle_diff(btw, hdg_now)) > 90.0:
                return hdg_now, factor  # just passed: let the core call the rounding
        if primary not in ("twa_up", "twa_down") or target is None:
            if primary == "cts" and btw is not None:
                return self._steer(_num(helm.get("cts_t")) or btw, twd), factor
            return (twd - self.sign * self.start_twa) % 360.0, factor
        if lay.get("state") == "fetching" and btw is not None:
            # lay the mark, never pinching above the target angle
            if abs(_angle_diff(twd, btw)) >= target or primary == "twa_down":
                return self._steer(btw, twd), factor
        my_tack = "stbd" if self.sign > 0 else "port"
        countdown = _num(lay.get("countdown_s"))
        due = lay.get("state") == "overstood" or (countdown is not None and countdown <= 0)
        if due and self.tack_left == 0 and lay.get("tack") == my_tack:
            self.sign = -self.sign
            self.tacks += 1
            self.tack_left = self.TACK_S
            factor = 0.5
        return (twd - self.sign * target) % 360.0, factor

    def _steer(self, heading: float, twd: float) -> float:
        """Steer a heading; the tack follows the side the wind is on."""
        self.sign = 1 if _angle_diff(twd, heading) >= 0 else -1
        return heading % 360.0


# -- encoders ----------------------------------------------------------------------------------
def udp_values(s: SynthState) -> list[dict]:
    return [
        {"path": "environment.wind.angleApparent", "value": s.awa, "unit": "rad"},
        {"path": "environment.wind.speedApparent", "value": s.aws, "unit": "m/s"},
        {"path": "environment.wind.angleTrueWater", "value": s.twa, "unit": "rad"},
        {"path": "environment.wind.speedTrue", "value": s.tws, "unit": "m/s"},
        {"path": "environment.wind.direction", "value": s.twd, "unit": "rad", "ref": "T"},
        {"path": "navigation.heading", "value": s.hdg, "unit": "rad", "ref": "T"},
        {"path": "navigation.speedThroughWater", "value": s.bsp, "unit": "m/s"},
    ]


def fastnet_frame(s: SynthState, variation_deg: float) -> bytes:
    """One Broadcast frame as the B&G bus would carry it (heading MAGNETIC, layout °M)."""
    mag = true_to_mag(s.hdg, math.radians(variation_deg))
    body = (
        rec01(0x41, ms_to_kn(s.bsp), 2)
        + rec01(0x51, round(math.degrees(s.awa)), 0)
        + rec01(0x4F, s.aws, 1)
        + rec01(0x59, round(math.degrees(s.twa)), 0)
        + rec01(0x56, s.tws, 1)
        + rec08(0x49, round(math.degrees(mag)) % 360, 0x66)
    )
    return frame(body)


def gps_objects(s: SynthState, utc: float) -> tuple[dict, dict]:
    tpv = {
        "class": "TPV",
        "device": DEVICE_PATH,
        "mode": 3,
        "time": utc_iso(utc),
        "lat": round(s.lat, 7),
        "lon": round(s.lon, 7),
        "track": round(math.degrees(s.hdg), 2),
        "speed": round(s.bsp, 3),
        "eph": 3.5,
    }
    sky = {"class": "SKY", "device": DEVICE_PATH, "uSat": 9, "nSat": 12, "hdop": 0.9}
    return tpv, sky


def hostile_datagrams(rng: random.Random) -> list[bytes]:
    nan_delta = (
        b'{"v":1,"type":"delta","src":"fastnet","t_mono":1.0,"t_wall":1.0,'
        b'"values":[{"path":"environment.wind.angleApparent","value":NaN,"unit":"rad"}]}'
    )
    return [rng.randbytes(64), b'{"v":1,"type":"delta",', b"x" * 9000, nan_delta]


# -- pty reader detection ----------------------------------------------------------------------
def _reader_has_open(path: str) -> bool:
    """Some other process holds an fd on the pty slave (Linux /proc)."""
    target = os.path.realpath(path)
    me = os.getpid()
    try:
        pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        if pid == me:
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.path.realpath(os.readlink(f"{fd_dir}/{fd}")) == target:
                    return True
            except OSError:
                continue
    return False


async def _wait_reader(slave_path: str, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if _reader_has_open(slave_path):
            await asyncio.sleep(0.5)  # the ingest flushes input right after opening
            return True
        await asyncio.sleep(0.05)
    return False


# -- runner ------------------------------------------------------------------------------------
async def run_synth(
    cfg: SynthConfig,
    *,
    on_ready: Callable[[dict], None] | None = None,
    stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run the synthetic boat for cfg.duration sim seconds (or until stop() is true). Returns a
    summary with the last emitted Fastnet state, per-fault active seconds, the tacks made in
    follow mode and the final position."""
    if cfg.mode not in ("udp", "pty"):
        raise ValueError(f"mode must be udp or pty, got {cfg.mode!r}")
    speed = cfg.speed if cfg.speed > 0 else 1.0
    rng = random.Random(cfg.seed)
    start_utc = float(cfg.start_utc) if cfg.start_utc is not None else float(int(time.time()))
    helm = FollowHelm(cfg.follow, cfg.twa) if cfg.follow else None
    boat = SynthBoat(cfg)
    if helm is not None:
        boat.polar = default_polar()
        boat.eff = 0.92
        boat.hdg_cmd = math.radians(cfg.twd - helm.sign * helm.start_twa)
        boat.state = boat._compute()
    fake = FakeGpsd(cfg.gpsd_host, cfg.gpsd_port)
    gpsd_port = await fake.start()
    sock: socket.socket | None = None
    feeder: PtyFeeder | None = None
    counts = {"deltas": 0, "frames": 0, "heartbeats": 0, "tpv": 0, "garbage": 0, "dropped": 0}
    fault_secs = {str(f): 0 for f in cfg.faults}
    last: SynthState | None = None
    try:
        if cfg.mode == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
        else:
            feeder = PtyFeeder(cfg.link)
        ready = {
            "gpsd_port": gpsd_port,
            "mode": cfg.mode,
            "udp": f"{cfg.udp[0]}:{cfg.udp[1]}" if cfg.mode == "udp" else None,
            "pty": feeder.slave_path if feeder is not None else None,
            "link": str(feeder.link_path) if feeder and feeder.link_path else None,
            "start_utc": utc_iso(start_utc),
        }
        if on_ready is not None:
            on_ready(ready)
        if cfg.wait_gpsd_s > 0:
            await fake.wait_watching(cfg.wait_gpsd_s)
        if feeder is not None and cfg.wait_reader_s > 0:
            await _wait_reader(feeder.slave_path, cfg.wait_reader_s)

        def send(data: bytes) -> None:
            assert sock is not None
            try:
                sock.sendto(data, cfg.udp)
            except (BlockingIOError, ConnectionRefusedError, OSError):
                counts["dropped"] += 1

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        n = max(0, int(math.ceil(cfg.duration)))
        for k in range(n):
            if stop is not None and stop():
                break
            s = boat.state
            t = s.t
            active = {f.kind for f in cfg.faults if f.active(t)}
            for f in cfg.faults:
                if f.active(t):
                    fault_secs[str(f)] += 1
            utc = start_utc + t + (cfg.jump_s if "clock-jump" in active else 0.0)
            silent = "bus-silent" in active

            if sock is not None:
                mono, wall = time.monotonic(), time.time()
                hb = messages.health_message(
                    "fastnet",
                    {"state": "silent" if silent else "ok", "device": "sim", "synthetic": True},
                    mono,
                    wall,
                    t_sim=utc,
                )
                send(messages.encode(hb))
                counts["heartbeats"] += 1
                if not silent:
                    msg = messages.delta_message(
                        "fastnet", udp_values(s), mono, wall, bus={"synthetic": True}, t_sim=utc
                    )
                    send(messages.encode(msg))
                    counts["deltas"] += 1
                    last = s
                if "garbage" in active:
                    for d in hostile_datagrams(rng):
                        send(d)
                        counts["garbage"] += 1
            elif feeder is not None:
                if not silent:
                    await feeder.awrite(fastnet_frame(s, cfg.variation))
                    counts["frames"] += 1
                    last = s
                if "garbage" in active:
                    await feeder.awrite(rng.randbytes(64))
                    counts["garbage"] += 1

            if "gps-loss" in active:
                if not fake.paused:
                    fake.pause()
            elif fake.paused:
                fake.resume()
            tpv, sky = gps_objects(s, utc)
            fake.push(tpv)
            fake.push(sky)
            if not fake.paused:
                counts["tpv"] += 1

            if helm is not None:
                nav = await asyncio.to_thread(helm.fetch)
                eff = _num(((nav or {}).get("polar") or {}).get("eff"))
                if eff is not None and eff > 0:
                    boat.eff = eff
                hdg_deg, boat.bsp_factor = helm.command(nav, s)
                boat.hdg_cmd = math.radians(hdg_deg)
            boat.step(1.0)
            delay = t0 + (k + 1) / speed - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
        if feeder is not None:
            await asyncio.sleep(0.3)  # let the reader drain before the pty disappears
    finally:
        if sock is not None:
            sock.close()
        if feeder is not None:
            feeder.close()
        await fake.close()
    return {
        "start_utc": start_utc,
        "gpsd_port": gpsd_port,
        "counts": counts,
        "faults": fault_secs,
        "last": asdict(last) if last is not None else None,
        "tacks": helm.tacks if helm is not None else 0,
        "final": {"lat": boat.lat, "lon": boat.lon, "t": boat.t},
    }


# -- CLI ---------------------------------------------------------------------------------------
def _hostport(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"expected HOST:PORT, got {text!r}")
    return host, int(port)


def _latlon(text: str) -> tuple[float, float]:
    try:
        lat_s, lon_s = text.split(",")
        lat, lon = float(lat_s), float(lon_s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected LAT,LON, got {text!r}") from e
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise argparse.ArgumentTypeError(f"LAT,LON out of range: {text!r}")
    return lat, lon


def _fault(text: str) -> Fault:
    try:
        return parse_fault(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _iso_epoch(text: str) -> float:
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected ISO8601 UTC, got {text!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-sim",
        description="L2 synthetic boat with fault injection (dev only).",
        epilog="fault kinds: " + ", ".join(FAULT_KINDS) + ". Example: --fault gps-loss@120+30",
    )
    p.add_argument("--mode", choices=("udp", "pty"), default="udp")
    p.add_argument("--speed", type=float, default=1.0, help="sim seconds per real second")
    p.add_argument("--duration", type=float, default=600.0, help="sim seconds")
    p.add_argument("--twd", type=float, default=330.0, help="true wind FROM, deg")
    p.add_argument("--tws", type=float, default=12.0, help="true wind speed, kn")
    p.add_argument("--shift", type=float, default=0.0, help="wind shift, deg per hour")
    p.add_argument("--gust", type=float, default=0.0, help="gust amplitude, kn (120 s period)")
    steer = p.add_mutually_exclusive_group()
    steer.add_argument("--heading", type=float, default=None, help="fixed true heading, deg")
    steer.add_argument("--twa", type=float, default=45.0, help="fixed TWA, deg (+ starboard)")
    p.add_argument("--start", type=_latlon, default=(43.73, 15.75), help="LAT,LON")
    p.add_argument("--start-utc", type=_iso_epoch, default=None, help="sim UTC at t=0")
    p.add_argument("--variation", type=float, default=5.0, help="magnetic variation, deg East")
    p.add_argument("--udp", type=_hostport, default=("127.0.0.1", messages.DEFAULT_UDP_PORT))
    p.add_argument("--gpsd-port", type=int, default=2948, help="embedded fake gpsd port")
    p.add_argument("--link", type=Path, default=None, help="pty mode: stable symlink path")
    p.add_argument(
        "--fault",
        type=_fault,
        action="append",
        default=[],
        metavar="KIND@START+DUR",
        help="inject a fault (" + "|".join(FAULT_KINDS) + "), sim seconds; repeatable",
    )
    p.add_argument("--jump-s", type=float, default=3600.0, help="clock-jump size, s")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--wait-gpsd", type=float, default=0.0, help="wait S for a gpsd client")
    p.add_argument("--wait-reader", type=float, default=0.0, help="pty: wait S for a reader")
    p.add_argument(
        "--follow",
        metavar="URL",
        default=None,
        help="closed loop: steer to the core's GET URL/api/nav each simulated second "
        "(e.g. http://127.0.0.1:8080); X35 polar boat speed",
    )
    return p


def config_from_args(args: argparse.Namespace) -> SynthConfig:
    return SynthConfig(
        mode=args.mode,
        speed=args.speed,
        duration=args.duration,
        twd=args.twd,
        tws=args.tws,
        shift=args.shift,
        gust=args.gust,
        heading=args.heading,
        twa=args.twa,
        start=args.start,
        variation=args.variation,
        udp=args.udp,
        gpsd_port=args.gpsd_port,
        link=args.link,
        faults=list(args.fault),
        jump_s=args.jump_s,
        seed=args.seed,
        start_utc=args.start_utc,
        wait_gpsd_s=args.wait_gpsd,
        wait_reader_s=args.wait_reader,
        follow=args.follow,
    )


def main(argv: list[str] | None = None) -> int:
    cfg = config_from_args(build_arg_parser().parse_args(argv))

    def ready(info: dict) -> None:
        print(f"jabuka-sim: mode {info['mode']}, gpsd on 127.0.0.1:{info['gpsd_port']}", flush=True)
        if info["udp"]:
            print(f"jabuka-sim: deltas to {info['udp']}", flush=True)
        if info["pty"]:
            print(f"jabuka-sim: pty {info['pty']} link {info['link']}", flush=True)
        print(f"jabuka-sim: sim UTC starts {info['start_utc']}", flush=True)

    try:
        summary = asyncio.run(run_synth(cfg, on_ready=ready))
    except KeyboardInterrupt:
        return 0
    print("jabuka-sim: fault timeline", flush=True)
    for f in cfg.faults:
        secs = summary["faults"][str(f)]
        print(f"  {f.kind:<10} t={f.start:g}..{f.start + f.dur:g} s  active {secs} s", flush=True)
    print(f"jabuka-sim: {summary['counts']}", flush=True)
    if cfg.follow:
        f = summary["final"]
        print(f"jabuka-sim: {summary['tacks']} tacks, final {f['lat']:.5f},{f['lon']:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
