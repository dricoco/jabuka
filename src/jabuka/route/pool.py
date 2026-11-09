"""Router worker pool: one forkserver worker at nice +10, timeout kill, crash recovery and
coalescing (CONTEXT §Router, RESEARCH Pattern 9).

- ``ProcessPoolExecutor(max_workers=1, mp_context=get_context("forkserver"))`` explicitly on
  every Python: 3.13 (the Pi) defaults to ``fork``, unsafe from a threaded asyncio process
  (RESEARCH Pitfall 11).
- A job longer than ``timeout_s`` is killed (3.14 ``kill_workers()``, else every process in the
  private ``_processes`` mapping) and the executor recreated; a dead worker (BrokenProcessPool)
  is recreated too. An ordinary exception raised by the job keeps the pool.
- Any other failure of the pool machinery (fork ENOMEM while submitting, a second failure in the
  retry) resolves the request "error", drops the executor and is counted in ``faults``: the pool
  is never left busy (03-REVIEW CR-01).
- At most one job runs and one waits (latest wins: an older waiting request resolves
  "superseded").
- Nothing blocking runs on the event loop: submitting (which may spawn the worker) and killing
  happen in a thread.
- The worker raises its oom_score_adj to +500 (``raise_oom_score_adj``): it must not keep the
  core's OOMScoreAdjust=-500 (review B/R06).

Job functions and the initializer must be importable module-level functions (pickled by name).
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, NamedTuple

WORKER_START_METHOD: str | None = None  # set inside the worker by _pool_init

# The worker inherits jabuka-core's OOMScoreAdjust=-500 through the forkserver. As the biggest
# allocator it must be killed first, before gpsd, NetworkManager (the AP) or journald (review
# B/R06); the core recreates it on demand.
OOM_SCORE_ADJ_PATH = "/proc/self/oom_score_adj"
WORKER_OOM_SCORE_ADJ = 500


class PoolOutcome(NamedTuple):
    status: str  # ok | timeout | crashed | error | superseded
    value: Any
    elapsed_s: float
    error: str | None


def raise_oom_score_adj(target: int = WORKER_OOM_SCORE_ADJ, path: str | None = None) -> int | None:
    """Raise this process's oom_score_adj to target when it is below; never lower it (an
    unprivileged process may raise its own value, not lower it). Returns the value in effect, or
    None when it cannot be read or written (best effort: never raises)."""
    p = path if path is not None else OOM_SCORE_ADJ_PATH
    try:
        with open(p) as fh:
            current = int(fh.read().strip())
        if current >= target:
            return current
        with open(p, "w") as fh:
            fh.write(f"{target}\n")
        return target
    except (OSError, ValueError):
        return None


def _pool_init(
    nice: int, start_method: str, init_fn: Callable[..., Any] | None, init_args: tuple
) -> None:
    """Worker initializer: raise oom_score_adj, record the start method, lower the priority,
    then the user init."""
    global WORKER_START_METHOD
    raise_oom_score_adj(WORKER_OOM_SCORE_ADJ)  # first: killed before the services (R06)
    WORKER_START_METHOD = start_method
    if nice:
        try:
            os.nice(nice)
        except OSError:  # pragma: no cover - not permitted: keep the default priority
            pass
    if init_fn is not None:
        init_fn(*init_args)


def kill_pool(executor: ProcessPoolExecutor) -> None:
    """Kill every worker of ``executor`` (3.14 kill_workers, 3.13 private _processes), then shut
    it down without waiting and cancel queued futures."""
    kill = getattr(executor, "kill_workers", None)
    if kill is not None:  # Python >= 3.14
        try:
            kill()
        except Exception:  # pragma: no cover - already broken / shut down
            pass
    else:  # Python 3.13 (the Pi): private but stable attribute
        for proc in list((getattr(executor, "_processes", None) or {}).values()):
            try:
                proc.kill()
            except Exception:  # pragma: no cover - already gone
                pass
    executor.shutdown(wait=False, cancel_futures=True)


class _Request(NamedTuple):
    fn: Callable[[Any], Any]
    arg: Any
    fut: asyncio.Future[PoolOutcome]


class RouterPool:
    """Single-worker process pool for routing jobs, driven from the asyncio loop."""

    def __init__(
        self,
        init_fn: Callable[..., Any] | None = None,
        init_args: tuple = (),
        *,
        timeout_s: float = 60.0,
        nice: int = 10,
        start_method: str = "forkserver",
    ):
        self.init_fn = init_fn
        self.init_args = tuple(init_args)
        self.timeout_s = timeout_s
        self.nice = nice
        self.start_method = start_method
        self._ctx = multiprocessing.get_context(start_method)
        self._executor: ProcessPoolExecutor | None = None
        self._busy = False
        self._pending: _Request | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._stats: dict[str, Any] = {
            "jobs": 0,
            "ok": 0,
            "timeouts": 0,
            "crashes": 0,
            "errors": 0,
            "superseded": 0,
            "restarts": 0,
            "faults": 0,  # failures of the pool machinery itself (submit/start), see _fault
            "last_fault": None,
            "last_ms": None,
        }

    # ---- lifecycle ----------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "running": 1 if self._busy else 0,
            "pending": 1 if self._pending is not None else 0,
        }

    def start(self) -> None:
        """Create the executor (the worker process itself starts on the first job)."""
        if self._closed:
            raise RuntimeError("RouterPool is closed")
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=self._ctx,
                initializer=_pool_init,
                initargs=(self.nice, self.start_method, self.init_fn, self.init_args),
            )

    def _discard(self) -> None:
        ex, self._executor = self._executor, None
        if ex is not None:
            kill_pool(ex)

    def restart(self) -> None:
        """Kill the worker and create a fresh executor (a running job resolves "crashed")."""
        self._discard()
        self._stats["restarts"] += 1
        if not self._closed:
            self.start()

    def close(self) -> None:
        """Kill the worker; the running request resolves "error", the waiting one
        "superseded". run_latest raises RuntimeError afterwards."""
        self._closed = True
        pending, self._pending = self._pending, None
        if pending is not None and not pending.fut.done():
            pending.fut.set_result(PoolOutcome("superseded", None, 0.0, None))
            self._stats["superseded"] += 1
        self._discard()
        if self._task is not None and not self._task.done():
            self._task.cancel()

    # ---- jobs ---------------------------------------------------------------------------

    async def run_latest(self, fn: Callable[[Any], Any], arg: Any) -> PoolOutcome:
        """Run ``fn(arg)`` in the worker. If a job is running, wait as the single pending job;
        a newer request supersedes this one."""
        if self._closed:
            raise RuntimeError("RouterPool is closed")
        loop = asyncio.get_running_loop()
        req = _Request(fn, arg, loop.create_future())
        if self._busy:
            old, self._pending = self._pending, req
            if old is not None and not old.fut.done():
                old.fut.set_result(PoolOutcome("superseded", None, 0.0, None))
                self._stats["superseded"] += 1
        else:
            self._launch(req)
        return await req.fut

    def _launch(self, req: _Request) -> None:
        self._busy = True
        self._task = asyncio.get_running_loop().create_task(self._job(req))

    async def _job(self, req: _Request) -> None:
        """Run one request; total: whatever happens, ``_busy`` is cleared and the pending
        request is launched (03-REVIEW CR-01: an exception escaping here used to wedge the
        pool for the rest of the race)."""
        try:
            outcome = await self._execute(req.fn, req.arg)
        except asyncio.CancelledError:
            if not req.fut.done():
                req.fut.set_result(PoolOutcome("error", None, 0.0, "pool closed"))
            self._busy = False
            raise
        except Exception as exc:  # noqa: BLE001 - e.g. OSError ENOMEM/EAGAIN/EMFILE on fork
            outcome = await self._fault(exc)
        if not req.fut.done():
            req.fut.set_result(outcome)
        self._busy = False
        nxt, self._pending = self._pending, None
        if nxt is not None and not nxt.fut.done():
            if self._closed:
                nxt.fut.set_result(PoolOutcome("superseded", None, 0.0, None))
            else:
                self._launch(nxt)

    async def _fault(self, exc: BaseException) -> PoolOutcome:
        """An unexpected failure of the pool machinery itself (not of the job): count it,
        drop the executor (the next job creates a fresh one) and answer "error"."""
        self._stats["errors"] += 1
        self._stats["faults"] += 1
        self._stats["last_fault"] = repr(exc)
        try:
            await asyncio.to_thread(self._discard)
        except Exception:  # noqa: BLE001 - best effort: the executor reference is gone anyway
            self._executor = None
        if not self._closed:
            self._stats["restarts"] += 1
        return PoolOutcome("error", None, 0.0, f"pool fault: {exc!r}")

    async def _execute(self, fn: Callable[[Any], Any], arg: Any) -> PoolOutcome:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        self._stats["jobs"] += 1

        def done(status: str, value: Any = None, error: str | None = None) -> PoolOutcome:
            elapsed = loop.time() - t0
            self._stats["last_ms"] = round(elapsed * 1000.0, 1)
            return PoolOutcome(status, value, elapsed, error)

        if self._closed:
            return done("error", error="pool closed")
        try:
            self.start()
            assert self._executor is not None
            ex = self._executor
            cfut = await asyncio.to_thread(ex.submit, fn, arg)  # may spawn the worker
        except (BrokenProcessPool, RuntimeError, OSError):
            # broken or shut down since the last job, or the worker spawn failed (fork ENOMEM,
            # EAGAIN, EMFILE): recreate once and retry. A second failure reaches _job's _fault.
            await asyncio.to_thread(self._discard)
            if self._closed:
                return done("error", error="pool closed")
            self._stats["restarts"] += 1
            self.start()
            assert self._executor is not None
            ex = self._executor
            cfut = await asyncio.to_thread(ex.submit, fn, arg)
        try:
            value = await asyncio.wait_for(asyncio.wrap_future(cfut), self.timeout_s)
        except TimeoutError:
            self._stats["timeouts"] += 1
            await self._recreate(ex)
            return done("timeout", error=f"no result after {self.timeout_s:g} s")
        except BrokenProcessPool as exc:
            if self._closed:
                return done("error", error="pool closed")
            self._stats["crashes"] += 1
            await self._recreate(ex)
            return done("crashed", error=repr(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._stats["errors"] += 1
            return done("error", error=repr(exc))
        self._stats["ok"] += 1
        return done("ok", value)

    async def _recreate(self, ex: ProcessPoolExecutor) -> None:
        """Kill ``ex`` (if still current) off the loop and create a fresh executor."""
        if self._executor is ex:
            self._executor = None
        await asyncio.to_thread(kill_pool, ex)
        if not self._closed:
            self._stats["restarts"] += 1
            self.start()
