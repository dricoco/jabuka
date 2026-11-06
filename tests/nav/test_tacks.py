"""Sailed tacking angles (RESEARCH Pattern 5): a tack/gybe is a damped-TWA sign change held 30 s; a
settled run (>= 120 s) records theta = COG - TWD (ground angle, so it already holds leeway and
current) and the mean SOG; the median of the last 3 per side is used; nothing is learnt inside the
Jabuka zone."""

from __future__ import annotations

import math

import pytest

from jabuka.nav.tacks import TackSample, TackTracker

R = math.radians
TWD = 20.0


class Feed:
    def __init__(self) -> None:
        self.tr = TackTracker()
        self.t = 0.0

    def run(self, seconds: int, theta: float, twa: float, sog: float = 6.0, in_zone=False):
        for _ in range(seconds):
            self.tr.update(self.t, R(twa), R((TWD + theta) % 360.0), R(TWD), sog, in_zone)
            self.t += 1.0


def test_medians_of_the_last_three_settled_tacks() -> None:
    f = Feed()
    for st, po in ((-48.0, 47.0), (-50.0, 49.0), (-52.0, 51.0)):
        f.run(130, st, 45.0, sog=5.5)
        f.run(130, po, -45.0, sog=5.9)
    ang = f.tr.angles()
    assert ang["up"]["stbd"].theta_deg == pytest.approx(-50.0, abs=0.05)
    assert ang["up"]["port"].theta_deg == pytest.approx(49.0, abs=0.05)
    assert ang["up"]["stbd"].sog_kn == pytest.approx(5.5)
    assert ang["up"]["port"].sog_kn == pytest.approx(5.9)
    assert ang["down"] == {"stbd": None, "port": None}
    assert [round(x, 1) for x in f.tr.samples("up", "stbd")] == [-48.0, -50.0, -52.0]


def test_keeps_only_the_last_three() -> None:
    f = Feed()
    for st in (-40.0, -48.0, -50.0, -52.0):
        f.run(130, st, 45.0)
        f.run(130, 47.0, -45.0)
    assert [round(x, 1) for x in f.tr.samples("up", "stbd")] == [-48.0, -50.0, -52.0]


def test_short_sign_flip_is_ignored() -> None:
    f = Feed()
    f.run(100, -50.0, 45.0)
    f.run(20, 49.0, -45.0)  # 20 s on the other side: not a tack
    f.run(100, -50.0, 45.0)
    ang = f.tr.angles()
    assert ang["up"]["port"] is None
    assert ang["up"]["stbd"].theta_deg == pytest.approx(-50.0, abs=0.05)
    assert len(f.tr.samples("up", "stbd")) == 1


def test_unsettled_run_is_not_recorded() -> None:
    f = Feed()
    f.run(100, -50.0, 45.0)
    assert f.tr.angles()["up"]["stbd"] is None


def test_nothing_learnt_inside_the_zone() -> None:
    f = Feed()
    f.run(130, -50.0, 45.0, in_zone=True)
    f.run(130, 49.0, -45.0, in_zone=True)
    assert f.tr.angles()["up"] == {"stbd": None, "port": None}


def test_downwind_gybes_are_their_own_samples() -> None:
    f = Feed()
    f.run(130, -150.0, 150.0)
    f.run(130, 152.0, -150.0)
    ang = f.tr.angles()
    assert ang["down"]["stbd"].theta_deg == pytest.approx(-150.0, abs=0.05)
    assert ang["down"]["port"].theta_deg == pytest.approx(152.0, abs=0.05)
    assert ang["up"] == {"stbd": None, "port": None}


def test_wrap_safe_means() -> None:
    f = Feed()
    # TWD 20, theta -30 -> COG 350: the circular means do not average through 180
    f.run(130, -30.0, 45.0)
    assert f.tr.angles()["up"]["stbd"].theta_deg == pytest.approx(-30.0, abs=0.05)


def test_reaching_and_missing_inputs_are_not_learnt() -> None:
    tr = TackTracker()
    for k in range(200):
        tr.update(float(k), R(90.0), R(110.0), R(TWD), 7.0, False)  # reach
        tr.update(float(k) + 0.5, None, None, None, None, False)
    assert tr.angles()["up"]["stbd"] is None and tr.angles()["down"]["stbd"] is None


def test_sample_type() -> None:
    s = TackSample(-50.0, 6.0)
    assert s.theta_deg == -50.0 and s.sog_kn == 6.0
