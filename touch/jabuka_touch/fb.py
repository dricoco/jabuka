"""Linux framebuffer output (fbtft fb_ili9486 on the MHS35, RGB565 little-endian).

The device is found by NAME in /proc/fb (its number changes with the vc4 driver), its geometry
read from sysfs. show() only rewrites the band of rows that changed since the previous frame:
the SPI link of the MHS35 is slow (a full frame is ~300 kB), so unchanged rows never hit it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger("jabuka_touch.fb")


def find_fb(proc_fb_text: str, name: str) -> int | None:
    """Index N of the framebuffer called ``name`` in /proc/fb ("<N> <name>" lines)."""
    for line in proc_fb_text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].strip() == name:
            return int(parts[0])
    return None


def read_geometry(sysfs_dir: Path | str) -> tuple[int, int, int, int]:
    """(width, height, bpp, stride) from /sys/class/graphics/fbN."""
    d = Path(sysfs_dir)
    w, h = (int(v) for v in (d / "virtual_size").read_text().strip().split(","))
    bpp = int((d / "bits_per_pixel").read_text().strip())
    stride = int((d / "stride").read_text().strip())
    return w, h, bpp, stride


def rgb565(rgb: np.ndarray) -> np.ndarray:
    """HxWx3 uint8 -> HxW little-endian uint16 RGB565."""
    a = np.asarray(rgb, dtype=np.uint8)
    r = a[..., 0].astype(np.uint16)
    g = a[..., 1].astype(np.uint16)
    b = a[..., 2].astype(np.uint16)
    return (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).astype("<u2")


class FrameBuffer:
    """A framebuffer device (or a plain file of the same layout, for tests)."""

    def __init__(self, path: Path | str, width: int, height: int, stride: int, bpp: int = 16):
        if bpp != 16:
            raise ValueError(f"framebuffer {path} : {bpp} bits par pixel, seul 16 (RGB565) géré")
        if stride < width * 2:
            raise ValueError(f"framebuffer {path} : stride {stride} < largeur {width} x 2")
        self.path = Path(path)
        self.width, self.height, self.stride, self.bpp = width, height, stride, bpp
        self.fd = os.open(self.path, os.O_RDWR)
        self.prev: np.ndarray | None = None
        pad = stride - width * 2
        self.padding: np.ndarray | None = None
        if pad:
            raw = os.pread(self.fd, stride * height, 0)
            buf = np.zeros(stride * height, dtype=np.uint8)
            buf[: len(raw)] = np.frombuffer(raw, dtype=np.uint8)
            self.padding = buf.reshape(height, stride)[:, width * 2 :].copy()

    def show(self, rgb: np.ndarray) -> tuple[int, int] | None:
        """Write the frame; returns the rewritten row band (y0, y1) or None when unchanged."""
        px = rgb565(rgb)
        if px.shape != (self.height, self.width):
            raise ValueError(f"image {px.shape} != écran {(self.height, self.width)}")
        if self.prev is None:
            y0, y1 = 0, self.height
        else:
            rows = np.flatnonzero(np.any(px != self.prev, axis=1))
            if rows.size == 0:
                return None
            y0, y1 = int(rows[0]), int(rows[-1]) + 1
        band = px[y0:y1].view(np.uint8).reshape(y1 - y0, self.width * 2)
        if self.padding is not None:
            band = np.concatenate([band, self.padding[y0:y1]], axis=1)
        os.pwrite(self.fd, np.ascontiguousarray(band).tobytes(), y0 * self.stride)
        self.prev = px
        return y0, y1

    def invalidate(self) -> None:
        """Force the next show() to rewrite the whole frame (e.g. after the text console)."""
        self.prev = None

    def close(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            finally:
                self.fd = -1


class FileFrameBuffer(FrameBuffer):
    """A plain file laid out like a framebuffer (created when absent): tests and selftest."""

    def __init__(self, path: Path | str, width: int = 480, height: int = 320, stride: int = 0):
        stride = stride or width * 2
        p = Path(path)
        if not p.exists():
            p.write_bytes(bytes(stride * height))
        super().__init__(p, width, height, stride, 16)


def open_display(proc_fb: Path, sys_graphics: Path, dev: Path, name: str) -> FrameBuffer | None:
    """The framebuffer called ``name``, or None (logged) when absent: the caller retries."""
    try:
        idx = find_fb(Path(proc_fb).read_text(), name)
    except OSError as e:
        log.warning("écran : %s illisible (%s)", proc_fb, e)
        return None
    if idx is None:
        log.warning("écran : aucun framebuffer %s dans %s", name, proc_fb)
        return None
    try:
        w, h, bpp, stride = read_geometry(Path(sys_graphics) / f"fb{idx}")
        return FrameBuffer(Path(dev) / f"fb{idx}", w, h, stride, bpp)
    except (OSError, ValueError) as e:
        log.warning("écran : fb%d inutilisable (%s)", idx, e)
        return None
