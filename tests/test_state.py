"""StateStore under a SimClock: per-source rows, staleness, arbitration, prefix thresholds."""

from __future__ import annotations

from jabuka.core.state import DEFAULT_STALE_S, StateStore


def _v(path: str, value, unit: str | None = None, **kw) -> dict:
    return {"path": path, "value": value, "unit": unit, **kw}


def test_same_path_two_sources_two_rows(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values("a", [_v("navigation.position", {"latitude": 1.0, "longitude": 2.0})], 0.0)
    st.update_values("b", [_v("navigation.position", {"latitude": 1.1, "longitude": 2.1})], 0.0)
    rows = [r for r in st.snapshot()["values"] if r["path"] == "navigation.position"]
    assert [r["src"] for r in rows] == ["a", "b"]


def test_staleness_flips_and_age_grows(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values(
        "fastnet", [_v("environment.wind.angleApparent", 0.5, "rad")], clock.monotonic()
    )
    row = st.snapshot()["values"][0]
    assert row["stale"] is False
    assert row["age_s"] == 0.0
    clock.advance(4.0)
    row = st.snapshot()["values"][0]
    assert row["stale"] is False
    assert row["age_s"] == 4.0
    clock.advance(2.0)
    row = st.snapshot()["values"][0]
    assert row["stale"] is True
    assert row["age_s"] == 6.0


def test_age_never_negative(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values("x", [_v("navigation.heading", 1.0, "rad", ref="M")], 100.0)  # future t_rx
    assert st.snapshot()["values"][0]["age_s"] == 0.0


def test_latest_freshest_non_stale(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values("a", [_v("navigation.speedThroughWater", 2.0, "m/s")], clock.monotonic())
    clock.advance(1.0)
    st.update_values("b", [_v("navigation.speedThroughWater", 3.0, "m/s")], clock.monotonic())
    latest = st.latest("navigation.speedThroughWater")
    assert latest is not None
    assert latest["src"] == "b"
    assert latest["value"] == 3.0
    clock.advance(10.0)
    assert st.latest("navigation.speedThroughWater") is None
    assert st.latest("does.not.exist") is None


def test_latest_skips_stale_source(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values("a", [_v("environment.depth.belowTransducer", 5.0, "m")], 0.0)
    clock.advance(8.0)
    st.update_values("b", [_v("environment.depth.belowTransducer", 6.0, "m")], clock.monotonic())
    clock.advance(3.0)  # a is 11 s old (> 10 s), b is 3 s old
    latest = st.latest("environment.depth.belowTransducer")
    assert latest is not None
    assert latest["src"] == "b"


def test_longest_prefix_thresholds(sim_clock) -> None:
    st = StateStore(sim_clock())
    assert st.threshold("environment.wind.angleApparent") == 5.0
    assert st.threshold("environment.wind.direction") == 5.0
    assert st.threshold("environment.current.set") == 60.0
    assert st.threshold("environment.current.drift") == 60.0
    assert st.threshold("environment.depth.belowTransducer") == 10.0
    assert st.threshold("navigation.position") == 3.0
    assert st.threshold("navigation.heading") == 5.0
    assert st.threshold("navigation.headingSomethingElse") == 10.0
    assert st.threshold("bandg.unknown.0x3B") == 10.0
    assert DEFAULT_STALE_S["environment.current."] == 60.0


def test_current_set_stays_fresh_longer(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values("fastnet", [_v("environment.current.set", 1.0, "rad", ref="M")], 0.0)
    st.update_values("fastnet", [_v("environment.wind.speedApparent", 5.0, "m/s")], 0.0)
    clock.advance(30.0)
    rows = {r["path"]: r for r in st.snapshot()["values"]}
    assert rows["environment.current.set"]["stale"] is False
    assert rows["environment.wind.speedApparent"]["stale"] is True


def test_health_merges_and_alive(sim_clock) -> None:
    clock = sim_clock()
    st = StateStore(clock)
    st.update_health("fastnet", {"bytes_in": 10, "frames_ok": 1}, clock.monotonic())
    st.update_health("fastnet", {"device": "ok"}, clock.monotonic())
    h = st.snapshot()["health"]["fastnet"]
    assert h["bytes_in"] == 10
    assert h["device"] == "ok"
    assert h["alive"] is True
    clock.advance(5.0)
    h = st.snapshot()["health"]["fastnet"]
    assert h["alive"] is False
    assert h["age_s"] == 5.0


def test_rows_sorted_by_path_then_src(sim_clock) -> None:
    st = StateStore(sim_clock())
    st.update_values("z", [_v("b.path", 1)], 0.0)
    st.update_values("a", [_v("b.path", 1)], 0.0)
    st.update_values("m", [_v("a.path", 1)], 0.0)
    rows = st.snapshot()["values"]
    assert [(r["path"], r["src"]) for r in rows] == [
        ("a.path", "m"),
        ("b.path", "a"),
        ("b.path", "z"),
    ]


def test_latest_ignores_off_values_from_another_source(sim_clock) -> None:
    """WR-08: a Fastnet "OFF" (value None) received after the gpsd TPV used to hide gpsd's SOG."""
    clock = sim_clock()
    st = StateStore(clock)
    st.update_values("gpsd", [_v("navigation.speedOverGround", 3.2, "m/s")], clock.monotonic())
    clock.advance(0.5)
    st.update_values("fastnet", [_v("navigation.speedOverGround", None, "m/s")], clock.monotonic())
    latest = st.latest("navigation.speedOverGround")
    assert latest is not None
    assert latest["src"] == "gpsd" and latest["value"] == 3.2
    # the OFF row is still shown for diagnostics
    rows = [r for r in st.snapshot()["values"] if r["path"] == "navigation.speedOverGround"]
    assert {r["src"]: r["value"] for r in rows} == {"gpsd": 3.2, "fastnet": None}
    # only OFF left: no value at all
    st2 = StateStore(clock)
    st2.update_values("fastnet", [_v("navigation.speedOverGround", None)], clock.monotonic())
    assert st2.latest("navigation.speedOverGround") is None
