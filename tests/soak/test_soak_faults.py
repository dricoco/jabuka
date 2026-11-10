"""Fault functions against fake harnesses: the harness findings of the Pi race-36h soak
20261110T153632Z (system scope, report under var/soak/20261110T153632Z-race-36h/).

- f67/f70/f71/f79/f85: after the f65 core restart the router numbered its routes from 1 again
  (course A finished, B selected: the saved route of the older course is rightly not restored),
  but the faults waited for a version above the run-wide maximum (114) and failed although new
  routes were adopted 4-15 s after each fault.
- f33..f84 grib-gap: the full wind cube was restored with the run dir as the guard root, while
  system scope keeps the race pack under /var/lib/jabuka/soak-<ts> (state_root).
- f55 power-pull: the clean pull landed 0.4 s after POST /api/wind/manual, inside the core's
  background durability window (atomicio G-4-R05): the acknowledged change was not on disk yet.
"""

from __future__ import annotations

import json
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from jabuka.soak import faults
from jabuka.soak.scenario import FaultSpec
from jabuka.soak.tablet import TabletClient
from jabuka.tools import soak


def _route(version: int, kind: str = "optimal") -> str:
    coords = [[15.70, 43.60], [15.75, 43.55]]
    feat = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"role": "route", "version": version},
    }
    return json.dumps(
        {
            "type": "route",
            "version": version,
            "kind": kind,
            "geojson": {"type": "FeatureCollection", "features": [feat]},
        }
    )


def _nav(version: int, stay: bool | None = None) -> str:
    route: dict[str, Any] = {"state": "ok", "version": version}
    if stay is not None:
        route["stay"] = {"active": stay}
    return json.dumps({"type": "nav", "route": route, "course_version": 1})


def _adopt(tb: TabletClient, version: int, kind: str = "optimal", stay: bool | None = None) -> None:
    tb._on_text(_route(version, kind))
    tb._on_text(_nav(version, stay))


def _renumbered_tablet() -> TabletClient:
    """Process 1 reached v114, then a core restart renumbered from 1 (no route restored)."""
    tb = TabletClient("ws://127.0.0.1:9/ws")
    for v in (113, 114, 1, 2, 3, 4, 5, 6):
        _adopt(tb, v)
    return tb


class _Sc:
    def budget(self, key: str) -> float:
        return 1.5


class _CoreFake:
    """The parts of the harness the route-wait faults use; `later` adopts a route on the tablet
    a moment after a request, as the core's router would."""

    def __init__(self, tb: TabletClient) -> None:
        self.tablet = tb
        self.sc = _Sc()
        self.speed = 20.0
        self.calls: list[tuple[str, str, Any]] = []

    def sim_now(self) -> float:
        return 66000.0

    def poll_abort(self) -> None:
        pass

    def course_upkeep(self) -> None:
        pass

    def later(self, fn) -> None:
        threading.Timer(0.2, fn).start()

    def http(self, method: str, path: str, body: Any = None, timeout: float = 5.0):
        self.calls.append((method, path, body))
        if (method, path) == ("GET", "/api/course"):
            return 200, {"template": "B", "version": 7}
        if (method, path) == ("POST", "/api/course/select"):
            self.later(lambda: _adopt(self.tablet, 7))
            return 200, {"template": "A", "version": 8}
        if (method, path) == ("POST", "/api/route/stay"):
            if body["active"]:
                _adopt(self.tablet, 7, "stay", stay=True)
                _adopt(self.tablet, 8, "stay", stay=True)
            else:
                self.tablet._on_text(_nav(8, stay=False))
                self.later(lambda: _adopt(self.tablet, 9, "optimal", stay=False))
            return 200, {}
        return 200, {}


def test_last_route_version_follows_a_renumbering_core() -> None:
    tb = _renumbered_tablet()
    assert tb.max_route_version() == 114  # the run-wide maximum (what the faults used)
    assert tb.last_route_version() == 6  # what the tablet shows now
    assert TabletClient("ws://127.0.0.1:9/ws").last_route_version() == 0


def test_course_change_after_a_renumbering_restart_sees_the_new_route() -> None:
    h = _CoreFake(_renumbered_tablet())
    rec = faults.course_change(h, FaultSpec("f67", "course-change", 66000.0))  # type: ignore[arg-type]
    assert rec["ok"] is not False, rec["notes"]
    assert rec["route_version_before"] == 6
    assert rec["route_version"] == 7 and rec["recovery_s"] is not None


def test_stay_toggle_after_a_renumbering_restart_sees_the_optimal_route() -> None:
    h = _CoreFake(_renumbered_tablet())
    spec = FaultSpec("f70", "stay-toggle", 68400.0, dur=2.0)
    rec = faults.stay_toggle(h, spec)  # type: ignore[arg-type]
    assert rec["stay_routes"] == 2
    assert rec["ok"] is not False, rec["notes"]
    assert rec["recovery_s"] is not None


def test_stay_toggle_still_waits_for_a_route_newer_than_the_stay_ones() -> None:
    """Boundary: the last stay route itself (same version, re-adopted) is not "optimal again"."""
    tb = _renumbered_tablet()
    h = _CoreFake(tb)

    def http(method: str, path: str, body: Any = None, timeout: float = 5.0):
        if (method, path) == ("POST", "/api/route/stay") and not body["active"]:
            tb._on_text(_nav(8, stay=False))
            h.later(lambda: _adopt(tb, 8, "optimal", stay=False))  # no new version
            return 200, {}
        return _CoreFake.http(h, method, path, body, timeout)

    h.http = http  # type: ignore[method-assign]
    rec = faults.stay_toggle(h, FaultSpec("f85", "stay-toggle", 84665.0, dur=2.0))  # type: ignore[arg-type]
    assert rec["ok"] is False and "no optimal route" in rec["notes"]


def test_full_wind_is_restored_under_the_state_root(tmp_path: Path) -> None:
    """System scope: run dir (report) and state root (/var/lib/jabuka/soak-<ts>) differ."""
    run_dir = tmp_path / "home" / "var" / "soak" / "20261110T153632Z-race-36h"
    state_root = tmp_path / "var-lib-jabuka" / "soak-20261110T153632Z"
    run_dir.mkdir(parents=True)
    (state_root / "racepack").mkdir(parents=True)
    t0 = 1_794_596_400.0
    h = types.SimpleNamespace(
        run_dir=run_dir,
        state_root=state_root,
        pack_dir=state_root / "racepack",
        start_utc=t0,
        wind_end_utc=lambda: t0 + 6 * 3600.0,
        wind_kw=lambda: {"twd": 161.0, "tws_kn": 12.0},
    )
    soak.Harness.write_full_wind(h)  # type: ignore[arg-type]
    assert (state_root / "racepack" / "wind.npz").is_file()


class _Pulled(Exception):
    pass


class _PullFake:
    """POST /api/wind/manual is acknowledged at once; the file lands on disk `lag_s` later (the
    core's FIFO durability thread). The fake power pull records what was on disk at the cut."""

    def __init__(self, data_dir: Path, lag_s: float) -> None:
        self.data_dir = data_dir
        self.lag_s = lag_s
        self.sc = _Sc()
        self.tablet = types.SimpleNamespace(last_route_version=lambda: 3)
        self.manual: dict | None = None
        self.on_disk_at_pull: Any = "not pulled"
        (data_dir / "wind_manual.json").write_text("{}")  # the previous pull's DELETE
        self.sup = types.SimpleNamespace(power_pull=self._pull)

    def sim_now(self) -> float:
        return 54000.0

    def _pull(self, off) -> None:
        self.on_disk_at_pull = json.loads((self.data_dir / "wind_manual.json").read_text())
        raise _Pulled

    def _durable(self, entry: dict) -> None:
        time.sleep(self.lag_s)
        (self.data_dir / "wind_manual.json").write_text(json.dumps(entry))

    def http(self, method: str, path: str, body: Any = None, timeout: float = 5.0):
        if (method, path) == ("POST", "/api/wind/manual"):
            self.manual = {
                "twd_t_deg": body["twd"],
                "tws_kn": body["tws_kn"],
                "ref_entered": body["ref"],
                "twd_entered": body["twd"],
                "t_set_wall": 1794327708.4,
            }
            threading.Thread(target=self._durable, args=(dict(self.manual),), daemon=True).start()
            return 200, {}
        if (method, path) == ("GET", "/api/wind/manual"):
            return 200, {"manual": self.manual}
        return 200, {"version": 1}


def test_clean_pull_waits_for_the_acknowledged_manual_wind_on_disk(tmp_path: Path) -> None:
    h = _PullFake(tmp_path, lag_s=0.6)
    with pytest.raises(_Pulled):
        faults.power_pull(h, FaultSpec("f55", "power-pull", 54000.0, params={"off_s": 600}))  # type: ignore[arg-type]
    assert h.on_disk_at_pull == h.manual


def test_manual_wind_never_on_disk_is_a_failure_not_a_hang(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(faults, "MANUAL_DURABLE_S", 0.3)
    h = _PullFake(tmp_path, lag_s=1.0)
    rec: dict[str, Any] = {"notes": "", "ok": None}
    assert faults._wait_manual_on_disk(h, rec, None) == 0.0  # nothing posted: nothing to wait for
    assert rec["ok"] is None
    h.http("POST", "/api/wind/manual", {"twd": 150.0, "tws_kn": 11.5, "ref": "T"})
    t = time.monotonic()
    assert faults._wait_manual_on_disk(h, rec, h.manual) is None  # type: ignore[arg-type]
    assert time.monotonic() - t < 0.9
    assert rec["ok"] is False and "not on disk" in rec["notes"]
    assert rec["manual_durable_s"] is None


# -- f41/f72 ws-stall: the legacy websockets keepalive ping on a stalled client -------------------
# Verbatim from proc/core-journal.log:188-205 of the Pi run (f41 window 1994-2024 s after t0).
_WS_STALL_T = 1794327009.287
_LEGACY = "/opt/jabuka/venv/lib/python3.13/site-packages/websockets/legacy/protocol.py"
_KEEPALIVE_TB = "\n".join(
    [
        "ERROR:    keepalive ping failed",
        "Traceback (most recent call last):",
        f'  File "{_LEGACY}", line 1245, in keepalive_ping',
        "    pong_waiter = await self.ping()",
        "                  ^^^^^^^^^^^^^^^^^",
        f'  File "{_LEGACY}", line 849, in ping',
        "    await self.write_frame(True, OP_PING, data)",
        f'  File "{_LEGACY}", line 1196, in write_frame',
        "    await self.drain()",
        f'  File "{_LEGACY}", line 1179, in drain',
        "    await self._drain()",
        f'  File "{_LEGACY}", line 334, in _drain',
        "    await self._drain_helper()",
        f'  File "{_LEGACY}", line 314, in _drain_helper',
        "    assert waiter is None or waiter.cancelled()",
        "           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
        "AssertionError",
    ]
)
_OTHER_ASSERT_TB = """\
Traceback (most recent call last):
  File "/opt/jabuka/venv/lib/python3.13/site-packages/jabuka/core/web.py", line 120, in ws_endpoint
    assert waiter is None or waiter.cancelled()
AssertionError
"""


def _classify(tmp_path: Path, tb: str, kind: str, t0: float, t1: float):
    from jabuka.soak import report as rep
    from jabuka.soak.scenario import load_scenario

    log = tmp_path / "core-journal.log"
    log.write_text("".join(f"{_WS_STALL_T} {line}\n" for line in tb.splitlines()))
    rules = rep.merge_expected(load_scenario("race-36h").expected_tracebacks)
    windows = [{"id": "f41", "kind": kind, "t_wall": t0, "end_wall": t1}]
    return rep.classify_tracebacks(rep.scan_tracebacks([log]), windows, rules, 5.0)


def test_race_36h_expects_the_keepalive_assertion_inside_a_ws_stall(tmp_path: Path) -> None:
    exp, unexp = _classify(
        tmp_path, _KEEPALIVE_TB, "ws-stall", _WS_STALL_T - 20.7, _WS_STALL_T + 9.3
    )
    assert unexp == []
    assert [(e["line"], e["expected_by"]["fault"], e["expected_by"]["kind"]) for e in exp] == [
        (2, "f41", "ws-stall")
    ]
    assert "keepalive" in exp[0]["expected_by"]["why"]


@pytest.mark.parametrize(
    ("tb", "kind", "dt0", "dt1"),
    [
        (_KEEPALIVE_TB, "ws-churn", -20.7, 9.3),  # rule is scoped to ws-stall windows
        (_KEEPALIVE_TB, "kill-core", -20.7, 9.3),
        (_KEEPALIVE_TB, "ws-stall", -80.0, -50.0),  # outside the window (+5 s margin)
        (_KEEPALIVE_TB, "ws-stall", 6.0, 36.0),  # window starts after the traceback
        (_OTHER_ASSERT_TB, "ws-stall", -20.7, 9.3),  # same assert, not the keepalive ping
    ],
)
def test_race_36h_keepalive_rule_expects_nothing_else(
    tmp_path: Path, tb: str, kind: str, dt0: float, dt1: float
) -> None:
    exp, unexp = _classify(tmp_path, tb, kind, _WS_STALL_T + dt0, _WS_STALL_T + dt1)
    assert exp == [] and len(unexp) == 1
