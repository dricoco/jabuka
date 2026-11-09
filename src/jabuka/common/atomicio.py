"""Crash-safe config/state files (power cuts mid-write must never leave a half-written file).

atomic_write_bytes: write ``.NAME.tmp`` + flush + fsync; hard-link the current file to
``.NAME.bak.tmp`` and rename it to ``NAME.bak``; rename tmp onto NAME; fsync the directory.
load_json_with_bak: NAME, then NAME.bak, then the default.
load_json_status: the same, plus where the value came from and an optional validate hook. A value
from NAME.bak ("bak") must be announced by the caller ("restauré"), and so must a file present but
unusable ("unreadable", "illisible"): neither may be silent (04-01 soak, 04-REVIEW WR-04).

Background mode (G-4-R05), opt-in per process: jabuka-core and jabuka-ingest-fastnet call
enable_background() at start and disable_background() (a bounded drain) at exit. Every fsync then
runs on ONE FIFO daemon thread (WORKER_NAME), so a multi-second SD stall delays that thread only,
never the event loop (tick, WebSocket, UDP intake, sd_notify watchdog). fsync_fd dups the fd on the
caller, so the caller may close its file at once. A job failure is logged and counted
(background_status), never raised and never silent. Without the switch (tests, tools, prep CLIs)
nothing changes: every call is synchronous, exactly as before.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("jabuka.durable")

WORKER_NAME = "jabuka-durable"

# -- durability thread (background mode) ---------------------------------------------------------
# No clock is read here (tests/test_no_wallclock.py): drain waits on the condition with a timeout.
_cond = threading.Condition()
_jobs: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
_enabled = False
_pending = 0  # jobs queued or running
_errors = 0
_last_error: str | None = None
_worker: threading.Thread | None = None


def _run_worker() -> None:
    global _pending, _errors, _last_error
    while True:
        job = _jobs.get()
        try:
            job()
        except Exception as exc:
            log.exception("background durability job failed")
            with _cond:
                _errors += 1
                _last_error = repr(exc)[:200]
        finally:
            with _cond:
                _pending -= 1
                _cond.notify_all()


def _submit(job: Callable[[], None]) -> None:
    global _pending, _worker
    with _cond:
        if _worker is None or not _worker.is_alive():
            worker = threading.Thread(target=_run_worker, name=WORKER_NAME, daemon=True)
            worker.start()  # may raise: then nothing is counted
            _worker = worker
        _pending += 1
        _jobs.put(job)  # SimpleQueue: unbounded, never blocks


def enable_background() -> None:
    """Process-wide: run every fsync on the durability thread from now on (idempotent). The
    thread starts lazily on the first job."""
    global _enabled
    with _cond:
        _enabled = True


def disable_background(timeout_s: float = 20.0) -> bool:
    """drain(timeout_s), then back to synchronous mode. Returns the drain result."""
    global _enabled
    drained = drain(timeout_s)
    with _cond:
        _enabled = False
    return drained


def background_enabled() -> bool:
    with _cond:
        return _enabled


def drain(timeout_s: float) -> bool:
    """True once no background job is queued or running (False after timeout_s)."""
    with _cond:
        return _cond.wait_for(lambda: _pending == 0, timeout=timeout_s)


def background_status() -> dict:
    with _cond:
        return {
            "enabled": _enabled,
            "pending": _pending,
            "errors": _errors,
            "last_error": _last_error,
        }


def fsync_fd(fd: int, on_done: Callable[[], None] | None = None) -> None:
    """fsync fd. Synchronous mode: os.fsync on the caller (errors propagate, as before), on_done
    in finally. Background mode: the fd is dup'd on the caller (the caller may close fd at once)
    and fsync + close of the dup run on the durability thread; on_done runs there in finally."""
    if not background_enabled():
        try:
            os.fsync(fd)
        finally:
            if on_done is not None:
                on_done()
        return
    dup = os.dup(fd)

    def job() -> None:
        try:
            try:
                os.fsync(dup)
            finally:
                os.close(dup)
        finally:
            if on_done is not None:
                on_done()

    try:
        _submit(job)
    except BaseException:
        os.close(dup)
        raise


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        # keep the previous good version as NAME.bak (atomic via hard link + rename)
        bak_tmp = path.with_name(f".{path.name}.bak.tmp")
        bak_tmp.unlink(missing_ok=True)
        os.link(path, bak_tmp)
        os.replace(bak_tmp, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def atomic_write_json(path: str | Path, obj: Any) -> None:
    data = json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    atomic_write_bytes(path, data.encode("utf-8"))


def load_json_with_bak(path: str | Path, default: Any) -> Any:
    return load_json_status(path, default)[0]


def load_json_status(
    path: str | Path, default: Any, validate: Callable[[Any], Any] | None = None
) -> tuple[Any, str]:
    """(value, source): source "main" or "bak" for the file that loaded, "missing" when neither
    NAME nor NAME.bak exists (first boot: the default is expected), "unreadable" when one exists
    but none loads (corruption: the caller must say so, never fall back silently). "bak" is a
    fallback too: the caller must say so ("restauré"), it may be an older state.

    validate: called with each decoded candidate; ValueError or TypeError (a pydantic
    ValidationError is a ValueError) rejects it and the next candidate is tried, so a main file
    that decodes but fails validation falls through to a valid NAME.bak. The value returned is
    validate's result. None: the decoded JSON, as before."""
    path = Path(path)
    present = False
    for p, source in ((path, "main"), (path.with_name(path.name + ".bak"), "bak")):
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            continue
        except OSError:  # EACCES/EIO, a directory: present but unreadable
            present = True
            continue
        present = True
        try:
            value = json.loads(data.decode("utf-8"))
        except ValueError:  # torn or bad JSON, bad UTF-8
            continue
        if validate is None:
            return value, source
        try:
            return validate(value), source
        except (ValueError, TypeError):  # decodes but invalid: try NAME.bak
            continue
    return default, ("unreadable" if present else "missing")
