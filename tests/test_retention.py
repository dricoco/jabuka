"""CR-01: one retention policy for the whole data volume (budgets, reserve, raw floor)."""

from __future__ import annotations

import os
from collections import namedtuple
from pathlib import Path

import pytest

from jabuka.ingest.retention import CATEGORIES, RAW_FLOOR_S, Retention

DU = namedtuple("DU", "total used free")
H = 3600.0
T0 = 1_800_000_000.0  # newest file's mtime


class FakeDisk:
    """total bytes; free = total - base_used - bytes of every file under root."""

    def __init__(self, root: Path, total: int, base_used: int = 0) -> None:
        self.root = root
        self.total = total
        self.base_used = base_used

    def __call__(self, path: Path) -> DU:
        files = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        used = self.base_used + files
        return DU(self.total, used, self.total - used)


class Mono:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _mk(root: Path, cat: str, age_h: float, size: int, seq: int = 0) -> Path:
    sub, prefix = CATEGORIES[cat]
    suffix = ".jsonl" if cat in ("derived", "events") else ".log"
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{prefix}-h{age_h:08.2f}-{seq:03d}{suffix}"
    p.write_bytes(b"x" * size)
    mtime = T0 - age_h * H
    os.utime(p, (mtime, mtime))
    return p


def _hours(root: Path, cat: str, n: int, size: int) -> list[Path]:
    """n hourly files, oldest first (age n-1 .. 0 hours)."""
    return [_mk(root, cat, float(age), size) for age in range(n - 1, -1, -1)]


def test_budget_prunes_each_category_to_its_share(tmp_path: Path) -> None:
    disk = FakeDisk(tmp_path, total=10**9)
    derived = _hours(tmp_path, "derived", 10, 1000)  # 10 kB, share 20 % of 20 kB = 4 kB
    raw = _hours(tmp_path, "raw", 10, 1000)  # 10 kB, share 50 % = 10 kB: fits
    r = Retention(tmp_path, budget_bytes=20_000, disk_usage=disk, reserve_bytes=0)
    r.run()
    assert [p.exists() for p in derived] == [False] * 6 + [True] * 4  # oldest went first
    assert all(p.exists() for p in raw)
    assert r.used["derived"] == 4000
    assert r.deleted == 6
    st = r.status()
    assert st["state"] == "ok"
    assert st["used_bytes"]["raw"] == 10_000


def test_events_and_derived_are_pruned_too(tmp_path: Path) -> None:
    """Regression: the old per-log guards never pruned derived/ and events/."""
    disk = FakeDisk(tmp_path, total=10**9)
    events = _hours(tmp_path, "events", 4, 1000)
    derived = _hours(tmp_path, "derived", 4, 1000)
    Retention(tmp_path, budget_bytes=10_000, disk_usage=disk, reserve_bytes=0).run()
    assert not events[0].exists() and events[-1].exists()  # 5 % of 10 kB = 500 B
    assert not derived[0].exists() and derived[-1].exists()  # 20 % = 2 kB


def test_raw_floor_survives_budget(tmp_path: Path) -> None:
    disk = FakeDisk(tmp_path, total=10**9)
    raw = _hours(tmp_path, "raw", 48, 1000)  # 48 h of raw, budget allows 5 files
    Retention(tmp_path, budget_bytes=10_000, disk_usage=disk, reserve_bytes=0).run()
    kept = [p for p in raw if p.exists()]
    ages = sorted(T0 - p.stat().st_mtime for p in kept)
    assert ages[-1] <= RAW_FLOOR_S  # everything outside the floor went
    assert len(kept) == 37  # ages 0..36 h inclusive: >= 36 h of raw history kept


def test_reserve_prunes_in_order_bus_derived_gps_then_raw(tmp_path: Path) -> None:
    # 100 kB disk, reserve 30 kB. Logs 80 kB -> free 20 kB: need to free >= 10 kB.
    disk = FakeDisk(tmp_path, total=100_000)
    bus = _hours(tmp_path, "bus", 6, 2000)  # 12 kB, 5 deletable (newest protected)
    derived = _hours(tmp_path, "derived", 6, 2000)
    raw = _hours(tmp_path, "raw", 28, 2000)  # 56 kB, all inside the floor
    r = Retention(tmp_path, reserve_bytes=30_000, enforce_budgets=False, disk_usage=disk)
    r.run()
    assert [p.exists() for p in bus] == [False] * 5 + [True]
    # 10 kB from bus is exactly enough: derived untouched
    assert all(p.exists() for p in derived)
    assert all(p.exists() for p in raw)
    assert r.reserve_deletions == 5
    assert r.status()["state"] == "pruning"


def test_reserve_raw_outside_floor_before_raw_inside(tmp_path: Path) -> None:
    disk = FakeDisk(tmp_path, total=200_000)
    raw = _hours(tmp_path, "raw", 40, 2000)  # 80 kB; ages 39..0; 3 files (39, 38, 37) outside
    r = Retention(tmp_path, reserve_bytes=126_000, enforce_budgets=False, disk_usage=disk)
    r.run()  # free 120 kB -> needs 6 kB: exactly the three files outside the floor
    assert [p.exists() for p in raw[:4]] == [False, False, False, True]
    assert r.raw_floor_breaches == 0
    # disk now fuller (e.g. something else wrote): the floor is breached only as a last resort
    disk.base_used = 10_000
    r.run()
    assert r.raw_floor_breaches >= 1
    assert raw[-1].exists()  # newest raw (the open file) is never deleted


def test_newest_file_and_protected_paths_never_deleted(tmp_path: Path) -> None:
    disk = FakeDisk(tmp_path, total=10_000)
    bus = _hours(tmp_path, "bus", 3, 3000)
    r = Retention(tmp_path, reserve_bytes=9_999, enforce_budgets=False, disk_usage=disk)
    r.run(protect=[bus[0]])
    assert bus[0].exists()  # protected by the caller
    assert not bus[1].exists()
    assert bus[2].exists()  # newest of its category
    assert r.status()["state"] == "low"  # could not get back above the reserve


def test_other_files_are_never_touched(tmp_path: Path) -> None:
    disk = FakeDisk(tmp_path, total=10_000)
    (tmp_path / "raw").mkdir()
    keep = [tmp_path / "raw" / "notes.txt", tmp_path / "raw" / "fastnet-x.log.bak"]
    for p in keep:
        p.write_bytes(b"z" * 4000)
    _hours(tmp_path, "raw", 2, 10)
    Retention(tmp_path, reserve_bytes=9_999, disk_usage=disk).run()
    assert all(p.exists() for p in keep)


def test_rate_limited_on_the_injected_clock(tmp_path: Path) -> None:
    disk = FakeDisk(tmp_path, total=10**9)
    mono = Mono()
    r = Retention(tmp_path, budget_bytes=1000, reserve_bytes=0, disk_usage=disk, mono=mono)
    assert r.maybe_run() is True
    mono.t = 30
    assert r.maybe_run() is False
    mono.t = 61
    assert r.maybe_run() is True
    assert r.runs == 2


def test_default_budget_and_reserve_scale_with_the_disk(tmp_path: Path) -> None:
    gb = 1_000_000_000
    r = Retention(tmp_path, disk_usage=lambda p: DU(16 * gb, 4 * gb, 12 * gb))
    st = r.status()
    assert st["budget_bytes"] == 8 * gb
    assert st["reserve_bytes"] == gb
    # 36 h of raw at ~0.5 GB/day fits well inside raw's share of a 16 GB card's budget
    assert 0.5 * st["budget_bytes"] > 1.5 * 0.5 * gb
    tiny = Retention(tmp_path, disk_usage=lambda p: DU(10**6, 0, 10**6))
    assert tiny.status()["reserve_bytes"] == 100_000


def test_errors_are_reported_not_raised(tmp_path: Path) -> None:
    def broken(path: Path) -> DU:
        raise OSError(5, "EIO")

    r = Retention(tmp_path, disk_usage=broken)
    r.run()  # never raises
    assert r.errors == 1
    st = r.status()
    assert st["state"] == "error"
    assert st["free_bytes"] is None


@pytest.mark.parametrize("cat", sorted(CATEGORIES))
def test_every_category_is_scanned(tmp_path: Path, cat: str) -> None:
    disk = FakeDisk(tmp_path, total=10**9)
    _hours(tmp_path, cat, 3, 100)
    r = Retention(tmp_path, reserve_bytes=0, disk_usage=disk)
    r.run()
    assert r.used[cat] == 300


def test_ingest_heartbeat_reports_disk(tmp_path: Path) -> None:
    from jabuka.ingest.fastnet_main import FastnetIngest
    from jabuka.ingest.rawlog import RotatingAppendLog

    rawlog = RotatingAppendLog(tmp_path / "raw", "fastnet")
    ingest = FastnetIngest(rawlog, lambda b: None)
    assert "disk_state" not in ingest.health()
    disk = FakeDisk(tmp_path, total=10_000, base_used=9_900)
    ingest.retention = Retention(tmp_path, enforce_budgets=False, disk_usage=disk)
    h = ingest.health()
    rawlog.close()
    assert h["disk_state"] == "low"
    assert h["disk_free_bytes"] == 100
    assert h["retention_deleted"] == 0
