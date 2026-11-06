"""jabuka-prep: laptop race-pack builder (weather + land), ``python -m jabuka.prep.cli``.

Subcommands: wind, waves, grib FILE, current FILE.nc, land ... (jabuka.prep.land), check.
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

    p = sub.add_parser("check", help="vérifier le pack et la couverture météo")
    _common(p)

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


def _cmd_wind(args: argparse.Namespace) -> int:
    from jabuka.prep.grib import decode_wind_files
    from jabuka.prep.wxpack import default_crop, iso_utc, write_cube

    window = _window(args)
    out = Path(args.out)
    t0 = time.perf_counter()
    if not args.from_files:
        raise PrepError(
            "téléchargement DWD indisponible dans cette version : utiliser --from-files"
        )
    files = _grib_files(args.from_files)
    try:
        cube = decode_wind_files(files, default_crop(), tmp_dir=args.cache)
    except ValueError as exc:
        raise PrepError(str(exc)) from exc
    path = write_cube(
        out, "wind", cube, model=args.model, source=f"fichiers locaux {Path(args.from_files).name}"
    )
    run = iso_utc(cube.run) if cube.run is not None else "?"
    print(
        f"Vent : run {run}, {cube.t.size} échéances, grille {cube.lat.size}x{cube.lon.size} "
        f"-> {path} ({time.perf_counter() - t0:.1f} s)"
    )
    return run_check(out, args.marks, window)


def _cmd_check(args: argparse.Namespace) -> int:
    return run_check(Path(args.out), args.marks, _window(args))


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
    handlers = {"wind": _cmd_wind, "check": _cmd_check}
    try:
        return handlers[args.cmd](args)
    except PrepError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
