"""RouterPool: forkserver worker at nice +10, timeout kill, crash recovery, coalescing, and an
event loop that never blocks (on the Pi's Python 3.13 as well as 3.14)."""

from __future__ import annotations

import asyncio
import os

import pytest

from jabuka.route import pool_probe
from jabuka.route.pool import RouterPool


def make_pool(**kw) -> RouterPool:
    pool = RouterPool(pool_probe.init_probe, ("t",), **kw)
    pool.start()
    return pool


async def test_worker_identity_forkserver_and_nice() -> None:
    pool = make_pool(timeout_s=20.0)
    try:
        out = await pool.run_latest(pool_probe.whoami, None)
        assert out.status == "ok", out
        who = out.value
        assert who["start_method"] == "forkserver"
        assert who["tag"] == "t"  # initializer ran in the worker
        assert who["pid"] != os.getpid()
        assert who["ppid"] != os.getpid()  # forked by the fork server, not by us
        assert who["nice"] >= min(os.nice(0) + 10, 19)
        assert out.elapsed_s >= 0.0
        echo = await pool.run_latest(pool_probe.echo, {"a": 1})
        assert echo.status == "ok" and echo.value == {"a": 1} and echo.error is None
        st = pool.stats
        assert st["jobs"] == 2 and st["ok"] == 2 and st["restarts"] == 0
        assert st["running"] == 0 and st["pending"] == 0
        assert st["last_ms"] is not None
    finally:
        pool.close()


async def test_timeout_kills_and_recreates() -> None:
    pool = make_pool(timeout_s=0.5)
    try:
        loop = asyncio.get_running_loop()
        first = await pool.run_latest(pool_probe.whoami, None)
        t0 = loop.time()
        out = await asyncio.wait_for(pool.run_latest(pool_probe.sleep_for, 5.0), 10.0)
        assert out.status == "timeout"
        assert loop.time() - t0 < 3.0
        assert pool.stats["restarts"] == 1 and pool.stats["timeouts"] == 1
        again = await asyncio.wait_for(pool.run_latest(pool_probe.whoami, None), 10.0)
        assert again.status == "ok"
        assert again.value["pid"] != first.value["pid"]  # a fresh worker
        assert (await pool.run_latest(pool_probe.echo, 7)).value == 7
    finally:
        pool.close()


async def test_crash_recreates() -> None:
    pool = make_pool(timeout_s=20.0)
    try:
        out = await asyncio.wait_for(pool.run_latest(pool_probe.crash, None), 15.0)
        assert out.status == "crashed"
        assert pool.stats["crashes"] == 1 and pool.stats["restarts"] == 1
        nxt = await asyncio.wait_for(pool.run_latest(pool_probe.echo, "ok"), 15.0)
        assert nxt.status == "ok" and nxt.value == "ok"
    finally:
        pool.close()


async def test_error_keeps_pool() -> None:
    pool = make_pool(timeout_s=20.0)
    try:
        out = await pool.run_latest(pool_probe.boom, None)
        assert out.status == "error"
        assert "boom" in (out.error or "")
        assert pool.stats["errors"] == 1 and pool.stats["restarts"] == 0
        assert (await pool.run_latest(pool_probe.echo, 3)).status == "ok"
    finally:
        pool.close()


async def test_coalescing_latest_wins() -> None:
    pool = make_pool(timeout_s=20.0)
    try:
        await pool.run_latest(pool_probe.echo, 0)  # worker warm
        running = asyncio.create_task(pool.run_latest(pool_probe.sleep_for, 1.0))
        await asyncio.sleep(0.2)
        a = asyncio.create_task(pool.run_latest(pool_probe.echo, 1))
        await asyncio.sleep(0)
        b = asyncio.create_task(pool.run_latest(pool_probe.echo, 2))
        await asyncio.sleep(0.05)
        st = pool.stats
        assert st["running"] == 1 and st["pending"] == 1
        ra = await asyncio.wait_for(a, 10.0)
        assert ra.status == "superseded"
        rb = await asyncio.wait_for(b, 10.0)
        r0 = await running
        assert r0.status == "ok" and r0.value == 1.0
        assert rb.status == "ok" and rb.value == 2
        assert pool.stats["superseded"] == 1
        assert pool.stats["running"] == 0 and pool.stats["pending"] == 0
    finally:
        pool.close()


async def test_event_loop_never_blocks() -> None:
    pool = make_pool(timeout_s=20.0)
    try:
        loop = asyncio.get_running_loop()
        gaps: list[float] = []
        stop = asyncio.Event()

        async def ticker() -> None:
            last = loop.time()
            while not stop.is_set():
                await asyncio.sleep(0.05)
                now = loop.time()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        out = await pool.run_latest(pool_probe.sleep_for, 1.5)  # includes the worker spawn
        stop.set()
        await tick
        assert out.status == "ok"
        assert len(gaps) >= 20
        assert max(gaps) < 0.2, max(gaps)
    finally:
        pool.close()


async def test_close_resolves_waiters() -> None:
    pool = make_pool(timeout_s=20.0)
    running = asyncio.create_task(pool.run_latest(pool_probe.sleep_for, 5.0))
    await asyncio.sleep(0.2)
    pending = asyncio.create_task(pool.run_latest(pool_probe.echo, 1))
    await asyncio.sleep(0.05)
    pool.close()
    r1 = await asyncio.wait_for(running, 5.0)
    r2 = await asyncio.wait_for(pending, 5.0)
    assert r1.status in {"error", "crashed"}
    assert r2.status == "superseded"
    with pytest.raises(RuntimeError):
        await pool.run_latest(pool_probe.echo, 1)


def _flaky_submit(monkeypatch, fail_calls: set[int]) -> dict:
    """ProcessPoolExecutor.submit raising OSError(ENOMEM) on the given call numbers (1-based),
    as a fork failing under memory pressure on the Pi (03-REVIEW CR-01)."""
    from concurrent.futures import ProcessPoolExecutor

    orig = ProcessPoolExecutor.submit
    calls = {"n": 0}

    def flaky(self, fn, *a, **k):
        calls["n"] += 1
        if calls["n"] in fail_calls:
            raise OSError(12, "Cannot allocate memory")
        return orig(self, fn, *a, **k)

    monkeypatch.setattr(ProcessPoolExecutor, "submit", flaky)
    return calls


async def test_submit_oserror_is_retried_once(monkeypatch) -> None:
    calls = _flaky_submit(monkeypatch, {2})
    pool = make_pool(timeout_s=20.0)
    try:
        assert (await pool.run_latest(pool_probe.echo, 1)).status == "ok"
        out = await asyncio.wait_for(pool.run_latest(pool_probe.echo, 2), 15.0)
        assert out.status == "ok" and out.value == 2  # recreated and retried
        assert calls["n"] == 3
        assert pool.stats["running"] == 0 and pool.stats["faults"] == 0
    finally:
        pool.close()


async def test_pool_fault_never_wedges_the_pool(monkeypatch) -> None:
    # CR-01 regression: the submit fails twice in a row (first try and the retry) -> the job
    # resolves "error", the pool is not left busy and the next jobs run on a fresh executor.
    _flaky_submit(monkeypatch, {2, 3})
    pool = make_pool(timeout_s=20.0)
    try:
        assert (await pool.run_latest(pool_probe.echo, 1)).status == "ok"
        out = await asyncio.wait_for(pool.run_latest(pool_probe.echo, 2), 15.0)
        assert out.status == "error" and "Cannot allocate memory" in (out.error or "")
        st = pool.stats
        assert st["running"] == 0 and st["pending"] == 0
        assert st["faults"] == 1 and "OSError" in st["last_fault"]
        r3 = await asyncio.wait_for(pool.run_latest(pool_probe.echo, 3), 15.0)
        assert r3.status == "ok" and r3.value == 3
        assert pool._task is not None and pool._task.exception() is None
    finally:
        pool.close()


async def test_pool_fault_launches_the_pending_request(monkeypatch) -> None:
    from jabuka.route import pool as pool_mod

    pool = make_pool(timeout_s=20.0)
    real = pool_mod.RouterPool._execute
    n = {"calls": 0}

    async def boom_once(self, fn, arg):
        n["calls"] += 1
        if n["calls"] == 1:
            await asyncio.sleep(0.2)
            raise OSError(11, "Resource temporarily unavailable")
        return await real(self, fn, arg)

    monkeypatch.setattr(pool_mod.RouterPool, "_execute", boom_once)
    try:
        first = asyncio.create_task(pool.run_latest(pool_probe.echo, 1))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(pool.run_latest(pool_probe.echo, 2))
        r1 = await asyncio.wait_for(first, 5.0)
        r2 = await asyncio.wait_for(second, 15.0)
        assert r1.status == "error" and "pool fault" in (r1.error or "")
        assert r2.status == "ok" and r2.value == 2
        assert pool.stats["running"] == 0
    finally:
        pool.close()
