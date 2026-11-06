"""gpsd JSON client: pure parsers (parse_line, tpv_to_values, sky_to_values) and the asyncio client
against FakeGpsd (raw-first log, hostile lines counted, health)."""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from jabuka.ingest.gpsd_client import (
    MAX_LINE,
    GpsdClient,
    parse_line,
    sky_to_values,
    tpv_to_values,
)
from jabuka.sim.fake_gpsd import FakeGpsd

TPV3 = {
    "class": "TPV",
    "mode": 3,
    "time": "2026-11-13T19:00:00.000Z",
    "lat": 43.75,
    "lon": 15.77,
    "track": 225.0,
    "speed": 3.0,
}


def _by_path(values: list[dict]) -> dict[str, dict]:
    return {v["path"]: v for v in values}


# -- parse_line --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        b"not json at all",
        b"[1, 2, 3]",
        b'"just a string"',
        b'{"mode": 3}',
        b'{"class": 5}',
        b'{"class":"TPV","lat":NaN}',
        b"\xff\xfe\x00garbage",
        b"",
        b'{"class":"TPV","pad":"' + b"x" * MAX_LINE + b'"}',
    ],
)
def test_parse_line_rejects(line: bytes) -> None:
    assert parse_line(line) is None


def test_parse_line_accepts_object_with_class() -> None:
    obj = parse_line(json.dumps(TPV3).encode() + b"\r\n")
    assert obj is not None and obj["class"] == "TPV" and obj["mode"] == 3


# -- tpv_to_values -----------------------------------------------------------------------------
def test_tpv_to_values_mode3() -> None:
    vals = _by_path(tpv_to_values(TPV3))
    pos = vals["navigation.position"]
    assert pos["value"] == {"latitude": 43.75, "longitude": 15.77}
    assert pos["unit"] == "deg"
    cog = vals["navigation.courseOverGroundTrue"]
    assert cog["value"] == pytest.approx(math.radians(225.0), abs=1e-12)
    assert cog["unit"] == "rad"
    sog = vals["navigation.speedOverGround"]
    assert sog["value"] == 3.0  # gpsd speed is already m/s
    assert sog["unit"] == "m/s"
    assert vals["navigation.datetime"]["value"] == "2026-11-13T19:00:00.000Z"
    assert vals["gps.mode"]["value"] == 3


def test_tpv_to_values_no_fix_only_mode() -> None:
    vals = tpv_to_values({"class": "TPV", "mode": 1, "time": "2026-11-13T19:00:00.000Z"})
    assert [v["path"] for v in vals] == ["gps.mode"]
    assert vals[0]["value"] == 1


def test_tpv_to_values_eph_and_bad_numbers() -> None:
    tpv = dict(TPV3, eph=4.2, lat=True, track="north", speed=-0.0)
    vals = _by_path(tpv_to_values(tpv))
    assert "navigation.position" not in vals  # bool is not a latitude
    assert "navigation.courseOverGroundTrue" not in vals
    assert vals["gps.eph"]["value"] == 4.2 and vals["gps.eph"]["unit"] == "m"
    out_of_range = _by_path(tpv_to_values(dict(TPV3, lat=91.0)))
    assert "navigation.position" not in out_of_range


# -- sky_to_values -----------------------------------------------------------------------------
def test_sky_uses_usat_nsat() -> None:
    vals = _by_path(sky_to_values({"class": "SKY", "uSat": 8, "nSat": 11, "hdop": 0.9}))
    assert vals["gps.satellitesUsed"]["value"] == 8
    assert vals["gps.satellitesVisible"]["value"] == 11
    assert vals["gps.hdop"]["value"] == 0.9


def test_sky_counts_used_satellites_when_no_usat() -> None:
    sats = [{"PRN": n, "used": n % 2 == 0} for n in range(1, 8)]
    vals = _by_path(sky_to_values({"class": "SKY", "satellites": sats}))
    assert vals["gps.satellitesUsed"]["value"] == 3
    assert vals["gps.satellitesVisible"]["value"] == 7
    assert "gps.hdop" not in vals


# -- client against FakeGpsd -------------------------------------------------------------------
class ListLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, text: str) -> None:
        self.lines.append(text)


async def _wait(pred, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not pred():
        if loop.time() > deadline:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.02)


async def test_client_raw_first_and_rejects_hostile_lines() -> None:
    fake = FakeGpsd("127.0.0.1", 0)
    port = await fake.start()
    got: list[dict] = []
    health: list[dict] = []
    raw = ListLog()
    client = GpsdClient(
        "127.0.0.1",
        port,
        lambda obj, t: got.append(obj),
        raw,
        health=lambda h: health.append(dict(h)),
    )
    task = asyncio.create_task(client.run())
    try:
        await _wait(lambda: fake.watching > 0)
        await _wait(lambda: client.health["device"] == "/dev/gps")
        for line in (b"not json", b"[1,2]", b'{"no":"class"}', b"x" * (MAX_LINE + 500)):
            fake.push_raw(line)
        fake.push(TPV3)
        fake.push({"class": "SKY", "uSat": 7, "nSat": 9, "hdop": 1.1})
        await _wait(lambda: any(o.get("class") == "SKY" for o in got))
        classes = [o["class"] for o in got]
        assert "TPV" in classes and "SKY" in classes
        assert client.health["rejected_lines"] == 4
        assert client.health["connected"] is True
        assert client.health["mode"] == 3
        assert client.health["sats_used"] == 7
        assert client.health["sats_visible"] == 9
        assert client.health["hdop"] == 1.1
        assert client.health["tpv_rx"] == 1 and client.health["sky_rx"] == 1
        # raw-first: VERSION, DEVICES, WATCH and every hostile line are in the raw log
        assert json.loads(raw.lines[0])["class"] == "VERSION"
        assert any('"DEVICES"' in line for line in raw.lines)
        assert "not json" in raw.lines
        assert "[1,2]" in raw.lines
        assert json.dumps(TPV3, separators=(",", ":")) in raw.lines
        assert len(raw.lines) >= 9
        assert health and health[-1]["connected"] is True
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.close()


async def test_client_reconnects_after_server_restart() -> None:
    fake = FakeGpsd("127.0.0.1", 0)
    port = await fake.start()
    raw = ListLog()
    client = GpsdClient(
        "127.0.0.1", port, lambda o, t: None, raw, health=lambda h: None, backoff_min=0.1
    )
    task = asyncio.create_task(client.run())
    try:
        await _wait(lambda: client.health["connected"] is True)
        await fake.close()
        await _wait(lambda: client.health["connected"] is False)
        fake = FakeGpsd("127.0.0.1", port)
        await fake.start()
        await _wait(lambda: client.health["connected"] is True)
        assert client.health["reconnects"] >= 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.close()


def test_fake_gpsd_script_accepts_jsonl_and_raw_log(tmp_path) -> None:
    from jabuka.sim.fake_gpsd import load_script

    p = tmp_path / "gps.log"
    p.write_text(
        json.dumps(TPV3)
        + "\n"
        + '12.000 1762470000.000 {"class":"SKY","uSat":5}\n'
        + "garbage line\n"
        + '13.000 1762470001.000 {"class":"TPV","mode":2,"time":"2026-11-13T19:00:01.000Z"}\n'
        + '14.000 1762470002.000 {"class":"TP'  # torn last line
    )
    objs = load_script(p)
    assert [o["class"] for o in objs] == ["TPV", "SKY", "TPV"]


async def test_fake_gpsd_play_retime_paces_and_stamps_now() -> None:
    fake = FakeGpsd("127.0.0.1", 0)
    port = await fake.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b'?WATCH={"enable":true,"json":true};\n')
    await writer.drain()
    try:
        objs = [
            {"class": "TPV", "mode": 3, "time": "2019-01-01T00:00:00.000Z"},
            {"class": "TPV", "mode": 3, "time": "2019-01-01T00:00:01.000Z"},
        ]
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await fake.play(objs, speed=4.0, retime=True)
        assert 0.2 <= loop.time() - t0 < 1.0  # 1 s of GPS time at speed 4
        got = []
        while len([o for o in got if o["class"] == "TPV"]) < 2:
            got.append(json.loads(await asyncio.wait_for(reader.readline(), 2)))
        tpvs = [o for o in got if o["class"] == "TPV"]
        assert all(not t["time"].startswith("2019") for t in tpvs)
    finally:
        writer.close()
        await fake.close()


async def test_client_never_raises_when_handler_fails() -> None:
    fake = FakeGpsd("127.0.0.1", 0)
    port = await fake.start()

    def boom(obj: dict, t: float) -> None:
        raise RuntimeError("handler bug")

    client = GpsdClient("127.0.0.1", port, boom, ListLog(), health=lambda h: None)
    task = asyncio.create_task(client.run())
    try:
        await _wait(lambda: fake.watching > 0)
        fake.push(TPV3)
        fake.push(TPV3)
        await _wait(lambda: client.health["handler_errors"] >= 2)
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.close()
