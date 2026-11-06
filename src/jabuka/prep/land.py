"""Laptop land-mask builder: OSM coastline (Overpass) -> land polygons -> 25 m raster + margins.

    python -m jabuka.prep.land build --out var/racepack [--cell-m 25] [--shore-margin-m 100]
                                     [--cache var/cache/prep] [--offline]
    python -m jabuka.prep.land check DIR|FILE.npz

Laptop only (shapely, urllib, the wall clock). The Pi only loads the npz with numpy
(jabuka.route.landmask). OSM data © OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, box
from shapely.ops import linemerge, polygonize, unary_union

from jabuka.common.atomicio import atomic_write_bytes, atomic_write_json
from jabuka.route.frame import DEFAULT_FRAME, NM_M, RACE_BBOX, Frame
from jabuka.route.landmask import LandMask

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "jabuka-prep/0.1 (offline race navigation)"
TIMEOUT_S = 180
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_CACHE = Path("var/cache/prep")
SOURCE = "OSM coastline + seamark hazards via Overpass"

# Query box slightly larger than RACE_BBOX (south, west, north, east) so clipping is clean.
QUERY_BBOX = "42.7,14.9,44.1,16.4"
COASTLINE_QUERY = f'[out:json][timeout:180];way["natural"="coastline"]({QUERY_BBOX});out geom;'
HAZARD_QUERY = (
    "[out:json][timeout:180];("
    'node["seamark:type"~"^(rock|beacon_isolated_danger|buoy_isolated_danger|wreck|obstruction)$"]'
    f"({QUERY_BBOX});"
    f'way["seamark:type"="obstruction"]({QUERY_BBOX});'
    f'nwr["natural"~"^(reef|shoal)$"]({QUERY_BBOX});'
    ");out geom;"
)

# Hazard geometry (metres): points become discs, ways a buffer around their line; then the hazard
# margin is added. Submerged rocks (depth unknown in OSM) are discs without margin.
DISC_M = 50.0
WAY_BUFFER_M = 25.0
# Rock water levels that show or break the surface: full hazard margin.
AWASH_LEVELS = frozenset({"awash", "covers", "dry", "always_dry", "partly_submerged_at_high_water"})
MARGIN_SEAMARKS = frozenset(
    {"beacon_isolated_danger", "buoy_isolated_danger", "wreck", "obstruction"}
)
# Built-in hand hazards, always added even when OSM omits them (03-RESEARCH "Hazards found in
# OSM"): the Plić Sestre shoal in Zlarinski kanal, a course mark rounded at 0.3 nm.
HAND_HAZARDS = (
    ("Plić Sestre, balise (OSM node 498394251)", 43.684627, 15.811626),
    ("Plić Sestre, roche (OSM node 8883790953)", 43.684411, 15.811043),
)
MAX_USER_HAZARDS_BYTES = 5 * 1024 * 1024
# Land is clipped to RACE_BBOX + this margin (deg) so shore margins at the grid edge are right.
WORK_PAD_DEG = 0.05


class LandPrepError(ValueError):
    """Prep failure with a message for the navigator (French)."""


# ------------------------------------------------------------------------------ Overpass
def _cache_path(cache_dir: Path, query: str) -> Path:
    return cache_dir / f"osm-{hashlib.sha256(query.encode()).hexdigest()[:16]}.json"


def _finite_ll(p: Any) -> bool:
    return (
        isinstance(p, dict)
        and all(isinstance(p.get(k), int | float) for k in ("lat", "lon"))
        and math.isfinite(p["lat"])
        and math.isfinite(p["lon"])
        and -90 <= p["lat"] <= 90
        and -180 <= p["lon"] <= 180
    )


def validate_overpass(d: Any) -> dict:
    """Schema check of an Overpass JSON response before any geometry work."""
    if not isinstance(d, dict) or not isinstance(d.get("elements"), list):
        raise LandPrepError("réponse Overpass invalide : liste 'elements' absente")
    for e in d["elements"]:
        if not isinstance(e, dict) or e.get("type") not in ("node", "way", "relation"):
            raise LandPrepError("réponse Overpass invalide : élément sans type node/way/relation")
        if not isinstance(e.get("id"), int):
            raise LandPrepError("réponse Overpass invalide : élément sans id entier")
        if e["type"] == "node" and not _finite_ll(e):
            raise LandPrepError(f"réponse Overpass invalide : nœud {e['id']} sans lat/lon finies")
        geom = e.get("geometry")
        if geom is not None and (
            not isinstance(geom, list) or not all(_finite_ll(p) for p in geom)
        ):
            raise LandPrepError(f"réponse Overpass invalide : géométrie de {e['type']} {e['id']}")
        if e["type"] == "relation":
            members = e.get("members", [])
            if not isinstance(members, list):
                raise LandPrepError(f"réponse Overpass invalide : membres de la relation {e['id']}")
            for m in members:
                g = m.get("geometry") if isinstance(m, dict) else None
                if g is not None and (not isinstance(g, list) or not all(_finite_ll(p) for p in g)):
                    raise LandPrepError(
                        f"réponse Overpass invalide : géométrie d'un membre de {e['id']}"
                    )
        if "tags" in e and not isinstance(e["tags"], dict):
            raise LandPrepError(f"réponse Overpass invalide : tags de {e['type']} {e['id']}")
    return d


def _download(query: str) -> bytes:
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
        method="POST",
    )
    chunks, total = [], 0
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (fixed https URL)
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise LandPrepError(
                    f"réponse Overpass trop grande (> {MAX_RESPONSE_BYTES // 2**20} Mo), abandon"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def fetch_overpass(
    query: str, cache_dir: Path = DEFAULT_CACHE, offline: bool = False, refresh: bool = False
) -> dict:
    """Run an Overpass query, caching the raw response (atomic) for offline reruns."""
    cache_dir = Path(cache_dir)
    path = _cache_path(cache_dir, query)
    if path.exists() and not refresh:
        print(f"  cache OSM : {path}")
        return validate_overpass(json.loads(path.read_bytes()))
    if offline:
        raise LandPrepError(
            f"mode hors ligne : pas de réponse Overpass en cache ({path}). "
            "Relancer une fois avec internet, sans --offline."
        )
    print(f"  requête Overpass ({OVERPASS_URL}) ...")
    try:
        data = _download(query)
    except OSError as exc:
        raise LandPrepError(f"Overpass injoignable : {exc}") from None
    try:
        d = validate_overpass(json.loads(data))
    except json.JSONDecodeError as exc:
        raise LandPrepError(f"réponse Overpass non JSON : {exc}") from None
    cache_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, data)
    print(f"  {len(d['elements'])} éléments, mis en cache dans {path}")
    return d


def osm_base(d: dict) -> str:
    v = d.get("osm3s", {}).get("timestamp_osm_base", "") if isinstance(d, dict) else ""
    return v if isinstance(v, str) else ""


# ------------------------------------------------------------------------------ geometry
def _line_m(geometry: list[dict], frame: Frame) -> LineString | None:
    if len(geometry) < 2:
        return None
    x, y = frame.to_m([p["lat"] for p in geometry], [p["lon"] for p in geometry])
    return LineString(np.column_stack([x, y]))


def bbox_m(bbox: tuple[float, float, float, float], frame: Frame) -> tuple[float, ...]:
    """(lon_min, lat_min, lon_max, lat_max) -> (x0, y0, x1, y1) metres."""
    x0, y0 = frame.to_m(bbox[1], bbox[0])
    x1, y1 = frame.to_m(bbox[3], bbox[2])
    return float(x0), float(y0), float(x1), float(y1)


def coastline_to_land(
    elements: list[dict],
    frame: Frame = DEFAULT_FRAME,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[Any, dict]:
    """OSM coastline ways -> land (shapely, local metres), OSM rule "land on the left".

    Chains are merged, clipped to the work rectangle, noded with its boundary and polygonized;
    each face is oriented CCW (so it lies on the left of its rings) and classified by the first
    coastline segment found on its boundary: same direction = land, reversed = water.
    Raises LandPrepError when a face cannot be classified.
    """
    if bbox is None:
        p = WORK_PAD_DEG
        bbox = (RACE_BBOX[0] - p, RACE_BBOX[1] - p, RACE_BBOX[2] + p, RACE_BBOX[3] + p)
    rect = box(*bbox_m(bbox, frame))
    lines = []
    for e in elements:
        if e.get("type") == "way" and e.get("tags", {}).get("natural", "coastline") == "coastline":
            ls = _line_m(e.get("geometry") or [], frame)
            if ls is not None:
                lines.append(ls)
    info = {"ways": len(lines), "faces": 0, "land_faces": 0, "unclassified": 0}
    if not lines:
        return shapely.Polygon(), info
    merged = linemerge(lines)
    merged = list(getattr(merged, "geoms", [merged]))
    parts = []
    for ls in merged:
        g = rect.intersection(ls)
        if not g.is_empty:
            parts.extend(
                x for x in getattr(g, "geoms", [g]) if x.geom_type == "LineString" and x.length > 0
            )
    coast_dir: set[tuple] = set()
    for ls in parts:
        c = np.round(np.asarray(ls.coords), 3)
        coast_dir.update((tuple(c[i]), tuple(c[i + 1])) for i in range(len(c) - 1))
    land = []
    faces = list(polygonize(unary_union([*parts, rect.exterior])))
    for f in faces:
        f = shapely.geometry.polygon.orient(f, 1.0)
        verdict = None
        for ring in [f.exterior, *f.interiors]:
            c = np.round(np.asarray(ring.coords), 3)
            for i in range(len(c) - 1):
                a, b = tuple(c[i]), tuple(c[i + 1])
                if (a, b) in coast_dir:
                    verdict = True
                    break
                if (b, a) in coast_dir:
                    verdict = False
                    break
            if verdict is not None:
                break
        if verdict is None:
            info["unclassified"] += 1
        elif verdict:
            land.append(f)
    info["faces"] = len(faces)
    info["land_faces"] = len(land)
    if info["unclassified"]:
        raise LandPrepError(
            f"{info['unclassified']} faces de trait de côte non classées (terre/mer) : "
            "données OSM incohérentes, masque refusé"
        )
    return unary_union(land), info


def rasterize(geom, x0: float, y0: float, cell: float, nx: int, ny: int) -> np.ndarray:
    """Even-odd scanline fill: True where the cell centre (x0+(c+.5)cell, y0+(r+.5)cell) is
    inside the polygon(s). Vectorised over all ring edges (no GDAL)."""
    polys = [
        g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and not g.is_empty
    ]
    if not polys:
        return np.zeros((ny, nx), dtype=bool)
    rings = []
    for poly in polys:
        rings.append(np.asarray(poly.exterior.coords))
        rings.extend(np.asarray(r.coords) for r in poly.interiors)
    a = np.concatenate([r[:-1] for r in rings])
    b = np.concatenate([r[1:] for r in rings])
    ya, yb = (a[:, 1] - y0) / cell - 0.5, (b[:, 1] - y0) / cell - 0.5
    r0 = np.clip(np.ceil(np.minimum(ya, yb)).astype(np.int64), 0, ny)
    r1 = np.clip(np.ceil(np.maximum(ya, yb)).astype(np.int64), 0, ny)  # half-open rows
    n = np.maximum(r1 - r0, 0)
    idx = np.repeat(np.arange(len(a)), n)
    rows = np.repeat(r0, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    t = (rows - ya[idx]) / (yb[idx] - ya[idx])
    xc = (a[idx, 0] + t * (b[idx, 0] - a[idx, 0]) - x0) / cell - 0.5
    cols = np.clip(np.ceil(xc).astype(np.int64), 0, nx)
    # uint8 toggles: wrap-around keeps the parity, which is all the even-odd rule needs
    tog = np.zeros((ny, nx + 1), dtype=np.uint8)
    np.add.at(tog, (rows, cols), 1)
    return (np.cumsum(tog, axis=1, dtype=np.uint8)[:, :nx] & 1).astype(bool)


# ------------------------------------------------------------------------------ hazards
def _geom_extent(geom):
    """Point -> 50 m disc; line -> 25 m buffer; polygon(s) as they are."""
    if geom.geom_type in ("Point", "MultiPoint"):
        return geom.buffer(DISC_M, quad_segs=8)
    if geom.geom_type in ("LineString", "MultiLineString"):
        return geom.buffer(WAY_BUFFER_M, quad_segs=8)
    return geom


def _way_geom(geometry: list[dict], frame: Frame, area: bool):
    """Closed way tagged as an area -> polygon, else its line (None when degenerate)."""
    ls = _line_m(geometry, frame)
    if ls is None:
        return None
    if area and ls.is_closed and len(ls.coords) >= 4:
        poly = shapely.Polygon(ls.coords)
        return poly if poly.is_valid and poly.area > 0 else shapely.make_valid(poly)
    return ls


def _relation_geom(e: dict, frame: Frame):
    lines = [
        ls
        for m in e.get("members", [])
        if isinstance(m, dict) and m.get("geometry")
        for ls in [_line_m(m["geometry"], frame)]
        if ls is not None
    ]
    if not lines:
        return None
    polys = list(polygonize(unary_union(lines)))
    # holes (inner rings) come out as faces too: filled, which is conservative
    return unary_union(polys) if polys else shapely.MultiLineString(lines)


def classify_hazards(elements: list[dict], frame: Frame) -> tuple[list, list, dict[str, int]]:
    """Overpass hazard elements -> (geometries that get the hazard margin, submerged-rock points,
    counts per class). Metres in the local frame."""
    marked, submerged = [], []
    counts: dict[str, int] = {}

    def add(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    for e in elements:
        tags = e.get("tags") or {}
        st, nat = tags.get("seamark:type"), tags.get("natural")
        kind = e.get("type")
        area = nat in ("reef", "shoal") or st == "obstruction"
        if kind == "node":
            geom = shapely.Point(*frame.to_m(e["lat"], e["lon"]))
        elif kind == "way":
            geom = _way_geom(e.get("geometry") or [], frame, area)
        else:
            geom = _relation_geom(e, frame)
        if geom is None or geom.is_empty:
            add("ignored")
            continue
        if st == "rock" and kind == "node":
            if tags.get("seamark:rock:water_level") in AWASH_LEVELS:
                marked.append(_geom_extent(geom))
                add("rock_awash")
            else:  # submerged, or no water level: depth unknown
                submerged.append(geom)
                add("rock_submerged")
        elif st in MARGIN_SEAMARKS:
            # obstruction/wreck areas: their outline plus 25 m, like the lines
            g = geom if geom.geom_type in ("Point", "MultiPoint") else geom.buffer(WAY_BUFFER_M)
            marked.append(_geom_extent(g))
            add(st)
        elif nat in ("reef", "shoal"):
            marked.append(_geom_extent(geom))
            add(f"natural_{nat}")
        else:
            add("ignored")
    return marked, submerged, counts


def _bad_hazards(msg: str) -> LandPrepError:
    return LandPrepError(f"fichier de dangers invalide : {msg}")


def _positions(coords: Any, depth: int) -> Any:
    """Validate GeoJSON coordinates nested `depth` levels deep ([lon, lat] finite, in range)."""
    if depth == 0:
        if (
            not isinstance(coords, list)
            or len(coords) < 2
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in coords[:2])
            or not all(math.isfinite(v) for v in coords[:2])
            or not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90)
        ):
            raise _bad_hazards(f"coordonnée {coords!r} (attendu [lon, lat] finis)")
        return (float(coords[0]), float(coords[1]))
    if not isinstance(coords, list) or not coords:
        raise _bad_hazards("liste de coordonnées vide ou absente")
    return [_positions(c, depth - 1) for c in coords]


def _geojson_geom(g: Any, frame: Frame) -> list:
    if not isinstance(g, dict):
        raise _bad_hazards("géométrie absente")
    t = g.get("type")

    def xy(p):
        return frame.to_m(p[1], p[0])

    def ring(r):
        if len(r) < 4 or r[0] != r[-1]:
            raise _bad_hazards("anneau de polygone non fermé ou trop court")
        return [xy(p) for p in r]

    def polygon(rings):
        poly = shapely.Polygon(ring(rings[0]), [ring(r) for r in rings[1:]])
        return poly if poly.is_valid else shapely.make_valid(poly)

    c = g.get("coordinates")
    if t == "Point":
        return [shapely.Point(xy(_positions(c, 0))).buffer(DISC_M, quad_segs=8)]
    if t == "MultiPoint":
        return [shapely.Point(xy(p)).buffer(DISC_M, quad_segs=8) for p in _positions(c, 1)]
    if t == "LineString":
        pts = _positions(c, 1)
        if len(pts) < 2:
            raise _bad_hazards("ligne de moins de 2 points")
        return [shapely.LineString([xy(p) for p in pts]).buffer(WAY_BUFFER_M, quad_segs=8)]
    if t == "MultiLineString":
        return [
            x
            for line in c or []
            for x in _geojson_geom({"type": "LineString", "coordinates": line}, frame)
        ]
    if t == "Polygon":
        return [polygon(_positions(c, 2))]
    if t == "MultiPolygon":
        return [polygon(rings) for rings in _positions(c, 3)]
    if t == "GeometryCollection" and isinstance(g.get("geometries"), list):
        return [x for sub in g["geometries"] for x in _geojson_geom(sub, frame)]
    raise _bad_hazards(f"type de géométrie non pris en charge : {t!r}")


def load_user_hazards(path: str | Path, frame: Frame = DEFAULT_FRAME) -> list:
    """--hazards FILE.geojson: Points (50 m discs), LineStrings (25 m buffer), Polygons, all given
    the hazard margin by the caller. LandPrepError (French) on anything invalid."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise _bad_hazards(f"{path} illisible ({exc})") from None
    if size > MAX_USER_HAZARDS_BYTES:
        raise LandPrepError(f"fichier de dangers trop gros ({size} octets, max 5 Mo) : {path}")
    try:
        d = json.loads(path.read_bytes())
    except (ValueError, OSError) as exc:
        raise _bad_hazards(f"{path} n'est pas du JSON ({exc})") from None
    if not isinstance(d, dict):
        raise _bad_hazards("objet GeoJSON attendu")
    if d.get("type") == "FeatureCollection":
        feats = d.get("features")
        if not isinstance(feats, list):
            raise _bad_hazards("'features' doit être une liste")
        geoms = [f.get("geometry") if isinstance(f, dict) else None for f in feats]
    elif d.get("type") == "Feature":
        geoms = [d.get("geometry")]
    else:
        geoms = [d]
    out = [x for g in geoms for x in _geojson_geom(g, frame)]
    if not out:
        raise _bad_hazards("aucune géométrie")
    return out


# ------------------------------------------------------------------------------ build
def grid_for(
    bbox: tuple[float, float, float, float], cell_m: float, frame: Frame
) -> tuple[float, float, int, int]:
    """Grid covering bbox: SW corner (x0, y0) metres and (nx, ny)."""
    x0, y0, x1, y1 = bbox_m(bbox, frame)
    return x0, y0, int(math.ceil((x1 - x0) / cell_m)), int(math.ceil((y1 - y0) / cell_m))


def _npz_bytes(**arrays: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def write_mask(
    out_dir: Path,
    mask: np.ndarray,
    raw: np.ndarray,
    *,
    x0_m: float,
    y0_m: float,
    cell_m: float,
    frame: Frame,
    margin_m: float,
    hazard_margin_m: float,
    source: str,
    base: str,
    extra: dict | None = None,
) -> dict:
    """landmask.npz (packbits along axis 1, 0-d scalars/strings) then the sha256 sidecar."""
    out_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _npz_bytes(
        mask=np.packbits(mask, axis=1),
        raw=np.packbits(raw, axis=1),
        shape=np.array(mask.shape, dtype=np.int64),
        x0_nm=np.float64(x0_m / NM_M),
        y0_nm=np.float64(y0_m / NM_M),
        cell_nm=np.float64(cell_m / NM_M),
        cell_m=np.float64(cell_m),
        lat0=np.float64(frame.lat0),
        lon0=np.float64(frame.lon0),
        margin_m=np.float64(margin_m),
        hazard_margin_m=np.float64(hazard_margin_m),
        source=np.str_(source),
        osm_base=np.str_(base),
        created=np.str_(created),
    )
    atomic_write_bytes(out_dir / "landmask.npz", data)
    side = {
        "file": "landmask.npz",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "created": created,
        "source": source,
        "osm_base": base,
        "cell_m": cell_m,
        "margin_m": margin_m,
        "hazard_margin_m": hazard_margin_m,
        "frame": {"lat0": frame.lat0, "lon0": frame.lon0},
        **(extra or {}),
    }
    atomic_write_json(out_dir / "landmask.json", side)
    return side


def build_mask(
    out_dir: str | Path,
    cell_m: float = 25.0,
    shore_margin_m: float = 100.0,
    hazard_margin_m: float = 200.0,
    *,
    cache_dir: str | Path = DEFAULT_CACHE,
    offline: bool = False,
    refresh: bool = False,
    frame: Frame = DEFAULT_FRAME,
    bbox: tuple[float, float, float, float] = RACE_BBOX,
    submerged_rocks: bool = True,
    hazards_file: str | Path | None = None,
) -> dict:
    """Fetch (or reuse) OSM data, build land + margins + hazards, write landmask.npz + .json.

    mask = land + shore margin, OR hazards (+ hazard margin), OR submerged-rock discs;
    raw = land only."""
    t0 = time.perf_counter()
    out_dir = Path(out_dir)
    cache_dir = Path(cache_dir)
    coast = fetch_overpass(COASTLINE_QUERY, cache_dir, offline=offline, refresh=refresh)
    haz = fetch_overpass(HAZARD_QUERY, cache_dir, offline=offline, refresh=refresh)
    pad = WORK_PAD_DEG
    work = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    land, info = coastline_to_land(coast["elements"], frame, work)
    print(
        f"  trait de côte : {info['ways']} chemins, {info['faces']} faces, "
        f"{info['land_faces']} faces terre, {info['unclassified']} non classées"
    )
    marked, submerged, counts = classify_hazards(haz["elements"], frame)
    for _name, lat, lon in HAND_HAZARDS:
        marked.append(shapely.Point(*frame.to_m(lat, lon)).buffer(DISC_M))
    counts["hand"] = len(HAND_HAZARDS)
    if hazards_file is not None:
        user = load_user_hazards(hazards_file, frame)
        marked.extend(user)
        counts["user"] = len(user)
    print("  dangers : " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if not submerged_rocks:
        print("  roches immergées ignorées (--no-submerged-rocks)")
    x0, y0, nx, ny = grid_for(bbox, cell_m, frame)
    raw = rasterize(land, x0, y0, cell_m, nx, ny)
    obst = land.buffer(shore_margin_m, quad_segs=8) if shore_margin_m > 0 else land
    mask = rasterize(obst, x0, y0, cell_m, nx, ny) | raw
    hz = unary_union(marked).buffer(hazard_margin_m, quad_segs=8)
    mask |= rasterize(hz, x0, y0, cell_m, nx, ny)
    if submerged_rocks and submerged:
        discs = shapely.MultiPoint(submerged).buffer(DISC_M, quad_segs=8)
        mask |= rasterize(discs, x0, y0, cell_m, nx, ny)
    side = write_mask(
        out_dir,
        mask,
        raw,
        x0_m=x0,
        y0_m=y0,
        cell_m=cell_m,
        frame=frame,
        margin_m=shore_margin_m,
        hazard_margin_m=hazard_margin_m,
        source=SOURCE,
        base=osm_base(coast),
        extra={
            "land_faces": info["land_faces"],
            "hazards": dict(sorted(counts.items())),
            "submerged_rocks": submerged_rocks,
            "osm_base_hazards": osm_base(haz),
            "user_hazards": Path(hazards_file).name if hazards_file is not None else None,
        },
    )
    print(
        f"  grille {ny} x {nx} = {nx * ny / 1e6:.1f} Mcellules de {cell_m:g} m, "
        f"bloqué {mask.mean() * 100:.1f} % (terre {raw.mean() * 100:.1f} %), "
        f"{side['bytes'] / 1024:.0f} Ko, {time.perf_counter() - t0:.1f} s"
    )
    print(f"  écrit {out_dir / 'landmask.npz'} (sha256 {side['sha256'][:16]}…)")
    return side


# ------------------------------------------------------------------------------ check
def _resolve(path: Path) -> tuple[Path, Path]:
    """DIR (holding landmask.npz) or FILE.npz -> (npz, sidecar json)."""
    if path.is_dir():
        return path / "landmask.npz", path / "landmask.json"
    return path, path.with_suffix(".json")


def check(path: str | Path) -> int:
    npz, side_path = _resolve(Path(path))
    try:
        lm = LandMask.load(npz)
    except ValueError as exc:
        print(f"ÉCHEC : {exc}")
        return 1
    ny, nx = lm.shape
    print(f"masque {npz}")
    print(
        f"  cellule {lm.cell_m:g} m, grille {ny} x {nx}, marge côte {lm.margin_m:g} m, "
        f"marge dangers {lm.hazard_margin_m:g} m"
    )
    print(f"  source {lm.source}, OSM base {lm.osm_base}, créé {lm.created}")
    print(f"  bloqué {lm.mask.mean() * 100:.1f} % (terre {lm.raw.mean() * 100:.1f} %)")
    if side_path.exists():
        side = json.loads(side_path.read_bytes())
        digest = hashlib.sha256(npz.read_bytes()).hexdigest()
        if side.get("sha256") != digest:
            print(f"ÉCHEC : sha256 du masque différent de {side_path.name}")
            return 1
        print(f"  sha256 conforme à {side_path.name}")
    else:
        print(f"  attention : pas de fichier {side_path.name} (sha256 non vérifié)")
    return 0


# ------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jabuka-prep land", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="construire landmask.npz depuis OSM")
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--cell-m", type=float, default=25.0)
    b.add_argument("--shore-margin-m", type=float, default=100.0)
    b.add_argument("--hazard-margin-m", type=float, default=200.0)
    b.add_argument(
        "--submerged-rocks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="roches immergées OSM (profondeur inconnue) en disques de 50 m (défaut : oui)",
    )
    b.add_argument("--hazards", type=Path, help="dangers en plus (GeoJSON, lon/lat WGS84)")
    b.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    b.add_argument("--offline", action="store_true", help="n'utiliser que le cache OSM")
    b.add_argument("--refresh", action="store_true", help="ignorer le cache et re-télécharger")
    c = sub.add_parser("check", help="vérifier un masque (DIR ou FICHIER.npz)")
    c.add_argument("path", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return check(args.path)
    if not (5 <= args.cell_m <= 200) or args.shore_margin_m < 0 or args.hazard_margin_m < 0:
        ap.error("cellule entre 5 et 200 m, marges >= 0")
    try:
        build_mask(
            args.out,
            args.cell_m,
            args.shore_margin_m,
            args.hazard_margin_m,
            cache_dir=args.cache,
            offline=args.offline,
            refresh=args.refresh,
            submerged_rocks=args.submerged_rocks,
            hazards_file=args.hazards,
        )
    except LandPrepError as exc:
        print(f"ÉCHEC : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
