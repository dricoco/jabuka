"""Pi benchmark gate script (2026-11-09): quick laptop run on the fixture pack."""

from __future__ import annotations

import json
import os
import time

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route import bench  # noqa: E402


def test_quick_fixture_bench(tmp_path, capsys) -> None:
    out = tmp_path / "bench.json"
    t0 = time.perf_counter()
    rc = bench.main(["--quick", "--fixture", "--json", str(out)])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 120.0
    text = capsys.readouterr().out
    assert "NIVEAU RECOMMANDÉ" in text
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["recommended"] in ("L0", "L1")
    assert set(data["levels"]) == {"L0", "L1"}
    for lvl in ("L0", "L1"):
        row = data["levels"][lvl]
        for key in ("p50_s", "p95_s", "max_s", "jitter_ms", "rss_kb", "runs", "pass", "eta_h"):
            assert key in row, (lvl, key)
        assert row["p95_s"] > 0 and row["pass"] is True
    plat = data["platform"]
    for key in ("python", "numpy", "cpu", "machine"):
        assert key in plat
    assert data["gate"] == {"p95_s": 30.0, "jitter_ms": 200.0}


def test_levels_and_duty_math() -> None:
    assert bench.parse_levels("L0,L3") == ["L0", "L3"]
    with pytest.raises(SystemExit):
        bench.parse_levels("L9")
    assert bench.percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert bench.percentile([5.0], 95) == 5.0
    # L4: 10-min cadence; L5: cost every other cycle
    assert bench.duty("L4", [6.0, 6.0], [2.0, 2.0]) == pytest.approx(8.0 / 600.0)
    assert bench.duty("L5", [6.0, 6.0], [2.0, 2.0]) == pytest.approx(7.0 / 600.0)
    assert bench.duty("L0", [6.0], [2.0]) is None
