"""fastnet-probe against pty replays (ok / swap wires / silent / noisy) and capture files, plus the
pty-replay fault injection it is tested with."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest
from jabuka.tools.probe import run_probe

from jabuka.ingest.fastnet_framing import load_capture
from jabuka.sim.pty_replay import PtyFeeder, build_arg_parser, replay_bytes
from jabuka.tools import probe as probe_mod

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fastnet"
EXAMPLE2 = FIX / "example2_fastnet_data.txt"
RAWFN = FIX / "rawfn-20260502-011827.txt"
INVENTORY_KEYS = {"v", "verdict", "stats", "channels", "from_addresses"}


def _write_capture(path: Path, data: bytes, line: int = 40) -> Path:
    path.write_text("".join(data[i : i + line].hex() + "\n" for i in range(0, len(data), line)))
    return path


def _garbage_laced(data: bytes, rate: float, seed: int) -> bytes:
    rng = random.Random(seed)
    out = bytearray()
    for i in range(0, len(data), 64):
        part = data[i : i + 64]
        if rng.random() < rate:
            part = rng.randbytes(rng.randint(1, 32)) + part
        out += part
    return bytes(out)


def _probe_cli(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "jabuka.tools.probe", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# -- live mode against a pty ------------------------------------------------------------------


def test_probe_live_example2_ok(running_replay, probe_out_dir: Path) -> None:
    data = load_capture(EXAMPLE2)
    with running_replay(data, speed=20) as rr:
        report = run_probe(rr.feeder.slave_path, seconds=3, out_dir=probe_out_dir, on_open=rr.start)
        assert rr.done.wait(10)
    assert report.state == "ok", report.hint
    assert report.exit_code == 0
    assert report.hint.startswith("OK: ")
    for ch in ("0x41", "0x49", "0x51"):
        assert ch in report.channels
    inv = json.loads((probe_out_dir / "inventory.json").read_text())
    assert INVENTORY_KEYS <= set(inv)
    assert inv["v"] == 1
    assert inv["verdict"]["state"] == "ok"
    assert inv["device"] == rr.feeder.slave_path
    assert inv["tiocgicount"] is None  # ENOTTY on a pty: degraded, not an error
    assert inv["stats"]["frames_ok"] > 0
    assert inv["stats"]["frames_per_s"] > 0
    hdg = inv["channels"]["0x49"]
    assert hdg["name"] == "Heading"
    assert hdg["count"] > 0
    assert "°M" in hdg["layouts_seen"]
    assert hdg["layout_codes_seen"] == ["0x66"]
    assert hdg["raw_records"] and all(r.startswith("49") for r in hdg["raw_records"])
    assert "navigation.heading" in hdg["paths"]
    assert "0x05" in inv["from_addresses"] and inv["from_addresses"]["0x05"]["count"] > 0
    # capture.log is replayable and holds exactly the bytes received
    cap = probe_out_dir / "capture.log"
    assert report.capture_path == cap
    assert load_capture(cap) == data
    assert report.bytes_received == len(data)

    # --file on the same capture sees the same channel set
    file_report = run_probe(EXAMPLE2, out_dir=probe_out_dir / "file")
    assert file_report.state == "ok"
    assert set(file_report.channels) == set(report.channels)
    assert file_report.capture_path is None


def test_probe_live_inverted_says_swap_wires(running_replay, probe_out_dir: Path) -> None:
    data = load_capture(EXAMPLE2)
    with running_replay(data, speed=20, invert=True) as rr:
        report = run_probe(rr.feeder.slave_path, seconds=3, out_dir=probe_out_dir, on_open=rr.start)
    assert report.state == "no_frames"
    assert report.exit_code == 3
    assert "BYTES BUT NO VALID FRAMES: swap White/Green (A/B)" in report.hint


def test_probe_live_silent(running_replay, probe_out_dir: Path) -> None:
    with running_replay(b"") as rr:
        report = run_probe(rr.feeder.slave_path, seconds=2, out_dir=probe_out_dir)
    assert report.state == "silent"
    assert report.exit_code == 2
    assert report.hint.startswith("NO BYTES")


def test_probe_live_garbage_is_noisy(running_replay, probe_out_dir: Path) -> None:
    data = load_capture(EXAMPLE2)
    with running_replay(data, speed=20, garbage_rate=0.5, rng=random.Random(7)) as rr:
        report = run_probe(rr.feeder.slave_path, seconds=3, out_dir=probe_out_dir, on_open=rr.start)
    assert report.state == "noisy", report.inventory["stats"]
    assert report.exit_code == 4
    assert "Black" in report.hint


def test_probe_opens_read_only(running_replay, probe_out_dir: Path, monkeypatch) -> None:
    seen: list[int] = []
    real_open = probe_mod.open_fastnet

    def spy(path: str):
        ser = real_open(path)
        seen.append(fcntl.fcntl(ser.fileno(), fcntl.F_GETFL) & os.O_ACCMODE)
        return ser

    monkeypatch.setattr(probe_mod, "open_fastnet", spy)
    with running_replay(b"") as rr:
        run_probe(rr.feeder.slave_path, seconds=0.2, out_dir=probe_out_dir)
        assert probe_mod.read_icount(rr.feeder.slave) is None  # pty: ENOTTY -> None
    assert seen == [os.O_RDONLY]


def test_probe_missing_device(tmp_path: Path) -> None:
    report = run_probe(tmp_path / "nope", seconds=1, out_dir=tmp_path / "out", file_mode=False)
    assert report.state == "missing"
    assert report.exit_code == 1
    assert json.loads((tmp_path / "out" / "inventory.json").read_text())["verdict"]["error"]


# -- capture files ---------------------------------------------------------------------------


def test_probe_file_rawfn_keeps_heading_raw_records(probe_out_dir: Path) -> None:
    report = run_probe(RAWFN, out_dir=probe_out_dir)
    assert report.state == "ok"
    hdg = report.channels["0x49"]
    assert "0x66" in hdg["layout_codes_seen"]
    assert None in hdg["layouts_seen"] and "°M" in hdg["layouts_seen"]
    assert "490600bee8e8" in hdg["raw_records"]
    for ch in ("0x6D", "0x84"):
        assert report.channels[ch]["raw_records"]


def test_cli_file_exit_codes(tmp_path: Path) -> None:
    data = load_capture(EXAMPLE2)
    cases = {
        "ok": (EXAMPLE2, 0),
        "inverted": (_write_capture(tmp_path / "inv.txt", bytes(b ^ 0xFF for b in data)), 3),
        "garbage": (_write_capture(tmp_path / "noise.txt", _garbage_laced(data, 0.5, 3)), 4),
        "empty": (_write_capture(tmp_path / "empty.txt", b""), 2),
        "few": (_write_capture(tmp_path / "few.txt", bytes(b ^ 0xFF for b in data[:500])), 5),
    }
    for label, (path, code) in cases.items():
        out = tmp_path / f"out-{label}"
        r = _probe_cli("--file", str(path), "--out", str(out))
        assert r.returncode == code, (label, r.stdout, r.stderr)
        assert (out / "inventory.json").is_file()
    r = _probe_cli("--file", str(EXAMPLE2), "--out", str(tmp_path / "j"), "--json")
    inv = json.loads(r.stdout)
    assert "0x49" in inv["channels"] and "layouts_seen" in inv["channels"]["0x49"]


def test_cli_live_silent_pty_exit_2(tmp_path: Path) -> None:
    with PtyFeeder() as feeder:
        r = _probe_cli("--device", feeder.slave_path, "--seconds", "1", "--out", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NO BYTES" in r.stdout
    assert "raised to 5" in r.stderr  # live windows are at least 5 s


def test_cli_missing_device_exit_1(tmp_path: Path) -> None:
    r = _probe_cli("--device", str(tmp_path / "nope"), "--out", str(tmp_path / "o"))
    assert r.returncode == 1
    assert "DEVICE MISSING" in r.stdout


def test_cli_help_says_stop_the_ingest() -> None:
    r = _probe_cli("--help")
    assert r.returncode == 0
    assert "jabuka-ingest-fastnet" in r.stdout


# -- pty replay fault injection --------------------------------------------------------------


class _Sink:
    def __init__(self) -> None:
        self.out = bytearray()
        self.times: list[tuple[float, int]] = []

    async def awrite(self, b: bytes) -> None:
        self.out += b
        self.times.append((asyncio.get_running_loop().time(), len(b)))


def test_replay_invert() -> None:
    sink = _Sink()
    asyncio.run(replay_bytes(sink, b"\x00\x0f\xff", speed=0, invert=True))  # type: ignore[arg-type]
    assert bytes(sink.out) == b"\xff\xf0\x00"


def test_replay_garbage_is_deterministic_and_keeps_data_order() -> None:
    data = bytes(range(256)) * 4
    a, b = _Sink(), _Sink()
    asyncio.run(replay_bytes(a, data, speed=0, garbage_rate=0.5, rng=random.Random(1)))  # type: ignore[arg-type]
    asyncio.run(replay_bytes(b, data, speed=0, garbage_rate=0.5, rng=random.Random(1)))  # type: ignore[arg-type]
    assert a.out == b.out
    assert len(a.out) > len(data)
    it = iter(a.out)
    assert all(byte in it for byte in data)  # data is a subsequence of the output


def test_replay_silence_window() -> None:
    sink = _Sink()
    data = bytes(64 * 20)
    # 64 B chunks at 2400*1 B/s ~= 27 ms each; silence 0.2 s starting at 0.1 s
    asyncio.run(replay_bytes(sink, data, speed=1.0, silences=[(0.1, 0.2)]))  # type: ignore[arg-type]
    gaps = [t2 - t1 for (t1, _), (t2, _) in zip(sink.times, sink.times[1:], strict=False)]
    assert max(gaps) >= 0.2
    assert bytes(sink.out) == data


def test_replay_cli_lists_fault_flags() -> None:
    text = build_arg_parser().format_help()
    for flag in ("--invert", "--garbage-rate", "--silence", "--unplug-at", "--replug-after"):
        assert flag in text
    args = build_arg_parser().parse_args(["x.txt", "--silence", "1:2", "--silence", "5:0.5"])
    assert args.silence == [(1.0, 2.0), (5.0, 0.5)]
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["x.txt", "--silence", "bad"])
