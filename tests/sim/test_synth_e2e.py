"""L2 synthetic boat through the real pipeline.

udp mode: synth -> UDP deltas + embedded FakeGpsd -> core (--clock sim, --gpsd) -> derived JSONL,
with bus-silent, gps-loss, garbage and clock-jump faults at speed 20.
pty mode: synth -> encoded Fastnet frames -> pty -> real jabuka-ingest-fastnet -> UDP -> core.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import socket
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jabuka.common.units import ms_to_kn
from jabuka.core.main import CoreContext, build_arg_parser, build_context
from jabuka.core.web import create_app
from jabuka.sim.synth import SynthBoat, SynthConfig, parse_fault, run_synth, synthetic_bsp

BIN = Path(sys.executable).parent
START = datetime(2026, 11, 13, 19, 0, 0, tzinfo=UTC).timestamp()
WIND = "environment.wind.angleApparent"


def _free_tcp() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _core(data_dir: Path, udp_port: int, *extra: str) -> CoreContext:
    args = build_arg_parser().parse_args(
        ["--data-dir", str(data_dir), "--udp-port", str(udp_port), *extra]
    )
    return build_context(args)


def _run_synth_thread(cfg: SynthConfig) -> tuple[threading.Thread, dict]:
    out: dict = {}

    def target() -> None:
        try:
            out.update(asyncio.run(run_synth(cfg)))
        except BaseException as e:  # surfaced by the test
            out["error"] = repr(e)

    th = threading.Thread(target=target, daemon=True)
    th.start()
    return th, out


def _derived(data_dir: Path) -> list[dict]:
    lines: list[dict] = []
    for p in sorted((data_dir / "logs" / "derived").glob("derived-*.jsonl")):
        lines += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return lines


def _row(line: dict, path: str, src: str) -> dict | None:
    for r in line["values"]:
        if r["path"] == path and r["src"] == src:
            return r
    return None


# -- model unit checks -------------------------------------------------------------------------
def test_parse_fault_and_bsp_model() -> None:
    f = parse_fault("gps-loss@120+30")
    assert (f.kind, f.start, f.dur) == ("gps-loss", 120.0, 30.0)
    assert f.active(120.0) and f.active(149.9) and not f.active(150.0)
    for bad in ("nope@1+2", "gps-loss@1", "gps-loss+3", "garbage@-1+2"):
        try:
            parse_fault(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    assert synthetic_bsp(12.0, 0.0) == 0.0
    prev = 0.0
    for tws in range(0, 40):
        v = synthetic_bsp(float(tws), math.radians(60))
        assert v >= prev and v <= 8.5
        prev = v


def test_boat_heading_from_twa_and_dead_reckoning() -> None:
    boat = SynthBoat(SynthConfig(twd=330.0, twa=45.0, tws=12.0))
    s = boat.state
    assert math.degrees(s.hdg) == pytest.approx(285.0, abs=1e-9)
    assert math.degrees(s.twa) == pytest.approx(45.0, abs=1e-9)
    assert s.awa > 0 and s.awa < s.twa  # apparent wind forward of true, same (starboard) side
    s2 = boat.step(60.0)
    assert s2.t == 60.0
    assert s2.lon < s.lon  # heading 285: westwards


# -- udp mode with faults ----------------------------------------------------------------------
def test_udp_mode_with_faults(tmp_path: Path, free_udp_port: int, caplog) -> None:
    caplog.set_level(logging.WARNING)
    data_dir = tmp_path / "var"
    gport = _free_tcp()
    ctx = _core(data_dir, free_udp_port, "--clock", "sim", "--gpsd", f"127.0.0.1:{gport}")
    cfg = SynthConfig(
        mode="udp",
        speed=20.0,
        duration=70.0,
        udp=("127.0.0.1", free_udp_port),
        gpsd_port=gport,
        start_utc=START,
        wait_gpsd_s=10.0,
        seed=7,
        faults=[
            parse_fault("bus-silent@10+15"),
            parse_fault("gps-loss@30+10"),
            parse_fault("garbage@45+5"),
            parse_fault("clock-jump@55+10"),
        ],
    )
    with TestClient(create_app(ctx)):
        th, out = _run_synth_thread(cfg)
        th.join(timeout=60)
        assert not th.is_alive(), "synth did not finish"
        assert "error" not in out, out.get("error")
        assert ctx.stats["handler_errors"] == 0
    # TestClient exit -> lifespan shutdown -> logs closed (flushed + fsynced)

    lines = _derived(data_dir)
    assert 60 <= len(lines) < 200, len(lines)  # ticks never back-fill after the jump

    by_rel: dict[int, dict] = {}
    for line in lines:
        utc = line["clock"]["utc"]
        if utc is None:
            continue
        rel = datetime.fromisoformat(utc).timestamp() - START
        by_rel.setdefault(round(rel), line)
        # every age is non-negative, including during and after the clock jump
        for r in line["values"]:
            assert r["age_s"] >= 0, (rel, r)
        for h in line["health"].values():
            assert h["age_s"] >= 0

    def wind_stale(rel: int) -> bool:
        r = _row(by_rel[rel], WIND, "fastnet")
        assert r is not None, rel
        return r["stale"]

    for rel in range(2, 10):
        assert not wind_stale(rel), rel
    for rel in range(21, 25):
        assert wind_stale(rel), rel
    for rel in range(29, 51):
        assert not wind_stale(rel), rel

    for rel in range(2, 30):
        r = _row(by_rel[rel], "navigation.position", "gpsd")
        assert r is not None and not r["stale"], rel
    for rel in range(35, 40):
        r = _row(by_rel[rel], "navigation.position", "gpsd")
        assert r is not None and r["stale"], rel
    for rel in range(42, 50):
        assert not _row(by_rel[rel], "navigation.position", "gpsd")["stale"], rel

    for rel in range(10, 44):
        assert by_rel[rel]["core"]["udp_rejected"] == 0, rel
    for rel in range(47, 55):
        assert by_rel[rel]["core"]["udp_rejected"] > 0, rel

    # the clock jump is visible as sim UTC +3600 s, then back on the original timeline
    assert any(3600 + 55 <= rel <= 3600 + 65 for rel in by_rel)
    assert any(66 <= rel <= 70 for rel in by_rel)
    assert by_rel[22]["health"]["fastnet"]["state"] == "silent"

    errors = [
        r for r in caplog.records if r.name.startswith("jabuka") and r.levelno >= logging.ERROR
    ]
    assert errors == [], [r.getMessage() for r in errors]


# -- pty mode through the real ingest ----------------------------------------------------------
def test_pty_mode_through_real_ingest(tmp_path: Path, free_udp_port: int, wait_until) -> None:
    data_dir = tmp_path / "var"
    link = tmp_path / "fastnet-pty"
    ctx = _core(data_dir, free_udp_port)
    cfg = SynthConfig(
        mode="pty",
        speed=1.0,
        duration=4.0,
        link=link,
        gpsd_port=_free_tcp(),
        start_utc=START,
        wait_reader_s=15.0,
        gust=3.0,
    )
    with TestClient(create_app(ctx)) as client:
        th, out = _run_synth_thread(cfg)
        wait_until(lambda: link.is_symlink(), timeout=10)
        proc = subprocess.Popen(
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
        try:
            th.join(timeout=30)
            assert not th.is_alive(), "synth did not finish"
            assert "error" not in out, out.get("error")
            last = out["last"]
            assert last is not None

            def matches():
                rows = {
                    r["path"]: r
                    for r in client.get("/api/state").json()["values"]
                    if r["src"] == "fastnet"
                }
                awa, bsp = rows.get(WIND), rows.get("navigation.speedThroughWater")
                if awa is None or bsp is None:
                    return None
                if abs(math.degrees(awa["value"] - last["awa"])) > 1.0:
                    return None
                if abs(ms_to_kn(bsp["value"]) - ms_to_kn(last["bsp"])) > 0.05:
                    return None
                return rows

            rows = wait_until(matches, timeout=10)
            assert rows["navigation.heading"]["ref"] == "M"
            assert rows["environment.wind.speedTrue"]["unit"] == "m/s"
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)


def test_sim_help_lists_flags_and_fault_kinds() -> None:
    out = subprocess.run(
        [str(BIN / "jabuka-sim"), "--help"], capture_output=True, text=True, check=True
    ).stdout
    for word in ("--mode", "--speed", "--fault", "bus-silent", "gps-loss", "garbage", "clock-jump"):
        assert word in out
