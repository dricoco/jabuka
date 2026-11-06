"""Laptop supervisor shim: what systemd does for the Jabuka units, for the soak (CONTEXT §Pi
specifics).

- Restart=, RestartSec=, WatchdogSec= are read from deploy/systemd/<unit> when the repo is present,
  else the embedded defaults (a test keeps both equal: drift guard). The source is reported.
- Type=notify: each service gets its own NOTIFY_SOCKET (an abstract unix datagram socket, so no
  path-length limit) and WATCHDOG_USEC; READY=1 marks it ready, WATCHDOG=1 feeds the watchdog.
- WatchdogSec: no WATCHDOG=1 for that long after READY=1 -> SIGABRT, then SIGKILL of the group
  after a grace, then a restart, as systemd does.
- KillMode=control-group: when the main process exits, the rest of its process group (forkserver,
  router worker) is SIGKILLed before the restart, so orphans never skew fd/RSS numbers.
- Every service runs in its own session (start_new_session=True); stdout+stderr go through a pipe
  into <run>/proc/<role>-<n>.log with a wall timestamp per line (the traceback classifier needs
  it). stop_all() is SIGTERM, then SIGKILL after a timeout; it is idempotent.
"""

from __future__ import annotations

import dataclasses
import os
import re
import select
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UNITS: dict[str, str] = {
    "core": "jabuka-core.service",
    "ingest": "jabuka-ingest-fastnet.service",
}
START_TIMEOUT_S = 90.0  # systemd DefaultTimeoutStartSec
ABORT_GRACE_S = 1.0  # SIGABRT -> SIGKILL (systemd TimeoutAbortSec, shortened)
STOP_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Policy:
    restart: str = "always"
    restart_sec: float = 2.0
    watchdog_sec: float | None = 30.0
    source: str = "embedded"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# Must equal deploy/systemd (tests/soak/test_soak_units.py drift guard).
EMBEDDED_POLICIES: dict[str, Policy] = {
    "jabuka-core.service": Policy("always", 2.0, 30.0, "embedded"),
    "jabuka-ingest-fastnet.service": Policy("always", 2.0, 30.0, "embedded"),
}

_TIMESPAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|sec|min|m)?\s*$")


def parse_timespan(text: str) -> float:
    """systemd time span subset: '2', '2s', '500ms', '1min' -> seconds."""
    m = _TIMESPAN.match(text)
    if not m:
        raise ValueError(f"unsupported time span {text!r}")
    v = float(m.group(1))
    unit = m.group(2) or "s"
    return v / 1000.0 if unit == "ms" else v * 60.0 if unit in ("min", "m") else v


def parse_unit_policy(path: Path) -> Policy:
    """Restart=/RestartSec=/WatchdogSec= from a unit file's [Service] section."""
    section = None
    vals: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Service" and "=" in line:
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    wd = vals.get("WatchdogSec")
    return Policy(
        restart=vals.get("Restart", "no"),
        restart_sec=parse_timespan(vals.get("RestartSec", "100ms")),
        watchdog_sec=parse_timespan(wd) if wd and wd not in ("0", "infinity") else None,
        source=f"deploy/systemd/{Path(path).name}",
    )


def repo_root() -> Path | None:
    """The checkout this module runs from (None for an installed wheel)."""
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "deploy" / "systemd").is_dir() and (p / "pyproject.toml").is_file():
            return p
    return None


def load_policy(unit: str, repo: Path | None = None) -> Policy:
    repo = repo if repo is not None else repo_root()
    if repo is not None:
        path = repo / "deploy" / "systemd" / unit
        if path.is_file():
            return parse_unit_policy(path)
    return EMBEDDED_POLICIES[unit]


@dataclass
class Service:
    role: str
    argv: list[str]
    policy: Policy
    env: dict[str, str]
    log_dir: Path
    notify_addr: str = ""
    proc: subprocess.Popen | None = None
    n: int = 0  # starts so far
    restarts: int = 0
    held: bool = False  # power off: no automatic restart
    started_wall: float | None = None
    ready_wall: float | None = None
    last_ping: float | None = None
    stopping: bool = False
    restart_due: float | None = None
    abort_sent: float | None = None
    watchdog_kills: int = 0
    exits: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    log_path: Path | None = None
    _sock: socket.socket | None = None

    @property
    def pid(self) -> int | None:
        p = self.proc
        return p.pid if p is not None and p.poll() is None else None


class Supervisor:
    """Restart=always / WatchdogSec / KillMode=control-group for a few child processes."""

    def __init__(
        self, run_dir: Path, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        self.run_dir = Path(run_dir)
        self.log_dir = self.run_dir / "proc"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.services: dict[str, Service] = {}
        self.events: list[dict[str, Any]] = []
        self.on_event = on_event
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._notify_thread: threading.Thread | None = None
        self._readers: list[threading.Thread] = []
        self._closed = False

    # -- bookkeeping -------------------------------------------------------------------------
    def _event(self, role: str, event: str, **kw: Any) -> None:
        rec = {"t_wall": time.time(), "role": role, "event": event, **kw}
        with self._lock:
            self.events.append(rec)
        if self.on_event is not None:
            try:
                self.on_event(rec)
            except Exception:  # noqa: BLE001 - observers never break supervision
                pass

    def add(self, role: str, argv: list[str], policy: Policy, env: dict[str, str] | None = None):
        tag = f"jabuka-soak-{os.getpid()}-{role}-{id(self) & 0xFFFFFF:x}"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
        sock.bind("\0" + tag)  # abstract namespace: no 108-byte path limit
        sock.setblocking(False)
        svc = Service(role, list(argv), policy, dict(env or {}), self.log_dir, "@" + tag)
        svc._sock = sock
        with self._lock:
            self.services[role] = svc
        return svc

    # -- spawning ----------------------------------------------------------------------------
    def _spawn(self, svc: Service) -> None:
        svc.n += 1
        svc.log_path = self.log_dir / f"{svc.role}-{svc.n}.log"
        env = dict(os.environ)
        env.update(svc.env)
        env["PYTHONUNBUFFERED"] = "1"
        env["NOTIFY_SOCKET"] = svc.notify_addr
        env.pop("WATCHDOG_PID", None)
        if svc.policy.watchdog_sec:
            env["WATCHDOG_USEC"] = str(int(svc.policy.watchdog_sec * 1e6))
        else:
            env.pop("WATCHDOG_USEC", None)
        proc = subprocess.Popen(
            svc.argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        svc.proc = proc
        svc.started_wall = time.time()
        svc.ready_wall = None
        svc.last_ping = None
        svc.stopping = False
        svc.abort_sent = None
        svc.restart_due = None
        t = threading.Thread(
            target=self._pump, args=(proc, svc.log_path), name=f"soak-log-{svc.role}", daemon=True
        )
        t.start()
        self._readers.append(t)
        self._event(svc.role, "start", pid=proc.pid, n=svc.n)

    @staticmethod
    def _pump(proc: subprocess.Popen, path: Path) -> None:
        """Child output -> log file, one wall timestamp per line."""
        assert proc.stdout is not None
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            for raw in iter(proc.stdout.readline, b""):
                f.write(f"{time.time():.3f} {raw.decode('utf-8', 'replace').rstrip()}\n")
                f.flush()
        proc.stdout.close()

    def start(self, role: str) -> None:
        with self._lock:
            svc = self.services[role]
            svc.held = False
            if svc.pid is None:
                self._spawn(svc)
        self._ensure_threads()

    def start_all(self) -> None:
        for role in list(self.services):
            self.start(role)

    def _ensure_threads(self) -> None:
        if self._monitor is None:
            self._monitor = threading.Thread(
                target=self._run_monitor, name="soak-shim", daemon=True
            )
            self._monitor.start()
        if self._notify_thread is None:
            self._notify_thread = threading.Thread(
                target=self._run_notify, name="soak-notify", daemon=True
            )
            self._notify_thread.start()

    # -- notify ------------------------------------------------------------------------------
    def _run_notify(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                socks = {s._sock: s for s in self.services.values() if s._sock is not None}
            if not socks:
                time.sleep(0.05)
                continue
            try:
                r, _, _ = select.select(list(socks), [], [], 0.1)
            except (OSError, ValueError):
                time.sleep(0.05)
                continue
            for sock in r:
                svc = socks[sock]
                while True:
                    try:
                        data = sock.recv(4096)
                    except (BlockingIOError, OSError):
                        break
                    self._on_notify(svc, data.decode("utf-8", "replace"))

    def _on_notify(self, svc: Service, text: str) -> None:
        now = time.time()
        for line in text.splitlines():
            if line == "READY=1":
                with self._lock:
                    if svc.ready_wall is None and svc.started_wall is not None:
                        svc.ready_wall = now
                        svc.last_ping = now
                        latency = round(now - svc.started_wall, 3)
                    else:
                        latency = None
                if latency is not None:
                    self._event(svc.role, "ready", pid=svc.pid, latency_s=latency)
            elif line == "WATCHDOG=1":
                svc.last_ping = now
            elif line == "STOPPING=1":
                svc.stopping = True

    # -- monitor -----------------------------------------------------------------------------
    def _run_monitor(self) -> None:
        while not self._stop.is_set():
            try:
                self._monitor_once()
            except Exception as exc:  # noqa: BLE001 - keep supervising
                self._event("shim", "monitor_error", error=repr(exc))
            time.sleep(0.05)

    def _monitor_once(self) -> None:
        now = time.time()
        with self._lock:
            services = list(self.services.values())
        for svc in services:
            proc = svc.proc
            if proc is not None and proc.poll() is not None:
                code = proc.returncode
                svc.proc = None
                self._kill_group(proc.pid, signal.SIGKILL)  # KillMode=control-group
                svc.exits.append({"t_wall": now, "pid": proc.pid, "code": code})
                self._event(svc.role, "exit", pid=proc.pid, code=code)
                if not svc.held and not self._closed and svc.policy.restart == "always":
                    svc.restart_due = now + svc.policy.restart_sec
                continue
            if proc is None:
                if svc.restart_due is not None and now >= svc.restart_due and not svc.held:
                    with self._lock:
                        if self._closed:
                            return
                        svc.restarts += 1
                        self._spawn(svc)
                    self._event(svc.role, "restart", n=svc.n, restarts=svc.restarts)
                continue
            # running: watchdog and start timeout
            wd = svc.policy.watchdog_sec
            if svc.abort_sent is not None:
                if now - svc.abort_sent >= ABORT_GRACE_S:
                    self._kill_group(proc.pid, signal.SIGKILL)
                continue
            if svc.ready_wall is None:
                if svc.started_wall is not None and now - svc.started_wall > START_TIMEOUT_S:
                    self._event(svc.role, "start_timeout", pid=proc.pid)
                    self._abort(svc, proc)
                continue
            if wd and svc.last_ping is not None and now - svc.last_ping > wd:
                svc.watchdog_kills += 1
                self._event(
                    svc.role, "watchdog", pid=proc.pid, silent_s=round(now - svc.last_ping, 3)
                )
                self._abort(svc, proc)

    def _abort(self, svc: Service, proc: subprocess.Popen) -> None:
        svc.abort_sent = time.time()
        try:
            os.kill(proc.pid, signal.SIGABRT)
        except ProcessLookupError:
            pass

    @staticmethod
    def _kill_group(pgid: int, sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    # -- control -----------------------------------------------------------------------------
    def main_pid(self, role: str) -> int | None:
        return self.services[role].pid

    def restarts(self, role: str) -> int:
        return self.services[role].restarts

    def kill(self, role: str, sig: int = signal.SIGKILL) -> int | None:
        """Signal the main process of ``role`` (None if not running)."""
        pid = self.main_pid(role)
        if pid is not None:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                return None
        return pid

    def hold(self, roles: list[str] | None = None) -> None:
        """Power off: no automatic restart for these roles until start()."""
        for role in roles or list(self.services):
            self.services[role].held = True
            self.services[role].restart_due = None

    def kill_all_groups(self, roles: list[str] | None = None) -> list[int]:
        """SIGKILL every process group at once (a power pull). Returns the main pids."""
        pids = []
        for role in roles or list(self.services):
            svc = self.services[role]
            if svc.proc is not None:
                pids.append(svc.proc.pid)
                self._kill_group(svc.proc.pid, signal.SIGKILL)
        return pids

    def wait_ready(self, role: str, timeout: float, *, after_n: int = 0) -> bool:
        """True once start number > after_n of ``role`` sent READY=1."""
        deadline = time.monotonic() + timeout
        svc = self.services[role]
        while time.monotonic() < deadline:
            if svc.n > after_n and svc.ready_wall is not None and svc.pid is not None:
                return True
            time.sleep(0.02)
        return False

    def all_pids(self) -> list[int]:
        """Main pids of every running service."""
        return [p for p in (s.pid for s in self.services.values()) if p is not None]

    def stop_all(self, timeout: float = STOP_TIMEOUT_S) -> None:
        """SIGTERM every group, SIGKILL whatever is left after ``timeout``; idempotent."""
        with self._lock:
            self._closed = True
            services = list(self.services.values())
        for svc in services:
            svc.held = True
            svc.restart_due = None
            if svc.proc is not None and svc.proc.poll() is None:
                self._kill_group(svc.proc.pid, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        for svc in services:
            proc = svc.proc
            if proc is None:
                continue
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            self._kill_group(proc.pid, signal.SIGKILL)  # leftovers of the group, or the main
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL never ignored
                pass
            svc.exits.append({"t_wall": time.time(), "pid": proc.pid, "code": proc.returncode})
        self._stop.set()
        for t in (self._monitor, self._notify_thread):
            if t is not None:
                t.join(timeout=5)
        for t in self._readers:
            t.join(timeout=5)
        for svc in services:
            if svc._sock is not None:
                svc._sock.close()
                svc._sock = None
