"""Shared helpers for the race-pack tests (plan 03-02).

GRIB files are generated from the committed ICON-EU template (tests/fixtures/racepack/grib/) by
editing grid, values, parameter and forecastTime with pygrib (RESEARCH "Tiny GRIB fixtures").
pygrib/numpy are imported lazily so Phase 2 venvs without them can still collect this directory
(the test modules apply the route-deps guard themselves).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

RACEPACK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "racepack"
ICON_TEMPLATE = RACEPACK_FIXTURES / "grib" / "icon_template.grib2"
EWAM_TEMPLATE = RACEPACK_FIXTURES / "grib" / "ewam_template.grib2"

# 13 Nov 12Z run, the race window 13 Nov 17:00Z -> 15 Nov 09:00Z
RUN_13_12Z = datetime(2026, 11, 13, 12, tzinfo=UTC)
WINDOW_START = int(datetime(2026, 11, 13, 17, tzinfo=UTC).timestamp())
WINDOW_END = int(datetime(2026, 11, 15, 9, tzinfo=UTC).timestamp())


def grib_message(
    *,
    template: Path = ICON_TEMPLATE,
    short_name: str | None = None,
    run: datetime = RUN_13_12Z,
    forecast: int = 0,
    lat_first: float = 42.5,
    lat_last: float = 44.5,
    lon_first: float = 14.5,
    lon_last: float = 16.75,
    dlat: float = 0.0625,
    dlon: float = 0.0625,
    values: Any = 0.0,
    missing: Any = None,
    keys: dict[str, Any] | None = None,
) -> bytes:
    """One GRIB message (bytes) from a template. ``forecast`` is in the template's time unit
    (MINUTES for the ICON-EU template, hours for EWAM). ``lat_first > lat_last`` stores rows
    north to south. ``missing`` (bool [NY, NX]) writes a bitmap with those cells masked."""
    import numpy as np
    import pygrib

    g = pygrib.open(str(template)).message(1)
    nj = int(round(abs(lat_last - lat_first) / dlat)) + 1
    ni = int(round((lon_last - lon_first) / dlon)) + 1
    g["packingType"] = "grid_simple"
    g["Ni"], g["Nj"] = ni, nj
    g["jScansPositively"] = 1 if lat_last > lat_first else 0
    g["latitudeOfFirstGridPointInDegrees"] = lat_first
    g["latitudeOfLastGridPointInDegrees"] = lat_last
    g["longitudeOfFirstGridPointInDegrees"] = lon_first
    g["longitudeOfLastGridPointInDegrees"] = lon_last
    g["iDirectionIncrementInDegrees"] = dlon
    g["jDirectionIncrementInDegrees"] = dlat
    if short_name is not None:
        g["shortName"] = short_name
    g["dataDate"] = int(run.strftime("%Y%m%d"))
    g["dataTime"] = int(run.strftime("%H%M"))
    g["forecastTime"] = forecast
    for k, v in (keys or {}).items():
        g[k] = v
    vals = np.broadcast_to(np.asarray(values, dtype=np.float64), (nj, ni)).copy()
    if missing is not None:
        g["missingValue"] = 9999
        g["bitmapPresent"] = 1
        vals[np.asarray(missing, dtype=bool)] = 9999.0
    g.values = vals
    return g.tostring()


def grid_axes(
    lat_first: float = 42.5,
    lat_last: float = 44.5,
    lon_first: float = 14.5,
    lon_last: float = 16.75,
    dlat: float = 0.0625,
    dlon: float = 0.0625,
):
    """(lats as stored row by row, lons) for the same arguments as grib_message."""
    import numpy as np

    nj = int(round(abs(lat_last - lat_first) / dlat)) + 1
    ni = int(round((lon_last - lon_first) / dlon)) + 1
    return np.linspace(lat_first, lat_last, nj), np.linspace(lon_first, lon_last, ni)


@pytest.fixture
def make_grib() -> Callable[..., bytes]:
    return grib_message


@pytest.fixture
def write_grib() -> Callable[[Path, Sequence[bytes]], Path]:
    def _write(path: Path, messages: Sequence[bytes]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(messages))
        return path

    return _write


def wind_run_messages(
    hours: Sequence[int], u: float = 0.0, v: float = -5.0, run: datetime = RUN_13_12Z, **kw: Any
) -> list[bytes]:
    """10u/10v message pairs for the given forecast hours (ICON-EU minutes coding)."""
    out = []
    for h in hours:
        out.append(grib_message(short_name="10u", run=run, forecast=h * 60, values=u, **kw))
        out.append(grib_message(short_name="10v", run=run, forecast=h * 60, values=v, **kw))
    return out


@pytest.fixture
def wind_messages() -> Callable[..., list[bytes]]:
    return wind_run_messages


PHASE2_MARKS = {
    "version": 1,
    "marks": [
        {"id": "vodice", "name": "Vodice", "lat": 43.75, "lon": 15.78, "radius_nm": 0.15},
        {
            "id": "plic-sestre",
            "name": "Plić Sestre",
            "lat": 43.684627,
            "lon": 15.811626,
            "radius_nm": 0.3,
        },
        {"id": "jabuka", "name": "Jabuka", "lat": 43.09153, "lon": 15.46054, "radius_nm": 0.6},
        {
            "id": "blitvenica",
            "name": "Blitvenica",
            "lat": 43.62508,
            "lon": 15.57476,
            "radius_nm": 0.55,
        },
        {"id": "mulo", "name": "Mulo", "lat": 43.5146, "lon": 15.91857, "radius_nm": 0.5},
    ],
    "templates": {
        "A": [
            {"mark_id": m, "side": s}
            for m, s in (
                ("vodice", "none"),
                ("plic-sestre", "stbd"),
                ("jabuka", "stbd"),
                ("blitvenica", "stbd"),
                ("vodice", "none"),
            )
        ],
        "B": [
            {"mark_id": m, "side": s}
            for m, s in (
                ("vodice", "none"),
                ("plic-sestre", "port"),
                ("jabuka", "port"),
                ("mulo", "port"),
                ("vodice", "none"),
            )
        ],
    },
}


@pytest.fixture
def marks_file(tmp_path: Path) -> Path:
    p = tmp_path / "marks.json"
    p.write_text(json.dumps(PHASE2_MARKS, ensure_ascii=False), encoding="utf-8")
    return p


def synthetic_grid(
    t0: int = int(datetime(2026, 11, 13, 12, tzinfo=UTC).timestamp()),
    hours: int = 49,
    step_s: int = 3600,
    u: float = 0.0,
    v: float = -5.0,
):
    """(t, lat, lon, u, v) covering the race area like an ICON-EU crop."""
    import numpy as np

    t = t0 + step_s * np.arange(hours, dtype=np.int64)
    lat = np.round(np.arange(42.5625, 44.25 + 1e-9, 0.0625), 6)
    lon = np.round(np.arange(14.75, 16.5 + 1e-9, 0.0625), 6)
    shape = (t.size, lat.size, lon.size)
    return (t, lat, lon, np.full(shape, u, dtype=np.float32), np.full(shape, v, dtype=np.float32))


@pytest.fixture
def rp() -> Any:
    """All helpers and constants in one namespace (test modules cannot import conftest under
    --import-mode=importlib)."""
    from types import SimpleNamespace

    return SimpleNamespace(
        fixtures=RACEPACK_FIXTURES,
        icon_template=ICON_TEMPLATE,
        ewam_template=EWAM_TEMPLATE,
        run_13_12z=RUN_13_12Z,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        grib_message=grib_message,
        grid_axes=grid_axes,
        wind_run_messages=wind_run_messages,
        synthetic_grid=synthetic_grid,
        marks=PHASE2_MARKS,
    )
