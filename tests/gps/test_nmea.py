"""NMEA (dev-only GPS path): checksum validation and RMC/GGA -> gpsd-shaped TPV/SKY."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jabuka.ingest.nmea import NmeaToGpsd, parse_sentence

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "gps"
BIN = Path(sys.executable).parent

# Checksums below were computed by a script (XOR of the bytes between "$" and "*").
GGA = "$GPGGA,190000.00,4343.8000,N,01545.0000,E,1,08,0.9,42.1,M,40.0,M,,*5B"
RMC_A = "$GPRMC,190000.00,A,4343.8000,N,01545.0000,E,5.83,225.0,131126,4.6,E,A*0F"
RMC_V = "$GPRMC,190000.00,V,,,,,,,131126,,,N*73"
GNRMC_A = "$GNRMC,190000.00,A,4343.8000,N,01545.0000,E,5.83,225.0,131126,4.6,E,A*11"


def test_parse_sentence_valid_and_any_talker() -> None:
    s = parse_sentence(RMC_A)
    assert s is not None and s["type"] == "RMC" and s["talker"] == "GP"
    g = parse_sentence(GNRMC_A + "\r\n")
    assert g is not None and g["talker"] == "GN" and g["type"] == "RMC"


@pytest.mark.parametrize(
    "line",
    [
        RMC_A[:-2] + "00",  # wrong checksum
        RMC_A.replace("*0F", ""),  # missing checksum
        "GPRMC,190000.00,A*0F",  # no "$"
        "$GPRMC,190000.00,A,4343.8000*ZZ",  # non-hex checksum
        "",
        "$\xff\xfe*00",
    ],
)
def test_parse_sentence_rejects(line: str) -> None:
    assert parse_sentence(line) is None


def test_rmc_a_with_gga_fix_is_mode3_tpv() -> None:
    conv = NmeaToGpsd()
    sky = conv.feed(GGA)
    assert sky and sky[0]["class"] == "SKY"
    assert sky[0]["uSat"] == 8 and sky[0]["hdop"] == 0.9
    out = conv.feed(RMC_A)
    assert len(out) == 1
    tpv = out[0]
    assert tpv["class"] == "TPV"
    assert tpv["mode"] == 3
    assert tpv["time"] == "2026-11-13T19:00:00.000Z"
    assert tpv["lat"] == pytest.approx(43.73, abs=1e-9)
    assert tpv["lon"] == pytest.approx(15.75, abs=1e-9)
    assert tpv["speed"] == pytest.approx(5.83 * 0.514444, abs=1e-5)  # kn -> m/s
    assert tpv["track"] == 225.0


def test_rmc_a_without_gga_is_2d() -> None:
    out = NmeaToGpsd().feed(RMC_A)
    assert out[0]["mode"] == 2


def test_rmc_v_is_no_fix_without_time() -> None:
    out = NmeaToGpsd().feed(RMC_V)
    assert out == [{"class": "TPV", "device": "nmea", "mode": 1}]


def test_bad_checksum_feeds_nothing() -> None:
    assert NmeaToGpsd().feed(RMC_A[:-2] + "00") == []


def test_sample_file_yields_six_mode3_fixes() -> None:
    conv = NmeaToGpsd()
    objs = [o for line in (FIX / "sample.nmea").read_text().splitlines() for o in conv.feed(line)]
    tpvs = [o for o in objs if o["class"] == "TPV"]
    assert len(tpvs) == 6
    assert all(t["mode"] == 3 for t in tpvs)
    assert tpvs[-1]["time"] == "2026-11-13T19:00:05.000Z"


def test_fake_gpsd_cli_serves_nmea(free_tcp_port: int) -> None:
    proc = subprocess.Popen(
        [
            str(BIN / "jabuka-fake-gpsd"),
            "--port",
            str(free_tcp_port),
            "--nmea",
            str(FIX / "sample.nmea"),
            "--speed",
            "20",
            "--loop",
        ],
        stdout=subprocess.PIPE,
    )

    async def client() -> list[dict]:
        for _ in range(100):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", free_tcp_port)
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            raise AssertionError("fake gpsd not listening")
        writer.write(b'?WATCH={"enable":true,"json":true};\n')
        await writer.drain()
        got: list[dict] = []
        while sum(1 for o in got if o["class"] == "TPV") < 2:
            line = await asyncio.wait_for(reader.readline(), 5)
            assert line, "server closed"
            got.append(json.loads(line))
        writer.close()
        return got

    try:
        objs = asyncio.run(client())
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    assert objs[0]["class"] == "VERSION"
    assert any(o["class"] == "DEVICES" for o in objs)
    tpvs = [o for o in objs if o["class"] == "TPV"]
    assert tpvs[0]["mode"] == 3 and "time" in tpvs[0]


def test_iso_time_never_rounds_into_a_four_digit_fraction() -> None:
    """IN-06: 59.9996 s used to produce ":59.1000Z", read back as 59.1 s."""
    from datetime import datetime

    from jabuka.ingest.nmea import _iso_time

    out = _iso_time("131126", "185959.9996")
    assert out == "2026-11-13T18:59:59.999Z"
    assert datetime.fromisoformat(out).second == 59
    assert _iso_time("131126", "185959.5") == "2026-11-13T18:59:59.500Z"
