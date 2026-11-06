"""Tack/gybe detection and the angles the crew actually sails (NAV-01 sailed mode, RESEARCH
Pattern 5).

- Point of sail from the helm-damped TWA: upwind |TWA| <= 70 deg, downwind >= 110 deg. Anything in
  between (reaching) is not learnt and ends the current run.
- A tack (upwind) or gybe (downwind) is a sign change of the TWA held for >= 30 s. A shorter
  excursion is ignored and the run on the original side goes on.
- A run is settled once it has lasted >= 120 s. Its sample is theta = wrap_pi(circular mean COG -
  circular mean TWD) and the mean SOG, over the run minus its first 30 s (the manoeuvre). theta is
  ground-referenced, so it already includes leeway and current: laylines never add the current
  to it (Pitfall 8). While a settled run continues, its sample keeps updating.
- The last 3 samples are kept per (point of sail, side). Use the median theta and the mean SOG.
- Nothing is learnt inside the Jabuka zone, where COG replaces an untrusted compass and TWD comes
  from COG (Pitfall 7).

Samples live in memory and in the derived log (nav.tacks.*), not in the settings.
Inputs: radians TRUE, SOG in kn, t from the injected monotonic clock. Side naming: stbd = TWA >= 0
(project convention, negative = port), so a starboard-tack theta is negative.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Any

from jabuka.common.units import wrap_pi

UP_MAX_DEG = 70.0
DOWN_MIN_DEG = 110.0
FLIP_HOLD_S = 30.0
SETTLED_S = 120.0
KEEP = 3
LEGS = ("up", "down")
SIDES = ("stbd", "port")


@dataclass(frozen=True)
class TackSample:
    theta_deg: float  # signed ground angle COG - TWD (stbd negative)
    sog_kn: float


class _Run:
    __slots__ = ("leg", "side", "start", "n", "cx", "cy", "wx", "wy", "sog", "recorded", "last_t")

    def __init__(self, leg: str, side: str, start: float) -> None:
        self.leg, self.side, self.start = leg, side, start
        self.n = 0
        self.cx = self.cy = self.wx = self.wy = self.sog = 0.0
        self.recorded = False
        self.last_t = start

    def add(self, t: float, cog: float, twd: float, sog: float) -> None:
        self.last_t = t
        if t < self.start + FLIP_HOLD_S:  # the manoeuvre itself is not a settled angle
            return
        self.n += 1
        self.cx += math.sin(cog)
        self.cy += math.cos(cog)
        self.wx += math.sin(twd)
        self.wy += math.cos(twd)
        self.sog += sog

    def sample(self) -> TackSample | None:
        if self.n == 0:
            return None
        theta = wrap_pi(math.atan2(self.cx, self.cy) - math.atan2(self.wx, self.wy))
        return TackSample(math.degrees(theta), self.sog / self.n)


class TackTracker:
    def __init__(self, settings: Any = None) -> None:
        self.settings = settings  # interface symmetry with the other nav stages (unused)
        self._samples: dict[tuple[str, str], deque[TackSample]] = {
            (leg, side): deque(maxlen=KEEP) for leg in LEGS for side in SIDES
        }
        self._run: _Run | None = None
        self._pending_side: str | None = None
        self._pending_start: float | None = None
        self._last_t: float | None = None

    def update(
        self,
        t_mono: float,
        twa_damped: float | None,
        cog_t: float | None,
        twd_lay_t: float | None,
        sog_kn: float | None,
        in_zone: bool,
    ) -> None:
        if self._last_t is not None and t_mono <= self._last_t:
            return  # same instant twice (API push between ticks) or clock going backwards
        self._last_t = t_mono
        if in_zone:
            self._end_run()
            return
        if twa_damped is None or cog_t is None or twd_lay_t is None or sog_kn is None:
            return
        a = abs(math.degrees(wrap_pi(twa_damped)))
        leg = "up" if a <= UP_MAX_DEG else "down" if a >= DOWN_MIN_DEG else None
        if leg is None:
            self._end_run()
            return
        side = "stbd" if twa_damped >= 0.0 else "port"
        run = self._run
        if run is None or run.leg != leg:
            self._start(leg, side, t_mono)
            run = self._run
        elif side == run.side:
            self._pending_side = self._pending_start = None  # short excursion: ignored
        else:
            if self._pending_side != side:
                self._pending_side, self._pending_start = side, t_mono
            if t_mono - self._pending_start >= FLIP_HOLD_S:  # confirmed tack / gybe
                self._start(leg, side, self._pending_start)
            run = self._run
            if run.side != side:  # still pending: nothing to add to either run
                self._record(run, t_mono)
                return
        assert run is not None
        run.add(t_mono, cog_t, twd_lay_t, sog_kn)
        self._record(run, t_mono)

    def _start(self, leg: str, side: str, start: float) -> None:
        self._run = _Run(leg, side, start)
        self._pending_side = self._pending_start = None

    def _end_run(self) -> None:
        self._run = None
        self._pending_side = self._pending_start = None

    def _record(self, run: _Run, t: float) -> None:
        if t - run.start < SETTLED_S:
            return
        smp = run.sample()
        if smp is None:
            return
        q = self._samples[(run.leg, run.side)]
        if run.recorded and q:
            q[-1] = smp
        else:
            q.append(smp)
            run.recorded = True

    # -- queries -----------------------------------------------------------------------------
    def samples(self, leg: str, side: str) -> list[float]:
        """Recorded theta (deg), oldest first."""
        return [s.theta_deg for s in self._samples[(leg, side)]]

    def angles(self) -> dict[str, dict[str, TackSample | None]]:
        """{"up": {"stbd": TackSample|None, "port": ...}, "down": {...}}: median theta of the last
        samples and their mean SOG."""
        out: dict[str, dict[str, TackSample | None]] = {}
        for leg in LEGS:
            out[leg] = {}
            for side in SIDES:
                q = self._samples[(leg, side)]
                out[leg][side] = (
                    TackSample(
                        statistics.median(s.theta_deg for s in q),
                        statistics.fmean(s.sog_kn for s in q),
                    )
                    if q
                    else None
                )
        return out

    def diag(self, side: str) -> dict[str, list[float]]:
        """Diag / derived-log value for nav.tacks.<side>: recorded thetas per point of sail."""
        return {leg: [round(x, 1) for x in self.samples(leg, side)] for leg in LEGS}
