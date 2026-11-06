"""GRIB bias (WIND-06): application to u/v, gated EMA estimator, clamps, decay, manual entry."""

from __future__ import annotations

import json
import math

import pytest

from jabuka.common.conventions import current_towards_uv, wind_from_uv
from jabuka.common.units import kn_to_ms
from jabuka.route.bias import BiasEstimator, BiasParams, BiasSample, bias_changed

T0 = 1_800_000_000.0
R = math.radians


def sample(t: float, **kw) -> BiasSample:
    base = dict(
        t=t,
        dt=1.0,
        source="LIVE",
        stale=False,
        twd_meas=R(210.0),
        tws_meas=kn_to_ms(12.0),
        twd_grib=R(200.0),
        tws_grib=kn_to_ms(10.0),
        bsp=kn_to_ms(6.0),
        cog=R(320.0),
        in_zone=False,
        last_tack_t=None,
        enabled=True,
        current_uv=None,
    )
    base.update(kw)
    return BiasSample(**base)


def feed(est: BiasEstimator, t_start: float, n: int, **kw) -> float:
    """n samples one second apart starting at t_start; returns the last sample time."""
    t = t_start
    for k in range(n):
        t = t_start + k
        est.update(sample(t, **kw))
    return t


def learned(n: int = 300, **kw) -> tuple[BiasEstimator, float]:
    est = BiasEstimator()
    return est, feed(est, T0, n, **kw)


# ---- application -----------------------------------------------------------------------


def test_rotation_is_clockwise_for_positive_offset() -> None:
    p = BiasParams(R(90.0), 1.0, T0)
    u, v = p.apply_uv(0.0, -1.0, T0)  # wind from 000
    d, s = wind_from_uv(u, v)
    assert math.degrees(d) == pytest.approx(90.0, abs=1e-9)
    assert s == pytest.approx(1.0, abs=1e-12)
    p2 = BiasParams(R(90.0), 1.2, T0)
    assert wind_from_uv(*p2.apply_uv(0.0, -1.0, T0))[1] == pytest.approx(1.2, abs=1e-12)


def test_decay_after_tau() -> None:
    p = BiasParams(R(90.0), 1.2, T0)
    phi, scale = p.weights(T0 + 9000.0)
    assert phi == pytest.approx(R(90.0) * math.exp(-1.0), abs=1e-12)
    assert scale == pytest.approx(1.0 + 0.2 * math.exp(-1.0), abs=1e-12)
    dir_deg, ratio = p.effective(T0 + 9000.0)
    assert dir_deg == pytest.approx(90.0 * math.exp(-1.0), abs=1e-9)
    assert ratio == pytest.approx(1.0 + 0.2 * math.exp(-1.0), abs=1e-12)
    assert p.weights(T0 - 100.0) == (pytest.approx(R(90.0)), pytest.approx(1.2))  # no growth


# ---- learning --------------------------------------------------------------------------


def test_valid_after_300_gated_seconds() -> None:
    est, t = learned(299)
    st = est.status(t)
    assert st["valid"] is False and st["state"] == "apprentissage"
    assert est.params(t) is None
    feed(est, t + 1.0, 1)
    st = est.status(t + 1.0)
    assert st["valid"] is True
    assert st["state"] == "actif"
    assert st["dir_deg"] == pytest.approx(10.0, abs=0.5)
    assert st["ratio"] == pytest.approx(1.2, abs=0.01)
    assert st["gated_s"] == pytest.approx(300.0)
    assert st["clamped"] is False
    assert st["reason"] is None
    p = est.params(t + 1.0)
    assert p is not None and p.t_obs == t + 1.0


def test_fresh_estimator_is_none() -> None:
    est = BiasEstimator()
    st = est.status(T0)
    assert st["state"] == "aucun" and st["valid"] is False and est.params(T0) is None


def test_circular_mean_across_north() -> None:
    est = BiasEstimator()
    for k in range(400):
        meas = 200.0 + (179.0 if k % 2 else -179.0)
        est.update(sample(T0 + k, twd_meas=R(meas)))
    d, _k = est.raw()
    assert abs(math.degrees(d)) == pytest.approx(180.0, abs=1.0)


GATES = [
    ({"source": "MANUEL"}, "source non mesurée"),
    ({"source": "NONE"}, "source non mesurée"),
    ({"stale": True}, "mesures périmées"),
    ({"bsp": kn_to_ms(1.9)}, "vitesse faible"),
    ({"tws_meas": kn_to_ms(3.9)}, "vent faible"),
    ({"tws_grib": kn_to_ms(3.9)}, "vent faible"),
    ({"twd_grib": None, "tws_grib": None}, "pas de GRIB"),
    ({"cog": None}, "COG absent"),
    ({"in_zone": True}, "gelé (Jabuka)"),
    ({"enabled": False}, "désactivé"),
]


@pytest.mark.parametrize(("closed", "reason"), GATES)
def test_each_gate_closes_and_ema_holds(closed: dict, reason: str) -> None:
    est, t = learned()
    before = est.raw()
    gated = est.status(t)["gated_s"]
    # very different wind while closed: must not leak into the estimate
    t2 = feed(est, t + 1.0, 60, **{"twd_meas": R(240.0), "tws_meas": kn_to_ms(20.0), **closed})
    st = est.status(t2)
    assert st["reason"] == reason
    assert est.raw() == before
    assert st["gated_s"] == gated


def test_recent_tack_gate() -> None:
    est, t = learned()
    gated = est.status(t)["gated_s"]
    est.update(sample(t + 1.0, last_tack_t=t + 1.0 - 179.0))
    assert est.status(t + 1.0)["reason"] == "virement récent"
    assert est.status(t + 1.0)["gated_s"] == gated
    est.update(sample(t + 2.0, last_tack_t=t + 2.0 - 181.0))
    assert est.status(t + 2.0)["reason"] is None
    assert est.status(t + 2.0)["gated_s"] == gated + 1.0


def test_turn_rate_gate() -> None:
    est, t = learned()
    cog0 = 320.0
    last = t
    for k in range(1, 35):  # 3.5 deg/s for 34 s
        last = t + k
        est.update(sample(last, cog=R(cog0 + 3.5 * k)))
    assert est.status(last)["reason"] == "virage"
    before = est.raw()
    for k in range(35, 45):
        last = t + k
        est.update(sample(last, cog=R(cog0 + 3.5 * k), twd_meas=R(240.0)))
    assert est.status(last)["reason"] == "virage"
    assert est.raw() == before
    # a slow turn (1 deg/s) keeps the gate open
    est2, t2 = learned()
    for k in range(1, 40):
        est2.update(sample(t2 + k, cog=R(cog0 + 1.0 * k)))
    assert est2.status(t2 + 39)["reason"] is None


def test_clamps() -> None:
    est, t = learned(twd_meas=R(250.0), tws_meas=kn_to_ms(20.0))  # +50 deg, x2.0
    p = est.params(t)
    assert p is not None
    assert math.degrees(p.d_dir_rad) == pytest.approx(35.0, abs=1e-9)
    assert p.k == pytest.approx(1.5, abs=1e-12)
    assert est.status(t)["clamped"] is True
    est2, t2 = learned(twd_meas=R(150.0), tws_meas=kn_to_ms(5.0))  # -50 deg, x0.5
    p2 = est2.params(t2)
    assert math.degrees(p2.d_dir_rad) == pytest.approx(-35.0, abs=1e-9)
    assert p2.k == pytest.approx(0.6, abs=1e-12)


def test_fading_when_gate_stays_closed() -> None:
    est, t = learned()
    t2 = feed(est, t + 1.0, 120, bsp=kn_to_ms(1.0))
    st = est.status(t2)
    assert st["state"] == "s'estompe"
    p = est.params(t2)
    assert p is not None and p.t_obs == t
    assert st["dir_deg"] < 10.0 and st["dir_deg"] == pytest.approx(p.effective(t2)[0])
    assert st["valid"] is True


def test_frozen_and_disabled_states() -> None:
    est, t = learned()
    est.update(sample(t + 1.0, in_zone=True))
    st = est.status(t + 1.0)
    assert st["state"] == "gelé (Jabuka)"
    assert est.params(t + 1.0) is not None  # frozen, still applied (fading)
    est.update(sample(t + 2.0, enabled=False))
    st = est.status(t + 2.0)
    assert st["state"] == "désactivé" and st["enabled"] is False
    assert est.params(t + 2.0) is None
    est.update(sample(t + 3.0))  # switched back on: the learned bias is still there
    assert est.params(t + 3.0) is not None


def test_water_to_ground_with_current() -> None:
    # B&G true wind is water-referenced: from 000 at 10 kn over a 1 kn current setting 090.
    # Ground air motion = (0, -10) + (1, 0) kn -> from 354.29 deg at sqrt(101) kn.
    est, t = learned(
        twd_meas=0.0,
        tws_meas=kn_to_ms(10.0),
        twd_grib=0.0,
        tws_grib=kn_to_ms(10.0),
        current_uv=current_towards_uv(R(90.0), kn_to_ms(1.0)),
    )
    st = est.status(t)
    assert st["dir_deg"] == pytest.approx(-math.degrees(math.atan2(1.0, 10.0)), abs=0.01)
    assert st["ratio"] == pytest.approx(math.sqrt(101.0) / 10.0, abs=1e-4)
    est2, t2 = learned(twd_meas=0.0, tws_meas=kn_to_ms(10.0), twd_grib=0.0, tws_grib=kn_to_ms(10.0))
    assert est2.status(t2)["ratio"] == pytest.approx(1.0, abs=1e-9)


def test_manual_observation_and_ema_takeover() -> None:
    est = BiasEstimator()
    est.observe_manual(T0, R(210.0), kn_to_ms(10.0), R(200.0), kn_to_ms(8.0))
    p = est.params(T0)
    assert p is not None
    assert math.degrees(p.d_dir_rad) == pytest.approx(10.0, abs=1e-9)
    assert p.k == pytest.approx(1.25, abs=1e-12)
    assert p.t_obs == T0
    assert est.status(T0)["valid"] is True
    # a later valid EMA (newer than the manual observation) takes over
    t = feed(est, T0 + 10.0, 300, twd_meas=R(220.0))
    p2 = est.params(t)
    assert math.degrees(p2.d_dir_rad) == pytest.approx(20.0, abs=0.5)
    assert p2.t_obs == t
    # clamped like the EMA
    est.observe_manual(t + 1.0, R(260.0), kn_to_ms(20.0), R(200.0), kn_to_ms(8.0))
    p3 = est.params(t + 1.0)
    assert math.degrees(p3.d_dir_rad) == pytest.approx(35.0, abs=1e-9)
    assert p3.k == pytest.approx(1.5, abs=1e-12)
    assert est.status(t + 1.0)["clamped"] is True


def test_json_round_trip() -> None:
    est, t = learned()
    est.observe_manual(T0 - 50.0, R(205.0), kn_to_ms(9.0), R(200.0), kn_to_ms(8.0))
    obj = json.loads(json.dumps(est.to_json()))
    back = BiasEstimator.from_json(obj)
    assert back.params(t + 60.0) == est.params(t + 60.0)
    assert back.raw() == est.raw()
    assert back.status(t + 60.0) == est.status(t + 60.0)
    est.reset()
    assert est.params(t) is None and est.status(t)["state"] == "aucun"
    with pytest.raises(ValueError):
        BiasEstimator.from_json({"version": 1, "S": "nope"})


def test_bias_changed() -> None:
    assert bias_changed((10.0, 1.2), (14.0, 1.25)) is False
    assert bias_changed((10.0, 1.2), (16.0, 1.2)) is True
    assert bias_changed((10.0, 1.2), (10.0, 1.31)) is True
    assert bias_changed(None, (0.0, 1.0)) is True
    assert bias_changed((0.0, 1.0), None) is True
    assert bias_changed(None, None) is False
    assert bias_changed((178.0, 1.0), (-178.0, 1.0)) is False  # wraps
