"""Interim X35 polar: parsing, interpolation, VMG targets, JSON round trip (WIND-01/02)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jabuka.nav.polar import (
    Polar,
    default_polar,
    load_racepack_polar,
    parse_expedition,
    polar_from_json,
    polar_to_json,
)


@pytest.fixture(scope="module")
def polar() -> Polar:
    return default_polar()


def test_default_polar_targets_at_12_kn(polar: Polar) -> None:
    t = polar.targets(12.0)
    assert t.up_twa == pytest.approx(37.7, abs=0.6)
    assert t.up_bsp == pytest.approx(6.50, abs=0.05)
    assert t.down_twa == pytest.approx(158.9, abs=1.0)
    assert t.down_twa <= 158.9  # never deeper than the polar goes at this TWS
    assert t.down_bsp == pytest.approx(6.77, abs=0.05)
    assert polar.source.startswith("builtin:")


def test_speed_on_grid_clamped_and_zero(polar: Polar) -> None:
    assert polar.speed(12.0, 90.0) == pytest.approx(7.69)
    assert polar.speed(12.0, -90.0) == pytest.approx(7.69)  # port is folded
    assert polar.speed(12.0, 270.0) == pytest.approx(7.69)  # 270 = 90 on the other side
    assert polar.speed(25.0, 90.0) == polar.speed(20.0, 90.0)  # no extrapolation
    assert polar.speed(0.0, 90.0) == 0.0
    assert polar.speed(12.0, 0.0) == 0.0
    assert polar.speed(3.0, 90.0) == pytest.approx(6.10 / 2)  # implicit TWS 0 curve
    # linear across TWS between the 12 and 14 kn curves
    assert polar.speed(13.0, 90.0) == pytest.approx((7.69 + 8.01) / 2)


def test_json_round_trip_gives_identical_speeds(polar: Polar) -> None:
    again = polar_from_json(json.loads(json.dumps(polar_to_json(polar))))
    for tws in range(0, 26):
        for twa in range(0, 181, 5):
            assert again.speed(tws, twa) == polar.speed(tws, twa)


def test_efficiency_never_moves_target_angles(polar: Polar) -> None:
    """Pitfall 9: a uniform efficiency scales speeds only."""
    for tws in (6.0, 9.0, 12.0, 16.0, 20.0):
        t = polar.targets(tws)
        for eff in (0.8, 1.0):
            scaled = Polar(
                "scaled",
                [(s, [(a, b * eff) for a, b in pts]) for s, pts in polar.curves],
            )
            ts = scaled.targets(tws)
            assert (ts.up_twa, ts.down_twa) == (t.up_twa, t.down_twa)
            assert ts.up_bsp == pytest.approx(t.up_bsp * eff)


def test_targets_below_the_lowest_curve_keep_its_angles(polar: Polar) -> None:
    lo, mid = polar.targets(6.0), polar.targets(3.0)
    assert mid.up_twa == lo.up_twa
    assert mid.up_bsp == pytest.approx(lo.up_bsp / 2)


def test_parse_expedition_tabs_spaces_comments() -> None:
    p = parse_expedition("! comment\n\n10\t40 5.0\t90 7.0\n 20  40 6.0  90 8.0 \n", "t")
    assert p.speed(15.0, 90.0) == pytest.approx(7.5)
    assert p.name == "t"


@pytest.mark.parametrize(
    "text",
    [
        "10 40 5.0 90",  # odd pair count
        "10 40 nan",  # non-finite
        "10 40 inf 90 7",
        "10 -40 5.0",  # negative
        "10 40 abc",
        "! only comments\n",
        "10 200 5.0",  # TWA above 180
    ],
)
def test_parse_expedition_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError):
        parse_expedition(text)


def test_load_racepack_polar_prefers_valid_polar_json(tmp_path: Path) -> None:
    assert load_racepack_polar(tmp_path).source.startswith("builtin:")
    assert load_racepack_polar(None).source.startswith("builtin:")
    (tmp_path / "polar.json").write_text("{not json")
    assert load_racepack_polar(tmp_path).source.startswith("builtin:")
    own = parse_expedition("8 40 5.0 90 6.0 150 5.0\n12 40 6.0 90 7.0 160 6.0", "mine")
    (tmp_path / "polar.json").write_text(json.dumps(polar_to_json(own)))
    p = load_racepack_polar(tmp_path)
    assert p.source == "racepack:polar.json"
    assert p.name == "mine"
    assert p.speed(12.0, 90.0) == pytest.approx(7.0)


def test_polar_needs_a_curve_above_0_kn() -> None:
    """IN-04: a polar whose only curve is TWS 0 made targets() raise StopIteration every tick."""
    with pytest.raises(ValueError, match="above 0 kn"):
        Polar("zero", [(0.0, [(40.0, 0.0), (90.0, 0.0)])])
    with pytest.raises(ValueError, match="above 0 kn"):
        polar_from_json({"curves": [[0, [[45, 0], [90, 0]]]]})


def test_racepack_polar_that_breaks_targets_falls_back_to_builtin(
    tmp_path: Path, monkeypatch
) -> None:
    """IN-04: the racepack smoke check runs targets() like the nav tick does; any failure there
    gives the builtin polar instead of a nav crash every second."""
    (tmp_path / "polar.json").write_text('{"curves": [[0, [[45, 0], [90, 0]]]]}')
    assert load_racepack_polar(tmp_path).source.startswith("builtin:")
    own = parse_expedition("8 40 5.0 90 6.0 150 5.0\n12 40 6.0 90 7.0 160 6.0", "mine")
    (tmp_path / "polar.json").write_text(json.dumps(polar_to_json(own)))

    def boom(self, tws_kn):
        raise StopIteration

    monkeypatch.setattr(Polar, "targets", boom)
    assert load_racepack_polar(tmp_path).source.startswith("builtin:")
