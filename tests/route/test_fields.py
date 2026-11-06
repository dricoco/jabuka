"""WindField / WaveField / CurrentField: time + bilinear interpolation, bias, edges, horizon."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.common.conventions import wind_from_uv  # noqa: E402
from jabuka.route.bias import BiasParams  # noqa: E402
from jabuka.route.fields import MS_TO_KN, WindField, hs_from_tws  # noqa: E402
from jabuka.route.frame import DEFAULT_FRAME  # noqa: E402
from jabuka.route.racepack import Grid  # noqa: E402

T0 = 1_800_000_000


def _two_step_grid() -> Grid:
    """2 times x 2 lat x 3 lon. u varies in time and longitude, v in latitude."""
    lat = np.array([43.0, 44.0])
    lon = np.array([15.0, 15.5, 16.0])
    t = np.array([T0, T0 + 3600], dtype=np.int64)
    u = np.zeros((2, 2, 3), np.float32)
    v = np.zeros((2, 2, 3), np.float32)
    u[0] = [[0.0, 2.0, 4.0], [0.0, 2.0, 4.0]]
    u[1] = u[0] + 6.0
    v[:, 0, :] = -2.0
    v[:, 1, :] = -6.0
    return Grid(t, lat, lon, {"u": u, "v": v})


def _uv_kn(wf: WindField, t, lat, lon, bias=None):
    twd, tws = wf.at(t, lat, lon, bias)
    return -tws * math.sin(twd), -tws * math.cos(twd)


def test_time_linear_and_space_bilinear() -> None:
    wf = WindField(_two_step_grid(), DEFAULT_FRAME)
    # half-way in time, in the middle of the first cell (lat 43.5, lon 15.25)
    u, v = _uv_kn(wf, T0 + 1800, 43.5, 15.25)
    assert u == pytest.approx((1.0 + 3.0) * MS_TO_KN, rel=1e-6)  # (1 at t0, 7 at t1) / 2
    assert v == pytest.approx(-4.0 * MS_TO_KN, rel=1e-6)
    # exactly on a node at the second time
    u, v = _uv_kn(wf, T0 + 3600, 44.0, 16.0)
    assert u == pytest.approx(10.0 * MS_TO_KN, rel=1e-6)
    assert v == pytest.approx(-6.0 * MS_TO_KN, rel=1e-6)


def test_direction_matches_conventions() -> None:
    wf = WindField(_two_step_grid(), DEFAULT_FRAME)
    for lat, lon in ((43.2, 15.1), (43.9, 15.9), (43.5, 15.5)):
        twd, tws = wf.at(T0 + 600, lat, lon)
        u, v = (c / MS_TO_KN for c in _uv_kn(wf, T0 + 600, lat, lon))
        d, s = wind_from_uv(u, v)
        assert twd == pytest.approx(d, abs=1e-9)
        assert tws == pytest.approx(s * MS_TO_KN, rel=1e-9)
    # vectorised sample agrees with the scalar
    x, y = DEFAULT_FRAME.to_xy(np.array([43.2, 43.9]), np.array([15.1, 15.9]))
    twd_v, tws_v = wf.sample(T0 + 600, x, y)
    twd0, tws0 = wf.at(T0 + 600, 43.2, 15.1)
    assert twd_v[0] == pytest.approx(twd0) and tws_v[0] == pytest.approx(tws0)


def test_bias_rotates_and_scales() -> None:
    wf = WindField(_two_step_grid(), DEFAULT_FRAME)
    bias = BiasParams(math.radians(10.0), 1.1, T0 + 900)
    d0, s0 = wf.at(T0 + 900, 43.5, 15.6)
    d1, s1 = wf.at(T0 + 900, 43.5, 15.6, bias)
    assert math.degrees((d1 - d0) % (2 * math.pi)) == pytest.approx(10.0, abs=1e-6)
    assert s1 == pytest.approx(1.1 * s0, rel=1e-9)
    # decays with time after the observation
    d2, s2 = wf.at(T0 + 900 + 9000, 43.5, 15.6, bias)
    d2r, s2r = wf.at(T0 + 900 + 9000, 43.5, 15.6)
    w = math.exp(-1.0)
    assert math.degrees((d2 - d2r) % (2 * math.pi)) == pytest.approx(10.0 * w, abs=1e-6)
    assert s2 / s2r == pytest.approx(1 + w * 0.1, rel=1e-9)


def test_edges_held_and_horizon() -> None:
    wf = WindField(_two_step_grid(), DEFAULT_FRAME)
    # outside the grid: nearest edge cell
    assert wf.at(T0, 42.0, 14.0) == pytest.approx(wf.at(T0, 43.0, 15.0))
    assert wf.at(T0, 45.0, 17.0) == pytest.approx(wf.at(T0, 44.0, 16.0))
    # before the first / after the last time: held
    assert wf.at(T0 - 7200, 43.5, 15.5) == pytest.approx(wf.at(T0, 43.5, 15.5))
    assert wf.at(T0 + 99999, 43.5, 15.5) == pytest.approx(wf.at(T0 + 3600, 43.5, 15.5))
    assert not wf.horizon_hold(T0 + 3600)
    assert wf.horizon_hold(T0 + 3601)
    assert wf.t_first == T0 and wf.t_last == T0 + 3600


def test_hs_from_tws_table() -> None:
    assert float(hs_from_tws(5)) == pytest.approx(0.1)
    assert float(hs_from_tws(12.5)) == pytest.approx(0.6)
    assert float(hs_from_tws(30)) == pytest.approx(2.8)
    assert float(hs_from_tws(45)) == pytest.approx(2.8)


def test_sample_wind_is_real(sample_wind) -> None:
    wf = WindField(sample_wind, DEFAULT_FRAME)
    twd, tws = wf.at(float(sample_wind.t[3]), 43.6, 15.6)
    assert 0.0 <= twd < 2 * math.pi and 0.0 <= tws < 40.0


def test_nan_stencil_is_no_wind_not_a_calm() -> None:
    """03-REVIEW MD-01: a wind cell without a value never becomes 0 kn from 180."""
    g = _two_step_grid()
    g.arrays["u"][:, :, 0] = np.nan  # west column without a value
    wf = WindField(g, DEFAULT_FRAME)
    twd, tws = wf.at(T0, 43.5, 15.2)  # stencil touches the NaN column
    assert math.isnan(twd) and math.isnan(tws)
    twd, tws = wf.at(T0, 43.5, 15.75)  # clear of it
    assert math.isfinite(twd) and tws > 0.0
