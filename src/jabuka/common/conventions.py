"""Direction and unit conventions: the single boundary every later phase converts through.

- Radians internally; directions wrapped to [0, 2pi), signed relative angles to (-pi, pi].
- Magnetic variation and heading offset are EAST-positive (true = magnetic + variation).
  gpsd's TPV ``magvar`` is WEST-positive: convert with gpsd_magvar_to_east.
- Wind direction is where the wind blows FROM; current (set) is where it flows TOWARDS.
- u = east component, v = north component (GRIB convention).
- TWA/AWA are signed, negative = port (Signal K; RESEARCH A1 to be verified on the boat, the
  ingest's --awa-sign flips it if needed).

Pinned by tests/common/test_conventions.py. Converting live data to TRUE is Phase 2 (WIND-03).
"""

from __future__ import annotations

import math
from typing import NamedTuple

from jabuka.common.units import wrap_2pi, wrap_pi


class TrueWind(NamedTuple):
    twa: float  # rad, signed, negative = port
    tws: float  # m/s (same unit as the inputs)
    twd: float  # rad FROM, [0, 2pi)


class ApparentWind(NamedTuple):
    awa: float  # rad, signed, negative = port
    aws: float  # same unit as the inputs


def mag_to_true(mag: float, variation_east: float) -> float:
    """Magnetic -> true bearing (rad); variation East-positive: true = mag + var."""
    return wrap_2pi(mag + variation_east)


def true_to_mag(true: float, variation_east: float) -> float:
    """True -> magnetic bearing (rad); variation East-positive: mag = true - var."""
    return wrap_2pi(true - variation_east)


def apply_heading_offset(heading: float, offset: float) -> float:
    """Sensor heading + calibration offset (rad, East/clockwise-positive), wrapped to [0, 2pi)."""
    return wrap_2pi(heading + offset)


def gpsd_magvar_to_east(magvar_west_positive: float) -> float:
    """gpsd TPV magvar (West-positive) -> East-positive variation, same unit in and out."""
    return -magvar_west_positive


def wind_from_uv(u: float, v: float) -> tuple[float, float]:
    """Wind u/v (air motion, east/north) -> (direction FROM in rad [0, 2pi), speed)."""
    return wrap_2pi(math.atan2(-u, -v)), math.hypot(u, v)


def uv_from_wind_from(direction_from: float, speed: float) -> tuple[float, float]:
    """Wind (direction FROM rad, speed) -> u/v of the air motion (east, north)."""
    return -speed * math.sin(direction_from), -speed * math.cos(direction_from)


def current_towards_uv(direction_towards: float, speed: float) -> tuple[float, float]:
    """Current (set TOWARDS rad, drift) -> u/v of the water motion (east, north)."""
    return speed * math.sin(direction_towards), speed * math.cos(direction_towards)


def uv_to_current_towards(u: float, v: float) -> tuple[float, float]:
    """Water motion u/v -> (set TOWARDS in rad [0, 2pi), drift)."""
    return wrap_2pi(math.atan2(u, v)), math.hypot(u, v)


def true_wind_from_apparent(awa: float, aws: float, bsp: float, hdg: float) -> TrueWind:
    """Apparent wind (signed AWA rad, AWS) + boat speed through water + true heading -> true wind
    over the water (signed TWA, TWS, TWD FROM [0, 2pi)). Boat frame: x forward, y starboard."""
    # air motion relative to the boat (FROM awa -> moving towards awa + pi)
    ax, ay = -aws * math.cos(awa), -aws * math.sin(awa)
    # true air motion = apparent + boat velocity (bsp, 0)
    tx, ty = ax + bsp, ay
    tws = math.hypot(tx, ty)
    twa = wrap_pi(math.atan2(-ty, -tx))
    return TrueWind(twa=twa, tws=tws, twd=wrap_2pi(hdg + twa))


def apparent_from_true(twd: float, tws: float, bsp: float, hdg: float) -> ApparentWind:
    """True wind (TWD FROM rad, TWS) + boat speed + true heading -> apparent wind (signed AWA,
    AWS) felt on board. Inverse of true_wind_from_apparent."""
    twa = wrap_pi(twd - hdg)
    tx, ty = -tws * math.cos(twa), -tws * math.sin(twa)
    ax, ay = tx - bsp, ty
    return ApparentWind(awa=wrap_pi(math.atan2(-ay, -ax)), aws=math.hypot(ax, ay))
