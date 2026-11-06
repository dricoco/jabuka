"""Soak harness tests (plan 04-01). The end-to-end soak runs carry the marker "soak" (registered
here, pyproject markers untouched); they are part of the default gate."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "soak: end-to-end soak run of the real stack (jabuka-soak), seconds to minutes"
    )


def pids_referencing(path: Path) -> list[tuple[int, str]]:
    """Live processes whose command line mentions ``path`` (harness leftovers)."""
    needle = str(path)
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) == os.getpid():
            continue
        try:
            raw = Path(f"/proc/{name}/cmdline").read_bytes()
            state = Path(f"/proc/{name}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if state == "Z":
            continue
        cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace")
        if needle in cmd:
            out.append((int(name), cmd))
    return out


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.fixture
def leftovers() -> Callable[[Path], list[tuple[int, str]]]:
    return pids_referencing


@pytest.fixture
def is_alive() -> Callable[[int], bool]:
    return alive
