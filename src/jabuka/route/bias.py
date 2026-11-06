"""GRIB bias (WIND-06): interface skeleton (RED phase, behaviour not implemented yet)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple


@dataclass(frozen=True)
class BiasParams:
    d_dir_rad: float
    k: float
    t_obs: float
    tau_decay_s: float = 9000.0

    def weights(self, t: float) -> tuple[float, float]:
        return 0.0, 1.0

    def apply_uv(self, u: float, v: float, t: float) -> tuple[float, float]:
        return u, v

    def effective(self, t: float) -> tuple[float, float]:
        return 0.0, 1.0


class BiasSample(NamedTuple):
    t: float
    dt: float
    source: str
    stale: bool
    twd_meas: float
    tws_meas: float
    twd_grib: float | None
    tws_grib: float | None
    bsp: float
    cog: float | None
    in_zone: bool
    last_tack_t: float | None
    enabled: bool
    current_uv: tuple[float, float] | None


class BiasEstimator:
    def __init__(self, **_kw: Any) -> None:
        pass

    def update(self, sample: BiasSample) -> None:
        pass

    def observe_manual(
        self, t: float, twd: float, tws: float, grib_twd: float, grib_tws: float
    ) -> None:
        pass

    def raw(self) -> tuple[float, float] | None:
        return None

    def params(self, t: float) -> BiasParams | None:
        return None

    def status(self, t: float) -> dict[str, Any]:
        return {}

    def to_json(self) -> dict[str, Any]:
        return {}

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> BiasEstimator:
        return cls()

    def reset(self) -> None:
        pass


def bias_changed(prev: tuple[float, float] | None, now: tuple[float, float] | None) -> bool:
    return False
