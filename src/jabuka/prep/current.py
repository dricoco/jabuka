"""Copernicus Marine Med surface current NetCDF -> race-pack current Cube (GRIB-03, laptop only).

The owner downloads the file with their own free account (``copernicusmarine login`` then
``copernicusmarine subset ...``, see docs/WEATHER-PACK.md). This importer only takes a file path:
it never asks for, reads or stores credentials.

Dataset ``cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m``: ``uo``/``vo`` (m/s, eastward/northward,
i.e. TOWARDS, the convention of ``conventions.current_towards_uv``), coordinates ``time``,
``latitude``, ``longitude`` (an optional size-1 ``depth`` is squeezed). Land/masked cells become 0:
unknown current means no current, never a value copied from a neighbouring sea cell.
"""

from __future__ import annotations

import calendar
from pathlib import Path
from typing import Any

import numpy as np

from jabuka.prep.grib import MAX_INPUT_BYTES, check_size
from jabuka.prep.wxpack import Crop, Cube

SOURCE = "Copernicus MEDSEA cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m"
_U = ("uo", "eastward_sea_water_velocity")
_V = ("vo", "northward_sea_water_velocity")
_LAT = ("latitude", "lat", "nav_lat")
_LON = ("longitude", "lon", "nav_lon")


def _find(ds: Any, names: tuple[str, ...]) -> Any | None:
    for name in names:
        if name in ds.variables:
            return ds.variables[name]
    for var in ds.variables.values():
        if getattr(var, "standard_name", None) in names:
            return var
    return None


def import_copernicus(path: str | Path, crop: Crop) -> Cube:
    """Read uo/vo from a Copernicus NetCDF, crop, normalise, land = 0. ValueError (French)."""
    try:
        import netCDF4
    except ImportError as exc:  # pragma: no cover - prep extra missing
        raise RuntimeError("netCDF4 absent : installer l'extra prep") from exc
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"fichier introuvable : {path}")
    check_size(path, MAX_INPUT_BYTES)
    try:
        ds = netCDF4.Dataset(str(path), "r")
    except OSError as exc:
        raise ValueError(f"fichier NetCDF illisible : {path.name} ({exc})") from exc
    try:
        u_var, v_var = _find(ds, _U), _find(ds, _V)
        if u_var is None or v_var is None:
            raise ValueError(
                f"courants uo/vo introuvables dans {path.name} ; variables : "
                + ", ".join(ds.variables)
            )
        lat_var, lon_var, t_var = _find(ds, _LAT), _find(ds, _LON), _find(ds, ("time",))
        if lat_var is None or lon_var is None or t_var is None:
            raise ValueError(f"coordonnées time/latitude/longitude introuvables dans {path.name}")
        lat = np.asarray(lat_var[:], dtype=np.float64)
        lon = np.asarray(lon_var[:], dtype=np.float64)
        if lat.ndim != 1 or lon.ndim != 1:
            raise ValueError("grille courant non régulière (latitude/longitude 2-D)")
        dates = netCDF4.num2date(
            t_var[:],
            t_var.units,
            getattr(t_var, "calendar", "standard"),
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        t = np.array([calendar.timegm(d.timetuple()) for d in np.atleast_1d(dates)], np.int64)
        jj = np.flatnonzero((lat >= crop.lat1) & (lat <= crop.lat2))
        ii = np.flatnonzero((lon >= crop.lon1) & (lon <= crop.lon2))
        if jj.size < 2 or ii.size < 2:
            raise ValueError("le fichier courant ne recouvre pas la zone de course")
        fields: dict[str, np.ndarray] = {}
        for name, var in (("u", u_var), ("v", v_var)):
            data = np.ma.asarray(var[:])
            while data.ndim > 3:  # (time, depth=1, lat, lon) -> (time, lat, lon)
                axis = next((i for i in range(1, data.ndim - 2) if data.shape[i] == 1), None)
                if axis is None:
                    raise ValueError(f"{var.name} : dimension de profondeur > 1 non gérée")
                data = data.squeeze(axis=axis)
            if data.shape != (t.size, lat.size, lon.size):
                raise ValueError(f"{var.name} : forme {data.shape} inattendue")
            arr = np.ma.filled(data.astype(np.float64), np.nan)[:, jj][:, :, ii]
            arr[~np.isfinite(arr) | (np.abs(arr) > 50.0)] = 0.0  # land / masked / fill: none
            fields[name] = arr
    finally:
        ds.close()
    lat_c, lon_c = lat[jj], lon[ii]
    if lat_c[0] > lat_c[-1]:
        lat_c = lat_c[::-1]
        fields = {k: a[:, ::-1, :] for k, a in fields.items()}
    if lon_c[0] > lon_c[-1]:
        lon_c = lon_c[::-1]
        fields = {k: a[:, :, ::-1] for k, a in fields.items()}
    order = np.argsort(t)
    if np.any(np.diff(t[order]) <= 0):
        raise ValueError("temps du fichier courant dupliqués")
    return Cube(
        t=t[order],
        lat=np.ascontiguousarray(lat_c),
        lon=np.ascontiguousarray(lon_c),
        fields={k: np.ascontiguousarray(a[order]).astype(np.float32) for k, a in fields.items()},
        found=("uo", "vo"),
    )
