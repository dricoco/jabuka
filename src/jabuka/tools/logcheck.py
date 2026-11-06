"""jabuka-logcheck: validate every Jabuka log and state file after a crash or power pull.

    jabuka-logcheck DIR [--json]

Walks DIR recursively:

- ``fastnet*.log`` / ``capture*.log`` (raw): every complete line is
  ``<t_mono> <t_wall> <hex>`` with two floats and a non-empty, even-length hex string.
- ``bus*.log`` / ``gps*.log``: ``<t_mono> <t_wall> <json>``, the third field valid JSON.
- ``*.jsonl`` (derived, events): every complete line is valid JSON.
- ``*.json`` (atomic state files): loaded via ``load_json_with_bak``; reports whether the main
  file or ``NAME.bak`` was used. ``NAME.bak`` and hidden ``.NAME.tmp`` leftovers are not checked
  on their own.

A torn last line (no trailing newline: the power went mid-write) is reported as ``torn_tail``,
not an error, exactly like ``jabuka.ingest.rawlog.iter_log_lines`` skips it. Complete lines must
be valid UTF-8. Exit status: 0 ok, 1 corruption found, 2 DIR is not a directory.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jabuka.common.atomicio import load_json_with_bak

RAW_PREFIXES = ("fastnet", "capture")
LINE_JSON_PREFIXES = ("bus", "gps")
MAX_ERRORS_KEPT = 20

_MISSING = object()


@dataclass
class FileReport:
    path: str
    kind: str  # "raw" | "line-json" | "jsonl" | "json"
    lines: int = 0
    torn_tail: bool = False
    errors: list[str] = field(default_factory=list)
    error_count: int = 0
    source: str | None = None  # json only: "main" | "bak" | None (unreadable)

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def add_error(self, msg: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_ERRORS_KEPT:
            self.errors.append(msg)


@dataclass
class Report:
    root: str
    files: list[FileReport] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.files)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "ok": self.ok,
            "files": [asdict(f) | {"ok": f.ok} for f in self.files],
            "skipped": self.skipped,
        }


# -- line validators (return an error message or None) ------------------------------------------


def _float(text: str, name: str) -> str | None:
    try:
        v = float(text)
    except ValueError:
        return f"{name} is not a number: {text[:32]!r}"
    if not math.isfinite(v):
        return f"{name} is not finite: {text[:32]!r}"
    return None


def _check_raw(line: str) -> str | None:
    parts = line.split(" ")
    if len(parts) != 3:
        return f"expected 3 fields '<t_mono> <t_wall> <hex>', got {len(parts)}"
    for value, name in ((parts[0], "t_mono"), (parts[1], "t_wall")):
        if err := _float(value, name):
            return err
    hexs = parts[2]
    if not hexs or len(hexs) % 2:
        return f"hex field has odd or zero length ({len(hexs)})"
    try:
        bytes.fromhex(hexs)
    except ValueError:
        return f"hex field is not hex: {hexs[:32]!r}"
    return None


def _check_line_json(line: str) -> str | None:
    parts = line.split(" ", 2)
    if len(parts) != 3:
        return f"expected 3 fields '<t_mono> <t_wall> <json>', got {len(parts)}"
    for value, name in ((parts[0], "t_mono"), (parts[1], "t_wall")):
        if err := _float(value, name):
            return err
    try:
        json.loads(parts[2])
    except json.JSONDecodeError as e:
        return f"invalid JSON: {e.msg} at column {e.colno}"
    return None


def _check_jsonl(line: str) -> str | None:
    try:
        json.loads(line)
    except json.JSONDecodeError as e:
        return f"invalid JSON: {e.msg} at column {e.colno}"
    return None


_LINE_CHECKS = {"raw": _check_raw, "line-json": _check_line_json, "jsonl": _check_jsonl}


def _classify(path: Path) -> str | None:
    name = path.name
    if name.startswith(".") and name.endswith(".tmp"):
        return None  # atomicio temp file left by a crash before the rename
    if path.suffix == ".log":
        if name.startswith(RAW_PREFIXES):
            return "raw"
        if name.startswith(LINE_JSON_PREFIXES):
            return "line-json"
        return None
    if path.suffix == ".jsonl":
        return "jsonl"
    if path.suffix == ".json":
        return "json"
    if name.endswith(".json.bak") and not path.with_name(name[: -len(".bak")]).exists():
        return "json-orphan-bak"  # only the .bak survived: check it through its main name
    return None


def check_lines(path: Path, kind: str, rel: str) -> FileReport:
    rep = FileReport(path=rel, kind=kind)
    check = _LINE_CHECKS[kind]
    try:
        data = path.read_bytes()
    except OSError as e:
        rep.add_error(f"cannot read: {e}")
        return rep
    parts = data.split(b"\n")
    rep.torn_tail = parts[-1] != b""  # same rule as iter_log_lines: skip, don't fail
    for lineno, raw in enumerate(parts[:-1], start=1):
        rep.lines += 1
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError:
            rep.add_error(f"line {lineno}: not valid UTF-8")
            continue
        if not line:
            rep.add_error(f"line {lineno}: empty line")
            continue
        if err := check(line):
            rep.add_error(f"line {lineno}: {err}")
    return rep


def check_json(path: Path, rel: str) -> FileReport:
    rep = FileReport(path=rel, kind="json")
    try:
        json.loads(path.read_bytes().decode("utf-8"))
        rep.source = "main"
        return rep
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    if load_json_with_bak(path, _MISSING) is not _MISSING:
        rep.source = "bak"  # main torn or missing, the previous good version loads
    else:
        rep.add_error(f"neither {path.name} nor {path.name}.bak is valid JSON")
    return rep


def check_dir(path: Path) -> Report:
    root = Path(path)
    report = Report(root=str(root))
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        kind = _classify(p)
        if kind is None:
            report.skipped.append(rel)
        elif kind == "json":
            report.files.append(check_json(p, rel))
        elif kind == "json-orphan-bak":
            main_path = p.with_name(p.name[: -len(".bak")])
            report.files.append(check_json(main_path, str(main_path.relative_to(root))))
        else:
            report.files.append(check_lines(p, kind, rel))
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-logcheck",
        description="Validate Jabuka logs and state files (after a crash or power pull). "
        "Exit 0 ok, 1 corruption found, 2 DIR is not a directory.",
    )
    p.add_argument("dir", metavar="DIR", type=Path, help="e.g. /var/lib/jabuka/logs")
    p.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    return p


def _print_text(report: Report) -> None:
    for f in report.files:
        status = "OK " if f.ok else "BAD"
        extra = f" source={f.source}" if f.kind == "json" else ""
        print(
            f"{status} {f.path} kind={f.kind} lines={f.lines} torn_tail={str(f.torn_tail).lower()}"
            f" errors={f.error_count}{extra}"
        )
        for err in f.errors:
            print(f"      {f.path}: {err}")
    bad = sum(1 for f in report.files if not f.ok)
    torn = sum(1 for f in report.files if f.torn_tail)
    if report.ok:
        print(f"logcheck: OK ({len(report.files)} files, {torn} torn tails) in {report.root}")
    else:
        print(f"logcheck: CORRUPT ({bad} of {len(report.files)} files) in {report.root}")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.dir.is_dir():
        print(f"jabuka-logcheck: not a directory: {args.dir}", file=sys.stderr)
        return 2
    report = check_dir(args.dir)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_text(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
