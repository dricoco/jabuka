"""Crash-safe config/state files (power cuts mid-write must never leave a half-written file).

atomic_write_bytes: write ``.NAME.tmp`` + flush + fsync; hard-link the current file to
``.NAME.bak.tmp`` and rename it to ``NAME.bak``; rename tmp onto NAME; fsync the directory.
load_json_with_bak: NAME, then NAME.bak, then the default.
"""

from __future__ import annotations

import json
import os
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
    path = Path(path)
    for p in (path, path.with_name(path.name + ".bak")):
        try:
            return json.loads(p.read_bytes().decode("utf-8"))
        except (OSError, ValueError):  # missing, EACCES/EIO, a directory, torn or bad JSON
            continue
    return default
