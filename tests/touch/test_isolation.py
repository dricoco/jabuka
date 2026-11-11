"""The menu never imports the jabuka package (system python, separate from the venv) and never
goes through a shell. AST-based, so comments and strings never trip it."""

from __future__ import annotations

import ast
from pathlib import Path

TOUCH_DIR = Path(__file__).resolve().parents[2] / "touch"

PKG = TOUCH_DIR / "jabuka_touch"
VENV_ONLY = {"demo_wind.py"}  # run by /opt/jabuka/venv/bin/python as jabuka, never imported


def _modules() -> list[Path]:
    mods = sorted(p for p in PKG.glob("*.py") if p.name not in VENV_ONLY)
    assert len(mods) >= 10
    return mods


def _is_jabuka(name: str | None) -> bool:
    return bool(name) and (name == "jabuka" or name.startswith("jabuka."))


def _truthy_const(node: ast.AST) -> bool:
    return not (isinstance(node, ast.Constant) and not node.value)


def test_no_jabuka_import_no_shell() -> None:
    problems = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                problems += [
                    f"{path.name}: import {a.name}" for a in node.names if _is_jabuka(a.name)
                ]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and _is_jabuka(node.module):
                    problems.append(f"{path.name}: from {node.module}")
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    if f.value.id == "os" and f.attr in ("system", "popen"):
                        problems.append(f"{path.name}:{node.lineno}: os.{f.attr}")
                for kw in node.keywords:
                    if kw.arg == "shell" and _truthy_const(kw.value):
                        problems.append(f"{path.name}:{node.lineno}: shell=")
    assert problems == []


def test_checker_catches_violations(tmp_path: Path) -> None:
    src = "import jabuka.nav\nimport os\nos.system('x')\nsubprocess.run(['a'], shell=True)\n"
    tree = ast.parse(src)
    kinds = [type(n).__name__ for n in ast.walk(tree)]
    assert "Import" in kinds
    imports = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert any(_is_jabuka(m) for m in imports)
    assert not _is_jabuka("jabuka_touch")
    shells = [
        kw
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg == "shell" and _truthy_const(kw.value)
    ]
    assert len(shells) == 1
