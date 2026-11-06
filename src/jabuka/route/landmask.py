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
BLOCK = 8  # coarse "near" grid: 8 x 8 fine cells (200 m at 25 m)
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


def _sample_hit(grid, x0, y0, cell, ax, ay, bx, by, spacing) -> np.ndarray:
    """Sample every segment at <= spacing (both endpoints included): True where a sample falls
    in a True or out-of-grid cell."""
    length = np.hypot(bx - ax, by - ay)
    k = np.maximum(np.ceil(length / spacing).astype(np.int64), 1)
    counts = k + 1
    hit = np.zeros(len(ax), dtype=bool)
    for sl in _chunks(counts):
        seg, j = _ragged(counts[sl])
        g = seg + sl.start
        fr = j / k[g]
        xs = ax[g] + fr * (bx[g] - ax[g])
        ys = ay[g] + fr * (by[g] - ay[g])
        c = np.floor((xs - x0) / cell).astype(np.int64)
        r = np.floor((ys - y0) / cell).astype(np.int64)
        hit[sl] = np.bincount(seg, weights=_lookup(grid, r, c), minlength=len(counts[sl])) > 0
    return hit


def _block_any(grid: np.ndarray, b: int) -> np.ndarray:
    """Coarse blocks of b x b cells: True when any cell is True (padding counts as True)."""
    ny, nx = grid.shape
    gy, gx = -(-ny // b), -(-nx // b)
    pad = np.ones((gy * b, gx * b), dtype=bool)
    pad[:ny, :nx] = grid
    return pad.reshape(gy, b, gx, b).any(axis=(1, 3))


def _dilate(a: np.ndarray, r: int) -> np.ndarray:
    """Square (Chebyshev) dilation by r cells; outside the array counts as True."""
    if r <= 0:
        return a.copy()
    p = np.pad(a, r, constant_values=True)
    w = 2 * r + 1
    rows = np.lib.stride_tricks.sliding_window_view(p, w, axis=0).any(axis=-1)
    return np.lib.stride_tricks.sliding_window_view(rows, w, axis=1).any(axis=-1)


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
        # Coarse "near" grid: blocks of BLOCK x BLOCK cells, near when any blocked cell lies in
        # the block or its 8 neighbours (outside the grid counts as blocked).
        self.bcell_nm = BLOCK * self.cell_nm
        self._blocks = _block_any(self.mask, BLOCK)
        self._near = _dilate(self._blocks, 1)
        self._zones: dict[float, np.ndarray] = {}

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

    def fine_pass_needed(self, ax, ay, bx, by) -> np.ndarray:
        """Coarse pass: sample each segment at the block spacing on the near grid. A segment whose
        samples all fall in non-near blocks is clear: any point of it lies within half a block
        of a sample, so any blocked cell it touches would sit in that sample's 3 x 3 blocks."""
        ax, ay, bx, by = _f64(ax, ay, bx, by)
        b = self.bcell_nm
        return _sample_hit(self._near, self.x0_nm, self.y0_nm, b, ax, ay, bx, by, b)

    def segments_clear(self, ax, ay, bx, by) -> np.ndarray:
        """bool[] per segment: True when no cell it passes through is blocked.

        Coarse near-grid pass first; only segments near something blocked get the exact pass,
        so the answer is identical to the exact pass alone."""
        ax, ay, bx, by = _f64(ax, ay, bx, by)
        ok = np.ones(len(ax), dtype=bool)
        idx = np.nonzero(self.fine_pass_needed(ax, ay, bx, by))[0]
        if len(idx):
            ok[idx] = ~segments_touch(
                self.mask, self.x0_nm, self.y0_nm, self.cell_nm, ax[idx], ay[idx], bx[idx], by[idx]
            )
        return ok

    def near_land(self, x, y, within_nm: float) -> np.ndarray:
        """bool[]: something blocked may lie within `within_nm` (block resolution, conservative:
        can also flag up to one block further). Outside the grid = True. Used by the router's
        fine-time-step rule; zone rasters are cached per distance."""
        key = round(float(within_nm), 6)
        zone = self._zones.get(key)
        if zone is None:
            zone = _dilate(self._blocks, int(math.ceil(max(key, 0.0) / self.bcell_nm)))
            self._zones[key] = zone
        x, y = _f64(x, y)
        c = np.floor((x - self.x0_nm) / self.bcell_nm).astype(np.int64)
        r = np.floor((y - self.y0_nm) / self.bcell_nm).astype(np.int64)
        return _lookup(zone, r, c)

    def snap_clear(self, x: float, y: float, max_nm: float = 1.0):
        """Boat or target inside the dilated mask (marina, close to shore): the nearest clear cell
        centre within max_nm whose exit segment does not cross raw land.

        Returns (x, y, False) when the point is already clear, (x', y', True) when moved, None
        when nothing qualifies (deep inland, or no clear water within max_nm)."""
        x, y = float(x), float(y)
        if bool(self.points_clear(x, y)[0]):
            return x, y, False
        ny, nx = self.shape
        r0, c0 = (int(v[0]) for v in self.rc(x, y))
        rad = int(math.ceil(max_nm / self.cell_nm)) + 1
        rlo, rhi = max(r0 - rad, 0), min(r0 + rad + 1, ny)
        clo, chi = max(c0 - rad, 0), min(c0 + rad + 1, nx)
        if rlo >= rhi or clo >= chi:
            return None
        rr, cc = np.nonzero(~self.mask[rlo:rhi, clo:chi])
        cx = self.x0_nm + (cc + clo + 0.5) * self.cell_nm
        cy = self.y0_nm + (rr + rlo + 0.5) * self.cell_nm
        d = np.hypot(cx - x, cy - y)
        keep = d <= max_nm
        cx, cy, d = cx[keep], cy[keep], d[keep]
        order = np.argsort(d, kind="stable")
        for i in range(0, len(order), 256):  # nearest first, in batches
            sel = order[i : i + 256]
            ok = self.raw_segments_clear(x, y, cx[sel], cy[sel])
            if ok.any():
                j = sel[int(np.argmax(ok))]
                return float(cx[j]), float(cy[j]), True
        return None

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


# ---------------------------------------------------------------------- connectivity
def _run_ids(clear: np.ndarray) -> tuple[np.ndarray, int]:
    """Label runs of contiguous clear cells along axis 1 (row-major): run id per cell."""
    start = clear.copy()
    start[:, 1:] &= ~clear[:, :-1]
    ids = np.cumsum(start.ravel(), dtype=np.int32 if clear.size < 2**31 else np.int64)
    ids = ids.reshape(clear.shape)
    return ids, int(ids[-1, -1]) + 1


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]  # path halving
        i = parent[i]
    return i


def flood_reachable(blocked: np.ndarray, seeds_rc) -> np.ndarray:
    """4-connected flood fill of clear cells from the seed cells (run-based, numpy).

    Runs of contiguous clear cells along each row are labelled with a cumulative sum; two runs in
    adjacent rows touch when they share a column. Joining touching runs (union-find over the few
    thousand runs, not the cells) gives the connected components, so the cost does not depend on
    the length or the number of turns of the path. Seeds outside the grid or on blocked cells are
    ignored."""
    clear = ~np.asarray(blocked, dtype=bool)
    ny, nx = clear.shape
    seeds = np.asarray(seeds_rc, dtype=np.int64).reshape(-1, 2)
    inside = (seeds[:, 0] >= 0) & (seeds[:, 0] < ny) & (seeds[:, 1] >= 0) & (seeds[:, 1] < nx)
    s = seeds[inside]
    s = s[clear[s[:, 0], s[:, 1]]]
    if len(s) == 0:
        return np.zeros_like(clear)
    ids, n = _run_ids(clear)
    # one (upper run, lower run) pair per stretch of vertically touching cells
    both = clear[:-1] & clear[1:]
    up, dn = ids[:-1], ids[1:]
    first = both.copy()
    first[:, 1:] &= ~(both[:, :-1] & (up[:, 1:] == up[:, :-1]) & (dn[:, 1:] == dn[:, :-1]))
    pairs = np.unique(np.stack([up[first], dn[first]], axis=1), axis=0)
    parent = list(range(n))
    for a, b in pairs.tolist():
        ra, rb = _find(parent, a), _find(parent, b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([_find(parent, i) for i in range(n)], dtype=np.int64)
    seed_roots = np.unique(roots[ids[s[:, 0], s[:, 1]]])
    return clear & np.isin(roots, seed_roots)[ids]


# ---------------------------------------------------------------------- geodesic fields
_SQ2, _SQ5 = math.sqrt(2.0), math.sqrt(5.0)
# 16-neighbour moves (dr, dc, length in cells): max error vs straight line 2.7 % (8-nb: 8 %)
_MOVES = [
    *((dr, dc, 1.0) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))),
    *((dr, dc, _SQ2) for dr in (-1, 1) for dc in (-1, 1)),
    *((dr, dc, _SQ5) for dr in (-1, 1) for dc in (-2, 2)),
    *((dr, dc, _SQ5) for dr in (-2, 2) for dc in (-1, 1)),
]


def _shift(a: np.ndarray, dr: int, dc: int, fill) -> np.ndarray:
    """out[r, c] = a[r - dr, c - dc] (fill outside)."""
    ny, nx = a.shape
    out = np.full_like(a, fill)
    rs, re = max(dr, 0), ny + min(dr, 0)
    cs, ce = max(dc, 0), nx + min(dc, 0)
    if rs < re and cs < ce:
        out[rs:re, cs:ce] = a[rs - dr : re - dr, cs - dc : ce - dc]
    return out


def _move_allowed(clear: np.ndarray, dr: int, dc: int) -> np.ndarray:
    """allowed[r, c]: the move from (r - dr, c - dc) to (r, c) stays in clear cells, including
    the cells it cuts through (no squeezing between two diagonal blocked cells)."""
    ok = clear & _shift(clear, dr, dc, False)
    sr, sc = int(np.sign(dr)), int(np.sign(dc))
    if abs(dr) == 1 and abs(dc) == 1:
        ok &= _shift(clear, dr, 0, False) & _shift(clear, 0, dc, False)
    elif abs(dr) == 1:  # (1, 2): passes cells (r - dr, c - sc) and (r, c - sc)
        ok &= _shift(clear, dr, sc, False) & _shift(clear, 0, sc, False)
    elif abs(dc) == 1:  # (2, 1): passes cells (r - sr, c - dc) and (r - sr, c)
        ok &= _shift(clear, sr, dc, False) & _shift(clear, sr, 0, False)
    return ok


class GeoField:
    """Distance (nm) by water to a target, on a coarse grid; inf when unreachable or outside."""

    def __init__(self, dist: np.ndarray, x0_nm: float, y0_nm: float, gcell_nm: float) -> None:
        self.dist = np.asarray(dist, dtype=np.float64)
        if self.dist.ndim != 2:
            raise ValueError("GeoField distances must be 2-D")
        self.x0_nm = float(x0_nm)
        self.y0_nm = float(y0_nm)
        self.gcell_nm = float(gcell_nm)

    def distance(self, x, y) -> np.ndarray:
        """Bilinear between the 4 surrounding cell centres when they are all finite, else the
        value of the cell holding the point. inf when unreachable or outside the grid."""
        x, y = _f64(x, y)
        u = (x - self.x0_nm) / self.gcell_nm
        v = (y - self.y0_nm) / self.gcell_nm
        c = np.floor(u).astype(np.int64)
        r = np.floor(v).astype(np.int64)
        ny, nx = self.dist.shape
        out = (r < 0) | (r >= ny) | (c < 0) | (c >= nx)
        cell = self.dist[np.clip(r, 0, ny - 1), np.clip(c, 0, nx - 1)]
        c0 = np.clip(np.floor(u - 0.5).astype(np.int64), 0, nx - 1)
        r0 = np.clip(np.floor(v - 0.5).astype(np.int64), 0, ny - 1)
        c1, r1 = np.minimum(c0 + 1, nx - 1), np.minimum(r0 + 1, ny - 1)
        fu = np.clip(u - 0.5 - c0, 0.0, 1.0)
        fv = np.clip(v - 0.5 - r0, 0.0, 1.0)
        q = (self.dist[r0, c0], self.dist[r0, c1], self.dist[r1, c0], self.dist[r1, c1])
        finite = np.isfinite(q[0]) & np.isfinite(q[1]) & np.isfinite(q[2]) & np.isfinite(q[3])
        with np.errstate(invalid="ignore"):
            bil = (q[0] * (1 - fu) + q[1] * fu) * (1 - fv) + (q[2] * (1 - fu) + q[3] * fu) * fv
        d = np.where(finite & np.isfinite(cell), bil, cell)
        return np.where(out, np.inf, d)


def coarse_blocked(lm: LandMask, gcell_nm: float, mode: str = "centre") -> tuple[np.ndarray, int]:
    """Blocked coarse grid of B x B fine cells (B = round(gcell / cell)).

    mode "centre": a coarse cell is blocked when the fine cell at its centre is (a channel at
    least 2 coarse cells wide stays open; prep at 200 m). mode "any": blocked when any fine cell
    in it is (conservative; on demand at 400 m)."""
    b = max(1, int(round(gcell_nm / lm.cell_nm)))
    if mode == "any":
        return _block_any(lm.mask, b), b
    if mode != "centre":
        raise ValueError(f"unknown geofield mode {mode!r}")
    ny, nx = lm.shape
    gy, gx = -(-ny // b), -(-nx // b)
    out = np.ones((gy, gx), dtype=bool)
    sub = lm.mask[b // 2 :: b, b // 2 :: b]
    out[: sub.shape[0], : sub.shape[1]] = sub
    return out, b


def compute_geofield(
    lm: LandMask,
    seeds_xy,
    gcell_nm: float = 200.0 / NM_M,
    mode: str = "centre",
    seed_radius_nm: float = 0.0,
    max_iter: int = 5000,
) -> GeoField:
    """Geodesic (by water) distance to the nearest seed, 16-neighbour relaxation in numpy.

    Every clear coarse cell within max(gcell, seed radius) of a seed starts at its straight-line
    distance minus the seed radius; distances then relax until nothing changes. RuntimeError past
    max_iter."""
    blocked, b = coarse_blocked(lm, gcell_nm, mode)
    h = b * lm.cell_nm
    gy, gx = blocked.shape
    clear = ~blocked
    seeds = np.asarray(seeds_xy, dtype=np.float64).reshape(-1, 2)
    cx = lm.x0_nm + (np.arange(gx) + 0.5) * h
    cy = lm.y0_nm + (np.arange(gy) + 0.5) * h
    d = np.full((gy, gx), np.inf)
    reach = max(h, float(seed_radius_nm))
    for sx, sy in seeds:
        e = np.hypot(cx[None, :] - sx, cy[:, None] - sy)
        init = np.where(clear & (e <= reach), np.maximum(e - seed_radius_nm, 0.0), np.inf)
        np.minimum(d, init, out=d)
    # Gauss-Seidel row sweeps (down, then up) until nothing changes. Each row first takes the
    # moves coming from the 1-2 rows already swept, then the exact horizontal pass along it.
    # Same move set and costs as a plain Jacobi relaxation, hence the same fixed point (the
    # shortest paths), in a few sweeps instead of one iteration per cell of path length.
    costs = {
        (dr, dc): np.where(_move_allowed(clear, dr, dc), w * h, np.inf) for dr, dc, w in _MOVES
    }
    link = np.zeros((gy, gx), dtype=bool)  # link[r, c]: the move c-1 <-> c is allowed
    link[:, 1:] = clear[:, 1:] & clear[:, :-1]
    pad = np.full((gy, gx + 4), np.inf)
    pad[:, 2:-2] = d
    for _ in range(max_iter):
        changed = False
        for sign, rows in ((1, range(gy)), (-1, range(gy - 1, -1, -1))):
            moves = [(dr, dc, c) for (dr, dc), c in costs.items() if dr * sign > 0]
            for r in rows:
                row = pad[r, 2:-2]
                new = row.copy()
                for dr, dc, cost in moves:
                    rs = r - dr
                    if 0 <= rs < gy:
                        np.minimum(new, pad[rs, 2 - dc : 2 - dc + gx] + cost[r], out=new)
                new = _row_pass(new, link[r], h)
                if not changed and not np.array_equal(new, row):
                    changed = True
                row[...] = new
        if not changed:
            return GeoField(pad[:, 2:-2].copy(), lm.x0_nm, lm.y0_nm, h)
    raise RuntimeError(f"compute_geofield did not converge in {max_iter} sweeps")


# Segment offset for the segmented running minimum: larger than any distance + row length (nm),
# small enough to keep float64 rounding far below a metre.
_BIG = 1e4


def _row_pass(v: np.ndarray, link: np.ndarray, h: float) -> np.ndarray:
    """Exact 1-D relaxation along a row: min over linked cells of v[j] + |c - j| * h, where
    link[c] allows the move between c-1 and c. Segmented running minimum in both directions."""
    n = len(v)
    pos = np.arange(n) * h
    seg = np.cumsum(~link) * _BIG  # a new segment wherever the move is not allowed
    fwd = np.minimum.accumulate(v - pos - seg) + pos + seg
    rv, rl = v[::-1], np.concatenate(([False], link[:0:-1]))
    rseg = np.cumsum(~rl) * _BIG
    bwd = (np.minimum.accumulate(rv - pos - rseg) + pos + rseg)[::-1]
    cand = np.minimum(fwd, bwd)
    cand[cand > _BIG / 2] = np.inf  # values carried over from another segment
    # keep only real improvements: rounding noise must not count as a change (convergence)
    return np.where(cand < v - 1e-9, cand, v)


def save_geofields(path: str | Path, fields: dict[tuple[float, float, float], GeoField]) -> None:
    """One npz: fields float32 [K, gy, gx], keys float64 [K, 3] = (lat, lon, radius_nm)."""
    if not fields:
        raise ValueError("no geofields to save")
    items = list(fields.items())
    g0 = items[0][1]
    for _, f in items:
        if f.dist.shape != g0.dist.shape or (f.x0_nm, f.y0_nm, f.gcell_nm) != (
            g0.x0_nm,
            g0.y0_nm,
            g0.gcell_nm,
        ):
            raise ValueError("all geofields in one file must share the grid")
    np.savez_compressed(
        Path(path),
        fields=np.stack([f.dist for _, f in items]).astype(np.float32),
        keys=np.array([k for k, _ in items], dtype=np.float64),
        x0_nm=np.float64(g0.x0_nm),
        y0_nm=np.float64(g0.y0_nm),
        gcell_nm=np.float64(g0.gcell_nm),
    )


def load_geofields(path: str | Path) -> dict[tuple[float, float, float], GeoField]:
    """Inverse of save_geofields; ValueError on anything unexpected (never unpickles)."""
    try:
        with np.load(Path(path), allow_pickle=False) as z:
            if not isinstance(z, np.lib.npyio.NpzFile):
                raise ValueError("not an npz archive")
            need = ("fields", "keys", "x0_nm", "y0_nm", "gcell_nm")
            missing = [k for k in need if k not in z.files]
            if missing:
                raise ValueError(f"missing keys: {', '.join(missing)}")
            a = {k: z[k] for k in need}
    except ValueError as exc:
        raise ValueError(f"invalid geofields {path}: {exc}") from None
    except (OSError, zipfile.BadZipFile, EOFError, KeyError) as exc:
        raise ValueError(f"unreadable geofields {path}: {exc}") from None
    fields, keys = a["fields"], a["keys"]
    if fields.dtype.kind != "f" or fields.ndim != 3 or 0 in fields.shape:
        raise ValueError(f"invalid geofields {path}: fields must be float [K, gy, gx]")
    if keys.dtype.kind != "f" or keys.shape != (fields.shape[0], 3) or not np.isfinite(keys).all():
        raise ValueError(f"invalid geofields {path}: keys must be finite float [K, 3]")
    if np.isnan(fields).any():
        raise ValueError(f"invalid geofields {path}: NaN distances")
    geo = []
    for k in ("x0_nm", "y0_nm", "gcell_nm"):
        v = a[k]
        if v.shape != () or v.dtype.kind != "f" or not math.isfinite(float(v)):
            raise ValueError(f"invalid geofields {path}: {k} must be a finite 0-d float")
        geo.append(float(v))
    if geo[2] <= 0:
        raise ValueError(f"invalid geofields {path}: gcell_nm must be > 0")
    return {
        (round(float(k[0]), 4), round(float(k[1]), 4), round(float(k[2]), 3)): GeoField(
            fields[i], *geo
        )
        for i, k in enumerate(keys)
    }
