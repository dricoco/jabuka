"""Worker cycle: one snapshot -> optimal whole course + forced current leg + cost + old route
re-evaluated, in process and through the forkserver RouterPool (ROUT-02, ROUT-07, ROUT-08)."""

from __future__ import annotations

import dataclasses
import os
import pickle

import pytest

if os.environ.get("JABUKA_REQUIRE_ROUTE") == "1":
    import numpy as np  # noqa: F401
else:  # Phase 2 worktrees without numpy skip instead of failing
    np = pytest.importorskip("numpy")

from jabuka.route import cycle  # noqa: E402
from jabuka.route.bench import assemble_fixture_pack  # noqa: E402
from jabuka.route.pool import RouterPool  # noqa: E402
from jabuka.route.types import CycleRequest, CycleResult, RouterSettings  # noqa: E402


@pytest.fixture(scope="module")
def pack_dir(tmp_path_factory):
    return assemble_fixture_pack(tmp_path_factory.mktemp("pack"), with_geofields=False)


@pytest.fixture(scope="module")
def creq(pack_dir, course, make_request):
    env = cycle.build_env(pack_dir)
    start, marks = course("A")
    t0 = env.fields.wind.t_first + 3600.0
    base = make_request(
        start.lat, start.lon, marks, prev_mark=start, t0=t0, tack0=1, settings=RouterSettings()
    )
    return CycleRequest(base)


def test_build_env_loads_the_pack(pack_dir) -> None:
    env = cycle.build_env(pack_dir)
    assert env.mask.shape == (5334, 4199)
    assert env.fields.waves is not None and env.fields.current is None
    with pytest.raises(ValueError, match="vent"):
        cycle.build_env(pack_dir.parent)


def test_in_process_cycle(pack_dir, creq) -> None:
    cycle.init_worker(str(pack_dir))
    res = cycle.run_cycle(creq)
    assert isinstance(res, CycleResult)
    assert res.optimal.ok and res.optimal.valid, res.optimal.reason
    assert res.optimal.tacks, "the whole course has side changes"
    assert res.forced is not None and res.forced.ok, res.forced
    assert len(res.forced.legs) == 1
    assert res.cost_s is not None and res.cost_s >= 0.0
    assert res.forced.legs[0].mark_id == res.optimal.legs[0].mark_id
    w = res.worker
    for key in ("level", "optimal_ms", "forced_ms", "steps", "rss_kb", "pid"):
        assert key in w
    assert w["level"] == "L0" and w["pid"] == os.getpid() and w["rss_kb"] > 0
    assert res.eta_old_now is None and res.old_valid is None


def test_old_path_reevaluated(pack_dir, creq) -> None:
    cycle.init_worker(str(pack_dir))
    first = cycle.run_cycle(creq)
    again = cycle.run_cycle(dataclasses.replace(creq, old_path=first.optimal.path))
    assert again.old_valid is True and again.old_reason is None
    remaining = first.optimal.eta - creq.base.t0
    assert abs(again.eta_old_now - first.optimal.eta) <= 0.01 * remaining


def test_pool_round_trip(pack_dir, creq) -> None:
    import asyncio

    async def go():
        pool = RouterPool(cycle.init_worker, (str(pack_dir),), timeout_s=120.0)
        try:
            return await pool.run_latest(cycle.run_cycle, creq)
        finally:
            pool.close()

    out = asyncio.run(go())
    assert out.status == "ok", out.error
    res = pickle.loads(pickle.dumps(out.value))
    assert res.optimal.ok and res.worker["pid"] != os.getpid()
    assert res.worker["rss_kb"] > 10_000


def test_pack_without_mask_fails_cleanly(tmp_path, creq) -> None:
    import asyncio
    import shutil

    bad = tmp_path / "bad"
    bad.mkdir()
    pack = assemble_fixture_pack(tmp_path / "good", with_geofields=False)
    for name in ("wind.npz", "wind.json"):
        shutil.copy(pack / name, bad / name)
    cycle.init_worker(str(bad))
    res = cycle.run_cycle(creq)
    assert not res.optimal.ok and "landmask.npz" in res.optimal.reason

    async def go():
        pool = RouterPool(cycle.init_worker, (str(bad),), timeout_s=60.0)
        try:
            a = await pool.run_latest(cycle.run_cycle, creq)
            b = await pool.run_latest(cycle.run_cycle, creq)
            return a, b, pool.stats
        finally:
            pool.close()

    a, b, stats = asyncio.run(go())
    assert a.status == b.status == "ok"
    assert not a.value.optimal.ok and "landmask.npz" in a.value.optimal.reason
    assert stats["crashes"] == 0 and stats["restarts"] == 0


def test_altered_land_mask_is_refused(tmp_path) -> None:
    """03-REVIEW MD-05: landmask.npz is checked against its landmask.json sha256."""
    import json
    import shutil

    pack = assemble_fixture_pack(tmp_path / "pack", with_geofields=False)
    side = pack / "landmask.json"
    doc = json.loads(side.read_text())
    doc["sha256"] = "0" * 64
    side.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="empreinte sha256"):
        cycle.build_env(pack)
    side.unlink()
    with pytest.raises(ValueError, match="landmask.json"):
        cycle.build_env(pack)
    shutil.rmtree(pack)


def test_worker_refuses_a_request_for_another_pack(pack_dir, creq) -> None:
    """03-REVIEW MD-05: a worker restarted after the pack was replaced on disk must not route
    the helm on a pack the core did not load."""
    from jabuka.route.racepack import pack_fingerprint

    cycle.init_worker(str(pack_dir))
    fp = pack_fingerprint(pack_dir)
    same = cycle.run_cycle(dataclasses.replace(creq, pack_fp=fp))
    assert same.optimal.ok
    other = tuple((stem, "f" * 64 if stem == "wind" else sha) for stem, sha in fp)
    res = cycle.run_cycle(dataclasses.replace(creq, pack_fp=other))
    assert not res.optimal.ok and res.optimal.reason.startswith(cycle.PACK_CHANGED)
