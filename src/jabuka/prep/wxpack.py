"""Race-pack writer (laptop): weather cubes -> <stem>.npz + <stem>.json sidecar, written atomically.

npz layout (contract with jabuka.route.racepack): float32 fields [T, NY, NX], ``t`` int64 UTC epoch
seconds strictly increasing, ``lat``/``lon`` float64 ascending, strings (model, run, source) as 0-d
numpy unicode arrays, so the Pi loads everything with ``np.load(..., allow_pickle=False)``.

The sidecar carries the sha256 of the npz bytes; the Pi refuses a file whose hash differs.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from jabuka.common.atomicio import atomic_write_bytes, atomic_write_json

# Race area (lon_min, lat_min, lon_max, lat_max), the same box as jabuka.route.frame.RACE_BBOX.
RACE_BBOX = (15.0, 42.8, 16.3, 44.0)
# Crop margin in degrees: more than one cell of every source grid, so the bbox edges interpolate
# (cropping exactly at the bbox dropped 16.3E from ICON-EU and 15.0E from EWAM in research).
MARGIN_DEG = 0.25


@dataclass(frozen=True)
class Crop:
    lat1: float
    lat2: float
    lon1: float
    lon2: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat1 <= lat <= self.lat2 and self.lon1 <= lon <= self.lon2


def default_crop(
    bbox: tuple[float, float, float, float] = RACE_BBOX, margin: float = MARGIN_DEG
) -> Crop:
    lon_min, lat_min, lon_max, lat_max = bbox
    return Crop(
        lat1=lat_min - margin, lat2=lat_max + margin, lon1=lon_min - margin, lon2=lon_max + margin
    )


@dataclass
class Cube:
    """A decoded, cropped weather field set on a regular ascending lat/lon grid."""

    t: np.ndarray  # int64 [T] UTC epoch seconds, strictly increasing
    lat: np.ndarray  # float64 [NY] ascending
    lon: np.ndarray  # float64 [NX] ascending
    fields: dict[str, np.ndarray]  # name -> float32 [T, NY, NX]
    run: int | None = None  # model run (analysis) time, UTC epoch seconds
    found: tuple[str, ...] = ()  # field names seen while decoding (diagnostics)


def iso_utc(epoch: int | float) -> str:
    return datetime.fromtimestamp(int(epoch), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_npz(out_dir: str | Path, stem: str, arrays: dict[str, Any], meta: dict[str, Any]) -> Path:
    """Write ``out_dir/<stem>.npz`` and its ``<stem>.json`` sidecar atomically; return the npz path.

    ``arrays`` holds numpy arrays; str values become 0-d unicode arrays. ``meta`` supplies
    source/model/run (any extra keys are copied into the sidecar).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, np.ndarray] = {}
    for key, value in arrays.items():
        payload[key] = np.array(value, dtype=np.str_) if isinstance(value, str) else value
    buf = io.BytesIO()
    np.savez_compressed(buf, **payload)
    data = buf.getvalue()
    npz_path = out_dir / f"{stem}.npz"
    atomic_write_bytes(npz_path, data)
    t = payload.get("t")
    sidecar = {
        "file": npz_path.name,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": meta.get("source", ""),
        "model": meta.get("model", ""),
        "run": meta.get("run", ""),
        "t_first": iso_utc(t[0]) if t is not None and len(t) else None,
        "t_last": iso_utc(t[-1]) if t is not None and len(t) else None,
        "shape": {k: list(np.shape(v)) for k, v in payload.items()},
    }
    for key, value in meta.items():
        sidecar.setdefault(key, value)
    atomic_write_json(out_dir / f"{stem}.json", sidecar)
    return npz_path


def write_cube(
    out_dir: str | Path, stem: str, cube: Cube, *, model: str, source: str, run: str | None = None
) -> Path:
    """Write a Cube with the pack schema (float32 fields, int64 t, float64 axes, string meta)."""
    run_s = run if run is not None else (iso_utc(cube.run) if cube.run is not None else "")
    arrays: dict[str, Any] = {
        name: np.asarray(a, dtype=np.float32) for name, a in cube.fields.items()
    }
    arrays.update(
        t=np.asarray(cube.t, dtype=np.int64),
        lat=np.asarray(cube.lat, dtype=np.float64),
        lon=np.asarray(cube.lon, dtype=np.float64),
        model=model,
        run=run_s,
        source=source,
    )
    return write_npz(out_dir, stem, arrays, {"model": model, "run": run_s, "source": source})


def write_coverage(out_dir: str | Path, report: Any) -> Path:
    """Write coverage.txt (UTF-8, French lines) from a racepack.CoverageReport."""
    from jabuka.route.racepack import format_report

    path = Path(out_dir) / "coverage.txt"
    atomic_write_bytes(path, (format_report(report) + "\n").encode("utf-8"))
    return path
