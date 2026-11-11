"""jabuka-touch tests: the package lives in <repo>/touch (system python on the Pi, never
installed in the dev venvs), so put that directory first on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOUCH_DIR = Path(__file__).resolve().parents[2] / "touch"
if str(TOUCH_DIR) not in sys.path:
    sys.path.insert(0, str(TOUCH_DIR))

from jabuka_touch import actions  # noqa: E402
from jabuka_touch.selftest import ManualClock  # noqa: E402

REPO = TOUCH_DIR.parent


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(100.0)


@pytest.fixture
def runner() -> actions.FakeRunner:
    return actions.FakeRunner()


@pytest.fixture
def fake_sys(tmp_path: Path) -> Path:
    """A fake /proc/fb, /sys/class/graphics/fb1, /dev/fb1 and an ADS7846 input node."""
    root = tmp_path / "sys"
    (root / "proc").mkdir(parents=True)
    (root / "proc" / "fb").write_text("0 vc4drmfb\n1 fb_ili9486\n")
    g = root / "graphics" / "fb1"
    g.mkdir(parents=True)
    (g / "virtual_size").write_text("480,320\n")
    (g / "bits_per_pixel").write_text("16\n")
    (g / "stride").write_text("960\n")
    (root / "dev").mkdir()
    (root / "dev" / "fb1").write_bytes(bytes(960 * 320))
    for n, name in ((0, "vc4-hdmi"), (3, "ADS7846 Touchscreen")):
        d = root / "input" / f"event{n}" / "device"
        d.mkdir(parents=True)
        (d / "name").write_text(name + "\n")
    return root
