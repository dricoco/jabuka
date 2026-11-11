"""Text console of tty1: KD_GRAPHICS while the menu draws, KD_TEXT again afterwards.

Never VT_ACTIVATE or switch VTs here: logind could spawn autovt@tty1 (= getty@tty1), which
conflicts with jabuka-touch.service and would stop the menu.
"""

from __future__ import annotations

import fcntl
import logging
import os
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("jabuka_touch.console")

KDSETMODE = 0x4B3A
KD_TEXT = 0
KD_GRAPHICS = 1


class Console:
    def __init__(
        self, tty_path: Path | str = "/dev/tty1", ioctl: Callable[..., object] = fcntl.ioctl
    ):
        self.tty_path = str(tty_path)
        self.ioctl = ioctl

    def _set(self, mode: int) -> None:
        fd = os.open(self.tty_path, os.O_RDWR | os.O_NOCTTY)
        try:
            self.ioctl(fd, KDSETMODE, mode)
        finally:
            os.close(fd)

    def graphics(self) -> bool:
        """KD_GRAPHICS (the console stops drawing on the screen); False when impossible."""
        try:
            self._set(KD_GRAPHICS)
            return True
        except OSError as e:
            log.warning("console : KD_GRAPHICS impossible sur %s (%s)", self.tty_path, e)
            return False

    def text(self) -> bool:
        """KD_TEXT; never raises (missing tty is logged)."""
        try:
            self._set(KD_TEXT)
            return True
        except Exception as e:  # noqa: BLE001 - called from finally blocks and ExecStopPost
            log.warning("console : KD_TEXT impossible sur %s (%s)", self.tty_path, e)
            return False
