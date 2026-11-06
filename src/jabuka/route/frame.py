"""Local equirectangular frame shared by the land mask, the geodesic fields and the router.

x = (lon - lon0) * 60 * cos(lat0) nm (east), y = (lat - lat0) * 60 nm (north). The scale error is
about 1 % in x at the edges of the race box, which is fine because the mask and the router use
the same frame: land checks are exact in this frame. Metres = nm * 1852 (prep only).
Every function accepts scalars or numpy arrays; scalar inputs return Python floats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

NM_M = 1852.0
NM_PER_DEG = 60.0

# (lon_min, lat_min, lon_max, lat_max): Vodice, the Šibenik archipelago, Blitvenica, Mulo, Jabuka.
RACE_BBOX: tuple[float, float, float, float] = (15.0, 42.8, 16.3, 44.0)


def _out(a: np.ndarray) -> float | np.ndarray:
    return float(a) if np.ndim(a) == 0 else a


@dataclass(frozen=True)
class Frame:
    lat0: float
    lon0: float

    @property
    def kx(self) -> float:
        """nm per degree of longitude in this frame."""
        return NM_PER_DEG * math.cos(math.radians(self.lat0))

    def to_xy(self, lat, lon) -> tuple[float | np.ndarray, float | np.ndarray]:
        """(lat, lon) deg -> (x, y) nm."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        return _out((lon - self.lon0) * self.kx), _out((lat - self.lat0) * NM_PER_DEG)

    def to_ll(self, x, y) -> tuple[float | np.ndarray, float | np.ndarray]:
        """(x, y) nm -> (lat, lon) deg."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        return _out(self.lat0 + y / NM_PER_DEG), _out(self.lon0 + x / self.kx)

    def to_m(self, lat, lon) -> tuple[float | np.ndarray, float | np.ndarray]:
        """(lat, lon) deg -> (x, y) metres (laptop prep: shapely works in metres)."""
        x, y = self.to_xy(lat, lon)
        return _out(np.asarray(x) * NM_M), _out(np.asarray(y) * NM_M)

    def from_m(self, xm, ym) -> tuple[float | np.ndarray, float | np.ndarray]:
        """(x, y) metres -> (lat, lon) deg."""
        return self.to_ll(np.asarray(xm, dtype=np.float64) / NM_M, np.asarray(ym) / NM_M)


DEFAULT_FRAME = Frame(lat0=43.4, lon0=15.65)
