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


def _domain_wall_uses(path: Path) -> list[str]:
    """Uses of the injected Clock.wall (the unsynced system clock) outside log metadata: the only
    allowed form is the value of a "t_wall" key in an event/log dict literal (WR-03)."""
    tree = ast.parse(path.read_text(), filename=str(path))
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "t_wall":
                    allowed.add(id(v))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) in allowed:
            continue
        target = node.func if isinstance(node, ast.Call) else node
        chain = _attr_chain(target) if isinstance(target, ast.Attribute) else []
        if len(chain) >= 2 and chain[-1] == "wall" and chain[-2] == "clock":
            if isinstance(node, ast.Call) or not any(
                isinstance(p, ast.Call) and p.func is node for p in ast.walk(tree)
            ):
                out.append(f"{path.name}:{node.lineno} {'.'.join(chain)}")
    return out


def test_domain_decisions_never_use_the_system_wall_clock() -> None:
    """WR-03: manual-wind age and the Annuler window run on trusted UTC (clock.utc_epoch), not on
    clock.wall() (system clock, fake-hwclock's last save after a power cut)."""
    files = [PKG / "core" / n for n in ("nav_service.py", "nav_api.py", "course_api.py")]
    files += sorted((PKG / "nav").glob("*.py"))
    bad = [v for f in files for v in _domain_wall_uses(f)]
    assert bad == [], "use jabuka.common.clock.utc_epoch(clock):\n" + "\n".join(bad)


def test_domain_wall_detector(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "rec = {'t_wall': ctx.clock.wall(), 'x': 1}\n"  # log metadata: allowed
        "a = ctx.clock.wall()\n"
        "course.wall = ctx.clock.wall\n"
        "w.update(t_wall=self.clock.wall())\n"
    )
    assert len(_domain_wall_uses(sample)) == 3


def test_detector_catches_violations(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import time\nfrom datetime import datetime\nfrom time import monotonic\n"
        "a = time.time()\nb = time.monotonic()\nc = datetime.now()\nd = datetime.utcnow()\n"
    )
    assert len(_violations(sample)) == 5
