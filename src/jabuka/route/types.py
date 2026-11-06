"""Router contracts: requests, results and the degraded-level ladder (picklable, plain types).

Everything here crosses the process boundary between the core and the routing worker, so it is
made of frozen dataclasses / NamedTuples holding floats, ints, strings and tuples only (plus the
frozen ``BiasParams``). Times are UTC epoch seconds, angles in degrees, speeds in knots.

Conventions (``jabuka.common.conventions``): TWA is signed, negative = port; tack +1 = starboard,
-1 = port, 0 = unknown; heading = TWD - TWA. A path point carries the TWA/tack/BSP sailed from
that point to the next one (03-04 RouteFollower contract).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import NamedTuple

from jabuka.route.bias import BiasParams

INF = math.inf


class CourseMark(NamedTuple):
    mark_id: str
    name: str
    lat: float
    lon: float
    side: str  # "port" | "stbd" | "none"
    radius_nm: float


class Waypoint(NamedTuple):
    lat: float
    lon: float
    mark_id: str
    kind: str  # "rounding" | "mark" | "finish"
    mark_index: int  # index of the mark in RouteRequest.marks


@dataclass(frozen=True)
class RouterSettings:
    hdg_step_deg: float = 5.0
    sector_deg: float = 1.5
    # (elapsed since t0 below which this step applies, step s)
    dt_schedule: tuple[tuple[float, float], ...] = (
        (3600.0, 600.0),
        (10800.0, 900.0),
        (INF, 1800.0),
    )
    fine_dt_s: float = 600.0
    near_land_nm: float = 1.0
    near_target_nm: float = 3.0
    lazy_k: int = 4
    tack_penalty_s: float = 45.0
    max_steps: int = 800
    max_marks_ahead: int | None = None
    use_waves: bool = True
    use_current: bool = True
    wave_k: tuple[float, float, float] = (0.05, 0.03, 0.015)  # per m of Hs: <60, 60-120, >120 deg
    wave_floor: float = 0.70
    stay_extra_s: float = 300.0
    cadence_s: float = 300.0
    forced_every_n: int = 1
    level: str = "L0"

    def dt_for(self, elapsed_s: float) -> float:
        for limit, dt in self.dt_schedule:
            if elapsed_s < limit:
                return float(dt)
        return float(self.dt_schedule[-1][1])

    def problems(self) -> list[str]:
        """French reasons why these settings cannot be used (empty when fine)."""
        out = []
        if not (0.5 <= self.hdg_step_deg <= 30.0):
            out.append(f"pas de cap invalide ({self.hdg_step_deg})")
        if not (0.25 <= self.sector_deg <= 20.0):
            out.append(f"secteur invalide ({self.sector_deg})")
        if not self.dt_schedule or any(
            not (30.0 <= float(dt) <= 7200.0) for _lim, dt in self.dt_schedule
        ):
            out.append("pas de temps invalide")
        if not (30.0 <= self.fine_dt_s <= 3600.0):
            out.append(f"pas fin invalide ({self.fine_dt_s})")
        if not (1 <= self.lazy_k <= 64):
            out.append(f"lazy_k invalide ({self.lazy_k})")
        if not (0.0 <= self.tack_penalty_s <= 600.0):
            out.append(f"pénalité de virement invalide ({self.tack_penalty_s})")
        if not (1 <= self.max_steps <= 20000):
            out.append(f"max_steps invalide ({self.max_steps})")
        if self.max_marks_ahead is not None and self.max_marks_ahead < 1:
            out.append(f"max_marks_ahead invalide ({self.max_marks_ahead})")
        if not (0.0 < self.wave_floor <= 1.0) or any(not (0.0 <= k < 1.0) for k in self.wave_k):
            out.append("facteur vagues invalide")
        for name in ("near_land_nm", "near_target_nm", "stay_extra_s"):
            v = getattr(self, name)
            if not (math.isfinite(v) and v >= 0.0):
                out.append(f"{name} invalide ({v})")
        return out


_L0 = RouterSettings()
_L1 = replace(_L0, hdg_step_deg=10.0, level="L1")
_L2 = replace(_L1, dt_schedule=((3600.0, 900.0), (INF, 1800.0)), sector_deg=2.0, level="L2")
_L3 = replace(_L2, max_marks_ahead=2, level="L3")
_L4 = replace(_L3, cadence_s=600.0, level="L4")
_L5 = replace(_L4, forced_every_n=2, level="L5")

# Degraded ladder (CONTEXT §Router order): 10 deg headings -> 15/30-min steps + 2 deg sectors ->
# next mark + one -> 10-min cadence -> cost of not tacking every other cycle.
LEVELS: dict[str, RouterSettings] = {s.level: s for s in (_L0, _L1, _L2, _L3, _L4, _L5)}

Curves = tuple[tuple[float, tuple[tuple[float, float], ...]], ...]


@dataclass(frozen=True)
class RouteRequest:
    request_id: str
    t0: float  # UTC epoch s
    lat: float
    lon: float
    tack0: int  # +1 starboard, -1 port, 0 unknown
    prev_mark: CourseMark | None  # previous mark (start for leg 1): fixes the rounding geometry
    marks: tuple[CourseMark, ...]  # remaining marks, next first
    polar_curves: Curves
    eff: float
    eff_up: float | None
    eff_down: float | None
    bias: BiasParams | None
    settings: RouterSettings
    force_tack_until: float | None = None  # stay on tack0 until this time ("On reste")
    leg_only: bool = False  # route to the first mark only (forced route / cost)


class PathPoint(NamedTuple):
    t: float
    lat: float
    lon: float
    twa_deg: float  # TWA sailed from this point to the next one (signed, - = port)
    tack: int
    bsp_kn: float
    twd_deg: float
    tws_kn: float


class TackPoint(NamedTuple):
    t: float
    lat: float
    lon: float
    from_tack: int
    to_tack: int
    kind: str  # "tack" | "gybe"


class LegResult(NamedTuple):
    mark_id: str
    eta: float
    lat: float
    lon: float


@dataclass(frozen=True)
class RouteResult:
    ok: bool
    reason: str | None
    request_id: str
    t0: float
    path: tuple[PathPoint, ...] = ()
    tacks: tuple[TackPoint, ...] = ()
    legs: tuple[LegResult, ...] = ()
    eta: float | None = None
    valid: bool = False
    horizon_hold: bool = False
    start_in_margin: bool = False
    force_released_at: float | None = None
    level: str = "L0"
    compute_ms: float = 0.0
    steps: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CycleRequest:
    base: RouteRequest
    want_forced: bool = True
    stay_active: bool = False
    old_path: tuple[PathPoint, ...] | None = None
    # route time of the helm follower's projection on old_path (evaluate_path window, MD-03)
    old_t_here: float | None = None


@dataclass(frozen=True)
class CycleResult:
    optimal: RouteResult
    forced: RouteResult | None
    cost_s: float | None
    eta_old_now: float | None
    old_valid: bool | None
    old_reason: str | None
    worker: dict
