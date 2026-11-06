"""L1 replay: a core bus log replayed over UDP at --speed N into a core running a SimClock."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from jabuka.sim.msg_replay import replay_messages

from jabuka.common import messages
from jabuka.common.clock import SimClock, SystemClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
from jabuka.ingest.fastnet_decode import decode_to_values
from jabuka.ingest.fastnet_framing import CountingFramer, chunks_from_capture
from jabuka.ingest.rawlog import iter_log_lines

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fastnet"
EXAMPLE2 = FIX / "example2_fastnet_data.txt"
N_MSGS = 40


def _deltas() -> list[dict]:
    framer = CountingFramer()
    out: list[dict] = []
    t_wall = 1762470000.0
    for chunk in chunks_from_capture(EXAMPLE2):
        for frame in framer.feed(chunk):
            res = decode_to_values(frame)
            if res.values:
                out.append(messages.delta_message("fastnet", res.values, 0.0, t_wall))
                t_wall += 0.25
        if len(out) >= N_MSGS:
            break
    return out[:N_MSGS]


def _fastnet_paths(diag: dict) -> set[str]:
    return {r["path"] for r in diag["values"] if r["src"] == "fastnet"}


def _record_bus_log(data_dir: Path, port: int, wait_until) -> tuple[list[Path], set[str]]:
    ctx = CoreContext.create(SystemClock(), data_dir, udp_port=port)
    deltas = _deltas()
    with TestClient(create_app(ctx)) as client:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for msg in deltas:
                s.sendto(messages.encode(msg), ("127.0.0.1", port))
                time.sleep(0.03)  # recorded t_mono gaps: ~1.2 s session
        wait_until(lambda: ctx.stats["udp_rx"] >= len(deltas), timeout=5)
        paths = _fastnet_paths(client.get("/api/state").json())
    logs = sorted((data_dir / "logs" / "bus").glob("bus-*.log"))
    assert logs
    return logs, paths


def _line_walls(logs: list[Path]) -> list[float]:
    return [float(line.split(" ", 2)[1]) for p in logs for line in iter_log_lines(p)]


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_replay_bus_log_into_sim_core(tmp_path: Path, free_udp_port: int, wait_until) -> None:
    logs, live_paths = _record_bus_log(tmp_path / "live", free_udp_port, wait_until)
    walls = _line_walls(logs)
    assert len(walls) == N_MSGS
    assert walls[-1] - walls[0] > 0.5

    clock = SimClock()
    port2 = _free_udp_port()
    ctx = CoreContext.create(clock, tmp_path / "replayed", udp_port=port2)
    with TestClient(create_app(ctx)) as client:
        assert client.get("/api/state").json()["clock"]["time_valid"] is False
        t0 = time.monotonic()
        sent, skipped = asyncio.run(replay_messages(logs, speed=20, udp=("127.0.0.1", port2)))
        elapsed = time.monotonic() - t0
        assert (sent, skipped) == (N_MSGS, 0)
        assert elapsed < (walls[-1] - walls[0]) / 2  # accelerated, not real time
        wait_until(lambda: ctx.stats["udp_rx"] >= N_MSGS, timeout=5)
        diag = client.get("/api/state").json()

    assert _fastnet_paths(diag) == live_paths
    assert {"navigation.heading", "environment.wind.angleApparent"} <= live_paths
    clk = diag["clock"]
    assert clk["kind"] == "sim" and clk["time_valid"] is True
    # sim time followed the recording: UTC is the last recorded line's t_wall
    assert walls[0] <= clock.wall() <= walls[-1]
    assert abs(clock.wall() - walls[-1]) < 1e-3
    assert abs(clock.monotonic() - (walls[-1] - walls[0])) < 1e-3


def test_replay_skips_garbage_lines(tmp_path: Path) -> None:
    good = messages.encode(messages.delta_message("fastnet", [{"path": "a.b", "value": 1.0}], 0, 0))
    log = tmp_path / "bus-x.log"
    log.write_text(
        "10.000 1762470000.000 " + good.decode() + "\n"
        "garbage\n"
        "11.000 1762470001.000 {not json}\n"
        "12.000 notafloat " + good.decode() + "\n"
        "13.000 1762470003.000 " + good.decode() + "\n"
        '14.000 1762470004.000 {"torn'  # torn last line: never yielded
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(2)
        port = rx.getsockname()[1]
        sent, skipped = asyncio.run(replay_messages([log], speed=100, udp=("127.0.0.1", port)))
        got = [messages.decode(rx.recv(65536)) for _ in range(sent)]
    assert (sent, skipped) == (2, 3)
    assert [m["t_sim"] for m in got] == [1762470000.0, 1762470003.0]


def test_replay_clamps_huge_gaps(tmp_path: Path) -> None:
    good = messages.encode(messages.delta_message("fastnet", [{"path": "a.b", "value": 1.0}], 0, 0))
    log = tmp_path / "bus-x.log"
    log.write_text(
        "10.000 1762470000.000 " + good.decode() + "\n"
        "5000.000 1762475000.000 " + good.decode() + "\n"  # reboot / long gap: not waited for
        "2.000 1762475001.000 " + good.decode() + "\n"  # t_mono went backwards
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        t0 = time.monotonic()
        sent, skipped = asyncio.run(
            replay_messages([log], speed=1, udp=("127.0.0.1", rx.getsockname()[1]))
        )
        assert time.monotonic() - t0 < 2.0
    assert (sent, skipped) == (3, 0)


def test_replay_keeps_existing_t_sim(tmp_path: Path) -> None:
    msg = messages.delta_message("sim", [{"path": "a.b", "value": 1.0}], 0, 0, t_sim=1762000000.5)
    log = tmp_path / "bus-x.log"
    log.write_text("1.000 1762470000.000 " + messages.encode(msg).decode() + "\n")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(2)
        asyncio.run(replay_messages([log], speed=0, udp=("127.0.0.1", rx.getsockname()[1])))
        got = messages.decode(rx.recv(65536))
    assert got is not None and got["t_sim"] == 1762000000.5


def test_cli_help_and_run(tmp_path: Path) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "jabuka.sim.msg_replay", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0
    assert "--speed" in r.stdout and "--udp" in r.stdout and "--loop" in r.stdout
    good = messages.encode(messages.delta_message("fastnet", [{"path": "a.b", "value": 1.0}], 0, 0))
    log = tmp_path / "bus-x.log"
    log.write_text("1.000 1762470000.000 " + good.decode() + "\nnope\n")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        port = rx.getsockname()[1]
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "jabuka.sim.msg_replay",
                str(log),
                "--speed",
                "10",
                "--udp",
                f"127.0.0.1:{port}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert r.returncode == 0, r.stderr
    assert "sent 1" in r.stdout and "skipped 1" in r.stdout
