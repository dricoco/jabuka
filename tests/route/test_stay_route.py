"""The "On reste" display route (quick-261110-iil, D-01..D-06): the forced current leg followed
by the same cycle's optimal route from the active mark onward, shifted by the forced delay.

Synthetic routes build every case by hand (no numpy needed); one test runs the real router on
a two-mark beat (skipped without numpy, like test_forced_cost.py)."""

from __future__ import annotations

import dataclasses
import math
import os

import pytest

from jabuka.route.advice import RouteFollower
from jabuka.route.stay import JOIN_TOL_NM, stay_route
from jabuka.route.types import LegResult, PathPoint, RouteResult, TackPoint

T0 = 1793923200.0
A = (43.30, 15.30)  # start
B = (43.35, 15.25)  # forced tack point
C = (43.33, 15.33)  # optimal tack point
M = (43.40, 15.30)  # active mark
D = (43.42, 15.36)  # tack on the next leg
E = (43.45, 15.42)  # second mark
F = (43.48, 15.40)  # finish


def _pp(t: float, p: tuple[float, float], twa: float) -> PathPoint:
    return PathPoint(T0 + t, p[0], p[1], twa, 1 if twa > 0 else -1, 6.0, 0.0, 12.0)


def _tk(t: float, p: tuple[float, float], frm: int, to: int, kind: str = "tack") -> TackPoint:
    return TackPoint(T0 + t, p[0], p[1], frm, to, kind)


def _forced(eta_s: float = 3900.0) -> RouteResult:
    """Held on starboard until 1800 s, then port to the mark (arrival = copy of the last
    sailed segment, as isochrone._route ships a leg_only route)."""
    path = (_pp(0.0, A, 45.0), _pp(1800.0, B, -45.0), _pp(eta_s, M, -45.0))
    tacks = (_tk(1800.0, B, 1, -1),)
    return RouteResult(
        ok=True,
        reason=None,
        request_id="r",
        t0=T0,
        path=path,
        tacks=tacks,
        legs=(LegResult("m", T0 + eta_s, *M),),
        eta=T0 + eta_s,
        valid=True,
        force_released_at=T0 + 1234.0,
        notes=("on_reste",),
        level="L1",
    )


def _optimal(leave_twa: float = -50.0) -> RouteResult:
    """Tack at C (port -> stbd), mark M at 3600 s leaving on ``leave_twa``, tack at D, mark n at
    E, finish p at F (3 legs)."""
    leave_tack = 1 if leave_twa > 0 else -1
    after = -leave_twa
    path = (
        _pp(0.0, A, -45.0),
        _pp(1200.0, C, 45.0),
        _pp(3600.0, M, leave_twa),
        _pp(4800.0, D, after),
        _pp(6000.0, E, after),
        _pp(7200.0, F, after),
    )
    tacks = [_tk(0.0, A, 1, -1), _tk(1200.0, C, -1, 1)]
    if leave_tack != 1:
        tacks.append(_tk(3600.0, M, 1, leave_tack, "gybe" if abs(leave_twa) >= 90 else "tack"))
    tacks.append(_tk(4800.0, D, leave_tack, -leave_tack, "gybe" if abs(after) >= 90 else "tack"))
    return RouteResult(
        ok=True,
        reason=None,
        request_id="r",
        t0=T0,
        path=path,
        tacks=tuple(tacks),
        legs=(
            LegResult("m", T0 + 3600.0, *M),
            LegResult("n", T0 + 6000.0, *E),
            LegResult("p", T0 + 7200.0, *F),
        ),
        eta=T0 + 7200.0,
        valid=True,
        horizon_hold=True,
        level="L0",
    )


def _non_decreasing(path) -> bool:
    return all(b.t >= a.t for a, b in zip(path, path[1:], strict=False))


# -- composition (D-01, D-02) ---------------------------------------------------------------------
def test_composition_appends_the_shifted_optimal_continuation() -> None:
    f, o = _forced(), _optimal()
    s = stay_route(f, o)
    delta = f.legs[0].eta - o.legs[0].eta
    assert delta == pytest.approx(300.0)
    j = 2  # optimal point at the active mark
    junction = s.path[len(f.path) - 1]
    assert s.path[: len(f.path) - 1] == f.path[:-1]
    assert (junction.t, junction.lat, junction.lon) == (f.path[-1].t, *f.path[-1][1:3])
    assert (junction.twa_deg, junction.tack, junction.bsp_kn) == (
        o.path[j].twa_deg,
        o.path[j].tack,
        o.path[j].bsp_kn,
    )
    tail = s.path[len(f.path) :]
    assert tail == tuple(p._replace(t=p.t + delta) for p in o.path[j + 1 :])
    assert _non_decreasing(s.path)
    assert s.legs[0] is f.legs[0]
    assert [lg.mark_id for lg in s.legs] == ["m", "n", "p"]
    assert [lg.eta for lg in s.legs[1:]] == [lg.eta + delta for lg in o.legs[1:]]
    assert s.eta == pytest.approx(o.eta + delta) and s.eta == s.path[-1].t
    assert s.tacks[: len(f.tacks)] == f.tacks
    later = tuple(tk._replace(t=tk.t + delta) for tk in o.tacks if tk.t > o.legs[0].eta)
    assert s.tacks[len(f.tacks) :] == later
    # everything else is the forced route's (D-03: the forced route itself is unchanged)
    assert (s.request_id, s.t0, s.level, s.notes) == (f.request_id, f.t0, f.level, f.notes)
    assert s.force_released_at == f.force_released_at
    assert s.valid and s.horizon_hold  # forced or optimal at the GRIB horizon
    assert f.legs == (LegResult("m", T0 + 3900.0, *M),) and len(f.path) == 3


@pytest.mark.parametrize(
    ("leave_twa", "kind"), [(50.0, "tack"), (120.0, "gybe"), (-50.0, None), (-130.0, None)]
)
def test_junction_tack_when_the_next_leg_leaves_on_the_other_side(leave_twa, kind) -> None:
    """The forced boat arrives on port: a next leg leaving on starboard needs a tack (or a
    gybe) at the mark; leaving on port needs none."""
    f, o = _forced(), _optimal(leave_twa)
    s = stay_route(f, o)
    at_mark = [tk for tk in s.tacks if tk.t == f.legs[0].eta]
    if kind is None:
        assert at_mark == []
    else:
        assert at_mark == [TackPoint(f.path[-1].t, *M, -1, 1, kind)]
    # the tack after the mark is still there, shifted
    assert s.tacks[-1].t == pytest.approx(T0 + 4800.0 + 300.0)


def test_negative_delta_stays_continuous() -> None:
    """The forced boat reaches the mark first: the continuation moves earlier (not clamped)."""
    f, o = _forced(eta_s=3300.0), _optimal()
    s = stay_route(f, o)
    assert s is not f
    assert s.eta == pytest.approx(o.eta - 300.0) == s.path[-1].t
    assert _non_decreasing(s.path)
    assert s.legs[1].eta == pytest.approx(o.legs[1].eta - 300.0)


# -- fallbacks (D-06) -----------------------------------------------------------------------------
def _drop_mark_point(o: RouteResult) -> RouteResult:
    return dataclasses.replace(o, path=o.path[:2] + o.path[3:])


def _shift_mark_point(o: RouteResult) -> RouteResult:
    p = list(o.path)
    p[2] = p[2]._replace(t=p[2].t + 5.0)
    return dataclasses.replace(o, path=tuple(p))


def _far_arrival(f: RouteResult) -> RouteResult:
    p = list(f.path)
    p[-1] = p[-1]._replace(lat=p[-1].lat + 0.5 / 60.0)
    return dataclasses.replace(f, path=tuple(p))


FALLBACKS = {
    "optimal_single_leg": lambda f, o: (f, dataclasses.replace(o, legs=o.legs[:1])),
    "mark_id_mismatch": lambda f, o: (
        dataclasses.replace(f, legs=(f.legs[0]._replace(mark_id="x"),)),
        o,
    ),
    "no_point_at_mark_eta": lambda f, o: (f, _drop_mark_point(o)),
    "point_5s_off": lambda f, o: (f, _shift_mark_point(o)),
    "mark_point_is_last": lambda f, o: (f, dataclasses.replace(o, path=o.path[:3])),
    "junction_far": lambda f, o: (_far_arrival(f), o),
    "optimal_not_ok": lambda f, o: (f, dataclasses.replace(o, ok=False)),
    "forced_not_ok": lambda f, o: (dataclasses.replace(f, ok=False), o),
    "forced_eta_none": lambda f, o: (dataclasses.replace(f, eta=None), o),
    "optimal_eta_nan": lambda f, o: (f, dataclasses.replace(o, eta=math.nan)),
    "optimal_empty_path": lambda f, o: (f, dataclasses.replace(o, path=())),
    "forced_no_legs": lambda f, o: (dataclasses.replace(f, legs=()), o),
}


@pytest.mark.parametrize("case", sorted(FALLBACKS))
def test_fallback_returns_the_forced_route(case) -> None:
    f, o = FALLBACKS[case](_forced(), _optimal())
    assert stay_route(f, o) is f


def test_junction_tolerance_constant() -> None:
    assert JOIN_TOL_NM == pytest.approx(0.1)


# -- helm advice on the current leg (D-05) --------------------------------------------------------
def _cog(a: PathPoint, b: PathPoint) -> float:
    dlat = b.lat - a.lat
    dlon = (b.lon - a.lon) * math.cos(math.radians(0.5 * (a.lat + b.lat)))
    return math.degrees(math.atan2(dlon, dlat)) % 360.0


FIELDS = ("idx", "xte_nm", "course_dev_deg", "target_twa", "target_tack")


def _check_advice_invariance(forced: RouteResult, composed: RouteResult) -> int:
    """Feed both followers the same boat at the midpoint of every forced segment (the arrival
    point has none). Target, XTE, course deviation and segment index are identical everywhere;
    next tack and countdown are identical while the forced leg still has a tack ahead.

    The one intended change: once the forced leg has no tack left, the composed route's
    countdown points at the first tack after the mark (exactly what an optimal multi-leg route
    does) instead of none. Returns the number of compared positions."""
    fol_f = RouteFollower(forced.path, forced.tacks, legs=[forced.legs[0].eta])
    fol_c = RouteFollower(composed.path, composed.tacks, legs=[lg.eta for lg in composed.legs])
    after_mark = [tk for tk in composed.tacks if tk.t >= forced.legs[0].eta]
    n = 0
    for a, b in zip(forced.path[:-1], forced.path[1:], strict=True):
        if b.t - a.t < 1.0:
            continue
        t = 0.5 * (a.t + b.t)
        lat, lon = 0.5 * (a.lat + b.lat), 0.5 * (a.lon + b.lon)
        cog = _cog(a, b)
        x = fol_f.follow(t, lat, lon, cog, a.twd_deg)
        y = fol_c.follow(t, lat, lon, cog, a.twd_deg)
        for name in FIELDS:
            assert getattr(x, name) == getattr(y, name), (name, t, x, y)
        if x.next_tack is not None:
            assert tuple(x.next_tack) == tuple(y.next_tack), (t, x, y)
            assert x.countdown_s == y.countdown_s
        elif after_mark:
            assert tuple(y.next_tack) == tuple(after_mark[0])
        n += 1
    return n


def test_current_leg_advice_is_the_forced_legs() -> None:
    f = _forced()
    for o in (_optimal(), _optimal(50.0)):
        s = stay_route(f, o)
        assert s is not f
        assert _check_advice_invariance(f, s) == 2
        # next tack = the forced leg's first tack
        fol = RouteFollower(s.path, s.tacks, legs=[lg.eta for lg in s.legs])
        first = fol.follow(T0 + 10.0, *A, _cog(f.path[0], f.path[1]), 0.0)
        assert tuple(first.next_tack) == tuple(f.tacks[0])
        assert first.countdown_s == pytest.approx(1800.0, abs=1.0)  # boat at A: route time t0


# -- one real-router round ------------------------------------------------------------------------
OPEN = (43.25, 15.20)


def _offset(p, bearing_deg: float, nm: float):
    lat = p[0] + nm * math.cos(math.radians(bearing_deg)) / 60.0
    lon = p[1] + nm * math.sin(math.radians(bearing_deg)) / (60.0 * math.cos(math.radians(p[0])))
    return lat, lon


def test_real_router_two_marks(env_factory, uniform_wind, make_request, mark_point) -> None:
    if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
        import numpy  # noqa: F401
    else:  # Phase 2 worktrees without numpy skip instead of failing
        pytest.importorskip("numpy")
    from jabuka.route.cycle import cycle_with_env
    from jabuka.route.types import CycleRequest, RouterSettings

    env = env_factory(uniform_wind(0.0, 12.0))
    a = _offset(OPEN, 30.0, 8.0)
    b = _offset(a, 100.0, 5.0)
    marks = [mark_point(*a, "A"), mark_point(*b, "B")]
    req = make_request(*OPEN, marks, tack0=1, settings=RouterSettings(use_waves=False))
    res = cycle_with_env(env, CycleRequest(req, stay_active=True))
    opt, f = res.optimal, res.forced
    assert opt.ok and f is not None and f.ok, (opt.reason, f)
    assert len(f.legs) == 1 and len(opt.legs) == 2  # D-03: the forced route is the leg only
    s = stay_route(f, opt)
    assert s is not f
    delta = f.legs[0].eta - opt.legs[0].eta
    assert [lg.mark_id for lg in s.legs] == ["a", "b"]
    assert s.legs[0] == f.legs[0]
    assert s.eta == pytest.approx(opt.eta + delta)
    if delta >= 0.0:
        assert s.eta - opt.eta == pytest.approx(res.cost_s)
    assert _non_decreasing(s.path)
    assert (s.path[-1].lat, s.path[-1].lon) == (opt.path[-1].lat, opt.path[-1].lon)
    assert s.tacks[: len(f.tacks)] == f.tacks
    assert _check_advice_invariance(f, s) >= 1
