"""Laylines by vector decomposition (NAV-01/02, RESEARCH Pattern 4) and the helm primary number
(HELM-02, CONTEXT D-6).

Local flat frame centred on the anchor A (the point at the rounding radius on the rounding side of
the mark, Pitfall 17), x east / y north in nm, velocities in kn (nm/h):

- leg type from beta = |wrap_pi(bearing boat->A - TWD)|: beat if beta < up TWA, run if
  beta > down TWA, else reach (+-5 deg hysteresis on the previous leg type);
- tack headings h_stbd = TWD - TWA, h_port = TWD + TWA (TWA positive = starboard);
- ground vectors g = target BSP * u(h) (+ current when NAV-03 is on, outside the Jabuka zone), or
  in sailed mode the measured ground track TWD + theta at the measured SOG (no current: theta is
  ground-referenced already, Pitfall 8), with the polar as the per-side fallback;
- D = A - P = a * g_current_tack + b * g_other_tack: a = hours before tacking, b = hours after.
  a > 0 and b > 0: normal; a <= 0: overstood (overstood_s = -a); b <= 0: fetching on this tack
  (helm.cts_t = heading whose ground track points at A).
- countdown: along the boat's actual track, the ray P + s*u(COG) meeting the other-tack layline
  through A, time s / SOG (SOG > 1 kn); else the polar a.

Reach legs have no laylines: the primary number is the course to steer (to A, current-corrected).
Inputs in radians/knots; the result dicts are already in display units (degrees TRUE, kn, nm, s).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jabuka.common.units import wrap_2pi, wrap_pi
from jabuka.nav import geo
from jabuka.nav.polar import Targets
from jabuka.nav.wind import WindSolution

UP_LIMIT_DEG = 70.0
DOWN_LIMIT_DEG = 110.0
HYSTERESIS_DEG = 5.0
LEG_HYSTERESIS_DEG = 5.0
MIN_LINE_NM = 2.0
SOG_MIN_KN = 0.5
TRACK_SOG_MIN_KN = 1.0  # below this the COG is noise: countdown from the polar decomposition


@dataclass
class BoatState:
    lat: float
    lon: float
    hdg: float | None = None  # rad TRUE
    cog: float | None = None  # rad TRUE
    sog_kn: float | None = None
    bsp_kn: float | None = None


@dataclass
class Anchor:
    lat: float
    lon: float


@dataclass
class LaylineResult:
    leg: str | None = None  # beat | run | reach
    dtw_nm: float | None = None
    btw: float | None = None  # rad TRUE, boat -> anchor
    ttw_s: float | None = None
    layline: dict | None = None
    helm: dict = field(
        default_factory=lambda: {"primary": None, "target": None, "deviation": None, "cts_t": None}
    )
    target_bsp_kn: float | None = None


def _r(x: float | None, nd: int) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, nd)


def _deg360(rad: float) -> float:
    d = math.degrees(rad) % 360.0
    return 0.0 if d >= 359.95 else d


def select_primary(prev: str | None, twa_abs_deg: float) -> str:
    """D-6 primary number from the boat's |TWA|: < 70 target TWA upwind, > 110 target TWA
    downwind, else course to steer; +-5 deg hysteresis around the mode already shown."""
    a = abs(twa_abs_deg)
    if prev == "twa_up" and a < UP_LIMIT_DEG + HYSTERESIS_DEG:
        return "twa_up"
    if prev == "twa_down" and a > DOWN_LIMIT_DEG - HYSTERESIS_DEG:
        return "twa_down"
    if prev == "cts":
        if a < UP_LIMIT_DEG - HYSTERESIS_DEG:
            return "twa_up"
        if a > DOWN_LIMIT_DEG + HYSTERESIS_DEG:
            return "twa_down"
        return "cts"
    if a < UP_LIMIT_DEG:
        return "twa_up"
    if a > DOWN_LIMIT_DEG:
        return "twa_down"
    return "cts"


def leg_type(beta_deg: float, up_twa: float, down_twa: float, prev: str | None = None) -> str:
    h = LEG_HYSTERESIS_DEG
    if prev == "beat" and beta_deg < up_twa + h:
        return "beat"
    if prev == "run" and beta_deg > down_twa - h:
        return "run"
    if beta_deg < up_twa:
        return "beat"
    if beta_deg > down_twa:
        return "run"
    return "reach"


def decompose(
    d: tuple[float, float], ga: tuple[float, float], gb: tuple[float, float]
) -> tuple[float, float] | None:
    """Solve d = a*ga + b*gb; None when the two vectors are parallel."""
    det = ga[0] * gb[1] - ga[1] * gb[0]
    if abs(det) < 1e-9:
        return None
    a = (d[0] * gb[1] - d[1] * gb[0]) / det
    b = (ga[0] * d[1] - ga[1] * d[0]) / det
    return a, b


def _line(anchor: Anchor, g: tuple[float, float], length_nm: float, tack: str) -> dict:
    n = math.hypot(*g)
    ux, uy = (g[0] / n, g[1] / n) if n > 0 else (0.0, 0.0)
    far_lat, far_lon = geo.from_local(-ux * length_nm, -uy * length_nm, anchor.lat, anchor.lon)
    return {
        "type": "Feature",
        "properties": {"tack": tack},
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [round(far_lon, 6), round(far_lat, 6)],
                [round(anchor.lon, 6), round(anchor.lat, 6)],
            ],
        },
    }


def _steer_deviation(boat: BoatState, cts: float) -> float | None:
    h = boat.hdg if boat.hdg is not None else boat.cog
    return None if h is None else math.degrees(wrap_pi(h - cts))


def course_to_steer(
    btw: float, current_kn: tuple[float, float] | None, speed_kn: float | None
) -> float:
    """Heading (rad TRUE) whose ground track points along btw: the water velocity cancels the
    current's cross-track component (h = btw - asin(c_right / V)). Equals btw without current, or
    when the current is too strong to be cancelled."""
    if current_kn is None or speed_kn is None or speed_kn <= SOG_MIN_KN:
        return btw
    cx, cy = current_kn
    c_right = cx * math.cos(btw) - cy * math.sin(btw)
    c_along = cx * math.sin(btw) + cy * math.cos(btw)
    if abs(c_right) >= speed_kn:
        return btw
    off = math.asin(c_right / speed_kn)
    if speed_kn * math.cos(off) + c_along <= 0.0:
        return btw
    return wrap_2pi(btw - off)


def _cts_helm(boat: BoatState, cts: float) -> dict:
    return {
        "primary": "cts",
        "target": _r(_deg360(cts), 1),
        "deviation": _r(_steer_deviation(boat, cts), 1),
        "cts_t": _r(_deg360(cts), 1),
    }


def _track_to_layline(
    d: tuple[float, float], cog: float, g_other: tuple[float, float]
) -> float | None:
    """Distance (nm) along the ray P + s*u(COG) to the other-tack layline A + t*g_other (t <= 0),
    or None when the track does not meet it ahead. d = A - P."""
    n = math.hypot(*g_other)
    if n <= 0.0:
        return None
    r = decompose(d, geo.unit(cog), (g_other[0] / n, g_other[1] / n))
    if r is None:
        return None
    s_nm, back = r  # d = s*u(COG) + back*g_hat, back = -t >= 0
    return s_nm if s_nm > 0.0 and back >= 0.0 else None


def solve(
    boat: BoatState,
    wind: WindSolution,
    targets_eff: Targets,
    target: Anchor,
    *,
    prev_leg: str | None = None,
    prev_primary: str | None = None,
    reach_bsp_kn: float | None = None,
    current_kn: tuple[float, float] | None = None,
    src: str = "polar",
    sailed: Mapping[str, Mapping[str, Any]] | None = None,
) -> LaylineResult:
    """targets_eff: target angles (deg) and target speeds (kn) WITH the efficiency applied.
    current_kn: (east, north) water motion in kn (Hercules set/drift, only when use_current is on),
    ignored inside the Jabuka zone; added to the polar ground vectors and used for the CTS.
    src "sailed" + sailed (TackTracker.angles()): a side with a sample uses its ground angle
    (TWD + theta) at its mean SOG, never plus the current (Pitfall 8); a side without one uses the
    polar. layline.src is "sailed" only when both sides are sailed."""
    px, py = geo.to_local(boat.lat, boat.lon, target.lat, target.lon)
    d = (-px, -py)
    dtw = math.hypot(*d)
    btw = geo.bearing_of(*d)
    res = LaylineResult(dtw_nm=dtw, btw=btw)
    sog = boat.sog_kn if boat.sog_kn is not None and boat.sog_kn > SOG_MIN_KN else None
    current = current_kn if current_kn is not None and not wind.in_zone else None

    if not wind.ok or wind.twd_lay is None:
        if sog is not None:
            res.ttw_s = dtw / sog * 3600.0
        return res

    twd = wind.twd_lay
    beta = abs(math.degrees(wrap_pi(btw - twd)))
    leg = leg_type(beta, targets_eff.up_twa, targets_eff.down_twa, prev_leg)
    res.leg = leg
    twa_abs = abs(math.degrees(wind.twa)) if wind.twa is not None else None
    bsp = boat.bsp_kn if boat.bsp_kn is not None and boat.bsp_kn > SOG_MIN_KN else None

    if leg == "reach":
        res.helm = _cts_helm(boat, course_to_steer(btw, current, bsp or reach_bsp_kn))
        res.target_bsp_kn = reach_bsp_kn
        speed = max(sog or 0.0, reach_bsp_kn or 0.0)
        res.ttw_s = dtw / speed * 3600.0 if speed > SOG_MIN_KN else None
        return res

    if leg == "beat":
        tack_twa, tack_bsp, leg_key = targets_eff.up_twa, targets_eff.up_bsp, "up"
    else:
        tack_twa, tack_bsp, leg_key = targets_eff.down_twa, targets_eff.down_bsp, "down"
    cx, cy = current if current is not None else (0.0, 0.0)
    samples = ((sailed or {}).get(leg_key) or {}) if src == "sailed" else {}

    def side(name: str, h: float) -> tuple[tuple[float, float], float, bool]:
        """(ground vector kn, heading/track shown for that tack rad, sailed?)"""
        smp = samples.get(name)
        if smp is not None and smp.sog_kn > SOG_MIN_KN:
            trk = wrap_2pi(twd + math.radians(smp.theta_deg))
            return (smp.sog_kn * math.sin(trk), smp.sog_kn * math.cos(trk)), trk, True
        return (tack_bsp * math.sin(h) + cx, tack_bsp * math.cos(h) + cy), h, False

    g_stbd, h_stbd, sailed_stbd = side("stbd", wrap_2pi(twd - math.radians(tack_twa)))
    g_port, h_port, sailed_port = side("port", wrap_2pi(twd + math.radians(tack_twa)))
    on_stbd = wind.twa is None or wind.twa >= 0.0
    tack = "stbd" if on_stbd else "port"
    g_cur, g_other = (g_stbd, g_port) if on_stbd else (g_port, g_stbd)
    h_other = h_port if on_stbd else h_stbd
    current_used = current is not None and not (sailed_stbd and sailed_port)

    primary = (
        select_primary(prev_primary, twa_abs)
        if twa_abs is not None
        else ("twa_up" if leg == "beat" else "twa_down")
    )
    if primary == "cts":
        res.helm = _cts_helm(boat, course_to_steer(btw, current, bsp or reach_bsp_kn))
        res.target_bsp_kn = reach_bsp_kn
    else:
        tgt = targets_eff.up_twa if primary == "twa_up" else targets_eff.down_twa
        res.helm = {
            "primary": primary,
            "target": _r(tgt, 1),
            "deviation": _r(twa_abs - tgt, 1) if twa_abs is not None else None,
            "cts_t": None,
        }
        res.target_bsp_kn = targets_eff.up_bsp if primary == "twa_up" else targets_eff.down_bsp

    ab = (
        decompose(d, g_cur, g_other)
        if math.hypot(*g_cur) > 0 and math.hypot(*g_other) > 0
        else None
    )
    if ab is None:
        if sog is not None:
            res.ttw_s = dtw / sog * 3600.0
        return res
    a, b = ab
    if a <= 0.0:
        state = "overstood"
    elif b <= 0.0:
        state = "fetching"
    else:
        state = "normal"
    countdown_h = dist_nm = None
    if state == "normal":
        time_h = a + b
        countdown_h, dist_nm = a, a * math.hypot(*g_cur)
        # the boat's actual track (CONTEXT: countdown = time to the layline at the current SOG)
        if boat.cog is not None and boat.sog_kn is not None and boat.sog_kn > TRACK_SOG_MIN_KN:
            s_nm = _track_to_layline(d, boat.cog, g_other)
            if s_nm is not None:
                countdown_h, dist_nm = s_nm / boat.sog_kn, s_nm
    else:
        vmc = math.hypot(*g_cur) if sog is None else max(sog, math.hypot(*g_cur))
        time_h = dtw / vmc if vmc > 0 else math.nan
    if state == "fetching":
        res.helm["cts_t"] = _r(_deg360(course_to_steer(btw, current, bsp or tack_bsp)), 1)
    res.ttw_s = time_h * 3600.0
    length = max(1.5 * dtw, MIN_LINE_NM)
    res.layline = {
        "src": "sailed" if sailed_stbd and sailed_port else "polar",
        "tack": tack,
        "state": state,
        "countdown_s": _r(countdown_h * 3600.0, 0) if countdown_h is not None else None,
        "dist_nm": _r(dist_nm, 2) if dist_nm is not None else None,
        "time_s": _r(time_h * 3600.0, 0),
        "overstood_s": _r(-a * 3600.0, 0) if state == "overstood" else None,
        "other_tack_hdg_t": _r(_deg360(h_other), 1),
        "current": current_used,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                _line(target, g_stbd, length, "stbd"),
                _line(target, g_port, length, "port"),
            ],
        },
    }
    return res
