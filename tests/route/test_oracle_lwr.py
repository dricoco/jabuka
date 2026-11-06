"""Optional oracle: an open-water leg agrees with libweatherrouting (``weatherrouting``).

The package is NOT installed by any plan: the dependency legitimacy audit flagged it [SUS]
(RESEARCH, threat T-03-03-SC). The owner may install it after review; until then this module
skips. lwr stops "near" the target (gap up to ~1 nm, ETA quantised to its step), so its arrival
gap is converted to time at the polar speed before comparing (RESEARCH "Benchmark accuracy").
"""

from __future__ import annotations

import datetime as dt
import math
import os

import pytest

wr = pytest.importorskip("weatherrouting")

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:
    np = pytest.importorskip("numpy")

from jabuka.route.isochrone import route  # noqa: E402
from jabuka.route.polar_grid import PolarGrid  # noqa: E402

T0 = 1793923200.0
START = (43.25, 15.20)
TARGET = (43.25 + 8.0 / 60.0, 15.20 + 4.0 / (60.0 * math.cos(math.radians(43.3))))


def _lwr_polar(polar_curves, tmp_path):
    """Write the curves as a lwr .pol grid (TWA rows x TWS columns) and load it."""
    tws = [t for t, _ in polar_curves]
    pg = PolarGrid.from_curves(polar_curves)
    lines = ["TWA\\TWS\t" + "\t".join(f"{t:g}" for t in tws)]
    for twa in range(30, 181, 5):
        lines.append(f"{twa}\t" + "\t".join(f"{float(pg.speed(t, twa)):.2f}" for t in tws))
    path = tmp_path / "x35.pol"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    polar_cls = getattr(wr, "Polar", None)
    if polar_cls is None:
        pytest.skip("weatherrouting API without Polar")
    return polar_cls(str(path))


def test_open_water_leg_agrees_with_lwr(
    env_factory, uniform_wind, make_request, mark_point, polar_curves, tmp_path
) -> None:
    ours = route(make_request(*START, [mark_point(*TARGET)]), env_factory(uniform_wind(0.0, 12.0)))
    assert ours.ok, ours.reason
    ours_h = (ours.eta - T0) / 3600.0

    polar = _lwr_polar(polar_curves, tmp_path)
    routing_cls = getattr(wr, "Routing", None)
    algo = getattr(getattr(wr, "routers", None), "LinearBestIsoRouter", None)
    if routing_cls is None or algo is None:
        pytest.skip("weatherrouting API without Routing/LinearBestIsoRouter")

    def wind(_t, _lat, _lon):  # (TWD deg, TWS kn): 12 kn from the north everywhere
        return (0.0, 12.0)

    start_time = dt.datetime.fromtimestamp(T0, dt.UTC).replace(tzinfo=None)
    r = routing_cls(algo, polar, [START, TARGET], wind, start_time)
    last = None
    for _ in range(500):
        res = r.step()
        last = res
        if getattr(r, "end", False):
            break
    assert last is not None
    pos = last.position
    gap = math.hypot(
        (pos[0] - TARGET[0]) * 60.0, (pos[1] - TARGET[1]) * 60.0 * math.cos(math.radians(43.3))
    )
    lwr_h = (last.time - start_time).total_seconds() / 3600.0
    vmg = float(PolarGrid.from_curves(polar_curves).vmg_up[12])
    lwr_h += gap / vmg
    assert abs(ours_h - lwr_h) <= max(0.03 * lwr_h, 5.0 / 60.0)
