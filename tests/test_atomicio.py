"""Crash-safe JSON files: tmp + fsync + rename + dir fsync, previous version kept as NAME.bak."""

from __future__ import annotations

from pathlib import Path

from jabuka.common.atomicio import atomic_write_bytes, atomic_write_json, load_json_with_bak


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "course.json"
    atomic_write_json(p, {"b": 2, "a": [1, 2, 3], "name": "Jabuka"})
    assert load_json_with_bak(p, None) == {"a": [1, 2, 3], "b": 2, "name": "Jabuka"}
    assert p.read_bytes() == b'{"a":[1,2,3],"b":2,"name":"Jabuka"}'


def test_second_write_keeps_previous_as_bak(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, {"v": 1})
    assert not (tmp_path / "state.json.bak").exists()
    atomic_write_json(p, {"v": 2})
    assert load_json_with_bak(p, None) == {"v": 2}
    assert load_json_with_bak(tmp_path / "state.json.bak", None) == {"v": 1}


def test_truncated_main_falls_back_to_bak(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, {"v": 1, "pad": "x" * 50})
    atomic_write_json(p, {"v": 2, "pad": "y" * 50})
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])  # simulated torn write / power cut
    assert load_json_with_bak(p, None) == {"v": 1, "pad": "x" * 50}


def test_leftover_tmp_is_ignored(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, {"v": 1})
    (tmp_path / ".state.json.tmp").write_bytes(b'{"v": 999')
    assert load_json_with_bak(p, None) == {"v": 1}
    atomic_write_json(p, {"v": 2})  # a stale tmp never blocks the next write
    assert load_json_with_bak(p, None) == {"v": 2}


def test_missing_file_returns_default(tmp_path: Path) -> None:
    assert load_json_with_bak(tmp_path / "nope.json", {"default": True}) == {"default": True}


def test_garbage_main_and_bak_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_bytes(b"\xff\xfe not json")
    (tmp_path / "x.json.bak").write_bytes(b"{broken")
    assert load_json_with_bak(p, 42) == 42


def test_atomic_write_bytes_replaces(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    atomic_write_bytes(p, b"one")
    atomic_write_bytes(p, b"two")
    assert p.read_bytes() == b"two"
    assert (tmp_path / "blob.bin.bak").read_bytes() == b"one"
    assert not (tmp_path / ".blob.bin.tmp").exists()
    assert not (tmp_path / ".blob.bin.bak.tmp").exists()
