"""Bus-health verdict rules (shared by fastnet-probe and the ingest heartbeat)."""

from __future__ import annotations

from jabuka.ingest.bus_health import STATES, WindowStats, classify

from jabuka.ingest.fastnet_framing import FramerStats


def test_states_contract() -> None:
    assert STATES == ("ok", "silent", "few_bytes", "no_frames", "noisy", "missing")


def test_silent() -> None:
    state, hint = classify(0, 0, 0, 5)
    assert state == "silent"
    assert hint.startswith("NO BYTES")


def test_no_frames_means_swap_wires() -> None:
    state, hint = classify(12000, 12000, 0, 5)
    assert state == "no_frames"
    assert "swap White/Green (A/B)" in hint
    assert "28800 8O2" in hint


def test_chance_checksum_match_still_counts_as_no_frames() -> None:
    # a byte-inverted example2 capture yields exactly one coincidental "frame"
    state, _ = classify(66425, 65963, 1, 27.7)
    assert state == "no_frames"


def test_few_bytes() -> None:
    state, hint = classify(500, 500, 0, 5)
    assert state == "few_bytes"
    assert hint.startswith("FEW BYTES")


def test_noisy() -> None:
    state, hint = classify(12000, 2000, 300, 5)
    assert state == "noisy"
    assert "Black" in hint
    assert "termination" in hint


def test_ok() -> None:
    assert classify(12000, 10, 500, 5, n_channels=12) == ("ok", "OK: 100.0 frames/s, 12 channels")


def test_ok_zero_window_does_not_divide_by_zero() -> None:
    state, hint = classify(12000, 0, 500, 0)
    assert state == "ok"
    assert "0.0 frames/s" in hint


def _stats(b: int, d: int, f: int) -> FramerStats:
    return FramerStats(bytes_in=b, bytes_discarded=d, frames_ok=f)


def test_window_stats_rates_over_last_window() -> None:
    w = WindowStats(5.0)
    assert w.rates()["bytes_in"] == 0
    for t in range(0, 11):
        w.push(float(t), _stats(t * 2400, t * 10, t * 100))
    r = w.rates()
    assert r["span_s"] == 5.0
    assert r["bytes_in"] == 5 * 2400
    assert r["bytes_discarded"] == 50
    assert r["frames_ok"] == 500
    assert r["bytes_per_s"] == 2400.0
    assert r["frames_per_s"] == 100.0


def test_window_stats_silence_gives_zero_rates() -> None:
    w = WindowStats(5.0)
    for t in range(0, 4):
        w.push(float(t), _stats(1000, 0, 40))  # counters frozen: bus went quiet
    r = w.rates()
    assert r["bytes_in"] == 0
    assert classify(r["bytes_in"], r["bytes_discarded"], r["frames_ok"], r["span_s"])[0] == (
        "silent"
    )


def test_window_stats_counter_reset_is_not_negative() -> None:
    w = WindowStats(5.0)
    w.push(0.0, _stats(5000, 0, 200))
    w.push(1.0, _stats(100, 0, 4))  # framer replaced after a reconnect
    r = w.rates()
    assert r["bytes_in"] >= 0 and r["frames_ok"] >= 0
