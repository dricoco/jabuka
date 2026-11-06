"""True-wind pipeline (WIND-03): every direction becomes TRUE at one boundary, here.

heading_true() is the single magnetic->true conversion of instrument headings (Pitfall 16, A9: a
heading whose reference is unknown is treated as magnetic by setting). WindPipeline turns the
latest instrument values into a WindSolution once per tick.

This file holds the computed-live-wind path: true wind from AWA/AWS/BSP/heading when all four are
fresh (source LIVE), else NONE. Plan 02-03 adds, inside this module, the instrument and manual
sources, the stale state, the two damping filters (twd_lay_t then differs from twd_t), the Jabuka
zone and the cross-check.

Inputs are StateStore.latest() rows keyed by path ({value, unit, src, ref, ...} or None).
Radians and m/s throughout.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from jabuka.common.conventions import apply_heading_offset, mag_to_true, true_wind_from_apparent
from jabuka.common.units import kn_to_ms, wrap_2pi, wrap_pi
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


def heading_true(value: float, ref: str | None, settings: Settings) -> float:
    """Instrument heading (rad) -> TRUE heading (rad). The calibration offset applies to the sensor
    reading; then magnetic headings (ref "M", or unknown ref with heading_ref_unknown "M") get the
    variation (East-positive)."""
    h = apply_heading_offset(value, math.radians(settings.heading_offset_deg))
    is_mag = ref == "M" or (ref != "T" and settings.heading_ref_unknown == "M")
    if is_mag:
        h = mag_to_true(h, math.radians(settings.variation_deg))
    return h


@dataclass
class WindSolution:
    source: str = "NONE"  # LIVE | LIVE_BG | MANUEL | NONE
    stale: bool = False
    twd: float | None = None  # rad TRUE, FROM (helm)
    twd_lay: float | None = None  # rad TRUE, FROM (laylines; damped harder by plan 02-03)
    tws: float | None = None  # m/s
    twa: float | None = None  # rad signed, negative = port
    hdg: float | None = None  # rad TRUE (heading used for the true wind)
    heading_trusted: bool = True
    in_zone: bool = False
    manual_age_s: float | None = None
    check: dict | None = None
    alerts: list[str] = field(default_factory=list)  # helm alert strings raised by the pipeline

    @property
    def ok(self) -> bool:
        return self.twd is not None and self.tws is not None


class WindPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last: WindSolution = WindSolution()

    def heading(self, inputs: Inputs) -> float | None:
        row = inputs.get(HEADING)
        v = num(row)
        if v is None:
            return None
        return heading_true(v, row.get("ref") if row else None, self.settings)

    def update(
        self,
        inputs: Inputs,
        t_mono: float,
        manual: ManualWind | None = None,
        t_wall: float | None = None,
    ) -> WindSolution:
        """One tick. Arbitration: LIVE (computed true wind, AWA/AWS/BSP/heading all fresh) >
        MANUEL (the stored manual entry, sticky until cleared) > NONE.
        t_wall: injected wall clock, for the age of the manual entry."""
        awa, aws, bsp = num(inputs.get(AWA)), num(inputs.get(AWS)), num(inputs.get(BSP))
        hdg = self.heading(inputs)
        sol = WindSolution(hdg=hdg)
        if None not in (awa, aws, bsp, hdg):
            tw = true_wind_from_apparent(awa, aws, bsp, hdg)
            sol.source = "LIVE"
            sol.twd = sol.twd_lay = tw.twd
            sol.tws = tw.tws
            sol.twa = tw.twa
        elif manual is not None:
            sol.source = "MANUEL"
            sol.twd = sol.twd_lay = wrap_2pi(math.radians(manual.twd_t_deg))
            sol.tws = kn_to_ms(manual.tws_kn)
            if hdg is not None:
                sol.twa = wrap_pi(sol.twd - hdg)
            self._manual_age(sol, manual, t_wall)
        self.last = sol
        return sol

    def _manual_age(self, sol: WindSolution, manual: ManualWind, t_wall: float | None) -> None:
        if t_wall is None:
            return
        age = max(0.0, t_wall - manual.t_set_wall)
        sol.manual_age_s = age
        limit_min = self.settings.manual_wind_max_age_min
        if age > limit_min * 60.0:
            sol.stale = True
            sol.alerts.append(f"Vent manuel ancien (> {limit_min:g} min)")
