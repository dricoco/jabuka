"""CRSE-05: the edited course (marks, overrides, sequence, active mark, finish, sides, pending
advance banner) survives a core restart and a kill -9 during a stream of edits."""

from __future__ import annotations

import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from jabuka.common.clock import SimClock
from jabuka.core.main import CoreContext
from jabuka.nav.course import COURSE_FILE, CourseStore

BIN = Path(sys.executable).parent
CYCLES = 5

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="kill -9 loop: Linux only")


def test_new_core_context_reproduces_the_course(tmp_path: Path) -> None:
    ctx = CoreContext.create(SimClock(), tmp_path)
    cs = ctx.nav.course
    cs.select("B")
    cs.add_mark("Bouée dégagement", 43.68, 15.79, radius_nm=0.1, side="stbd")
    cs.edit_mark("vodice", lat=43.745, lon=15.775)
    cs.set_leg(1, side="stbd", radius_nm=0.4)
    cs.reorder(3, 4)
    cs.next()
    cs.set_finish(4)
    cs.confirm_sides()
    before = cs.to_api()
    again = CoreContext.create(SimClock(), tmp_path).nav.course
    assert again.to_api() == before
    assert again.course.overrides == cs.course.overrides
    assert again.course.next_mark_n == cs.course.next_mark_n
    assert again.alerts == []


def test_pending_advance_banner_survives_a_restart(tmp_path: Path) -> None:
    wall = [1_000_000.0]
    cs = CourseStore(tmp_path, wall=lambda: wall[0])
    cs._advance(100.0, 1, cs.marks["plic-sestre"])  # what the state machine does on rounding
    token = cs.status()["banner"]["token"]
    assert cs.course.active_idx == 2

    wall[0] += 20.0  # restarted 20 s later: 40 s of Annuler left
    again = CourseStore(tmp_path, wall=lambda: wall[0])
    assert again.course.banner is not None and again.course.active_idx == 2
    again.on_tick(None, None, 5.0)
    assert again.status()["banner"]["undo_until_s"] == pytest.approx(45.0)
    again.undo(token, 6.0)
    assert again.course.active_idx == 1

    cs = CourseStore(tmp_path, wall=lambda: wall[0])
    cs._advance(10.0, 1, cs.marks["plic-sestre"])
    wall[0] += 75.0  # restarted after the window: no Annuler any more
    late = CourseStore(tmp_path, wall=lambda: wall[0])
    late.on_tick(None, None, 1.0)
    assert late.status()["banner"] is None
    assert CourseStore(tmp_path).course.banner is None  # and the expiry was persisted


def test_banner_window_without_trusted_utc(tmp_path: Path) -> None:
    """WR-03: the banner window is stamped with trusted (GPS) UTC only. Unsynced (None): no
    stamp, and a restart offers the full window instead of trusting the system clock."""
    cs = CourseStore(tmp_path, wall=lambda: None)
    cs._advance(100.0, 1, cs.marks["plic-sestre"])
    b = cs.course.banner
    assert b is not None and b.at_wall is None and b.until_wall is None
    again = CourseStore(tmp_path, wall=lambda: None)
    again.on_tick(None, None, 5.0)  # never raises
    assert again.status()["banner"]["undo_until_s"] == pytest.approx(65.0)
    # stamped while synced, restarted before the GPS is back: the full window, no crash
    utc = [1_000_000.0]
    cs = CourseStore(tmp_path, wall=lambda: utc[0])
    cs._advance(10.0, 1, cs.marks["plic-sestre"])
    unsynced = CourseStore(tmp_path, wall=lambda: None)
    unsynced.on_tick(None, None, 2.0)
    assert unsynced.status()["banner"]["undo_until_s"] == pytest.approx(62.0)


# -- kill -9 during edits -----------------------------------------------------------------------
def _free(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_core(data_dir: Path) -> tuple[subprocess.Popen, str]:
    port = _free(socket.SOCK_STREAM)
    proc = subprocess.Popen(
        [
            str(BIN / "jabuka-core"),
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(port),
            "--udp-port",
            str(_free(socket.SOCK_DGRAM)),
            "--data-dir",
            str(data_dir),
            "--clock",
            "system",
            "--gpsd",
            "none",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"jabuka-core exited with {proc.returncode}")
        try:
            if httpx.get(base + "/api/course", timeout=0.5).status_code == 200:
                return proc, base
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    proc.kill()
    pytest.fail("jabuka-core did not serve /api/course within 15 s")


def _edit_loop(base: str, stop: threading.Event, acked: list[int]) -> None:
    """PATCH Plić Sestre back and forth as fast as the core answers; record acknowledged
    versions."""
    with httpx.Client(timeout=2.0) as client:
        try:
            v = client.get(base + "/api/course").json()["version"]
        except httpx.HTTPError:
            return
        k = 0
        while not stop.is_set():
            k += 1
            body = {"lat": 43.68 + (k % 50) * 1e-4, "lon": 15.81, "base_version": v}
            try:
                r = client.patch(base + "/api/marks/plic-sestre", json=body)
            except httpx.HTTPError:
                return  # killed
            if r.status_code != 200:
                return
            v = r.json()["version"]
            acked.append(v)


def test_kill9_during_edits_never_loses_the_course(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    last_acked = 0
    for cycle in range(CYCLES):
        proc, base = _start_core(data_dir)
        served = httpx.get(base + "/api/course", timeout=2.0).json()
        assert served["version"] >= last_acked - 1, (cycle, served["version"], last_acked)
        stop = threading.Event()
        acked: list[int] = []
        th = threading.Thread(target=_edit_loop, args=(base, stop, acked), daemon=True)
        th.start()
        deadline = time.monotonic() + 5
        while len(acked) < 10 + 7 * cycle and time.monotonic() < deadline:
            time.sleep(0.01)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        stop.set()
        th.join(timeout=5)
        assert acked, f"cycle {cycle}: no edit acknowledged"
        last_acked = max(last_acked, acked[-1])
        cs = CourseStore(data_dir)
        assert cs.alerts == [], (cycle, cs.alerts)  # course.json or its .bak always loads
        assert cs.version >= last_acked - 1, (cycle, cs.version, last_acked)
        assert (data_dir / COURSE_FILE).exists()
    proc, base = _start_core(data_dir)  # and the core restarts serving the course
    try:
        c = httpx.get(base + "/api/course", timeout=2.0).json()
        assert c["version"] >= last_acked - 1
        assert c["marks"]["plic-sestre"]["moved"] is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)
