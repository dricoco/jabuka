"""Tack advice: follow the current route, detect tacks, flag a missed tack (ROUT-06/09/10).

Pure Python (stdlib + jabuka.common), no numpy and no clock reads: every time is an argument
(UTC epoch seconds from the GPS-disciplined clock). Angles in this module are DEGREES because
they come straight from the route path and go straight to the helm display.

Conventions (jabuka.common.conventions): TWA signed, negative = port; twd = hdg + twa, so the
heading to steer for a target TWA is ``hdg = TWD - TWA`` (RESEARCH Pitfall 1; CONTEXT's
"TWD + TWA" assumes the opposite TWA sign).

Route path point (tuple-like, 03-03's PathPoint starts with these fields in this order):
``(t, lat, lon, twa_deg, tack, ...)`` with tack +1 starboard / -1 port. Point i carries the
TWA sailed from point i to point i + 1. Tack point: ``(t, lat, lon, from_tack, to_tack, kind)``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, NamedTuple

LAT0 = 43.4  # local equirectangular frame origin (same constants as route/frame.py)
LON0 = 15.65
NM_PER_DEG_LAT = 60.0
SEARCH_AHEAD = 40  # segments searched ahead of the last projection
GLOBAL_SEARCH_NM = 2.0  # beyond this distance from all of them, search the whole rest
_EPS = 1e-12


def _wrap180(a: float) -> float:
    """Degrees wrapped to (-180, 180]."""
    r = math.fmod(a, 360.0)
    if r <= -180.0:
        r += 360.0
    elif r > 180.0:
        r -= 360.0
    return r


def _wrap360(a: float) -> float:
    """Degrees wrapped to [0, 360)."""
    r = math.fmod(a, 360.0)
    if r < 0.0:
        r += 360.0
    if r >= 360.0:
        r = 0.0
    return r


def to_xy(lat: float, lon: float, lat0: float = LAT0, lon0: float = LON0) -> tuple[float, float]:
    """(lat, lon) degrees -> local (x east, y north) in nautical miles."""
    return (
        (lon - lon0) * NM_PER_DEG_LAT * math.cos(math.radians(lat0)),
        (lat - lat0) * NM_PER_DEG_LAT,
    )


def from_xy(x: float, y: float, lat0: float = LAT0, lon0: float = LON0) -> tuple[float, float]:
    """Local (x, y) nautical miles -> (lat, lon) degrees. Inverse of to_xy."""
    return (
        lat0 + y / NM_PER_DEG_LAT,
        lon0 + x / (NM_PER_DEG_LAT * math.cos(math.radians(lat0))),
    )


def target_heading(twd_deg: float, twa_deg: float) -> float:
    """True heading (deg, [0, 360)) that sails ``twa_deg`` in a wind from ``twd_deg``."""
    return _wrap360(twd_deg - twa_deg)


# --------------------------------------------------------------------------------------------
# Tack detection
# --------------------------------------------------------------------------------------------


class TackEvent(NamedTuple):
    t_change: float  # UTC s: first sample on the new side
    new_side: int  # +1 starboard, -1 port
    kind: str  # "tack" | "gybe"


class TackDetector:
    """Confirm a side change once the angle (damped AWA, or TWA) has stayed on the other side,
    with |angle| in [min_deg, max_deg], for ``confirm_s`` seconds of valid samples.

    The first valid sample initialises the side without an event. ``None`` samples pause the
    confirmation (the gap is not counted) without resetting it or the side. Out-of-band samples
    (head to wind, dead downwind) pause it when on the candidate sign and reset it when back on
    the current side, so oscillation around 0 deg or 180 deg never confirms a tack.
    """

    def __init__(self, confirm_s: float = 30.0, min_deg: float = 15.0, max_deg: float = 165.0):
        self.confirm_s = confirm_s
        self.min_deg = min_deg
        self.max_deg = max_deg
        self.side = 0
        self.last_tack_t: float | None = None
        self._cand_start: float | None = None
        self._cand_last: float | None = None
        self._cand_held = 0.0

    def _reset_candidate(self) -> None:
        self._cand_start = None
        self._cand_last = None
        self._cand_held = 0.0

    def update(self, t: float, angle_deg: float | None) -> TackEvent | None:
        if angle_deg is None or not math.isfinite(angle_deg):
            self._cand_last = None  # pause: the gap does not count
            return None
        a = _wrap180(angle_deg)
        sign = 1 if a > 0.0 else -1
        in_band = self.min_deg <= abs(a) <= self.max_deg
        if self.side == 0:
            if in_band:
                self.side = sign
            return None
        if sign == self.side:
            self._reset_candidate()
            return None
        if not in_band:
            self._cand_last = None  # opposite sign but ambiguous: pause
            return None
        if self._cand_start is None:
            self._cand_start = t
            self._cand_last = t
            self._cand_held = 0.0
        else:
            if self._cand_last is not None and t > self._cand_last:
                self._cand_held += t - self._cand_last
            self._cand_last = t
        if self._cand_held >= self.confirm_s:
            t_change = self._cand_start
            self.side = sign
            self.last_tack_t = t_change
            self._reset_candidate()
            return TackEvent(t_change, sign, "tack" if abs(a) < 90.0 else "gybe")
        return None


# --------------------------------------------------------------------------------------------
# Route following
# --------------------------------------------------------------------------------------------


class Follow(NamedTuple):
    idx: int  # segment index (path[idx] -> path[idx + 1])
    t_route_here: float  # route time at the boat's projection (UTC s)
    xte_nm: float  # distance from the boat to the segment
    seg_course_deg: float  # true course of the segment
    course_dev_deg: float | None  # |COG - segment course| when COG is known
    target_twa: float  # signed deg, + = starboard
    target_tack: int  # +1 / -1
    target_hdg_t: float | None  # TWD - TWA when TWD is known
    next_tack: Any | None  # tack point tuple
    countdown_s: float | None  # route time to the next tack (negative = overdue)
    eta_now: float  # t_now + remaining route time
    remaining_s: float
    finished: bool


class RouteFollower:
    """Project the boat onto a route polyline (never backwards) and derive the helm advice.

    The countdown is measured in route time from the projection, so it stays right when the
    boat is early or late. An advised tack stays the "next tack" (with a negative countdown in
    wall time) while COG and TWD show the boat still sailing the old tack after the route has
    passed the tack point; this is what lets MissedTackWatch fire.
    """

    def __init__(
        self,
        path: Sequence[Sequence[Any]],
        tacks: Sequence[Sequence[Any]] = (),
        lat0: float = LAT0,
        lon0: float = LON0,
    ):
        if len(path) == 0:
            raise ValueError("empty route path")
        self.path = list(path)
        self.tacks = sorted(tacks, key=lambda k: float(k[0]))
        self._t = [float(p[0]) for p in self.path]
        self._xy = [to_xy(float(p[1]), float(p[2]), lat0, lon0) for p in self.path]
        self._lat0, self._lon0 = lat0, lon0
        n = len(self.path)
        self._nseg = max(1, n - 1)
        self._idx = 0
        # pending advised tack (overdue while the boat is still on the old tack)
        self._adv: Any | None = None
        self._adv_wall: float | None = None
        self._adv_overdue = False

    @property
    def idx(self) -> int:
        return self._idx

    def _seg(self, i: int) -> tuple[float, float, float, float]:
        """(x0, y0, dx, dy) of segment i (degenerate for a one-point path)."""
        x0, y0 = self._xy[i]
        if i + 1 < len(self._xy):
            x1, y1 = self._xy[i + 1]
        else:
            x1, y1 = x0, y0
        return x0, y0, x1 - x0, y1 - y0

    def _project(self, i: int, x: float, y: float) -> tuple[float, float]:
        """(distance nm, parameter s in [0, 1]) of (x, y) on segment i."""
        x0, y0, dx, dy = self._seg(i)
        l2 = dx * dx + dy * dy
        s = 0.0 if l2 < _EPS else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / l2))
        return math.hypot(x - (x0 + s * dx), y - (y0 + s * dy)), s

    def _nearest(self, lo: int, hi: int, x: float, y: float) -> tuple[int, float, float]:
        best = (lo, math.inf, 0.0)
        for i in range(lo, hi):
            d, s = self._project(i, x, y)
            if d <= best[1] + 1e-9:  # ties go to the later segment (vertex -> next leg)
                best = (i, d, s)
        return best

    def _seg_course(self, i: int) -> float:
        # degenerate segments borrow the course of the nearest real one
        for j in list(range(i, self._nseg)) + list(range(i - 1, -1, -1)):
            _, _, dx, dy = self._seg(j)
            if dx * dx + dy * dy > _EPS:
                return _wrap360(math.degrees(math.atan2(dx, dy)))
        return 0.0

    def follow(
        self,
        t_now: float,
        lat: float,
        lon: float,
        cog_deg: float | None = None,
        twd_deg: float | None = None,
    ) -> Follow:
        x, y = to_xy(lat, lon, self._lat0, self._lon0)
        lo = self._idx
        i, d, s = self._nearest(lo, min(self._nseg, lo + SEARCH_AHEAD), x, y)
        if d > GLOBAL_SEARCH_NM and lo + SEARCH_AHEAD < self._nseg:
            i2, d2, s2 = self._nearest(lo, self._nseg, x, y)
            if d2 < d:
                i, d, s = i2, d2, s2
        self._idx = i
        t0 = self._t[i]
        t1 = self._t[i + 1] if i + 1 < len(self._t) else t0
        t_here = t0 + s * (t1 - t0)
        seg_course = self._seg_course(i)
        course_dev = None if cog_deg is None else abs(_wrap180(cog_deg - seg_course))
        p = self.path[i]
        target_twa = float(p[3])
        target_tack = int(p[4])
        target_hdg = None if twd_deg is None else target_heading(twd_deg, target_twa)

        upcoming = next((k for k in self.tacks if float(k[0]) > t_here), None)
        next_tack, countdown = self._advised(t_now, t_here, upcoming, cog_deg, twd_deg)

        remaining = self._t[-1] - t_here
        finished = i >= self._nseg - 1 and (s >= 1.0 - 1e-9 or len(self.path) == 1)
        return Follow(
            idx=i,
            t_route_here=t_here,
            xte_nm=d,
            seg_course_deg=seg_course,
            course_dev_deg=course_dev,
            target_twa=target_twa,
            target_tack=target_tack,
            target_hdg_t=target_hdg,
            next_tack=next_tack,
            countdown_s=countdown,
            eta_now=t_now + remaining,
            remaining_s=remaining,
            finished=finished,
        )

    def _advised(
        self,
        t_now: float,
        t_here: float,
        upcoming: Any | None,
        cog_deg: float | None,
        twd_deg: float | None,
    ) -> tuple[Any | None, float | None]:
        adv = self._adv
        if adv is not None and adv is not upcoming and float(adv[0]) <= t_here:
            # the route has passed the advised tack: did the boat follow it?
            side = None
            if cog_deg is not None and twd_deg is not None:
                twa_now = _wrap180(twd_deg - cog_deg)  # twd = hdg + twa
                if 15.0 <= abs(twa_now) <= 165.0:
                    side = 1 if twa_now > 0 else -1
            if side is not None and side == int(adv[3]) and self._adv_wall is not None:
                self._adv_overdue = True
                return adv, self._adv_wall - t_now  # still on the old tack: overdue
        self._adv_overdue = False
        self._adv = upcoming
        if upcoming is None:
            self._adv_wall = None
            return None, None
        countdown = float(upcoming[0]) - t_here
        self._adv_wall = t_now + countdown
        return upcoming, countdown


# --------------------------------------------------------------------------------------------
# Missed tack
# --------------------------------------------------------------------------------------------


class MissedTackWatch:
    """True once per advised tack when it is more than ``late_s`` overdue and no tack was
    detected since ``pre_s`` before it (RESEARCH Pattern 11)."""

    def __init__(self, late_s: float = 120.0, pre_s: float = 60.0):
        self.late_s = late_s
        self.pre_s = pre_s
        self._fired: int | None = None

    def update(self, t_now: float, countdown_s: float | None, last_tack_t: float | None) -> bool:
        if countdown_s is None or countdown_s >= -self.late_s:
            return False
        advised = t_now + countdown_s
        if last_tack_t is not None and last_tack_t >= advised - self.pre_s:
            return False
        key = round(advised)
        if key == self._fired:
            return False
        self._fired = key
        return True


def cost_text(cost_s: float | None) -> str | None:
    """Cost of not tacking for the helm: None, "< 1 min" (also for negative noise, Pitfall 9),
    or "+N min"."""
    if cost_s is None:
        return None
    if cost_s < 60.0:
        return "< 1 min"
    return f"+{round(cost_s / 60.0)} min"
