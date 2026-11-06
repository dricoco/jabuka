"""The routing core (src/jabuka/route/) stays pure: no clock reads, no network, no shapely/GRIB
libraries, no dependency on the core/nav/prep packages. Every module present is scanned, so the
modules added by later plans are covered automatically."""

from __future__ import annotations

import ast
from pathlib import Path

import jabuka

PKG = Path(jabuka.__file__).resolve().parent
ROUTE = PKG / "route"
BANNED_CALLS = {
    ("time", "time"),
    ("time", "monotonic"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
}
BANNED_FROM_TIME = {"time", "monotonic"}  # perf_counter stays allowed (timing diagnostics)
BANNED_MODULES = (
    "shapely",
    "pygrib",
    "netCDF4",
    "urllib",
    "http",
    "socket",
    "ssl",
    "requests",
    "fastapi",
    "starlette",
    "jabuka.core",
    "jabuka.nav",
    "jabuka.prep",
)


def _attr_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _banned_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in BANNED_MODULES)


def _resolve_from(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    base = package.split(".")
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _violations(path: Path, package: str = "jabuka.route") -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = _attr_chain(node.func)
            if len(chain) >= 2 and (chain[-2], chain[-1]) in BANNED_CALLS:
                out.append(f"{path.name}:{node.lineno} {'.'.join(chain)}()")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _banned_module(alias.name):
                    out.append(f"{path.name}:{node.lineno} import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = _resolve_from(node, package)
            if mod == "time":
                for alias in node.names:
                    if alias.name in BANNED_FROM_TIME:
                        out.append(f"{path.name}:{node.lineno} from time import {alias.name}")
            if _banned_module(mod):
                out.append(f"{path.name}:{node.lineno} from {mod} import ...")
            else:  # "from jabuka import nav" style
                for alias in node.names:
                    if _banned_module(f"{mod}.{alias.name}"):
                        out.append(f"{path.name}:{node.lineno} from {mod} import {alias.name}")
    return out


def _scanned() -> list[Path]:
    return sorted(ROUTE.glob("*.py"))


def test_scan_covers_route_modules() -> None:
    names = {f.name for f in _scanned()}
    assert {"__init__.py", "frame.py", "landmask.py"} <= names


def test_route_package_is_pure() -> None:
    bad = [v for f in _scanned() for v in _violations(f)]
    assert bad == [], "route/ must stay pure (numpy only, injected time):\n" + "\n".join(bad)


def test_detector_catches_violations(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import time\nfrom datetime import datetime\nfrom time import monotonic\n"
        "import shapely.geometry\nimport urllib.request\nfrom http import client\n"
        "from jabuka.nav import polar\nfrom jabuka import prep\nfrom ..core import state\n"
        "import socket, ssl\n"
        "a = time.time()\nb = time.monotonic()\nc = datetime.now()\nd = datetime.utcnow()\n"
        "e = time.perf_counter()\n"
    )
    found = _violations(sample)
    # 1 from-time + 7 import lines (socket and ssl count twice) + 4 clock calls
    assert len(found) == 13, found
    assert not any("perf_counter" in v for v in found)
