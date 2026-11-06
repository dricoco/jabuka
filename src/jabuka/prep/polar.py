"""jabuka-prep-polar: convert a boat polar into the race-pack polar.json (WIND-01; CONTEXT "Polar";
RESEARCH Pattern 3 parsers a-c).

    jabuka-prep-polar INPUT [--name NAME] [--out FILE]      (default var/racepack/polar.json)
    exit 0 ok, 1 output not writable, 2 unreadable/invalid input

Formats, detected by content (parse_any):
  JSON        the race-pack form {"name", "source", "curves": [[tws, [[twa, bsp], ...]], ...]}
  ORC table   certificate layout: a header row of TWS, then "Beat Angles", "Beat VMG", angle rows
              ("52°" ... "150°", the ° optional) of boat speeds, "Run VMG", "Gybe Angles". The beat
              point is BSP = VMG / cos(angle), the gybe point BSP = VMG / -cos(angle).
  grid        OpenCPN / qtVlm: first cell "TWA\\TWS" or "twa/tws" (any case), rows = TWA, columns =
              TWS; separator tab, ';', ',' or runs of spaces; decimal commas accepted with ';' or
              tab; empty and zero cells skipped; an optional boat-name line before the header.
  Expedition  '!' comments, lines "TWS TWA BSP TWA BSP ..." (jabuka.nav.polar.parse_expedition).
Every value is checked (finite; TWS in (0, 60] kn, TWA in (0, 180] deg, BSP in [0, 30] kn; at least
2 TWS curves; at most 1 MB) and a bad value raises ValueError naming its line. The output is
written with nav.polar.polar_to_json and read back with polar_from_json, so the core loads exactly
what was checked here. The target table (TWS | up TWA / BSP | down TWA / BSP) is printed so the
owner can sanity-check the polar before copying it with the race pack (docs/RACE-PACK.md).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from jabuka.common.atomicio import atomic_write_json
from jabuka.nav.polar import Polar, parse_expedition, polar_from_json, polar_to_json

EXIT_OK, EXIT_WRITE, EXIT_INPUT = 0, 1, 2
MAX_BYTES = 1024 * 1024
DEFAULT_OUT = Path("var/racepack/polar.json")
TWS_MAX = 60.0
BSP_MAX = 30.0
MIN_CURVES = 2
TABLE_TWS = (6, 8, 10, 12, 14, 16, 18, 20)

_GRID_HEADER = re.compile(r"^\s*twa\s*[\\/]\s*tws", re.IGNORECASE)
_UNITS = re.compile(r"(°|º|deg|kts?|kn|knots?)$", re.IGNORECASE)
_ORC_LABELS = {
    "beat angle": "beat_angle",
    "beat angles": "beat_angle",
    "beat vmg": "beat_vmg",
    "run vmg": "run_vmg",
    "gybe angle": "gybe_angle",
    "gybe angles": "gybe_angle",
    "run angle": "gybe_angle",
    "run angles": "gybe_angle",
}
_ORC_NAMES = {
    "beat_angle": "Beat Angles",
    "beat_vmg": "Beat VMG",
    "run_vmg": "Run VMG",
    "gybe_angle": "Gybe Angles",
}

Curves = list[tuple[float, list[tuple[float, float]]]]


# -- value checks -------------------------------------------------------------------------------
def _where(lineno: int | None) -> str:
    return f"line {lineno}" if lineno is not None else "polar"


def _num(cell: str, lineno: int | None, decimal_comma: bool = False) -> float:
    s = cell.strip()
    s = _UNITS.sub("", s).strip()
    if decimal_comma:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"{_where(lineno)}: {cell.strip()[:20]!r} is not a number") from None
    if not math.isfinite(v):
        raise ValueError(f"{_where(lineno)}: non-finite number {cell.strip()[:20]!r}")
    return v


def _check_tws(v: float, lineno: int | None) -> float:
    if not 0.0 < v <= TWS_MAX:
        raise ValueError(f"{_where(lineno)}: TWS {v:g} kn outside (0, {TWS_MAX:g}]")
    return v


def _check_twa(v: float, lineno: int | None) -> float:
    if not 0.0 < v <= 180.0:
        raise ValueError(f"{_where(lineno)}: TWA {v:g} deg outside (0, 180]")
    return v


def _check_bsp(v: float, lineno: int | None) -> float:
    if not 0.0 <= v <= BSP_MAX:
        raise ValueError(f"{_where(lineno)}: BSP {v:g} kn outside [0, {BSP_MAX:g}]")
    return v


def _finish(name: str, curves: Curves, source: str) -> Polar:
    curves = [(t, pts) for t, pts in curves if pts]
    if len(curves) < MIN_CURVES:
        raise ValueError(
            f"polar: {len(curves)} TWS curve(s), need at least {MIN_CURVES} TWS curves"
        )
    return Polar(name=name, curves=curves, source=source)


# -- splitting ----------------------------------------------------------------------------------
def _data_lines(text: str) -> list[tuple[int, str]]:
    out = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith(("!", "#")):
            out.append((lineno, raw.rstrip("\r\n")))
    return out


def _separator(line: str) -> str | None:
    for sep in ("\t", ";", ","):
        if sep in line:
            return sep
    return None  # runs of spaces


def _is_number(token: str) -> bool:
    try:
        float(_UNITS.sub("", token.strip()).replace(",", "."))
        return True
    except ValueError:
        return False


def _cells(line: str, sep: str | None) -> tuple[str, list[str]]:
    """(label, value cells). With runs of spaces the label is the first token when it is a number
    (an angle row), else every leading non-number token ("Beat Angles")."""
    if sep is not None:
        parts = line.split(sep)
        return parts[0].strip(), [p.strip() for p in parts[1:]]
    tokens = line.split()
    if not tokens:
        return "", []
    if _is_number(tokens[0]):
        return tokens[0], tokens[1:]
    i = 0
    while i < len(tokens) and not _is_number(tokens[i]):
        i += 1
    return " ".join(tokens[:i]), tokens[i:]


# -- parsers ------------------------------------------------------------------------------------
def parse_grid(text: str, name: str = "polar") -> Polar:
    """OpenCPN / qtVlm TWA\\TWS grid."""
    lines = _data_lines(text)
    start = next((k for k, (_, line) in enumerate(lines) if _GRID_HEADER.match(line)), None)
    if start is None:
        raise ValueError("polar: no 'TWA\\TWS' header line")
    head_no, head = lines[start]
    sep = _separator(head)
    dec_comma = sep in (";", "\t")
    _, tws_cells = _cells(head, sep)
    while tws_cells and not tws_cells[-1]:
        tws_cells.pop()
    tws = [_check_tws(_num(c, head_no, dec_comma), head_no) for c in tws_cells]
    if len(set(tws)) != len(tws):
        raise ValueError(f"line {head_no}: duplicate TWS column")
    curves: list[list[tuple[float, float]]] = [[] for _ in tws]
    for lineno, line in lines[start + 1 :]:
        label, cells = _cells(line, sep)
        twa = _check_twa(_num(label, lineno, dec_comma), lineno)
        while len(cells) > len(tws) and not cells[-1]:
            cells.pop()
        if len(cells) > len(tws) or (sep is None and len(cells) != len(tws)):
            raise ValueError(f"line {lineno}: {len(cells)} values for {len(tws)} TWS columns")
        for j, cell in enumerate(cells):
            if not cell:
                continue
            bsp = _check_bsp(_num(cell, lineno, dec_comma), lineno)
            if bsp > 0.0:
                curves[j].append((twa, bsp))
    return _finish(name, list(zip(tws, curves, strict=True)), "grid")


def _orc_key(label: str) -> str | None:
    return _ORC_LABELS.get(" ".join(label.lower().split()))


def looks_like_orc(text: str) -> bool:
    for _, line in _data_lines(text)[:60]:
        label, _ = _cells(line, _separator(line))
        if _orc_key(label):
            return True
    return False


def parse_orc_table(text: str, name: str = "polar") -> Polar:
    """ORC certificate polar table (Beat Angles / Beat VMG / angle rows / Run VMG / Gybe Angles)."""
    tws: list[float] | None = None
    tws_line: int | None = None
    special: dict[str, tuple[int, list[float | None]]] = {}
    rows: list[tuple[int, float, list[float | None]]] = []
    for lineno, line in _data_lines(text):
        sep = _separator(line)
        dec_comma = sep == ";" or sep == "\t"
        label, cells = _cells(line, sep)
        while cells and not cells[-1]:
            cells.pop()
        key = _orc_key(label)
        if tws is None:
            # the header: a non-angle label followed by at least 2 numbers (titles are skipped)
            if (
                key is None
                and not _is_number(label)
                and len(cells) >= MIN_CURVES
                and all(_is_number(c) for c in cells)
            ):
                tws = [_check_tws(_num(c, lineno, dec_comma), lineno) for c in cells]
                tws_line = lineno
            continue
        if key is None and not _is_number(label):
            continue  # a title or unrelated row
        if len(cells) > len(tws):
            raise ValueError(f"line {lineno}: {len(cells)} values for {len(tws)} TWS columns")
        vals: list[float | None] = [_num(c, lineno, dec_comma) if c else None for c in cells]
        vals += [None] * (len(tws) - len(cells))
        if key is not None:
            special[key] = (lineno, vals)
        else:
            twa = _check_twa(_num(label, lineno, dec_comma), lineno)
            for v in vals:
                if v is not None:
                    _check_bsp(v, lineno)
            rows.append((lineno, twa, vals))
    if tws is None:
        raise ValueError("polar: no TWS header row in the ORC table")
    # the beat pair is mandatory (it is what the laylines use); the run pair is optional as a pair
    for pair, required in ((("beat_angle", "beat_vmg"), True), (("gybe_angle", "run_vmg"), False)):
        missing = [k for k in pair if k not in special]
        if missing and (required or len(missing) == 1):
            raise ValueError(f"line {tws_line}: ORC table has no '{_ORC_NAMES[missing[0]]}' row")
    curves: Curves = []
    for j, t in enumerate(tws):
        pts: list[tuple[float, float]] = []
        for _, twa, v in rows:
            bsp = v[j]
            if bsp is not None and bsp > 0.0:
                pts.append((twa, bsp))
        angles = {round(a, 1) for a, _ in pts}
        for akey, vkey, upwind in (
            ("beat_angle", "beat_vmg", True),
            ("gybe_angle", "run_vmg", False),
        ):
            if akey not in special:
                continue
            a_line, a_vals = special[akey]
            v_line, v_vals = special[vkey]
            a, vmg = a_vals[j], v_vals[j]
            if a is None or vmg is None:
                continue
            _check_twa(a, a_line)
            if upwind and not a < 90.0:
                raise ValueError(f"line {a_line}: beat angle {a:g} deg must be below 90")
            if not upwind and not a > 90.0:
                raise ValueError(f"line {a_line}: gybe angle {a:g} deg must be above 90")
            cos = math.cos(math.radians(a))
            bsp = _check_bsp(vmg / cos if upwind else vmg / -cos, v_line)
            if round(a, 1) not in angles:
                pts.append((a, round(bsp, 4)))
        pts.sort()
        curves.append((t, pts))
    return _finish(name, curves, "orc-table")


def _validate_expedition(text: str) -> None:
    """Range checks with line numbers before nav.polar.parse_expedition parses the same text."""
    for lineno, line in _data_lines(text):
        nums = [_num(tok, lineno) for tok in line.split()]
        if len(nums) < 3 or (len(nums) - 1) % 2:
            raise ValueError(f"line {lineno}: expected TWS followed by TWA BSP pairs")
        _check_tws(nums[0], lineno)
        for k in range(1, len(nums), 2):
            _check_twa(nums[k], lineno)
            _check_bsp(nums[k + 1], lineno)


def _from_json(text: str, name: str) -> Polar:
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise ValueError(f"polar json: {e}") from None
    p = polar_from_json(obj)
    curves: Curves = []
    for i, (t, pts) in enumerate(p.curves, 1):
        where = f"polar json curve {i}"
        if not 0.0 < t <= TWS_MAX:
            raise ValueError(f"{where}: TWS {t:g} kn outside (0, {TWS_MAX:g}]")
        kept = []
        for a, b in pts:
            if a == 0.0 and b == 0.0:
                continue  # the implicit origin Polar adds to every curve
            if not 0.0 < a <= 180.0:
                raise ValueError(f"{where}: TWA {a:g} deg outside (0, 180]")
            if not 0.0 <= b <= BSP_MAX:
                raise ValueError(f"{where}: BSP {b:g} kn outside [0, {BSP_MAX:g}]")
            kept.append((a, b))
        curves.append((t, kept))
    return _finish(name or p.name, curves, "json")


def parse_any(text: str, name: str = "polar") -> Polar:
    """Detect the format by content and parse + validate it."""
    if len(text.encode("utf-8", "surrogatepass")) > MAX_BYTES:
        raise ValueError("polar: file larger than 1 MB")
    if not _data_lines(text):
        raise ValueError("polar: no data line")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return _from_json(stripped, name)
    if looks_like_orc(text):
        return parse_orc_table(text, name)
    if any(_GRID_HEADER.match(line) for _, line in _data_lines(text)[:5]):
        return parse_grid(text, name)
    _validate_expedition(text)
    p = parse_expedition(text, name)
    return _finish(name, p.curves, "expedition")


# -- CLI ----------------------------------------------------------------------------------------
def read_input(path: Path) -> str:
    """UTF-8 (BOM tolerated) with a latin-1 fallback; at most 1 MB."""
    with open(path, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"{path.name}: file larger than 1 MB")
    if b"\x00" in data:
        raise ValueError(f"{path.name}: binary file (NUL bytes), not a polar")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def target_table(polar: Polar, tws_list: Sequence[float] = TABLE_TWS) -> str:
    lines = [
        f"polar {polar.name!r} ({polar.source}), raw VPP speeds (the efficiency setting applies on "
        "the boat):",
        " TWS | up TWA    BSP     | down TWA  BSP",
        "-----+-----------------+-----------------",
    ]
    for t in tws_list:
        tg = polar.targets(float(t))
        lines.append(
            f"{t:4.0f} | {tg.up_twa:5.1f}°  {tg.up_bsp:5.2f} kn | {tg.down_twa:5.1f}°  "
            f"{tg.down_bsp:5.2f} kn"
        )
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-prep-polar",
        description="Convert a polar (OpenCPN/qtVlm grid, Expedition, ORC table or JSON) into the "
        "race-pack polar.json and print its VMG targets.",
    )
    p.add_argument("input", type=Path, help="polar file")
    p.add_argument("--name", help="polar name shown on the tablets (default: the file name)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output (var/racepack/polar.json)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    try:
        a = build_arg_parser().parse_args(argv)
    except SystemExit as e:  # --help -> 0, usage error -> 2
        return int(e.code or 0)
    name = (a.name or a.input.stem).strip()[:80] or "polar"
    try:
        text = read_input(a.input)
        polar = parse_any(text, name)
        if a.name:
            polar.name = name
    except (OSError, ValueError) as e:
        print(f"prep-polar: {a.input}: {e}", file=sys.stderr)
        return EXIT_INPUT
    polar.source = f"{polar.source}:{a.input.name}"[:80]
    obj = polar_to_json(polar)
    try:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(a.out, obj)
        a.out.with_name(a.out.name + ".bak").unlink(missing_ok=True)
        back = polar_from_json(json.loads(a.out.read_text("utf-8")))  # what the core will load
    except (OSError, ValueError) as e:
        print(f"prep-polar: cannot write {a.out}: {e}", file=sys.stderr)
        return EXIT_WRITE
    print(target_table(back))
    print(f"prep-polar: wrote {a.out} ({len(back.curves)} TWS curves)")
    if a.out.name != "polar.json":
        print("prep-polar: NOTE the core only reads <racepack>/polar.json", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
