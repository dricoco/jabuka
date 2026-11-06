"""ROUT-11 on the real race-area mask: straight lines through islands are rejected at segment
level, open water is clear. Committed fixture (OSM, ODbL): tests/fixtures/route/."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route.landmask import LandMask  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "route" / "landmask_race_25m.npz"


@pytest.fixture(scope="module")
def lm() -> LandMask:
    return LandMask.load(FIXTURE)


def _seg(lm: LandMask, a: tuple[float, float], b: tuple[float, float]) -> bool:
    ax, ay = lm.frame.to_xy(*a)
    bx, by = lm.frame.to_xy(*b)
    return bool(lm.segments_clear(ax, ay, bx, by)[0])


def _pt(lm: LandMask, p: tuple[float, float], raw: bool = False) -> bool:
    fn = lm.raw_points_clear if raw else lm.points_clear
    return bool(fn(*lm.frame.to_xy(*p))[0])


CROSSINGS = {
    "Prvić": ((43.75, 15.78), (43.705, 15.80)),
    "Zlarin": ((43.69, 15.815), (43.69, 15.87)),
    "Tijat": ((43.735, 15.75), (43.705, 15.78)),
}


def test_fixture_metadata(lm: LandMask) -> None:
    assert lm.shape == (5334, 4199)
    assert lm.cell_m == pytest.approx(25.0)
    assert lm.margin_m == 100.0
    assert lm.osm_base.startswith("2026-")


@pytest.mark.parametrize("name", sorted(CROSSINGS))
def test_straight_line_through_island_is_rejected(lm: LandMask, name: str) -> None:
    a, b = CROSSINGS[name]
    # both endpoints are in water: only a segment-level check can catch the crossing
    assert _pt(lm, a, raw=True) and _pt(lm, b, raw=True)
    assert not _seg(lm, a, b)
    # the undilated land raster agrees: the line really crosses the island, not just a margin
    ax, ay = lm.frame.to_xy(*a)
    bx, by = lm.frame.to_xy(*b)
    assert not lm.raw_segments_clear(ax, ay, bx, by)[0]


def test_open_water_control_is_clear(lm: LandMask) -> None:
    assert _seg(lm, (43.60, 15.60), (43.55, 15.65))


def test_known_sea_points(lm: LandMask) -> None:
    assert _pt(lm, (43.75, 15.78))  # Vodice start
    assert _pt(lm, (43.60, 15.60))  # open sea


@pytest.mark.parametrize(
    "name,p",
    [
        ("Jabuka", (43.09153, 15.46054)),
        ("Blitvenica", (43.62508, 15.57476)),
        ("Mulo", (43.5146, 15.91857)),
    ],
)
def test_island_marks_are_land(lm: LandMask, name: str, p: tuple[float, float]) -> None:
    assert not _pt(lm, p, raw=True)


def test_vectorised_segments_and_polyline(lm: LandMask) -> None:
    pts = [CROSSINGS[k] for k in sorted(CROSSINGS)] + [((43.60, 15.60), (43.55, 15.65))]
    ax, ay = lm.frame.to_xy(np.array([p[0][0] for p in pts]), np.array([p[0][1] for p in pts]))
    bx, by = lm.frame.to_xy(np.array([p[1][0] for p in pts]), np.array([p[1][1] for p in pts]))
    assert lm.segments_clear(ax, ay, bx, by).tolist() == [False, False, False, True]


def test_outside_the_grid_is_blocked(lm: LandMask) -> None:
    assert not _pt(lm, (42.5, 15.5))
    assert not _seg(lm, (43.0, 15.1), (43.0, 14.8))


# ------------------------------------------------------------------ Plić Sestre (hazard)
BEACON = (43.684627, 15.811626)  # OSM node 498394251, built-in hand hazard
M_PER_DEG_LAT = 1852.0 * 60


def _east(p: tuple[float, float], metres: float) -> tuple[float, float]:
    return p[0], p[1] + metres / (M_PER_DEG_LAT * np.cos(np.radians(p[0])))


def _north(p: tuple[float, float], metres: float) -> tuple[float, float]:
    return p[0] + metres / M_PER_DEG_LAT, p[1]


def test_plic_sestre_kept_at_a_distance(lm: LandMask) -> None:
    assert not _pt(lm, BEACON) and not _pt(lm, _east(BEACON, 200))
    assert _pt(lm, BEACON, raw=True)  # a shoal, not land
    assert _pt(lm, _east(BEACON, 0.3 * 1852))  # Course A rounding radius (0.3 nm) is clear


def test_segment_near_plic_sestre(lm: LandMask) -> None:
    # north-south segments 1 nm long, passing 100 m and 0.3 nm east of the beacon
    for metres, ok in ((100, False), (0.3 * 1852, True)):
        c = _east(BEACON, metres)
        assert _seg(lm, _north(c, -926), _north(c, 926)) is ok, metres
