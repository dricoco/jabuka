"""Real race pack end to end (plan 03-06 Task 3, GRIB-01 + ROUT-01): an in-process core on a pack
built on the laptop from today's DWD (and OSM) data routes Course A from Vodice in the real
forkserver worker. The adopted polyline never crosses the pack's own land mask, the route block
is "ok" with a target, and the legs include Plić Sestre; the same with GPS + GRIB only (no
instruments).

Skipped unless JABUKA_REAL_PACK points at the pack (scripts/racepack-dryrun.sh sets it): never in
CI, the data is not committed.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

import numpy as np
import pytest

from jabuka.route.landmask import LandMask

REAL_PACK = os.environ.get("JABUKA_REAL_PACK")
pytestmark = pytest.mark.skipif(
    not REAL_PACK, reason="JABUKA_REAL_PACK not set (laptop dry run: scripts/racepack-dryrun.sh)"
)

VODICE = (43.75, 15.78)  # start/finish (marks.json, provisional)
KN = 1852.0 / 3600.0
ROUTE_WAIT_S = 120.0  # generous real-time bound: the whole remaining course at L0


def _pack() -> Path:
    p = Path(str(REAL_PACK)).resolve()
    assert (p / "wind.npz").is_file(), f"no wind.npz in {p}"
    assert (p / "landmask.npz").is_file(), f"no landmask.npz in {p}"
    return p


def _first_time(pack: Path) -> float:
    with np.load(pack / "wind.npz", allow_pickle=False) as z:
        return float(z["t"][0])


@pytest.mark.parametrize("live", [True, False], ids=["instruments", "grib-only"])
def test_real_pack_routes_course_a_from_vodice(routing_core, live: bool) -> None:
    pack = _pack()
    core = routing_core(racepack_dir=pack, utc=_first_time(pack) + 2 * 3600.0)
    assert core.router.pack_ok, core.router.pack_reason
    lat, lon = VODICE
    core.tick(0.0)  # the clock gate opens on the first tick
    g = core.call(lambda: core.router.grib_wind_at(lat, lon))
    assert g is not None, "the pack's wind does not cover Vodice at the start time"
    twd = math.degrees(g[0]) % 360.0
    tws = g[1] / KN
    hdg = (twd - 45.0) % 360.0  # starboard, close-hauled

    deadline = time.monotonic() + ROUTE_WAIT_S
    nav: dict = {}
    while time.monotonic() < deadline:
        if live:
            core.sail(lat, lon, hdg, twd_deg=twd, tws_kn=tws, bsp_kn=6.0)
        else:
            core.feed_gps(lat, lon, hdg, 6.0)
        nav = core.tick(0.0)
        if (nav.get("route") or {}).get("version", 0) >= 1:
            break
        time.sleep(0.1)
    r = nav.get("route") or {}
    assert r.get("version", 0) >= 1, f"no route within {ROUTE_WAIT_S} s: {r}"
    assert r["state"] == "ok" and r["reason"] is None, r
    assert r["target"] is not None and r["target_tack"] in ("stbd", "port"), r
    assert nav["wind"]["source"] == ("LIVE" if live else "GRIB"), nav["wind"]
    assert r["pack"]["ok"] is True

    msg = core.router.route_message()
    assert msg is not None
    assert "plic-sestre" in [leg["mark_id"] for leg in msg["legs"]], msg["legs"]

    adopted = core.router.route
    mask = LandMask.load(pack / "landmask.npz")
    lats = np.array([p.lat for p in adopted.path])
    lons = np.array([p.lon for p in adopted.path])
    xs, ys = mask.frame.to_xy(lats, lons)
    v0 = 1 if adopted.start_in_margin else 0
    ok, bad = mask.validate_polyline(xs[v0:], ys[v0:])
    assert ok, f"route segment {bad} crosses the pack's land mask"
    print(
        f"\nreal pack ({'instruments' if live else 'GRIB only'}): {len(adopted.path)} points, "
        f"{len(adopted.tacks)} tacks, ETA {r['eta_utc']}, level {r['level']}, "
        f"wind {twd:.0f}°/{tws:.1f} kn at Vodice"
    )
