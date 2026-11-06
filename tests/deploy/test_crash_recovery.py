"""REL-01 on the laptop: kill -9 of ingest and core mid-stream never corrupts, truncates or
overwrites a log, restarts serve live values again, and atomic JSON always loads a whole version.

Only plan-01 CLI flags and log formats are used (01-02/01-03 changes are additive)."""

from __future__ import annotations

import json
import os
import random
import re
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

import httpx
import pytest

from jabuka.common.atomicio import load_json_with_bak
from jabuka.tools.logcheck import check_dir

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "fastnet"
CAPTURE = FIX / "example2_fastnet_data.txt"
AWA = "environment.wind.angleApparent"
CYCLES = 3
RESTART_DEADLINE_S = 10.0
RAW_NAME = re.compile(r"^fastnet-(\d{8}T\d{2})Z-([0-9a-z]{8})-(\d{3})\.log$")

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="ptys + /proc: Linux only")


def _spawn(*args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _kill9(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill9(proc)


def _reset_pty_termios(link: Path) -> None:
    """pty limitation, not a device one (RESEARCH Pitfall 3): a pty silently drops PARENB. With
    glibc >= 2.42 (laptop: 2.43, where termios.B28800 exists) a pty already at 28800 then makes
    pyserial's next tcsetattr(... PARENB ...) fail with EINVAL, so a restarted ingest could not
    reopen the SAME pty. A real UART keeps PARENB. Put the pty back to its fresh 38400 state, as a
    newly created pty would be, before restarting the ingest. See 01-04-SUMMARY "Deferred"."""
    fd = os.open(link, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        cbaud = termios.CBAUD | (termios.CBAUD << 16)  # CBAUD and CIBAUD (IBSHIFT 16)
        attrs[2] = (attrs[2] & ~cbaud) | termios.B38400
        attrs[4] = attrs[5] = termios.B38400
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    finally:
        os.close(fd)


def _snapshot(logs: Path) -> dict[Path, tuple[int, int]]:
    out = {}
    for p in logs.rglob("*"):
        if p.is_file():
            st = p.stat()
            out[p] = (st.st_size, st.st_ino)
    return out


def _raw_files(logs: Path) -> list[str]:
    return sorted(p.name for p in (logs / "raw").glob("fastnet-*.log"))


def _awa_served(port: int) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/state", timeout=1.0)
    except httpx.HTTPError:
        return False
    if r.status_code != 200:
        return False
    return any(v.get("path") == AWA and v.get("src") == "fastnet" for v in r.json()["values"])


def _assert_nothing_shrank_or_replaced(before: dict, after: dict) -> None:
    for path, (size, ino) in before.items():
        assert path in after, f"{path.name} disappeared"
        new_size, new_ino = after[path]
        assert new_ino == ino, f"{path.name} was replaced (inode {ino} -> {new_ino})"
        assert new_size >= size, f"{path.name} shrank ({size} -> {new_size})"


def test_kill9_ingest_and_core_mid_stream(
    tmp_path: Path, free_udp_port: int, free_tcp_port: int, wait_until
) -> None:
    data_dir = tmp_path / "var"
    logs = data_dir / "logs"
    link = tmp_path / "fastnet-pty"
    core_cmd = (
        "jabuka.core.main",
        "--data-dir",
        str(data_dir),
        "--http-host",
        "127.0.0.1",
        "--http-port",
        str(free_tcp_port),
        "--udp-port",
        str(free_udp_port),
    )
    ingest_cmd = (
        "jabuka.ingest.fastnet_main",
        "--device",
        str(link),
        "--udp",
        f"127.0.0.1:{free_udp_port}",
        "--data-dir",
        str(data_dir),
    )
    replay = _spawn("jabuka.sim.pty_replay", str(CAPTURE), "--link", str(link), "--loop")
    core = ingest = None
    ingest_starts = 0
    try:
        wait_until(link.is_symlink, timeout=10)
        core = _spawn(*core_cmd)
        ingest = _spawn(*ingest_cmd)
        ingest_starts += 1
        wait_until(lambda: _awa_served(free_tcp_port), timeout=20)
        wait_until(lambda: _raw_files(logs), timeout=5)

        for cycle in range(1, CYCLES + 1):
            time.sleep(0.5 + 0.3 * cycle)  # let the logs grow mid-stream
            raw_before = _raw_files(logs)
            _kill9(ingest)
            _kill9(core)
            assert ingest.returncode == -signal.SIGKILL
            assert core.returncode == -signal.SIGKILL
            after_kill = _snapshot(logs)

            # straight after the "power pull": only torn tails, never corruption
            report = check_dir(logs)
            assert report.ok, [(f.path, f.errors) for f in report.files if not f.ok]

            _reset_pty_termios(link)
            t0 = time.monotonic()
            core = _spawn(*core_cmd)
            ingest = _spawn(*ingest_cmd)
            ingest_starts += 1
            wait_until(lambda: _awa_served(free_tcp_port), timeout=RESTART_DEADLINE_S)
            assert time.monotonic() - t0 <= RESTART_DEADLINE_S + 1.0, f"cycle {cycle} too slow"

            # the restarted ingest writes a NEW raw file: same boot id, next sequence number
            def new_raw(before: list[str] = raw_before) -> list[str]:
                return [n for n in _raw_files(logs) if n not in before]

            new = wait_until(new_raw, timeout=5)
            assert new  # (two only if the UTC hour rolled over during this cycle)
            prev = RAW_NAME.match(raw_before[-1])
            cur = RAW_NAME.match(new[0])
            assert prev and cur, (raw_before[-1], new[0])
            assert cur.group(2) == prev.group(2)  # boot8
            if cur.group(1) == prev.group(1):  # same UTC hour: seq increments
                assert int(cur.group(3)) == int(prev.group(3)) + 1

            _assert_nothing_shrank_or_replaced(after_kill, _snapshot(logs))
    finally:
        for proc in (ingest, core, replay):
            if proc is not None:
                _stop(proc)

    proc = subprocess.run(
        [sys.executable, "-m", "jabuka.tools.logcheck", str(logs)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(_raw_files(logs)) >= ingest_starts == CYCLES + 1
    # every raw file holds real bytes from the bus (no empty file from a restart)
    assert all((logs / "raw" / n).stat().st_size > 0 for n in _raw_files(logs))


# -- atomic JSON torture ---------------------------------------------------------------------

WRITER = r"""
import sys
from jabuka.common.atomicio import atomic_write_json, load_json_with_bak
path = sys.argv[1]
cur = load_json_with_bak(path, {"counter": -1})["counter"]
while True:
    cur += 1
    atomic_write_json(path, {"counter": cur, "pad": "x" * 4096, "check": cur * 7})
    sys.stdout.write(f"{cur}\n")
    sys.stdout.flush()
"""


def _complete(obj: object) -> bool:
    return (
        isinstance(obj, dict)
        and set(obj) == {"counter", "pad", "check"}
        and obj["pad"] == "x" * 4096
        and obj["check"] == obj["counter"] * 7
    )


def test_atomic_json_survives_random_sigkill(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    rng = random.Random(20261112)
    last_known = -1
    total_writes = 0
    for i in range(20):
        proc = subprocess.Popen(
            [sys.executable, "-c", WRITER, str(path)],
            stdout=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        time.sleep(rng.uniform(0.08, 0.35))
        proc.send_signal(signal.SIGKILL)
        out, _ = proc.communicate(timeout=10)
        written = [int(x) for x in out.split()]
        if written:
            assert written[0] == last_known + 1, (i, written[:3], last_known)
            last_known = written[-1]
            total_writes += len(written)

        if last_known < 0:
            continue  # killed before the very first write ever completed
        # the main file is never torn (rename is atomic) ...
        main = json.loads(path.read_text())
        assert _complete(main), main
        # ... and holds the last completed write, or the one in flight that won the rename
        assert main["counter"] in (last_known, last_known + 1), (main["counter"], last_known)
        loaded = load_json_with_bak(path, None)
        assert _complete(loaded) and loaded["counter"] == main["counter"]
        bak = path.with_name("state.json.bak")
        if bak.exists():
            prev = json.loads(bak.read_text())
            assert _complete(prev)
            # main-1 normally; == main when killed between the .bak link and the main rename
            assert prev["counter"] in (main["counter"] - 1, main["counter"])
        last_known = main["counter"]

    assert total_writes >= 20, "the writer barely ran: kills came too early"
    assert check_dir(tmp_path).ok
