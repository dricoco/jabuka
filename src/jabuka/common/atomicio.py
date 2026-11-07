"""Crash-safe config/state files (power cuts mid-write must never leave a half-written file).

atomic_write_bytes: write ``.NAME.tmp`` + flush + fsync; hard-link the current file to
``.NAME.bak.tmp`` and rename it to ``NAME.bak``; rename tmp onto NAME; fsync the directory.
load_json_with_bak: NAME, then NAME.bak, then the default.
load_json_status: the same, plus where the value came from and an optional validate hook. A value
from NAME.bak ("bak") must be announced by the caller ("restauré"), and so must a file present but
unusable ("unreadable", "illisible"): neither may be silent (04-01 soak, 04-REVIEW WR-04).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        # keep the previous good version as NAME.bak (atomic via hard link + rename)
        bak_tmp = path.with_name(f".{path.name}.bak.tmp")
        bak_tmp.unlink(missing_ok=True)
        os.link(path, bak_tmp)
        os.replace(bak_tmp, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def atomic_write_json(path: str | Path, obj: Any) -> None:
    data = json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    atomic_write_bytes(path, data.encode("utf-8"))


def load_json_with_bak(path: str | Path, default: Any) -> Any:
    return load_json_status(path, default)[0]


def load_json_status(
    path: str | Path, default: Any, validate: Callable[[Any], Any] | None = None
) -> tuple[Any, str]:
    """(value, source): source "main" or "bak" for the file that loaded, "missing" when neither
    NAME nor NAME.bak exists (first boot: the default is expected), "unreadable" when one exists
    but none loads (corruption: the caller must say so, never fall back silently). "bak" is a
    fallback too: the caller must say so ("restauré"), it may be an older state.

    validate: called with each decoded candidate; ValueError or TypeError (a pydantic
    ValidationError is a ValueError) rejects it and the next candidate is tried, so a main file
    that decodes but fails validation falls through to a valid NAME.bak. The value returned is
    validate's result. None: the decoded JSON, as before."""
    path = Path(path)
    present = False
    for p, source in ((path, "main"), (path.with_name(path.name + ".bak"), "bak")):
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            continue
        except OSError:  # EACCES/EIO, a directory: present but unreadable
            present = True
            continue
        present = True
        try:
            value = json.loads(data.decode("utf-8"))
        except ValueError:  # torn or bad JSON, bad UTF-8
            continue
        if validate is None:
            return value, source
        try:
            return validate(value), source
        except (ValueError, TypeError):  # decodes but invalid: try NAME.bak
            continue
    return default, ("unreadable" if present else "missing")
