"""jabuka-prep: laptop race-pack builder (weather + land), ``python -m jabuka.prep.cli``.

Subcommands: wind, waves, grib FILE, current FILE.nc, land ... (jabuka.prep.land), geofields
(precomputed router pruning fields per mark), check.
Exit codes: 0 ok, 3 coverage incomplete (files still written), 2 usage/input error.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.resources
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jabuka.route.racepack import (
    DEFAULT_WINDOW_LOCAL,
    RaceWindow,
    course_points_legs,
    coverage,
    format_report,
    load_pack,
    read_marks_file,
    window_from_local,
)

EXIT_OK, EXIT_USAGE, EXIT_INCOMPLETE = 0, 2, 3
GRIB_SUFFIXES = (".grib2", ".grib2.bz2", ".grib", ".grb", ".grb2", ".grib1", ".grb.bz2")
# urllib opener used for DWD listings and downloads; tests replace it (no network in tests)
URL_OPENER: Any = None


class PrepError(Exception):
    """Input/usage problem: printed in French, exit 2."""


def _default_marks() -> Path | None:
    try:
        res = importlib.resources.files("jabuka.nav") / "data" / "marks.json"
        if res.is_file():
            return Path(str(res))
    except (ModuleNotFoundError, TypeError):
        pass
    return None


def _parse_now(value: str | None) -> int:
    if not value:
        return int(datetime.now(UTC).timestamp())
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", default="var/racepack", help="dossier du pack (défaut var/racepack)")
    p.add_argument("--cache", default="var/cache/prep", help="cache de téléchargement")
    p.add_argument("--marks", default=None, help="marks.json (défaut : celui du paquet jabuka.nav)")
    p.add_argument(
        "--window-start",
        default=DEFAULT_WINDOW_LOCAL[0],
        help="début de fenêtre, heure locale ISO (défaut %(default)s)",
    )
    p.add_argument(
        "--window-end",
        default=DEFAULT_WINDOW_LOCAL[1],
        help="fin de fenêtre, heure locale ISO (défaut %(default)s)",
    )
    p.add_argument("--now", default=None, help="heure courante ISO (tests)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jabuka-prep", description="Préparation du pack de course")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("wind", help="vent ICON-EU (DWD) -> wind.npz")
    _common(p)
    p.add_argument(
        "--from-files",
        default=None,
        help="importer des fichiers GRIB locaux (dossier) au lieu de télécharger",
    )
    p.add_argument("--model", default="ICON-EU")
    p.add_argument("--listing-dir", default=None, help="listes DWD enregistrées (tests)")

    p = sub.add_parser("waves", help="vagues EWAM (DWD) -> waves.npz")
    _common(p)
    p.add_argument("--from-files", default=None, help="importer des fichiers GRIB locaux")
    p.add_argument("--listing-dir", default=None, help="listes DWD enregistrées (tests)")

    p = sub.add_parser("grib", help="n'importe quel GRIB1/GRIB2 de vent 10 m -> wind.npz")
    _common(p)
    p.add_argument("file", help="fichier GRIB (prévision de l'organisateur, OpenSkiron, ...)")
    p.add_argument("--name", default="wind", help="nom du fichier écrit (défaut wind)")

    p = sub.add_parser("current", help="courant Copernicus (NetCDF) -> current.npz")
    _common(p)
    p.add_argument("file", help="fichier NetCDF téléchargé avec copernicusmarine")

    p = sub.add_parser("check", help="vérifier le pack et la couverture météo")
    _common(p)

    p = sub.add_parser(
        "geofields", help="champs de distance par l'eau vers chaque marque -> geofields.npz"
    )
    p.add_argument("--marks", required=True, help="marks.json (format Phase 2)")
    p.add_argument("--out", default="var/racepack", help="dossier du pack (avec landmask.npz)")
    p.add_argument(
        "--gcell-m", type=float, default=200.0, help="maille du champ en m (défaut %(default)s)"
    )

    sub.add_parser("land", help="masque terre (jabuka.prep.land)", add_help=False)
    return ap


def _window(args: argparse.Namespace) -> RaceWindow:
    try:
        return window_from_local(args.window_start, args.window_end)
    except ValueError as exc:
        raise PrepError(str(exc)) from exc


def run_check(out_dir: Path, marks: str | None, window: RaceWindow) -> int:
    """load_pack + coverage (the code the Pi runs); print, write coverage.txt, return 0 or 3."""
    from jabuka.prep.wxpack import write_coverage

    marks_path = Path(marks) if marks else _default_marks()
    if marks_path is None:
        raise PrepError("--marks requis : marks.json du paquet jabuka.nav introuvable")
    try:
        doc = read_marks_file(marks_path)
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    pack = load_pack(out_dir)
    for err in pack.errors:
        print(f"Pack : {err}")
    points, legs = course_points_legs(doc)
    rep = coverage(pack, points, legs, window)
    print(format_report(rep))
    path = write_coverage(out_dir, rep)
    print(f"Rapport : {path}")
    return EXIT_OK if rep.ok else EXIT_INCOMPLETE


def _grib_files(directory: str) -> list[Path]:
    d = Path(directory)
    if not d.is_dir():
        raise PrepError(f"dossier introuvable : {d}")
    files = sorted(p for p in d.iterdir() if p.is_file() and p.name.endswith(GRIB_SUFFIXES))
    if not files:
        raise PrepError(f"aucun fichier GRIB dans {d}")
    return files


def _opener() -> Any:
    if URL_OPENER is not None:
        return URL_OPENER
    from jabuka.prep import dwd

    return dwd.safe_urlopen  # LO-07: redirects re-checked against the allowed hosts


def _listings(
    args: argparse.Namespace, variables: Sequence[str], dir_urls: Any, pattern: Any
) -> dict[str, dict[datetime, set[int]]]:
    """{var: {run: steps}} from DWD directory listings (or saved HTML files with --listing-dir)."""
    from jabuka.prep import dwd

    out: dict[str, dict[datetime, set[int]]] = {}
    if args.listing_dir:
        d = Path(args.listing_dir)
        pages = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(d.glob("*.html"))]
        if not pages:
            raise PrepError(f"aucune liste .html dans {d}")
        for var in variables:
            out[var] = dwd.merge_listings(*(dwd.parse_listing(h, pattern(var)) for h in pages))
        return out
    for var in variables:
        pages_by_url = dwd.fetch_listings(dir_urls(var), opener=_opener())
        out[var] = dwd.merge_listings(
            *(dwd.parse_listing(h, pattern(var)) for h in pages_by_url.values())
        )
    return out


def _download_run(
    args: argparse.Namespace,
    model: str,
    variables: Sequence[str],
    dir_urls: Any,
    pattern: Any,
    file_urls: Any,
    window: RaceWindow,
) -> tuple[Any, list[Path], Any]:
    from jabuka.prep import dwd

    listings = _listings(args, variables, dir_urls, pattern)
    choice = dwd.select_run(listings, window, _parse_now(args.now), model)
    for line in choice.skipped if choice else []:
        print(f"{model} : {line}")
    if choice is None:
        raise PrepError(f"{model} : aucun run complet trouvé sur opendata.dwd.de")
    print(
        f"{model} : run {choice.run:%Y-%m-%d %HZ}, échéances +{choice.steps[0]}..+"
        f"{choice.steps[-1]} ({len(choice.steps)})"
    )
    if choice.incomplete:
        print(f"MÉTÉO INCOMPLÈTE : {model} {choice.reason} (pack de test seulement)")
    urls = [u for var in variables for u in file_urls(choice.run, choice.steps, var)]
    cache = Path(args.cache) / model.lower()
    try:
        res = dwd.download_all(urls, cache, opener=_opener())
    except (RuntimeError, ValueError) as exc:
        raise PrepError(str(exc)) from exc
    print(
        f"{model} : {res.downloaded} fichiers téléchargés ({res.downloaded_bytes / 1e6:.1f} Mo), "
        f"{res.cached} déjà en cache"
    )
    return choice, res.paths, res


def _cmd_wind(args: argparse.Namespace) -> int:
    from jabuka.prep import dwd
    from jabuka.prep.grib import decode_wind_files
    from jabuka.prep.wxpack import default_crop, iso_utc, write_cube

    window = _window(args)
    out = Path(args.out)
    t0 = time.perf_counter()
    choice = None
    if args.from_files:
        files = _grib_files(args.from_files)
        source = f"fichiers locaux {Path(args.from_files).name}"
    else:
        choice, files, _res = _download_run(
            args,
            "ICON-EU",
            dwd.ICON_VARS,
            dwd.icon_listing_urls,
            dwd.icon_listing_pattern,
            dwd.icon_eu_urls,
            window,
        )
        source = "DWD opendata ICON-EU 10 m U/V (Datenbasis: Deutscher Wetterdienst)"
    try:
        cube = decode_wind_files(files, default_crop(), tmp_dir=args.cache)
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    path = write_cube(out, "wind", cube, model=args.model, source=source)
    run = iso_utc(cube.run) if cube.run is not None else "?"
    print(
        f"Vent : run {run}, {cube.t.size} échéances, grille {cube.lat.size}x{cube.lon.size} "
        f"-> {path} ({time.perf_counter() - t0:.1f} s)"
    )
    rc = run_check(out, args.marks, window)
    return EXIT_INCOMPLETE if choice is not None and choice.incomplete else rc


def _cmd_waves(args: argparse.Namespace) -> int:
    from jabuka.prep import dwd
    from jabuka.prep.grib import decode_wave_files
    from jabuka.prep.wxpack import default_crop, iso_utc, write_cube

    window = _window(args)
    out = Path(args.out)
    t0 = time.perf_counter()
    choice = None
    if args.from_files:
        files = _grib_files(args.from_files)
        source = f"fichiers locaux {Path(args.from_files).name}"
    else:
        choice, files, _res = _download_run(
            args,
            "EWAM",
            dwd.EWAM_VARS,
            dwd.ewam_listing_urls,
            dwd.ewam_listing_pattern,
            dwd.ewam_urls,
            window,
        )
        source = "DWD opendata EWAM SWH/MWD (Datenbasis: Deutscher Wetterdienst)"
    try:
        cube = decode_wave_files(files, default_crop(), tmp_dir=args.cache)
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    path = write_cube(out, "waves", cube, model="EWAM", source=source)
    run = iso_utc(cube.run) if cube.run is not None else "?"
    print(
        f"Vagues : run {run}, {cube.t.size} échéances, grille {cube.lat.size}x{cube.lon.size}, "
        f"champs {', '.join(cube.fields)} -> {path} ({time.perf_counter() - t0:.1f} s)"
    )
    rc = run_check(out, args.marks, window)
    return EXIT_INCOMPLETE if choice is not None and choice.incomplete else rc


def _cmd_grib(args: argparse.Namespace) -> int:
    import re

    from jabuka.prep.grib import import_generic
    from jabuka.prep.wxpack import default_crop, iso_utc, write_cube

    if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", args.name):
        raise PrepError(f"nom refusé : {args.name!r} (lettres minuscules, chiffres, _)")
    window = _window(args)
    out = Path(args.out)
    src = Path(args.file)
    try:
        cube = import_generic(src, default_crop())
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    model = src.name.split(".")[0] or "organiser"
    run = iso_utc(cube.run) if cube.run is not None else iso_utc(int(cube.t[0]))
    path = write_cube(out, args.name, cube, model=model, source=f"GRIB {src.name}", run=run)
    print(
        f"Vent ({src.name}) : {cube.t.size} échéances {iso_utc(cube.t[0])} -> "
        f"{iso_utc(cube.t[-1])}, grille {cube.lat.size}x{cube.lon.size} -> {path}"
    )
    if args.name != "wind":
        print(f"Écrit sous {path.name} : renommer en wind.npz/wind.json pour l'utiliser.")
    return run_check(out, args.marks, window)


def _cmd_current(args: argparse.Namespace) -> int:
    from jabuka.prep.current import SOURCE, import_copernicus
    from jabuka.prep.wxpack import default_crop, iso_utc, write_cube

    window = _window(args)
    out = Path(args.out)
    try:
        cube = import_copernicus(Path(args.file), default_crop())
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    path = write_cube(out, "current", cube, model="MEDSEA", source=SOURCE, run="")
    print(
        f"Courant : {cube.t.size} échéances {iso_utc(cube.t[0])} -> {iso_utc(cube.t[-1])}, "
        f"grille {cube.lat.size}x{cube.lon.size} -> {path}"
    )
    return run_check(out, args.marks, window)


def _cmd_check(args: argparse.Namespace) -> int:
    return run_check(Path(args.out), args.marks, _window(args))


def _cmd_geofields(args: argparse.Namespace) -> int:
    """One 200 m centre-mode geodesic field per mark, seeded within radius + one coarse cell;
    written as geofields.npz + sidecar (sha256) next to landmask.npz."""
    import numpy as np

    from jabuka.prep.wxpack import write_npz
    from jabuka.route.frame import NM_M
    from jabuka.route.landmask import LandMask, compute_geofield

    out = Path(args.out)
    if not (50.0 <= args.gcell_m <= 2000.0):
        raise PrepError(f"maille invalide : {args.gcell_m} m (50 à 2000)")
    mask_path = out / "landmask.npz"
    if not mask_path.is_file():
        raise PrepError(f"landmask.npz absent de {out} : lancer d'abord « jabuka-prep land build »")
    try:
        mask = LandMask.load(mask_path)
        doc = read_marks_file(args.marks)
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    g = args.gcell_m / NM_M
    fields, keys, marks = [], [], []
    geo0 = None
    for m in doc.marks.values():
        t0 = time.perf_counter()
        x, y = mask.frame.to_xy(m.lat, m.lon)
        geo = compute_geofield(mask, [(x, y)], g, "centre", seed_radius_nm=m.radius_nm + g)
        geo0 = geo
        fields.append(geo.dist.astype(np.float32))
        keys.append((m.lat, m.lon, m.radius_nm))
        reach = float(np.isfinite(geo.dist).mean())
        marks.append({"id": m.id, "name": m.name, "lat": m.lat, "lon": m.lon, "r": m.radius_nm})
        print(
            f"Champ {m.name} : {geo.dist.shape[0]}x{geo.dist.shape[1]} mailles, "
            f"{reach:.0%} atteignables ({time.perf_counter() - t0:.1f} s)"
        )
    if geo0 is None:
        raise PrepError(f"aucune marque dans {args.marks}")
    path = write_npz(
        out,
        "geofields",
        {
            "fields": np.stack(fields),
            "keys": np.array(keys, dtype=np.float64),
            "x0_nm": np.float64(geo0.x0_nm),
            "y0_nm": np.float64(geo0.y0_nm),
            "gcell_nm": np.float64(geo0.gcell_nm),
        },
        {
            "source": f"jabuka-prep geofields ({mask_path.name})",
            "gcell_m": float(args.gcell_m),
            "mode": "centre",
            "marks": marks,
        },
    )
    print(f"Champs : {len(fields)} marques -> {path}")
    return EXIT_OK


def _cmd_land(argv: Sequence[str]) -> int:
    try:
        land = importlib.import_module("jabuka.prep.land")
    except ModuleNotFoundError as exc:
        print(f"jabuka-prep land : module jabuka.prep.land absent ({exc})", file=sys.stderr)
        return EXIT_USAGE
    rc = land.main(list(argv))
    return int(rc or 0)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "land":
        return _cmd_land(argv[1:])
    args = build_parser().parse_args(argv)
    handlers = {
        "wind": _cmd_wind,
        "waves": _cmd_waves,
        "grib": _cmd_grib,
        "current": _cmd_current,
        "check": _cmd_check,
        "geofields": _cmd_geofields,
    }
    try:
        return handlers[args.cmd](args)
    except PrepError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
