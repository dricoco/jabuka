"""Soak race pack: the committed 25 m land mask plus a generated hourly wind cube.

The uniform cube deliberately duplicates the ~20-line writer of tests/routing/conftest.write_wind
(nothing under src/ may import from tests/). TWD(t) = TWD + shift x hours since start_utc,
TWS = TWS x grib.tws_factor, hourly from start_utc - hours_before to end_utc.
"""

from __future__ import annotations

import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from jabuka.prep.wxpack import write_npz

KN = 1852.0 / 3600.0
LAT = np.arange(42.5, 44.3, 0.25, dtype=np.float64)
LON = np.arange(14.75, 16.6, 0.25, dtype=np.float64)
MASK_STEM = "landmask_race_25m"


def inside(path: Path, root: Path) -> Path:
    """``path`` resolved, asserted inside ``root`` (T-04-01-01: never touch real data)."""
    p, r = Path(path).resolve(), Path(root).resolve()
    if p != r and r not in p.parents:
        raise ValueError(f"refusing to touch {p}: outside the soak run dir {r}")
    return p


def wind_arrays(
    start_utc: float,
    end_utc: float,
    *,
    twd: float,
    tws_kn: float,
    shift_deg_h: float = 0.0,
    tws_factor: float = 1.0,
    hours_before: float = 2.0,
) -> dict:
    """Hourly uniform-in-space wind (FROM twd + shift * h, tws_kn * tws_factor)."""
    t0 = int(math.floor((start_utc - hours_before * 3600.0) / 3600.0) * 3600)
    t1 = int(math.ceil(end_utc / 3600.0) * 3600)
    t = np.arange(t0, max(t1, t0 + 3600) + 1, 3600, dtype=np.int64)
    hours = (t - start_utc) / 3600.0
    twd_t = np.radians(twd + shift_deg_h * hours)
    ms = tws_kn * tws_factor * KN
    u = (-ms * np.sin(twd_t)).astype(np.float32)
    v = (-ms * np.cos(twd_t)).astype(np.float32)
    shape = (t.size, LAT.size, LON.size)
    run = datetime.fromtimestamp(t0, UTC).strftime("%Y-%m-%dT%H:%MZ")
    return {
        "t": t,
        "lat": LAT.copy(),
        "lon": LON.copy(),
        "u": np.broadcast_to(u[:, None, None], shape).copy(),
        "v": np.broadcast_to(v[:, None, None], shape).copy(),
        "model": "soak-uniform",
        "run": run,
    }


def write_wind(dest: Path, root: Path, start_utc: float, end_utc: float, **kw) -> Path:
    """wind.npz + sidecar into dest (inside root), atomically."""
    dest = inside(dest, root)
    arrays = wind_arrays(start_utc, end_utc, **kw)
    meta = {"source": "jabuka-soak", "model": "soak-uniform", "run": arrays["run"]}
    return write_npz(dest, "wind", arrays, meta)


def build_pack(
    dest: Path,
    root: Path,
    fixtures: Path,
    start_utc: float,
    end_utc: float,
    wind: dict,
    grib: dict,
) -> Path:
    """<dest>/landmask.{npz,json} from fixtures/route plus wind.npz covering the run."""
    dest = inside(dest, root)
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(fixtures) / "route" / MASK_STEM
    for suffix in (".npz", ".json"):
        if not src.with_suffix(suffix).is_file():
            raise FileNotFoundError(f"soak pack: {src.with_suffix(suffix)} missing (--fixtures)")
        shutil.copy(src.with_suffix(suffix), dest / f"landmask{suffix}")
    write_wind(
        dest,
        root,
        start_utc,
        end_utc,
        twd=float(wind.get("twd", 161.0)),
        tws_kn=float(wind.get("tws_kn", 12.0)),
        shift_deg_h=float(wind.get("shift_deg_h", 0.0)),
        tws_factor=float(grib.get("tws_factor", 1.0)),
        hours_before=float(grib.get("hours_before", 2.0)),
    )
    return dest
