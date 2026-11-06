"""Shared fixtures for the router tests (plan 03-03).

numpy is imported inside the fixtures only: this module must import without numpy so Phase 2
worktrees (no numpy) still collect tests/route (each test module applies the route-deps guard).
"""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MASK_FILE = FIXTURES / "route" / "landmask_race_25m.npz"
POLAR_FILE = FIXTURES / "route" / "x35_polar.json"
MARKS_FILE = FIXTURES / "route" / "marks.json"
WIND_SAMPLE = FIXTURES / "racepack" / "wind_icon_eu_sample"
WAVES_SAMPLE = FIXTURES / "racepack" / "waves_ewam_sample"

T0 = 1793923200.0  # 2026-11-06T00:00Z, first time of the committed ICON-EU sample
KN = 1852.0 / 3600.0  # m/s per knot


@pytest.fixture(scope="session")
def mask():
    from jabuka.route.landmask import LandMask

    return LandMask.load(MASK_FILE)


@pytest.fixture(scope="session")
def polar_curves():
    from jabuka.route.polar_grid import curves_from_json

    return curves_from_json(json.loads(POLAR_FILE.read_text(encoding="utf-8")))


def _axes():
    import numpy as np

    return np.arange(42.5, 44.3, 0.25), np.arange(14.75, 16.6, 0.25)


@pytest.fixture(scope="session")
def uniform_wind() -> Callable[..., Any]:
    """factory(twd_deg, tws_kn, t0=T0, hours=48) -> racepack.Grid of constant wind (m/s)."""
    import numpy as np

    from jabuka.route.racepack import Grid

    def make(twd_deg: float, tws_kn: float, t0: float = T0, hours: float = 48.0) -> Grid:
        lat, lon = _axes()
        t = np.array([int(t0) - 3600, int(t0 + hours * 3600)], dtype=np.int64)
        ms = tws_kn * KN
        u = -ms * math.sin(math.radians(twd_deg))
        v = -ms * math.cos(math.radians(twd_deg))
        shape = (2, lat.size, lon.size)
        return Grid(
            t, lat, lon, {"u": np.full(shape, u, np.float32), "v": np.full(shape, v, np.float32)}
        )

    return make


@pytest.fixture(scope="session")
def uniform_grid() -> Callable[..., Any]:
    """factory(arrays: {name: value}, t0=T0, hours=48) -> Grid of constant fields (pack units)."""
    import numpy as np

    from jabuka.route.racepack import Grid

    def make(values: dict[str, float], t0: float = T0, hours: float = 48.0) -> Grid:
        lat, lon = _axes()
        t = np.array([int(t0) - 3600, int(t0 + hours * 3600)], dtype=np.int64)
        shape = (2, lat.size, lon.size)
        return Grid(t, lat, lon, {k: np.full(shape, v, np.float32) for k, v in values.items()})

    return make


@pytest.fixture(scope="session")
def sample_pack(tmp_path_factory):
    """RacePack loaded (load_pack) from a temp copy of the committed ICON-EU/EWAM samples."""
    from jabuka.route.racepack import load_pack

    d = tmp_path_factory.mktemp("samplepack")
    for src, stem in ((WIND_SAMPLE, "wind"), (WAVES_SAMPLE, "waves")):
        shutil.copy(src.with_suffix(".npz"), d / f"{stem}.npz")
        shutil.copy(src.with_suffix(".json"), d / f"{stem}.json")
    pack = load_pack(d)
    assert pack.wind is not None and not pack.errors, pack.errors
    return pack


@pytest.fixture(scope="session")
def sample_wind(sample_pack):
    return sample_pack.wind


@pytest.fixture(scope="session")
def geo_cache() -> dict:
    """In-session cache of on-demand geodesic fields, shared by every RouterEnv."""
    return {}


@pytest.fixture(scope="session")
def env_factory(mask, geo_cache) -> Callable[..., Any]:
    """factory(wind_grid, waves=None, current=None, geofields=None) -> RouterEnv."""
    from jabuka.route.fields import CurrentField, Fields, WaveField, WindField
    from jabuka.route.isochrone import RouterEnv

    def make(wind, waves=None, current=None, geofields=None) -> RouterEnv:
        f = mask.frame
        fields = Fields(
            WindField(wind, f),
            WaveField(waves, f) if waves is not None else None,
            CurrentField(current, f) if current is not None else None,
        )
        return RouterEnv(mask, fields, geofields=dict(geofields or {}), geo_cache=geo_cache)

    return make


@pytest.fixture(scope="session")
def make_request(polar_curves) -> Callable[..., Any]:
    """factory(lat, lon, marks, **overrides) -> RouteRequest (eff 1.0, L0, no bias)."""
    from jabuka.route.types import RouteRequest, RouterSettings

    def make(lat: float, lon: float, marks, **kw) -> Any:
        args: dict[str, Any] = {
            "request_id": "test",
            "t0": T0,
            "lat": lat,
            "lon": lon,
            "tack0": 0,
            "prev_mark": None,
            "marks": tuple(marks),
            "polar_curves": polar_curves,
            "eff": 1.0,
            "eff_up": None,
            "eff_down": None,
            "bias": None,
            "settings": RouterSettings(),
        }
        args.update(kw)
        return RouteRequest(**args)

    return make


def point_mark(lat: float, lon: float, name: str = "cible", radius: float = 0.0):
    from jabuka.route.types import CourseMark

    return CourseMark(name.lower(), name, lat, lon, "none", radius)


@pytest.fixture(scope="session")
def mark_point() -> Callable[..., Any]:
    return point_mark


# --------------------------------------------------------------------------- courses (Task 2)
PLIC_BEACON = (43.684627, 15.811626)  # OSM node 498394251, isolated-danger beacon


@pytest.fixture(scope="session")
def marks_doc():
    from jabuka.route.racepack import read_marks_file

    return read_marks_file(MARKS_FILE)


@pytest.fixture(scope="session")
def course(marks_doc) -> Callable[..., Any]:
    """factory(key) -> (start CourseMark, remaining marks tuple) for template A or B, the boat
    at the start (the start mark is the previous mark of leg 1)."""
    from jabuka.route.types import CourseMark

    def make(key: str):
        cms = []
        for mid, side in marks_doc.templates[key]:
            m = marks_doc.marks[mid]
            cms.append(CourseMark(m.id, m.name, m.lat, m.lon, side, m.radius_nm))
        return cms[0], tuple(cms[1:])

    return make


@pytest.fixture(scope="session")
def course_geofields(mask, marks_doc) -> dict:
    """200 m centre-mode fields for the five marks, keyed like load_geofields (prep output)."""
    from jabuka.route.isochrone import mark_key
    from jabuka.route.landmask import compute_geofield
    from jabuka.route.types import CourseMark

    g = 200.0 / 1852.0
    out = {}
    for m in marks_doc.marks.values():
        x, y = mask.frame.to_xy(m.lat, m.lon)
        cm = CourseMark(m.id, m.name, m.lat, m.lon, "none", m.radius_nm)
        out[mark_key(cm)] = compute_geofield(
            mask, [(x, y)], g, "centre", seed_radius_nm=m.radius_nm + g
        )
    return out


def densify(path, mask, step_nm: float = 0.05):
    """Path points -> dense (x, y) arrays in the mask frame (winding / distance checks)."""
    import numpy as np

    xs, ys = mask.frame.to_xy(np.array([p.lat for p in path]), np.array([p.lon for p in path]))
    out_x, out_y = [xs[0]], [ys[0]]
    for i in range(len(xs) - 1):
        n = max(1, int(math.ceil(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) / step_nm)))
        f = np.arange(1, n + 1) / n
        out_x.extend(xs[i] + f * (xs[i + 1] - xs[i]))
        out_y.extend(ys[i] + f * (ys[i + 1] - ys[i]))
    return np.array(out_x), np.array(out_y)


def winding_deg(path, mask, lat: float, lon: float, within_nm: float) -> float:
    """Signed winding (deg) of the path around (lat, lon), x east / y north, counter-clockwise
    positive, over the contiguous stretch within ``within_nm`` around the closest approach."""
    import numpy as np

    x, y = densify(path, mask)
    mx, my = mask.frame.to_xy(lat, lon)
    d = np.hypot(x - mx, y - my)
    i = int(np.argmin(d))
    lo = i
    while lo > 0 and d[lo - 1] <= within_nm:
        lo -= 1
    hi = i
    while hi < len(d) - 1 and d[hi + 1] <= within_nm:
        hi += 1
    ang = np.unwrap(np.arctan2(y[lo : hi + 1] - my, x[lo : hi + 1] - mx))
    return float(np.degrees(ang[-1] - ang[0]))


def min_dist_m(path, mask, lat: float, lon: float) -> float:
    import numpy as np

    x, y = densify(path, mask, 0.005)
    mx, my = mask.frame.to_xy(lat, lon)
    return float(np.hypot(x - mx, y - my).min() * 1852.0)


@pytest.fixture(scope="session")
def path_tools() -> dict[str, Callable[..., Any]]:
    return {"winding": winding_deg, "min_dist_m": min_dist_m, "densify": densify}


@pytest.fixture(scope="session")
def plic_beacon() -> tuple[float, float]:
    return PLIC_BEACON
