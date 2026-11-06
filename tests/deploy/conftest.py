"""Fixtures for the deploy/ (Pi appliance) tests: repo paths and a systemd unit reader."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"

Unit = dict[str, dict[str, list[str]]]


def parse_unit_text(text: str) -> Unit:
    """Minimal systemd INI reader: {section: {key: [values in order]}}.

    Repeated keys are kept (systemd semantics: lists append), comments (# ;) are skipped and a
    trailing backslash continues the line.
    """
    out: Unit = {}
    section: str | None = None
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.strip()
        pending = ""
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, {})
            continue
        if section is None or "=" not in line:
            raise ValueError(f"not a unit file line: {raw!r}")
        key, _, value = line.partition("=")
        out[section].setdefault(key.strip(), []).append(value.strip())
    return out


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def deploy_dir() -> Path:
    return DEPLOY


@pytest.fixture
def parse_unit() -> Callable[[str | Path], Unit]:
    """parse_unit("jabuka-core.service") reads deploy/systemd/<name>; a Path is read as is."""

    def _parse(name: str | Path) -> Unit:
        path = name if isinstance(name, Path) else DEPLOY / "systemd" / name
        return parse_unit_text(path.read_text())

    return _parse
