"""Efficiency (WIND-02): speeds only, never angles (Pitfall 9); separate upwind/downwind factors
with the general factor elsewhere."""

from __future__ import annotations

import pytest

from jabuka.nav.polar import apply_efficiency, default_polar, efficiency_for


def test_efficiency_never_moves_target_angles() -> None:
    raw = default_polar().targets(12.0)
    a = apply_efficiency(raw, 0.8)
    b = apply_efficiency(raw, 1.0)
    assert (a.up_twa, a.down_twa) == (b.up_twa, b.down_twa) == (raw.up_twa, raw.down_twa)
    assert a.up_bsp == pytest.approx(raw.up_bsp * 0.8)
    assert b.down_bsp == pytest.approx(raw.down_bsp)


def test_up_and_down_factors() -> None:
    raw = default_polar().targets(12.0)
    t = apply_efficiency(raw, 0.92, efficiency_up=0.85)
    assert t.up_bsp == pytest.approx(raw.up_bsp * 0.85)
    assert t.down_bsp == pytest.approx(raw.down_bsp * 0.92)
    t = apply_efficiency(raw, 0.92, efficiency_down=0.8)
    assert t.up_bsp == pytest.approx(raw.up_bsp * 0.92)
    assert t.down_bsp == pytest.approx(raw.down_bsp * 0.8)


@pytest.mark.parametrize(
    ("twa", "expected"),
    [(40.0, 0.85), (-40.0, 0.85), (90.0, 0.92), (150.0, 0.8), (-170.0, 0.8), (None, 0.92)],
)
def test_point_of_sail_factor(twa, expected) -> None:
    assert efficiency_for(twa, 0.92, 0.85, 0.8) == expected


def test_point_of_sail_factor_defaults_to_general() -> None:
    assert efficiency_for(40.0, 0.92) == 0.92
    assert efficiency_for(150.0, 0.92, None, None) == 0.92
