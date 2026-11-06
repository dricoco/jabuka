"""Unit conversions and angle wrapping. Internally everything is SI: radians, m/s, metres."""

from __future__ import annotations

import math

TWO_PI = 2.0 * math.pi
KN_IN_MS = 1852.0 / 3600.0  # 1 knot = 1852 m/h = 0.514444... m/s


def kn_to_ms(kn: float) -> float:
    """Knots -> metres per second."""
    return kn * KN_IN_MS


def ms_to_kn(ms: float) -> float:
    """Metres per second -> knots."""
    return ms / KN_IN_MS


def deg2rad(deg: float) -> float:
    """Degrees -> radians."""
    return math.radians(deg)


def rad2deg(rad: float) -> float:
    """Radians -> degrees."""
    return math.degrees(rad)


def wrap_2pi(a: float) -> float:
    """Angle wrapped to [0, 2pi) (directions: heading, COG, TWD)."""
    r = math.fmod(a, TWO_PI)
    if r < 0.0:
        r += TWO_PI
    if r >= TWO_PI:  # -tiny + 2pi rounds to 2pi
        r = 0.0
    return r


def wrap_pi(a: float) -> float:
    """Angle wrapped to (-pi, pi] (signed relative angles: TWA/AWA, negative = port)."""
    return math.pi - wrap_2pi(math.pi - a)
