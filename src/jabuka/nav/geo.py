"""Flat-earth geometry in nautical miles, good to well under 1 % over the 40 nm race legs.

Local frame around a reference point: x east, y north, in nm;
x = dlon * cos(lat0) * 60, y = dlat * 60 (equirectangular).
bearing_distance/offset use the mid-latitude of the two points, which makes them exact inverses
of each other (the latitude step does not depend on the longitude scale).
Bearings are TRUE, in radians, [0, 2pi).
"""

from __future__ import annotations

import math

from jabuka.common.units import wrap_2pi

NM_PER_DEG = 60.0


def to_local(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """(lat, lon) deg -> (x east, y north) nm in the frame centred on (lat0, lon0)."""
    k = math.cos(math.radians(lat0))
    return (lon - lon0) * k * NM_PER_DEG, (lat - lat0) * NM_PER_DEG


def from_local(x: float, y: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Inverse of to_local: (x, y) nm -> (lat, lon) deg."""
    k = math.cos(math.radians(lat0))
    return lat0 + y / NM_PER_DEG, lon0 + x / (k * NM_PER_DEG)


def unit(bearing: float) -> tuple[float, float]:
    """Unit vector (east, north) of a true bearing in radians."""
    return math.sin(bearing), math.cos(bearing)


def bearing_of(x: float, y: float) -> float:
    """True bearing (rad, [0, 2pi)) of a local vector (east, north)."""
    return wrap_2pi(math.atan2(x, y))


def bearing_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """True bearing (rad) and distance (nm) from point 1 to point 2."""
    k = math.cos(math.radians((lat1 + lat2) / 2.0))
    dx = (lon2 - lon1) * k * NM_PER_DEG
    dy = (lat2 - lat1) * NM_PER_DEG
    return bearing_of(dx, dy), math.hypot(dx, dy)


def offset(lat: float, lon: float, bearing: float, dist_nm: float) -> tuple[float, float]:
    """Point dist_nm from (lat, lon) on a true bearing (rad). Exact inverse of bearing_distance."""
    dy = dist_nm * math.cos(bearing)
    dx = dist_nm * math.sin(bearing)
    lat2 = lat + dy / NM_PER_DEG
    k = math.cos(math.radians((lat + lat2) / 2.0))
    return lat2, lon + dx / (k * NM_PER_DEG)
