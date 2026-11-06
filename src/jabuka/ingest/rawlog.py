"""Append-only line logs (raw Fastnet bytes, bus datagrams, derived JSONL, events JSONL).

File names: ``{prefix}-{YYYYmmddTHH}Z-{boot8}-{seq:03d}{suffix}``. boot8 is the first 8 chars of
/proc/sys/kernel/random/boot_id ("nobootid" when unavailable) so names never collide when the
clock steps after GPS sync. seq is the next free number: existing files are never overwritten.
Readers tolerate a torn last line (``iter_log_lines``).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

_BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def boot8() -> str:
    try:
        with open(_BOOT_ID_PATH) as f:
            bid = f.read().strip().replace("-", "")
        return bid[:8] or "nobootid"
    except OSError:
        return "nobootid"


def _hour_stamp(wall: float) -> str:
    return datetime.fromtimestamp(wall, tz=UTC).strftime("%Y%m%dT%H")


class RotatingAppendLog:
    def __init__(
        self,
        directory: Path,
        prefix: str,
        *,
        suffix: str = ".log",
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        flush_s: float = 1.0,
        fsync_s: float = 10.0,
        max_bytes: int = 32 * 1024 * 1024,
        min_free_bytes: int = 1_000_000_000,
        guard_prefixes: tuple[str, ...] = ("fastnet",),
    ) -> None:
        self.directory = Path(directory)
        self.prefix = prefix
        self.suffix = suffix
        self._mono = mono
        self._wall = wall
        self.flush_s = flush_s
        self.fsync_s = fsync_s
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.guard_prefixes = tuple(guard_prefixes)
        self.guard_deleted = 0
        self.lines_written = 0
        self._boot = boot8()
        self._fh: IO[bytes] | None = None
        self._hour: str | None = None
        self._size = 0
        self.current_path: Path | None = None
        self.directory.mkdir(parents=True, exist_ok=True)

    # -- file management ---------------------------------------------------------------------
    def _next_path(self, hour: str) -> Path:
        stem = f"{self.prefix}-{hour}Z-{self._boot}-"
        seq = 0
        for p in self.directory.glob(f"{stem}*{self.suffix}"):
            tail = p.name[len(stem) : len(p.name) - len(self.suffix)]
            if tail.isdigit():
                seq = max(seq, int(tail) + 1)
        return self.directory / f"{stem}{seq:03d}{self.suffix}"

    def _open(self, hour: str) -> None:
        path = self._next_path(hour)
        # "xb": exclusive create, never truncates an existing file
        self._fh = open(path, "xb")  # noqa: SIM115 - long-lived handle
        self._hour = hour
        self._size = 0
        self.current_path = path

    def _close_file(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.flush()
            os.fsync(self._fh.fileno())
        finally:
            self._fh.close()
            self._fh = None

    def _ensure_open(self, wall: float, incoming: int) -> None:
        hour = _hour_stamp(wall)
        if self._fh is None:
            self._open(hour)

    # -- writing -----------------------------------------------------------------------------
    def _write(self, data: bytes, *, fsync_now: bool = False) -> None:
        wall = self._wall()
        self._ensure_open(wall, len(data))
        assert self._fh is not None
        self._fh.write(data)
        self._size += len(data)
        self.lines_written += 1
        self._fh.flush()
        if fsync_now:
            os.fsync(self._fh.fileno())

    def write_chunk(self, b: bytes) -> None:
        """Raw bytes as ``"<t_mono:.3f> <t_wall:.3f> <hex>\\n"``."""
        self._write(f"{self._mono():.3f} {self._wall():.3f} {bytes(b).hex()}\n".encode("ascii"))

    def write_line(self, text: str) -> None:
        """Text as ``"<t_mono:.3f> <t_wall:.3f> <text>\\n"`` (newlines in text are escaped)."""
        safe = text.replace("\n", "\\n")
        self._write(f"{self._mono():.3f} {self._wall():.3f} {safe}\n".encode())

    def write_json(self, obj: dict, *, fsync_now: bool = False) -> None:
        """One JSON object per line (JSONL)."""
        import json

        line = json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n"
        self._write(line.encode("utf-8"), fsync_now=fsync_now)

    def maybe_flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        self._close_file()


def iter_log_lines(path: str | Path) -> Iterator[str]:
    """Yield complete lines (without the newline). A torn last line (no trailing newline, e.g.
    after a power cut mid-write) is skipped."""
    data = Path(path).read_bytes()
    parts = data.split(b"\n")
    for part in parts[:-1]:  # the final element is either b"" or a torn fragment
        yield part.decode("utf-8", errors="replace")
