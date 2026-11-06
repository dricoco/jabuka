"""Race-pack loader and weather coverage report (GRIB-02), on the Pi and in ``jabuka-prep check``.

numpy + stdlib only, no clock reads. Every pack file has a fixed name inside the pack directory;
every npz is checked against the sha256 of its ``<stem>.json`` sidecar and loaded with
``np.load(..., allow_pickle=False)``. Content problems never raise: they become French strings in
``RacePack.errors`` and that component is ``None`` (a bad optional file disables its factor).

Coverage rules (RESEARCH Pattern 3):
1. wind times cover the race window, else alert "MÉTÉO INCOMPLÈTE : ...";
2. a time step above 1 h inside the window is a warning;
3. every mark and every leg (sampled every 1 nm) lies inside the interpolation margin
   ``[lat[1], lat[-2]] x [lon[1], lon[-2]]`` with finite u/v at every window time, else alert;
4. waves/current get the same checks as warnings (the factor is disabled), absent files are info;
5. ``details["horizon_hold"]`` is true when the wind ends before the window end (the router then
   holds the last field).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import numpy as np

from jabuka.route.frame import RACE_BBOX

log = logging.getLogger(__name__)

WIND_FILE = "wind.npz"
WAVES_FILE = "waves.npz"
CURRENT_FILE = "current.npz"
LANDMASK_FILE = "landmask.npz"
GEOFIELDS_FILE = "geofields.npz"
POLAR_FILE = "polar.json"

MAX_NPZ_BYTES = 200 * 1024 * 1024
ALERT_PREFIX = "MÉTÉO INCOMPLÈTE : "
DEFAULT_WINDOW_LOCAL = ("2026-11-13T18:00", "2026-11-15T10:00")
LOCAL_TZ = "Europe/Zagreb"
MAX_STEP_S = 3600
SAMPLE_NM = 1.0

# component -> (required fields, optional fields, French label)
_SPECS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "wind": (("u", "v"), (), "vent"),
    "waves": (("hs",), ("mwd",), "vagues"),
    "current": (("u", "v"), (), "courant"),
}


@dataclass(frozen=True, eq=False)
class Grid:
    t: np.ndarray  # int64 [T] UTC epoch s, strictly increasing
    lat: np.ndarray  # float64 [NY] ascending
    lon: np.ndarray  # float64 [NX] ascending
    arrays: dict[str, np.ndarray]  # float32 [T, NY, NX]


@dataclass
class RacePack:
    dir: Path
    wind: Grid | None = None
    waves: Grid | None = None
    current: Grid | None = None
    landmask_path: Path | None = None
    geofields_path: Path | None = None
    polar_path: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarkPos:
    id: str
    name: str
    lat: float
    lon: float
    radius_nm: float


@dataclass(frozen=True)
class MarksDoc:
    marks: dict[str, MarkPos]
    templates: dict[str, list[tuple[str, str]]]


@dataclass(frozen=True)
class RaceWindow:
    start_utc: int
    end_utc: int


@dataclass
class CoverageReport:
    ok: bool
    alerts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    infos: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- loading


def _check_grid(
    z: Any, name: str, required: tuple[str, ...], optional: tuple[str, ...]
) -> tuple[Grid | None, dict[str, Any], str | None]:
    """Validate an opened NpzFile. Returns (grid, string meta, error)."""
    keys = set(z.files)
    missing = [k for k in ("t", "lat", "lon", *required) if k not in keys]
    if missing:
        return None, {}, f"{name} : clés manquantes {', '.join(missing)}"
    try:
        t = z["t"]
        lat = z["lat"]
        lon = z["lon"]
        arrays = {k: z[k] for k in (*required, *(o for o in optional if o in keys))}
    except ValueError as exc:  # object arrays refused by allow_pickle=False
        return None, {}, f"{name} : contenu refusé ({exc})"
    if t.dtype != np.int64 or t.ndim != 1 or t.size < 1:
        return None, {}, f"{name} : t doit être int64 [T] (reçu {t.dtype} {t.shape})"
    for axis_name, axis in (("lat", lat), ("lon", lon)):
        if axis.dtype != np.float64 or axis.ndim != 1 or axis.size < 2:
            return (
                None,
                {},
                f"{name} : {axis_name} doit être float64 [N>=2] ({axis.dtype} {axis.shape})",
            )
        if not np.all(np.isfinite(axis)) or not np.all(np.diff(axis) > 0):
            return None, {}, f"{name} : {axis_name} non strictement croissant"
    if t.size > 1 and not np.all(np.diff(t) > 0):
        return None, {}, f"{name} : temps non strictement croissants"
    shape = (t.size, lat.size, lon.size)
    for key, arr in arrays.items():
        if arr.dtype != np.float32:
            return None, {}, f"{name} : {key} doit être float32 (reçu {arr.dtype})"
        if arr.shape != shape:
            return None, {}, f"{name} : {key} de forme {arr.shape}, attendu {shape}"
        finite_per_t = np.isfinite(arr.reshape(shape[0], -1)).any(axis=1)
        if not finite_per_t.all():
            bad = int(np.flatnonzero(~finite_per_t)[0])
            return None, {}, f"{name} : {key} sans aucune valeur valide au pas {bad}"
    meta: dict[str, Any] = {}
    for key in ("model", "run", "source"):
        if key in keys:
            try:
                val = z[key]
            except ValueError:
                return None, {}, f"{name} : contenu refusé ({key})"
            if val.dtype.kind == "U" and val.ndim == 0:
                meta[key] = str(val)
    return Grid(t=t, lat=lat, lon=lon, arrays=arrays), meta, None


def _load_component(pack_dir: Path, comp: str) -> tuple[Grid | None, dict[str, Any], str | None]:
    required, optional, _label = _SPECS[comp]
    name = f"{comp}.npz"
    path = pack_dir / name
    side_path = pack_dir / f"{comp}.json"
    try:
        size = path.stat().st_size
    except OSError:
        return None, {}, None  # absent: not an error at load time (coverage reports it)
    if size > MAX_NPZ_BYTES:
        return None, {}, f"{name} : fichier trop gros ({size} octets)"
    try:
        sidecar = json.loads(side_path.read_text(encoding="utf-8"))
        expected = str(sidecar["sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, {}, f"{name} : fiche {side_path.name} absente ou illisible"
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, {}, f"{name} : lecture impossible ({exc})"
    if hashlib.sha256(data).hexdigest() != expected:
        return (
            None,
            {},
            f"{name} : empreinte sha256 différente de {side_path.name} (fichier altéré)",
        )
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            grid, meta, err = _check_grid(z, name, required, optional)
    except Exception as exc:  # noqa: BLE001 - any parse failure becomes an error string
        return None, {}, f"{name} : illisible ({type(exc).__name__})"
    if err:
        return None, {}, err
    meta = {**sidecar, **meta} if isinstance(sidecar, dict) else meta
    return grid, meta, None


def load_pack(pack_dir: str | Path) -> RacePack:
    """Load and validate the race pack in ``pack_dir`` (fixed file names only)."""
    pack_dir = Path(pack_dir)
    pack = RacePack(dir=pack_dir)
    for comp in ("wind", "waves", "current"):
        grid, meta, err = _load_component(pack_dir, comp)
        setattr(pack, comp, grid)
        if meta:
            pack.meta[comp] = meta
        if err:
            pack.errors.append(err)
    if pack.wind is None and not (pack_dir / WIND_FILE).exists():
        pack.errors.append(f"{WIND_FILE} absent du pack {pack_dir}")
    for attr, fname in (
        ("landmask_path", LANDMASK_FILE),
        ("geofields_path", GEOFIELDS_FILE),
        ("polar_path", POLAR_FILE),
    ):
        p = pack_dir / fname
        setattr(pack, attr, p if p.is_file() else None)
    return pack


# --------------------------------------------------------------------------- marks / window


def read_marks_file(path: str | Path) -> MarksDoc:
    """Parse the Phase 2 marks.json format; ValueError (French) on a malformed file."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"fichier de marques illisible : {path} ({exc})") from exc
    marks: dict[str, MarkPos] = {}
    try:
        for m in doc["marks"]:
            lat, lon = float(m["lat"]), float(m["lon"])
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise ValueError(f"position invalide pour {m['id']}")
            mid = str(m["id"])
            marks[mid] = MarkPos(
                id=mid,
                name=str(m.get("name", mid)),
                lat=lat,
                lon=lon,
                radius_nm=float(m.get("radius_nm", 0.0)),
            )
        templates: dict[str, list[tuple[str, str]]] = {}
        for key, seq in dict(doc.get("templates", {})).items():
            items = [(str(e["mark_id"]), str(e.get("side", "none"))) for e in seq]
            for mid, _side in items:
                if mid not in marks:
                    raise ValueError(f"le parcours {key} cite une marque inconnue : {mid}")
            templates[str(key)] = items
    except (KeyError, TypeError) as exc:
        raise ValueError(f"fichier de marques mal formé : {path} ({exc})") from exc
    return MarksDoc(marks=marks, templates=templates)


def _local_tz(tz: str = LOCAL_TZ) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError / missing tzdata
        log.warning("fuseau %s introuvable (tzdata absent) : décalage fixe +01:00", tz)
        return timezone(timedelta(hours=1))


def _parse_local(iso: str, tzi: tzinfo) -> int:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tzi)
    return int(dt.timestamp())


def window_from_local(start_iso: str, end_iso: str, tz: str = LOCAL_TZ) -> RaceWindow:
    """Local wall-clock ISO times (Europe/Zagreb by default) -> RaceWindow in UTC epoch seconds."""
    tzi = _local_tz(tz)
    start, end = _parse_local(start_iso, tzi), _parse_local(end_iso, tzi)
    if end <= start:
        raise ValueError(f"fenêtre invalide : fin {end_iso} avant début {start_iso}")
    return RaceWindow(start_utc=start, end_utc=end)


def fmt_local(epoch: int | float, tz: str = LOCAL_TZ) -> str:
    """'14/11 19:00' in local race time."""
    return datetime.fromtimestamp(int(epoch), UTC).astimezone(_local_tz(tz)).strftime("%d/%m %H:%M")


def course_points_legs(
    doc: MarksDoc, template_keys: tuple[str, ...] | None = None
) -> tuple[
    list[tuple[str, float, float]], list[tuple[str, tuple[float, float], tuple[float, float]]]
]:
    """All marks used by the templates (points) and consecutive template marks (legs)."""
    keys = template_keys if template_keys is not None else tuple(sorted(doc.templates))
    points: list[tuple[str, float, float]] = []
    legs: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    seen_p: set[str] = set()
    seen_l: set[frozenset[str]] = set()
    for key in keys:
        seq = [m for m, _side in doc.templates.get(key, [])]
        for mid in seq:
            if mid not in seen_p:
                seen_p.add(mid)
                m = doc.marks[mid]
                points.append((m.name, m.lat, m.lon))
        for a, b in zip(seq, seq[1:], strict=False):
            pair = frozenset((a, b))
            if a == b or pair in seen_l:
                continue
            seen_l.add(pair)
            ma, mb = doc.marks[a], doc.marks[b]
            legs.append((f"{key} {ma.name} → {mb.name}", (ma.lat, ma.lon), (mb.lat, mb.lon)))
    if not keys:
        for m in doc.marks.values():
            points.append((m.name, m.lat, m.lon))
    return points, legs


# --------------------------------------------------------------------------- coverage


def _sample_leg(a: tuple[float, float], b: tuple[float, float]) -> np.ndarray:
    lat0 = math.radians((a[0] + b[0]) / 2.0)
    dy = (b[0] - a[0]) * 60.0
    dx = (b[1] - a[1]) * 60.0 * math.cos(lat0)
    n = max(2, int(math.ceil(math.hypot(dx, dy) / SAMPLE_NM)) + 1)
    f = np.linspace(0.0, 1.0, n)
    return np.column_stack((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))


def _window_slice(t: np.ndarray, window: RaceWindow) -> slice:
    i0 = max(int(np.searchsorted(t, window.start_utc, side="right")) - 1, 0)
    i1 = min(int(np.searchsorted(t, window.end_utc, side="left")), t.size - 1)
    return slice(min(i0, i1), i1 + 1)


def _point_problem(grid: Grid, lat: float, lon: float, tsl: slice) -> str | None:
    """None if (lat, lon) is inside the interpolation margin with finite fields, else a reason."""
    la, lo = grid.lat, grid.lon
    if not (la[1] <= lat <= la[-2] and lo[1] <= lon <= lo[-2]):
        return "hors de la zone couverte"
    j = int(np.clip(np.searchsorted(la, lat, side="right") - 1, 0, la.size - 2))
    i = int(np.clip(np.searchsorted(lo, lon, side="right") - 1, 0, lo.size - 2))
    for arr in grid.arrays.values():
        if not np.all(np.isfinite(arr[tsl, j : j + 2, i : i + 2])):
            return "valeurs manquantes (NaN)"
    return None


def _grid_checks(
    grid: Grid,
    label: str,
    points: list[tuple[str, float, float]],
    legs: list[tuple[str, tuple[float, float], tuple[float, float]]],
    window: RaceWindow,
) -> tuple[list[str], list[str]]:
    """(problems, step_warnings) for one component; problems are message bodies without prefix."""
    problems: list[str] = []
    step_warnings: list[str] = []
    t = grid.t
    if t[0] > window.start_utc:
        problems.append(
            f"{label} à partir du {fmt_local(t[0])} seulement, "
            f"début requis {fmt_local(window.start_utc)}"
        )
    if t[-1] < window.end_utc:
        problems.append(
            f"{label} jusqu'au {fmt_local(t[-1])} seulement, "
            f"fin requise {fmt_local(window.end_utc)}"
        )
    tsl = _window_slice(t, window)
    tw = t[tsl]
    if tw.size > 1:
        step = int(np.max(np.diff(tw)))
        if step > MAX_STEP_S:
            step_warnings.append(
                f"{label} : pas de temps de {step / 3600:g} h dans la fenêtre "
                "(interpolé, moins précis)"
            )
    for name, lat, lon in points:
        why = _point_problem(grid, lat, lon, tsl)
        if why:
            problems.append(f"{label} {why} à {name} ({lat:.4f}N {lon:.4f}E)")
    for name, a, b in legs:
        for lat, lon in _sample_leg(a, b):
            why = _point_problem(grid, float(lat), float(lon), tsl)
            if why:
                problems.append(f"{label} {why} sur le bord {name} ({lat:.3f}N {lon:.3f}E)")
                break
    return problems, step_warnings


def _area_holes(grid: Grid, window: RaceWindow) -> int:
    """Wind cells without a value (u or v) that a bilinear stencil inside RACE_BBOX can touch
    (the bbox widened by one grid cell), at the time steps bracketing the race window."""
    lon_min, lat_min, lon_max, lat_max = RACE_BBOX
    iy = np.flatnonzero((grid.lat >= lat_min) & (grid.lat <= lat_max))
    ix = np.flatnonzero((grid.lon >= lon_min) & (grid.lon <= lon_max))
    if iy.size == 0 or ix.size == 0:
        return 0
    y0, y1 = max(0, int(iy[0]) - 1), min(grid.lat.size, int(iy[-1]) + 2)
    x0, x1 = max(0, int(ix[0]) - 1), min(grid.lon.size, int(ix[-1]) + 2)
    tsl = _window_slice(grid.t, window)
    bad = np.zeros(grid.arrays["u"][tsl, y0:y1, x0:x1].shape, dtype=bool)
    for key in ("u", "v"):
        bad |= ~np.isfinite(grid.arrays[key][tsl, y0:y1, x0:x1])
    return int(np.count_nonzero(bad.any(axis=0)))


def coverage(
    pack: RacePack,
    points: list[tuple[str, float, float]],
    legs: list[tuple[str, tuple[float, float], tuple[float, float]]],
    window: RaceWindow,
) -> CoverageReport:
    """GRIB-02 coverage report for the race window, marks and legs (see module docstring)."""
    rep = CoverageReport(ok=True)
    rep.details["window"] = {
        "start_utc": window.start_utc,
        "end_utc": window.end_utc,
        "start_local": fmt_local(window.start_utc),
        "end_local": fmt_local(window.end_utc),
    }
    rep.details["points"] = len(points)
    rep.details["legs"] = len(legs)
    if pack.wind is None:
        reason = next((e for e in pack.errors if e.startswith("wind.npz")), "fichier vent absent")
        rep.alerts.append(f"{ALERT_PREFIX}pas de vent utilisable ({reason})")
        rep.details["horizon_hold"] = False
    else:
        w = pack.wind
        rep.details["wind_first_local"] = fmt_local(w.t[0])
        rep.details["wind_last_local"] = fmt_local(w.t[-1])
        rep.details["horizon_hold"] = bool(w.t[-1] < window.end_utc)
        problems, steps = _grid_checks(w, "vent", points, legs, window)
        rep.alerts.extend(ALERT_PREFIX + p for p in problems)
        rep.warnings.extend(steps)
        holes = _area_holes(w, window)  # 03-REVIEW MD-01: the router would see calms there
        if holes:
            rep.alerts.append(
                f"{ALERT_PREFIX}vent sans valeur sur {holes} cellules de la zone de course "
                "(le routeur y verrait du calme : refaire le pack)"
            )
    for comp, label, absent, factor in (
        (
            "waves",
            "vagues",
            "Vagues absentes : vitesse réduite d'après le vent",
            "facteur vagues désactivé",
        ),
        ("current", "courant", "Courant absent : routage sans courant", "courant désactivé"),
    ):
        grid: Grid | None = getattr(pack, comp)
        if grid is None:
            if (pack.dir / f"{comp}.npz").exists():
                err = next((e for e in pack.errors if e.startswith(f"{comp}.npz")), "invalide")
                rep.warnings.append(f"{label.capitalize()} invalides ({err}) : {factor}")
            else:
                rep.infos.append(absent)
            rep.details[f"{comp}_ok"] = False
            continue
        problems, steps = _grid_checks(grid, label, points, legs, window)
        rep.warnings.extend(f"{p} : {factor}" for p in problems)
        rep.warnings.extend(steps)
        rep.details[f"{comp}_ok"] = not problems
    rep.ok = not rep.alerts
    return rep


def format_report(rep: CoverageReport) -> str:
    """Human-readable French report (coverage.txt, prep output)."""
    lines = ["COUVERTURE MÉTÉO : OK" if rep.ok else "MÉTÉO INCOMPLÈTE"]
    win = rep.details.get("window")
    if win:
        lines.append(
            f"Fenêtre de course : {win['start_local']} → {win['end_local']} (heure locale)"
        )
    if "wind_first_local" in rep.details:
        lines.append(f"Vent : {rep.details['wind_first_local']} → {rep.details['wind_last_local']}")
    if rep.details.get("horizon_hold"):
        lines.append("Au-delà de la dernière échéance, le routage garde le dernier champ de vent.")
    lines.extend(f"ALERTE : {a}" for a in rep.alerts)
    lines.extend(f"Attention : {w}" for w in rep.warnings)
    lines.extend(f"Info : {i}" for i in rep.infos)
    return "\n".join(lines)
