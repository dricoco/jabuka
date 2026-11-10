"""The core's "On reste" display route: the forced current leg, then the rest of the course.

The routing worker computes the forced route ("stay on this tack") for the current leg only
(``leg_only``), because the cost of not tacking is a current-leg quantity. Shown alone, that
route would drop every later leg from the map and turn the route ETA into the active-mark ETA.
``stay_route`` composes the displayed route instead (quick-261110-iil, D-01/D-02):

- the forced route up to its arrival at the active mark (path, tacks, leg ETA unchanged);
- then the SAME cycle's optimal route from that mark onward (path points, tack points, later
  leg ETAs), shifted in time by ``delta = forced ETA at the mark - optimal ETA at the mark``;
- the route ETA is the finish: ``optimal.eta + delta``.

The junction is the forced arrival point (its time and position) carrying the optimal's
segment leaving the mark, so the path stays continuous in time and space; a tack at the
junction is added when the forced boat arrives on another tack than the next leg leaves on
(the same rule as ``isochrone._tack_points``).

Whenever the two routes cannot be joined safely, ``forced`` itself is returned unchanged
(D-06): the helm then sees the current leg only, as before. Pure: stdlib + route types, no
clock, no numpy.
"""

from __future__ import annotations

import dataclasses
import logging
import math

from jabuka.route.types import LegResult, PathPoint, RouteResult, TackPoint

log = logging.getLogger(__name__)

JOIN_TOL_S = 1.0  # the optimal path point at the mark carries the leg ETA (same float)
JOIN_TOL_NM = 0.1  # forced and optimal arrive at the same (snapped) mark target

REASON_LAST_LEG = "last leg"  # nothing to append: the forced ETA already is the finish


def _finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)


def _usable(r: RouteResult | None) -> bool:
    return bool(
        r is not None and r.ok and r.path and r.legs and _finite(r.eta) and _finite(r.legs[0].eta)
    )


def _dist_nm(a: PathPoint, b: PathPoint) -> float:
    """Equirectangular distance (nm): plenty for a 0.1 nm junction check."""
    dlat = (b.lat - a.lat) * 60.0
    dlon = (b.lon - a.lon) * 60.0 * math.cos(math.radians(0.5 * (a.lat + b.lat)))
    return math.hypot(dlat, dlon)


def _join_index(forced: RouteResult, optimal: RouteResult) -> tuple[int | None, str | None]:
    """Index of the optimal path point at the active mark, or (None, why not)."""
    if not _usable(forced):
        return None, "forced route not usable"
    if not _usable(optimal):
        return None, "optimal route not usable"
    if len(optimal.legs) < 2:
        return None, REASON_LAST_LEG
    if forced.legs[0].mark_id != optimal.legs[0].mark_id:
        return None, (
            f"active mark mismatch ({forced.legs[0].mark_id} != {optimal.legs[0].mark_id})"
        )
    t_mark = float(optimal.legs[0].eta)
    best, best_dt = None, JOIN_TOL_S
    for i, p in enumerate(optimal.path):
        dt = abs(p.t - t_mark)
        if dt <= best_dt:
            best, best_dt = i, dt
    if best is None:
        return None, "no optimal path point at the active-mark ETA"
    if best >= len(optimal.path) - 1:
        return None, "the active-mark point ends the optimal path"
    d = _dist_nm(optimal.path[best], forced.path[-1])
    if not math.isfinite(d) or d > JOIN_TOL_NM:
        return None, f"junction {d:.2f} nm from the forced arrival"
    return best, None


def _appended_tacks(path: list[PathPoint], start: int, prev: int) -> list[TackPoint]:
    """``isochrone._tack_points`` on ``path[start:-1]`` (the arrival never tacks)."""
    out = []
    for p in path[start:-1]:
        tk = p.tack
        if prev != 0 and tk != 0 and tk != prev:
            kind = "gybe" if abs(p.twa_deg) >= 90.0 else "tack"
            out.append(TackPoint(p.t, p.lat, p.lon, prev, tk, kind))
        if tk != 0:
            prev = tk
    return out


def stay_route(forced: RouteResult, optimal: RouteResult) -> RouteResult:
    """Forced current leg + the optimal continuation shifted by the forced delay (see module
    docstring). Returns ``forced`` itself when the two cannot be composed; never raises for
    malformed routes."""
    j, why = _join_index(forced, optimal)
    if j is None:
        if why == REASON_LAST_LEG:
            log.debug("stay route: forced route only (%s)", why)
        else:
            log.info("stay route: forced route only (%s)", why)
        return forced
    assert forced.eta is not None and optimal.eta is not None  # _usable
    delta = float(forced.legs[0].eta) - float(optimal.legs[0].eta)  # not clamped: continuity
    arrival = forced.path[-1]
    at_mark = optimal.path[j]
    junction = arrival._replace(
        twa_deg=at_mark.twa_deg,
        tack=at_mark.tack,
        bsp_kn=at_mark.bsp_kn,
        twd_deg=at_mark.twd_deg,
        tws_kn=at_mark.tws_kn,
    )
    head = list(forced.path[:-1])
    path = [*head, junction, *(p._replace(t=p.t + delta) for p in optimal.path[j + 1 :])]
    tacks = (*forced.tacks, *_appended_tacks(path, len(head), int(arrival.tack)))
    legs = (
        forced.legs[0],
        *(LegResult(lg.mark_id, lg.eta + delta, lg.lat, lg.lon) for lg in optimal.legs[1:]),
    )
    return dataclasses.replace(
        forced,
        path=tuple(path),
        tacks=tuple(tacks),
        legs=legs,
        eta=float(optimal.eta) + delta,
        valid=bool(forced.valid and optimal.valid),
        horizon_hold=bool(forced.horizon_hold or optimal.horizon_hold),
    )
