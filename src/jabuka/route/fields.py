"""Weather fields for the router and the core: wind (with GRIB bias), waves, current.

All three share one interpolation: the two time slices bracketing t are blended linearly once per
call (tiny 2-D arrays), then every query point is interpolated bilinearly in (lat, lon). Outside
the grid the nearest edge cell is held; before the first time the first slice and beyond the last
time the last slice is held (``horizon_hold(t)`` tells the router, RESEARCH Pattern 3 rule 5).

Units out: knots for wind and current, metres for Hs, radians for directions. Wind is air motion
(u east, v north) with the direction FROM = atan2(-u, -v) (``conventions.wind_from_uv``); current
is water motion TOWARDS. The GRIB bias is applied to the wind after interpolation (it is linear):
rotation of the air-motion vector by phi then scale (``BiasParams.weights``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from jabuka.route.bias import BiasParams
from jabuka.route.frame import Frame
from jabuka.route.racepack import Grid, RacePack

MS_TO_KN = 3600.0 / 1852.0

# Hs (m) estimated from TWS (kn) when no wave file: ~0.7 x WMO "probable wave height" [ASSUMED]
HS_TABLE_TWS = np.array([0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0])
HS_TABLE_M = np.array([0.0, 0.1, 0.4, 0.8, 1.4, 2.0, 2.8])


def hs_from_tws(tws_kn) -> np.ndarray:
    """Significant wave height (m) estimated from the wind speed (kn), clamped above 30 kn."""
    return np.interp(np.asarray(tws_kn, dtype=np.float64), HS_TABLE_TWS, HS_TABLE_M)


class _Sampler:
    """Time-blend + bilinear interpolation of named float32 [T, NY, NX] arrays of a Grid."""

    def __init__(self, grid: Grid, keys: tuple[str, ...], frame: Frame, scale: float = 1.0):
        self.grid = grid
        self.frame = frame
        self.keys = keys
        self.t = np.asarray(grid.t, dtype=np.float64)
        self.lat = np.asarray(grid.lat, dtype=np.float64)
        self.lon = np.asarray(grid.lon, dtype=np.float64)
        self._iy = np.arange(self.lat.size, dtype=np.float64)
        self._ix = np.arange(self.lon.size, dtype=np.float64)
        self._arr = {k: np.asarray(grid.arrays[k], dtype=np.float64) * scale for k in keys}
        self._cache_t: float | None = None
        self._cache: dict[str, np.ndarray] = {}

    @property
    def t_first(self) -> float:
        return float(self.t[0])

    @property
    def t_last(self) -> float:
        return float(self.t[-1])

    def horizon_hold(self, t: float) -> bool:
        return float(t) > self.t_last

    def _slices(self, t: float) -> dict[str, np.ndarray]:
        t = float(t)
        if self._cache_t == t:
            return self._cache
        tt = self.t
        if t <= tt[0] or tt.size == 1:
            out = {k: a[0] for k, a in self._arr.items()}
        elif t >= tt[-1]:
            out = {k: a[-1] for k, a in self._arr.items()}
        else:
            i = int(np.searchsorted(tt, t, side="right")) - 1
            w = (t - tt[i]) / (tt[i + 1] - tt[i])
            out = {k: a[i] * (1.0 - w) + a[i + 1] * w for k, a in self._arr.items()}
        self._cache_t, self._cache = t, out
        return out

    def _weights(self, lat, lon):
        fy = np.interp(lat, self.lat, self._iy)  # clamps to the edge cells outside the grid
        fx = np.interp(lon, self.lon, self._ix)
        ny, nx = self.lat.size, self.lon.size
        i0 = np.minimum(fy.astype(np.int64), ny - 2)
        j0 = np.minimum(fx.astype(np.int64), nx - 2)
        return i0, j0, fy - i0, fx - j0

    def values_ll(self, t: float, lat, lon) -> dict[str, np.ndarray]:
        lat = np.atleast_1d(np.asarray(lat, dtype=np.float64))
        lon = np.atleast_1d(np.asarray(lon, dtype=np.float64))
        sl = self._slices(t)
        i0, j0, fy, fx = self._weights(lat, lon)
        out = {}
        for k, a in sl.items():
            lo = a[i0, j0] * (1.0 - fx) + a[i0, j0 + 1] * fx
            hi = a[i0 + 1, j0] * (1.0 - fx) + a[i0 + 1, j0 + 1] * fx
            out[k] = lo * (1.0 - fy) + hi * fy
        return out

    def values_xy(self, t: float, x, y) -> dict[str, np.ndarray]:
        lat, lon = self.frame.to_ll(x, y)
        return self.values_ll(t, lat, lon)


def _apply_bias(u, v, t: float, bias: BiasParams | None):
    if bias is None:
        return u, v
    phi, scale = bias.weights(t)
    c, s = math.cos(phi), math.sin(phi)
    return (u * c + v * s) * scale, (-u * s + v * c) * scale


def uv_to_dir_speed(u, v) -> tuple[np.ndarray, np.ndarray]:
    """Air motion (kn) -> (direction FROM rad in [0, 2pi), speed kn), vectorised."""
    return np.mod(np.arctan2(-u, -v), 2.0 * math.pi), np.hypot(u, v)


class WindField:
    """GRIB 10 m wind (pack ``wind.npz``, m/s) sampled in knots, with the GRIB bias."""

    def __init__(self, grid: Grid, frame: Frame) -> None:
        self._s = _Sampler(grid, ("u", "v"), frame, MS_TO_KN)

    @property
    def t_first(self) -> float:
        return self._s.t_first

    @property
    def t_last(self) -> float:
        return self._s.t_last

    def horizon_hold(self, t: float) -> bool:
        return self._s.horizon_hold(t)

    def uv_kn(self, t: float, x, y, bias: BiasParams | None = None):
        """Air motion (u east, v north) in knots at frame points (x, y) nm, bias applied."""
        val = self._s.values_xy(t, x, y)
        u = np.nan_to_num(val["u"], nan=0.0)
        v = np.nan_to_num(val["v"], nan=0.0)
        return _apply_bias(u, v, t, bias)

    def sample(self, t: float, x, y, bias: BiasParams | None = None):
        """(TWD FROM rad, TWS kn) per point."""
        return uv_to_dir_speed(*self.uv_kn(t, x, y, bias))

    def at(
        self, t: float, lat: float, lon: float, bias: BiasParams | None = None
    ) -> tuple[float, float]:
        """Scalar (TWD FROM rad, TWS kn) at a position (core GRIB-only wind, WIND-05)."""
        val = self._s.values_ll(t, lat, lon)
        u = float(np.nan_to_num(val["u"][0], nan=0.0))
        v = float(np.nan_to_num(val["v"][0], nan=0.0))
        u, v = _apply_bias(u, v, t, bias)
        return math.atan2(-u, -v) % (2.0 * math.pi), math.hypot(u, v)


class WaveField:
    """Significant wave height (pack ``waves.npz`` ``hs``, m). NaN where the file has no value."""

    def __init__(self, grid: Grid, frame: Frame) -> None:
        self._s = _Sampler(grid, ("hs",), frame)

    def hs(self, t: float, x, y) -> np.ndarray:
        return self._s.values_xy(t, x, y)["hs"]


class CurrentField:
    """Surface current (pack ``current.npz``, water motion TOWARDS, m/s) sampled in knots."""

    def __init__(self, grid: Grid, frame: Frame) -> None:
        self._s = _Sampler(grid, ("u", "v"), frame, MS_TO_KN)

    def uv_kn(self, t: float, x, y) -> tuple[np.ndarray, np.ndarray]:
        val = self._s.values_xy(t, x, y)
        return np.nan_to_num(val["u"], nan=0.0), np.nan_to_num(val["v"], nan=0.0)


@dataclass
class Fields:
    wind: WindField
    waves: WaveField | None = None
    current: CurrentField | None = None


def fields_from_pack(pack: RacePack, frame: Frame) -> Fields:
    """Fields from a loaded RacePack (waves/current only when present and valid)."""
    if pack.wind is None:
        raise ValueError("pas de vent utilisable dans le pack")
    waves = WaveField(pack.waves, frame) if pack.waves is not None else None
    current = CurrentField(pack.current, frame) if pack.current is not None else None
    return Fields(WindField(pack.wind, frame), waves, current)
