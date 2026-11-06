"""Local equirectangular frame shared by the land mask and the router."""

from __future__ import annotations

import math
import os

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.frame import DEFAULT_FRAME, NM_M, RACE_BBOX, Frame  # noqa: E402


def test_origin_and_scales() -> None:
    f = DEFAULT_FRAME
    assert f == Frame(lat0=43.4, lon0=15.65)
    x, y = f.to_xy(43.4, 15.65)
    assert isinstance(x, float) and isinstance(y, float)
    assert (x, y) == (0.0, 0.0)
    _, y1 = f.to_xy(43.4 + 1 / 60, 15.65)
    assert y1 == pytest.approx(1.0, abs=1e-12)
    x1, _ = f.to_xy(43.4, 15.65 + 1 / 60)
    assert x1 == pytest.approx(math.cos(math.radians(43.4)), abs=1e-12)


def test_round_trip_scalar_and_array() -> None:
    f = DEFAULT_FRAME
    lat, lon = f.to_ll(*f.to_xy(43.75, 15.78))
    assert lat == pytest.approx(43.75, abs=1e-9) and lon == pytest.approx(15.78, abs=1e-9)
    lats = np.linspace(RACE_BBOX[1], RACE_BBOX[3], 7)
    lons = np.linspace(RACE_BBOX[0], RACE_BBOX[2], 7)
    x, y = f.to_xy(lats, lons)
    assert isinstance(x, np.ndarray) and x.shape == (7,)
    la2, lo2 = f.to_ll(x, y)
    assert np.max(np.abs(la2 - lats)) < 1e-9 and np.max(np.abs(lo2 - lons)) < 1e-9


def test_metres_helpers() -> None:
    f = DEFAULT_FRAME
    xm, ym = f.to_m(43.4 + 1 / 60, 15.65)
    assert ym == pytest.approx(NM_M) and xm == pytest.approx(0.0)
    lat, lon = f.from_m(*f.to_m(43.1, 15.2))
    assert lat == pytest.approx(43.1, abs=1e-9) and lon == pytest.approx(15.2, abs=1e-9)
