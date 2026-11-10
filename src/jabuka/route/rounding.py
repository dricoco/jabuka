"""Rounding waypoints: pass each mark on its required side, on a circle of the mark's radius at
sea (RESEARCH Pattern 6, CONTEXT §Land mask "marks placed on land").

For mark M with previous P (previous mark; the boat only for the very first mark when no
previous mark is known) and next N: b_in = bearing(P -> M), b_out = bearing(M -> N), bearings
from the mark measured in the local frame.

- Starboard (mark on the boat's right, clockwise around it): from a1 = b_in - 90 sweeping
  clockwise to a2 = b_out - 90. Port: from a1 = b_in + 90 counter-clockwise to a2 = b_out + 90.
- One waypoint per <= 90 deg of sweep (start point included): Course A Plić Sestre (161 -> 203
  deg) gives 071 -> 113 (42 deg, two waypoints); the Jabuka hairpin (203 -> 009) sweeps 166 deg
  with three.
- When the course bends AWAY from the required side (e.g. Course B passes Plić Sestre to port
  while turning 42 deg to starboard) the formula would ask for a 318 deg loop. The rounding rule
  ("string" drawn taut along the track passes the mark on the required side) only needs the boat
  abeam on the right side: a waypoint at a1, preceded by an entry waypoint 45 deg earlier in the
  rounding direction so the abeam point cannot be reached by going round the mark the wrong way.
- The previous MARK (not the boat) fixes b_in, so the waypoints do not move between reruns.
  Waypoints of the first mark already passed (boat inside the zone and past them in sweep order)
  are dropped; when all are passed the mark is skipped.
- Side "none": one waypoint at the mark itself ("mark"). The last mark of the course ("finish"):
  the mark itself when its side is "none" and its centre is clear water (Vodice); otherwise
  (rounding side, or centre on land such as the Blitvenica islet) one waypoint on its radius
  circle on the approach side (towards the previous mark, the boat when there is none), pushed
  outward like the rounding waypoints (the centre when no clear point is found on that bearing:
  the router then snaps it to clear water or fails with "cible dans la terre").
- A waypoint inside the land mask is pushed radially outward in 0.02 nm steps (up to 0.5 nm) with
  a note; otherwise ValueError with a French reason naming the mark.
"""

from __future__ import annotations

import math

from jabuka.route.frame import DEFAULT_FRAME, Frame
from jabuka.route.landmask import LandMask
from jabuka.route.types import CourseMark, Waypoint

MAX_SWEEP_STEP_DEG = 90.0
PUSH_STEP_NM = 0.02
PUSH_MAX_NM = 0.5
ZONE_FACTOR = 3.0  # "inside the zone": within 3 x radius (at least radius + 0.5 nm)
LEAVE_ARC_DEG = 60.0  # bearings past the last waypoint still count as "rounding" (leaving)
PASS_BY_ENTRY_DEG = 45.0  # pass-by marks: entry waypoint this far before the abeam point


def _bearing(frame: Frame, a: tuple[float, float], b: tuple[float, float]) -> float | None:
    ax, ay = frame.to_xy(*a)
    bx, by = frame.to_xy(*b)
    if math.hypot(bx - ax, by - ay) < 1e-9:
        return None
    return math.degrees(math.atan2(bx - ax, by - ay)) % 360.0


def _at(frame: Frame, mark: CourseMark, bearing_deg: float, r_nm: float) -> tuple[float, float]:
    mx, my = frame.to_xy(mark.lat, mark.lon)
    a = math.radians(bearing_deg)
    lat, lon = frame.to_ll(mx + r_nm * math.sin(a), my + r_nm * math.cos(a))
    return float(lat), float(lon)


def _clear(mask: LandMask | None, frame: Frame, lat: float, lon: float) -> bool:
    if mask is None:
        return True
    x, y = frame.to_xy(lat, lon)
    return bool(mask.points_clear(x, y)[0])


def _arc(prev_pos, mark: CourseMark, next_pos, frame: Frame) -> tuple[float, float, int] | None:
    """(a1, sweep, direction) for a rounding mark; direction +1 clockwise (starboard), -1
    counter-clockwise (port). None when the mark is a plain point."""
    if mark.side not in ("port", "stbd") or next_pos is None:
        return None
    m = (mark.lat, mark.lon)
    b_out = _bearing(frame, m, next_pos)
    b_in = _bearing(frame, prev_pos, m) if prev_pos is not None else None
    if b_out is None and b_in is None:
        return None
    b_in = b_out if b_in is None else b_in
    b_out = b_in if b_out is None else b_out
    if mark.side == "stbd":
        a1, a2, direction = (b_in - 90.0) % 360.0, (b_out - 90.0) % 360.0, 1
        sweep = (a2 - a1) % 360.0
    else:
        a1, a2, direction = (b_in + 90.0) % 360.0, (b_out + 90.0) % 360.0, -1
        sweep = (a1 - a2) % 360.0
    if sweep > 180.0:  # the course bends away from the mark: pass abeam, no loop
        sweep = 0.0
    return a1, sweep, direction


def _push(mask, frame, mark: CourseMark, bearing: float, notes: list[str] | None):
    lat, lon = _at(frame, mark, bearing, mark.radius_nm)
    if _clear(mask, frame, lat, lon):
        return lat, lon
    r = mark.radius_nm
    while r < mark.radius_nm + PUSH_MAX_NM - 1e-9:
        r += PUSH_STEP_NM
        lat, lon = _at(frame, mark, bearing, r)
        if _clear(mask, frame, lat, lon):
            if notes is not None:
                notes.append(
                    f"point de contournement de {mark.name} repoussé à {r:.2f} nm "
                    f"(relèvement {bearing:.0f}°)"
                )
            return lat, lon
    raise ValueError(
        f"impossible de contourner {mark.name} : aucun point en eau libre à moins de "
        f"{mark.radius_nm + PUSH_MAX_NM:.2f} nm au relèvement {bearing:.0f}°"
    )


def expand(
    prev: CourseMark | None,
    marks: tuple[CourseMark, ...] | list[CourseMark],
    boat_lat: float,
    boat_lon: float,
    mask: LandMask | None = None,
    notes: list[str] | None = None,
) -> list[Waypoint]:
    """Waypoints for the remaining ``marks`` (next first). ValueError (French) when a rounding
    waypoint cannot be placed at sea."""
    frame = mask.frame if mask is not None else DEFAULT_FRAME
    out: list[Waypoint] = []
    n = len(marks)
    for i, m in enumerate(marks):
        if i == 0:
            p = prev if prev is not None else None
            prev_pos = (p.lat, p.lon) if p is not None else (boat_lat, boat_lon)
        else:
            prev_pos = (marks[i - 1].lat, marks[i - 1].lon)
        next_pos = (marks[i + 1].lat, marks[i + 1].lon) if i + 1 < n else None
        arc = _arc(prev_pos, m, next_pos, frame)
        if arc is None:
            if i == n - 1 and (m.side in ("port", "stbd") or not _clear(mask, frame, m.lat, m.lon)):
                bearing = _bearing(frame, (m.lat, m.lon), prev_pos)
                if bearing is None:
                    bearing = _bearing(frame, (m.lat, m.lon), (boat_lat, boat_lon))
                if bearing is None:
                    bearing = 0.0
                try:
                    lat, lon = _push(mask, frame, m, bearing, notes)
                except ValueError:  # no water on that bearing: the centre, snapped by the router
                    lat, lon = m.lat, m.lon
                out.append(Waypoint(lat, lon, m.mark_id, "finish", i))
                continue
            out.append(Waypoint(m.lat, m.lon, m.mark_id, "finish" if i == n - 1 else "mark", i))
            continue
        a1, sweep, direction = arc
        k = max(1, math.ceil(sweep / MAX_SWEEP_STEP_DEG - 1e-9)) if sweep > 0 else 0
        offsets = [sweep * j / k for j in range(k + 1)] if k else [-PASS_BY_ENTRY_DEG, 0.0]
        if i == 0:
            offsets = _not_passed(frame, m, a1, sweep, direction, offsets, boat_lat, boat_lon)
            if not offsets and notes is not None:
                notes.append(f"marque {m.name} déjà contournée")
        for s in offsets:
            bearing = (a1 + direction * s) % 360.0
            lat, lon = _push(mask, frame, m, bearing, notes)
            out.append(Waypoint(lat, lon, m.mark_id, "rounding", i))
    return out


def _not_passed(frame, m: CourseMark, a1, sweep, direction, offsets, boat_lat, boat_lon):
    """Drop the waypoints the boat is already past (inside the zone, in sweep order)."""
    mx, my = frame.to_xy(m.lat, m.lon)
    bx, by = frame.to_xy(boat_lat, boat_lon)
    dist = math.hypot(bx - mx, by - my)
    if dist > max(ZONE_FACTOR * m.radius_nm, m.radius_nm + 0.5) or dist < 1e-9:
        return offsets
    bb = math.degrees(math.atan2(bx - mx, by - my)) % 360.0
    s_boat = ((bb - a1) * direction + 180.0) % 360.0 - 180.0  # (-180, 180] along the sweep
    if s_boat > sweep + LEAVE_ARC_DEG or s_boat < offsets[0]:
        return offsets  # approaching: nothing passed yet
    return [s for s in offsets if s > s_boat]
