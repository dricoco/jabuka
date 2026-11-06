"""jabuka-logcheck: every log and state file is valid after a crash or power pull."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from jabuka.common.atomicio import atomic_write_json
from jabuka.ingest.rawlog import RotatingAppendLog
from jabuka.tools.logcheck import check_dir, main


class _Clock:
    def __init__(self) -> None:
        self.mono = 100.0
        self.wall = 1_762_470_000.0

    def m(self) -> float:
        return self.mono

    def w(self) -> float:
        return self.wall


def _valid_tree(root: Path) -> Path:
    """A logs/ tree written by the real writers, like a running Pi produces."""
    logs = root / "logs"
    c = _Clock()
    raw = RotatingAppendLog(logs / "raw", "fastnet", mono=c.m, wall=c.w)
    bus = RotatingAppendLog(logs / "bus", "bus", mono=c.m, wall=c.w)
    gps = RotatingAppendLog(logs / "gps", "gps", mono=c.m, wall=c.w)
    derived = RotatingAppendLog(logs / "derived", "derived", suffix=".jsonl", mono=c.m, wall=c.w)
    events = RotatingAppendLog(logs / "events", "events", suffix=".jsonl", mono=c.m, wall=c.w)
    for i in range(5):
        c.mono += 1
        c.wall += 1
        raw.write_chunk(bytes([0xFF, 0x75, 0x14, 0x01, i]))
        bus.write_line(json.dumps({"v": 1, "src": "fastnet", "label": "with spaces", "i": i}))
        gps.write_line(json.dumps({"class": "TPV", "mode": 3, "i": i}))
        derived.write_json({"type": "derived", "i": i})
    events.write_json({"type": "event", "n": 1, "label": "mark"}, fsync_now=True)
    for lg in (raw, bus, gps, derived, events):
        lg.close()
    atomic_write_json(root / "state" / "settings.json", {"awa_sign": 1})
    return logs


def _by_name(report) -> dict[str, object]:
    return {Path(f.path).name: f for f in report.files}


def _only(report, prefix: str):
    hits = [f for f in report.files if Path(f.path).name.startswith(prefix)]
    assert len(hits) == 1, [f.path for f in report.files]
    return hits[0]


def test_valid_tree_is_ok(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    report = check_dir(tmp_path)
    assert report.ok
    kinds = sorted(f.kind for f in report.files)
    assert kinds == ["json", "jsonl", "jsonl", "line-json", "line-json", "raw"]
    raw = _only(report, "fastnet-")
    assert raw.lines == 5 and raw.torn_tail is False and raw.errors == []
    assert _only(report, "settings.json").source == "main"
    assert main([str(tmp_path)]) == 0


def test_torn_tail_is_reported_not_an_error(tmp_path: Path) -> None:
    logs = _valid_tree(tmp_path)
    raw = next((logs / "raw").glob("fastnet-*.log"))
    with open(raw, "ab") as f:
        f.write(b"105.000 1762470005.000 ff75")  # power cut mid-line: no newline
    derived = next((logs / "derived").glob("derived-*.jsonl"))
    with open(derived, "ab") as f:
        f.write(b'{"type":"derived","i":')
    report = check_dir(tmp_path)
    assert report.ok
    assert _only(report, "fastnet-").torn_tail is True
    assert _only(report, "fastnet-").lines == 5
    assert _only(report, "derived-").torn_tail is True
    assert _only(report, "bus-").torn_tail is False
    assert main([str(tmp_path)]) == 0


@pytest.mark.parametrize(
    ("subdir", "glob", "bad_line"),
    [
        ("raw", "fastnet-*.log", b"101.000 1762470001.000 ff7g"),  # bad hex
        ("raw", "fastnet-*.log", b"101.000 1762470001.000 ff7"),  # odd length
        ("raw", "fastnet-*.log", b"101.000 ff75"),  # two fields
        ("raw", "fastnet-*.log", b"abc 1762470001.000 ff75"),  # t_mono not a float
        ("bus", "bus-*.log", b'101.000 1762470001.000 {"v":1,'),  # bad JSON
        ("gps", "gps-*.log", b"101.000 nan-ish {}"),  # t_wall not a float
        ("derived", "derived-*.jsonl", b'{"type":"derived"'),
        ("events", "events-*.jsonl", b"\xff\xfe not utf-8"),
        ("derived", "derived-*.jsonl", b""),  # empty line: writers never produce one
    ],
)
def test_corrupt_complete_line_in_the_middle(
    tmp_path: Path, subdir: str, glob: str, bad_line: bytes, capsys
) -> None:
    logs = _valid_tree(tmp_path)
    path = next((logs / subdir).glob(glob))
    lines = path.read_bytes().split(b"\n")
    if len(lines) < 3:  # events has one line: append a valid one after the bad one
        lines = [lines[0], bad_line, lines[0], b""]
        bad_no = 2
    else:
        lines.insert(1, bad_line)
        bad_no = 2
    path.write_bytes(b"\n".join(lines))
    report = check_dir(tmp_path)
    assert report.ok is False
    bad = _by_name(report)[path.name]
    assert bad.errors, bad
    assert bad.errors[0].startswith(f"line {bad_no}:"), bad.errors
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert path.name in out
    assert f"line {bad_no}" in out


def test_json_state_recovered_from_bak(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    state = tmp_path / "state" / "settings.json"
    atomic_write_json(state, {"awa_sign": -1})  # previous version is now settings.json.bak
    state.write_bytes(b'{"awa_si')  # truncated main file
    report = check_dir(tmp_path)
    assert report.ok
    f = _only(report, "settings.json")
    assert f.source == "bak"
    assert f.errors == []
    assert main([str(tmp_path)]) == 0


def test_json_state_both_unreadable(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    state = tmp_path / "state" / "settings.json"
    atomic_write_json(state, {"awa_sign": -1})
    state.write_bytes(b"{")
    state.with_name("settings.json.bak").write_bytes(b"")
    report = check_dir(tmp_path)
    assert report.ok is False
    assert _only(report, "settings.json").source is None
    assert main([str(tmp_path)]) == 1


def test_bak_and_tmp_files_are_not_checked_on_their_own(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    state = tmp_path / "state"
    atomic_write_json(state / "settings.json", {"awa_sign": -1})
    (state / ".settings.json.tmp").write_bytes(b"{half")  # crash before the rename
    report = check_dir(tmp_path)
    assert report.ok
    names = [Path(f.path).name for f in report.files]
    assert "settings.json.bak" not in names
    assert ".settings.json.tmp" not in names


def test_capture_prefix_is_raw(tmp_path: Path) -> None:
    (tmp_path / "capture-20261112T10Z-abcd1234-000.log").write_bytes(b"1.0 2.0 ff75\n")
    report = check_dir(tmp_path)
    assert report.ok
    assert report.files[0].kind == "raw"


def test_json_output(tmp_path: Path, capsys) -> None:
    _valid_tree(tmp_path)
    assert main([str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert len(data["files"]) == 6
    for f in data["files"]:
        assert {"path", "kind", "lines", "torn_tail", "errors"} <= set(f)


def test_empty_dir_is_ok(tmp_path: Path) -> None:
    report = check_dir(tmp_path)
    assert report.ok and report.files == []


def test_missing_dir_is_a_usage_error(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2


def test_console_script_help() -> None:
    exe = Path(sys.executable).parent / "jabuka-logcheck"
    proc = subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    assert "DIR" in proc.stdout
