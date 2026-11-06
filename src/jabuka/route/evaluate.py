"""Re-evaluate an existing route under new weather (hysteresis input, RESEARCH Pattern 9).

The old polyline is re-sailed from the boat's projection onto it, segment by segment (pieces of
at most 2 nm, weather sampled at the start of each piece like the router samples it at each
parent), at polar x efficiency x wave factor under the new wind / bias / current, with the course
to steer through the current and a tack penalty at every side change. A segment whose TWA falls
below 30 deg (minus a 5 deg sampling tolerance: the router itself sails 30 deg segments), that the
current makes impossible, or that crosses the land mask makes the old route invalid (French
reason). numpy only, pure: time comes from the caller.
"""

from __future__ import annotations

import math

import numpy as np

from jabuka.route.bias import BiasParams
from jabuka.route.isochrone import MIN_TWA_DEG, RouterEnv, course_to_steer, sample_weather
from jabuka.route.polar_grid import PolarGrid
from jabuka.route.types import PathPoint, RouterSettings, TackPoint

PIECE_NM = 2.0
TWA_TOLERANCE_DEG = 5.0
MIN_ALONG_KN = 0.05


def project(xs: np.ndarray, ys: np.ndarray, x: float, y: float) -> tuple[int, float]:
    """(segment index, fraction 0..1) of the point of the polyline nearest to (x, y)."""
    ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(L2 > 0, ((x - ax) * dx + (y - ay) * dy) / L2, 0.0)
    f = np.clip(f, 0.0, 1.0)
    d = np.hypot(ax + f * dx - x, ay + f * dy - y)
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
) -> tuple[float | None, bool, str | None]:
    """(ETA at the end of the old path, valid, reason) re-sailed from the boat's projection."""
    s = settings or RouterSettings()
    if len(path) < 2:
        return None, False, "ancienne route trop courte"
    frame = env.frame
    xs, ys = frame.to_xy(np.array([p.lat for p in path]), np.array([p.lon for p in path]))
    bx, by = frame.to_xy(lat, lon)
    k, f = project(xs, ys, bx, by)
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
