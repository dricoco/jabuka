"""Inject the clock everywhere: core/, common/ (except common/clock.py) and nav/ never read the
time directly."""

from __future__ import annotations

import ast
from pathlib import Path

import jabuka

PKG = Path(jabuka.__file__).resolve().parent
BANNED = {("time", "time"), ("time", "monotonic"), ("datetime", "now"), ("datetime", "utcnow")}


def _attr_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    rel = path.relative_to(PKG) if path.is_relative_to(PKG) else path.name
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = _attr_chain(node.func)
            if len(chain) >= 2 and (chain[-2], chain[-1]) in BANNED:
                out.append(f"{rel}:{node.lineno} {'.'.join(chain)}()")
        # bare-name imports would dodge the attribute check: ban them outright
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            for alias in node.names:
                if alias.name in ("time", "monotonic"):
                    out.append(f"{rel}:{node.lineno} from time import {alias.name}")
    return out


def _scanned() -> list[Path]:
    files = (
        sorted((PKG / "core").glob("*.py"))
        + sorted((PKG / "common").glob("*.py"))
        + sorted((PKG / "nav").glob("*.py"))
    )
    return [f for f in files if f.name != "clock.py"]


def test_scan_covers_core_and_common() -> None:
    names = {f.name for f in _scanned()}
    assert {"state.py", "main.py", "web.py", "messages.py"} <= names
    assert {"laylines.py", "wind.py", "polar.py", "course.py", "nav_service.py"} <= names
    assert "clock.py" not in names


def test_no_wall_or_monotonic_clock_reads() -> None:
    bad = [v for f in _scanned() for v in _violations(f)]
    assert bad == [], "use the injected Clock instead:\n" + "\n".join(bad)


def test_detector_catches_violations(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import time\nfrom datetime import datetime\nfrom time import monotonic\n"
        "a = time.time()\nb = time.monotonic()\nc = datetime.now()\nd = datetime.utcnow()\n"
    )
    assert len(_violations(sample)) == 5
