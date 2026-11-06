"""Local demo (quick 001, python -m jabuka.tools.demo): the whole synthetic stack comes up on a
free port, the core shows LIVE wind and a route in state ok, the page answers for 127.0.0.1,
localhost and a LAN IP literal (Host check, 421 otherwise), and Ctrl-C (SIGINT) stops every child:
no process mentioning the demo's data directory is left. The data directory is only wiped when the
demo created it."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from jabuka.tools import demo

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="pty + /proc: Linux only")

START_TIMEOUT_S = 50.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _procs_mentioning(text: str) -> list[str]:
    """Command lines of live processes (other than this one) containing text."""
    found = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            raw = (d / "cmdline").read_bytes()
            state = (d / "stat").read_text().split(") ", 1)[1][:1]
        except OSError:
            continue
        cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace")
        if text in cmd and state != "Z":
            found.append(f"{d.name}: {cmd}")
    return found


def test_reset_out_refuses_a_foreign_directory(tmp_path: Path) -> None:
    foreign = tmp_path / "precious"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x")
    with pytest.raises(demo.DemoError):
        demo.reset_out(foreign)
    assert (foreign / "keep.txt").is_file()
    mine = tmp_path / "demo"
    demo.reset_out(mine)  # created, with the marker
    (mine / "old.log").write_text("x")
    demo.reset_out(mine)  # wiped again
    assert sorted(p.name for p in mine.iterdir()) == [demo.MARKER]


def test_urls_and_lan_addresses() -> None:
    assert demo.urls(8080, False) == ["http://127.0.0.1:8080/", "http://localhost:8080/"]
    lan = demo.urls(8080, True)
    assert lan[:2] == ["http://127.0.0.1:8080/", "http://localhost:8080/"]
    assert all(not u.startswith("http://127.") for u in lan[2:])


def test_demo_routes_and_stops_cleanly(tmp_path: Path) -> None:
    port = _free_port()
    out = tmp_path / "demo-data"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jabuka.tools.demo",
            "--port",
            str(port),
            "--speed",
            "4",
            "--out",
            str(out),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.extend(proc.stdout), daemon=True)
    reader.start()
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        nav: dict | None = None
        while True:
            assert proc.poll() is None, "demo exited:\n" + "".join(lines)
            try:
                nav = httpx.get(base + "/api/nav", timeout=2.0).json()
            except (httpx.HTTPError, ValueError):
                nav = None
            if (
                nav
                and (nav.get("wind") or {}).get("source") == "LIVE"
                and (nav.get("route") or {}).get("state") == "ok"
            ):
                break
            assert time.monotonic() < deadline, (
                f"no LIVE wind + route ok within {START_TIMEOUT_S:g} s: "
                f"{(nav or {}).get('wind')} {((nav or {}).get('route') or {}).get('state')}\n"
                + "".join(lines)
            )
            time.sleep(0.5)
        # the Host check accepts localhost and IP literals (a phone on the Wi-Fi with --lan)
        for host in (f"localhost:{port}", f"192.168.1.23:{port}"):
            r = httpx.get(base + "/", headers={"Host": host}, timeout=5.0)
            assert r.status_code == 200 and 'id="tab-barre"' in r.text, host
        assert httpx.get(base + "/", headers={"Host": "evil.example.com"}).status_code == 421
        pack = out / "racepack"
        for name in ("race.pmtiles", "seamarks.geojson", "landmask.npz", "wind.npz"):
            assert (pack / name).is_file(), name
        assert (out / demo.MARKER).is_file()
        wait = time.monotonic() + 10
        while f"{base}/" not in "".join(lines) and time.monotonic() < wait:
            time.sleep(0.2)
        assert f"    {base}/" in "".join(lines)  # the URL is printed
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)  # Ctrl-C
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        reader.join(timeout=5)
    text = "".join(lines)
    assert proc.returncode == 0, text
    assert "Tout est arrêté." in text
    deadline = time.monotonic() + 10
    while _procs_mentioning(str(out)) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert _procs_mentioning(str(out)) == []
    assert (out / "logs").is_dir()  # children's logs kept
