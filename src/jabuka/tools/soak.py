"""jabuka-soak: run the real Jabuka stack under SimClock at ~60x, inject a seeded fault schedule,
check recovery through a WebSocket "tablet" and /proc probes, write a JSON + Markdown report.

    python -m jabuka.tools.soak --scenario ci [--speed X] [--duration SIM_S] [--seed N]
        [--out DIR] [--logs-fs auto|tmpfs:SIZE|none] [--fixtures DIR] [--python EXE] [--keep]

Exit 0 PASS, 1 FAIL, 2 usage/setup error. The run dir is <out>/<UTC ts>-<scenario>/ (created
here, never pre-existing; an --out under /var/lib/jabuka is refused): report.json, report.md,
samples.csv, timeline.jsonl, proc/<role>-<n>.log, data/ (core + ingest data dir), racepack/.

Processes (each spawned as [python, -m, module]): the synthetic X35 (jabuka.sim.synth, pty mode,
fake gpsd, steering on the core's own targets), the receive-only ingest on that pty and the core
(with its forkserver router worker), both under the supervisor shim (jabuka.soak.supervisor).

With logs_fs tmpfs (or auto when the scenario has a disk-full fault) the harness re-executes
itself under ``unshare --user --map-root-user --mount`` to mount a size-limited tmpfs on
data/logs; without a user namespace the disk-full fault is SKIPPED, never run on the real disk.
Dev / bench tool: never part of a systemd unit; it may read the wall clock.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import math
import os
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

from jabuka.soak import report as rep
from jabuka.soak.faults import FAULTS
from jabuka.soak.pack import build_pack, inside
from jabuka.soak.scenario import FaultSpec, Scenario, compile_timeline, load_scenario, parse_logs_fs
from jabuka.soak.supervisor import UNITS, Supervisor, load_policy, repo_root
from jabuka.soak.tablet import TabletClient

REFUSED_OUT = Path("/var/lib/jabuka")
LOCAL_TZ = "Europe/Zagreb"
STARTUP_TIMEOUT_S = 60.0
FIRST_ROUTE_TIMEOUT_S = 120.0


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
        self.repo = repo_root()
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
        self.sup: Supervisor = Supervisor(run_dir, on_event=self._on_sup_event)
        self.tablet: TabletClient | None = None  # type: ignore[assignment]
        self.synth: subprocess.Popen | None = None
        self._synth_reader: threading.Thread | None = None
        self._progress: tuple[float, float] | None = None  # (sim t, wall)
        self._tl_lock = threading.Lock()
        self._tl = open(run_dir / "timeline.jsonl", "a", encoding="utf-8")  # noqa: SIM115
        self.t0_wall = time.time()
        self.wall_budget = self.duration / self.speed * 4.0 + 600.0
        self.faults: list[dict[str, Any]] = []
        self.skipped: list[dict[str, str]] = []
        self.findings: list[str] = []
        self.checks: dict[str, dict] = {}
        self.logs_fs_mode, self.logs_fs_bytes = parse_logs_fs(args.logs_fs or sc.logs_fs)
        self.tmpfs = False
        self.policies: dict[str, Any] = {}
        self.setup_error: str | None = None
        self.logcheck_runs: list[dict[str, Any]] = []
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
        with open(self.run_dir / "proc" / "synth.log", "a", encoding="utf-8") as f:
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
        if over:
            pol = dataclasses.replace(pol, **over, source=pol.source + " + scenario shim override")
        self.policies[role] = pol.to_dict()
        return pol

    def core_argv(self) -> list[str]:
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

    def mount_logs_tmpfs(self) -> None:
        logs = self.data_dir / "logs"
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
        end = self.start_utc + self.duration + 3600.0
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
        t = self.tablet.wait_live(self.t0_wall, STARTUP_TIMEOUT_S)
        if t is None:
            raise SoakAbort("the tablet never saw live wind and position")
        self.log("first_live", after_s=round(t - self.t0_wall, 2))
        r = self.tablet.wait(lambda tb: tb.routes[:1], FIRST_ROUTE_TIMEOUT_S)
        if not r:
            block = self.tablet.route_block()
            raise SoakAbort(f"no route adopted within {FIRST_ROUTE_TIMEOUT_S:.0f} s: {block}")
        self.log(
            "first_route", version=r[0]["version"], after_s=round(r[0]["t_wall"] - self.t0_wall, 2)
        )

    # -- run ---------------------------------------------------------------------------------
    def wait_sim(self, t_sim: float) -> None:
        while self.sim_now() < t_sim:
            self.poll_abort()
            time.sleep(0.05)

    def run_faults(self) -> None:
        settle = self.sc.budget("settle_s")
        for spec in self.timeline:
            fn = FAULTS.get(spec.kind)
            if fn is None:
                self.skipped.append({"kind": spec.kind, "id": spec.id, "reason": "not implemented"})
                self.log("fault_skipped", id=spec.id, kind=spec.kind, reason="not implemented")
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
            self.faults.append(rec)
            self.log("fault_end", **{k: v for k, v in rec.items() if k not in ("t_wall",)})
            self.poll_abort()
            time.sleep(settle)
        self.wait_sim(self.duration)

    def run(self) -> dict[str, Any]:
        try:
            self.mount_logs_tmpfs()
            self.pack_dir.mkdir(parents=True, exist_ok=True)
            build_pack(
                self.pack_dir,
                self.run_dir,
                self.fixtures,
                self.start_utc,
                self.start_utc + self.duration + self.sc.grib["hours_after"] * 3600.0,
                self.sc.wind,
                self.sc.grib,
            )
            self.start_synth()
            self.start_services()
            self.tablet = TabletClient(
                f"ws://127.0.0.1:{self.http_port}/ws", self.pack_dir / "landmask.npz"
            )
            self.tablet.start()
            self.apply_settings()
            self.wait_first()
            self.run_faults()
        except SoakAbort as exc:
            self.setup_error = str(exc)
            self.log("abort", error=str(exc))
        finally:
            self.shutdown()
        return self.build_report()

    def shutdown(self) -> None:
        if self.tablet is not None:
            self.tablet.stop()
        self.sup.stop_all()
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
        if self.tablet is not None:
            self.tablet.join(timeout=5)

    # -- checks ------------------------------------------------------------------------------
    def run_logcheck(self, label: str) -> dict[str, Any]:
        from jabuka.tools.logcheck import check_dir

        logs = self.data_dir / "logs"
        res = check_dir(logs) if logs.is_dir() else None
        out = {
            "label": label,
            "ok": bool(res.ok) if res is not None else None,
            "errors": []
            if res is None
            else [e for f in res.files for e in getattr(f, "errors", [])][:20],
        }
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
            c["land"] = rep.check(not bad, len(tb.routes), 0, detail)
        else:
            c["land"] = rep.insufficient("no route adopted")
        if "persistence" not in c:
            c["persistence"] = rep.skipped("no power pull in this run")
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
        c["tracebacks"] = rep.check(
            not unexp,
            len(unexp),
            0,
            "; ".join(f"{u['file']}:{u['line']} {u['text'].splitlines()[-1]}" for u in unexp[:5])
            + (f" ({len(exp)} expected)" if exp else ""),
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
            "mode": "shim",
            "host": rep.host_info(),
            "git": rep.git_info(self.repo),
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
            "setup_error": self.setup_error,
        }
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
    p.add_argument("--logs-fs", default=None, help="auto | tmpfs:SIZE | none (default: scenario)")
    p.add_argument("--fixtures", type=Path, default=None, help="default <repo>/tests/fixtures")
    p.add_argument("--python", default=None, help="interpreter for the children (default: this)")
    p.add_argument("--keep", action="store_true", help="keep data/ and racepack/ after a PASS")
    p.add_argument("--in-userns", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--run-dir", type=Path, default=None, help=argparse.SUPPRESS)
    return p


def _needs_namespace(sc: Scenario, logs_fs: str, timeline: list[FaultSpec]) -> bool:
    mode, _ = parse_logs_fs(logs_fs)
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
        repo = repo_root()
        args.fixtures = (repo / "tests" / "fixtures") if repo else Path("tests/fixtures")
    h = Harness(run_dir, sc, args)
    if not args.in_userns and any(f.kind == "disk-full" for f in h.timeline):
        h.findings.append("disk-full: no user namespace on this host, the fault is SKIPPED")
    _ACTIVE.append(h)
    print(f"jabuka-soak: {sc.name} -> {run_dir}", flush=True)
    try:
        report = h.run()
    finally:
        _ACTIVE.remove(h)
    jpath, mpath = rep.write_report(run_dir, report)
    if report["verdict"] == "PASS" and not args.keep:
        for d in ("racepack",):
            shutil.rmtree(run_dir / d, ignore_errors=True)
    print(f"jabuka-soak: report {mpath}", flush=True)
    print(f"jabuka-soak: verdict {report['verdict']}", flush=True)
    for r in report.get("fail_reasons", []):
        print(f"jabuka-soak:   {r}", flush=True)
    return 0 if report["verdict"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    try:
        sc = load_scenario(args.scenario)
        logs_fs = args.logs_fs or sc.logs_fs
        parse_logs_fs(logs_fs)
        timeline = compile_timeline(sc, args.seed)
    except ValueError as exc:
        print(f"jabuka-soak: {exc}", file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, _on_signal)
    atexit.register(_cleanup)
    if (
        not args.in_userns
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
