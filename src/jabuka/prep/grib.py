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
from datetime import UTC, datetime
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


def _key(g: Any, name: str, default: Any = None) -> Any:
    try:
        return g[name]
    except Exception:  # noqa: BLE001 - pygrib raises RuntimeError/KeyError for absent keys
        return default


def valid_epoch(g: Any) -> int:
    """UTC epoch seconds of the message's valid time (never forecastTime arithmetic).

    eccodes' computed ``validityDate``/``validityTime`` first: they honour the time unit of
    every edition (ICON-EU codes forecastTime in minutes; GRIB1 uses P1 + unit, where pygrib's
    ``validDate`` falls back to the analysis time). ``g.validDate`` only if those keys are absent.
    """
    vd, vt = _key(g, "validityDate"), _key(g, "validityTime")
    if vd is not None and vt is not None:
        d, t = int(vd), int(vt)
        dt = datetime(d // 10000, d // 100 % 100, d % 100, t // 100, t % 100, tzinfo=UTC)
        return int(dt.timestamp())
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


# --------------------------------------------------------------------------- generic GRIB import

REGRID_STEP = 0.025  # deg, target grid for projected / rotated sources
_U_NAMES, _V_NAMES = {"u", "UGRD"}, {"v", "VGRD"}
_WS_NAMES, _WD_NAMES = {"ws", "wind", "si"}, {"wdir", "dir"}
# GRIB1: with table2Version < 128, parameters 1-127 are the WMO standard (31 dir, 32 speed, 33 u,
# 34 v) whatever the centre; local tables (>= 128) reuse those numbers for other fields (ECMWF
# 128/33 is snow density "rsn"), so they are only trusted through eccodes' own names.
_GRIB1_WMO = {33: "u", 34: "v", 32: "ws", 31: "wd"}


def _at_10m(g: Any) -> bool:
    level = _key(g, "level")
    if level is None or float(level) != 10.0:
        return False
    tol = str(_key(g, "typeOfLevel", ""))
    return tol in ("heightAboveGround", "") or "height" in tol.lower()


def wind_kind(g: Any) -> str | None:
    """'u' | 'v' | 'ws' | 'wd' for a 10 m wind message, else None (several key families)."""
    sn = str(_key(g, "shortName", ""))
    if sn == "10u":
        return "u"
    if sn == "10v":
        return "v"
    if sn == "10si":
        return "ws"
    if sn == "10wdir":
        return "wd"
    pid = _key(g, "paramId")
    if pid in (165, 166):
        return "u" if pid == 165 else "v"
    if not _at_10m(g):
        return None
    for names, kind in ((_U_NAMES, "u"), (_V_NAMES, "v"), (_WS_NAMES, "ws"), (_WD_NAMES, "wd")):
        if sn in names:
            return kind
    if _key(g, "edition") == 1:
        table = _key(g, "table2Version")
        iop = _key(g, "indicatorOfParameter")
        if table is not None and int(table) < 128 and iop is not None:
            return _GRIB1_WMO.get(int(iop))
    return None


def _field_label(g: Any) -> str:
    sn = str(_key(g, "shortName", "?"))
    if sn in ("unknown", "?", ""):
        iop = _key(g, "indicatorOfParameter", _key(g, "parameterNumber", "?"))
        return f"{sn}(param {iop})"
    return sn


def uv_from_speed_dir(speed: Any, direction_deg: Any) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised twin of conventions.uv_from_wind_from (direction FROM in degrees)."""
    rad = np.radians(np.asarray(direction_deg, dtype=np.float64))
    spd = np.asarray(speed, dtype=np.float64)
    return -spd * np.sin(rad), -spd * np.cos(rad)


def idw_regrid(
    src_lat: np.ndarray,
    src_lon: np.ndarray,
    vals: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    k: int = 4,
    max_dist: float | None = None,
) -> np.ndarray:
    """Inverse-distance (1/d^2) regrid of scattered points onto the regular (lat, lon) grid using
    the ``k`` nearest sources (brute force in chunks). ``vals`` [K, N] -> [K, NY, NX]; targets
    farther than ``max_dist`` (default 2 x median source spacing) from any source are NaN."""
    vals = np.atleast_2d(np.asarray(vals, dtype=np.float64))
    src_lat = np.asarray(src_lat, dtype=np.float64).ravel()
    src_lon = np.asarray(src_lon, dtype=np.float64).ravel()
    n = src_lat.size
    coslat = np.cos(np.radians(np.mean(src_lat))) if n else 1.0
    sx, sy = src_lon * coslat, src_lat
    tlat, tlon = np.meshgrid(lat, lon, indexing="ij")
    tx, ty = tlon.ravel() * coslat, tlat.ravel()
    out = np.full((vals.shape[0], tx.size), np.nan)
    if n == 0:
        return out.reshape(vals.shape[0], lat.size, lon.size)
    if max_dist is None:
        if n > 1:
            sample = np.linspace(0, n - 1, min(n, 400)).astype(int)
            d2 = (sx[sample, None] - sx[None, :]) ** 2 + (sy[sample, None] - sy[None, :]) ** 2
            d2[np.arange(sample.size), sample] = np.inf
            max_dist = 2.0 * float(np.median(np.sqrt(d2.min(axis=1))))
        else:
            max_dist = np.inf
    kk = min(k, n)
    for start in range(0, tx.size, 512):
        sl = slice(start, min(start + 512, tx.size))
        d2 = (tx[sl, None] - sx[None, :]) ** 2 + (ty[sl, None] - sy[None, :]) ** 2
        idx = (
            np.argpartition(d2, kk - 1, axis=1)[:, :kk]
            if kk < n
            else np.tile(np.arange(n), (d2.shape[0], 1))
        )
        d = np.sqrt(np.take_along_axis(d2, idx, axis=1))
        exact = d < 1e-9
        w = np.where(
            exact.any(axis=1, keepdims=True), exact.astype(float), 1.0 / np.maximum(d, 1e-12) ** 2
        )
        v = vals[:, idx]  # [K, chunk, kk]
        good = np.isfinite(v)
        wk = np.where(good, w[None], 0.0)
        num = np.sum(np.where(good, v, 0.0) * wk, axis=2)
        den = np.sum(wk, axis=2)
        with np.errstate(invalid="ignore", divide="ignore"):
            res = num / den
        res[:, d.min(axis=1) > max_dist] = np.nan
        out[:, sl] = res
    return out.reshape(vals.shape[0], lat.size, lon.size)


def _target_axes(crop: Crop, lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat_lo, lat_hi = max(crop.lat1, float(lats.min())), min(crop.lat2, float(lats.max()))
    lon_lo, lon_hi = max(crop.lon1, float(lons.min())), min(crop.lon2, float(lons.max()))
    if lat_hi - lat_lo < REGRID_STEP or lon_hi - lon_lo < REGRID_STEP:
        raise ValueError("la grille du fichier ne recouvre pas la zone de course")
    lat = np.arange(np.ceil(lat_lo / REGRID_STEP), np.floor(lat_hi / REGRID_STEP) + 1) * REGRID_STEP
    lon = np.arange(np.ceil(lon_lo / REGRID_STEP), np.floor(lon_hi / REGRID_STEP) + 1) * REGRID_STEP
    return np.round(lat, 6), np.round(lon, 6)


def import_generic(path: str | Path, crop: Crop | None = None) -> Cube:
    """Any GRIB1/GRIB2 file with 10 m wind (u/v or speed/direction; regular, rotated or projected
    grid) -> wind Cube (u, v). ValueError (French) when unusable."""
    pygrib = _pygrib()
    crop = crop or default_crop()
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"fichier introuvable : {path}")
    check_size(path)
    found: list[str] = []
    # t -> kind -> ("reg", arr2d, lat, lon) | ("pts", vals1d, lats1d, lons1d)
    recs: dict[int, dict[str, tuple[Any, ...]]] = {}
    run: int | None = None
    sel = 0.3  # deg kept around the crop for projected grids (IDW neighbours at the edges)
    with open_grib_path(path) as gp:
        try:
            grbs = pygrib.open(gp)
        except Exception as exc:  # noqa: BLE001 - not a GRIB file
            raise ValueError(f"fichier GRIB illisible : {path.name} ({exc})") from exc
        try:
            for g in grbs:
                found.append(_field_label(g))
                kind = wind_kind(g)
                if kind is None:
                    continue
                t = valid_epoch(g)
                run = run if run is not None else run_epoch(g)
                gtype = str(_key(g, "gridType", ""))
                if gtype in ("regular_ll", "regular_gg"):
                    arr, la, lo = crop_regular(g, crop) or (None, None, None)
                    if arr is None:
                        raise ValueError(f"grille {gtype} illisible")
                    recs.setdefault(t, {})[kind] = ("reg", arr, la, lo)
                    continue
                try:
                    lats, lons = g.latlons()
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"type de grille non pris en charge : {gtype}") from exc
                lats = np.asarray(lats, dtype=np.float64).ravel()
                lons = _wrap_lon(np.asarray(lons, dtype=np.float64).ravel())
                vals = np.ma.filled(np.ma.asarray(g.values, dtype=np.float64), np.nan).ravel()
                keep = (
                    (lats >= crop.lat1 - sel)
                    & (lats <= crop.lat2 + sel)
                    & (lons >= crop.lon1 - sel)
                    & (lons <= crop.lon2 + sel)
                )
                if not keep.any():
                    raise ValueError("la grille du fichier ne recouvre pas la zone de course")
                recs.setdefault(t, {})[kind] = ("pts", vals[keep], lats[keep], lons[keep])
        finally:
            grbs.close()
    print(f"GRIB {path.name} : champs trouvés : {', '.join(dict.fromkeys(found)) or 'aucun'}")
    st = _Stack()
    st.run = run
    st.found = found
    for t in sorted(recs):
        r = recs[t]
        if "u" in r and "v" in r:
            ru, rv, from_sd = r["u"], r["v"], False
        elif "ws" in r and "wd" in r:
            ru, rv, from_sd = r["ws"], r["wd"], True
        else:
            continue
        if ru[0] != rv[0] or ru[2].shape != rv[2].shape or not np.allclose(ru[2], rv[2]):
            raise ValueError("composantes du vent sur des grilles différentes")
        a, b = ru[1], rv[1]
        if from_sd:
            a, b = uv_from_speed_dir(a, b)
        if ru[0] == "reg":
            st.add(t, "u", a, ru[2], ru[3])
            st.add(t, "v", b, ru[2], ru[3])
        else:
            lat, lon = _target_axes(crop, ru[2], ru[3])
            out = idw_regrid(ru[2], ru[3], np.vstack([a, b]), lat, lon)
            st.add(t, "u", out[0], lat, lon)
            st.add(t, "v", out[1], lat, lon)
    if not st.by_t:
        present = ", ".join(dict.fromkeys(found)) or "aucun"
        raise ValueError(f"aucun champ de vent 10 m trouvé ; champs présents : {present}")
    return st.cube(("u", "v"))
