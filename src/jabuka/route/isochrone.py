"""Vectorised isochrone router (numpy only, pure: time comes from the request).

RESEARCH Pattern 4 with the measured geodesic-ranking fix, Pattern 5 for land:

- Local equirectangular frame (nm) shared with the land mask; heading = TWD - TWA (project sign,
  Pitfall 1); tack = sign(TWA), +1 starboard.
- Each step: wind sampled once per parent (bias applied); candidates |TWA| in {30, 30 + step, ...,
  180} plus the parent's VMG up/down targets, both tacks; speed = polar x efficiency; the tack /
  gybe penalty is taken from the step when the tack changes.
- Exact arrival: for every parent, the direct shot to the target; when it fits in the step and
  its segment is clear, arrive at t + need (minimum over parents).
- Pruning: sectors of ``sector_deg`` by bearing from the leg origin; within a sector rank by
  max(geodesic distance by water, straight-line distance) to the target; land-check only the best
  ``lazy_k`` candidates and keep the first clear one (a sector whose ``lazy_k`` are all blocked is
  dropped for this step).
- Time step from the schedule, forced to ``fine_dt_s`` near the target, near the leg origin, or
  when the leading front points are near land (30-min segments cannot thread 1 km channels).
- The shipped path is decimated (only where the shortcut is clear and the cross-track error is
  small; tack and arrival points kept) and re-validated against the mask; an invalid path is never
  returned as ok.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np

from jabuka.route.fields import Fields
from jabuka.route.frame import NM_M
from jabuka.route.landmask import GeoField, LandMask, compute_geofield
from jabuka.route.polar_grid import PolarGrid, normalize_curves
from jabuka.route.types import (
    CourseMark,
    LegResult,
    PathPoint,
    RouteRequest,
    RouteResult,
    TackPoint,
    Waypoint,
)

MIN_TWA_DEG = 30.0
MAX_PATH_POINTS = 300
DECIMATE_XTE_NM = 0.05
SNAP_MAX_NM = 1.0
UNREACHABLE_KEY = 1e6  # ranking key offset for candidates the geodesic field cannot reach
EXIT_MIN_KN = 1.0
SHOT_HORIZON_S = 3600.0  # arrival shots use the parent's wind for at most max(2 dt, this)


def mark_key(mark: CourseMark) -> tuple[float, float, float]:
    """Geofield key of a mark: (lat, lon, radius_nm) rounded like load_geofields."""
    return (round(float(mark.lat), 4), round(float(mark.lon), 4), round(float(mark.radius_nm), 3))


def heading_from_twa(twd_rad, twa_rad):
    """Heading (rad, [0, 2pi)) = TWD - TWA (conventions: twd = hdg + twa, TWA - = port)."""
    return np.mod(np.asarray(twd_rad) - np.asarray(twa_rad), 2.0 * math.pi)


def tack_of(twa) -> np.ndarray:
    """+1 starboard (TWA > 0), -1 port."""
    return np.where(np.asarray(twa) >= 0.0, 1, -1).astype(np.int8)


def _wrap_pi(a):
    return (np.asarray(a) + math.pi) % (2.0 * math.pi) - math.pi


@dataclass
class RouterEnv:
    """Everything a routing call needs that does not change between requests."""

    mask: LandMask
    fields: Fields
    geofields: dict[tuple[float, float, float], GeoField] = field(default_factory=dict)
    geo_cache: dict[Any, GeoField] = field(default_factory=dict)
    polar_cache: dict[Any, PolarGrid] = field(default_factory=dict)
    on_demand_gcell_nm: float = 400.0 / NM_M
    on_demand_mode: str = "any"

    @property
    def frame(self):
        return self.mask.frame

    def geofield_for(self, mark: CourseMark) -> GeoField:
        """Precomputed field when the mark key matches, else a cached on-demand field (400 m
        "any" by default, seeded within radius + one coarse cell)."""
        key = mark_key(mark)
        pre = self.geofields.get(key)
        if pre is not None:
            return pre
        ckey = (key, round(self.on_demand_gcell_nm, 6), self.on_demand_mode)
        geo = self.geo_cache.get(ckey)
        if geo is None:
            x, y = self.frame.to_xy(mark.lat, mark.lon)
            geo = compute_geofield(
                self.mask,
                [(x, y)],
                self.on_demand_gcell_nm,
                self.on_demand_mode,
                seed_radius_nm=float(mark.radius_nm) + self.on_demand_gcell_nm,
            )
            self.geo_cache[ckey] = geo
        return geo

    def polar_for(self, curves, eff: float, eff_up=None, eff_down=None) -> PolarGrid:
        cv = normalize_curves(curves)
        key = (cv, float(eff), eff_up, eff_down)
        pg = self.polar_cache.get(key)
        if pg is None:
            pg = PolarGrid.from_curves(cv, eff, eff_up, eff_down)
            self.polar_cache[key] = pg
        return pg


class RouteFailure(Exception):
    """A routing problem with a French reason (becomes RouteResult(ok=False))."""


class _Seg(NamedTuple):
    """Segment leaving a point: TWA deg (signed), tack, BSP kn, TWD deg, TWS kn."""

    twa: float
    tack: int
    bsp: float
    twd: float
    tws: float


class _Pt(NamedTuple):
    t: float
    x: float
    y: float
    seg: _Seg
    protect: bool  # never decimated (leg arrival, start)


@dataclass
class _Ctx:
    req: RouteRequest
    env: RouterEnv
    polar: PolarGrid
    steps: int = 0
    force_until: float = -math.inf
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- sampling
def _wind(ctx: _Ctx, t: float, x, y):
    """(TWD rad, TWS kn) per point."""
    return ctx.env.fields.wind.sample(t, x, y, ctx.req.bias)


def _speed(ctx: _Ctx, tws, twa_abs):
    return ctx.polar.speed(tws, twa_abs)


# ---------------------------------------------------------------------------- one leg
class _Shots(NamedTuple):
    """Arrival candidates from the front (flat arrays, one row per candidate)."""

    t_arr: np.ndarray
    parent: np.ndarray
    boards: np.ndarray  # 1 (straight) or 2 (one tack/gybe on the way, at the VMG targets)
    mx: np.ndarray  # mid point (2 boards)
    my: np.ndarray
    mt: np.ndarray
    twa1: np.ndarray
    tack1: np.ndarray
    bsp1: np.ndarray
    twa2: np.ndarray
    tack2: np.ndarray
    bsp2: np.ndarray


def _shots(ctx: _Ctx, t, dt, px, py, ptack, target, twd, tws, force_tack: int) -> _Shots:
    """Exact arrivals by direct shot (one board) and by two boards on the VMG targets when the
    target lies inside the upwind or downwind cone (the layline tack is not quantised to the
    step). The wind is sampled at the parent, so a shot may last at most max(2 dt, 1 h)."""
    s = ctx.req.settings
    pen = s.tack_penalty_s
    horizon = max(2.0 * dt, SHOT_HORIZON_S)
    tx, ty = target
    n = px.size
    dx, dy = tx - px, ty - py
    dist = np.hypot(dx, dy)
    hdg = np.mod(np.arctan2(dx, dy), 2.0 * math.pi)
    twa_b = np.degrees(_wrap_pi(twd - hdg))
    bsp_b = _speed(ctx, tws, np.abs(twa_b))
    tack_b = tack_of(twa_b)
    with np.errstate(divide="ignore", invalid="ignore"):
        need = np.where(bsp_b > 1e-6, dist / np.maximum(bsp_b, 1e-6) * 3600.0, np.inf)
    need = need + np.where((tack_b != ptack) & (ptack != 0), pen, 0.0)
    ok1 = (np.abs(twa_b) >= MIN_TWA_DEG - 1e-9) & (need <= horizon)
    if force_tack:
        ok1 &= tack_b == force_tack
    idx = np.arange(n)
    rows = [
        (
            t + need[ok1],
            idx[ok1],
            np.ones(int(ok1.sum()), np.int8),
            np.full(int(ok1.sum()), np.nan),
            np.full(int(ok1.sum()), np.nan),
            np.full(int(ok1.sum()), np.nan),
            twa_b[ok1],
            tack_b[ok1],
            bsp_b[ok1],
            twa_b[ok1],
            tack_b[ok1],
            bsp_b[ok1],
        )
    ]
    # two boards at +-theta (theta = up target inside the upwind cone, down target downwind)
    up, down = ctx.polar.targets(tws)
    a = np.abs(twa_b)
    theta = np.where(a < up, up, np.where(a > down, down, np.nan))
    two = np.isfinite(theta) & (dist > 1e-6)
    if two.any():
        i2 = idx[two]
        th = theta[two]
        v = _speed(ctx, tws[two], th)
        hp = twd[two] - np.radians(th)  # starboard board (TWA +theta)
        hm = twd[two] + np.radians(th)  # port board
        gpx, gpy = v * np.sin(hp), v * np.cos(hp)
        gmx, gmy = v * np.sin(hm), v * np.cos(hm)
        det = gpx * gmy - gpy * gmx
        with np.errstate(divide="ignore", invalid="ignore"):
            tp = (dx[two] * gmy - dy[two] * gmx) / det * 3600.0
            tm = (gpx * dy[two] - gpy * dx[two]) / det * 3600.0
        good = (np.abs(det) > 1e-9) & (tp > 0) & (tm > 0) & np.isfinite(tp) & np.isfinite(tm)
        pt = ptack[two]
        for first in (1, -1):
            t1, t2 = (tp, tm) if first == 1 else (tm, tp)
            g1x, g1y = (gpx, gpy) if first == 1 else (gmx, gmy)
            p1 = np.where((pt != first) & (pt != 0), pen, 0.0)
            tot = p1 + t1 + pen + t2
            ok = good & (tot <= horizon)
            if force_tack:
                ok &= (first == force_tack) & (t + p1 + t1 >= ctx.force_until)
            if not ok.any():
                continue
            k = int(ok.sum())
            rows.append(
                (
                    t + tot[ok],
                    i2[ok],
                    np.full(k, 2, np.int8),
                    px[i2[ok]] + g1x[ok] * t1[ok] / 3600.0,
                    py[i2[ok]] + g1y[ok] * t1[ok] / 3600.0,
                    t + p1[ok] + t1[ok],
                    first * th[ok],
                    np.full(k, first, np.int8),
                    v[ok],
                    -first * th[ok],
                    np.full(k, -first, np.int8),
                    v[ok],
                )
            )
    return _Shots(*(np.concatenate(c) for c in zip(*rows, strict=True)))


def _best_shot(ctx: _Ctx, sh: _Shots, px, py, target, best_t: float):
    """Earliest clear shot arriving before best_t (lazy land checks, earliest first)."""
    tx, ty = target
    cand = np.nonzero(sh.t_arr < best_t)[0]
    if cand.size == 0:
        return None
    cand = cand[np.argsort(sh.t_arr[cand], kind="stable")]
    mask = ctx.env.mask
    for b in range(0, cand.size, 32):
        c = cand[b : b + 32]
        p = sh.parent[c]
        two = sh.boards[c] == 2
        ax = np.where(two, sh.mx[c], px[p])
        ay = np.where(two, sh.my[c], py[p])
        clear = mask.segments_clear(ax, ay, np.full(c.size, tx), np.full(c.size, ty))
        if two.any():
            clear[two] &= mask.segments_clear(px[p[two]], py[p[two]], sh.mx[c[two]], sh.my[c[two]])
        if clear.any():
            return int(c[int(np.argmax(clear))])
    return None


def _route_leg(ctx: _Ctx, start: _Pt, tack0: int, target: tuple[float, float], geo: GeoField):
    """Isochrones from ``start`` to ``target``. Returns (points without the arrival, arrival
    point). The arrival point's segment is a copy of the last one (replaced by the next leg)."""
    req, env, s = ctx.req, ctx.env, ctx.req.settings
    mask = env.mask
    tx, ty = target
    ox, oy = start.x, start.y
    t = start.t
    fx = np.array([ox])
    fy = np.array([oy])
    ftack = np.array([tack0], dtype=np.int8)
    # history per step: (t, x, y, parent, twa, tack, bsp, twd, tws) arrays of the nodes
    hist: list[tuple] = []
    best = None  # (t_arr, len(hist), shots, row, twd, tws)
    base = np.arange(MIN_TWA_DEG, 180.0 + 1e-9, s.hdg_step_deg)
    if base[-1] < 180.0 - 1e-9:
        base = np.append(base, 180.0)
    sector_rad = math.radians(s.sector_deg)
    for _step in range(s.max_steps):
        ctx.steps += 1
        n = fx.size
        twd, tws = _wind(ctx, t, fx, fy)
        dtt = np.hypot(tx - fx, ty - fy)
        dt = s.dt_for(t - req.t0)
        lead = np.argsort(dtt)[: max(1, int(math.ceil(0.2 * n)))]
        fine = bool(dtt.min() < s.near_target_nm) or bool(
            (np.hypot(fx[lead] - ox, fy[lead] - oy) < s.near_target_nm).any()
        )
        if not fine:
            fine = bool(mask.near_land(fx[lead], fy[lead], s.near_land_nm).any())
        if fine:
            dt = min(dt, s.fine_dt_s)
        # ---- exact arrival: keep the best shot until the front time passes it
        sh = _shots(ctx, t, dt, fx, fy, ftack, (tx, ty), twd, tws, 0)
        best_t = best[0] if best is not None else math.inf
        row = _best_shot(ctx, sh, fx, fy, (tx, ty), best_t)
        if row is not None:
            best = (float(sh.t_arr[row]), len(hist), sh, row, twd, tws)
        if best is not None and best[0] <= t + dt:
            return _arrival(start, hist, best, (tx, ty))
        # ---- expansion
        up, down = ctx.polar.targets(tws)
        twa_abs = np.concatenate(
            [np.broadcast_to(base, (n, base.size)), up[:, None], down[:, None]], axis=1
        )
        twa = np.concatenate([twa_abs, -twa_abs], axis=1)
        tack = np.where(twa > 0, 1, -1).astype(np.int8)
        bsp = _speed(ctx, tws[:, None], np.abs(twa))
        hdg = twd[:, None] - np.radians(twa)
        flip = (tack != ftack[:, None]) & (ftack[:, None] != 0)
        d = bsp * np.maximum(dt - np.where(flip, s.tack_penalty_s, 0.0), 0.0) / 3600.0
        cx = fx[:, None] + d * np.sin(hdg)
        cy = fy[:, None] + d * np.cos(hdg)
        par = np.broadcast_to(np.arange(n)[:, None], cx.shape)
        cx, cy, par = cx.ravel(), cy.ravel(), par.ravel()
        twa_f, tack_f, bsp_f = twa.ravel(), tack.ravel(), bsp.ravel()
        sel = _prune(ctx, fx, fy, cx, cy, par, (ox, oy), (tx, ty), geo, sector_rad)
        if sel.size == 0:
            if best is not None:
                return _arrival(start, hist, best, (tx, ty))
            raise RouteFailure("aucune expansion valide (front bloqué par la terre)")
        pi = par[sel]
        t = t + dt
        hist.append(
            (
                t,
                cx[sel],
                cy[sel],
                pi,
                twa_f[sel],
                tack_f[sel],
                bsp_f[sel],
                np.degrees(twd[pi]),
                tws[pi],
            )
        )
        fx, fy, ftack = cx[sel], cy[sel], tack_f[sel]
    if best is not None:
        return _arrival(start, hist, best, (tx, ty))
    raise RouteFailure(f"trop d'étapes (> {s.max_steps}) sans atteindre la marque")


def _prune(ctx, fx, fy, cx, cy, par, origin, target, geo: GeoField, sector_rad: float):
    """Indices of the kept candidates: per bearing sector from the origin, the best-ranked of
    the first lazy_k whose segment parent -> child is clear."""
    s = ctx.req.settings
    ox, oy = origin
    tx, ty = target
    brg = np.mod(np.arctan2(cx - ox, cy - oy), 2.0 * math.pi)
    sector = np.floor(brg / sector_rad).astype(np.int64)
    euclid = np.hypot(tx - cx, ty - cy)
    g = geo.distance(cx, cy)
    key = np.where(np.isfinite(g), np.maximum(g, euclid), UNREACHABLE_KEY + euclid)
    order = np.lexsort((key, sector))
    ss = sector[order]
    first = np.ones(ss.size, dtype=bool)
    first[1:] = ss[1:] != ss[:-1]
    starts = np.nonzero(first)[0]
    gid = np.cumsum(first) - 1
    rank = np.arange(ss.size) - starts[gid]
    cand = order[rank < s.lazy_k]
    pi = par[cand]
    ok = ctx.env.mask.segments_clear(fx[pi], fy[pi], cx[cand], cy[cand])
    good = cand[ok]
    if good.size == 0:
        return good
    _, first_idx = np.unique(sector[good], return_index=True)
    return good[first_idx]


def _arrival(start: _Pt, hist: list[tuple], best, target) -> tuple[list[_Pt], _Pt]:
    t_arr, k, sh, row, twd, tws = best
    p = int(sh.parent[row])
    twd_p, tws_p = float(np.degrees(twd[p])), float(tws[p])
    seg1 = _Seg(float(sh.twa1[row]), int(sh.tack1[row]), float(sh.bsp1[row]), twd_p, tws_p)
    pts = _backtrack(start, hist[:k], p, seg1)
    seg2 = seg1
    if int(sh.boards[row]) == 2:
        seg2 = _Seg(float(sh.twa2[row]), int(sh.tack2[row]), float(sh.bsp2[row]), twd_p, tws_p)
        pts.append(_Pt(float(sh.mt[row]), float(sh.mx[row]), float(sh.my[row]), seg2, False))
    return pts, _Pt(t_arr, target[0], target[1], seg2, True)


def _backtrack(start: _Pt, hist: list[tuple], idx: int, last_seg: _Seg) -> list[_Pt]:
    """Points from the leg start to the front node ``idx`` of the last step, each carrying the
    segment that leaves it (the last one carries ``last_seg``, the direct shot)."""
    nodes = []
    for k in range(len(hist) - 1, -1, -1):
        tk, x, y, par, twa, tack, bsp, twd, tws = hist[k]
        nodes.append(
            (
                tk,
                float(x[idx]),
                float(y[idx]),
                _Seg(
                    float(twa[idx]),
                    int(tack[idx]),
                    float(bsp[idx]),
                    float(twd[idx]),
                    float(tws[idx]),
                ),
            )
        )
        idx = int(par[idx])
    nodes.reverse()
    # node k's own segment is the one that ARRIVES at it; shift so each point carries the
    # segment that leaves it.
    out: list[_Pt] = []
    segs = [n[3] for n in nodes] + [last_seg]
    out.append(_Pt(start.t, start.x, start.y, segs[0], start.protect))
    for i, (tk, x, y, _seg) in enumerate(nodes):
        out.append(_Pt(tk, x, y, segs[i + 1], False))
    return out


# ---------------------------------------------------------------------------- whole route
def _waypoints(req: RouteRequest) -> list[Waypoint]:
    """Task 1: every mark is a point to reach (rounding comes with rounding.expand)."""
    out = []
    for i, m in enumerate(req.marks):
        kind = "finish" if i == len(req.marks) - 1 else "mark"
        out.append(Waypoint(m.lat, m.lon, m.mark_id, kind, i))
    return out


def _validate_request(req: RouteRequest) -> None:
    for name in ("t0", "lat", "lon"):
        v = getattr(req, name)
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise RouteFailure(f"requête invalide : {name} = {v!r}")
    if not (-90.0 <= req.lat <= 90.0 and -180.0 <= req.lon <= 180.0):
        raise RouteFailure("requête invalide : position hors limites")
    if req.tack0 not in (-1, 0, 1):
        raise RouteFailure(f"requête invalide : bord {req.tack0!r}")
    if not req.marks:
        raise RouteFailure("aucune marque à rallier")
    for m in req.marks:
        if not (
            math.isfinite(m.lat)
            and math.isfinite(m.lon)
            and math.isfinite(m.radius_nm)
            and 0.0 <= m.radius_nm <= 5.0
        ):
            raise RouteFailure(f"marque invalide : {m.name}")
        if m.side not in ("port", "stbd", "none"):
            raise RouteFailure(f"côté invalide pour {m.name} : {m.side!r}")
    problems = req.settings.problems()
    if problems:
        raise RouteFailure("réglages invalides : " + ", ".join(problems))


def _snap_target(ctx: _Ctx, x: float, y: float, name: str) -> tuple[float, float]:
    snap = ctx.env.mask.snap_clear(x, y, SNAP_MAX_NM)
    if snap is None:
        raise RouteFailure(f"cible dans la terre, aucune eau libre à {SNAP_MAX_NM:g} nm : {name}")
    sx, sy, moved = snap
    if moved:
        ctx.notes.append(f"cible déplacée hors de la marge côtière : {name}")
    return sx, sy


def _start(ctx: _Ctx) -> tuple[list[_Pt], _Pt, bool]:
    """(prefix points, routing start, start_in_margin). A start inside the dilated mask is
    snapped to the nearest clear cell and the exit segment (checked against raw land) is
    prepended."""
    req = ctx.req
    frame = ctx.env.frame
    x, y = frame.to_xy(req.lat, req.lon)
    snap = ctx.env.mask.snap_clear(x, y, SNAP_MAX_NM)
    if snap is None:
        raise RouteFailure(f"départ dans la terre : aucune eau libre à {SNAP_MAX_NM:g} nm")
    sx, sy, moved = snap
    if not moved:
        twd, tws = _wind(ctx, req.t0, x, y)
        seg = _Seg(0.0, int(req.tack0), 0.0, float(np.degrees(twd[0])), float(tws[0]))
        return [], _Pt(req.t0, x, y, seg, True), False
    ctx.notes.append("départ dans la marge côtière")
    twd, tws = _wind(ctx, req.t0, x, y)
    hdg = math.atan2(sx - x, sy - y)
    twa = float(np.degrees(_wrap_pi(twd[0] - hdg)))
    tack = int(req.tack0) if req.tack0 else (1 if twa >= 0 else -1)
    up, _down = ctx.polar.targets(tws)
    bsp = float(_speed(ctx, tws, max(abs(twa), float(up[0])))[0])
    dist = math.hypot(sx - x, sy - y)
    t1 = req.t0 + dist / max(bsp, EXIT_MIN_KN) * 3600.0
    seg = _Seg(math.copysign(abs(twa), tack), tack, bsp, float(np.degrees(twd[0])), float(tws[0]))
    first = _Pt(req.t0, x, y, seg, True)
    seg1 = _Seg(0.0, tack, 0.0, seg.twd, seg.tws)
    return [first], _Pt(t1, sx, sy, seg1, True), True


def _tack_points(pts: list[_Pt], tack0: int, frame) -> list[TackPoint]:
    out = []
    prev = tack0
    for p in pts[:-1]:
        tk = p.seg.tack
        if prev != 0 and tk != 0 and tk != prev:
            lat, lon = frame.to_ll(p.x, p.y)
            kind = "gybe" if abs(p.seg.twa) >= 90.0 else "tack"
            out.append(TackPoint(p.t, lat, lon, prev, tk, kind))
        if tk != 0:
            prev = tk
    return out


def _xte(ax, ay, bx, by, px, py) -> np.ndarray:
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy)
    if L < 1e-12:
        return np.hypot(px - ax, py - ay)
    return np.abs((px - ax) * dy - (py - ay) * dx) / L


def _decimate(pts: list[_Pt], mask: LandMask, tol: float, protect: set[int]) -> list[_Pt]:
    """Greedy: from each kept anchor, skip points while the shortcut is clear, keeps the same
    tack and stays within ``tol`` nm of every skipped point."""
    n = len(pts)
    if n <= 2:
        return pts
    xs = np.array([p.x for p in pts])
    ys = np.array([p.y for p in pts])
    keep = [0]
    a = 0
    j = 1
    while j < n - 1:
        ok = (
            j not in protect
            and pts[j].seg.tack == pts[a].seg.tack
            and float(
                _xte(xs[a], ys[a], xs[j + 1], ys[j + 1], xs[a + 1 : j + 1], ys[a + 1 : j + 1]).max()
            )
            < tol
            and bool(mask.segments_clear(xs[a], ys[a], xs[j + 1], ys[j + 1])[0])
        )
        if ok:
            j += 1
            continue
        keep.append(j)
        a = j
        j = a + 1
    keep.append(n - 1)
    return [pts[i] for i in keep]


def _protected(pts: list[_Pt], tack0: int) -> set[int]:
    out = {0, len(pts) - 1}
    prev = tack0
    for i, p in enumerate(pts):
        if p.protect:
            out.add(i)
        if prev != 0 and p.seg.tack != 0 and p.seg.tack != prev:
            out.add(i)
        if p.seg.tack != 0:
            prev = p.seg.tack
    return out


def route(req: RouteRequest, env: RouterEnv) -> RouteResult:
    """Time-optimal route through the remaining marks (see module docstring). Never raises for
    a routing problem: failures come back as ok False with a French reason."""
    t_start = time.perf_counter()
    ctx: _Ctx | None = None
    try:
        _validate_request(req)
        try:
            polar = env.polar_for(req.polar_curves, req.eff, req.eff_up, req.eff_down)
        except ValueError as exc:
            raise RouteFailure(str(exc)) from None
        ctx = _Ctx(req, env, polar)
        return _route(ctx, t_start)
    except RouteFailure as exc:
        return RouteResult(
            ok=False,
            reason=str(exc),
            request_id=req.request_id,
            t0=req.t0,
            level=req.settings.level,
            compute_ms=(time.perf_counter() - t_start) * 1000.0,
            steps=ctx.steps if ctx else 0,
            notes=tuple(ctx.notes) if ctx else (),
        )


def _route(ctx: _Ctx, t_start: float) -> RouteResult:
    req, env = ctx.req, ctx.env
    frame = env.frame
    prefix, cur, start_in_margin = _start(ctx)
    wps = _waypoints(req)
    pts: list[_Pt] = list(prefix)
    legs: list[LegResult] = []
    tack = int(req.tack0) if not start_in_margin else cur.seg.tack
    for k, wp in enumerate(wps):
        mark = req.marks[wp.mark_index]
        tx, ty = frame.to_xy(wp.lat, wp.lon)
        tx, ty = _snap_target(ctx, tx, ty, mark.name)
        geo = env.geofield_for(mark)
        leg_pts, arrival = _route_leg(ctx, cur, tack, (tx, ty), geo)
        pts.extend(leg_pts)
        tack = arrival.seg.tack
        cur = arrival
        last_of_mark = k == len(wps) - 1 or wps[k + 1].mark_index != wp.mark_index
        if last_of_mark:
            lat, lon = frame.to_ll(arrival.x, arrival.y)
            legs.append(LegResult(mark.mark_id, arrival.t, lat, lon))
    pts.append(cur)
    tacks = _tack_points(pts, int(req.tack0), frame)
    protect = _protected(pts, int(req.tack0))
    if start_in_margin:
        protect.add(1)
    shipped = pts
    tol = DECIMATE_XTE_NM
    while True:
        shipped = _decimate(pts, env.mask, tol, protect)
        if len(shipped) <= MAX_PATH_POINTS or tol > 1.0:
            break
        tol *= 2.0
    if tol > DECIMATE_XTE_NM:
        ctx.notes.append(f"route simplifiée à {tol:g} nm")
    xs = np.array([p.x for p in shipped])
    ys = np.array([p.y for p in shipped])
    v0 = 1 if start_in_margin else 0
    valid, _bad = env.mask.validate_polyline(xs[v0:], ys[v0:])
    if start_in_margin:
        valid = valid and bool(env.mask.raw_segments_clear(xs[0], ys[0], xs[1], ys[1])[0])
    if not valid:
        raise RouteFailure("route invalide (terre)")
    lat, lon = frame.to_ll(xs, ys)
    path = tuple(
        PathPoint(
            float(p.t),
            float(la),
            float(lo),
            float(p.seg.twa),
            int(p.seg.tack),
            float(p.seg.bsp),
            float(p.seg.twd),
            float(p.seg.tws),
        )
        for p, la, lo in zip(shipped, np.atleast_1d(lat), np.atleast_1d(lon), strict=True)
    )
    eta = float(cur.t)
    return RouteResult(
        ok=True,
        reason=None,
        request_id=req.request_id,
        t0=req.t0,
        path=path,
        tacks=tuple(tacks),
        legs=tuple(legs),
        eta=eta,
        valid=True,
        horizon_hold=env.fields.wind.horizon_hold(eta),
        start_in_margin=start_in_margin,
        force_released_at=None,
        level=req.settings.level,
        compute_ms=(time.perf_counter() - t_start) * 1000.0,
        steps=ctx.steps,
        notes=tuple(ctx.notes),
    )
