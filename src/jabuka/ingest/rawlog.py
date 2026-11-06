"""Append-only line logs (raw Fastnet bytes, bus datagrams, derived JSONL, events JSONL).

File names: ``{prefix}-{YYYYmmddTHH}Z-{boot8}-{seq:03d}{suffix}``. boot8 is the first 8 chars of
/proc/sys/kernel/random/boot_id ("nobootid" when unavailable) so names never collide when the
clock steps after GPS sync. seq is the next free number and files are opened with exclusive
create, so an existing file is never truncated or overwritten.

Durability: flush() at most every flush_s, os.fsync at most every fsync_s (both measured on the
injected monotonic clock), plus on rotation and close(); write_json(fsync_now=True) for events.
Rotation: on UTC-hour change of the injected wall clock, or when a line would push the file past
max_bytes. Disk guard: at most once per 60 s, if free space < min_free_bytes, delete the oldest
files whose names start with one of guard_prefixes (never the open file).

File names are only ever built from fixed prefixes: no user input reaches a path.
Readers tolerate a torn last line (``iter_log_lines``).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

log = logging.getLogger("jabuka.rawlog")

_BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
GUARD_INTERVAL_S = 60.0


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
        self.rotations = 0
        self._boot = boot8()
        self._fh: IO[bytes] | None = None
        self._hour: str | None = None
        self._size = 0
        self._last_flush = 0.0
        self._last_fsync = 0.0
        self._last_guard: float | None = None
        self._dirty = False
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
        while True:
            path = self._next_path(hour)
            try:
                # "xb": exclusive create, never truncates an existing file
                self._fh = open(path, "xb")  # noqa: SIM115 - long-lived handle
                break
            except FileExistsError:  # raced with another writer: take the next seq
                continue
        self._hour = hour
        self._size = 0
        now = self._mono()
        self._last_flush = now
        self._last_fsync = now
        self._dirty = False
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

    def _rotate_if_needed(self, wall: float, incoming: int) -> None:
        hour = _hour_stamp(wall)
        if self._fh is None:
            self._open(hour)
            return
        if hour != self._hour or (self._size > 0 and self._size + incoming > self.max_bytes):
            self._close_file()
            self.rotations += 1
            self._open(hour)

    # -- disk guard --------------------------------------------------------------------------
    def _guard(self, now: float) -> None:
        if self._last_guard is not None and now - self._last_guard < GUARD_INTERVAL_S:
            return
        self._last_guard = now
        if self.min_free_bytes <= 0 or not self.guard_prefixes:
            return
        try:
            if shutil.disk_usage(self.directory).free >= self.min_free_bytes:
                return
            candidates = []
            for p in self.directory.iterdir():
                if not p.is_file() or p == self.current_path:
                    continue
                if not p.name.startswith(self.guard_prefixes):
                    continue
                try:
                    candidates.append((p.stat().st_mtime, p.name, p))
                except OSError:
                    continue
            candidates.sort()
            for _, _, p in candidates:
                try:
                    p.unlink()
                    self.guard_deleted += 1
                    log.warning("disk guard: deleted %s", p.name)
                except OSError:
                    continue
                if shutil.disk_usage(self.directory).free >= self.min_free_bytes:
                    break
        except OSError as e:
            log.warning("disk guard failed: %s", e)

    # -- writing -----------------------------------------------------------------------------
    def _write(self, data: bytes, *, fsync_now: bool = False) -> None:
        now = self._mono()
        self._rotate_if_needed(self._wall(), len(data))
        fh = self._fh
        assert fh is not None
        fh.write(data)
        self._size += len(data)
        self.lines_written += 1
        self._dirty = True
        if fsync_now:
            fh.flush()
            os.fsync(fh.fileno())
            self._last_flush = self._last_fsync = now
            self._dirty = False
        else:
            self._cadence(now)
        self._guard(now)

    def _cadence(self, now: float) -> None:
        fh = self._fh
        if fh is None or not self._dirty:
            return
        if now - self._last_flush >= self.flush_s:
            fh.flush()
            self._last_flush = now
            if now - self._last_fsync >= self.fsync_s:
                os.fsync(fh.fileno())
                self._last_fsync = now
                self._dirty = False

    def write_chunk(self, b: bytes) -> None:
        """Raw bytes as ``"<t_mono:.3f> <t_wall:.3f> <hex>\\n"``."""
        self._write(f"{self._mono():.3f} {self._wall():.3f} {bytes(b).hex()}\n".encode("ascii"))

    def write_line(self, text: str) -> None:
        """Text as ``"<t_mono:.3f> <t_wall:.3f> <text>\\n"`` (newlines in text are escaped)."""
        safe = text.replace("\r", "\\r").replace("\n", "\\n")
        self._write(f"{self._mono():.3f} {self._wall():.3f} {safe}\n".encode())

    def write_json(self, obj: dict, *, fsync_now: bool = False) -> None:
        """One JSON object per line (JSONL)."""
        line = json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n"
        self._write(line.encode("utf-8"), fsync_now=fsync_now)

    def maybe_flush(self) -> None:
        """Apply the flush/fsync cadence without writing (call from a periodic task)."""
        self._cadence(self._mono())

    def close(self) -> None:
        self._close_file()


def iter_log_lines(path: str | Path) -> Iterator[str]:
    """Yield complete lines (without the newline). A torn last line (no trailing newline, e.g.
    after a power cut mid-write) is skipped. Invalid UTF-8 is replaced, never raised."""
    data = Path(path).read_bytes()
    parts = data.split(b"\n")
    for part in parts[:-1]:  # the final element is either b"" or a torn fragment
        yield part.decode("utf-8", errors="replace")
