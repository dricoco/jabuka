"""Soak backend driven by real systemd (plan 04-03, CONTEXT §Pi specifics): the units' own
Restart=, RestartSec=, WatchdogSec=, Type=notify and KillMode drive every recovery.

Two scopes:

- **system** (the Pi, root): the installed jabuka-core and jabuka-ingest-fastnet units. They are
  pointed at the soak inputs only through volatile drop-ins
  ``/run/systemd/system/<unit>.d/50-jabuka-soak.conf`` that reset ExecStart and set the soak one
  (same binary and flags as the shipped unit, except --data-dir, --device, --racepack, --clock
  sim and --gpsd on a fake port). Every other directive (User=, hardening, Restart=, WatchdogSec=)
  is the production one. Cleanup always runs (finally, atexit, signal handlers, and
  ``--systemd-cleanup`` alone): drop-ins removed, daemon-reload, the soak log fs unmounted, both
  units restarted on their production configuration. /run is cleared at reboot anyway.
- **user** (the laptop, no sudo): transient units through ``systemd-run --user`` with the shipped
  Type=, Restart=, RestartSec= and WatchdogSec= (and StartLimitIntervalSec=0). The hardening
  directives (User=, ProtectSystem=, PrivateDevices=, ...) are NOT applied: a user manager cannot
  apply most of them and the point is the restart, notify and watchdog control logic.

The control surface is the one jabuka.soak.supervisor.ProcessBackend describes, so the fault
actions run unchanged on the shim and on systemd.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jabuka.soak.supervisor import UNITS, Policy

DROPIN_NAME = "50-jabuka-soak.conf"
DROPIN_ROOT = Path("/run/systemd/system")
SOAK_PARENT = Path("/var/lib/jabuka")
RUN_LINK_DIR = Path("/run/jabuka-soak")
REAL_GPSD_PORT = 2947
SCOPES = ("user", "system")
SUDO_HINT = (
    "--systemd system drives the installed units and needs root: run "
    "`sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python ...`"
)
SHOW_PROPS = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "MainPID",
    "NRestarts",
    "InvocationID",
    "ExecMainCode",
    "ExecMainStatus",
    "ExecMainExitTimestampMonotonic",
)
_SAFE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


class SetupError(Exception):
    """The systemd mode cannot run here (not root, units missing, stale drop-in, no manager)."""


# -- unit files --------------------------------------------------------------------------------
def _service_items(text: str) -> list[tuple[str, str]]:
    """(key, value) of every [Service] line, in order (``systemctl cat`` output works too)."""
    section = None
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Service" and "=" in line:
            k, _, v = line.partition("=")
            out.append((k.strip(), v.strip()))
    return out


def unit_execstart(text: str) -> str:
    """The effective ExecStart= of a unit (+ drop-ins): an empty ExecStart= resets the list."""
    cur: list[str] = []
    for k, v in _service_items(text):
        if k == "ExecStart":
            cur = [v] if v else []
    if len(cur) != 1:
        raise ValueError(f"expected one effective ExecStart=, got {cur}")
    return cur[0]


def unit_value(text: str, key: str) -> str | None:
    vals = [v for k, v in _service_items(text) if k == key]
    return vals[-1] if vals else None


def _set_flag(argv: list[str], flag: str, value: str) -> list[str]:
    out = list(argv)
    for i, tok in enumerate(out):
        if tok == flag and i + 1 < len(out):
            out[i + 1] = value
            return out
        if tok.startswith(flag + "="):
            out[i] = f"{flag}={value}"
            return out
    return [*out, flag, value]


def soak_argv(
    role: str, shipped: list[str], *, soak_dir: Path, pty_link: Path, gpsd_port: int
) -> list[str]:
    """The shipped ExecStart argv with only the soak inputs changed."""
    data = str(Path(soak_dir) / "data")
    if role == "core":
        argv = _set_flag(shipped, "--data-dir", data)
        argv = _set_flag(argv, "--racepack", str(Path(soak_dir) / "racepack"))
        argv = _set_flag(argv, "--clock", "sim")
        return _set_flag(argv, "--gpsd", f"127.0.0.1:{gpsd_port}")
    if role == "ingest":
        argv = _set_flag(shipped, "--device", str(pty_link))
        return _set_flag(argv, "--data-dir", data)
    raise ValueError(f"unknown role {role!r}")


def _quote(tok: str) -> str:
    if not _SAFE.match(tok):
        raise ValueError(f"unsupported character in ExecStart token {tok!r}")
    return tok.replace("%", "%%")  # systemd specifiers


def dropin_text(argv: list[str]) -> str:
    return (
        "# jabuka soak (plan 04-03): volatile, removed by the harness or at reboot\n"
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart={' '.join(_quote(t) for t in argv)}\n"
    )


def check_soak_dir(soak_dir: Path) -> Path:
    p = Path(soak_dir)
    if p.parent != SOAK_PARENT or not p.name.startswith("soak-"):
        raise ValueError(f"the soak data dir must be {SOAK_PARENT}/soak-<ts>, got {p}")
    return p


def render_dropins(
    *, scope: str, units: dict[str, str], soak_dir: Path, pty_link: Path, gpsd_port: int
) -> dict[str, str]:
    """{unit name: drop-in text} for the system scope (``units``: unit name -> unit text)."""
    if scope != "system":
        raise ValueError("drop-ins are for the system scope; the user scope uses transient units")
    check_soak_dir(soak_dir)
    if int(gpsd_port) == REAL_GPSD_PORT:
        raise ValueError(f"the fake gpsd never uses the real gpsd port {REAL_GPSD_PORT}")
    out = {}
    for role, unit in UNITS.items():
        shipped = shlex.split(unit_execstart(units[unit]))
        argv = soak_argv(role, shipped, soak_dir=soak_dir, pty_link=pty_link, gpsd_port=gpsd_port)
        out[unit] = dropin_text(argv)
    return out


def _fmt_s(v: float) -> str:
    return f"{v:g}"


def _code(exec_code: str, status: str) -> int | None:
    """systemd ExecMainCode/Status -> a Popen-style returncode (-SIG when killed)."""
    try:
        c, s = int(exec_code or 0), int(status or 0)
    except ValueError:
        return None
    if c == 1:  # CLD_EXITED
        return s
    if c in (2, 3):  # CLD_KILLED, CLD_DUMPED
        return -s
    return None


@dataclass
class _Svc:
    role: str
    argv: list[str]
    policy: Policy
    env: dict[str, str]
    unit: str
    starts: int = 0
    created: bool = False
    exits: list[dict[str, Any]] = field(default_factory=list)
    watchdog_kills: int = 0
    restart_base: int = 0
    restart_offset: int = 0
    last: dict[str, str] = field(default_factory=dict)


class SystemdBackend:
    """Process control through systemctl / systemd-run (see the module docstring)."""

    mode = "systemd"

    def __init__(
        self,
        scope: str,
        *,
        run_dir: Path,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        systemctl: str = "systemctl",
        systemd_run: str = "systemd-run",
        journalctl: str = "journalctl",
        dropin_root: Path = DROPIN_ROOT,
        assume_root: bool | None = None,
        monitor: bool = True,
        poll_s: float = 0.5,
        tag: str | None = None,
        workdir: Path | None = None,
    ) -> None:
        if scope not in SCOPES:
            raise ValueError(f"--systemd must be user or system, got {scope!r}")
        self.scope = scope
        self.run_dir = Path(run_dir)
        self.on_event = on_event
        self.systemctl = systemctl
        self.systemd_run = systemd_run
        self.journalctl = journalctl
        self.dropin_root = Path(dropin_root)
        self.assume_root = assume_root
        self.poll_s = poll_s
        self.tag = tag or f"{time.strftime('%Y%m%dt%H%M%S')}-{os.getpid()}"
        self.workdir = Path(workdir) if workdir else self.run_dir
        self.services: dict[str, _Svc] = {}
        self.events: list[dict[str, Any]] = []
        self.mounts: list[Path] = []
        self.dropins: list[Path] = []
        self.cleaned = False
        self.cleanup_report: dict[str, Any] = {}
        self._installed = False
        self._pre_inv: dict[str, str] = {}
        self._stopped = False
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._want_monitor = monitor
        self._monitor: threading.Thread | None = None
        self._atexit = False

    # -- helpers -----------------------------------------------------------------------------
    @property
    def user(self) -> bool:
        return self.scope == "user"

    def unit(self, role: str) -> str:
        if self.user:
            return f"jabuka-soak-{self.tag}-{role}.service"
        return UNITS[role]

    def _ctl(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
        cmd = [self.systemctl, *(["--user"] if self.user else []), *args]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(cmd, 1, "", repr(exc))

    def _event(self, role: str, event: str, **kw: Any) -> None:
        rec = {"t_wall": time.time(), "role": role, "event": event, **kw}
        with self._lock:
            self.events.append(rec)
        if self.on_event is not None:
            with contextlib.suppress(Exception):
                self.on_event(rec)

    def _show_many(self, units: list[str], props: tuple[str, ...]) -> list[dict[str, str]]:
        r = self._ctl("show", *units, "-p", ",".join(props), timeout=20.0)
        blocks: list[dict[str, str]] = [{}]
        for line in r.stdout.splitlines():
            if not line.strip():
                if blocks[-1]:
                    blocks.append({})
                continue
            k, _, v = line.partition("=")
            blocks[-1][k] = v
        if not blocks[-1]:
            blocks.pop()
        return blocks

    def show(self, role: str, *props: str) -> dict[str, str]:
        b = self._show_many([self.unit(role)], props)
        return b[0] if b else {}

    def _is_root(self) -> bool:
        return self.assume_root if self.assume_root is not None else os.geteuid() == 0

    # -- setup -------------------------------------------------------------------------------
    def preflight(self) -> None:
        if self.user:
            r = self._ctl("is-system-running", timeout=10.0)
            state = r.stdout.strip()
            if state not in ("running", "degraded"):
                raise SetupError(f"no usable user systemd manager (is-system-running: {state!r})")
            if shutil.which(self.systemd_run) is None:
                raise SetupError(f"{self.systemd_run} not found")
            return
        if not self._is_root():
            raise SetupError(SUDO_HINT)
        for unit in UNITS.values():
            if self._ctl("cat", unit, timeout=20.0).returncode != 0:
                raise SetupError(
                    f"{unit} is not installed (systemctl cat failed): provision the Pi first"
                )
            stale = self.dropin_root / f"{unit}.d" / DROPIN_NAME
            if stale.exists():
                raise SetupError(
                    f"stale soak drop-in {stale} (an interrupted run?): run "
                    "`sudo bash scripts/soak.sh --systemd system --systemd-cleanup` first"
                )

    def installed_unit_text(self, unit: str) -> str:
        r = self._ctl("cat", unit, timeout=20.0)
        if r.returncode != 0:
            raise SetupError(f"{unit} is not installed: {r.stderr.strip()}")
        return r.stdout

    def unit_user(self, unit: str) -> str | None:
        """The User= of an installed unit (system scope), None for root or the user scope."""
        if self.user:
            return None
        blocks = self._show_many([unit], ("User",))
        return (blocks[0].get("User") or None) if blocks else None

    def add(
        self, role: str, argv: list[str], policy: Policy, env: dict[str, str] | None = None
    ) -> _Svc:
        svc = _Svc(role, list(argv), policy, dict(env or {}), self.unit(role))
        with self._lock:
            self.services[role] = svc
        return svc

    def _register_cleanup(self) -> None:
        if not self._atexit:
            atexit.register(self.cleanup)
            self._atexit = True

    def install(self, dropins: dict[str, str]) -> None:
        """System scope: write the drop-ins, daemon-reload, restart both units on them."""
        if self.user:
            raise SetupError("drop-ins are for the system scope")
        self._register_cleanup()
        for unit, text in dropins.items():
            d = self.dropin_root / f"{unit}.d"
            d.mkdir(parents=True, exist_ok=True)
            path = d / DROPIN_NAME
            path.write_text(text, encoding="utf-8")
            self.dropins.append(path)
        self._ctl("daemon-reload")
        for role in self.services:
            self._flush_restarts(role)
            self._pre_inv[role] = self.show(role, "InvocationID").get("InvocationID") or ""
        # blocking: the units are on the soak ExecStart (READY=1) before the harness talks to
        # port 80; wait_ready() then also checks the new invocation runs the soak argv, so the
        # harness never configures the production core (T-04-03-02)
        self._ctl("restart", *[UNITS[r] for r in ("ingest", "core")], timeout=180.0)
        self._installed = True
        for role in self.services:
            self._after_start(role)
        self._ensure_monitor()

    @contextlib.contextmanager
    def session(self, dropins: dict[str, str]) -> Iterator[SystemdBackend]:
        try:
            self.install(dropins)
            yield self
        finally:
            self.cleanup()

    def add_mount(self, path: Path) -> None:
        self._register_cleanup()
        self.mounts.append(Path(path))

    # -- restarts ----------------------------------------------------------------------------
    def _nrestarts(self, role: str) -> int:
        try:
            return int(self.show(role, "NRestarts").get("NRestarts") or 0)
        except ValueError:
            return 0

    def _flush_restarts(self, role: str) -> None:
        """Before an explicit start/stop: bank what systemd counted (a manual start resets
        NRestarts)."""
        svc = self.services[role]
        cur = self._nrestarts(role)
        if cur < svc.restart_offset:
            svc.restart_offset = 0
        svc.restart_base += cur - svc.restart_offset
        svc.restart_offset = cur

    def _after_start(self, role: str) -> None:
        svc = self.services[role]
        svc.restart_offset = self._nrestarts(role)

    def restarts(self, role: str) -> int:
        svc = self.services[role]
        if self._stopped:
            return svc.restart_base
        cur = self._nrestarts(role)
        if cur < svc.restart_offset:  # the manual start's reset landed after our offset read
            svc.restart_offset = 0
        return svc.restart_base + cur - svc.restart_offset

    n_restarts = restarts

    # -- control -----------------------------------------------------------------------------
    def _run_transient(self, svc: _Svc) -> subprocess.CompletedProcess:
        pol = svc.policy
        props = [
            "Type=notify",
            f"Restart={pol.restart}",
            f"RestartSec={_fmt_s(pol.restart_sec)}",
            "StartLimitIntervalSec=0",
            "KillMode=control-group",
        ]
        if pol.watchdog_sec:
            props.append(f"WatchdogSec={_fmt_s(pol.watchdog_sec)}")
        env = {"PYTHONUNBUFFERED": "1", **svc.env}
        cmd = [
            self.systemd_run,
            "--user",
            f"--unit={svc.unit.removesuffix('.service')}",
            "--collect",
            "--no-block",
            "--quiet",
            f"--working-directory={self.workdir}",
            *[a for p in props for a in ("-p", p)],
            *[f"--setenv={k}={v}" for k, v in env.items()],
            "--",
            *svc.argv,
        ]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(cmd, 1, "", repr(exc))

    def start(self, role: str) -> None:
        svc = self.services[role]
        self._stopped = False
        if self.user:
            self._register_cleanup()
            load = self.show(role, "LoadState").get("LoadState") if svc.created else None
            if load == "loaded":
                self._flush_restarts(role)
                self._ctl("start", "--no-block", svc.unit)
            else:  # never started, or collected after a stop: a new transient unit
                svc.restart_base += max(0, self._nrestarts(role) - svc.restart_offset)
                r = self._run_transient(svc)
                if r.returncode != 0:
                    raise SetupError(f"systemd-run {svc.unit} failed: {r.stderr.strip()}")
                svc.created = True
        else:
            self._flush_restarts(role)
            self._ctl("start", "--no-block", svc.unit)
        self._after_start(role)
        self._ensure_monitor()

    def start_all(self) -> None:
        """System scope: the drop-ins come from the added argv; user scope: transient units."""
        if self.user:
            for role in ("ingest", "core"):
                if role in self.services:
                    self.start(role)
            return
        self.install({s.unit: dropin_text(s.argv) for s in self.services.values()})

    def main_pid(self, role: str) -> int | None:
        try:
            pid = int(self.show(role, "MainPID").get("MainPID") or 0)
        except ValueError:
            return None
        return pid or None

    def all_pids(self) -> list[int]:
        return [p for p in (self.main_pid(r) for r in self.services) if p is not None]

    def kill(self, role: str, sig: int = signal.SIGKILL, whom: str = "main") -> int | None:
        """``systemctl kill --signal=SIG --kill-whom=main|all`` of the role's unit."""
        pid = self.main_pid(role)
        if pid is None and whom == "main":
            return None
        name = signal.Signals(sig).name
        self._ctl("kill", f"--signal={name}", f"--kill-whom={whom}", self.unit(role))
        return pid

    def starts(self, role: str) -> int:
        return self.services[role].starts

    def exit_codes(self, role: str, since: float) -> list[int | None]:
        self._poll_once()
        return [e["code"] for e in self.services[role].exits if e["t_wall"] >= since]

    def power_off(self, roles: list[str] | None = None) -> list[int]:
        """A power pull: SIGKILL every process of the units, then stop (cancels the pending
        auto-restart)."""
        roles = roles or [r for r in ("ingest", "core") if r in self.services]
        pids = [p for p in (self.main_pid(r) for r in roles) if p is not None]
        units = [self.unit(r) for r in roles]
        self._ctl("kill", "--signal=SIGKILL", "--kill-whom=all", *units)
        for r in roles:
            self._flush_restarts(r)
        self._ctl("stop", *units)
        return pids

    def power_on(self, roles: list[str] | None = None) -> None:
        roles = roles or [r for r in ("ingest", "core") if r in self.services]
        if self.user:
            for r in roles:
                self.start(r)
            return
        for r in roles:
            self._flush_restarts(r)
        self._ctl("start", "--no-block", *[self.unit(r) for r in roles])
        for r in roles:
            self._after_start(r)

    def power_pull(
        self, between: Callable[[list[int]], None], roles: list[str] | None = None
    ) -> list[int]:
        pids = self.power_off(roles)
        try:
            between(pids)
        finally:
            self.power_on(roles)
        return pids

    def wait_ready(self, role: str, timeout: float, *, after_n: int = 0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.show(role, "ActiveState", "SubState", "MainPID", "InvocationID")
            if (
                st.get("ActiveState") == "active"
                and st.get("SubState") == "running"
                and st.get("MainPID") not in (None, "", "0")
                and (not self._want_monitor or self.services[role].starts > after_n)
                and (st.get("InvocationID") or "") != self._pre_inv.get(role, "-")
                and self.runs_soak_argv(role, int(st["MainPID"]))
            ):
                return True
            self._poll_once()
            time.sleep(0.1)
        return False

    def runs_soak_argv(self, role: str, pid: int, proc: Path = Path("/proc")) -> bool:
        """System scope: the unit's main process carries every soak argument (data dir, pty,
        sim clock, fake gpsd), not the production ExecStart. Always true in the user scope."""
        if self.user:
            return True
        try:
            tokens = (proc / str(pid) / "cmdline").read_bytes().split(b"\0")
        except OSError:
            return False
        have = {t.decode("utf-8", "replace") for t in tokens}
        return all(a in have for a in self.services[role].argv[1:])

    def watchdog_sec(self, role: str) -> float | None:
        return self.services[role].policy.watchdog_sec

    def watchdog_kills(self, role: str) -> int:
        return self.services[role].watchdog_kills

    def wait_watchdog(self, role: str, pid: int | None, kills0: int, timeout: float) -> bool:
        """After the harness froze the main pid (SIGSTOP): wait for systemd's own watchdog
        (SubState *-watchdog, or a restart). Then SIGCONT the frozen pid so the WatchdogSignal
        (SIGABRT) systemd sent lands at once, as on a hung but signalable process; without it
        systemd would wait TimeoutAbortSec (90 s by default) before its SIGKILL."""
        svc = self.services[role]
        r0 = self.restarts(role)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if svc.watchdog_kills > kills0:
                fired = True
            else:
                sub = self.show(role, "SubState").get("SubState") or ""
                fired = "watchdog" in sub or self.restarts(role) > r0
                if fired:
                    with self._lock:
                        svc.watchdog_kills += 1
                    self._event(role, "watchdog", pid=pid, substate=sub)
            if fired:
                if pid is not None:
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.kill(pid, signal.SIGCONT)
                return True
            time.sleep(0.1)
        return False

    # -- monitor (exits, starts, watchdog for the timeline) -------------------------------------
    def _ensure_monitor(self) -> None:
        if self._want_monitor and self._monitor is None:
            self._monitor = threading.Thread(
                target=self._run_monitor, name="soak-systemd", daemon=True
            )
            self._monitor.start()

    def _run_monitor(self) -> None:
        while not self._stop.is_set():
            with contextlib.suppress(Exception):
                self._poll_once()
            self._stop.wait(self.poll_s)

    def _poll_once(self) -> None:
        if not self._want_monitor:
            return
        with self._lock:
            svcs = list(self.services.values())
        if not svcs:
            return
        blocks = self._show_many([s.unit for s in svcs], SHOW_PROPS)
        by_id = {b.get("Id"): b for b in blocks}
        now = time.time()
        for svc in svcs:
            cur = by_id.get(svc.unit)
            if cur is None:
                continue
            with self._lock:
                prev, svc.last = svc.last, cur
            inv = cur.get("InvocationID") or ""
            if inv and inv != prev.get("InvocationID"):
                svc.starts += 1
                self._event(svc.role, "start", pid=cur.get("MainPID"), n=svc.starts)
            ext = cur.get("ExecMainExitTimestampMonotonic") or "0"
            if ext not in ("0", "") and ext != prev.get("ExecMainExitTimestampMonotonic"):
                code = _code(cur.get("ExecMainCode", ""), cur.get("ExecMainStatus", ""))
                pid = prev.get("MainPID")
                svc.exits.append({"t_wall": now, "pid": pid, "code": code})
                self._event(svc.role, "exit", pid=pid, code=code)
            try:
                n_now, n_prev = int(cur.get("NRestarts") or 0), int(prev.get("NRestarts") or 0)
            except ValueError:
                n_now = n_prev = 0
            if prev and n_now > n_prev:
                self._event(svc.role, "restart", n_restarts=n_now)
            sub = cur.get("SubState") or ""
            if "watchdog" in sub and "watchdog" not in (prev.get("SubState") or ""):
                self._event(svc.role, "watchdog_substate", substate=sub)

    # -- journal -----------------------------------------------------------------------------
    def dump_journal(self, dest: Path, since_wall: float) -> list[Path]:
        """The units' journal since the run start -> dest/<role>-journal.log, one
        '<wall> <message>' line each (the traceback classifier's format)."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        units = {s.unit: s.role for s in self.services.values()}
        cmd = [self.journalctl, *(["--user"] if self.user else [])]
        for u in units:
            cmd += ["-u", u]
        cmd += ["--since", f"@{int(since_wall)}", "-o", "json", "--no-pager"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            out = r.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            out = ""
        files: dict[str, Any] = {}
        try:
            for line in out.splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                # the service's own output (_SYSTEMD_*UNIT) or the manager's lines about it
                # ("Main process exited", "Watchdog timeout": USER_UNIT / UNIT)
                fields = ("_SYSTEMD_USER_UNIT", "USER_UNIT", "_SYSTEMD_UNIT", "UNIT")
                role = next((units[e[k]] for k in fields if e.get(k) in units), None)
                if role is None:
                    continue
                msg = e.get("MESSAGE")
                if isinstance(msg, list):
                    msg = bytes(x & 0xFF for x in msg).decode("utf-8", "replace")
                ts = int(e.get("__REALTIME_TIMESTAMP", "0")) / 1e6
                f = files.get(role)
                if f is None:
                    f = files[role] = (dest / f"{role}-journal.log").open("a", encoding="utf-8")
                for part in str(msg or "").splitlines() or [""]:
                    f.write(f"{ts:.3f} {part}\n")
        finally:
            for f in files.values():
                f.close()
        return [dest / f"{r}-journal.log" for r in files]

    # -- teardown ----------------------------------------------------------------------------
    def stop_all(self, timeout: float = 30.0) -> None:
        """End of the run: stop the units (their restart counts are banked first)."""
        with self._lock:
            roles = list(self.services)
        if not roles or self._stopped:
            self._stop.set()
            return
        for r in roles:
            self._flush_restarts(r)
        self._poll_once()
        self._ctl("stop", *[self.unit(r) for r in roles], timeout=timeout + 30.0)
        self._stopped = True
        self._stop.set()
        if self._monitor is not None:
            self._monitor.join(timeout=5)
        if self.user:
            self._ctl("reset-failed", *[self.unit(r) for r in roles])

    def cleanup(self) -> dict[str, Any]:
        """Always safe to call (idempotent). System scope: drop-ins removed, daemon-reload,
        unmount, production units restarted; user scope: transient units stopped."""
        if self.cleaned:
            return self.cleanup_report
        self.cleaned = True
        self._stop.set()
        if self.user:
            units = [self.unit(r) for r in self.services]
            if units:
                self._ctl("stop", *units)
                self._ctl("reset-failed", *units)
            self.cleanup_report = {"scope": "user", "units": units}
            return self.cleanup_report
        removed = []
        for path in self.dropins:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
                removed.append(str(path))
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        self._ctl("daemon-reload")
        unmounted = [str(m) for m in self.mounts if unmount(m)]
        self._ctl("restart", *[UNITS[r] for r in ("ingest", "core")], timeout=180.0)
        left = soak_lines_in(self._ctl("cat", UNITS["core"]).stdout)
        with contextlib.suppress(OSError, ValueError):  # SSH gone: stdout may be a dead pipe
            print(
                f"jabuka-soak: systemd cleanup: drop-ins removed {len(removed)}, unmounted "
                f"{len(unmounted)}, production units restarted; `systemctl cat jabuka-core | "
                f"grep -c 50-jabuka-soak` = {left} (expected 0)",
                flush=True,
            )
        self.cleanup_report = {
            "scope": "system",
            "removed": removed,
            "unmounted": unmounted,
            "soak_lines_left": left,
        }
        return self.cleanup_report

    def info(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "units": {r: s.unit for r, s in self.services.items()},
            "n_restarts": {r: self.restarts(r) for r in self.services},
            "starts": {r: s.starts for r, s in self.services.items()},
            "watchdog_kills": {r: s.watchdog_kills for r, s in self.services.items()},
            "policies": {r: s.policy.to_dict() for r, s in self.services.items()},
            "hardening_applied": not self.user,
            "cleanup": self.cleanup_report,
        }


def soak_lines_in(text: str) -> int:
    return sum(1 for line in text.splitlines() if "50-jabuka-soak" in line)


def unmount(path: Path) -> bool:
    for args in (["umount", str(path)], ["umount", "-l", str(path)]):
        try:
            if subprocess.run(args, capture_output=True, timeout=30).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def soak_mounts(proc_mounts: Path = Path("/proc/mounts")) -> list[Path]:
    """Mount points left by a soak under /var/lib/jabuka/soak-*/ (deepest first)."""
    out = []
    try:
        lines = proc_mounts.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) > 1:
            mp = parts[1].replace("\\040", " ")
            if mp.startswith(str(SOAK_PARENT) + "/soak-"):
                out.append(Path(mp))
    return sorted(out, key=lambda p: len(p.parts), reverse=True)


def cleanup_system(
    *,
    dropin_root: Path = DROPIN_ROOT,
    assume_root: bool | None = None,
    systemctl: str = "systemctl",
    proc_mounts: Path = Path("/proc/mounts"),
) -> int:
    """``--systemd-cleanup``: remove stale soak drop-ins and mounts, restart the production units.
    Returns the number of 50-jabuka-soak lines left in ``systemctl cat jabuka-core``."""
    b = SystemdBackend(
        "system",
        run_dir=Path("."),
        dropin_root=dropin_root,
        assume_root=assume_root,
        systemctl=systemctl,
        monitor=False,
    )
    if not b._is_root():
        raise SetupError(SUDO_HINT)
    for unit in UNITS.values():
        p = Path(dropin_root) / f"{unit}.d" / DROPIN_NAME
        if p.exists():
            b.dropins.append(p)
    b.mounts.extend(soak_mounts(proc_mounts))
    return int(b.cleanup()["soak_lines_left"])


def mount_logs(
    logs: Path, mode: str, size: int, *, image_dir: Path, uid: int, gid: int
) -> dict[str, Any]:
    """System scope: a size-capped log fs on <soak>/data/logs (loop: an ext4 image in the soak dir,
    no root reserve; tmpfs: RAM). Returns what was mounted (raises SetupError on failure)."""
    logs.mkdir(parents=True, exist_ok=True)
    if mode == "loop":
        img = Path(image_dir) / "logs.img"
        with open(img, "wb") as f:
            f.truncate(size)
        for cmd in (
            ["mkfs.ext4", "-q", "-F", "-m", "0", str(img)],
            ["mount", "-o", "loop", str(img), str(logs)],
        ):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise SetupError(f"{' '.join(cmd)}: {r.stderr.strip()}")
        with contextlib.suppress(OSError):
            (logs / "lost+found").rmdir()
        os.chown(logs, uid, gid)
        return {"mode": "loop", "image": str(img), "bytes": size, "path": str(logs)}
    if mode == "tmpfs":
        r = subprocess.run(
            [
                "mount",
                "-t",
                "tmpfs",
                "-o",
                f"size={size},mode=0755,uid={uid},gid={gid}",
                "jabuka-soak",
                str(logs),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            raise SetupError(f"tmpfs mount on {logs}: {r.stderr.strip()}")
        return {"mode": "tmpfs", "bytes": size, "path": str(logs)}
    raise ValueError(f"unknown log fs mode {mode!r}")
