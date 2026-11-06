"""E2E: FakeGpsd -> core started with --gpsd -> /api/state GPS rows + health.gps, raw gps log,
and the client surviving a gpsd restart."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BIN = Path(sys.executable).parent

GPS_PATHS = (
    "navigation.position",
    "navigation.courseOverGroundTrue",
    "navigation.speedOverGround",
    "navigation.datetime",
    "gps.mode",
    "gps.satellitesUsed",
    "gps.hdop",
)


def _gps_rows(diag: dict) -> dict[str, dict]:
    return {r["path"]: r for r in diag["values"] if r["src"] == "gpsd"}


def _gps_log_lines(data_dir: Path) -> list[str]:
    out: list[str] = []
    for p in sorted((data_dir / "logs" / "gps").glob("gps-*.log")):
        for line in p.read_text().splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                out.append(parts[2])
    return out


def test_gps_values_and_health_on_diag(
    tmp_data_dir, free_udp_port, fake_gpsd, make_core, core_app, tpv_sky_objs, wait_until
) -> None:
    fg = fake_gpsd()
    ctx = make_core(tmp_data_dir, free_udp_port, gpsd=f"127.0.0.1:{fg.port}")
    with TestClient(core_app(ctx)) as client:
        wait_until(lambda: fg.watching() > 0, timeout=5)
        fg.play(tpv_sky_objs, speed=5, loop=True, retime=True)

        def ready():
            d = client.get("/api/state").json()
            rows = _gps_rows(d)
            if not all(p in rows for p in GPS_PATHS):
                return None
            if rows["gps.mode"]["value"] != 3:
                return None
            return d

        diag = wait_until(ready, timeout=10)
        rows = _gps_rows(diag)
        pos = rows["navigation.position"]["value"]
        assert abs(pos["latitude"] - 43.73) < 0.01 and abs(pos["longitude"] - 15.75) < 0.01
        assert rows["navigation.position"]["unit"] == "deg"
        assert rows["navigation.courseOverGroundTrue"]["unit"] == "rad"
        assert rows["navigation.speedOverGround"]["value"] == 3.0
        assert rows["navigation.datetime"]["value"].endswith("Z")
        for r in rows.values():
            assert r["age_s"] >= 0
        gps = diag["health"]["gps"]
        assert gps["connected"] is True
        assert gps["mode"] == 3
        assert gps["sats_used"] == 8
        assert gps["hdop"] == 0.9
        assert gps["device"] == "/dev/gps"

        # raw-first gps log holds VERSION, DEVICES and TPV lines verbatim (flushed by the tick)
        sent = fg.sent_lines()

        def logged():
            lines = _gps_log_lines(tmp_data_dir)
            classes = {json.loads(x).get("class") for x in lines if x.startswith("{")}
            return lines if {"VERSION", "DEVICES", "TPV"} <= classes else None

        lines = wait_until(logged, timeout=5)
        tpv_sent = [s for s in sent if '"class":"TPV"' in s]
        assert tpv_sent and tpv_sent[0] in lines
        version_sent = [s for s in sent if '"class":"VERSION"' in s]
        assert version_sent[0] in lines


def test_gpsd_restart_disconnect_and_reconnect(
    tmp_data_dir, free_udp_port, free_tcp_port, fake_gpsd, make_core, core_app, wait_until
) -> None:
    fg = fake_gpsd(free_tcp_port)
    ctx = make_core(tmp_data_dir, free_udp_port, gpsd=f"127.0.0.1:{free_tcp_port}")
    with TestClient(core_app(ctx)) as client:

        def connected(flag: bool):
            def pred():
                h = client.get("/api/state").json()["health"].get("gps")
                return h is not None and h.get("connected") is flag

            return pred

        wait_until(connected(True), timeout=5)
        fg.stop_server()
        wait_until(connected(False), timeout=3)
        fg.start()
        wait_until(connected(True), timeout=6)
        h = client.get("/api/state").json()["health"]["gps"]
        assert h["reconnects"] >= 1


def test_core_help_lists_gpsd_and_fake_help() -> None:
    out = subprocess.run(
        [str(BIN / "jabuka-core"), "--help"], capture_output=True, text=True, check=True
    ).stdout
    assert "--gpsd" in out
    out = subprocess.run(
        [str(BIN / "jabuka-fake-gpsd"), "--help"], capture_output=True, text=True, check=True
    ).stdout
    for flag in ("--script", "--nmea", "--speed", "--retime"):
        assert flag in out
