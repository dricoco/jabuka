"""One retention policy for the whole data volume (``<data-dir>/logs``).

Every log category has a byte budget, a share of one total budget. The total defaults to half of
the filesystem that holds the logs. Two rules apply, in this order:

1. Budgets (only where ``enforce_budgets``, i.e. the core, which owns the policy): a category over
   its share loses its oldest files until it fits. Raw files inside the raw floor (the newest
   ``raw_floor_s`` of raw history, default 36 h) are never deleted for budget reasons.
2. Free-space reserve (core AND ingest, so the disk is protected even while the core is down):
   while free space is below ``reserve_bytes`` the oldest files are deleted across categories in
   PRUNE_ORDER (bus, derived, gps, events, then raw outside the floor). Raw inside the floor goes
   only as a last resort, and each such deletion is counted in ``raw_floor_breaches``.

Never deleted: the newest file of each category (the file its writer has open, whichever process
that is) and any path passed in ``protect``.

Ages are relative to the newest raw file's mtime, not to a clock, so a clock step after GPS sync
cannot make the whole raw history look old (or new). Deletions are rate-limited to one pass per
``interval_s`` of the injected monotonic clock.

Sizing (rates measured on the 2026-05-14 capture at full bus load): raw ~0.5 GB/day, derived
~0.65 GB/day, gps ~0.1-0.2 GB/day, bus ~4 GB/day (opt-in, off on the Pi). On a 16 GB card the
default total budget is ~7 GB, so raw (50 %) keeps about a week and the 36 h floor (~0.75 GB) is
always inside its share.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("jabuka.retention")

# category -> (sub-directory of logs/, file-name prefix)
CATEGORIES: dict[str, tuple[str, str]] = {
    "raw": ("raw", "fastnet"),
    "bus": ("bus", "bus"),
    "derived": ("derived", "derived"),
    "gps": ("gps", "gps"),
    "events": ("events", "events"),
}
# deletion order under free-space pressure: most reproducible first, the primary record last
PRUNE_ORDER: tuple[str, ...] = ("bus", "derived", "gps", "events", "raw")
DEFAULT_SHARES: dict[str, float] = {
    "raw": 0.50,
    "derived": 0.20,
    "bus": 0.15,
    "gps": 0.10,
    "events": 0.05,
}
DEFAULT_BUDGET_FRACTION = 0.5
DEFAULT_RESERVE_BYTES = 1_000_000_000
RESERVE_MAX_FRACTION = 0.10  # small filesystems: the reserve is at most 10 % of the total
RAW_FLOOR_S = 36 * 3600.0
INTERVAL_S = 60.0
LOG_SUFFIXES = (".log", ".jsonl")


@dataclass(frozen=True)
class _File:
    mtime: float
    name: str
    size: int
    path: Path


class Retention:
    def __init__(
        self,
        logs_root: Path,
        *,
        budget_bytes: int | None = None,
        budget_fraction: float = DEFAULT_BUDGET_FRACTION,
        reserve_bytes: int | None = None,
        shares: dict[str, float] | None = None,
        raw_floor_s: float = RAW_FLOOR_S,
        enforce_budgets: bool = True,
        interval_s: float = INTERVAL_S,
        mono: Callable[[], float] = time.monotonic,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        self.root = Path(logs_root)
        self.budget_bytes = budget_bytes
        self.budget_fraction = budget_fraction
        self._reserve = reserve_bytes
        self.shares = dict(DEFAULT_SHARES if shares is None else shares)
        self.raw_floor_s = raw_floor_s
        self.enforce_budgets = enforce_budgets
        self.interval_s = interval_s
        self._mono = mono
        self._disk_usage = disk_usage
        self._last_run: float | None = None
        # counters (process lifetime)
        self.runs = 0
        self.deleted = 0
        self.deleted_bytes = 0
        self.reserve_deletions = 0
        self.raw_floor_breaches = 0
        self.errors = 0
        self.last_error: str | None = None
        # results of the last pass
        self.used: dict[str, int] = dict.fromkeys(CATEGORIES, 0)
        self.raw_span_h: float | None = None
        self.low_space = False
        self.pass_reserve_deletions = 0

    # -- sizing ------------------------------------------------------------------------------
    def _usage(self) -> Any:
        self.root.mkdir(parents=True, exist_ok=True)
        return self._disk_usage(self.root)

    def total_budget(self, total: int) -> int:
        if self.budget_bytes is not None:
            return int(self.budget_bytes)
        return int(total * self.budget_fraction)

    def reserve_bytes(self, total: int) -> int:
        if self._reserve is not None:
            return int(self._reserve)
        return int(min(DEFAULT_RESERVE_BYTES, total * RESERVE_MAX_FRACTION))

    # -- scanning ----------------------------------------------------------------------------
    def _scan(self) -> dict[str, list[_File]]:
        out: dict[str, list[_File]] = {}
        for cat, (sub, prefix) in CATEGORIES.items():
            files: list[_File] = []
            d = self.root / sub
            try:
                entries = list(d.iterdir())
            except FileNotFoundError:
                entries = []
            for p in entries:
                if not p.name.startswith(prefix + "-") or not p.name.endswith(LOG_SUFFIXES):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if not os.path.isfile(p):
                    continue
                files.append(_File(st.st_mtime, p.name, st.st_size, p))
            files.sort(key=lambda f: (f.mtime, f.name))  # oldest first
            out[cat] = files
        return out

    # -- one pass ----------------------------------------------------------------------------
    def maybe_run(self, protect: Iterable[Path | None] = ()) -> bool:
        """Run a pass if interval_s has elapsed since the last one. Never raises."""
        now = self._mono()
        if self._last_run is not None and now - self._last_run < self.interval_s:
            return False
        self._last_run = now
        self.run(protect)
        return True

    def run(self, protect: Iterable[Path | None] = ()) -> None:
        """One retention pass. Never raises (errors are counted and logged)."""
        try:
            self._run(protect)
            self.last_error = None
        except Exception as e:
            self.errors += 1
            self.last_error = str(e)
            log.warning("retention pass failed: %s", e)

    def _run(self, protect: Iterable[Path | None]) -> None:
        self.runs += 1
        self.pass_reserve_deletions = 0
        files = self._scan()
        protected = {Path(p) for p in protect if p is not None}
        for lst in files.values():
            if lst:
                protected.add(lst[-1].path)  # newest of each category: its writer's open file
        raw = files["raw"]
        newest_raw = raw[-1].mtime if raw else None
        floor_from = newest_raw - self.raw_floor_s if newest_raw is not None else None

        def in_floor(cat: str, f: _File) -> bool:
            return cat == "raw" and floor_from is not None and f.mtime >= floor_from

        def delete(cat: str, f: _File, why: str) -> bool:
            try:
                f.path.unlink()
            except FileNotFoundError:  # the other process pruned it first
                files[cat].remove(f)
                return True
            except OSError as e:
                log.warning("retention: cannot delete %s: %s", f.name, e)
                return False
            files[cat].remove(f)
            self.deleted += 1
            self.deleted_bytes += f.size
            log.warning("retention (%s): deleted %s/%s (%d bytes)", why, cat, f.name, f.size)
            return True

        du = self._usage()
        total = int(du.total)

        # 1. per-category budgets
        if self.enforce_budgets:
            budget = self.total_budget(total)
            for cat in PRUNE_ORDER:
                cap = int(budget * self.shares.get(cat, 0.0))
                usage = sum(f.size for f in files[cat])
                for f in list(files[cat]):
                    if usage <= cap:
                        break
                    if f.path in protected or in_floor(cat, f):
                        continue
                    if delete(cat, f, "budget"):
                        usage -= f.size

        # 2. free-space reserve: last resort, raw inside the floor
        reserve = self.reserve_bytes(total)
        free = int(self._usage().free)
        if free < reserve:
            passes = [(cat, False) for cat in PRUNE_ORDER] + [("raw", True)]
            for cat, floor_ok in passes:
                for f in list(files[cat]):
                    if free >= reserve:
                        break
                    if f.path in protected or (in_floor(cat, f) and not floor_ok):
                        continue
                    breach = in_floor(cat, f)
                    if delete(cat, f, "free space"):
                        self.reserve_deletions += 1
                        self.pass_reserve_deletions += 1
                        if breach:
                            self.raw_floor_breaches += 1
                            log.error("retention: raw history inside the floor deleted (disk full)")
                        free = int(self._usage().free)
                if free >= reserve:
                    break
        self.low_space = free < reserve

        self.used = {cat: sum(f.size for f in lst) for cat, lst in files.items()}
        raw = files["raw"]
        self.raw_span_h = round((raw[-1].mtime - raw[0].mtime) / 3600.0, 2) if raw else None

    # -- reporting ---------------------------------------------------------------------------
    def status(self) -> dict:
        """Disk + retention state for diag/heartbeat. free_bytes is read live; the rest is from the
        last pass. state: ok | pruning (the last pass had to delete for free space) | low (below
        the reserve) | error (the last pass failed)."""
        out: dict[str, Any] = {}
        try:
            du = self._usage()
            total, free = int(du.total), int(du.free)
            out.update(
                free_bytes=free,
                total_bytes=total,
                budget_bytes=self.total_budget(total),
                reserve_bytes=self.reserve_bytes(total),
            )
            low = free < self.reserve_bytes(total) or self.low_space
        except OSError as e:
            out.update(free_bytes=None, total_bytes=None)
            self.last_error = str(e)
            low = True
        if self.last_error is not None:
            state = "error"
        elif low:
            state = "low"
        elif self.pass_reserve_deletions:
            state = "pruning"
        else:
            state = "ok"
        out.update(
            state=state,
            used_bytes=dict(self.used),
            raw_history_h=self.raw_span_h,
            deleted=self.deleted,
            deleted_bytes=self.deleted_bytes,
            reserve_deletions=self.reserve_deletions,
            raw_floor_breaches=self.raw_floor_breaches,
            errors=self.errors,
            last_error=self.last_error,
        )
        return out
