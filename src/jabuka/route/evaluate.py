"""Re-evaluate an existing route under new weather (hysteresis input, RESEARCH Pattern 9).

The old polyline is re-sailed from the boat's projection onto it, segment by segment (pieces of
at most 2 nm, weather sampled at the start of each piece like the router samples it at each
parent), at polar x efficiency x wave factor under the new wind / bias / current, with the course
to steer through the current and a tack penalty at every side change. A segment whose TWA falls
below 30 deg (minus a 5 deg sampling tolerance: the router itself sails 30 deg segments), that the
current makes impossible, or that crosses the land mask makes the old route invalid (French
reason). numpy only, pure: time comes from the caller.

The projection is restricted to the route-time window around the helm follower's projection when
the caller gives it (``t_hint``: the same window as advice.RouteFollower, 03-REVIEW MD-03), so a
hairpin's return leg never makes the old route look hours shorter, and the time to rejoin the
old route (cross-track distance at the reaching speed) is added.
"""

from __future__ import annotations

import math

import numpy as np

from jabuka.route.advice import AHEAD_S, BACK_S
from jabuka.route.bias import BiasParams
from jabuka.route.isochrone import (
    MIN_TWA_DEG,
    RouterEnv,
    boat_speed,
    course_to_steer,
    sample_weather,
)
from jabuka.route.polar_grid import PolarGrid
from jabuka.route.types import PathPoint, RouterSettings, TackPoint

PIECE_NM = 2.0
TWA_TOLERANCE_DEG = 5.0
MIN_ALONG_KN = 0.05
REJOIN_MIN_NM = 0.01  # closer than this: on the old route, no rejoin time


def project(
    xs: np.ndarray,
    ys: np.ndarray,
    x: float,
    y: float,
    ts: np.ndarray | None = None,
    window: tuple[float, float] | None = None,
) -> tuple[int, float]:
    """(segment index, fraction 0..1) of the point of the polyline nearest to (x, y); with
    ``ts`` (point times) and ``window`` (lo, hi), only the part of the polyline whose time is
    inside the window (falls back to the whole polyline when nothing is)."""
    ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(L2 > 0, ((x - ax) * dx + (y - ay) * dy) / L2, 0.0)
    lo = np.zeros_like(f)
    hi = np.ones_like(f)
    ok = np.ones(f.shape, dtype=bool)
    if ts is not None and window is not None:
        t0, t1 = ts[:-1], ts[1:]
        dt = t1 - t0
        ok = (t0 <= window[1]) & (t1 >= window[0])
        if ok.any():
            with np.errstate(divide="ignore", invalid="ignore"):
                lo = np.where(dt > 0, np.clip((window[0] - t0) / dt, 0.0, 1.0), 0.0)
                hi = np.where(dt > 0, np.clip((window[1] - t0) / dt, 0.0, 1.0), 1.0)
            hi = np.maximum(hi, lo)
        else:
            ok = np.ones(f.shape, dtype=bool)
    f = np.clip(f, lo, hi)
    d = np.hypot(ax + f * dx - x, ay + f * dy - y)
    d = np.where(ok, d, np.inf)
    k = int(np.argmin(d))
    return k, float(f[k])


def first_side_change(
    path: tuple[PathPoint, ...] | list[PathPoint], after_t: float, tack0: int = 0
) -> TackPoint | None:
    """First tack/gybe of the path at or after ``after_t`` (a change at the first point counts
    when ``tack0`` is the boat's current tack). None when the path never changes side."""
    if len(path) < 2:
        return None
    prev = int(tack0)
    for p in path[:-1]:
        tk = int(p.tack)
        if prev != 0 and tk != 0 and tk != prev and p.t >= after_t:
            kind = "gybe" if abs(p.twa_deg) >= 90.0 else "tack"
            return TackPoint(p.t, p.lat, p.lon, prev, tk, kind)
        if tk != 0:
            prev = tk
    return None


def evaluate_path(
    path: tuple[PathPoint, ...] | list[PathPoint],
    lat: float,
    lon: float,
    t_now: float,
    env: RouterEnv,
    polar: PolarGrid,
    bias: BiasParams | None = None,
    settings: RouterSettings | None = None,
    t_hint: float | None = None,
) -> tuple[float | None, bool, str | None]:
    """(ETA at the end of the old path, valid, reason) re-sailed from the boat's projection.

    ``t_hint``: the route time of the helm follower's projection; the projection is then
    searched in [t_hint - BACK_S, t_hint + AHEAD_S] only (MD-03)."""
    s = settings or RouterSettings()
    if len(path) < 2:
        return None, False, "ancienne route trop courte"
    frame = env.frame
    xs, ys = frame.to_xy(np.array([p.lat for p in path]), np.array([p.lon for p in path]))
    ts = np.array([p.t for p in path], dtype=np.float64)
    bx, by = frame.to_xy(lat, lon)
    window = None if t_hint is None else (t_hint - BACK_S, t_hint + AHEAD_S)
    k, f = project(xs, ys, bx, by, ts, window)
    px = xs[k] + f * (xs[k + 1] - xs[k])
    py = ys[k] + f * (ys[k + 1] - ys[k])
    vx = np.concatenate(([px], xs[k + 1 :]))
    vy = np.concatenate(([py], ys[k + 1 :]))
    if len(vx) >= 2:
        clear = env.mask.segments_clear(vx[:-1], vy[:-1], vx[1:], vy[1:])
        if not clear.all():
            bad = int(np.argmin(clear)) + k
            return None, False, f"l'ancienne route traverse la terre (segment {bad})"
    t = float(t_now)
    xte = math.hypot(float(px - bx), float(py - by))
    if xte > REJOIN_MIN_NM:  # the boat is off the old route: time to rejoin it, on a reach
        wx = sample_weather(env, t, np.array([float(bx)]), np.array([float(by)]), bias, s)
        reach = float(boat_speed(polar, wx.tws, np.array([90.0]), wx.hs, s)[0])
        if not reach > MIN_ALONG_KN:
            return None, False, "ancienne route hors d'atteinte (pas de vent)"
        t += xte / reach * 3600.0
    prev_tack = int(path[k].tack)
    for i in range(len(vx) - 1):
        ax, ay, ex, ey = vx[i], vy[i], vx[i + 1], vy[i + 1]
        length = math.hypot(ex - ax, ey - ay)
        if length < 1e-9:
            continue
        brg = math.atan2(ex - ax, ey - ay) % (2.0 * math.pi)
        n = max(1, math.ceil(length / PIECE_NM))
        piece = length / n
        for j in range(n):
            qx = ax + (ex - ax) * j / n
            qy = ay + (ey - ay) * j / n
            wx = sample_weather(env, t, qx, qy, bias, s)
            twa, _bsp, along = course_to_steer(polar, wx, np.array([brg]), s)
            twa_d = float(twa[0])
            if abs(twa_d) < MIN_TWA_DEG - TWA_TOLERANCE_DEG:
                return (
                    None,
                    False,
                    f"segment {k + i} trop près du vent (TWA {abs(twa_d):.0f}° < "
                    f"{MIN_TWA_DEG:.0f}°)",
                )
            sog = float(along[0])
            if sog < MIN_ALONG_KN:
                return None, False, f"segment {k + i} impossible (vent ou courant)"
            tack = 1 if twa_d >= 0 else -1
            if prev_tack != 0 and tack != prev_tack:
                t += s.tack_penalty_s
            prev_tack = tack
            t += piece / sog * 3600.0
    return t, True, None
