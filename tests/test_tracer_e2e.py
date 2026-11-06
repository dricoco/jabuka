"""Walking-skeleton tracer: capture bytes -> pty -> ReadOnlySerial -> raw log -> framer -> decode ->
UDP -> StateStore -> /api/state, /ws and the page."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from jabuka.common.clock import SystemClock
from jabuka.core.main import CoreContext
from jabuka.core.web import create_app
from jabuka.ingest.fastnet_framing import load_capture
from jabuka.sim.pty_replay import PtyFeeder, replay_bytes

FIX = Path(__file__).parent / "fixtures" / "fastnet"
CAPTURE = FIX / "example2_fastnet_data.txt"
EXPECTED = ("environment.wind.angleApparent", "navigation.speedThroughWater", "navigation.heading")
BIN = Path(sys.executable).parent


def _rows(diag: dict) -> dict[str, dict]:
    return {r["path"]: r for r in diag.get("values", []) if r.get("src") == "fastnet"}


def _has_expected(diag: dict) -> bool:
    rows = _rows(diag)
    return all(p in rows for p in EXPECTED)


def _check_rows(diag: dict) -> None:
    rows = _rows(diag)
    awa = rows["environment.wind.angleApparent"]
    assert awa["unit"] == "rad"
    assert awa["src"] == "fastnet"
    assert rows["navigation.speedThroughWater"]["unit"] == "m/s"
    hdg = rows["navigation.heading"]
    assert hdg["ref"] == "M"
    assert hdg["ch"] == "0x49"
    for r in diag["values"]:
        assert r["age_s"] >= 0
        for key in ("unit", "src", "ref", "age_s", "stale"):
            assert key in r


def _raw_log_bytes(data_dir: Path) -> bytes:
    out = bytearray()
    for p in sorted((data_dir / "logs" / "raw").glob("fastnet-*.log")):
        for line in p.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3:
                out += bytes.fromhex(parts[2])
    return bytes(out)


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_in_process_core(
    tmp_data_dir: Path, free_udp_port: int, wait_until, process_has_open
) -> None:
    data = load_capture(CAPTURE)
    ctx = CoreContext.create(SystemClock(), tmp_data_dir, udp_port=free_udp_port)
    app = create_app(ctx)
    with TestClient(app) as client, PtyFeeder() as feeder:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "jabuka.ingest.fastnet_main",
                "--device",
                feeder.slave_path,
                "--udp",
                f"127.0.0.1:{free_udp_port}",
                "--data-dir",
                str(tmp_data_dir),
            ]
        )
        try:
            wait_until(lambda: process_has_open(proc.pid, feeder.slave_path))
            time.sleep(0.5)  # let the ingest finish termios setup + input flush
            asyncio.run(replay_bytes(feeder, data, speed=50))

            diag = wait_until(
                lambda: (d := client.get("/api/state").json()) and _has_expected(d) and d,
                timeout=10,
            )
            _check_rows(diag)
            assert diag["type"] == "diag"
            assert diag["clock"]["routing_time_gate"] == "blocked"
            assert diag["clock"]["time_valid"] is False
            assert diag["core"]["udp_rx"] > 0
            assert diag["health"]["fastnet"]["frames_ok"] > 0

            with client.websocket_connect("/ws") as ws:
                msg = ws.receive_json()
            assert msg["type"] == "diag"
            assert _has_expected(msg)
            _check_rows(msg)
            assert msg["clock"]["routing_time_gate"] == "blocked"

            # raw-first: everything written to the pty is in the raw log, byte for byte
            wait_until(lambda: len(_raw_log_bytes(tmp_data_dir)) >= len(data), timeout=10)
            assert _raw_log_bytes(tmp_data_dir) == data

            page = client.get("/")
            assert page.status_code == 200
            assert "Jabuka diagnostics" in page.text
            assert client.get("/diag.js").status_code == 200
        finally:
            _terminate(proc)


def test_full_stack_subprocesses(
    tmp_path: Path, free_udp_port: int, free_tcp_port: int, wait_until
) -> None:
    data_dir = tmp_path / "var"
    link = tmp_path / "fastnet-pty"
    procs: list[subprocess.Popen] = []
    try:
        procs.append(
            subprocess.Popen(
                [
                    str(BIN / "jabuka-replay"),
                    str(CAPTURE),
                    "--link",
                    str(link),
                    "--loop",
                    "--speed",
                    "5",
                ],
                stdout=subprocess.PIPE,
            )
        )
        wait_until(lambda: link.is_symlink(), timeout=10)
        procs.append(
            subprocess.Popen(
                [
                    str(BIN / "jabuka-core"),
                    "--data-dir",
                    str(data_dir),
                    "--http-host",
                    "127.0.0.1",
                    "--http-port",
                    str(free_tcp_port),
                    "--udp-port",
                    str(free_udp_port),
                ]
            )
        )
        procs.append(
            subprocess.Popen(
                [
                    str(BIN / "jabuka-ingest-fastnet"),
                    "--device",
                    str(link),
                    "--udp",
                    f"127.0.0.1:{free_udp_port}",
                    "--data-dir",
                    str(data_dir),
                ]
            )
        )

        def poll() -> dict | None:
            try:
                r = httpx.get(f"http://127.0.0.1:{free_tcp_port}/api/state", timeout=1.0)
            except httpx.HTTPError:
                return None
            if r.status_code != 200:
                return None
            d = r.json()
            return d if _has_expected(d) else None

        diag = wait_until(poll, timeout=15)
        _check_rows(diag)
        page = httpx.get(f"http://127.0.0.1:{free_tcp_port}/", timeout=2.0)
        assert "Jabuka diagnostics" in page.text
        for p in procs:
            assert p.poll() is None, "a pipeline process died"
    finally:
        for p in reversed(procs):
            _terminate(p)
