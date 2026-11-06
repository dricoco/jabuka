"""Append-only line logs (raw Fastnet bytes, bus datagrams, derived JSONL, events JSONL).

File names: ``{prefix}-{YYYYmmddTHH}Z-{boot8}-{seq:03d}{suffix}``. boot8 is the first 8 chars of
/proc/sys/kernel/random/boot_id ("nobootid" when unavailable) so names never collide when the
clock steps after GPS sync. seq is the next free number and files are opened with exclusive
create, so an existing file is never truncated or overwritten.

Durability: flush() at most every flush_s, os.fsync at most every fsync_s (both measured on the
injected monotonic clock), plus on rotation and close(); write_json(fsync_now=True) for events.
Rotation: on UTC-hour change of the injected wall clock, or when a line would push the file past
max_bytes. Disk space is managed for the whole data volume by jabuka.ingest.retention (one policy
with per-category budgets), not per log.

Whole lines only (04-01 soak, full disk on Python 3.13): lines are buffered here and handed to
the OS through an unbuffered file (FileIO); when a batch fails half-way (ENOSPC), the file is
truncated back to its last whole line and the batch kept for a retry (up to PENDING_MAX_BYTES,
then dropped and counted in dropped_bytes). Python 3.13's BufferedWriter could leave half of a
long line on disk and drop the rest, gluing the next line to that fragment mid-file.

File names are only ever built from fixed prefixes: no user input reaches a path.
Readers tolerate a torn last line (``iter_log_lines``).
"""

from __future__ import annotations

import errno
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

log = logging.getLogger("jabuka.rawlog")

_BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"
PENDING_FLUSH_BYTES = 8192  # hand a batch to the OS at least this often (the old buffer size)
PENDING_MAX_BYTES = 4 * 1024 * 1024  # whole lines kept for a retry while the disk is full


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
    ) -> None:
        self.directory = Path(directory)
        self.prefix = prefix
        self.suffix = suffix
        self._mono = mono
        self._wall = wall
        self.flush_s = flush_s
        self.fsync_s = fsync_s
        self.max_bytes = max_bytes
        self.lines_written = 0
        self.rotations = 0
        self._boot = boot8()
        self._fh: IO[bytes] | None = None  # unbuffered (FileIO): one write(2) per call
        self._pending = bytearray()  # whole lines not yet handed to the OS
        self._disk_size = 0  # bytes of whole lines in the current file
        self.dropped_bytes = 0  # lines lost to a full disk (beyond PENDING_MAX_BYTES / at close)
        self._hour: str | None = None
        self._size = 0
        self._last_flush = 0.0
        self._last_fsync = 0.0
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
                self._fh = open(path, "xb", buffering=0)  # noqa: SIM115 - long-lived handle
                break
            except FileExistsError:  # raced with another writer: take the next seq
                continue
        self._hour = hour
        self._size = 0
        self._disk_size = 0
        now = self._mono()
        self._last_flush = now
        self._last_fsync = now
        self._dirty = False
        self.current_path = path

    def _flush_pending(self) -> None:
        """Hand the pending whole lines to the OS. On failure the file is cut back to its last
        whole line, the lines stay pending (bounded) and the error propagates."""
        fh = self._fh
        if fh is None or not self._pending:
            return
        start = self._disk_size
        data = bytes(self._pending)
        written = 0
        try:
            while written < len(data):
                n = fh.write(data[written:])  # FileIO: one raw write(2), may be short
                if not n:
                    raise OSError(errno.ENOSPC, "no progress writing the log")
                written += n
        except OSError:
            if written:
                try:  # never a fragment on disk: back to the last whole line
                    fh.truncate(start)
                    fh.seek(start)
                except OSError:
                    log.exception("log rollback failed")
            if len(self._pending) > PENDING_MAX_BYTES:
                self.dropped_bytes += len(self._pending)
                self._pending.clear()
            raise
        self._disk_size = start + written
        self._pending.clear()

    def _close_file(self) -> None:
        if self._fh is None:
            return
        try:
            self._flush_pending()
            os.fsync(self._fh.fileno())
        finally:
            self._fh.close()
            self._fh = None
            if self._pending:  # the disk was still full: lost with this file
                self.dropped_bytes += len(self._pending)
                self._pending.clear()

    def _rotate_if_needed(self, wall: float, incoming: int) -> None:
        hour = _hour_stamp(wall)
        if self._fh is None:
            self._open(hour)
            return
        if hour != self._hour or (self._size > 0 and self._size + incoming > self.max_bytes):
            self._close_file()
            self.rotations += 1
            self._open(hour)

    # -- writing -----------------------------------------------------------------------------
    def _write(self, data: bytes, *, fsync_now: bool = False) -> None:
        now = self._mono()
        self._rotate_if_needed(self._wall(), len(data))
        fh = self._fh
        assert fh is not None
        self._pending += data
        self._size += len(data)
        self.lines_written += 1
        self._dirty = True
        if fsync_now:
            self._flush_pending()
            os.fsync(fh.fileno())
            self._last_flush = self._last_fsync = now
            self._dirty = False
        else:
            if len(self._pending) >= PENDING_FLUSH_BYTES:
                self._flush_pending()
            self._cadence(now)

    def _cadence(self, now: float) -> None:
        fh = self._fh
        if fh is None or not self._dirty:
            return
        if now - self._last_flush >= self.flush_s:
            self._flush_pending()
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
