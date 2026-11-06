"""Settings model bounds, versioned atomic persistence, the TRUE heading boundary (WIND-03)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from jabuka.nav.settings import Settings, SettingsStore, VersionConflict
from jabuka.nav.wind import HEADING, WindPipeline, heading_true


def test_defaults_match_the_addendum() -> None:
    s = Settings()
    assert s.variation_deg == 4.7
    assert s.heading_display == "M"
    assert s.heading_ref_unknown == "M"
    assert s.true_wind_source == "computed"
    assert s.efficiency == 0.92 and s.eff_up() == 0.92 and s.eff_down() == 0.92
    assert s.use_current is False
    assert (s.zone_lat, s.zone_lon, s.zone_radius_nm) == (43.09153, 15.46054, 3.0)


def test_schema_has_french_labels() -> None:
    props = SettingsStore.schema()["properties"]
    assert props["efficiency"]["label"] == "Efficacité polaire"
    assert props["variation_deg"]["maximum"] == 30.0
    assert all("label" in p for p in props.values())


def test_update_versions_and_persists(tmp_path: Path) -> None:
    st = SettingsStore(tmp_path)
    assert st.version == 0
    out = st.update({"efficiency": 0.85}, base_version=0)
    assert out["version"] == 1 and out["settings"]["efficiency"] == 0.85
    with pytest.raises(VersionConflict) as ei:
        st.update({"efficiency": 0.9}, base_version=0)
    assert ei.value.version == 1
    for bad in ({"efficiency": 2.0}, {"variation_deg": 45}, {"nope": 1}, {"variation_deg": "x"}):
        with pytest.raises(ValidationError):
            st.update(bad, base_version=1)
    assert st.version == 1
    again = SettingsStore(tmp_path)
    assert again.version == 1 and again.settings.efficiency == 0.85


def test_corrupt_settings_fall_back(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text('{"version": 4, "settings": {"efficiency": 9}}')
    st = SettingsStore(tmp_path)
    assert st.settings == Settings()
    assert st.alerts


@pytest.mark.parametrize(
    ("ref", "unknown", "expected"),
    [
        ("M", "M", 104.7),
        ("T", "M", 100.0),
        ("?", "M", 104.7),
        ("?", "T", 100.0),
        (None, "M", 104.7),
    ],
)
def test_heading_true_boundary(ref, unknown, expected) -> None:
    s = Settings(heading_ref_unknown=unknown)
    got = math.degrees(heading_true(math.radians(100.0), ref, s))
    assert got == pytest.approx(expected)


def test_heading_offset_applies_before_variation() -> None:
    s = Settings(heading_offset_deg=-2.0, variation_deg=5.0)
    assert math.degrees(heading_true(math.radians(359.0), "M", s)) == pytest.approx(2.0)


def test_pipeline_live_only_with_all_inputs() -> None:
    p = WindPipeline(Settings())
    rows = {
        "environment.wind.angleApparent": {"value": math.radians(30)},
        "environment.wind.speedApparent": {"value": 8.0},
        "navigation.speedThroughWater": {"value": 3.0},
        HEADING: {"value": math.radians(100), "ref": "T"},
    }
    sol = p.update(rows, 1.0)
    assert sol.source == "LIVE" and sol.ok
    assert sol.twd == sol.twd_lay
    sol = p.update({**rows, HEADING: None}, 2.0)
    assert sol.source == "NONE" and not sol.ok
