"""Heavy-weather polar reduction (quick 261107-1ow): a per-TWS factor ramping from
heavy_wind_start_kn to heavy_wind_full_kn, applied on the polar curves once (derate_polar) and
shared by the helm and the router; the efficiency multiplies on top."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from jabuka.common.clock import SimClock
from jabuka.common.conventions import apparent_from_true
from jabuka.common.units import kn_to_ms
from jabuka.core.nav_service import NavService
from jabuka.core.state import StateStore
from jabuka.nav import geo
from jabuka.nav.polar import default_polar, derate_polar, heavy_wind_factor
from jabuka.nav.settings import Settings, SettingsStore

R = math.radians
START, FULL, RED = 18.0, 25.0, 0.05


@pytest.fixture(scope="module")
def raw():
    return default_polar()


@pytest.fixture(scope="module")
def derated(raw):
    return derate_polar(raw, START, FULL, RED)


def _steps(lo: float, hi: float, step: float) -> list[float]:
    return [lo + k * step for k in range(int(round((hi - lo) / step)) + 1)]


# -- factor (S-02) --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tws", "expected"),
    [(0.0, 1.0), (12.0, 1.0), (18.0, 1.0), (21.5, 0.975), (25.0, 0.95), (30.0, 0.95), (40.0, 0.95)],
)
def test_factor_ramp(tws, expected) -> None:
    assert heavy_wind_factor(tws, START, FULL, RED) == pytest.approx(expected, abs=1e-12)


# -- knots and curves (S-04) ----------------------------------------------------------------------
def test_derated_curves_keep_their_points_and_gain_two_knots(raw, derated) -> None:
    assert [t for t, _ in raw.curves] == [6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 20.0]
    assert [t for t, _ in derated.curves] == [6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0]
    d = dict(derated.curves)
    for tws, pts in raw.curves:
        assert [a for a, _ in d[tws]] == [a for a, _ in pts], tws
    # the 18 kn knot sits on the union of the 16 and 20 kn curves' angles (planner deviation)
    union = sorted({a for t in (16.0, 20.0) for a, _ in dict(raw.curves)[t]} | {180.0})
    assert [a for a, _ in d[18.0]] == union
    assert derated.name == raw.name and derated.source == raw.source


def test_derate_is_pure(raw) -> None:
    before = [(t, list(p)) for t, p in raw.curves]
    derate_polar(raw, START, FULL, RED)
    assert raw.curves == before


def test_speeds_up_to_start_are_unchanged(raw, derated) -> None:
    for tws in [*_steps(4.0, 18.0, 0.5), 12.0, 17.5]:
        for twa in range(0, 181):
            assert derated.speed(tws, twa) == pytest.approx(raw.speed(tws, twa), abs=1e-9), (
                tws,
                twa,
            )


@pytest.mark.parametrize("tws", [25.0, 27.0, 30.0, 35.0])
def test_speeds_from_full_are_reduced_by_exactly_the_reduction(raw, derated, tws) -> None:
    for twa in range(0, 181):
        assert derated.speed(tws, twa) == pytest.approx(
            (1.0 - RED) * raw.speed(tws, twa), abs=1e-9
        ), twa


@pytest.mark.parametrize("tws", [25.0, 30.0])
def test_targets_from_full_are_reduced(raw, derated, tws) -> None:
    r, d = raw.targets(tws), derated.targets(tws)
    assert d.up_bsp == pytest.approx(0.95 * r.up_bsp, abs=1e-9)
    assert d.down_bsp == pytest.approx(0.95 * r.down_bsp, abs=1e-9)


def test_target_angles_never_move(raw, derated) -> None:
    """Pitfall 9: a uniform per-TWS factor never moves the VMG angles (S-05)."""
    for tws in _steps(4.0, 30.0, 0.5):
        r, d = raw.targets(tws), derated.targets(tws)
        assert (d.up_twa, d.down_twa) == (r.up_twa, r.down_twa), tws


@pytest.mark.parametrize("tws", [12.0, 16.0, 20.0, 22.0, 25.0])
def test_target_speed_ratio_is_the_factor(raw, derated, tws) -> None:
    r, d = raw.targets(tws), derated.targets(tws)
    f = heavy_wind_factor(tws, START, FULL, RED)
    assert d.up_bsp / r.up_bsp == pytest.approx(f, abs=1e-9)
    assert d.down_bsp / r.down_bsp == pytest.approx(f, abs=1e-9)


def test_knots_above_the_top_curve_copy_it(raw) -> None:
    d = dict(derate_polar(raw, 22.0, 28.0, RED).curves)
    top = dict(raw.curves)[20.0]
    assert [a for a, _ in d[28.0]] == [a for a, _ in top]
    assert [b for _, b in d[28.0]] == pytest.approx([0.95 * b for _, b in top], abs=1e-12)
    assert [a for a, _ in d[22.0]] == [a for a, _ in top]
    assert [b for _, b in d[22.0]] == pytest.approx([b for _, b in top], abs=1e-12)
    assert [b for _, b in d[20.0]] == pytest.approx([b for _, b in top], abs=1e-12)


def test_zero_reduction_is_the_identity(raw) -> None:
    assert derate_polar(raw, START, FULL, 0.0) is raw


@pytest.mark.parametrize(
    "args",
    [(25.0, 25.0, 0.05), (26.0, 25.0, 0.05), (0.0, 25.0, 0.05), (18.0, 25.0, 1.0),
     (18.0, 25.0, -0.1), (math.nan, 25.0, 0.05), (18.0, math.inf, 0.05)],
)  # fmt: skip
def test_bad_parameters_raise(raw, args) -> None:
    with pytest.raises(ValueError):
        derate_polar(raw, *args)


# -- settings (S-01) ------------------------------------------------------------------------------
def test_settings_defaults_and_labels() -> None:
    s = Settings()
    assert (s.heavy_wind_start_kn, s.heavy_wind_full_kn, s.heavy_wind_reduction) == (
        18.0,
        25.0,
        0.05,
    )
    props = Settings.model_json_schema()["properties"]
    assert props["heavy_wind_start_kn"]["label"] == "Vent fort : début de réduction (nds)"
    assert props["heavy_wind_full_kn"]["label"] == "Vent fort : réduction complète (nds)"
    assert props["heavy_wind_reduction"]["label"] == "Vent fort : réduction"
    order = list(props)
    i = order.index("efficiency_down")
    assert order[i + 1 : i + 4] == [
        "heavy_wind_start_kn",
        "heavy_wind_full_kn",
        "heavy_wind_reduction",
    ]


@pytest.mark.parametrize(
    "kw",
    [
        {"heavy_wind_start_kn": 25.0, "heavy_wind_full_kn": 25.0},
        {"heavy_wind_start_kn": 26.0, "heavy_wind_full_kn": 25.0},
        {"heavy_wind_reduction": 0.31},
        {"heavy_wind_reduction": -0.01},
        {"heavy_wind_start_kn": 9.0},
        {"heavy_wind_full_kn": 41.0},
    ],
)
def test_settings_reject_bad_values(kw) -> None:
    with pytest.raises(ValidationError):
        Settings(**kw)


def test_old_settings_file_without_the_keys_loads(tmp_path) -> None:
    (tmp_path / "settings.json").write_text('{"version": 3, "settings": {"efficiency": 0.9}}')
    store = SettingsStore(tmp_path)
    assert store.alerts == [] and store.version == 3
    assert store.settings.heavy_wind_reduction == 0.05


def test_store_refuses_start_after_full_and_writes_nothing(tmp_path) -> None:
    store = SettingsStore(tmp_path)
    store.update({"heavy_wind_reduction": 0.1}, store.version)
    path = tmp_path / "settings.json"
    before, version = path.read_bytes(), store.version
    with pytest.raises(ValidationError):
        store.update({"heavy_wind_start_kn": 30.0}, store.version)
    assert store.version == version and path.read_bytes() == before
    assert store.settings.heavy_wind_start_kn == 18.0


# -- NavService (S-06) ----------------------------------------------------------------------------
def _nav_with_inputs(tmp_path, tws_kn: float, **settings) -> NavService:
    clock = SimClock()
    state = StateStore(clock)
    nav = NavService(state, clock, tmp_path)
    if settings:
        nav.settings_store.update(settings, nav.settings_store.version)
    target = nav.course.active_target()
    twd, hdg = R(161.0), R(116.0)
    lat, lon = geo.offset(target.anchor_lat, target.anchor_lon, twd + math.pi, 3.0)
    aw = apparent_from_true(twd, kn_to_ms(tws_kn), kn_to_ms(6.0), hdg)
    values = [
        {"path": "environment.wind.angleApparent", "value": aw.awa},
        {"path": "environment.wind.speedApparent", "value": aw.aws},
        {"path": "navigation.speedThroughWater", "value": kn_to_ms(6.0)},
        {"path": "navigation.heading", "value": hdg, "ref": "T"},
        {"path": "navigation.position", "value": {"latitude": lat, "longitude": lon}},
        {"path": "navigation.courseOverGroundTrue", "value": hdg, "ref": "T"},
        {"path": "navigation.speedOverGround", "value": kn_to_ms(6.0)},
    ]
    state.update_values("fastnet", values, clock.monotonic())
    return nav


def test_nav_targets_at_25_kn_are_derated_with_the_same_angles(tmp_path) -> None:
    on = _nav_with_inputs(tmp_path / "on", 25.0).update()["polar"]
    off = _nav_with_inputs(tmp_path / "off", 25.0, heavy_wind_reduction=0.0).update()["polar"]
    for side in ("up", "down"):
        assert on[side]["twa"] == off[side]["twa"]
        assert on[side]["bsp_kn"] / off[side]["bsp_kn"] == pytest.approx(0.95, abs=0.003)
    assert on["eff"] == off["eff"] == 0.92  # the efficiency is still applied, on top
    assert on["pct"] > off["pct"]


def test_nav_targets_at_12_kn_are_unchanged(tmp_path) -> None:
    on = _nav_with_inputs(tmp_path / "on", 12.0).update()["polar"]
    off = _nav_with_inputs(tmp_path / "off", 12.0, heavy_wind_reduction=0.0).update()["polar"]
    assert on["up"] is not None and on == off


def test_nav_polar_identity_follows_the_settings(tmp_path) -> None:
    nav = _nav_with_inputs(tmp_path, 12.0)
    raw = nav.polar_raw
    p1 = nav.polar
    assert nav.polar is p1 and p1 is not raw
    nav.settings_store.update({"efficiency": 0.9}, nav.settings_store.version)
    assert nav.polar is p1  # not a heavy_wind_* change
    nav.settings_store.update({"heavy_wind_start_kn": 17.0}, nav.settings_store.version)
    p2 = nav.polar
    assert p2 is not p1 and nav.polar is p2
    assert 17.0 in [t for t, _ in p2.curves]
    nav.settings_store.update({"heavy_wind_reduction": 0.0}, nav.settings_store.version)
    assert nav.polar is raw
    assert nav.polar_raw is raw
