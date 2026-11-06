"""Picklable probe functions for RouterPool tests and diagnostics.

They live in the package because test modules imported with ``--import-mode=importlib`` cannot
be pickled by name into a forkserver child. Every job function takes exactly one argument
(RouterPool.run_latest(fn, arg)).
"""

from __future__ import annotations

import multiprocessing
import os
import time
from typing import Any

_TAG: Any = None


def init_probe(tag: Any = None) -> None:
    """Worker initializer: remember a tag so whoami() proves the initializer ran."""
    global _TAG
    _TAG = tag


def whoami(_arg: Any = None) -> dict[str, Any]:
    """Identity of the worker process: pid, parent pid, niceness, tag, start method."""
    from jabuka.route import pool as _pool  # the worker records how it was started

    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "nice": os.nice(0),
        "tag": _TAG,
        "start_method": _pool.WORKER_START_METHOD,
        "default_start_method": multiprocessing.get_start_method(allow_none=True),
    }


def sleep_for(seconds: float) -> float:
    """Block the worker for ``seconds`` (a stuck routing job)."""
    time.sleep(seconds)
    return seconds


def crash(_arg: Any = None) -> None:
    """Kill the worker abruptly (BrokenProcessPool on the parent side)."""
    os._exit(13)


def boom(_arg: Any = None) -> None:
    """Raise an ordinary exception in the worker."""
    raise ValueError("boom")


def echo(x: Any) -> Any:
    return x
