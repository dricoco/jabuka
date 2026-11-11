"""Rendering is exercised through `python3 -m jabuka_touch selftest` under the system python
(Pillow comes from apt on the Pi; it is not in the dev venvs and is never installed there)."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

TOUCH_DIR = Path(__file__).resolve().parents[2] / "touch"

SYS_PY = Path("/usr/bin/python3")


def _sys_python_has_pillow() -> str | None:
    if not SYS_PY.exists():
        return "/usr/bin/python3 absent"
    p = subprocess.run(
        [str(SYS_PY), "-c", "import PIL, numpy"], capture_output=True, text=True, timeout=60
    )
    return None if p.returncode == 0 else "/usr/bin/python3 sans Pillow/numpy"


def test_selftest_renders_every_screen(tmp_path: Path) -> None:
    out = tmp_path / "png"
    if importlib.util.find_spec("PIL") is not None:
        from jabuka_touch import selftest

        assert selftest.main(str(out)) == 0
    else:
        reason = _sys_python_has_pillow()
        if reason:
            pytest.skip(f"rendu non testé : {reason}")
        p = subprocess.run(
            [str(SYS_PY), "-m", "jabuka_touch", "selftest", "--out", str(out)],
            cwd=TOUCH_DIR,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert p.returncode == 0, p.stdout + p.stderr
        assert "selftest : ok" in p.stdout
    pngs = {p.stem for p in out.glob("*.png")}
    for name in (
        "home",
        "home-night",
        "home-demo",
        "system",
        "confirm-restart_services",
        "confirm-poweroff",
        "details",
        "prep",
        "journal",
        "demo",
    ):
        assert name in pngs, name
    for p in out.glob("*.png"):
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
