"""Reroute triggers, replacement hysteresis, off-route watch and the stay-on-tack state."""

from __future__ import annotations

import pytest

from jabuka.route.advice import (
    Follow,
    OffRouteWatch,
    StayOnTack,
    TackEvent,
    Trigger,
    TriggerInputs,
    Triggers,
    should_replace,
)

T0 = 1_800_000_000.0


def inputs(**kw) -> TriggerInputs:
    base = dict(
        course_version=1,
        bias_eff=(10.0, 1.2),
        manual_version=0,
        off_route=False,
        stay_version=0,
        missed=False,
        pack_version=1,
        has_route=True,
    )
    base.update(kw)
    return TriggerInputs(**base)


def reasons(trigs: list[Trigger]) -> dict[str, bool]:
    return {t.reason: t.forced for t in trigs}


def requested(now: float = T0, **kw) -> tuple[Triggers, TriggerInputs]:
    tr = Triggers()
    inp = inputs(**kw)
    tr.mark_requested(now, inp)
    return tr, inp


# ---- triggers ---------------------------------------------------------------------------


def test_first_when_no_route() -> None:
    tr = Triggers()
    assert reasons(tr.check(T0, inputs(has_route=False))) == {"first": False}
    tr.mark_requested(T0, inputs(has_route=False))
    assert tr.check(T0 + 1.0, inputs(has_route=False)) == []


def test_timer_cadence() -> None:
    tr, inp = requested()
    assert tr.check(T0 + 299.0, inp) == []
    assert reasons(tr.check(T0 + 300.0, inp)) == {"timer": False}
    tr.mark_requested(T0 + 300.0, inp)
    assert tr.check(T0 + 301.0, inp) == []


@pytest.mark.parametrize(
    ("change", "reason", "forced"),
    [
        ({"course_version": 2}, "course", True),
        ({"bias_eff": (16.0, 1.2)}, "bias", False),
        ({"bias_eff": None}, "bias", False),
        ({"manual_version": 1}, "manual", False),
        ({"off_route": True}, "off_route", False),
        ({"stay_version": 1}, "stay", True),
        ({"missed": True}, "missed", True),
        ({"pack_version": 2}, "pack", True),
    ],
)
def test_each_trigger_and_quiet_after_request(change: dict, reason: str, forced: bool) -> None:
    tr, inp = requested()
    assert tr.check(T0 + 10.0, inp) == []
    changed = inputs(**change)
    assert reasons(tr.check(T0 + 20.0, changed)) == {reason: forced}
    tr.mark_requested(T0 + 20.0, changed)
    assert tr.check(T0 + 21.0, changed) == []  # nothing until the next change


def test_small_bias_change_does_not_fire() -> None:
    tr, _ = requested()
    assert tr.check(T0 + 5.0, inputs(bias_eff=(14.0, 1.25))) == []


def test_off_route_fires_until_requested_then_on_next_rise() -> None:
    tr, inp = requested()
    on = inputs(off_route=True)
    assert reasons(tr.check(T0 + 1.0, on)) == {"off_route": False}
    assert reasons(tr.check(T0 + 2.0, on)) == {"off_route": False}  # not requested yet
    tr.mark_requested(T0 + 2.0, on)
    assert tr.check(T0 + 3.0, on) == []
    assert tr.check(T0 + 4.0, inp) == []
    assert reasons(tr.check(T0 + 5.0, on)) == {"off_route": False}


def test_missed_edges_fire_each_time() -> None:
    tr, inp = requested()
    for k in range(2):
        t = T0 + 10.0 * (k + 1)
        assert reasons(tr.check(t, inputs(missed=True))) == {"missed": True}
        tr.mark_requested(t, inputs(missed=True))
        assert tr.check(t + 1.0, inp) == []


def test_several_reasons_at_once() -> None:
    tr, _ = requested()
    got = reasons(tr.check(T0 + 400.0, inputs(course_version=5, manual_version=3)))
    assert got == {"timer": False, "course": True, "manual": False}


# ---- hysteresis -------------------------------------------------------------------------


def test_should_replace() -> None:
    now = T0
    h5 = now + 5 * 3600.0
    h10 = now + 10 * 3600.0
    assert should_replace(h5, now, h5, True, 60.0, False) == (False, "kept")
    assert should_replace(h5, now, h5 + 120.0, True, 60.0, False) == (False, "kept")
    assert should_replace(h5, now, h5 + 240.0, True, 60.0, False) == (True, "gain")
    assert should_replace(h10, now, h10 + 150.0, True, 60.0, False) == (False, "kept")
    assert should_replace(h10, now, h10 + 420.0, True, 60.0, False) == (True, "gain")
    assert should_replace(h5, now, h5, False, 60.0, False) == (True, "invalid")
    assert should_replace(h5, now, h5, True, 1201.0, False) == (True, "outdated")
    assert should_replace(h5, now, h5, True, 1200.0, False) == (False, "kept")
    assert should_replace(h5, now, h5 - 600.0, True, 60.0, True) == (True, "forced")
    assert should_replace(h5, now, None, False, None, False) == (True, "no_route")


# ---- off-route --------------------------------------------------------------------------


def follow(xte: float = 0.0, dev: float | None = 0.0) -> Follow:
    return Follow(
        idx=0,
        t_route_here=T0,
        xte_nm=xte,
        seg_course_deg=320.0,
        course_dev_deg=dev,
        target_twa=40.0,
        target_tack=1,
        target_hdg_t=320.0,
        next_tack=None,
        countdown_s=None,
        eta_now=T0 + 3600.0,
        remaining_s=3600.0,
        finished=False,
    )


def test_off_route_xte_sustained() -> None:
    w = OffRouteWatch()
    assert not w.update(T0, follow(xte=0.6))
    assert not w.update(T0 + 119.0, follow(xte=0.6))
    assert w.update(T0 + 121.0, follow(xte=0.6))


def test_off_route_course_deviation_sustained() -> None:
    w = OffRouteWatch()
    assert not w.update(T0, follow(dev=25.0))
    assert w.update(T0 + 121.0, follow(dev=25.0))
    w2 = OffRouteWatch()
    assert not w2.update(T0, follow(dev=None))
    assert not w2.update(T0 + 500.0, follow(dev=None))


def test_off_route_return_resets_timer() -> None:
    w = OffRouteWatch()
    w.update(T0, follow(xte=0.6))
    w.update(T0 + 100.0, follow(xte=0.6))
    assert not w.update(T0 + 100.0, follow(xte=0.1))
    assert not w.update(T0 + 110.0, follow(xte=0.1))
    assert not w.update(T0 + 111.0, follow(xte=0.6))
    assert not w.update(T0 + 200.0, follow(xte=0.6))
    assert w.update(T0 + 232.0, follow(xte=0.6))
    w.reset()
    assert not w.update(T0 + 233.0, follow(xte=0.6))


# ---- stay on tack -----------------------------------------------------------------------


def test_stay_on_tack_lifecycle() -> None:
    s = StayOnTack()
    assert not s.active and s.to_dict() == {"active": False, "tack": None, "since": None}
    v0 = s.version
    s.activate(T0, -1)
    assert s.active and s.tack == -1 and s.since == T0
    assert s.to_dict() == {"active": True, "tack": -1, "since": T0}
    assert s.version == v0 + 1
    s.on_tack(TackEvent(T0 + 60.0, 1, "tack"))
    assert not s.active and s.version == v0 + 2
    s.activate(T0 + 100.0, 1)
    s.cancel()
    assert not s.active and s.tack is None and s.since is None
    v = s.version
    s.cancel()  # no-op when inactive
    s.on_tack(TackEvent(T0 + 200.0, -1, "tack"))
    assert s.version == v
