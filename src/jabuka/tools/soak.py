"""jabuka-soak: run the real Jabuka stack under SimClock at ~60x, inject a seeded fault schedule,
check recovery through a WebSocket "tablet" and /proc probes, write a JSON + Markdown report.

    python -m jabuka.tools.soak --scenario ci [--speed X] [--duration SIM_S] [--seed N]
        [--out DIR] [--logs-fs auto|tmpfs:SIZE|loop:SIZE|none] [--fixtures DIR] [--python EXE]
        [--keep] [--systemd user|system] [--systemd-cleanup]

Exit 0 PASS, 1 FAIL, 2 usage/setup error. The run dir is <out>/<UTC ts>-<scenario>/ (created
here, never pre-existing; an --out under /var/lib/jabuka is refused): report.json, report.md,
samples.csv, timeline.jsonl, proc/<role>-<n>.log, data/ (core + ingest data dir), racepack/.

Processes (each spawned as [python, -m, module]): the synthetic X35 (jabuka.sim.synth, pty mode,
fake gpsd, steering on the core's own targets), the receive-only ingest on that pty and the core
(with its forkserver router worker), both under the supervisor shim (jabuka.soak.supervisor).

With logs_fs tmpfs (or auto when the scenario has a disk-full fault) the harness re-executes
itself under ``unshare --user --map-root-user --mount`` to mount a size-limited tmpfs on
data/logs; without a user namespace the disk-full fault is SKIPPED, never run on the real disk.

--systemd (plan 04-03, jabuka.soak.systemd): the core and the ingest run as systemd units instead
of under the shim, so systemd's own Restart=/RestartSec=/WatchdogSec=/Type=notify/KillMode drive
every recovery. ``user``: transient user units (laptop, no sudo; disk-full SKIPPED). ``system``
(Pi, root): the installed units through volatile /run drop-ins, soak data under
/var/lib/jabuka/soak-<ts>/, the tablet still on port 80, cleanup always (drop-ins removed,
production units restarted); ``--systemd-cleanup`` alone repairs an interrupted run.
Dev / bench tool: never part of a systemd unit; it may read the wall clock.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import hashlib
import json
import math
import os
import platform
import random
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jabuka.soak import probes
from jabuka.soak import report as rep
from jabuka.soak import systemd as sd
from jabuka.soak.faults import FAULTS
from jabuka.soak.pack import build_pack, inside
from jabuka.soak.scenario import FaultSpec, Scenario, compile_timeline, load_scenario, parse_logs_fs
from jabuka.soak.supervisor import UNITS, ProcessBackend, Supervisor, load_policy, repo_root
from jabuka.soak.tablet import TabletClient

REFUSED_OUT = Path("/var/lib/jabuka")
SYNTH_KINDS = frozenset({"bus-silent", "garbage", "noise", "unplug", "gps-loss", "clock-jump"})
LOCAL_TZ = "Europe/Zagreb"
STARTUP_TIMEOUT_S = 60.0
# WALL (real) seconds: TabletClient.wait runs on time.monotonic, so the wait does not shrink with
# --speed. On the Pi 3B the first route = forkserver spawn + worker init (pack, land mask,
# geofields) + one L0 cycle (bench p95 5.04 s), about 15-30 s real. 180 s covers one RouterPool
# job killed at POOL_TIMEOUT_S (60 s) + the RETRY_NO_ROUTE_S retry delay (60 s at speed 1, less
# when accelerated) + a complete second attempt (<= 60 s) (quick-261110-lqa; parity-tested in
# tests/soak/test_soak_units.py against jabuka.core.router_service, not imported here).
FIRST_ROUTE_TIMEOUT_S = 180.0
# the reason of a fault skipped by a shortened run (--duration). scripts/freeze-check.sh matches
# this phrase: F3/F4 never count such a report (plan 04-07, parity-tested)
SKIP_AFTER_END = "after the end of the run"


class SoakAbort(Exception):
    """The run cannot continue (a harness process died, the wall budget is exhausted)."""


def _free(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse_utc(text: str) -> float:
    if text == "now":
        return float(int(time.time()))
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def local_minutes(epoch: float, *, up: bool = False) -> str:
    """UTC epoch -> local (Europe/Zagreb) 'YYYY-MM-DDTHH:MM' for the settings race window."""
    from zoneinfo import ZoneInfo

    e = math.ceil(epoch / 60.0) * 60 if up else math.floor(epoch / 60.0) * 60
    return datetime.fromtimestamp(e, UTC).astimezone(ZoneInfo(LOCAL_TZ)).strftime("%Y-%m-%dT%H:%M")


def checkout() -> Path | None:
    """The jabuka checkout: the one this module runs from, else the current directory when it is
    one (the Pi runs the installed wheel from /opt/jabuka/venv inside ~/jabuka: the report's
    git.head then names that checkout, as 04-02 freeze-check needs)."""
    repo = repo_root()
    if repo is not None:
        return repo
    cwd = Path.cwd()
    if (cwd / "deploy" / "systemd").is_dir() and (cwd / "pyproject.toml").is_file():
        return cwd
    return None


def userns_available() -> bool:
    """True when an unprivileged user + mount namespace can be created on this host."""
    exe = shutil.which("unshare")
    if exe is None:
        return False
    try:
        r = subprocess.run(
            [exe, "--user", "--map-root-user", "--mount", "true"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


class Harness:
    """One soak run: processes, tablet, probes, fault timeline, report."""

    def __init__(self, run_dir: Path, sc: Scenario, args: argparse.Namespace) -> None:
        self.run_dir = run_dir
        self.sc = sc
        self.args = args
        self.repo = checkout()
        self.speed = float(args.speed or sc.speed)
        self.duration = float(args.duration or sc.duration_s)
        self.seed = sc.seed if args.seed is None else int(args.seed)
        self.timeline = compile_timeline(sc, self.seed)
        self.py = args.python or sys.executable
        self.fixtures = Path(args.fixtures).resolve()
        self.start_utc = parse_utc(sc.start_utc)
        self.data_dir = run_dir / "data"
        self.pack_dir = run_dir / "racepack"
        self.rt_dir = run_dir / "run"
        self.link = self.rt_dir / "fastnet-pty"
        self.http_port = _free(socket.SOCK_STREAM)
        self.udp_port = _free(socket.SOCK_DGRAM)
        self.gpsd_port = _free(socket.SOCK_STREAM)
        self.control_port: int | None = None
        self.scope: str | None = getattr(args, "systemd", None)
        self.code: dict[str, Any] | None = None  # report "code": the package that runs (04-04)
        self.code_error: str | None = None
        self.git: dict[str, Any] | None = None
        self.oom_adj: int | None = None  # system scope: the harness's own oom_score_adj
        self.state_root = run_dir  # every harness write into the stack's files stays inside it
        self.owner: tuple[int, int] | None = None  # system scope: the units' User=/Group=
        self.logs_fs_info: dict[str, Any] | None = None
        self.sup: ProcessBackend
        if self.scope is None:
            self.sup = Supervisor(run_dir, on_event=self._on_sup_event)
        else:
            self.sup = sd.SystemdBackend(
                self.scope,
                run_dir=run_dir,
                on_event=self._on_sup_event,
                tag=run_dir.name.lower().replace("_", "-"),
                workdir=self.repo or run_dir,
            )
        if self.scope == "system":
            self.soak_dir = sd.SOAK_PARENT / f"soak-{run_dir.name.split('-', 1)[0]}"
            self.state_root = self.soak_dir
            self.data_dir = self.soak_dir / "data"
            self.pack_dir = self.soak_dir / "racepack"
            self.rt_dir = sd.RUN_LINK_DIR
            self.link = self.rt_dir / "fastnet-pty"
            self.http_port, self.udp_port = self._production_ports()
            while self.gpsd_port == sd.REAL_GPSD_PORT:
                self.gpsd_port = _free(socket.SOCK_STREAM)
        self._pty_owner: threading.Thread | None = None
        self._pty_stop = threading.Event()
        self._pty_failed: str | None = None  # pty path whose chown failure was already logged
        self.tablet: TabletClient | None = None  # type: ignore[assignment]
        self.synth: subprocess.Popen | None = None
        self._synth_reader: threading.Thread | None = None
        self._progress: tuple[float, float] | None = None  # (sim t, wall)
        self._tl_lock = threading.Lock()
        self._tl = rep.open_append(run_dir / "timeline.jsonl")
        self.t0_wall = time.time()
        self.wall_budget = self.duration / self.speed * 4.0 + 600.0
        self.faults: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []
        self.findings: list[str] = []
        self.checks: dict[str, dict] = {}
        self.logs_fs_mode, self.logs_fs_bytes = parse_logs_fs(args.logs_fs or sc.logs_fs)
        self.tmpfs = False
        self.disk_full_skip = (
            "user scope: the services run under the user manager, outside the harness's mount "
            "namespace; never filled on the real disk"
            if self.scope == "user"
            else "--logs-fs none: never filled on the real disk (use --logs-fs loop:SIZE)"
            if self.scope == "system"
            else "no user namespace / tmpfs for data/logs: never filled on the real disk"
        )
        self.policies: dict[str, Any] = {}
        self.setup_error: str | None = None
        self.logcheck_runs: list[dict[str, Any]] = []
        self.persistence: list[dict[str, Any]] = []
        self.preapplied: dict[str, float] = {}
        self._course_check = 0.0
        self.rng = random.Random(self.seed)
        self.sampler: probes.Sampler | None = None
        # held from the end of the main run until run_soak has written and handed back the
        # report (review WR-02, plan 04-07)
        self.end_signals = sd.SignalHold()
        self.started_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # -- timeline ----------------------------------------------------------------------------
    def log(self, event_type: str, /, **kw: Any) -> None:
        rec = {"t_wall": round(time.time(), 3), "t_sim": round(self.sim_now(), 1)}
        rec["type"] = event_type
        rec.update(kw)
        with self._tl_lock:
            if not self._tl.closed:
                self._tl.write(json.dumps(rec, default=str) + "\n")
                self._tl.flush()

    def _on_sup_event(self, ev: dict[str, Any]) -> None:
        self.log("process", **{k: v for k, v in ev.items() if k != "t_wall"})

    # -- sim time ----------------------------------------------------------------------------
    def sim_now(self) -> float:
        p = self._progress
        if p is None:
            return 0.0
        t, wall = p
        return t + min(90.0, max(0.0, (time.time() - wall) * self.speed))

    def poll_abort(self) -> None:
        if self.synth is not None and self.synth.poll() is not None:
            raise SoakAbort(f"the synthetic boat exited with {self.synth.returncode}")
        if time.time() - self.t0_wall > self.wall_budget:
            raise SoakAbort(f"wall-time budget exhausted ({self.wall_budget:.0f} s)")

    # -- HTTP --------------------------------------------------------------------------------
    def http(
        self, method: str, path: str, body: Any = None, timeout: float = 5.0
    ) -> tuple[int, Any]:
        url = f"http://127.0.0.1:{self.http_port}{path}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (loopback)
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "null")
            except ValueError:
                return e.code, None
        except (OSError, ValueError):
            return 0, None

    # -- synth -------------------------------------------------------------------------------
    def control(self, kind: str, on: bool) -> None:
        if self.control_port is None:
            raise SoakAbort("synth control port unknown")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(
                json.dumps({"fault": kind, "on": on}).encode(), ("127.0.0.1", self.control_port)
            )

    def _synth_argv(self) -> list[str]:
        w = self.sc.wind
        lat, lon = self.sc.start
        iso = datetime.fromtimestamp(self.start_utc, UTC).strftime("%Y-%m-%dT%H:%M:%S")
        # the synth runs far longer than the scenario: the harness stops it at the end
        dur = self.duration * 4.0 + 7200.0
        return [
            self.py,
            "-m",
            "jabuka.sim.synth",
            "--mode",
            "pty",
            "--link",
            str(self.link),
            "--follow",
            f"http://127.0.0.1:{self.http_port}",
            "--follow-nowait",
            "--clock-udp",
            f"127.0.0.1:{self.udp_port}",
            "--control",
            "127.0.0.1:0",
            "--progress",
            "--wait-reader",
            "30",
            "--wait-gpsd",
            "30",
            "--gpsd-port",
            str(self.gpsd_port),
            "--speed",
            str(self.speed),
            "--duration",
            str(dur),
            "--twd",
            str(w["twd"]),
            "--tws",
            str(w["tws_kn"]),
            "--shift",
            str(w.get("shift_deg_h", 0.0)),
            "--gust",
            str(w.get("gust_kn", 0.0)),
            "--twa",
            "45",
            "--start",
            f"{lat},{lon}",
            "--start-utc",
            iso,
            "--seed",
            str(self.seed),
        ]

    def _read_synth(self) -> None:
        assert self.synth is not None and self.synth.stdout is not None
        with rep.open_append(self.run_dir / "proc" / "synth.log") as f:
            for raw in iter(self.synth.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                f.write(f"{time.time():.3f} {line}\n")
                f.flush()
                if line.startswith("{"):
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if obj.get("type") == "progress":
                        self._progress = (float(obj["t"]), time.time())
                elif line.startswith("jabuka-sim: control on "):
                    self.control_port = int(line.rsplit(":", 1)[1])

    def start_synth(self) -> None:
        self.rt_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "proc").mkdir(parents=True, exist_ok=True)
        self.synth = subprocess.Popen(
            self._synth_argv(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=dict(os.environ, PYTHONUNBUFFERED="1"),
        )
        self._synth_reader = threading.Thread(target=self._read_synth, daemon=True)
        self._synth_reader.start()
        if self.scope == "system":
            self._pty_owner = threading.Thread(target=self._own_pty, name="soak-pty", daemon=True)
            self._pty_owner.start()
        deadline = time.monotonic() + 30.0
        while self.control_port is None or not self.link.is_symlink():
            if self.synth.poll() is not None:
                raise SoakAbort(f"synth exited with {self.synth.returncode} at startup")
            if time.monotonic() > deadline:
                raise SoakAbort("synth did not start within 30 s")
            time.sleep(0.02)

    # -- services ----------------------------------------------------------------------------
    def policy(self, role: str):
        import dataclasses

        pol = load_policy(UNITS[role], self.repo)
        over = {
            k: float(v) for k, v in self.sc.shim.items() if k in ("watchdog_sec", "restart_sec")
        }
        if over and self.scope == "system":
            self.findings.append(
                f"scenario shim overrides {over} ignored in system scope: the installed units' "
                "values apply (drop-ins override ExecStart only)"
            )
            over = {}
        if over:
            pol = dataclasses.replace(pol, **over, source=pol.source + " + scenario shim override")
        self.policies[role] = pol.to_dict()
        return pol

    def _production_ports(self) -> tuple[int, int]:
        """System scope: the core keeps the installed HTTP port (80: the tablet watches the soak)
        and the ingest -> core UDP port of the installed units."""
        assert isinstance(self.sup, sd.SystemdBackend)
        core = self._installed_argv("core")
        ingest = self._installed_argv("ingest")
        from jabuka.core.main import build_arg_parser as core_parser
        from jabuka.ingest.fastnet_main import build_arg_parser as ingest_parser

        a = core_parser().parse_args(core[1:])
        b = ingest_parser().parse_args(ingest[1:])
        if b.udp[1] != a.udp_port:
            raise SoakAbort(f"installed units disagree on the UDP port: {b.udp} vs {a.udp_port}")
        return int(a.http_port), int(a.udp_port)

    def _installed_argv(self, role: str) -> list[str]:
        import shlex

        assert isinstance(self.sup, sd.SystemdBackend)
        return shlex.split(sd.unit_execstart(self.sup.installed_unit_text(UNITS[role])))

    def _unit_file_sha256(self, unit: str) -> str:
        """System scope: sha256 of the installed unit file (FragmentPath, drop-ins excluded)."""
        assert isinstance(self.sup, sd.SystemdBackend)
        shown = self.sup._show_many([unit], ("FragmentPath",))
        path = (shown[0].get("FragmentPath") or "") if shown else ""
        if not path:
            raise rep.CodeIdentityError(f"{unit}: systemctl show gives no FragmentPath")
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError as exc:
            raise rep.CodeIdentityError(f"{unit}: cannot read {path}: {exc}") from exc

    def compute_code_identity(self) -> None:
        """Fill self.code (report "code") with the fingerprint of the jabuka package the services
        run, or self.code_error. System scope: the installed units' own venv (found statically
        from their ExecStart binary, nothing executed as root) plus the sha256 of each installed
        unit file; never the harness interpreter or the ~/jabuka copy (WR-03). Shim and user
        scope: the package the children's interpreter imports. Never raises."""
        try:
            units: dict[str, str] | None = None
            if self.scope == "system":
                core_bin = self._installed_argv("core")[0]
                ingest_bin = self._installed_argv("ingest")[0]
                a, b = Path(core_bin).parent.parent, Path(ingest_bin).parent.parent
                if a != b:
                    self.code_error = f"the units run from two venvs: {a} / {b}"
                    return
                pkg = rep.venv_package(core_bin)
                units = {u: self._unit_file_sha256(u) for u in UNITS.values()}
                python, source = None, "units"
            else:
                pkg = rep.locate_package(self.py)
                python, source = self.py, "children"
            self.code = rep.code_identity(pkg, python=python, source=source, units=units)
            self.code_error = None
        except (rep.CodeIdentityError, OSError, ValueError, sd.SetupError) as exc:
            self.code = None
            self.code_error = str(exc)

    def _system_argv(self, role: str) -> list[str]:
        return sd.soak_argv(
            role,
            self._installed_argv(role),
            soak_dir=self.soak_dir,
            pty_link=self.link,
            gpsd_port=self.gpsd_port,
        )

    def core_argv(self) -> list[str]:
        if self.scope == "system":
            return self._system_argv("core")
        clock = "gps" if self.sc.clock == "gps" else "sim"
        return [
            self.py,
            "-m",
            "jabuka.core.main",
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(self.http_port),
            "--udp-port",
            str(self.udp_port),
            "--data-dir",
            str(self.data_dir),
            "--racepack",
            str(self.pack_dir),
            "--clock",
            clock,
            "--gpsd",
            f"127.0.0.1:{self.gpsd_port}",
            "--log-level",
            "WARNING",
        ]

    def ingest_argv(self) -> list[str]:
        if self.scope == "system":
            return self._system_argv("ingest")
        return [
            self.py,
            "-m",
            "jabuka.ingest.fastnet_main",
            "--device",
            str(self.link),
            "--udp",
            f"127.0.0.1:{self.udp_port}",
            "--data-dir",
            str(self.data_dir),
        ]

    def prepare_system(self) -> None:
        """System scope: /var/lib/jabuka/soak-<ts>/ owned by the units' User= (inside their
        ReadWritePaths), never the production state files."""
        import grp
        import pwd

        assert isinstance(self.sup, sd.SystemdBackend)
        # the root harness must not be the OOM victim: SIGKILL skips its cleanup (WR-02). Its
        # small children (synth, fake gpsd, logcheck) inherit -900; the units keep their own
        # OOMScoreAdjust= from the installed unit files.
        self.oom_adj = sd.protect_from_oom()
        self.log("harness_oom", value=self.oom_adj)
        os.umask(0o022)
        sd.check_soak_dir(self.soak_dir)
        user = self.sup.unit_user(UNITS["core"]) or "root"
        pw = pwd.getpwnam(user)
        shown = self.sup._show_many([UNITS["core"]], ("Group",))
        group = (shown[0].get("Group") or None) if shown else None
        gid = grp.getgrnam(group).gr_gid if group else pw.pw_gid
        self.owner = (pw.pw_uid, gid)
        self.soak_dir.mkdir(mode=0o755, exist_ok=False)
        self.data_dir.mkdir(mode=0o755)
        for d in (self.soak_dir, self.data_dir):
            os.chown(d, *self.owner)
        self.rt_dir.mkdir(mode=0o755, exist_ok=True)
        self.log("soak_dir", path=str(self.soak_dir), user=user, uid=pw.pw_uid, gid=gid)

    def own_state(self, path: Path) -> None:
        """System scope: files the harness created or rewrote in the data dir belong to the
        units' user again (a root-owned stray .tmp would block the service's atomic writer)."""
        if self.owner is None:
            return
        p = inside(Path(path), self.state_root)
        for q in [p, *(p.iterdir() if p.is_dir() else [])]:
            if q.is_symlink() or q.name == "logs":
                continue
            with contextlib.suppress(OSError):
                if q.stat().st_uid != self.owner[0]:
                    os.chown(q, *self.owner)

    def _own_pty(self) -> None:
        """System scope: every pty slave the synth creates (start and each unplug reopen) is
        chowned to the ingest's User=, which opens it through the link.

        The kernel reuses the slave number after an unplug (the replug pty is often the same
        /dev/pts/N, root 0600 again), so the owner is checked on every pass, not only when the
        link target changes."""
        while not self._pty_stop.is_set():
            self._own_pty_once()
            self._pty_stop.wait(0.1)

    def _own_pty_once(self) -> None:
        try:
            target = os.path.realpath(self.link) if self.link.is_symlink() else None
        except OSError:
            target = None
        if not target or self.owner is None:
            return
        try:
            st = os.stat(target)
            if (st.st_uid, st.st_gid) == tuple(self.owner):
                self._pty_failed = None
                return
            os.chown(target, *self.owner)
            self._pty_failed = None
            self.log("pty_chown", path=target)
        except OSError as exc:
            if self._pty_failed != target:  # log once per target, retried every 0.1 s
                self._pty_failed = target
                self.log("pty_chown_failed", path=target, error=repr(exc))

    def mount_logs_tmpfs(self) -> None:
        logs = self.data_dir / "logs"
        if self.scope == "system":
            mode, size = self.logs_fs_mode, self.logs_fs_bytes
            if mode == "auto":
                mode = "tmpfs" if any(f.kind == "disk-full" for f in self.timeline) else "none"
            if mode == "tmpfs":  # main() refuses it first; never pin RAM on the Pi (WR-02)
                raise sd.SetupError(
                    system_logs_fs_error(self.args.logs_fs or self.sc.logs_fs, self.timeline)
                    or "--systemd system: a tmpfs log fs is refused, use --logs-fs loop:SIZE"
                )
            if mode == "none":
                logs.mkdir(exist_ok=True)
                if self.owner is not None:
                    os.chown(logs, *self.owner)
                return
            assert self.owner is not None and isinstance(self.sup, sd.SystemdBackend)
            inside(logs, self.state_root)
            self.sup.add_mount(logs)  # registered first: cleanup unmounts even a partial setup
            self.logs_fs_info = sd.mount_logs(
                logs,
                mode,
                size or 64 * 1024 * 1024,
                image_dir=self.soak_dir,
                uid=self.owner[0],
                gid=self.owner[1],
            )
            self.tmpfs = True
            self.log("logs_fs", **self.logs_fs_info)
            return
        logs.mkdir(parents=True, exist_ok=True)
        if self.logs_fs_mode == "none" or not self.args.in_userns:
            return
        size = self.logs_fs_bytes or 64 * 1024 * 1024
        inside(logs, self.run_dir)
        r = subprocess.run(
            ["mount", "-t", "tmpfs", "-o", f"size={size},mode=0755", "jabuka-soak", str(logs)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            self.findings.append(f"tmpfs mount failed: {r.stderr.strip()}")
            return
        self.tmpfs = True
        self.log("tmpfs", path=str(logs), bytes=size)

    def start_services(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sup.add("ingest", self.ingest_argv(), self.policy("ingest"))
        self.sup.add("core", self.core_argv(), self.policy("core"))
        self.sup.start_all()
        for role in ("ingest", "core"):
            if not self.sup.wait_ready(role, STARTUP_TIMEOUT_S):
                raise SoakAbort(f"{role} did not send READY=1 within {STARTUP_TIMEOUT_S:.0f} s")

    def apply_settings(self) -> None:
        st, cur = self.http("GET", "/api/settings")
        if st != 200 or not isinstance(cur, dict):
            raise SoakAbort(f"GET /api/settings -> {st}")
        # the race window spans the whole generated wind (1 h inside its end), as on race day: a
        # wind cube cut short (grib-gap) then leaves part of the window uncovered
        end = max(self.start_utc + self.duration, self.wind_end_utc() - 3600.0)
        patch = {
            "race_start_local": local_minutes(self.start_utc),
            "race_end_local": local_minutes(end, up=True),
            "route_level": "L0",
        }
        patch.update(self.sc.settings)
        st, out = self.http(
            "PUT", "/api/settings", {"base_version": cur["version"], "patch": patch}
        )
        if st != 200:
            raise SoakAbort(f"PUT /api/settings -> {st} {out}")
        if self.sc.course != "A":
            st, c = self.http("GET", "/api/course")
            st, out = self.http(
                "POST",
                "/api/course/select",
                {"template": self.sc.course, "base_version": c["version"]},
            )
            if st != 200:
                raise SoakAbort(f"POST /api/course/select -> {st} {out}")

    def wait_first(self) -> None:
        assert self.tablet is not None
        if self.preapplied:  # the run starts inside a fault: its own checks cover the start
            return
        t = self.tablet.wait_live(self.t0_wall, STARTUP_TIMEOUT_S)
        if t is None:
            raise SoakAbort("the tablet never saw live wind and position")
        self.log("first_live", after_s=round(t - self.t0_wall, 2))
        r = self.tablet.wait(lambda tb: tb.routes[:1], FIRST_ROUTE_TIMEOUT_S)
        if not r:
            block = self.tablet.route_block()
            raise SoakAbort(f"no route adopted within {FIRST_ROUTE_TIMEOUT_S:.0f} wall s: {block}")
        self.log(
            "first_route", version=r[0]["version"], after_s=round(r[0]["t_wall"] - self.t0_wall, 2)
        )

    # -- run ---------------------------------------------------------------------------------
    def wait_sim(self, t_sim: float) -> None:
        # once even when the run is behind schedule and the loop never runs (Pi soak
        # 20261110T220521Z: f66 and f67 started late, the course finished at sim 64215 s stayed
        # finished until f67, and f66's stay-toggle had no route to toggle)
        self.course_upkeep()
        while self.sim_now() < t_sim:
            self.poll_abort()
            self.course_upkeep()
            time.sleep(0.05)

    def course_upkeep(self) -> bool:
        """Course finished (the boat is back near Vodice): select the other template, so the
        closed loop keeps sailing for any duration. True when a template was selected.

        The tablet's last nav only prompts the check: GET /api/course must say finished too. A
        nav from before a template switch still says finished (Pi soak 20261110T220521Z f67:
        0.2 s after the fault selected B, this switched the fresh course B back to A)."""
        if self.tablet is None:
            return False
        now = time.time()
        if now - self._course_check < 1.0:
            return False
        self._course_check = now
        with self.tablet.lock:
            course = ((self.tablet.last_nav or {}).get("course")) or {}
        if not course.get("finished"):
            return False
        st, c = self.http("GET", "/api/course")
        if st != 200 or not c.get("finished"):
            return False
        other = "B" if c.get("template") == "A" else "A"
        st, _ = self.http(
            "POST", "/api/course/select", {"template": other, "base_version": c["version"]}
        )
        self.log("course_finished", template=c.get("template"), next=other, status=st)
        self.findings.append(
            f"course {c.get('template')} finished at sim {self.sim_now():.0f} s: {other} selected"
        )
        return st == 200

    def wind_kw(self) -> dict[str, float]:
        w, g = self.sc.wind, self.sc.grib
        return {
            "twd": float(w.get("twd", 161.0)),
            "tws_kn": float(w.get("tws_kn", 12.0)),
            "shift_deg_h": float(w.get("shift_deg_h", 0.0)),
            "tws_factor": float(g.get("tws_factor", 1.0)),
            "hours_before": float(g.get("hours_before", 2.0)),
        }

    def wind_end_utc(self) -> float:
        return self.start_utc + self.duration + self.sc.grib["hours_after"] * 3600.0

    def write_full_wind(self) -> None:
        from jabuka.soak.pack import write_wind

        # state_root, like every harness write into the stack's files: system scope keeps the pack
        # under /var/lib/jabuka/soak-<ts>, outside the run dir (Pi soak 20261110T153632Z grib-gap)
        write_wind(
            self.pack_dir, self.state_root, self.start_utc, self.wind_end_utc(), **self.wind_kw()
        )

    def preapply(self) -> None:
        """Synth faults scheduled at t=0 are switched on before the boot (the gpsclock leg: GPS
        time arriving late after boot)."""
        for spec in self.timeline:
            if spec.at <= 0 and spec.kind in SYNTH_KINDS:
                self.control(spec.kind, True)
                self.preapplied[spec.id] = time.time()
                self.log("fault_preapplied", id=spec.id, kind=spec.kind)

    def run_faults(self) -> None:
        settle = self.sc.budget("settle_s")
        for spec in self.timeline:
            fn = FAULTS.get(spec.kind)
            why = None
            if fn is None:
                why = "not implemented"
            elif spec.at > self.duration:  # a shortened run (--duration): smoke tests
                why = f"scheduled at {spec.at:g} sim s, {SKIP_AFTER_END} ({self.duration:g})"
            if why is not None:
                self.skipped.append({"kind": spec.kind, "id": spec.id, "reason": why})
                self.log("fault_skipped", id=spec.id, kind=spec.kind, reason=why)
                continue
            self.wait_sim(spec.at)
            self.log("fault_start", id=spec.id, kind=spec.kind, params=spec.params)
            try:
                rec = fn(self, spec)
            except SoakAbort:
                raise
            except Exception as exc:  # noqa: BLE001 - a harness bug fails this fault, not the run
                rec = {
                    "id": spec.id,
                    "kind": spec.kind,
                    "t_sim": round(self.sim_now(), 1),
                    "t_wall": time.time(),
                    "ok": False,
                    "notes": f"harness error: {exc!r}",
                }
            if "skip" in rec:
                self.skipped.append({"kind": spec.kind, "id": spec.id, "reason": rec["skip"]})
                self.log("fault_skipped", id=spec.id, kind=spec.kind, reason=rec["skip"])
                continue
            self.faults.append(rec)
            self.log("fault_end", **{k: v for k, v in rec.items() if k not in ("t_wall",)})
            self.poll_abort()
            time.sleep(settle)
        self.wait_sim(self.duration)

    def run(self) -> dict[str, Any]:
        """The main run, then the end of the run (shutdown, report, cleanup). The returned report
        comes with end_signals still holding SIGINT/SIGTERM/SIGHUP: the caller must call
        end_signals.release() once the report is written (run_soak does)."""
        try:
            if self.scope == "system":
                self.prepare_system()
            self.mount_logs_tmpfs()
            self.pack_dir.mkdir(parents=True, exist_ok=True)
            build_pack(
                self.pack_dir,
                self.state_root,
                self.fixtures,
                self.start_utc,
                self.wind_end_utc(),
                self.sc.wind,
                self.sc.grib,
            )
            self.start_synth()
            self.preapply()
            self.start_services()
            self.tablet = TabletClient(
                f"ws://127.0.0.1:{self.http_port}/ws", self.pack_dir / "landmask.npz"
            )
            self.tablet.start()
            self.sampler = probes.Sampler(
                self.run_dir / "samples.csv",
                self.probe_pids,
                self.sim_now,
                pi_probe=probes.pi_probe(),
            )
            self.sampler.start()
            self.apply_settings()
            self.wait_first()
            self.run_faults()
        except (SoakAbort, sd.SetupError) as exc:
            self.setup_error = str(exc)
            self.log("abort", error=str(exc))
        except BaseException:
            # a signal or a crash during the main run still aborts it with no report; the atexit
            # cleanup restores production
            self.shutdown()
            raise
        # review WR-02, plan 04-07: from here until run_soak has written and handed back the
        # report, SIGINT/SIGTERM/SIGHUP are held, never acted on
        self.end_signals.start()
        try:
            self.shutdown()
            try:
                report = self.build_report()
            finally:
                cleanup = self.sup.cleanup()  # system scope: production units restored
            if self.scope is not None:
                report["systemd"]["cleanup"] = cleanup
                reasons = cleanup_fail_reasons(self.scope, cleanup)
                if reasons:
                    report["verdict"] = "FAIL"
                    report.setdefault("fail_reasons", []).extend(reasons)
        except BaseException:
            self.end_signals.release()
            raise
        return report

    def probe_pids(self) -> dict[str, int | None]:
        core = self.sup.main_pid("core") if "core" in self.sup.services else None
        out: dict[str, int | None] = {
            "core": core,
            "ingest": self.sup.main_pid("ingest") if "ingest" in self.sup.services else None,
        }
        if core is not None:
            tree = probes.router_tree(core)
            out["forkserver"] = tree["forkserver"]
            out["worker"] = tree["workers"][0] if tree["workers"] else None
        return out

    def shutdown(self) -> None:
        if self.sampler is not None:
            self.sampler.stop()
            self.sampler.join(timeout=5)
        if self.tablet is not None:
            self.tablet.stop()
        self.sup.stop_all()
        if isinstance(self.sup, sd.SystemdBackend) and not getattr(self, "_journal", False):
            self._journal = True
            self.sup.dump_journal(self.run_dir / "proc", self.t0_wall - 1.0)
        if self.synth is not None and self.synth.poll() is None:
            self.synth.terminate()
            try:
                self.synth.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.synth.pid, signal.SIGKILL)
                self.synth.wait(timeout=5)
        if self.synth is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.synth.pid, signal.SIGKILL)
        if self._synth_reader is not None:
            self._synth_reader.join(timeout=5)
        self._pty_stop.set()
        if self._pty_owner is not None:
            self._pty_owner.join(timeout=5)
        if self.tablet is not None:
            self.tablet.join(timeout=5)

    # -- checks ------------------------------------------------------------------------------
    def run_logcheck(self, label: str) -> dict[str, Any]:
        from jabuka.tools.logcheck import check_dir

        logs = self.data_dir / "logs"
        res = check_dir(logs) if logs.is_dir() else None
        bad = [] if res is None else [f for f in res.files if not f.ok]
        out = {
            "label": label,
            "ok": bool(res.ok) if res is not None else None,
            "errors": [f"{f.path}: {e}" for f in bad for e in f.errors][:20],
        }
        if bad:  # keep the evidence: a tmpfs vanishes with the run's namespace
            keep = self.run_dir / "logcheck-failed" / label.replace(" ", "_")
            for f in bad[:5]:
                src = logs / f.path
                dst = inside(keep / f.path, self.run_dir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    shutil.copy2(src, dst)
        self.logcheck_runs.append(out)
        return out

    def fault_windows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": f.get("id"),
                "kind": f.get("kind"),
                "t_wall": f.get("t_wall"),
                "end_wall": f.get("end_wall"),
            }
            for f in self.faults
        ]

    def compute_checks(self) -> None:
        c = self.checks
        tb = self.tablet

        def recovery(kinds: tuple[str, ...]) -> dict:
            fs = [f for f in self.faults if f.get("kind") in kinds]
            if not fs:
                return rep.skipped("no such fault in this run")
            worst = max((f.get("recovery_s") or math.inf) for f in fs)
            ok = all(rep.fault_ok(f) for f in fs)
            return rep.check(ok, None if math.isinf(worst) else worst, None, f"{len(fs)} fault(s)")

        c["recovery_bus"] = recovery(("bus-silent", "garbage", "noise", "unplug"))
        c["recovery_gps"] = recovery(("gps-loss", "clock-jump"))
        c["recovery_process"] = recovery(
            ("kill-core", "kill-ingest", "kill-worker", "sigterm-storm", "watchdog-hang")
        )
        c["recovery_power"] = recovery(("power-pull",))
        routed = [f for f in self.faults if "route_s" in f]
        if routed:
            miss = [f["id"] for f in routed if f.get("route_s") is None]
            worst = max(
                (f["route_s"] for f in routed if f.get("route_s") is not None), default=None
            )
            c["route_after_recovery"] = rep.check(
                not miss, worst, self.sc.budget("route"), f"missing after {miss}" if miss else ""
            )
        else:
            c["route_after_recovery"] = rep.skipped("no restart in this run")
        if tb is not None and tb.routes:
            bad = [r for r in tb.routes if r.get("land_ok") is False]
            unchecked = [r for r in tb.routes if r.get("land_ok") is None]
            detail = f"{len(tb.routes)} adopted routes re-validated"
            if bad:
                detail += (
                    f"; crossing land: versions {[r['version'] for r in bad]} at segments "
                    + str([r["bad_index"] for r in bad])
                )
            if unchecked:
                detail += f"; {len(unchecked)} not checkable"
            grazes = [r["graze_m"] for r in tb.routes if r.get("graze_m")]
            if grazes:  # the published copy of a valid route touching the mask (6-decimal rounding)
                detail += (
                    f"; {len(grazes)} within the publication rounding (deepest {max(grazes):g} m)"
                )
            c["land"] = rep.check(not bad, len(tb.routes), 0, detail)
        else:
            c["land"] = rep.insufficient("no route adopted")
        if self.persistence:
            bad = [p for p in self.persistence if not p["ok"]]
            c["persistence"] = rep.check(
                not bad,
                len(self.persistence),
                None,
                "; ".join(f"{p['id']} ({p['corrupt'] or 'clean'}): {p['checks']}" for p in bad)
                or ", ".join(f"{p['id']} {p['corrupt'] or 'clean'}" for p in self.persistence),
            )
        else:
            c["persistence"] = rep.skipped("no power pull in this run")
        self.probe_checks()
        self.log_disk_check()
        final = self.run_logcheck("end")
        bad_runs = [r for r in self.logcheck_runs if r["ok"] is False]
        c["logcheck"] = rep.check(
            not bad_runs if final["ok"] is not None else None,
            len(self.logcheck_runs),
            None,
            "; ".join(f"{r['label']}: {r['errors'][:3]}" for r in bad_runs),
        )
        # tracebacks
        logs = sorted((self.run_dir / "proc").glob("*.log"))
        blocks = rep.scan_tracebacks(logs)
        expected_rules = rep.merge_expected(self.sc.expected_tracebacks)
        exp, unexp = rep.classify_tracebacks(
            blocks, self.fault_windows(), expected_rules, self.sc.budget("margin_s")
        )
        for e in exp:
            for f in self.faults:
                if f.get("id") == e["expected_by"]["fault"]:
                    f.setdefault("expected_tracebacks", []).append(e["text"].splitlines()[-1])
        self.unexpected_tracebacks = unexp
        detail = "; ".join(
            f"{u['file']}:{u['line']} {u['text'].splitlines()[-1]}" for u in unexp[:5]
        ) + (f" ({len(exp)} expected)" if exp else "")
        # review CR-01, plan 04-08: a truncated, failed or missing journal copy must never read
        # as "no traceback"; the verdict is FAIL (fail closed). The classification of the blocks
        # that were read is unchanged.
        jerr = journal_problem(self.sup)
        c["tracebacks"] = rep.check(
            False if jerr else not unexp,
            len(unexp),
            0,
            f"journal dump incomplete ({jerr}); {detail}" if jerr else detail,
        )
        if tb is not None:
            wins = self.fault_windows()
            margin = self.sc.budget("margin_s")
            outside = [
                i
                for i in tb.counter_increases
                if not any(
                    w["t_wall"] is not None
                    and w["t_wall"] <= i["t_wall"] <= (w["end_wall"] or w["t_wall"]) + margin
                    for w in wins
                )
            ]
            c["error_counters"] = rep.check(
                not outside,
                len(outside),
                0,
                "; ".join(f"{i['counter']}+{i['delta']}" for i in outside[:5]),
            )
            ratio = tb.tick_ratio()
            c["tick_ratio"] = (
                rep.check(
                    ratio >= self.sc.budget("tick_ratio"),
                    round(ratio, 3),
                    self.sc.budget("tick_ratio"),
                )
                if ratio is not None
                else rep.insufficient("no diag pairs")
            )

    def log_disk_check(self) -> None:
        """Log disk usage follows the retention budget (the core's own Retention.status())."""
        tb = self.tablet
        with tb.lock if tb is not None else contextlib.nullcontext():
            disk = (((tb.last_diag or {}).get("core") or {}).get("disk") or {}) if tb else {}
        if not disk or disk.get("budget_bytes") is None:
            self.checks["log_disk"] = rep.insufficient("no disk status in the last diag")
            return
        used = sum(int(v or 0) for v in (disk.get("used_bytes") or {}).values())
        budget = int(disk["budget_bytes"])
        state = disk.get("state")
        ok = used <= budget and state != "error"
        self.checks["log_disk"] = rep.check(
            ok,
            used,
            budget,
            f"state {state}, free {disk.get('free_bytes')} B, deleted {disk.get('deleted')},"
            f" reserve deletions {disk.get('reserve_deletions')}, errors {disk.get('errors')}",
        )

    def probe_checks(self) -> None:
        c = self.checks
        samples = list(self.sampler.samples) if self.sampler is not None else []
        if not samples:
            for name in (
                "rss_core",
                "rss_worker",
                "leak_slope",
                "fd_growth",
                "thread_growth",
                "cpu_per_sim_s",
            ):
                c[name] = rep.insufficient("no /proc samples")
            return
        b = self.sc.budget
        c["rss_core"] = probes.max_rss_check(samples, "core", b("rss_core_mb"))
        c["rss_worker"] = probes.max_rss_check(samples, "worker", b("rss_worker_mb"))
        leak = probes.leak_check(
            samples,
            "core",
            budget_mb_36h=b("leak_mb_36h"),
            min_segment_s=b("min_segment_s"),
            warmup_s=b("warmup_s"),
        )
        worker = probes.leak_check(
            samples,
            "worker",
            budget_mb_36h=b("leak_mb_36h"),
            min_segment_s=b("min_segment_s"),
            warmup_s=b("warmup_s"),
        )
        leak["worker"] = worker
        if worker["ok"] is False:
            leak["ok"] = False
            leak["detail"] += f"; worker slope {worker['value']} MB/36 h"
        c["leak_slope"] = leak
        warm = b("warmup_s")
        c["fd_growth"] = probes.growth_check(
            samples, ("core", "ingest"), "fds", b("fd_growth"), warm
        )
        c["thread_growth"] = probes.growth_check(
            samples, ("core", "ingest"), "threads", b("thread_growth"), warm
        )
        c["cpu_per_sim_s"] = probes.cpu_check(samples, "core", b("cpu_per_sim_s"))

    def build_report(self) -> dict[str, Any]:
        try:
            self.compute_checks()
        except Exception as exc:  # noqa: BLE001 - a report must always be written
            self.findings.append(f"check computation failed: {exc!r}")
            self.setup_error = self.setup_error or f"check computation failed: {exc!r}"
        for name in rep.CHECK_NAMES:
            self.checks.setdefault(name, rep.skipped("not measured by this harness version"))
        wall = time.time() - self.t0_wall
        sim = self.sim_now()
        overrides = {k: v for k, v in self.sc.shim.items() if k != "why"}
        report: dict[str, Any] = {
            "schema": rep.SCHEMA,
            "verdict": None,
            "scenario": self.sc.name,
            # what ran, judged by freeze-check F3/F4 against race-36h.json at HEAD (plan 04-07)
            "scenario_source": self.sc.source,
            "scenario_sha256": self.sc.sha256,
            "duration_s": self.duration,
            "scenario_duration_s": self.sc.duration_s,
            "mode": self.sup.mode,
            "host": rep.host_info(),
            "git": self.git if self.git is not None else rep.git_info(self.repo),
            "code": self.code,
            "code_error": self.code_error,
            "speed_target": self.speed,
            "speed_achieved": round(sim / wall, 2) if wall > 0 else None,
            "sim_s": round(sim, 1),
            "wall_s": round(wall, 1),
            "started_utc": self.started_utc,
            "t0_wall": self.t0_wall,
            "seed": self.seed,
            "sim_start_utc": datetime.fromtimestamp(self.start_utc, UTC).isoformat(),
            "budgets": {k: self.sc.budget(k) for k in rep_budget_keys()},
            "shim": {
                "policies": self.policies,
                "overrides": overrides,
                "why": self.sc.shim.get("why"),
            },
            "logs_fs": {
                "mode": self.logs_fs_mode,
                "tmpfs": self.tmpfs,
                "bytes": self.logs_fs_bytes,
                "mounted": self.logs_fs_info,
            },
            "timeline": [s.to_dict() for s in self.timeline],
            "faults": self.faults,
            "checks": {k: self.checks[k] for k in rep.CHECK_NAMES}
            | {k: v for k, v in self.checks.items() if k not in rep.CHECK_NAMES},
            "skipped": self.skipped,
            "findings": self.findings,
            "logcheck_runs": self.logcheck_runs,
            "unexpected_tracebacks": getattr(self, "unexpected_tracebacks", []),
            "process_events": self.sup.events,
            "routes": self.tablet.routes if self.tablet is not None else [],
            "alerts_seen": self.tablet.alerts_seen if self.tablet is not None else {},
            "tablet": self.tablet.summary(self.t0_wall) if self.tablet is not None else None,
            "setup_error": self.setup_error,
            # run_soak sets it, just before write_report, to the first SIGINT/SIGTERM/SIGHUP held
            # at the end of the run; freeze-check F3/F4 refuse a non-null value (plan 04-08,
            # gap 07-5)
            "end_signal": None,
        }
        if self.scope is not None:
            report["systemd"] = self.sup.info()
            if self.scope == "system":
                report["systemd"]["soak_dir"] = str(self.soak_dir)
                report["systemd"]["harness_oom_score_adj"] = self.oom_adj
        pi = probes.pi_summary(list(self.sampler.samples) if self.sampler is not None else [])
        if pi is not None:
            report["pi"] = pi
        rep.finalize(report)
        with self._tl_lock:
            self._tl.close()
        return report


def rep_budget_keys() -> list[str]:
    from jabuka.soak.scenario import DEFAULT_BUDGETS

    return list(DEFAULT_BUDGETS)


# -- CLI ---------------------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-soak",
        description="Accelerated soak of the Jabuka stack with scripted faults (dev/bench tool).",
        epilog="Exit 0 PASS, 1 FAIL, 2 usage/setup error.",
    )
    p.add_argument("--scenario", default="ci", help="packaged name (ci, tracer, ...) or a path")
    p.add_argument("--speed", type=float, default=None, help="sim seconds per wall second")
    p.add_argument("--duration", type=float, default=None, metavar="SIM_S")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", type=Path, default=Path("var/soak"), help="default var/soak")
    p.add_argument(
        "--logs-fs",
        default=None,
        help="auto | tmpfs:SIZE | none | loop:SIZE (--systemd system only, max 1G) "
        "(default: scenario)",
    )
    p.add_argument("--fixtures", type=Path, default=None, help="default <repo>/tests/fixtures")
    p.add_argument("--python", default=None, help="interpreter for the children (default: this)")
    p.add_argument("--keep", action="store_true", help="keep data/ and racepack/ after a PASS")
    p.add_argument(
        "--systemd",
        choices=sd.SCOPES,
        default=None,
        help="run the core and the ingest as systemd units: user (transient user units, laptop) "
        "or system (the installed units through /run drop-ins, Pi, root)",
    )
    p.add_argument(
        "--systemd-cleanup",
        action="store_true",
        help="system scope: remove stale soak drop-ins and mounts, restart the production units, "
        "exit (0 when `systemctl cat jabuka-core` holds no 50-jabuka-soak line)",
    )
    p.add_argument("--in-userns", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--run-dir", type=Path, default=None, help=argparse.SUPPRESS)
    return p


def system_logs_fs_error(logs_fs: str, timeline: list[FaultSpec]) -> str | None:
    """--systemd system: the refusal message when the log fs would be a RAM tmpfs (explicit,
    the scenario's default such as race-36h's tmpfs:256M, or auto with a disk-full fault), else
    None. On the 1 GB Pi a tmpfs filled by disk-full pins RAM next to the root harness (WR-02)."""
    mode, _ = parse_logs_fs(logs_fs)
    if mode == "auto":
        mode = "tmpfs" if any(f.kind == "disk-full" for f in timeline) else "none"
    if mode != "tmpfs":
        return None
    return (
        "--systemd system: a tmpfs log fs pins RAM on the 1 GB Pi (scenario/flag gives "
        f"{logs_fs}): pass --logs-fs loop:SIZE (e.g. loop:512M) or --logs-fs none "
        "(disk-full then SKIPPED)"
    )


def journal_problem(sup: Any) -> str | None:
    """Why the units' journal copy cannot be trusted (systemd backend), else None. The shim pipes
    the process output itself, so it is never concerned (plan 04-08, review CR-01)."""
    if not isinstance(sup, sd.SystemdBackend):
        return None
    journal = sup.journal
    if journal is None:
        return "journal not copied"
    if journal.get("complete") is True:
        return None
    return journal.get("error") or "journal copy incomplete"


def cleanup_fail_reasons(scope: str | None, cleanup: dict[str, Any]) -> list[str]:
    """Why the systemd cleanup FAILs the soak verdict (plan 04-06, review WR-01): 50-jabuka-soak
    lines left, or (system scope) production units not active after the restart."""
    if scope is None:
        return []
    reasons = []
    left = cleanup.get("soak_lines_left")
    if left:
        reasons.append(f"systemd cleanup: {left} 50-jabuka-soak line(s) left in systemctl cat")
    if scope == "system" and cleanup.get("restarted") is not True:
        reasons.append(
            "systemd cleanup: production units not active after restart "
            f"({cleanup.get('active')}, rc {cleanup.get('restart_rc')}): sudo bash scripts/soak.sh "
            "--systemd system --systemd-cleanup, then systemctl is-active jabuka-core "
            "jabuka-ingest-fastnet"
        )
    return reasons


PI_F4_COMMAND = (
    "sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python "
    "--scenario race-36h --speed 20 --logs-fs loop:512M"
)


def run_length_messages(sc: Scenario, duration: float) -> list[str]:
    """The start WARNING of a shortened run (--duration below the scenario's): freeze-check F3/F4
    will not count its report (plan 04-07)."""
    if duration >= sc.duration_s:
        return []
    return [
        f"jabuka-soak: WARNING: shortened run (--duration {duration:g} < scenario "
        f"{sc.duration_s:g} sim s): faults after the end are SKIPPED and freeze-check F3/F4 will "
        "not count this report (essai raccourci); run quick tests with --out var/soak-essais "
        "(docs/SOAK.md)"
    ]


def identity_messages(
    scope: str | None,
    code: dict[str, Any] | None,
    code_error: str | None,
    git: dict[str, Any],
    *,
    machine: str | None = None,
) -> list[str]:
    """The stderr lines that announce what code this run certifies (04-VERIFICATION gap 1).
    System scope without a package fingerprint raises sd.SetupError: freeze-check F4 could never
    count such a 2-4 h Pi run. Elsewhere, no fingerprint and no git head gives a WARNING block.
    On the Pi (machine aarch64) a run that is not `--systemd system` gets a WARNING: F4 will not
    count it (plan 04-06)."""
    lines = _identity_lines(scope, code, code_error, git)
    if machine == "aarch64" and scope != "system":
        kind = "--systemd user" if scope == "user" else "shim"
        lines.append(
            f"jabuka-soak: WARNING: on the Pi, freeze-check F4 only counts `{PI_F4_COMMAND}`; "
            f"this {kind} run will not count (docs/SOAK.md)"
        )
    return lines


def _identity_lines(
    scope: str | None, code: dict[str, Any] | None, code_error: str | None, git: dict[str, Any]
) -> list[str]:
    head = (git or {}).get("head")
    shown_head = str(head)[:12] if head else "none"
    if code is None:
        if scope == "system":
            raise sd.SetupError(
                "--systemd system: cannot fingerprint the jabuka package the installed units run "
                f"({code_error}); freeze-check F4 could not count this run: reinstall with "
                "`sudo deploy/provision.sh` and retry"
            )
        if head is None:
            return [
                "jabuka-soak: WARNING: this run cannot be identified: no package fingerprint "
                f"({code_error}) and no git checkout",
                "jabuka-soak: WARNING: freeze-check F3/F4 will refuse this report "
                "(no code.sha256, git.head null)",
                "jabuka-soak: WARNING: run it from a checkout, or with a --python that imports "
                "jabuka",
            ]
        return [f"jabuka-soak: code none ({code_error}); git {shown_head}"]
    lines = [
        f"jabuka-soak: code {str(code.get('sha256'))[:12]} ({code.get('files')} files, "
        f"{code.get('package_dir')}, source {code.get('source')}); git {shown_head}"
    ]
    if head is None:
        lines.append(
            "jabuka-soak: note: no git checkout here: the report is identified by this package "
            "fingerprint (freeze-check F3/F4 compare it with src/jabuka at HEAD)"
        )
    return lines


def _needs_namespace(sc: Scenario, logs_fs: str, timeline: list[FaultSpec]) -> bool:
    mode, _ = parse_logs_fs(logs_fs)
    if mode == "loop":
        return False
    if mode == "tmpfs":
        return True
    return mode == "auto" and any(f.kind == "disk-full" for f in timeline)


def make_run_dir(out: Path, name: str) -> Path:
    out = out.resolve()
    if out == REFUSED_OUT or REFUSED_OUT in out.parents:
        raise ValueError(f"refusing --out under {REFUSED_OUT} (live data)")
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run = out / f"{ts}-{name}"
    out.mkdir(parents=True, exist_ok=True)
    run.mkdir(exist_ok=False)  # must not pre-exist
    return run


_ACTIVE: list[Harness] = []


def _cleanup() -> None:
    for h in list(_ACTIVE):
        with contextlib.suppress(Exception):
            h.shutdown()
        with contextlib.suppress(Exception):
            h.sup.cleanup()


def _give_back(run_dir: Path) -> None:
    """Under sudo: the run dir in the checkout belongs to the invoking user again (scp, rm)."""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if os.geteuid() != 0 or not uid or not gid:
        return
    for p in [run_dir, *run_dir.rglob("*")]:
        with contextlib.suppress(OSError):
            os.chown(p, int(uid), int(gid), follow_symlinks=False)


def _preflight(scope: str) -> None:
    sd.SystemdBackend(scope, run_dir=Path("."), monitor=False).preflight()


def _on_signal(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)


def run_soak(args: argparse.Namespace, sc: Scenario) -> int:
    if args.run_dir is not None:
        run_dir = Path(args.run_dir).resolve()
        if not run_dir.is_dir() or any(run_dir.iterdir()):
            print(f"jabuka-soak: run dir {run_dir} must exist empty", file=sys.stderr)
            return 2
    else:
        try:
            run_dir = make_run_dir(Path(args.out), sc.name)
        except (ValueError, OSError) as exc:
            print(f"jabuka-soak: {exc}", file=sys.stderr)
            return 2
    if args.fixtures is None:
        repo = checkout()
        args.fixtures = (repo / "tests" / "fixtures") if repo else Path("tests/fixtures")
    try:
        h = Harness(run_dir, sc, args)
    except (SoakAbort, sd.SetupError) as exc:
        print(f"jabuka-soak: {exc}", file=sys.stderr)
        return 2
    if (
        args.systemd is None
        and not args.in_userns
        and any(f.kind == "disk-full" for f in h.timeline)
    ):
        h.findings.append("disk-full: no user namespace on this host, the fault is SKIPPED")
    h.compute_code_identity()
    h.git = rep.git_info(h.repo)  # the identity printed now is the one reported
    try:
        lines = identity_messages(h.scope, h.code, h.code_error, h.git, machine=platform.machine())
    except sd.SetupError as exc:
        # nothing touched yet: Harness() only read the units (systemctl cat/show), and neither
        # _ACTIVE nor atexit has seen this harness
        print(f"jabuka-soak: {exc}", file=sys.stderr, flush=True)
        with contextlib.suppress(Exception):
            h._tl.close()
        shutil.rmtree(run_dir, ignore_errors=True)
        return 2
    for line in [*lines, *run_length_messages(sc, h.duration)]:
        print(line, file=sys.stderr, flush=True)
    _ACTIVE.append(h)
    print(f"jabuka-soak: {sc.name} -> {run_dir}", flush=True)
    try:
        try:
            report = h.run()
        finally:
            _ACTIVE.remove(h)
        end = h.end_signals.signal
        if end is None:
            end = getattr(h.sup, "pending_signal", None)
        report["end_signal"] = int(end) if end is not None else None  # plan 04-08
        jpath, mpath = rep.write_report(run_dir, report)
        if report["verdict"] == "PASS" and not args.keep:
            for d in ("racepack",):
                shutil.rmtree(run_dir / d, ignore_errors=True)
        _give_back(run_dir)
    finally:
        held = h.end_signals.release()  # plan 04-07: held since the end of the main run
    with contextlib.suppress(OSError, ValueError):  # SSH gone: stdout may be a dead pipe
        print(f"jabuka-soak: report {mpath}", flush=True)
        print(f"jabuka-soak: verdict {report['verdict']}", flush=True)
        for r in report.get("fail_reasons", []):
            print(f"jabuka-soak:   {r}", flush=True)
    # held back at the end of the run or during the cleanup (review WR-02): the report first
    sig = held if held is not None else getattr(h.sup, "pending_signal", None)
    if sig is not None:
        with contextlib.suppress(OSError, ValueError):
            print(
                f"jabuka-soak: signal {int(sig)} received at the end of the run: report "
                f"written, exiting {128 + int(sig)}",
                file=sys.stderr,
                flush=True,
            )
        return 128 + int(sig)
    return 0 if report["verdict"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    if args.systemd_cleanup:
        if args.systemd not in (None, "system"):
            print("jabuka-soak: --systemd-cleanup is for the system scope", file=sys.stderr)
            return 2
        try:
            left = sd.cleanup_system()
        except sd.CleanupIncomplete as exc:
            print(f"jabuka-soak: {exc}", file=sys.stderr)
            return 1
        except sd.SetupError as exc:
            print(f"jabuka-soak: {exc}", file=sys.stderr)
            return 2
        return 0 if left == 0 else 1
    try:
        sc = load_scenario(args.scenario)
        logs_fs = args.logs_fs or sc.logs_fs
        lmode, _ = parse_logs_fs(logs_fs)
        timeline = compile_timeline(sc, args.seed)
    except ValueError as exc:
        print(f"jabuka-soak: {exc}", file=sys.stderr)
        return 2
    if args.systemd == "system":  # a pure usage error, reported first for any user (WR-02)
        err = system_logs_fs_error(logs_fs, timeline)
        if err is not None:
            print(f"jabuka-soak: {err}", file=sys.stderr)
            return 2
    if args.systemd == "system" and os.geteuid() != 0:
        print(f"jabuka-soak: {sd.SUDO_HINT}", file=sys.stderr)
        return 2
    if lmode == "loop" and args.systemd != "system":
        print("jabuka-soak: --logs-fs loop:SIZE is for --systemd system", file=sys.stderr)
        return 2
    if args.systemd is not None:
        try:
            _preflight(args.systemd)
        except sd.SetupError as exc:
            print(f"jabuka-soak: {exc}", file=sys.stderr)
            return 2
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGHUP, _on_signal)
    atexit.register(_cleanup)
    if (
        args.systemd is None
        and not args.in_userns
        and _needs_namespace(sc, logs_fs, timeline)
        and sys.platform == "linux"
        and userns_available()
    ):
        # re-exec under a user + mount namespace: root only inside it, for one tmpfs mount
        try:
            run_dir = make_run_dir(Path(args.out), sc.name)
        except (ValueError, OSError) as exc:
            print(f"jabuka-soak: {exc}", file=sys.stderr)
            return 2
        cmd = [
            shutil.which("unshare") or "unshare",
            "--user",
            "--map-root-user",
            "--mount",
            "--propagation",
            "private",
            sys.executable,
            "-m",
            "jabuka.tools.soak",
            *argv,
            "--in-userns",
            "--run-dir",
            str(run_dir),
        ]
        speed = float(args.speed or sc.speed)
        dur = float(args.duration or sc.duration_s)
        timeout = dur / speed * 4.0 + 900.0
        child = subprocess.Popen(cmd)
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
            print("jabuka-soak: the namespaced run exceeded its wall budget", file=sys.stderr)
            return 1
        except (KeyboardInterrupt, SystemExit):
            child.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=30)
            raise
    return run_soak(args, sc)


if __name__ == "__main__":
    sys.exit(main())
