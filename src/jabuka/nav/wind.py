"""True-wind pipeline (WIND-03/04/07): every direction becomes TRUE at one boundary, here.

heading_true() is the single magnetic->true conversion of instrument headings and directions
(Pitfall 16, A9: a reference that is unknown is treated as magnetic by setting). WindPipeline
turns the latest instrument values into a WindSolution once per tick (RESEARCH Pattern 2):

1. Jabuka zone (WIND-07, Pitfall 7): within zone_radius_nm of (zone_lat, zone_lon) the compass is
   untrusted. The heading becomes GPS COG (only when SOG > 1 kn), and the Hercules direction (and
   set, see current_true) are ignored: they are compass-derived too.
2. Sources, in order:
   - LIVE: true wind computed from AWA/AWS/BSP and a trusted heading. Leeway rotates the water
     track to leeward first. This is the default (true_wind_source "computed").
   - LIVE_BG: the Hercules true wind (direction, else heading + angleTrueWater) when the computed
     inputs are missing or true_wind_source is "instrument".
   - MANUEL: the stored manual entry, sticky until cleared.
   - GRIB (WIND-05, Phase 3): with the bus silent and grib_wind_fallback on, the race-pack GRIB
     at the boat position and GPS time (bias-corrected, from the provider set by the core). The
     heading is GPS COG (SOG > 1 kn, else none: no TWA and no laylines) and SOG stands in for BSP.
   - NONE.
3. Cross-check: when both the computed and the Hercules values are fresh, dTWA/dTWS are published,
   with an alert after 60 s continuously above 10 deg.
4. Damping: vector EMAs on (TWS sin TWD, TWS cos TWD) with tau_helm_s (twd, helm) and
   tau_layline_s (twd_lay, laylines). TWS uses a scalar EMA with tau_helm_s. The filters reset
   whenever the source changes. TWA is reported to the bow: wrap(twd_helm - current heading).

Inputs are StateStore.latest() rows keyed by path ({value, unit, src, ref, ...} or None); stale
rows are already None (wind/heading 5 s). Radians and m/s throughout; time from the injected
monotonic clock (t_mono) and the injected wall clock (t_wall, manual age only).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from jabuka.common.conventions import apply_heading_offset, mag_to_true, true_wind_from_apparent
from jabuka.common.units import kn_to_ms, ms_to_kn, wrap_2pi, wrap_pi
from jabuka.nav import geo
from jabuka.nav.settings import ManualWind, Settings

AWA = "environment.wind.angleApparent"
AWS = "environment.wind.speedApparent"
TWA_INSTR = "environment.wind.angleTrueWater"
TWS_INSTR = "environment.wind.speedTrue"
TWD_INSTR = "environment.wind.direction"
HEADING = "navigation.heading"
BSP = "navigation.speedThroughWater"
POSITION = "navigation.position"
COG = "navigation.courseOverGroundTrue"
SOG = "navigation.speedOverGround"
CURRENT_SET = "environment.current.set"
CURRENT_DRIFT = "environment.current.drift"

INPUT_PATHS = (
    AWA,
    AWS,
    TWA_INSTR,
    TWS_INSTR,
    TWD_INSTR,
    HEADING,
    BSP,
    POSITION,
    COG,
    SOG,
    CURRENT_SET,
    CURRENT_DRIFT,
)

COG_MIN_SOG_KN = 1.0  # below this, COG is noise: no heading from it
CHECK_DTWA_DEG = 10.0
CHECK_HOLD_S = 60.0
MIN_WEIGHT_MS = 1e-3  # vector weight floor so a 0 kn manual entry keeps its direction

ALERT_ZONE = "CAP NON FIABLE (zone Jabuka)"
ALERT_CHECK = "Écart TWA calculé/B&G > 10°"
ALERT_GRIB = "VENT GRIB (pas d'instruments)"

# (lat, lon) deg -> (TWD FROM rad TRUE, TWS m/s) of the race-pack GRIB, or None (not covered)
GribProvider = Callable[[float, float], tuple[float, float] | None]

Inputs = Mapping[str, Mapping[str, Any] | None]


def num(row: Mapping[str, Any] | None) -> float | None:
    """Finite float value of a latest() row, else None."""
    if row is None:
        return None
    v = row.get("value")
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def position(inputs: Inputs) -> tuple[float, float] | None:
    row = inputs.get(POSITION)
    v = row.get("value") if row is not None else None
    if not isinstance(v, Mapping):
        return None
    lat, lon = num({"value": v.get("latitude")}), num({"value": v.get("longitude")})
    if lat is None or lon is None:
        return None
    return lat, lon


def heading_true(value: float, ref: str | None, settings: Settings) -> float:
    """Instrument heading or compass-derived direction (rad) -> TRUE (rad). The calibration
    offset applies to the sensor reading; then magnetic values (ref "M", or unknown ref with
    heading_ref_unknown "M") get the variation (East-positive)."""
    h = apply_heading_offset(value, math.radians(settings.heading_offset_deg))
    is_mag = ref == "M" or (ref != "T" and settings.heading_ref_unknown == "M")
    if is_mag:
        h = mag_to_true(h, math.radians(settings.variation_deg))
    return h


def current_true(inputs: Inputs, settings: Settings) -> tuple[float, float] | None:
    """Hercules set (TOWARDS, TRUE rad) and drift (m/s) when both are fresh, else None. The set
    goes through the same TRUE boundary as the heading (it is compass-derived)."""
    row = inputs.get(CURRENT_SET)
    s, d = num(row), num(inputs.get(CURRENT_DRIFT))
    if s is None or d is None or d < 0.0:
        return None
    return heading_true(s, row.get("ref") if row else None, settings), d


class VectorEma:
    """Time-based EMA of a direction weighted by a speed, on the (sin, cos) vector: no 359/1 deg
    wrap glitch. alpha = 1 - exp(-dt/tau). A clock going backwards resets the filter; the same
    instant twice is a no-op."""

    def __init__(self, tau_s: float) -> None:
        self.tau = tau_s
        self.x: float | None = None
        self.y: float | None = None
        self.t: float | None = None

    def reset(self) -> None:
        self.x = self.y = self.t = None

    def update(self, direction: float, weight: float, t: float) -> float:
        sx, sy = weight * math.sin(direction), weight * math.cos(direction)
        if self.x is None or self.y is None or self.t is None or t < self.t:
            self.x, self.y = sx, sy
        elif t > self.t:
            a = 1.0 - math.exp(-(t - self.t) / max(self.tau, 1e-6))
            self.x += a * (sx - self.x)
            self.y += a * (sy - self.y)
        self.t = t
        return wrap_2pi(math.atan2(self.x, self.y))


class ScalarEma:
    """Time-based EMA of a scalar (same reset rules as VectorEma)."""

    def __init__(self, tau_s: float) -> None:
        self.tau = tau_s
        self.v: float | None = None
        self.t: float | None = None

    def reset(self) -> None:
        self.v = self.t = None

    def update(self, value: float, t: float) -> float:
        if self.v is None or self.t is None or t < self.t:
            self.v = value
        elif t > self.t:
            a = 1.0 - math.exp(-(t - self.t) / max(self.tau, 1e-6))
            self.v += a * (value - self.v)
        self.t = t
        return self.v


@dataclass
class WindSolution:
    source: str = "NONE"  # LIVE | LIVE_BG | MANUEL | GRIB | NONE
    stale: bool = False
    twd: float | None = None  # rad TRUE, FROM (helm-damped)
    twd_lay: float | None = None  # rad TRUE, FROM (layline-damped)
    tws: float | None = None  # m/s (helm-damped)
    twa: float | None = None  # rad signed to the bow, negative = port
    hdg: float | None = None  # rad TRUE: the heading used (compass, or COG)
    heading_src: str | None = None  # compass | cog | None
    heading_trusted: bool = True
    in_zone: bool = False
    manual_age_s: float | None = None
    check: dict | None = None  # {"dtwa": deg, "dtws_kn": kn, "alert": bool} (display units)
    alerts: list[str] = field(default_factory=list)  # helm alert strings raised by the pipeline

    @property
    def ok(self) -> bool:
        return self.twd is not None and self.tws is not None


class WindPipeline:
    def __init__(self, settings: Settings, grib: GribProvider | None = None) -> None:
        self.settings = settings
        self.grib = grib  # set by the core when a race pack is loaded (NavService)
        self.last: WindSolution = WindSolution()
        self._ema_helm = VectorEma(settings.tau_helm_s)
        self._ema_lay = VectorEma(settings.tau_layline_s)
        self._ema_tws = ScalarEma(settings.tau_helm_s)
        self._source: tuple[str, str | None] | None = None
        self._check_since: float | None = None

    # -- heading -----------------------------------------------------------------------------
    def heading(self, inputs: Inputs) -> float | None:
        """Compass heading, TRUE (rad), or None."""
        row = inputs.get(HEADING)
        v = num(row)
        if v is None:
            return None
        return heading_true(v, row.get("ref") if row else None, self.settings)

    def in_zone(self, inputs: Inputs) -> bool:
        s = self.settings
        pos = position(inputs)
        if pos is None or s.zone_radius_nm <= 0.0:
            return False
        _, dist = geo.bearing_distance(pos[0], pos[1], s.zone_lat, s.zone_lon)
        return dist < s.zone_radius_nm

    # -- one tick ----------------------------------------------------------------------------
    def update(
        self,
        inputs: Inputs,
        t_mono: float,
        manual: ManualWind | None = None,
        t_wall: float | None = None,
    ) -> WindSolution:
        s = self.settings
        self._ema_helm.tau = s.tau_helm_s
        self._ema_lay.tau = s.tau_layline_s
        self._ema_tws.tau = s.tau_helm_s

        # 1. heading: compass, or COG inside the Jabuka zone
        zone = self.in_zone(inputs)
        cog = num(inputs.get(COG))
        sog = num(inputs.get(SOG))
        cog_ok = cog is not None and sog is not None and ms_to_kn(sog) > COG_MIN_SOG_KN
        sol = WindSolution(in_zone=zone, heading_trusted=not zone)
        if zone:
            hdg = cog if cog_ok else None
            hdg_src = "cog" if cog_ok else None
            sol.alerts.append(ALERT_ZONE)
        else:
            hdg = self.heading(inputs)
            hdg_src = "compass" if hdg is not None else None

        # 2a. computed true wind (leeway: water track rotated to leeward)
        awa, aws, bsp = num(inputs.get(AWA)), num(inputs.get(AWS)), num(inputs.get(BSP))
        comp = None  # (twd, tws, twa to the bow)
        if awa is not None and aws is not None and bsp is not None and hdg is not None:
            sign = 1.0 if awa >= 0.0 else -1.0
            lam = math.radians(s.leeway_deg) * sign
            tw = true_wind_from_apparent(awa + lam, aws, bsp, wrap_2pi(hdg - lam))
            comp = (tw.twd, tw.tws, wrap_pi(tw.twd - hdg))

        # 2b. Hercules true wind (its direction is compass-derived: ignored in the zone)
        twa_i, tws_i = num(inputs.get(TWA_INSTR)), num(inputs.get(TWS_INSTR))
        dir_row = inputs.get(TWD_INSTR)
        dir_i = None if zone else num(dir_row)
        twd_i = None
        if dir_i is not None:
            twd_i = heading_true(dir_i, dir_row.get("ref") if dir_row else None, s)
        elif twa_i is not None and hdg is not None:
            twd_i = wrap_2pi(hdg + twa_i)
        instr = (twd_i, tws_i) if twd_i is not None and tws_i is not None else None

        # 3. cross-check
        self._cross_check(sol, comp, twa_i, tws_i, t_mono)

        # 4. arbitration
        raw = None
        if comp is not None and (s.true_wind_source == "computed" or instr is None):
            sol.source, raw = "LIVE", (comp[0], comp[1])
        elif instr is not None:
            sol.source, raw = "LIVE_BG", instr
        elif manual is not None:
            sol.source = "MANUEL"
            raw = (wrap_2pi(math.radians(manual.twd_t_deg)), kn_to_ms(manual.tws_kn))
            self._manual_age(sol, manual, t_wall)
        else:
            raw = self._grib(sol, inputs)
            if raw is not None:
                # GPS + GRIB: the heading is COG (only above 1 kn), never the compass alone
                hdg, hdg_src = (cog, "cog") if cog_ok else (None, None)
                sol.heading_trusted = cog_ok and not zone

        # heading for the TWA: the trusted one, else COG as a best effort (MANUEL, LIVE_BG)
        if hdg is None and cog_ok:
            hdg, hdg_src = cog, "cog"
        sol.hdg, sol.heading_src = hdg, hdg_src

        # 5. damping (filters reset on a source change, or a new manual entry: applies at once)
        key = (sol.source, manual.model_dump_json() if sol.source == "MANUEL" and manual else None)
        if key != self._source:
            self._ema_helm.reset()
            self._ema_lay.reset()
            self._ema_tws.reset()
            self._source = key
        if raw is not None:
            twd_raw, tws_raw = raw
            w = max(tws_raw, MIN_WEIGHT_MS)
            sol.twd = self._ema_helm.update(twd_raw, w, t_mono)
            sol.twd_lay = self._ema_lay.update(twd_raw, w, t_mono)
            sol.tws = self._ema_tws.update(tws_raw, t_mono)
            if hdg is not None:
                sol.twa = wrap_pi(sol.twd - hdg)
            elif sol.source == "LIVE_BG" and twa_i is not None:
                sol.twa = wrap_pi(twa_i)
            elif sol.source == "GRIB":
                sol.twd_lay = None  # no heading: no laylines (Phase 2 NONE handling)
        self.last = sol
        return sol

    def _grib(self, sol: WindSolution, inputs: Inputs) -> tuple[float, float] | None:
        """GRIB wind at the boat (source GRIB + alert), or None when off / not covered."""
        if not self.settings.grib_wind_fallback or self.grib is None:
            return None
        pos = position(inputs)
        if pos is None:
            return None
        try:
            g = self.grib(pos[0], pos[1])
        except Exception:  # noqa: BLE001 - a GRIB problem means no GRIB wind, never a crash
            return None
        if g is None or not all(math.isfinite(x) for x in g):
            return None
        sol.source = "GRIB"
        sol.alerts.append(ALERT_GRIB)
        return wrap_2pi(g[0]), max(0.0, g[1])

    def _cross_check(
        self,
        sol: WindSolution,
        comp: tuple[float, float, float] | None,
        twa_i: float | None,
        tws_i: float | None,
        t: float,
    ) -> None:
        if comp is None or twa_i is None or tws_i is None:
            self._check_since = None
            return
        dtwa = math.degrees(wrap_pi(comp[2] - twa_i))
        dtws = ms_to_kn(comp[1] - tws_i)
        if abs(dtwa) > CHECK_DTWA_DEG:
            if self._check_since is None or t < self._check_since:
                self._check_since = t
        else:
            self._check_since = None
        alert = self._check_since is not None and t - self._check_since > CHECK_HOLD_S
        sol.check = {"dtwa": round(dtwa, 1), "dtws_kn": round(dtws, 1), "alert": alert}
        if alert:
            sol.alerts.append(ALERT_CHECK)

    def _manual_age(self, sol: WindSolution, manual: ManualWind, t_wall: float | None) -> None:
        if t_wall is None:
            return
        age = max(0.0, t_wall - manual.t_set_wall)
        sol.manual_age_s = age
        limit_min = self.settings.manual_wind_max_age_min
        if age > limit_min * 60.0:
            sol.stale = True
            sol.alerts.append(f"Vent manuel ancien (> {limit_min:g} min)")
