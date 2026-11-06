"""GRIB bias (WIND-06): learn how the measured wind differs from the GRIB, apply it with decay.

RESEARCH Pattern 8. Pure Python (stdlib + jabuka.common), no clock reads: every time is an
argument (UTC epoch s from the GPS-disciplined clock). Angles in radians, speeds in m/s.

- The estimator learns only in steady sailing (gate below), with a time-based EMA over gated
  seconds only: a circular mean of the direction offset via EMA(sin)/EMA(cos) and a ratio of
  mean speeds. Valid after 300 gated seconds, clamped to +-35 deg and 0.6..1.5.
- A gated sample more than ``tau_ema_s`` after the previous one (the gate was closed: Jabuka
  zone, light air, MANUEL/GRIB source) starts a new learning episode: the old estimate is kept
  only as a fallback with its original observation time, so it keeps decaying instead of coming
  back at full weight, until the new EMA is valid again (03-REVIEW HI-02). A restored bias.json
  is such a fallback too, never the live EMA.
- The router (per time step) and the core (GRIB-only helm wind) apply BiasParams: the GRIB
  air-motion vector is rotated clockwise by w * d (TWD increases for a positive offset) and
  scaled by 1 + w (k - 1), with w = exp(-max(0, t - t_obs) / tau_decay).
- States and reasons are French, as shown at the helm.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, NamedTuple

from jabuka.common.conventions import uv_from_wind_from, wind_from_uv
from jabuka.common.units import kn_to_ms, wrap_pi

LIVE_SOURCES = frozenset({"LIVE", "LIVE_BG"})
MIN_BSP = kn_to_ms(2.0)
MIN_TWS = kn_to_ms(4.0)
TACK_HOLD_S = 180.0
TURN_WINDOW_S = 30.0
MAX_TURN_RATE = math.radians(3.0)  # rad/s
MAX_DT_S = 10.0  # a gated sample never counts for more than this (gaps are not steady sailing)
ACTIVE_GRACE_S = 10.0  # "actif" while the last gated sample is this recent

STATE_NONE = "aucun"
STATE_LEARNING = "apprentissage"
STATE_ACTIVE = "actif"
STATE_FADING = "s'estompe"
STATE_FROZEN = "gelé (Jabuka)"
STATE_DISABLED = "désactivé"

REASON_DISABLED = "désactivé"
REASON_ZONE = "gelé (Jabuka)"
REASON_SOURCE = "source non mesurée"
REASON_STALE = "mesures périmées"
REASON_NO_GRIB = "pas de GRIB"
REASON_BSP = "vitesse faible"
REASON_TACK = "virement récent"
REASON_NO_COG = "COG absent"
REASON_TURN = "virage"
REASON_LIGHT = "vent faible"

JSON_VERSION = 1


@dataclass(frozen=True)
class BiasParams:
    """Bias to apply to the GRIB: direction offset (rad, + = clockwise / TWD increases), speed
    ratio, observation time (UTC s) and decay time constant."""

    d_dir_rad: float
    k: float
    t_obs: float
    tau_decay_s: float = 9000.0

    def weights(self, t: float) -> tuple[float, float]:
        """(phi rad, scale) at time t: phi = w d, scale = 1 + w (k - 1)."""
        w = math.exp(-max(0.0, t - self.t_obs) / self.tau_decay_s)
        return w * self.d_dir_rad, 1.0 + w * (self.k - 1.0)

    def apply_uv(self, u: float, v: float, t: float) -> tuple[float, float]:
        """GRIB air motion (u east, v north) -> corrected air motion at time t."""
        phi, scale = self.weights(t)
        c, s = math.cos(phi), math.sin(phi)
        return (u * c + v * s) * scale, (-u * s + v * c) * scale

    def effective(self, t: float) -> tuple[float, float]:
        """(direction offset deg, speed ratio) actually applied at time t (helm display)."""
        phi, scale = self.weights(t)
        return math.degrees(phi), scale


class BiasSample(NamedTuple):
    """One 1 Hz estimator input. Radians, m/s, UTC epoch s."""

    t: float
    dt: float  # seconds since the previous sample
    source: str  # Phase 2 wind source: LIVE | LIVE_BG | MANUEL | GRIB | NONE
    stale: bool  # any of AWA/AWS/BSP/heading/GPS stale
    twd_meas: float  # measured TRUE wind FROM (water-referenced, B&G)
    tws_meas: float
    twd_grib: float | None  # GRIB at (boat, now); None when the GRIB does not cover it
    tws_grib: float | None
    bsp: float
    cog: float | None  # damped COG
    in_zone: bool  # inside the Jabuka magnetic zone (freeze)
    last_tack_t: float | None
    enabled: bool
    current_uv: tuple[float, float] | None  # water motion (towards) u/v at the boat


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


class BiasEstimator:
    """Gated EMA estimator of the GRIB bias, plus manual observations (Pattern 8)."""

    def __init__(
        self,
        tau_ema_s: float = 600.0,
        min_gated_s: float = 300.0,
        clamp_deg: float = 35.0,
        k_min: float = 0.6,
        k_max: float = 1.5,
        tau_decay_s: float = 9000.0,
    ):
        self.tau_ema_s = tau_ema_s
        self.min_gated_s = min_gated_s
        self.clamp_deg = clamp_deg
        self.k_min = k_min
        self.k_max = k_max
        self.tau_decay_s = tau_decay_s
        self._cog: deque[tuple[float, float]] = deque()
        self.enabled = True
        self.reset()

    # ---- state --------------------------------------------------------------------------

    def reset(self) -> None:
        """Forget everything learned (EMA and manual observation)."""
        self._s = 0.0  # EMA(sin delta)
        self._c = 0.0  # EMA(cos delta)
        self._m = 0.0  # EMA(TWS measured, ground)
        self._g = 0.0  # EMA(TWS GRIB)
        self._gated_s = 0.0
        self._t_obs: float | None = None
        self._manual: tuple[float, float, float] | None = None  # (d raw, k raw, t_obs)
        # previous episode's estimate (d raw, k raw, t_obs), decaying from its own t_obs
        self._fallback: tuple[float, float, float] | None = None
        self._reason: str | None = None
        self._cog.clear()

    def _clamped(self, d: float, k: float) -> tuple[float, float, bool]:
        lim = math.radians(self.clamp_deg)
        dc, kc = _clamp(d, -lim, lim), _clamp(k, self.k_min, self.k_max)
        return dc, kc, (dc != d or kc != k)

    # ---- learning -----------------------------------------------------------------------

    def _turn_rate(self, t: float, cog: float | None) -> float | None:
        """|rad/s| over the last TURN_WINDOW_S, summed wrapped increments; None without COG."""
        if cog is None:
            self._cog.clear()
            return None
        self._cog.append((t, cog))
        while self._cog and self._cog[0][0] < t - TURN_WINDOW_S:
            self._cog.popleft()
        if len(self._cog) < 2:
            return 0.0
        total = 0.0
        prev = self._cog[0][1]
        for _, c in list(self._cog)[1:]:
            total += wrap_pi(c - prev)
            prev = c
        span = self._cog[-1][0] - self._cog[0][0]
        return abs(total) / span if span > 0.0 else 0.0

    def _gate(self, s: BiasSample, tws_meas: float, rate: float | None) -> str | None:
        if not s.enabled:
            return REASON_DISABLED
        if s.in_zone:
            return REASON_ZONE
        if s.source not in LIVE_SOURCES:
            return REASON_SOURCE
        if s.stale:
            return REASON_STALE
        if s.twd_grib is None or s.tws_grib is None:
            return REASON_NO_GRIB
        if not s.bsp > MIN_BSP:
            return REASON_BSP
        if s.last_tack_t is not None and s.t - s.last_tack_t < TACK_HOLD_S:
            return REASON_TACK
        if rate is None:
            return REASON_NO_COG
        if rate > MAX_TURN_RATE:
            return REASON_TURN
        if not (tws_meas > MIN_TWS and s.tws_grib > MIN_TWS):
            return REASON_LIGHT
        return None

    def _ground(self, s: BiasSample) -> tuple[float, float]:
        """Measured (water-referenced) wind -> ground wind when a current is known."""
        if s.current_uv is None:
            return s.twd_meas, s.tws_meas
        u, v = uv_from_wind_from(s.twd_meas, s.tws_meas)
        return wind_from_uv(u + s.current_uv[0], v + s.current_uv[1])

    def update(self, sample: BiasSample) -> None:
        """Feed one sample; accumulates only when every gate condition holds."""
        self.enabled = bool(sample.enabled)
        rate = self._turn_rate(sample.t, sample.cog)
        twd, tws = self._ground(sample)
        reason = self._gate(sample, tws, rate)
        self._reason = reason
        if reason is not None:
            return
        assert sample.twd_grib is not None and sample.tws_grib is not None
        if self._t_obs is not None and sample.t - self._t_obs > self.tau_ema_s:
            self._new_episode()
        dt = _clamp(float(sample.dt), 0.0, MAX_DT_S)
        delta = wrap_pi(twd - sample.twd_grib)
        if self._t_obs is None or self._gated_s <= 0.0:
            alpha = 1.0  # first gated sample initialises the EMAs
        else:
            alpha = 1.0 - math.exp(-dt / self.tau_ema_s)
        self._s += alpha * (math.sin(delta) - self._s)
        self._c += alpha * (math.cos(delta) - self._c)
        self._m += alpha * (tws - self._m)
        self._g += alpha * (sample.tws_grib - self._g)
        self._gated_s += dt
        self._t_obs = sample.t

    def _new_episode(self) -> None:
        """Keep the current estimate only as a decaying fallback and learn afresh (HI-02)."""
        if self._ema_valid():
            raw = self.raw()
            assert raw is not None and self._t_obs is not None
            self._fallback = (raw[0], raw[1], self._t_obs)
        self._s = self._c = self._m = self._g = 0.0
        self._gated_s = 0.0
        self._t_obs = None

    def observe_manual(
        self, t: float, twd: float, tws: float, grib_twd: float, grib_tws: float
    ) -> None:
        """A manual TRUE wind entry becomes one observation (no EMA), clamped like the EMA."""
        k = tws / grib_tws if grib_tws > 0.1 else 1.0
        self._manual = (wrap_pi(twd - grib_twd), k, t)

    # ---- outputs ------------------------------------------------------------------------

    def raw(self) -> tuple[float, float] | None:
        """Unclamped EMA estimate (d rad, k), or None before any gated sample."""
        if self._t_obs is None:
            return None
        k = self._m / self._g if self._g > 0.0 else 1.0
        return math.atan2(self._s, self._c), k

    def _ema_valid(self) -> bool:
        return self._t_obs is not None and self._gated_s >= self.min_gated_s

    def _source(self) -> tuple[str, float, float, float] | None:
        """("ema"|"manual", d raw, k raw, t_obs) of the bias in force (newer wins)."""
        cands: list[tuple[str, float, float, float]] = []
        if self._ema_valid():
            raw = self.raw()
            assert raw is not None and self._t_obs is not None
            cands.append(("ema", raw[0], raw[1], self._t_obs))
        if self._manual is not None:
            cands.append(("manual", *self._manual))
        if self._fallback is not None:
            cands.append(("fallback", *self._fallback))
        if not cands:
            return None
        return max(cands, key=lambda c: c[3])

    def params(self, t: float) -> BiasParams | None:
        """Bias to apply (decay is in BiasParams.weights), or None (disabled / nothing yet)."""
        if not self.enabled:
            return None
        src = self._source()
        if src is None:
            return None
        d, k, _ = self._clamped(src[1], src[2])
        return BiasParams(d, k, src[3], self.tau_decay_s)

    def status(self, t: float) -> dict[str, Any]:
        """Helm/diag view: state, effective offset and ratio now, gate reason."""
        src = self._source()
        p = self.params(t)
        clamped = False
        if src is not None:
            clamped = self._clamped(src[1], src[2])[2]
        if not self.enabled:
            state = STATE_DISABLED
        elif self._reason == REASON_ZONE:
            state = STATE_FROZEN
        elif p is None:
            state = STATE_LEARNING if self._gated_s > 0.0 else STATE_NONE
        elif (
            src is not None
            and src[0] == "ema"
            and self._reason is None
            and t - src[3] <= ACTIVE_GRACE_S
        ):
            state = STATE_ACTIVE
        else:
            state = STATE_FADING
        dir_deg, ratio = p.effective(t) if p is not None else (None, None)
        return {
            "enabled": self.enabled,
            "valid": p is not None,
            "state": state,
            "dir_deg": dir_deg,
            "ratio": ratio,
            "gated_s": self._gated_s,
            "clamped": clamped,
            "t_obs": p.t_obs if p is not None else None,
            "reason": self._reason,
        }

    # ---- persistence ----------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "version": JSON_VERSION,
            "config": {
                "tau_ema_s": self.tau_ema_s,
                "min_gated_s": self.min_gated_s,
                "clamp_deg": self.clamp_deg,
                "k_min": self.k_min,
                "k_max": self.k_max,
                "tau_decay_s": self.tau_decay_s,
            },
            "enabled": self.enabled,
            "S": self._s,
            "C": self._c,
            "M": self._m,
            "G": self._g,
            "gated_s": self._gated_s,
            "t_obs": self._t_obs,
            "manual": list(self._manual) if self._manual is not None else None,
            "fallback": list(self._fallback) if self._fallback is not None else None,
            "reason": self._reason,
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> BiasEstimator:
        """Rebuild an estimator from to_json(); ValueError on a malformed object."""
        try:
            if int(obj["version"]) != JSON_VERSION:
                raise ValueError(f"unsupported bias state version {obj['version']!r}")
            cfg = {k: float(v) for k, v in dict(obj["config"]).items()}
            est = cls(**cfg)
            est.enabled = bool(obj["enabled"])
            est._s, est._c = float(obj["S"]), float(obj["C"])
            est._m, est._g = float(obj["M"]), float(obj["G"])
            est._gated_s = float(obj["gated_s"])
            est._t_obs = None if obj["t_obs"] is None else float(obj["t_obs"])
            man = obj["manual"]
            if man is not None:
                d, k, t = (float(x) for x in man)
                est._manual = (d, k, t)
            fb = obj.get("fallback")
            if fb is not None:
                d, k, t = (float(x) for x in fb)
                est._fallback = (d, k, t)
            reason = obj.get("reason")
            est._reason = None if reason is None else str(reason)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid bias state: {exc}") from exc
        values = [est._s, est._c, est._m, est._g, est._gated_s]
        if not all(math.isfinite(x) for x in values):
            raise ValueError("invalid bias state: non-finite value")
        # after a restart the learned EMA is history: a decaying fallback, never the live EMA
        # (03-REVIEW HI-02); learning restarts on the next gated sample
        est._new_episode()
        return est


def bias_changed(prev: tuple[float, float] | None, now: tuple[float, float] | None) -> bool:
    """Reroute threshold (Pattern 8 step 7): |d dir| > 5 deg or |d ratio| > 0.10, or the bias
    appeared/disappeared. Arguments are effective (dir_deg, ratio) pairs."""
    if prev is None or now is None:
        return (prev is None) != (now is None)
    ddir = math.degrees(wrap_pi(math.radians(now[0] - prev[0])))
    return abs(ddir) > 5.0 or abs(now[1] - prev[1]) > 0.10
