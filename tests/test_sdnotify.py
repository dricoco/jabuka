"""sd_notify without libsystemd, and both entrypoints speaking READY/WATCHDOG/STOPPING."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from jabuka.common import sdnotify
from jabuka.sim.pty_replay import PtyFeeder


@pytest.fixture
def notify_sock(tmp_path: Path):
    path = tmp_path / "notify.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(str(path))
    s.settimeout(0.2)
    yield s, str(path)
    s.close()


def _recv_all(s: socket.socket, until: float) -> list[str]:
    out = []
    while time.monotonic() < until:
        try:
            out.append(s.recv(4096).decode())
        except TimeoutError:
            continue
    return out


def _collect(s: socket.socket, pred, timeout: float) -> list[str]:
    got: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            got.append(s.recv(4096).decode())
        except TimeoutError:
            pass
        if pred(got):
            return got
    raise AssertionError(f"notify messages not seen within {timeout}s: {got}")


def test_notify_noop_without_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sdnotify.notify("READY=1") is False


def test_notify_filesystem_socket(notify_sock, monkeypatch: pytest.MonkeyPatch) -> None:
    s, path = notify_sock
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    assert sdnotify.notify("READY=1") is True
    assert s.recv(4096) == b"READY=1"


def test_notify_abstract_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    name = f"jabuka-test-{uuid.uuid4().hex}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.bind("\0" + name)
        s.settimeout(1.0)
        monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
        assert sdnotify.notify("WATCHDOG=1") is True
        assert s.recv(4096) == b"WATCHDOG=1"


def test_notify_unreachable_socket_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "nobody-listens.sock"))
    assert sdnotify.notify("READY=1") is False


def test_watchdog_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert sdnotify.watchdog_interval() is None
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    assert sdnotify.watchdog_interval() == 15.0
    monkeypatch.setenv("WATCHDOG_USEC", "garbage")
    assert sdnotify.watchdog_interval() is None
    monkeypatch.setenv("WATCHDOG_USEC", "0")
    assert sdnotify.watchdog_interval() is None


def _check_lifecycle(proc: subprocess.Popen, s: socket.socket, on_ready=None) -> None:
    try:
        got = _collect(s, lambda g: "READY=1" in g, timeout=15)
        t_ready = time.monotonic()
        if on_ready is not None:
            on_ready()
        got += _collect(
            s, lambda g: sum(m == "WATCHDOG=1" for m in g) >= 2, timeout=3.0
        )  # WATCHDOG_USEC=2 s -> ping every 1 s
        assert time.monotonic() - t_ready <= 3.0
        assert got.index("READY=1") < len(got)
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=5)
        tail = _recv_all(s, time.monotonic() + 0.3)
        assert "STOPPING=1" in got + tail
        assert rc == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def _env(path: str) -> dict:
    env = dict(os.environ)
    env["NOTIFY_SOCKET"] = path
    env["WATCHDOG_USEC"] = "2000000"
    return env


def test_ingest_entrypoint_notify_and_sigterm(
    notify_sock, tmp_data_dir: Path, free_udp_port: int
) -> None:
    s, path = notify_sock
    with PtyFeeder() as feeder:
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
            ],
            env=_env(path),
        )
        frame = bytes.fromhex("ff010a01f54192f9dd420a01ec082cea")
        _check_lifecycle(proc, s, on_ready=lambda: feeder.write(frame))
    raw = list((tmp_data_dir / "logs" / "raw").glob("fastnet-*.log"))
    assert raw, "raw log flushed and closed on SIGTERM"
    assert raw[0].read_text().endswith("\n")


def test_core_entrypoint_notify_and_sigterm(
    notify_sock, tmp_data_dir: Path, free_udp_port: int, free_tcp_port: int
) -> None:
    s, path = notify_sock
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jabuka.core.main",
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(free_tcp_port),
            "--udp-port",
            str(free_udp_port),
            "--data-dir",
            str(tmp_data_dir),
        ],
        env=_env(path),
    )
    _check_lifecycle(proc, s)
