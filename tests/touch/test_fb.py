"""Framebuffer discovery, RGB565 conversion and row-band partial writes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from jabuka_touch import fb


def test_find_fb_by_name() -> None:
    assert fb.find_fb("0 vc4drmfb\n1 fb_ili9486\n", "fb_ili9486") == 1
    assert fb.find_fb("0 vc4drmfb\n", "fb_ili9486") is None
    assert fb.find_fb("", "fb_ili9486") is None


def test_read_geometry(fake_sys: Path) -> None:
    assert fb.read_geometry(fake_sys / "graphics" / "fb1") == (480, 320, 16, 960)


def test_rgb565_values() -> None:
    px = np.array([[[255, 255, 255], [255, 0, 0], [0, 255, 0], [0, 0, 255], [8, 4, 8]]], np.uint8)
    out = fb.rgb565(px)
    assert out.dtype == np.dtype("<u2")
    assert out.tolist() == [[0xFFFF, 0xF800, 0x07E0, 0x001F, 0x0821]]
    assert out.tobytes()[:2] == b"\xff\xff"
    assert fb.rgb565(np.array([[[255, 0, 0]]], np.uint8)).tobytes() == b"\x00\xf8"


def _frame(h: int = 320, w: int = 480) -> np.ndarray:
    return np.zeros((h, w, 3), np.uint8)


def test_partial_band_writes(tmp_path: Path) -> None:
    path = tmp_path / "fb.raw"
    path.write_bytes(bytes(960 * 320))
    f = fb.FrameBuffer(path, 480, 320, 960)
    a = _frame()
    a[:, :] = (255, 255, 255)
    assert f.show(a) == (0, 320)
    assert path.read_bytes() == b"\xff" * (960 * 320)
    assert f.show(a.copy()) is None
    b = a.copy()
    b[100:120, 10:20] = (255, 0, 0)
    before = path.stat().st_mtime_ns
    assert f.show(b) == (100, 120)
    data = np.frombuffer(path.read_bytes(), dtype="<u2").reshape(320, 480)
    assert data[105, 15] == 0xF800 and data[99, 15] == 0xFFFF and data[120, 15] == 0xFFFF
    assert path.stat().st_mtime_ns >= before
    f.close()


def test_band_write_offset_only(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "fb.raw"
    path.write_bytes(bytes(960 * 320))
    f = fb.FrameBuffer(path, 480, 320, 960)
    f.show(_frame())
    writes = []
    real = fb.os.pwrite

    def spy(fd, data, off):
        writes.append((len(data), off))
        return real(fd, data, off)

    monkeypatch.setattr(fb.os, "pwrite", spy)
    b = _frame()
    b[100:120] = (0, 0, 255)
    assert f.show(b) == (100, 120)
    assert writes == [(20 * 960, 100 * 960)]
    f.close()


def test_stride_padding_preserved(tmp_path: Path) -> None:
    w, h, stride = 4, 3, 12  # 4 padding bytes per row
    path = tmp_path / "fb.raw"
    path.write_bytes(b"\xab" * (stride * h))
    f = fb.FrameBuffer(path, w, h, stride)
    f.show(np.zeros((h, w, 3), np.uint8))
    raw = path.read_bytes()
    for row in range(h):
        line = raw[row * stride : (row + 1) * stride]
        assert line[: w * 2] == bytes(w * 2)
        assert line[w * 2 :] == b"\xab" * 4
    f.close()


def test_only_16_bpp(tmp_path: Path) -> None:
    path = tmp_path / "fb.raw"
    path.write_bytes(bytes(10))
    with pytest.raises(ValueError, match="16"):
        fb.FrameBuffer(path, 480, 320, 1920, bpp=32)


def test_open_display(fake_sys: Path) -> None:
    d = fb.open_display(
        fake_sys / "proc" / "fb", fake_sys / "graphics", fake_sys / "dev", "fb_ili9486"
    )
    assert d is not None and (d.width, d.height, d.stride) == (480, 320, 960)
    assert d.path.name == "fb1"
    d.close()
    assert (
        fb.open_display(fake_sys / "proc" / "fb", fake_sys / "graphics", fake_sys / "dev", "absent")
        is None
    )
    assert (
        fb.open_display(fake_sys / "nope", fake_sys / "graphics", fake_sys / "dev", "fb_ili9486")
        is None
    )
