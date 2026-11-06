"""Closed loop (CONTEXT §Simulation, CRSE-03, NAV-01): a jabuka-core on --clock sim and a
synthetic X35 steering to the core's own targets (jabuka-sim --follow). Starting 1.5 nm downwind
of Plić Sestre in 12 kn from 161 deg, the boat beats, tacks at the layline, rounds the mark and the
course advances to Jabuka on its own, with the banner on every tablet."""

from __future__ import annotations

import asyncio
import json
import math
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from jabuka.nav import geo
from jabuka.sim.synth import FollowHelm, SynthConfig, run_synth

BIN = Path(sys.executable).parent
PLIC = (43.684627, 15.811626)
START_UTC = datetime(2026, 11, 13, 19, 0, 0, tzinfo=UTC).timestamp()
SPEED = 60.0
MAX_SIM_S = 2400.0
REAL_TIMEOUT_S = 90.0

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="subprocess core: Linux only")


def _free(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_follow_helm_tacks_once_per_trigger() -> None:
    """Unit check of the helmsman: a stale message after a tack never tacks back."""
    from jabuka.sim.synth import SynthBoat

    helm = FollowHelm("http://127.0.0.1:9", 45.0)
    state = SynthBoat(SynthConfig(twd=161.0, twa=45.0)).state
    nav = {
        "type": "nav",
        "wind": {"twd_t": 161.0},
        "helm": {"primary": "twa_up", "target": 40.0},
        "layline": {"state": "normal", "tack": "stbd", "countdown_s": 30.0},
        "mark": {"btw_t": 170.0, "dtw_nm": 1.2},
    }
    hdg, f = helm.command(nav, state)
    assert hdg == pytest.approx(121.0) and f == 1.0 and helm.tacks == 0
    due = {**nav, "layline": {"state": "normal", "tack": "stbd", "countdown_s": 0.0}}
    hdg, f = helm.command(due, state)
    assert hdg == pytest.approx(201.0) and f == 0.5 and helm.tacks == 1
    hdg, _ = helm.command(due, state)  # the same (lagging) message again: no second tack
    assert hdg == pytest.approx(201.0) and helm.tacks == 1
    # a mark just passed (close, behind): hold the heading
    behind = {**nav, "mark": {"btw_t": 20.0, "dtw_nm": 0.05}}
    hdg, _ = helm.command(behind, state)
    assert hdg == pytest.approx(math.degrees(state.hdg))
    with pytest.raises(ValueError):
        FollowHelm("ftp://x", 45.0)


def test_closed_loop_beats_tacks_rounds_and_advances(tmp_path: Path) -> None:
    http_port, udp_port, gpsd_port = (
        _free(socket.SOCK_STREAM),
        _free(socket.SOCK_DGRAM),
        _free(socket.SOCK_STREAM),
    )
    data_dir = tmp_path / "data"
    core = subprocess.Popen(
        [
            str(BIN / "jabuka-core"),
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(http_port),
            "--udp-port",
            str(udp_port),
            "--data-dir",
            str(data_dir),
            "--clock",
            "sim",
            "--gpsd",
            f"127.0.0.1:{gpsd_port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{http_port}"
    stop = threading.Event()
    out: dict = {}
    th: threading.Thread | None = None
    t_real0 = time.monotonic()
    try:
        deadline = time.monotonic() + 15
        while True:
            assert core.poll() is None, f"jabuka-core exited with {core.returncode}"
            try:
                if httpx.get(base + "/api/course", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "core did not start"
            time.sleep(0.05)
        assert httpx.get(base + "/api/course").json()["active_idx"] == 1  # Course A, Plić

        start = geo.offset(*PLIC, math.radians(341.0), 1.5)
        cfg = SynthConfig(
            mode="udp",
            speed=SPEED,
            duration=MAX_SIM_S,
            twd=161.0,
            tws=12.0,
            twa=45.0,
            start=start,
            udp=("127.0.0.1", udp_port),
            gpsd_port=gpsd_port,
            start_utc=START_UTC,
            wait_gpsd_s=15.0,
            follow=base,
        )

        def target() -> None:
            try:
                out.update(asyncio.run(run_synth(cfg, stop=stop.is_set)))
            except BaseException as e:  # surfaced below
                out["error"] = repr(e)

        th = threading.Thread(target=target, daemon=True)
        th.start()

        samples: list[dict] = []
        banners: list[dict] = []
        advanced_at: float | None = None
        with httpx.Client(timeout=2.0) as client:
            while time.monotonic() - t_real0 < REAL_TIMEOUT_S and th.is_alive():
                nav = client.get(base + "/api/nav").json()
                lay = nav.get("layline") or {}
                samples.append(
                    {
                        "t": nav["t_mono"],
                        "tack": lay.get("tack"),
                        "state": lay.get("state"),
                        "countdown": lay.get("countdown_s"),
                        "idx": nav["course"]["active_idx"],
                    }
                )
                if nav["course"]["banner"] is not None:
                    banners.append({**nav["course"]["banner"], "t": nav["t_mono"]})
                if nav["course"]["active_idx"] == 2 and banners:
                    advanced_at = nav["t_mono"]
                    break
                time.sleep(0.03)
        stop.set()
        th.join(timeout=15)
        assert not th.is_alive(), "synth did not stop"
        assert "error" not in out, out.get("error")

        assert advanced_at is not None, (
            f"never advanced to Jabuka; last samples {samples[-5:]}, tacks {out.get('tacks')}"
        )
        course = httpx.get(base + "/api/course").json()
        assert course["active_idx"] == 2
        assert course["seq"][2]["mark_id"] == "jabuka"
        first_t = next(s["t"] for s in samples if s["tack"] is not None)
        assert advanced_at - first_t <= MAX_SIM_S
        print(
            f"closed loop: {out['tacks']} tacks, Jabuka active after {advanced_at - first_t:.0f}"
            f" sim s, {time.monotonic() - t_real0:.1f} s real, {len(samples)} nav samples"
        )
        assert out["tacks"] >= 1, out
        assert banners[0]["text"] == "Marque suivante : Jabuka — Annuler"
        assert banners[0]["undo_until_s"] > banners[0]["t"]

        # the countdown decreases on each straight tack segment
        segments: list[list[dict]] = []
        for s in samples:
            if s["countdown"] is None or s["state"] != "normal":
                continue
            if segments and segments[-1][-1]["tack"] == s["tack"]:
                segments[-1].append(s)
            else:
                segments.append([s])
        long = [seg for seg in segments if len(seg) >= 5]
        assert long, f"no countdown observed: {samples[:10]}"
        for seg in long:
            cds = [s["countdown"] for s in seg]
            assert cds[-1] < cds[0], cds
            assert all(b <= a + 2 for a, b in zip(cds, cds[1:], strict=False)), cds
        # a tack was observed in the nav messages (starboard -> port)
        tacks_seen = [s["tack"] for s in samples if s["tack"]]
        assert "stbd" in tacks_seen and "port" in tacks_seen

        # the advance is in the events log
        lines = []
        for p in sorted((data_dir / "logs" / "events").glob("*.jsonl")):
            lines += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
        adv = [e for e in lines if e.get("type") == "course_advance"]
        assert adv and adv[0]["to_idx"] == 2 and adv[0]["next_mark_id"] == "jabuka"
        assert time.monotonic() - t_real0 < 120
    finally:
        stop.set()
        if th is not None:
            th.join(timeout=10)
        if core.poll() is None:
            core.terminate()
            try:
                core.wait(timeout=10)
            except subprocess.TimeoutExpired:
                core.kill()
                core.wait(timeout=5)
