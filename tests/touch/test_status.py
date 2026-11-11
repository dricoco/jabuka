"""Status at a glance: parsers, the ten tiles from API fixtures, and the never-failing collector."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from jabuka_touch import config, status
from jabuka_touch.actions import CmdResult, FakeRunner
from jabuka_touch.selftest import ManualClock

HEALTHY_STATE = {
    "clock": {"kind": "gps", "time_valid": True, "routing_time_gate": "ok", "utc": "x"},
    "health": {
        "fastnet": {
            "device": "ok",
            "state": "ok",
            "hint": "",
            "frames_per_s": 41.6,
            "alive": True,
            "age_s": 0.2,
        },
        "gps": {"connected": True, "mode": 3, "sats_used": 9, "server": "127.0.0.1:2947"},
        "router": {
            "pack_ok": True,
            "pack_reason": None,
            "version": 12,
            "coverage": {"alerts": [], "warnings": []},
        },
        "racepack": {},
    },
    "core": {"disk": {}, "uptime_s": 3600},
    "values": [],
}
HEALTHY_NAV = {
    "wind": {"source": "LIVE", "stale": False, "tws_kn": 12.3},
    "route": {
        "state": "ok",
        "reason": None,
        "version": 12,
        "age_s": 185.0,
        "computed_utc": "x",
        "pack": {"ok": True, "model": "icon-eu", "run": "2026-11-12T06:00Z", "alerts": []},
    },
    "utc": "2026-11-12T08:00:00Z",
}
DEGRADED_STATE = {
    "clock": {"kind": "gps", "time_valid": False},
    "health": {
        "fastnet": {"device": "ok", "state": "silent", "hint": "bus muet", "alive": False},
        "gps": {"connected": True, "mode": 3, "sats_used": 5, "server": "127.0.0.1:2947"},
        "router": {"pack_ok": True, "pack_reason": None},
    },
}
DEGRADED_NAV = {
    "wind": {"source": "GRIB", "stale": False, "tws_kn": 10.0},
    "route": {
        "state": "blocked_clock",
        "reason": "horloge GPS pas encore valide",
        "version": 3,
        "age_s": None,
        "pack": {
            "ok": True,
            "model": "icon-eu",
            "run": "2026-11-12T00:00Z",
            "alerts": ["vent : fin de couverture avant l'arrivée"],
        },
    },
}

THROTTLED_OK = "throttled=0x0\n"
IW_AP = "Interface wlan0\n\tifindex 3\n\tssid jabuka\n\ttype AP\n\tchannel 6\n"
IW_PHONE = "Interface wlan0\n\tssid Noway_nomap\n\ttype managed\n"
STATIONS = (
    "Station aa:bb:cc:dd:ee:01 (on wlan0)\n\tinactive time:\t10 ms\n"
    "Station aa:bb:cc:dd:ee:02 (on wlan0)\n\tinactive time:\t20 ms\n"
)
CHRONY_OK = "47505300,GPS,1,1731400000.0,0.000001,0.0,0.0,0.0,0.0,0.0,0.0,0.0,16.0,Normal\n"
CHRONY_NOK = "00000000,,0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,Not synchronised\n"
PRERACE_LAST = (
    "prerace : 2026-11-12T07:41:03Z\n"
    "résultat : MÉTÉO INCOMPLÈTE\n"
    "code : 3\n"
    "vent : icon-eu run 2026-11-12T00:00Z\n"
    "vagues : ?\n"
    "Wi-Fi : partage du téléphone puis retour au point d'accès\n"
    "--- coverage.txt (fin) ---\n"
    "(pas de coverage.txt)\n"
)


def test_parse_throttled() -> None:
    assert status.parse_throttled(THROTTLED_OK).level == "ok"
    it = status.parse_throttled("throttled=0x50005")
    assert it.level == "bad" and it.short == "sous-tension !"
    it = status.parse_throttled("throttled=0x50000")
    assert it.level == "warn" and it.short == "sous-tension passée"
    assert status.parse_throttled("vcgencmd: not found").level == "unknown"
    assert status.parse_throttled("").level == "unknown"


def test_parse_iw() -> None:
    assert status.parse_iw_info(IW_AP) == {"mode": "ap", "ssid": "jabuka"}
    assert status.parse_iw_info(IW_PHONE) == {"mode": "phone", "ssid": "Noway_nomap"}
    assert status.parse_iw_info("")["mode"] == "none"
    assert status.parse_station_dump(STATIONS) == 2
    assert status.parse_station_dump("") == 0
    assert status.wifi_item({"mode": "ap", "ssid": "jabuka"}, 2).short == "AP · 2"
    assert status.wifi_item({"mode": "phone", "ssid": "X"}, 0).level == "warn"
    assert status.wifi_item({"mode": "none"}, 0).level == "bad"


def test_parse_chrony() -> None:
    assert status.parse_chrony_tracking(CHRONY_OK) == {
        "synced": True,
        "ref": "GPS",
        "leap": "Normal",
    }
    assert status.parse_chrony_tracking(CHRONY_NOK)["synced"] is False
    assert status.parse_chrony_tracking("garbage")["synced"] is None


def test_parse_prerace_last() -> None:
    got = status.parse_prerace_last(PRERACE_LAST)
    assert got == {
        "running": False,
        "date": "2026-11-12T07:41:03Z",
        "result": "MÉTÉO INCOMPLÈTE",
        "code": 3,
    }
    assert status.parse_prerace_last("en cours : journalctl -fu jabuka-prerace\n" + PRERACE_LAST)[
        "running"
    ]
    assert status.parse_prerace_last("")["result"] is None


def test_api_items_healthy() -> None:
    items = status.api_items(HEALTHY_STATE, HEALTHY_NAV, {"ref": "GPS", "leap": "Normal"})
    assert {k: i.level for k, i in items.items()} == dict.fromkeys(status.API_KEYS, "ok")
    assert items["gps"].short == "3D 9 sat"
    assert items["route"].short == "v12 · 3 min"
    assert items["pack"].short == "icon-eu 12/06Z"
    assert items["bus"].short == "ok 42 tr/s"
    assert items["wind"].short == "LIVE 12 kn"


def test_api_items_degraded() -> None:
    items = status.api_items(DEGRADED_STATE, DEGRADED_NAV, None)
    assert items["bus"].level == "warn" and items["bus"].short == "muet"
    assert items["gps"].level == "warn" and items["gps"].short == "horloge en attente"
    assert items["wind"].level == "warn"
    assert items["route"].level == "bad" and "horloge GPS" in items["route"].detail
    assert items["pack"].level == "warn" and "fin de couverture" in items["pack"].detail


@pytest.mark.parametrize(
    ("fastnet", "level"),
    [
        ({"state": "missing", "alive": False}, "bad"),
        ({"state": "busy", "alive": False}, "bad"),
        ({"state": "ok", "alive": False}, "bad"),
        ({"state": "noisy", "alive": True}, "warn"),
        ({"state": "few_bytes"}, "warn"),
        ({"state": "no_frames"}, "warn"),
        (None, "bad"),
    ],
)
def test_bus_levels(fastnet, level) -> None:
    st = {"health": {"fastnet": fastnet}} if fastnet is not None else {"health": {}}
    assert status.bus_item(st).level == level


@pytest.mark.parametrize(
    ("gps", "valid", "level"),
    [
        ({"connected": False, "mode": 3}, True, "bad"),
        ({"connected": True, "mode": 1}, True, "bad"),
        ({"connected": True, "mode": 2, "sats_used": 4}, True, "ok"),
        ({"connected": True, "mode": 3, "sats_used": 7}, False, "warn"),
    ],
)
def test_gps_levels(gps, valid, level) -> None:
    st = {"clock": {"time_valid": valid}, "health": {"gps": gps}}
    assert status.gps_item(st, None).level == level


@pytest.mark.parametrize(
    ("wind", "level"),
    [
        ({"source": "LIVE_BG"}, "ok"),
        ({"source": "LIVE", "stale": True}, "warn"),
        ({"source": "MANUEL"}, "warn"),
        ({"source": "NONE"}, "bad"),
        (None, "bad"),
    ],
)
def test_wind_levels(wind, level) -> None:
    assert status.wind_item({"wind": wind}).level == level


@pytest.mark.parametrize(
    ("state", "level"),
    [
        ("computing", "warn"),
        ("outdated", "warn"),
        ("no_course", "warn"),
        ("disabled", "warn"),
        ("failed", "bad"),
        ("no_pack", "bad"),
        ("no_position", "bad"),
        ("blocked_clock", "bad"),
    ],
)
def test_route_levels(state, level) -> None:
    assert status.route_item({"route": {"state": state, "reason": "r"}}).level == level


def test_pack_invalid_is_red() -> None:
    nav = {"route": {"pack": {"ok": False, "alerts": []}}}
    st = {"health": {"router": {"pack_reason": "wind.npz absent"}}}
    it = status.pack_item(nav, st)
    assert it.level == "bad" and "wind.npz absent" in it.detail


def test_core_down_five_red() -> None:
    items = status.api_items(None, None, None)
    assert all(i.level == "bad" and i.short == "cœur muet" for i in items.values())


def test_temp_and_disk() -> None:
    assert status.temp_item("69999").level == "ok"
    assert status.temp_item("70000").level == "warn"
    assert status.temp_item("80000").level == "bad"

    class St:
        f_frsize = 4096
        f_blocks = 1000
        f_bavail = 0

    for avail, level in ((300, "ok"), (150, "warn"), (50, "bad")):
        st = St()
        st.f_bavail = avail
        assert status.disk_item(st, "/d").level == level
    st = St()
    st.f_blocks, st.f_bavail = 4_000_000, 2_734_000
    assert status.disk_item(st, "/d").short == "11,2 Go libres"


def _paths(tmp_path: Path, demo: bool = False) -> config.Paths:
    (tmp_path / "temp").write_text("52000\n")
    (tmp_path / "prerace-last.txt").write_text(PRERACE_LAST)
    flag = tmp_path / "zz-jabuka-touch-demo.conf"
    if demo:
        flag.write_text("[Service]\n")
    return config.Paths(
        config=tmp_path / "touch.json",
        thermal=tmp_path / "temp",
        data_dir=tmp_path,
        prerace_last=tmp_path / "prerace-last.txt",
        current_last=tmp_path / "current-last.txt",
        current_npz=tmp_path / "racepack" / "current.npz",
        demo_flag=flag,
    )


def _healthy_runner() -> FakeRunner:
    r = FakeRunner()
    r.set(("systemctl", "is-active", "jabuka-core.service"), CmdResult(0, "active\n" * 3))
    r.set(("systemctl", "is-active", "jabuka-prerace.service"), CmdResult(3, "inactive\n"))
    r.set(("vcgencmd",), CmdResult(0, THROTTLED_OK))
    r.set(("iw", "dev", "wlan0", "info"), CmdResult(0, IW_AP))
    r.set(("iw", "dev", "wlan0", "station"), CmdResult(0, STATIONS))
    r.set(("chronyc",), CmdResult(0, CHRONY_OK))
    r.set(("journalctl",), CmdResult(0, "ligne 1\nligne 2\n"))
    return r


def _fetch(path: str):
    return {"/api/state": HEALTHY_STATE, "/api/nav": HEALTHY_NAV}.get(path)


def test_collector_healthy_ten_items(tmp_path: Path) -> None:
    c = status.Collector(_healthy_runner(), fetch=_fetch, paths=_paths(tmp_path))
    snap = c.collect_once()
    assert [i.key for i in snap.items] == list(status.KEYS)
    assert all(i.level == "ok" for i in snap.items), [(i.key, i.level) for i in snap.items]
    assert snap.item("wifi").short == "AP · 2"
    assert snap.extra["prerace_last"]["code"] == 3
    assert snap.demo is False and snap.prerace_running is False
    v = snap.version
    assert c.collect_once().version == v  # unchanged content -> same version


def test_collector_degraded_services(tmp_path: Path) -> None:
    r = _healthy_runner()
    r.set(
        ("systemctl", "is-active", "jabuka-core.service"),
        CmdResult(3, "active\nfailed\nactive\n"),
    )
    r.set(("systemctl", "is-active", "jabuka-prerace.service"), CmdResult(0, "active\n"))
    c = status.Collector(r, fetch=_fetch, paths=_paths(tmp_path, demo=True))
    snap = c.collect_once()
    it = snap.item("services")
    assert it.level == "bad" and "jabuka-ingest-fastnet" in it.short
    assert snap.demo is True and snap.prerace_running is True


def test_collector_never_raises(tmp_path: Path) -> None:
    r = FakeRunner(default=CmdResult(None, timed_out=True))
    r.set(("vcgencmd",), RuntimeError("boom"))
    r.set(("iw",), CmdResult(None, error="iw introuvable"))
    paths = config.Paths(
        thermal=tmp_path / "absent",
        data_dir=tmp_path / "absent",
        prerace_last=tmp_path / "absent",
        current_last=tmp_path / "absent",
        current_npz=tmp_path / "absent",
        demo_flag=tmp_path / "absent",
    )

    def bad_statvfs(p):
        raise OSError("nope")

    def bad_fetch(path):
        raise RuntimeError("down")

    c = status.Collector(r, fetch=bad_fetch, paths=paths, statvfs=bad_statvfs)
    c.set_extra({"journal_prerace", "wifi_status"})
    snap = c.collect_once()
    assert len(snap.items) == 10
    assert {i.key: i.level for i in snap.items if i.key in status.API_KEYS} == dict.fromkeys(
        status.API_KEYS, "bad"
    )
    assert snap.item("power").level == "unknown" and snap.item("disk").level == "unknown"
    assert snap.extra["journal_prerace"] == ("(délai dépassé)",)


def test_extra_queries_only_while_requested(tmp_path: Path) -> None:
    clock = ManualClock(0.0)
    r = _healthy_runner()
    c = status.Collector(r, fetch=_fetch, paths=_paths(tmp_path), clock=clock)
    c.collect_once()
    assert not any(call[0] in ("journalctl", "/usr/local/sbin/prerace") for call in r.calls)
    c.set_extra({"journal_prerace"})
    clock.advance(1.0)
    snap = c.collect_once(force_sys=False)
    assert snap.extra["journal_prerace"] == ("ligne 1", "ligne 2")
    assert [
        "journalctl",
        "-u",
        "jabuka-prerace.service",
        "-u",
        "jabuka-current.service",
        "-n",
        "10",
        "--no-pager",
        "-o",
        "cat",
    ] in r.calls
    n = len(r.calls)
    clock.advance(1.0)
    c.collect_once(force_sys=False)
    assert len(r.calls) == n  # every 3 s only (API only in between)
    c.set_extra(set())
    clock.advance(5.0)
    snap = c.collect_once(force_sys=False)
    assert "journal_prerace" not in snap.extra
    assert all(t <= 2.0 for t in r.timeouts)


def test_real_fetch_down_returns_none() -> None:
    fetch = status.make_fetch("http://127.0.0.1:9", timeout=0.5)
    assert fetch("/api/state") is None


def test_statvfs_real_dir(tmp_path: Path) -> None:
    it = status.disk_item(os.statvfs(tmp_path), str(tmp_path))
    assert it.short.endswith("Go libres")
