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
gps-loss, garbage, clock-jump. Closed-loop steering is Phase 2.

Dev tool only (never in a systemd unit); it may read the wall clock.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jabuka.common import messages
from jabuka.common.conventions import apparent_from_true, true_to_mag
from jabuka.common.units import kn_to_ms, ms_to_kn, wrap_2pi, wrap_pi
from jabuka.ingest.fastnet_encode import frame, rec01, rec08
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
        self.state = self._compute()

    def _compute(self) -> SynthState:
        cfg, t = self.cfg, self.t
        twd = wrap_2pi(math.radians(cfg.twd + cfg.shift * t / 3600.0))
        tws_kn = max(0.0, cfg.tws + cfg.gust * math.sin(2.0 * math.pi * t / 120.0))
        if cfg.heading is not None:
            hdg = wrap_2pi(math.radians(cfg.heading))
        else:
            hdg = wrap_2pi(twd - math.radians(cfg.twa))
        twa = wrap_pi(twd - hdg)
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
    cfg: SynthConfig, *, on_ready: Callable[[dict], None] | None = None
) -> dict[str, Any]:
    """Run the synthetic boat for cfg.duration sim seconds. Returns a summary with the last
    emitted Fastnet state and per-fault active seconds."""
    if cfg.mode not in ("udp", "pty"):
        raise ValueError(f"mode must be udp or pty, got {cfg.mode!r}")
    speed = cfg.speed if cfg.speed > 0 else 1.0
    rng = random.Random(cfg.seed)
    start_utc = float(cfg.start_utc) if cfg.start_utc is not None else float(int(time.time()))
    boat = SynthBoat(cfg)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
