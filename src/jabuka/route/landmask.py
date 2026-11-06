"""Runtime land/hazard raster: point, segment and polyline checks (numpy only, never unpickles).

landmask.npz (written by ``jabuka.prep.land``): ``mask`` and ``raw`` are
``np.packbits(bool[ny, nx], axis=1)`` with True = blocked. ``mask`` = land + shore margin, hazards
+ hazard margin and submerged rocks; ``raw`` = land only. Cell (r, c) centre is
(x0 + (c + 0.5) * cell, y0 + (r + 0.5) * cell) in the local frame (nm). Outside the grid counts as
blocked.

Segment checks are exact on the raster: every cell the segment passes through is looked up (grid
line crossings, never endpoints only), which is stricter than sampling at half a cell.
"""

from __future__ import annotations

import math
import zipfile
from pathlib import Path

import numpy as np

from jabuka.route.frame import NM_M, Frame

_FLOAT_KEYS = (
    "x0_nm",
    "y0_nm",
    "cell_nm",
    "cell_m",
    "lat0",
    "lon0",
    "margin_m",
    "hazard_margin_m",
)
_STR_KEYS = ("source", "osm_base", "created")
REQUIRED_KEYS = ("mask", "raw", "shape", *_FLOAT_KEYS, *_STR_KEYS)
MAX_CELLS = 200_000_000  # 25 m over the race box is 22 Mcells
_CHUNK = 2_000_000  # grid-line crossings handled per numpy batch


def _lookup(grid: np.ndarray, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    """grid[r, c] with out-of-grid = True (blocked)."""
    ny, nx = grid.shape
    out = (r < 0) | (r >= ny) | (c < 0) | (c >= nx)
    return out | grid[np.clip(r, 0, ny - 1), np.clip(c, 0, nx - 1)]


def _ragged(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For counts n[i]: (segment index, 0..n[i]-1) for every item, concatenated."""
    seg = np.repeat(np.arange(len(n)), n)
    j = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
    return seg, j


def _chunks(cost: np.ndarray, cap: int = _CHUNK):
    """Split range(len(cost)) into contiguous slices whose summed cost stays below cap."""
    start, acc = 0, 0
    for i, w in enumerate(cost.tolist()):
        if acc and acc + w > cap:
            yield slice(start, i)
            start, acc = i, 0
        acc += w
    if start < len(cost):
        yield slice(start, len(cost))


def _crossings_hit(grid, u0, v0, u1, v1) -> np.ndarray:
    """Per segment (grid units): does any cell on either side of a vertical grid-line crossing
    hold True? Run with (u, v) swapped (and the grid transposed) for horizontal lines."""
    n_seg = len(u0)
    lo, hi = np.minimum(u0, u1), np.maximum(u0, u1)
    k0 = np.floor(lo).astype(np.int64) + 1
    k1 = np.floor(hi).astype(np.int64)
    n = np.maximum(k1 - k0 + 1, 0)
    hit = np.zeros(n_seg, dtype=bool)
    for sl in _chunks(n):
        nn = n[sl]
        if not nn.any():
            continue
        seg, j = _ragged(nn)
        seg_g = seg + sl.start
        k = k0[seg_g] + j
        du = u1[seg_g] - u0[seg_g]  # never 0 when a crossing exists
        t = (k - u0[seg_g]) / du
        v = v0[seg_g] + t * (v1[seg_g] - v0[seg_g])
        row = np.floor(v).astype(np.int64)
        bad = _lookup(grid, row, k - 1) | _lookup(grid, row, k)
        hit[sl] = np.bincount(seg, weights=bad, minlength=len(nn)) > 0
    return hit


def segments_touch(grid, x0, y0, cell, ax, ay, bx, by) -> np.ndarray:
    """Exact raster traversal: True where the segment passes through a True or out-of-grid cell.

    The cells a segment passes through are its two end cells plus, at every crossing of a grid
    line, the two cells on either side of the crossing point.
    """
    u0, v0 = (ax - x0) / cell, (ay - y0) / cell
    u1, v1 = (bx - x0) / cell, (by - y0) / cell
    hit = _lookup(grid, np.floor(v0).astype(np.int64), np.floor(u0).astype(np.int64))
    hit |= _lookup(grid, np.floor(v1).astype(np.int64), np.floor(u1).astype(np.int64))
    hit |= _crossings_hit(grid, u0, v0, u1, v1)
    hit |= _crossings_hit(grid.T, v0, u0, v1, u1)
    return hit


def _f64(*arrays):
    out = [np.atleast_1d(np.asarray(a, dtype=np.float64)) for a in arrays]
    shape = np.broadcast_shapes(*(a.shape for a in out))
    return [np.broadcast_to(a, shape).ravel() for a in out]


class LandMask:
    """Blocked raster in the local frame (nm). True = blocked (land, margins, hazards)."""

    def __init__(
        self,
        mask: np.ndarray,
        raw: np.ndarray | None,
        *,
        x0_nm: float,
        y0_nm: float,
        cell_nm: float,
        frame: Frame,
        margin_m: float = 0.0,
        hazard_margin_m: float = 0.0,
        source: str = "",
        osm_base: str = "",
        created: str = "",
    ) -> None:
        mask = np.asarray(mask, dtype=bool)
        if mask.ndim != 2 or mask.size == 0:
            raise ValueError("mask must be a non-empty 2-D array")
        self.mask = mask
        self.raw = mask if raw is None else np.asarray(raw, dtype=bool)
        if self.raw.shape != mask.shape:
            raise ValueError("raw and mask shapes differ")
        self.shape: tuple[int, int] = (int(mask.shape[0]), int(mask.shape[1]))
        self.x0_nm = float(x0_nm)
        self.y0_nm = float(y0_nm)
        self.cell_nm = float(cell_nm)
        self.cell_m = self.cell_nm * NM_M
        self.frame = frame
        self.margin_m = float(margin_m)
        self.hazard_margin_m = float(hazard_margin_m)
        self.source = source
        self.osm_base = osm_base
        self.created = created

    # ---------------------------------------------------------------- loading
    @classmethod
    def load(cls, path: str | Path) -> LandMask:
        """Load and validate landmask.npz. ValueError on anything unexpected (never unpickles)."""
        try:
            with np.load(Path(path), allow_pickle=False) as z:
                if not isinstance(z, np.lib.npyio.NpzFile):
                    raise ValueError("not an npz archive")
                missing = [k for k in REQUIRED_KEYS if k not in z.files]
                if missing:
                    raise ValueError(f"missing keys: {', '.join(missing)}")
                arrs = {k: z[k] for k in REQUIRED_KEYS}
        except ValueError as exc:
            raise ValueError(f"invalid land mask {path}: {exc}") from None
        except (OSError, zipfile.BadZipFile, EOFError, KeyError) as exc:
            raise ValueError(f"unreadable land mask {path}: {exc}") from None
        return cls._from_arrays(arrs, str(path))

    @classmethod
    def _from_arrays(cls, a: dict[str, np.ndarray], name: str) -> LandMask:
        def bad(msg: str) -> ValueError:
            return ValueError(f"invalid land mask {name}: {msg}")

        for k, v in a.items():
            if v.dtype.kind == "O":
                raise bad(f"{k} is an object array")
        shape = a["shape"]
        if shape.dtype.kind not in "iu" or shape.shape != (2,):
            raise bad("shape must be 2 integers")
        ny, nx = int(shape[0]), int(shape[1])
        if ny <= 0 or nx <= 0 or ny * nx > MAX_CELLS:
            raise bad(f"implausible grid {ny} x {nx}")
        packed_w = (nx + 7) // 8
        grids = {}
        for k in ("mask", "raw"):
            p = a[k]
            if p.dtype != np.uint8 or p.shape != (ny, packed_w):
                raise bad(f"{k} must be uint8 {ny} x {packed_w}, got {p.dtype} {p.shape}")
            grids[k] = np.unpackbits(p, axis=1, count=nx).astype(bool)
        vals = {}
        for k in _FLOAT_KEYS:
            v = a[k]
            if v.shape != () or v.dtype.kind != "f" or not math.isfinite(float(v)):
                raise bad(f"{k} must be a finite 0-d float")
            vals[k] = float(v)
        for k in _STR_KEYS:
            v = a[k]
            if v.shape != () or v.dtype.kind != "U":
                raise bad(f"{k} must be a 0-d string")
            vals[k] = str(v)
        if vals["cell_nm"] <= 0 or abs(vals["cell_nm"] * NM_M - vals["cell_m"]) > 1e-6:
            raise bad("cell_nm / cell_m inconsistent")
        if not (-80 <= vals["lat0"] <= 80 and -180 <= vals["lon0"] <= 180):
            raise bad("frame out of range")
        return cls(
            grids["mask"],
            grids["raw"],
            x0_nm=vals["x0_nm"],
            y0_nm=vals["y0_nm"],
            cell_nm=vals["cell_nm"],
            frame=Frame(lat0=vals["lat0"], lon0=vals["lon0"]),
            margin_m=vals["margin_m"],
            hazard_margin_m=vals["hazard_margin_m"],
            source=vals["source"],
            osm_base=vals["osm_base"],
            created=vals["created"],
        )

    # ---------------------------------------------------------------- queries
    def rc(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        """Fine-grid (row, col) of points (may be out of the grid)."""
        x, y = _f64(x, y)
        c = np.floor((x - self.x0_nm) / self.cell_nm).astype(np.int64)
        r = np.floor((y - self.y0_nm) / self.cell_nm).astype(np.int64)
        return r, c

    def points_clear(self, x, y) -> np.ndarray:
        r, c = self.rc(x, y)
        return ~_lookup(self.mask, r, c)

    def raw_points_clear(self, x, y) -> np.ndarray:
        r, c = self.rc(x, y)
        return ~_lookup(self.raw, r, c)

    def segments_clear(self, ax, ay, bx, by) -> np.ndarray:
        """bool[] per segment: True when no cell it passes through is blocked."""
        ax, ay, bx, by = _f64(ax, ay, bx, by)
        return ~segments_touch(self.mask, self.x0_nm, self.y0_nm, self.cell_nm, ax, ay, bx, by)

    def raw_segments_clear(self, ax, ay, bx, by) -> np.ndarray:
        """Same as segments_clear on the undilated land raster (exit from inside the margin)."""
        ax, ay, bx, by = _f64(ax, ay, bx, by)
        return ~segments_touch(self.raw, self.x0_nm, self.y0_nm, self.cell_nm, ax, ay, bx, by)

    def validate_polyline(self, xs, ys) -> tuple[bool, int | None]:
        """(True, None) when every segment is clear, else (False, index of the first bad one).

        A single point is checked as a point (index 0 when blocked)."""
        xs, ys = _f64(xs, ys)
        if len(xs) == 1:
            return (True, None) if bool(self.points_clear(xs, ys)[0]) else (False, 0)
        ok = self.segments_clear(xs[:-1], ys[:-1], xs[1:], ys[1:])
        bad = np.nonzero(~ok)[0]
        return (True, None) if len(bad) == 0 else (False, int(bad[0]))
