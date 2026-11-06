"""GRIB decode / crop / normalise for the race pack (laptop only; pygrib is never used on the Pi).

Traps pinned by tests (RESEARCH Pitfalls 3, 4, 6, 14):
- crop with the 0.25 deg margin (``wxpack.default_crop``), never exactly at the race bbox;
- valid time = ``calendar.timegm(g.validDate.timetuple())``: ICON-EU codes forecastTime in MINUTES;
- rows are normalised to ascending latitude (EWAM and most GRIB1 files store them north to south);
- masked (bitmap) cells become NaN before any fill.

Inputs are capped (200 MB per file, 100 MB of bz2 output) before parsing.
"""

from __future__ import annotations

import bz2
import calendar
import contextlib
import os
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from jabuka.prep.wxpack import Crop, Cube, default_crop

MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_BZ2_OUTPUT = 100 * 1024 * 1024


def _pygrib() -> Any:
    try:
        import pygrib
    except ImportError as exc:  # pragma: no cover - prep extra missing
        raise RuntimeError(
            "pygrib absent : installer l'extra prep (uv pip install pygrib)"
        ) from exc
    return pygrib


def check_size(path: str | Path, cap: int = MAX_INPUT_BYTES) -> int:
    size = Path(path).stat().st_size
    if size > cap:
        raise ValueError(
            f"fichier trop gros : {Path(path).name} ({size / 1e6:.0f} Mo, "
            f"limite {cap / 1e6:.0f} Mo)"
        )
    return size


def bz2_decompress_capped(data: bytes, cap: int = MAX_BZ2_OUTPUT) -> bytes:
    """Fully decompress bz2 ``data``; ValueError if truncated/corrupt or larger than ``cap``."""
    dec = bz2.BZ2Decompressor()
    out = bytearray()
    try:
        chunk = dec.decompress(data, max_length=cap + 1 - len(out))
        out += chunk
        while not dec.eof:
            if len(out) > cap:
                break
            if dec.needs_input:
                raise ValueError("archive bz2 tronquée")
            out += dec.decompress(b"", max_length=cap + 1 - len(out))
    except OSError as exc:
        raise ValueError(f"archive bz2 corrompue ({exc})") from exc
    if len(out) > cap:
        raise ValueError(f"archive bz2 trop grosse une fois décompressée (> {cap / 1e6:.0f} Mo)")
    return bytes(out)


@contextlib.contextmanager
def open_grib_path(path: str | Path, tmp_dir: str | Path | None = None) -> Iterator[str]:
    """Yield a plain GRIB path for ``path`` (bz2 inputs are decompressed to a temp file)."""
    path = Path(path)
    check_size(path)
    if path.suffix != ".bz2":
        yield str(path)
        return
    raw = bz2_decompress_capped(path.read_bytes())
    if tmp_dir is not None:
        Path(tmp_dir).mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".grib2", dir=tmp_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def valid_epoch(g: Any) -> int:
    """UTC epoch seconds of the message's valid time (never forecastTime arithmetic)."""
    return calendar.timegm(g.validDate.timetuple())


def run_epoch(g: Any) -> int | None:
    try:
        return calendar.timegm(g.analDate.timetuple())
    except Exception:  # noqa: BLE001 - some GRIB1 files lack it
        return None


def _wrap_lon(lon: np.ndarray) -> np.ndarray:
    return np.where(lon > 180.0, lon - 360.0, lon)


def crop_regular(g: Any, crop: Crop) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Regular lat/lon message -> (data float64 [NY, NX] with NaN, lat asc, lon asc), or None when
    pygrib cannot return a 2-D subset (projected grid). ValueError when nothing overlaps."""
    data, lats, lons = g.data(lat1=crop.lat1, lat2=crop.lat2, lon1=crop.lon1, lon2=crop.lon2)
    if np.ndim(data) != 2:
        if np.size(data) == 0 and g.gridType in ("regular_ll", "regular_gg"):
            raise ValueError("la grille du fichier ne recouvre pas la zone de course")
        return None
    if data.size == 0 or data.shape[0] < 2 or data.shape[1] < 2:
        raise ValueError("la grille du fichier ne recouvre pas la zone de course")
    arr = np.ma.filled(np.ma.asarray(data, dtype=np.float64), np.nan)
    la = np.asarray(lats[:, 0], dtype=np.float64)
    lo = _wrap_lon(np.asarray(lons[0, :], dtype=np.float64))
    if la[0] > la[-1]:
        arr, la = arr[::-1, :], la[::-1]
    if lo[0] > lo[-1]:
        arr, lo = arr[:, ::-1], lo[::-1]
    return np.ascontiguousarray(arr), la.copy(), lo.copy()


class _Stack:
    """Collect 2-D fields per valid time on one common grid."""

    def __init__(self) -> None:
        self.lat: np.ndarray | None = None
        self.lon: np.ndarray | None = None
        self.by_t: dict[int, dict[str, np.ndarray]] = {}
        self.run: int | None = None
        self.found: list[str] = []

    def add(self, t: int, name: str, arr: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> None:
        if self.lat is None or self.lon is None:
            self.lat, self.lon = lat, lon
        elif (
            lat.shape != self.lat.shape
            or lon.shape != self.lon.shape
            or not np.allclose(lat, self.lat)
            or not np.allclose(lon, self.lon)
        ):
            raise ValueError("grilles différentes d'un message à l'autre : fichier non homogène")
        self.by_t.setdefault(t, {})[name] = arr

    def cube(self, required: Sequence[str], optional: Sequence[str] = ()) -> Cube:
        times = sorted(t for t, f in self.by_t.items() if all(k in f for k in required))
        if not times or self.lat is None or self.lon is None:
            raise ValueError(f"aucune échéance complète ({' + '.join(required)}) dans les fichiers")
        names = list(required) + [o for o in optional if all(o in self.by_t[t] for t in times)]
        fields = {n: np.stack([self.by_t[t][n] for t in times]).astype(np.float32) for n in names}
        return Cube(
            t=np.array(times, dtype=np.int64),
            lat=self.lat,
            lon=self.lon,
            fields=fields,
            run=self.run,
            found=tuple(dict.fromkeys(self.found)),
        )


_ICON_WIND = {"10u": "u", "10v": "v"}


def decode_wind_files(
    paths: Sequence[str | Path], crop: Crop | None = None, tmp_dir: str | Path | None = None
) -> Cube:
    """ICON-EU style files (10u/10v at 10 m, regular lat/lon) -> wind Cube with fields u, v."""

    def kind(g: Any) -> str | None:
        k = _ICON_WIND.get(str(g.shortName))
        if k is None or g.typeOfLevel != "heightAboveGround" or int(g.level) != 10:
            return None
        return k

    st = _decode_regular(paths, crop or default_crop(), tmp_dir, kind)
    return st.cube(("u", "v"))


def _decode_regular(
    paths: Sequence[str | Path], crop: Crop, tmp_dir: str | Path | None, kind: Any
) -> _Stack:
    pygrib = _pygrib()
    st = _Stack()
    for p in sorted(paths, key=str):
        with open_grib_path(p, tmp_dir) as gp:
            grbs = pygrib.open(gp)
            try:
                for g in grbs:
                    st.found.append(str(g.shortName))
                    k = kind(g)
                    if k is None:
                        continue
                    res = crop_regular(g, crop)
                    if res is None:
                        raise ValueError(
                            f"{Path(p).name} : grille non régulière ({g.gridType}), "
                            "utiliser la commande grib"
                        )
                    arr, la, lo = res
                    st.add(valid_epoch(g), k, arr, la, lo)
                    st.run = st.run if st.run is not None else run_epoch(g)
            finally:
                grbs.close()
    return st


def fill_nearest(a: np.ndarray, max_iter: int | None = None) -> np.ndarray:
    """Fill NaN cells from the nearest valid cell by iterative 4-neighbour dilation (numpy only).

    Works on [NY, NX] or [..., NY, NX] (each 2-D slice independently). Valid cells never change;
    a NaN cell takes the value of its first valid neighbour (row below, row above, column left,
    column right), so directions are never averaged across 0/360. Slices without any valid cell
    stay NaN.
    """
    out = np.array(a, dtype=np.float64, copy=True)
    ny, nx = out.shape[-2:]
    cap = max_iter if max_iter is not None else ny + nx + 2
    # (destination view, source view): the neighbour that feeds each cell
    shifts = (
        (np.s_[..., 1:, :], np.s_[..., :-1, :]),
        (np.s_[..., :-1, :], np.s_[..., 1:, :]),
        (np.s_[..., :, 1:], np.s_[..., :, :-1]),
        (np.s_[..., :, :-1], np.s_[..., :, 1:]),
    )
    for _ in range(cap):
        nan = np.isnan(out)
        if not nan.any():
            break
        cand = np.full_like(out, np.nan)
        for dst, src in shifts:
            view = cand[dst]
            source = out[src]
            take = np.isnan(view) & ~np.isnan(source)
            view[take] = source[take]
        fill = nan & ~np.isnan(cand)
        if not fill.any():
            break
        out[fill] = cand[fill]
    return out


_WAVE_NAMES = {"swh": "hs", "mwd": "mwd"}


def decode_wave_files(
    paths: Sequence[str | Path], crop: Crop | None = None, tmp_dir: str | Path | None = None
) -> Cube:
    """EWAM swh (+ optional mwd, degrees true FROM) files -> waves Cube (fields hs[, mwd]).

    EWAM rows are stored north to south and land/near-coast cells are masked (bitmap): rows are
    flipped to ascending latitude, masked cells become NaN, then filled from the nearest sea cell.
    """
    st = _decode_regular(
        paths, crop or default_crop(), tmp_dir, lambda g: _WAVE_NAMES.get(str(g.shortName))
    )
    cube = st.cube(("hs",), ("mwd",))
    for name, arr in cube.fields.items():
        filled = fill_nearest(arr)
        if np.isnan(filled).any():
            raise ValueError(f"vagues : aucune cellule de mer valide pour {name} sur la zone")
        if name == "mwd":
            filled = np.mod(filled, 360.0)
        cube.fields[name] = filled.astype(np.float32)
    return cube
