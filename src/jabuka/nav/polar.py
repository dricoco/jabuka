"""Boat polar as per-TWS curves (Expedition semantics) and its VMG targets (WIND-01).

speed(tws, twa): |TWA| folded into [0, 180]; linear in TWA inside each of the two bracketing TWS
curves, then linear across TWS. Every curve gets an implicit (0 deg, 0 kn) point and there is an
implicit all-zero TWS 0 curve. Above the highest TWS the speed is clamped (no extrapolation);
beyond the last TWA of a curve the last speed is held.

targets(tws): max upwind VMG (bsp * cos) over [25, 90] and max downwind VMG (-bsp * cos) over
[90, deepest TWA of the polar at that TWS], on a 0.5 deg grid plus every explicit polar angle, so a
VPP beat/gybe angle is found exactly. Cached per TWS rounded to 0.1 kn.

The efficiency factor is NEVER applied here (WIND-02): callers multiply target and polar speeds.
A uniform factor does not move the VMG-optimal angles (Pitfall 9).

Heavy-weather reduction: derate_polar(polar, start, full, reduction) returns a NEW polar whose
curves are multiplied by heavy_wind_factor(tws) (1 below start, ramping to 1 - reduction at and
above full). Callers decide whether to use it (the helm and the router share the same derated
polar; the efficiency still multiplies on top). The factor is uniform per TWS, so it does not move
the VMG angles either (Pitfall 9); the knots added at start and full are built on the union of
the bracketing curves' angles, so below start the derated polar reproduces the raw one exactly.
Units: knots and degrees (the polar's own units).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, NamedTuple

DEFAULT_POLAR_FILE = "x35-orc-od-2019.exp"
DEFAULT_POLAR_NAME = "X35 ORC OD 2019 (intérim)"
UP_RANGE = (25.0, 90.0)
GRID_STEP = 0.5

Curve = tuple[float, list[tuple[float, float]]]


class Targets(NamedTuple):
    up_twa: float  # deg
    up_bsp: float  # kn (raw polar, no efficiency)
    down_twa: float  # deg
    down_bsp: float  # kn


def _finite_nonneg(x: float, what: str) -> float:
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"polar: {what} must be a finite non-negative number, got {x!r}")
    return float(x)


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Piecewise linear, holding the end values outside [xs[0], xs[-1]]."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    if x1 == x0:
        return ys[hi]
    return ys[lo] + (ys[hi] - ys[lo]) * (x - x0) / (x1 - x0)


@dataclass
class Polar:
    name: str
    curves: list[Curve]
    source: str = ""
    _prepared: list[tuple[float, list[float], list[float]]] = field(
        default_factory=list, repr=False, compare=False
    )
    _cache: dict[float, Targets] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.curves:
            raise ValueError("polar: no TWS curve")
        prepared = []
        for tws, pts in sorted(self.curves, key=lambda c: c[0]):
            tws = _finite_nonneg(tws, "TWS")
            if not pts:
                raise ValueError(f"polar: empty curve at TWS {tws}")
            clean = sorted((_finite_nonneg(a, "TWA"), _finite_nonneg(b, "BSP")) for a, b in pts)
            if clean[-1][0] > 180.0:
                raise ValueError(f"polar: TWA above 180 at TWS {tws}")
            if clean[0][0] > 0.0:
                clean.insert(0, (0.0, 0.0))
            prepared.append((tws, [a for a, _ in clean], [b for _, b in clean]))
        if prepared[-1][0] <= 0.0:  # IN-04: targets() needs a real wind curve
            raise ValueError("polar: no TWS curve above 0 kn")
        if prepared[0][0] > 0.0:
            # implicit TWS 0 curve: zero everywhere
            prepared.insert(0, (0.0, [0.0, 180.0], [0.0, 0.0]))
        self._prepared = prepared
        self.curves = [(t, list(zip(a, b, strict=True))) for t, a, b in prepared if t > 0.0]

    # -- queries -----------------------------------------------------------------------------
    def _bracket(self, tws: float) -> tuple[int, int, float]:
        p = self._prepared
        if tws >= p[-1][0]:
            return len(p) - 1, len(p) - 1, 0.0
        for i in range(len(p) - 1):
            t0, t1 = p[i][0], p[i + 1][0]
            if t0 <= tws <= t1:
                return i, i + 1, (tws - t0) / (t1 - t0) if t1 > t0 else 0.0
        return 0, 0, 0.0

    def speed(self, tws_kn: float, twa_deg: float) -> float:
        """Raw polar boat speed (kn) at TWS (kn) and TWA (deg, any sign/wrap)."""
        if not (math.isfinite(tws_kn) and math.isfinite(twa_deg)) or tws_kn <= 0.0:
            return 0.0
        a = abs(math.fmod(twa_deg, 360.0))
        if a > 180.0:
            a = 360.0 - a
        i, j, f = self._bracket(tws_kn)
        _, xa, ya = self._prepared[i]
        s0 = _interp(xa, ya, a)
        if j == i:
            return s0
        _, xb, yb = self._prepared[j]
        return s0 + (_interp(xb, yb, a) - s0) * f

    def _deepest(self, tws_kn: float) -> float:
        """Deepest TWA the polar covers at this TWS (interpolated across the bracketing curves)."""
        i, j, f = self._bracket(tws_kn)
        lo = self._prepared[i][1][-1] if self._prepared[i][0] > 0 else self._prepared[j][1][-1]
        hi = self._prepared[j][1][-1]
        return min(180.0, max(90.0, lo + (hi - lo) * f))

    def _candidates(self, lo: float, hi: float) -> list[float]:
        n = int(math.floor((hi - lo) / GRID_STEP + 1e-9))  # never past hi
        grid = {round(lo + k * GRID_STEP, 6) for k in range(n + 1)}
        for _, xs, _ in self._prepared:
            grid.update(a for a in xs if lo <= a <= hi)
        grid.add(hi)
        return sorted(grid)

    def targets(self, tws_kn: float) -> Targets:
        """Max-VMG upwind and downwind TWA (deg) and their raw BSP (kn)."""
        key = round(max(0.0, tws_kn), 1) if math.isfinite(tws_kn) else 0.0
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        # below the lowest curve the speeds scale towards 0, so the optimal angles are the lowest
        # curve's: search there, then read the speeds at the real TWS
        lowest = next(t for t, _, _ in self._prepared if t > 0.0)
        search = max(key, lowest)
        best_up = max(
            self._candidates(*UP_RANGE),
            key=lambda a: self.speed(search, a) * math.cos(math.radians(a)),
        )
        deep = self._deepest(search)
        best_down = max(
            self._candidates(90.0, deep),
            key=lambda a: -self.speed(search, a) * math.cos(math.radians(a)),
        )
        out = Targets(best_up, self.speed(key, best_up), best_down, self.speed(key, best_down))
        if len(self._cache) > 4096:
            self._cache.clear()
        self._cache[key] = out
        return out


# -- efficiency (WIND-02) ----------------------------------------------------------------------
EFF_UP_MAX_DEG = 70.0  # |TWA| below: upwind factor (same split as the helm primary number)
EFF_DOWN_MIN_DEG = 110.0  # |TWA| above: downwind factor; in between the general factor


def efficiency_for(
    twa_deg: float | None,
    efficiency: float,
    efficiency_up: float | None = None,
    efficiency_down: float | None = None,
) -> float:
    """Factor for the current point of sail (% polar, reach target speed): efficiency_up upwind,
    efficiency_down downwind when set, the general efficiency otherwise."""
    if twa_deg is not None and math.isfinite(twa_deg):
        a = abs(twa_deg)
        if a < EFF_UP_MAX_DEG and efficiency_up is not None:
            return efficiency_up
        if a > EFF_DOWN_MIN_DEG and efficiency_down is not None:
            return efficiency_down
    return efficiency


def apply_efficiency(
    raw: Targets,
    efficiency: float,
    efficiency_up: float | None = None,
    efficiency_down: float | None = None,
) -> Targets:
    """Raw VMG targets -> targets with the efficiency on the SPEEDS only (Pitfall 9): the upwind
    target speed gets efficiency_up (else efficiency), the downwind one efficiency_down."""
    up = efficiency_up if efficiency_up is not None else efficiency
    down = efficiency_down if efficiency_down is not None else efficiency
    return Targets(raw.up_twa, raw.up_bsp * up, raw.down_twa, raw.down_bsp * down)


# -- heavy-weather reduction -------------------------------------------------------------------
def heavy_wind_factor(tws_kn: float, start_kn: float, full_kn: float, reduction: float) -> float:
    """1 - reduction * clamp((tws - start) / (full - start), 0, 1): 1 up to start, 1 - reduction
    from full upwards, linear in between."""
    if full_kn <= start_kn:
        return 1.0 - reduction if tws_kn >= full_kn else 1.0
    ramp = min(1.0, max(0.0, (tws_kn - start_kn) / (full_kn - start_kn)))
    return 1.0 - reduction * ramp


def _knot_curve(polar: Polar, tws: float) -> Curve:
    """A curve at `tws` reproducing the polar exactly there: the union of the bracketing curves'
    angles up to the (interpolated) deepest TWA, plus that deepest TWA. Above the top curve it is
    a copy of the top curve, below the lowest one the lowest curve's angle set."""
    below = [c for c in polar.curves if c[0] < tws]
    above = [c for c in polar.curves if c[0] > tws]
    brackets = ([below[-1]] if below else []) + ([above[0]] if above else [])
    deep = polar._deepest(tws)
    angles = {a for _, pts in brackets for a, _ in pts if a <= deep}
    angles.add(deep)
    return tws, [(a, polar.speed(tws, a)) for a in sorted(angles)]


def derate_polar(polar: Polar, start_kn: float, full_kn: float, reduction: float) -> Polar:
    """The polar with the heavy-wind reduction applied on its curves (pure: never mutates
    `polar`). reduction == 0 returns `polar` itself. Knots are added at start_kn and full_kn
    (unless a curve already exists there) so the ramp is exact; every curve keeps its own TWA
    points. Raises ValueError unless 0 < start_kn < full_kn and 0 <= reduction < 1."""
    vals = (start_kn, full_kn, reduction)
    if not all(isinstance(x, int | float) and math.isfinite(x) for x in vals):
        raise ValueError(f"polaire vent fort : valeurs non finies {vals!r}")
    if not 0.0 < start_kn < full_kn:
        raise ValueError(
            f"polaire vent fort : le début ({start_kn}) doit être > 0 et < la fin ({full_kn})"
        )
    if not 0.0 <= reduction < 1.0:
        raise ValueError(f"polaire vent fort : réduction hors de [0, 1[ : {reduction}")
    if reduction == 0.0:
        return polar
    curves: list[Curve] = list(polar.curves)
    for k in (float(start_kn), float(full_kn)):
        if not any(math.isclose(t, k, abs_tol=1e-6) for t, _ in polar.curves):
            curves.append(_knot_curve(polar, k))
    curves.sort(key=lambda c: c[0])
    out = [
        (tws, [(a, b * heavy_wind_factor(tws, start_kn, full_kn, reduction)) for a, b in pts])
        for tws, pts in curves
    ]
    return Polar(name=polar.name, curves=out, source=polar.source)


# -- parsing / serialisation -------------------------------------------------------------------
def parse_expedition(text: str, name: str = "polar") -> Polar:
    """Expedition polar: '!' comment lines, data lines 'TWS TWA BSP TWA BSP ...' separated by tabs
    or spaces. Raises ValueError on malformed, non-finite or negative numbers."""
    curves: list[Curve] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        try:
            nums = [float(tok) for tok in line.split()]
        except ValueError:
            raise ValueError(f"polar line {lineno}: not a number in {line[:60]!r}") from None
        if len(nums) < 3 or (len(nums) - 1) % 2:
            raise ValueError(f"polar line {lineno}: expected TWS followed by TWA BSP pairs")
        for x in nums:
            _finite_nonneg(x, f"value on line {lineno}")
        tws = nums[0]
        pts = [(nums[k], nums[k + 1]) for k in range(1, len(nums), 2)]
        curves.append((tws, pts))
    if not curves:
        raise ValueError("polar: no data line")
    return Polar(name=name, curves=curves, source="expedition")


def polar_to_json(polar: Polar) -> dict[str, Any]:
    return {
        "name": polar.name,
        "source": polar.source,
        "curves": [[t, [[a, b] for a, b in pts]] for t, pts in polar.curves],
    }


def polar_from_json(obj: Any) -> Polar:
    """{"name", "source", "curves": [[tws, [[twa, bsp], ...]], ...]} -> Polar.
    Raises ValueError when malformed."""
    if not isinstance(obj, dict) or not isinstance(obj.get("curves"), list):
        raise ValueError("polar json: expected an object with a 'curves' list")
    curves: list[Curve] = []
    for c in obj["curves"]:
        if not (isinstance(c, list | tuple) and len(c) == 2 and isinstance(c[1], list | tuple)):
            raise ValueError("polar json: each curve is [tws, [[twa, bsp], ...]]")
        pts = []
        for p in c[1]:
            if not (isinstance(p, list | tuple) and len(p) == 2):
                raise ValueError("polar json: each point is [twa, bsp]")
            pts.append((float(p[0]), float(p[1])))
        curves.append((float(c[0]), pts))
    name = obj.get("name")
    return Polar(
        name=str(name)[:80] if name else "polar",
        curves=curves,
        source=str(obj.get("source") or "json")[:80],
    )


def default_polar() -> Polar:
    """The packaged interim X35 polar (ORC X-35 OD 2019 certificate, derived)."""
    text = resources.files("jabuka.nav").joinpath("data", DEFAULT_POLAR_FILE).read_text("utf-8")
    p = parse_expedition(text, DEFAULT_POLAR_NAME)
    p.source = f"builtin:{DEFAULT_POLAR_FILE}"
    return p


def load_racepack_polar(racepack_dir: str | Path | None) -> Polar:
    """<racepack>/polar.json when it parses and validates, else default_polar().
    Polar.source says which one was used ("racepack:polar.json" or "builtin:...").
    The smoke check runs what the nav tick runs (speed and the VMG targets, light and strong
    wind): a polar that would raise there every tick falls back to the builtin one (IN-04)."""
    if racepack_dir is not None:
        path = Path(racepack_dir) / "polar.json"
        try:
            p = polar_from_json(json.loads(path.read_text("utf-8")))
            for tws in (6.0, 12.0, 20.0):
                p.speed(tws, 45.0)
                t = p.targets(tws)
                if not all(math.isfinite(x) for x in (t.up_twa, t.up_bsp, t.down_twa, t.down_bsp)):
                    raise ValueError("polar: non-finite targets")
            p.source = "racepack:polar.json"
            return p
        except Exception:  # anything the tick would hit: the builtin polar, never a dead helm
            pass
    return default_polar()
