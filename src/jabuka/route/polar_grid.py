"""Dense polar table for the router: one resampling, then index arithmetic (numpy only).

Input is the Phase 2 polar JSON curves ``[[tws_kn, [[twa_deg, bsp_kn], ...]], ...]`` (02-01
``polar_to_json`` / race-pack ``polar.json``), with an implicit (0 deg, 0 kn) point on every curve
and an implicit all-zero TWS 0 curve. The table spans TWS 0-40 kn (step 1) x TWA 0-180 deg (step
0.1, so a given angle such as 37.7 deg is an exact column).

Per curve:
- linear in TWA between the given points (and from the implicit (0, 0) point);
- downwind segments whose two ends are both >= 120 deg are interpolated linearly in VMG
  (bsp x -cos TWA) instead of speed: linear speed between 150 and 180 deg invents a VMG bump
  (the 20 kn target would move from 180 to about 170 deg);
- beyond the last given angle the curve is NOT extended flat (RESEARCH Pattern 4 bug note): it
  reaches 0.9 x the last speed at 180 deg (VMG-linear when the last angle is >= 120 deg), capped
  so the run VMG at 180 deg stays below 98 % of the last given point's VMG (the X35 6-10 kn
  curves stop near their gybe angle; without the cap the tail invents a 180 deg run target).
Across TWS: linear between curves, clamped above the highest TWS.

VMG targets per integer TWS (up in [25, 90], down in [90, 180]) come from the raw table, so the
efficiency never moves the angles. Efficiency multiplies the speed: eff_up below 90 deg, eff_down
from 90 deg, eff when the specific one is not given.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np

TWS_MAX = 40
TWA_STEP = 0.1
_NA = int(round(180.0 / TWA_STEP)) + 1
TWA_AXIS = np.linspace(0.0, 180.0, _NA)
TWS_AXIS = np.arange(TWS_MAX + 1, dtype=np.float64)
TAIL_FACTOR = 0.9  # speed at 180 deg when a curve stops earlier
TAIL_VMG_CAP = 0.98  # ... but at most 98 % of the last given point's downwind VMG
VMG_SEGMENT_MIN_DEG = 120.0

Curves = tuple[tuple[float, tuple[tuple[float, float], ...]], ...]


def normalize_curves(curves: Iterable[Any]) -> Curves:
    """Validate and freeze curves into nested tuples (hashable cache key). ValueError when not
    finite, negative, out of range, or empty."""
    out = []
    try:
        items = list(curves)
    except TypeError as exc:
        raise ValueError("polaire : courbes illisibles") from exc
    if not items:
        raise ValueError("polaire : aucune courbe")
    for item in items:
        try:
            tws_raw, pts_raw = item
            tws = float(tws_raw)
            pts = tuple((float(a), float(b)) for a, b in pts_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"polaire : courbe mal formée ({item!r:.60})") from exc
        if not (math.isfinite(tws) and 0.0 < tws <= 80.0):
            raise ValueError(f"polaire : TWS invalide {tws}")
        if not pts:
            raise ValueError(f"polaire : courbe TWS {tws:g} vide")
        for twa, bsp in pts:
            if not (math.isfinite(twa) and 0.0 < twa <= 180.0):
                raise ValueError(f"polaire : TWA invalide {twa} (TWS {tws:g})")
            if not (math.isfinite(bsp) and 0.0 <= bsp <= 60.0):
                raise ValueError(f"polaire : vitesse invalide {bsp} (TWS {tws:g})")
        pts = tuple(sorted(pts))
        if len({a for a, _ in pts}) != len(pts):
            raise ValueError(f"polaire : angles en double (TWS {tws:g})")
        out.append((tws, pts))
    out.sort()
    if len({t for t, _ in out}) != len(out):
        raise ValueError("polaire : TWS en double")
    return tuple(out)


def curves_from_json(obj: Any) -> Curves:
    """Phase 2 polar JSON object -> normalised curves (ValueError when malformed)."""
    if not isinstance(obj, dict) or "curves" not in obj:
        raise ValueError("polaire : objet JSON sans 'curves'")
    return normalize_curves(obj["curves"])


def _resample_curve(pts: tuple[tuple[float, float], ...]) -> np.ndarray:
    """One curve -> speeds on TWA_AXIS (see module docstring)."""
    a = [0.0, *(p[0] for p in pts)]
    s = [0.0, *(p[1] for p in pts)]
    if a[-1] < 180.0:
        tail = TAIL_FACTOR * s[-1]
        if a[-1] >= VMG_SEGMENT_MIN_DEG:  # never a run VMG above the last given point's
            tail = min(tail, TAIL_VMG_CAP * s[-1] * -math.cos(math.radians(a[-1])))
        a.append(180.0)
        s.append(tail)
    ak = np.asarray(a)
    sk = np.asarray(s)
    out = np.interp(TWA_AXIS, ak, sk)
    vk = -sk * np.cos(np.radians(ak))  # downwind VMG at the knots
    seg = np.clip(np.searchsorted(ak, TWA_AXIS, side="right") - 1, 0, len(ak) - 2)
    vmg_seg = (ak[seg] >= VMG_SEGMENT_MIN_DEG) & (ak[seg + 1] >= VMG_SEGMENT_MIN_DEG)
    if vmg_seg.any():
        th = TWA_AXIS[vmg_seg]
        out[vmg_seg] = np.interp(th, ak, vk) / -np.cos(np.radians(th))
    return out


class PolarGrid:
    """Resampled polar (raw table + efficiency) with vectorised speed and VMG target lookups."""

    def __init__(
        self,
        raw: np.ndarray,
        eff: float = 1.0,
        eff_up: float | None = None,
        eff_down: float | None = None,
        name: str = "",
    ) -> None:
        for label, v in (("eff", eff), ("eff_up", eff_up), ("eff_down", eff_down)):
            if v is not None and not (math.isfinite(v) and 0.0 < v <= 2.0):
                raise ValueError(f"polaire : efficacité {label} invalide ({v})")
        self.raw = np.asarray(raw, dtype=np.float64)
        if self.raw.shape != (TWS_MAX + 1, _NA):
            raise ValueError("polaire : table de forme inattendue")
        self.eff = float(eff)
        self.eff_up = float(eff_up) if eff_up is not None else self.eff
        self.eff_down = float(eff_down) if eff_down is not None else self.eff
        self.name = name
        cos = np.cos(np.radians(TWA_AXIS))
        up_cols = (TWA_AXIS >= 25.0) & (TWA_AXIS <= 90.0)
        down_cols = TWA_AXIS >= 90.0
        up_idx = np.nonzero(up_cols)[0]
        down_idx = np.nonzero(down_cols)[0]
        vmg = self.raw * cos[None, :]
        self.up_deg = TWA_AXIS[up_idx[np.argmax(vmg[:, up_idx], axis=1)]]
        self.down_deg = TWA_AXIS[down_idx[np.argmax(-vmg[:, down_idx], axis=1)]]
        self.vmg_up = np.max(vmg[:, up_idx], axis=1)
        self.vmg_down = np.max(-vmg[:, down_idx], axis=1)

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_curves(
        cls,
        curves: Iterable[Any],
        eff: float = 1.0,
        eff_up: float | None = None,
        eff_down: float | None = None,
        name: str = "",
    ) -> PolarGrid:
        cv = normalize_curves(curves)
        tws_k = np.asarray([0.0, *(t for t, _ in cv)])
        rows = np.vstack([np.zeros(_NA), *(_resample_curve(p) for _, p in cv)])
        # linear across TWS, clamped above the highest curve
        k = np.clip(np.searchsorted(tws_k, TWS_AXIS, side="right") - 1, 0, len(tws_k) - 2)
        f = np.clip((TWS_AXIS - tws_k[k]) / (tws_k[k + 1] - tws_k[k]), 0.0, 1.0)[:, None]
        raw = rows[k] * (1.0 - f) + rows[k + 1] * f
        return cls(raw, eff, eff_up, eff_down, name)

    @classmethod
    def from_polar_json(
        cls,
        obj: Any,
        eff: float = 1.0,
        eff_up: float | None = None,
        eff_down: float | None = None,
    ) -> PolarGrid:
        cv = curves_from_json(obj)
        name = str(obj.get("name", "")) if isinstance(obj, dict) else ""
        return cls.from_curves(cv, eff, eff_up, eff_down, name)

    # ------------------------------------------------------------------ lookups
    def raw_speed(self, tws, twa_abs) -> np.ndarray:
        """Polar speed (kn) without efficiency, bilinear in (TWS, |TWA|)."""
        w = np.clip(np.asarray(tws, dtype=np.float64), 0.0, float(TWS_MAX))
        a = np.clip(np.abs(np.asarray(twa_abs, dtype=np.float64)), 0.0, 180.0) / TWA_STEP
        w, a = np.broadcast_arrays(w, a)
        i0 = np.minimum(w.astype(np.int64), TWS_MAX - 1)
        j0 = np.minimum(a.astype(np.int64), _NA - 2)
        fw = w - i0
        fa = a - j0
        r = self.raw
        lo = r[i0, j0] * (1.0 - fa) + r[i0, j0 + 1] * fa
        hi = r[i0 + 1, j0] * (1.0 - fa) + r[i0 + 1, j0 + 1] * fa
        return lo * (1.0 - fw) + hi * fw

    def eff_factor(self, twa_abs) -> np.ndarray:
        a = np.abs(np.asarray(twa_abs, dtype=np.float64))
        return np.where(a < 90.0, self.eff_up, self.eff_down)

    def speed(self, tws, twa_abs) -> np.ndarray:
        """Boat speed (kn) = polar x efficiency."""
        return self.raw_speed(tws, twa_abs) * self.eff_factor(twa_abs)

    def targets(self, tws) -> tuple[np.ndarray, np.ndarray]:
        """(upwind, downwind) VMG target |TWA| in degrees, linear between integer TWS."""
        w = np.clip(np.asarray(tws, dtype=np.float64), 0.0, float(TWS_MAX))
        return np.interp(w, TWS_AXIS, self.up_deg), np.interp(w, TWS_AXIS, self.down_deg)
