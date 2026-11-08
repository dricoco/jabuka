"""The soak's systemd backend (plan 04-03): system scope (Pi, installed units + volatile /run
drop-ins) rendered, verified and always cleaned up; user scope (laptop, transient units) driven
end to end against the real user manager."""

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
import sys
import textwrap
import time
from pathlib import Path

import pytest

from jabuka.core.main import build_arg_parser as core_parser
from jabuka.ingest.fastnet_main import build_arg_parser as ingest_parser
from jabuka.soak import systemd as sd
from jabuka.soak.scenario import load_scenario
from jabuka.soak.supervisor import Policy
from jabuka.tools import soak

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "systemd"
CORE = "jabuka-core.service"
INGEST = "jabuka-ingest-fastnet.service"
SOAK_DIR = Path("/var/lib/jabuka/soak-20261107T120000Z")
PTY = Path("/run/jabuka-soak/fastnet-pty")
SYSTEMD_ANALYZE = "/usr/bin/systemd-analyze"
BAD = re.compile(r"Unknown key|Unknown section|Unknown lvalue|Failed to parse|Invalid")


def _units() -> dict[str, str]:
    return {u: (DEPLOY / u).read_text(encoding="utf-8") for u in (CORE, INGEST)}


def _render() -> dict[str, str]:
    return sd.render_dropins(
        scope="system", units=_units(), soak_dir=SOAK_DIR, pty_link=PTY, gpsd_port=29470
    )


def _execstart(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    assert lines[0] == "[Service]"
    assert lines[1] == "ExecStart="  # resets the shipped ExecStart
    assert lines[2].startswith("ExecStart=")
    assert len(lines) == 3, f"the drop-in must override ExecStart only: {lines}"
    return shlex.split(lines[2].partition("=")[2])


# -- rendering ---------------------------------------------------------------------------------
def test_dropins_override_execstart_only_and_parse_with_the_real_parsers() -> None:
    d = _render()
    assert set(d) == {CORE, INGEST}
    core = _execstart(d[CORE])
    shipped = shlex.split(sd.unit_execstart(_units()[CORE]))
    assert core[0] == shipped[0] == "/opt/jabuka/venv/bin/jabuka-core"
    a = core_parser().parse_args(core[1:])
    assert str(a.data_dir).startswith("/var/lib/jabuka/soak-")
    assert str(a.racepack).startswith(str(SOAK_DIR))
    assert a.clock == "sim"
    assert a.gpsd is not None and a.gpsd[1] != 2947
    # the tablet watches the soak live on the AP, as in production
    assert a.http_host == "0.0.0.0" and a.http_port == 80

    ing = _execstart(d[INGEST])
    assert ing[0] == "/opt/jabuka/venv/bin/jabuka-ingest-fastnet"
    b = ingest_parser().parse_args(ing[1:])
    assert b.device == str(PTY)
    assert str(b.data_dir) == str(a.data_dir)
    assert b.udp == ("127.0.0.1", a.udp_port)


def test_render_refuses_a_data_dir_outside_the_soak_dir_and_the_real_gpsd_port() -> None:
    with pytest.raises(ValueError, match="soak-"):
        sd.render_dropins(
            scope="system",
            units=_units(),
            soak_dir=Path("/var/lib/jabuka"),
            pty_link=PTY,
            gpsd_port=29470,
        )
    with pytest.raises(ValueError, match="2947"):
        sd.render_dropins(
            scope="system", units=_units(), soak_dir=SOAK_DIR, pty_link=PTY, gpsd_port=2947
        )
    with pytest.raises(ValueError, match="user"):
        sd.render_dropins(
            scope="user", units=_units(), soak_dir=SOAK_DIR, pty_link=PTY, gpsd_port=29470
        )


def test_unit_execstart_follows_reset_lines() -> None:
    text = "[Service]\nExecStart=/a x\n# /run/x.d/y.conf\n[Service]\nExecStart=\nExecStart=/b y\n"
    assert sd.unit_execstart(text) == "/b y"


def _verify(tmp_path: Path, dropins: dict[str, str]) -> str:
    venv_bin = str(Path(sys.executable).parent) + "/"
    for name in (CORE, INGEST):
        text = (DEPLOY / name).read_text().replace("/opt/jabuka/venv/bin/", venv_bin)
        (tmp_path / name).write_text(text)
        dd = tmp_path / f"{name}.d"
        dd.mkdir()
        (dd / sd.DROPIN_NAME).write_text(dropins[name].replace("/opt/jabuka/venv/bin/", venv_bin))
    proc = subprocess.run(
        [SYSTEMD_ANALYZE, "verify", "--man=no", *(str(tmp_path / n) for n in (CORE, INGEST))],
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = proc.stdout + proc.stderr
    return "\n".join(
        ln for ln in out.splitlines() if str(tmp_path) in ln or CORE in ln or INGEST in ln
    )


@pytest.mark.skipif(not Path(SYSTEMD_ANALYZE).exists(), reason="systemd-analyze not installed")
def test_dropins_pass_systemd_analyze_verify(tmp_path: Path) -> None:
    ours = _verify(tmp_path, _render())
    assert not [ln for ln in ours.splitlines() if BAD.search(ln)], ours


@pytest.mark.skipif(not Path(SYSTEMD_ANALYZE).exists(), reason="systemd-analyze not installed")
def test_verify_reads_the_dropins(tmp_path: Path) -> None:
    """The check above would catch a broken drop-in (so it really loads them)."""
    bad = {u: t + "Restartz=always\n" for u, t in _render().items()}
    ours = _verify(tmp_path, bad)
    assert [ln for ln in ours.splitlines() if BAD.search(ln)], ours


# -- fake systemctl ----------------------------------------------------------------------------
FAKE = """\
#!{py}
import json, os, sys
with open(os.environ["FAKE_SYSTEMD_LOG"], "a") as f:
    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\\n")
args = [a for a in sys.argv[1:] if a != "--user"]
if args and args[0] == "show":
    props, units, value = [], [], "--value" in args
    it = iter(args[1:])
    for a in it:
        if a == "-p":
            props += next(it).split(",")
        elif a.startswith("--property="):
            props += a.split("=", 1)[1].split(",")
        elif not a.startswith("-"):
            units.append(a)
    vals = {{"MainPID": os.environ.get("FAKE_MAINPID", "4242"), "NRestarts": "0",
             "ActiveState": os.environ.get("FAKE_ACTIVE", "active"), "SubState": "running",
             "LoadState": "loaded",
             "InvocationID": "abc", "Id": "x"}}
    for i, u in enumerate(units or ["-"]):
        if i:
            print()
        for p in props:
            print(vals.get(p, "") if value else f"{{p}}={{vals.get(p, '')}}")
elif args and args[0] == "cat":
    unit = args[1]
    path = os.path.join(os.environ["FAKE_UNITS"], unit)
    if not os.path.exists(path):
        print(f"No files found for {{unit}}.", file=sys.stderr)
        sys.exit(1)
    print(f"# {{path}}")
    print(open(path).read())
sys.exit(0)
"""


@pytest.fixture
def fake_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    b = tmp_path / "bin"
    b.mkdir()
    for name in ("systemctl", "systemd-run", "journalctl"):
        p = b / name
        p.write_text(FAKE.format(py=sys.executable))
        p.chmod(0o755)
    units = tmp_path / "units"
    units.mkdir()
    for u in (CORE, INGEST):
        shutil.copy(DEPLOY / u, units / u)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SYSTEMD_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_UNITS", str(units))
    return b


def _calls(tmp_path: Path) -> list[list[str]]:
    p = tmp_path / "calls.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines()]


def _ctl(tmp_path: Path, verb: str) -> list[list[str]]:
    return [c for c in _calls(tmp_path) if c[0] == "systemctl" and verb in c[1:3]]


def _system(tmp_path: Path, **kw) -> sd.SystemdBackend:
    b = sd.SystemdBackend(
        "system",
        run_dir=tmp_path / "run",
        dropin_root=tmp_path / "run-systemd",
        assume_root=True,
        monitor=False,
        **kw,
    )
    for role in ("ingest", "core"):
        b.add(role, ["/opt/jabuka/venv/bin/x", "--y"], Policy())
    return b


def test_kill_core_is_a_systemctl_kill_of_the_main_pid(tmp_path: Path, fake_bin: Path) -> None:
    b = _system(tmp_path)
    pid = b.kill("core", signal.SIGKILL)
    assert pid == 4242
    kills = _ctl(tmp_path, "kill")
    assert kills[-1][1:] == ["kill", "--signal=SIGKILL", "--kill-whom=main", CORE]


def test_power_pull_is_kill_all_then_stop_then_start(tmp_path: Path, fake_bin: Path) -> None:
    b = _system(tmp_path)
    seen: list[str] = []

    def between(pids: list[int]) -> None:
        seen.append("between")
        (tmp_path / "calls.jsonl").open("a").write(json.dumps(["between"]) + "\n")

    b.power_pull(between)
    seq = [
        c[1] if c[0] == "systemctl" else c[0]
        for c in _calls(tmp_path)
        if c[0] == "between" or (c[0] == "systemctl" and c[1] in ("kill", "stop", "start"))
    ]
    assert seq == ["kill", "stop", "between", "start"], seq
    kill = _ctl(tmp_path, "kill")[0]
    assert "--signal=SIGKILL" in kill and "--kill-whom=all" in kill
    assert {CORE, INGEST} <= set(kill)
    assert {CORE, INGEST} <= set(_ctl(tmp_path, "stop")[0])
    assert {CORE, INGEST} <= set(_ctl(tmp_path, "start")[0])


def test_cleanup_runs_when_the_run_raises(tmp_path: Path, fake_bin: Path) -> None:
    b = _system(tmp_path)
    dropins = _render()
    with pytest.raises(RuntimeError, match="boom"), b.session(dropins):
        for u in (CORE, INGEST):
            assert (tmp_path / "run-systemd" / f"{u}.d" / sd.DROPIN_NAME).is_file()
        raise RuntimeError("boom")
    for u in (CORE, INGEST):
        assert not (tmp_path / "run-systemd" / f"{u}.d" / sd.DROPIN_NAME).exists()
    calls = _calls(tmp_path)
    verbs = [c[1] for c in calls if c[0] == "systemctl"]
    # drop-ins written -> reload -> restart on the soak config; cleanup: reload -> restart
    assert verbs.count("daemon-reload") == 2
    last_reload = len(verbs) - 1 - verbs[::-1].index("daemon-reload")
    restarts = [i for i, v in enumerate(verbs) if v == "restart"]
    assert restarts and restarts[-1] > last_reload
    assert {CORE, INGEST} <= set(_ctl(tmp_path, "restart")[-1])
    assert b.cleaned
    b.cleanup()  # idempotent
    assert [c[1] for c in _calls(tmp_path) if c[0] == "systemctl"].count("daemon-reload") == 2


def test_stale_dropin_and_missing_units_are_refused(tmp_path: Path, fake_bin: Path) -> None:
    b = _system(tmp_path)
    b.preflight()  # the fake knows both units
    stale = tmp_path / "run-systemd" / f"{CORE}.d" / sd.DROPIN_NAME
    stale.parent.mkdir(parents=True)
    stale.write_text("[Service]\n")
    with pytest.raises(sd.SetupError, match="--systemd-cleanup"):
        b.preflight()
    stale.unlink()
    (tmp_path / "units" / CORE).unlink()
    with pytest.raises(sd.SetupError, match="not installed"):
        b.preflight()


def test_systemd_cleanup_alone_removes_stale_dropins(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_unmount(tmp_path, monkeypatch)  # never the real /proc/mounts and umount (IN-06)
    stale = tmp_path / "run-systemd" / f"{INGEST}.d" / sd.DROPIN_NAME
    stale.parent.mkdir(parents=True)
    stale.write_text("[Service]\n")
    n = sd.cleanup_system(
        dropin_root=tmp_path / "run-systemd", assume_root=True, proc_mounts=tmp_path / "mounts"
    )
    assert n == 0  # 50-jabuka-soak lines left in `systemctl cat jabuka-core`
    assert not stale.exists()
    assert {CORE, INGEST} <= set(_ctl(tmp_path, "restart")[-1])


def test_harness_never_takes_the_production_core_for_the_soak_one(
    tmp_path: Path, fake_bin: Path
) -> None:
    """T-04-03-02: before talking to port 80 the harness checks the unit's main process runs the
    soak argv (data dir, pty, sim clock), so it never configures the production core; the
    drop-in restart is blocking (not --no-block)."""
    b = sd.SystemdBackend(
        "system", run_dir=tmp_path, dropin_root=tmp_path / "rs", assume_root=True, monitor=False
    )
    shipped = shlex.split(sd.unit_execstart(_units()[CORE]))
    soak_argv = sd.soak_argv("core", shipped, soak_dir=SOAK_DIR, pty_link=PTY, gpsd_port=29470)
    b.add("core", soak_argv, Policy())
    proc = tmp_path / "proc"
    for pid, argv in ((10, ["/opt/jabuka/venv/bin/python3", *shipped]), (11, ["py", *soak_argv])):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    assert not b.runs_soak_argv("core", 10, proc)
    assert b.runs_soak_argv("core", 11, proc)
    assert not b.runs_soak_argv("core", 12, proc)
    b.add("ingest", ["/x", "--y"], Policy())
    b.install({CORE: sd.dropin_text(soak_argv)})
    restart = _ctl(tmp_path, "restart")[-1]
    assert "--no-block" not in restart and {CORE, INGEST} <= set(restart)
    b.cleanup()


def test_system_scope_without_root_is_a_setup_error(tmp_path: Path) -> None:
    b = sd.SystemdBackend("system", run_dir=tmp_path, assume_root=False, monitor=False)
    with pytest.raises(sd.SetupError, match="sudo"):
        b.preflight()


@pytest.mark.skipif(os.geteuid() == 0, reason="the non-root refusal needs a non-root user")
def test_cli_system_scope_without_root_exits_2_with_a_sudo_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = soak.main(["--systemd", "system", "--scenario", "tracer", "--out", str(tmp_path)])
    assert rc == 2
    assert "sudo" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())  # refused before any run dir


def test_user_scope_transient_unit_copies_the_shipped_policy(
    tmp_path: Path, fake_bin: Path
) -> None:
    b = sd.SystemdBackend("user", run_dir=tmp_path / "run", monitor=False, tag="t1")
    pol = Policy("always", 2.0, 30.0, "deploy/systemd/jabuka-core.service")
    b.add("core", [sys.executable, "-m", "jabuka.core.main", "--x"], pol, {"A": "1"})
    b.start("core")
    run = [c for c in _calls(tmp_path) if c[0] == "systemd-run"][-1]
    assert "--user" in run and "--collect" in run
    assert "--unit=jabuka-soak-t1-core" in run
    for prop in ("Type=notify", "Restart=always", "RestartSec=2", "WatchdogSec=30"):
        assert prop in run, prop
    assert run[run.index("--") + 1 :] == [sys.executable, "-m", "jabuka.core.main", "--x"]
    b.kill("core", signal.SIGKILL)
    assert _ctl(tmp_path, "kill")[-1][1:] == [
        "--user",
        "kill",
        "--signal=SIGKILL",
        "--kill-whom=main",
        "jabuka-soak-t1-core.service",
    ]


# -- Pi metrics --------------------------------------------------------------------------------
def test_vcgencmd_parsing() -> None:
    from jabuka.soak import probes

    assert probes.parse_temp("temp=48.3'C\n") == 48.3
    assert probes.parse_throttled("throttled=0x50005\n") == 0x50005
    assert probes.throttled_flags(0x50005) == [
        "under-voltage now",
        "throttled now",
        "under-voltage occurred",
        "throttled occurred",
    ]
    assert probes.parse_temp("garbage") is None


# -- end to end, user scope --------------------------------------------------------------------
def _user_manager() -> str | None:
    exe = shutil.which("systemctl")
    if exe is None or sys.platform != "linux":
        return "no systemctl"
    try:
        r = subprocess.run(
            [exe, "--user", "is-system-running"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"systemctl --user failed: {exc}"
    state = r.stdout.strip()
    return None if state in ("running", "degraded") else f"user manager is {state or 'absent'}"


def _soak_units() -> list[str]:
    r = subprocess.run(
        ["systemctl", "--user", "list-units", "--all", "--no-legend", "jabuka-soak-*"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


@pytest.mark.soak
def test_user_scope_tracer_end_to_end(tmp_path: Path) -> None:
    why = _user_manager()
    if why is not None:
        pytest.skip(why)
    before = _soak_units()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "jabuka.tools.soak",
            "--systemd",
            "user",
            "--scenario",
            "tracer",
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=REPO,
    )
    out = proc.stdout + proc.stderr
    reports = list(tmp_path.glob("*-tracer/report.json"))
    assert reports, out
    rep = json.loads(reports[0].read_text())
    assert proc.returncode == 0, textwrap.shorten(json.dumps(rep.get("fail_reasons")) + out, 4000)
    assert rep["mode"] == "systemd"
    assert rep["systemd"]["scope"] == "user"
    # systemd itself restarted the killed core
    assert rep["systemd"]["n_restarts"]["core"] >= 1
    assert _soak_units() == before
    assert rep["systemd"]["journal"]["complete"] is True, rep["systemd"]["journal"]
    assert rep["end_signal"] is None, rep["end_signal"]


# -- plan 04-04: WR-01 cleanup order / retry / deferred signals, WR-02 no tmpfs, OOM ------------
def _fake_unmount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never the real umount (review IN-06): record it in the fake systemctl call log."""

    def unmount(path: Path) -> bool:
        with (tmp_path / "calls.jsonl").open("a") as f:
            f.write(json.dumps(["umount", str(path)]) + "\n")
        return True

    monkeypatch.setattr(sd, "unmount", unmount)


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sd.SystemdBackend:
    _fake_unmount(tmp_path, monkeypatch)
    b = _system(tmp_path)
    b.add_mount(tmp_path / "soak" / "data" / "logs")
    b.install(_render())
    atexit.unregister(b.cleanup)
    return b


def _verbs_since(tmp_path: Path, n: int) -> list[str]:
    out = []
    for c in _calls(tmp_path)[n:]:
        if c[0] == "umount":
            out.append("umount")
        elif c[0] == "systemctl" and c[1] in ("daemon-reload", "restart"):
            out.append(c[1])
    return out


def test_system_cleanup_restarts_the_units_before_unmounting(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _installed(tmp_path, monkeypatch)
    n = len(_calls(tmp_path))
    report = b.cleanup()
    verbs = _verbs_since(tmp_path, n)
    assert verbs == ["daemon-reload", "restart", "umount"], verbs
    assert verbs.index("restart") < verbs.index("umount")
    assert {CORE, INGEST} <= set(_ctl(tmp_path, "restart")[-1])
    assert report["restarted"] is True and report["soak_lines_left"] == 0
    assert b.cleaned


def test_interrupted_system_cleanup_is_retried(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _installed(tmp_path, monkeypatch)
    real = b._ctl
    fired: list[str] = []

    def ctl(*args: str, timeout: float = 60.0):
        if args and args[0] == "restart" and not fired:
            fired.append("restart")
            raise KeyboardInterrupt  # a second Ctrl-C while the units are being restarted
        return real(*args, timeout=timeout)

    monkeypatch.setattr(b, "_ctl", ctl)
    with pytest.raises(KeyboardInterrupt):
        b.cleanup()
    assert b.cleaned is False
    for u in (CORE, INGEST):
        assert not (tmp_path / "run-systemd" / f"{u}.d" / sd.DROPIN_NAME).exists()
    n = len(_calls(tmp_path))
    report = b.cleanup()  # atexit / --systemd-cleanup: the critical steps run again
    verbs = _verbs_since(tmp_path, n)
    assert "daemon-reload" in verbs and "restart" in verbs, verbs
    assert verbs.index("restart") < verbs.index("umount")
    assert b.cleaned is True and report["soak_lines_left"] == 0
    n = len(_calls(tmp_path))
    assert b.cleanup() is report  # idempotent once done
    assert len(_calls(tmp_path)) == n


def test_signal_during_system_cleanup_is_deferred_until_the_units_restart(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _installed(tmp_path, monkeypatch)
    real = b._ctl
    fired: list[int] = []

    def ctl(*args: str, timeout: float = 60.0):
        if args and args[0] == "daemon-reload" and not fired:
            fired.append(len(_calls(tmp_path)))
            os.kill(os.getpid(), signal.SIGHUP)  # the SSH session drops mid-cleanup
        return real(*args, timeout=timeout)

    monkeypatch.setattr(b, "_ctl", ctl)
    prev = signal.signal(signal.SIGHUP, soak._on_signal)
    try:
        report = b.cleanup()  # plan 04-06 (WR-02): recorded, honoured by run_soak after the report
        assert report["restarted"] is True and b.pending_signal == signal.SIGHUP
        after = _verbs_since(tmp_path, fired[0])
        assert after[:3] == ["daemon-reload", "restart", "umount"], after
        assert b.cleaned is True
        assert signal.getsignal(signal.SIGHUP) is soak._on_signal
    finally:
        signal.signal(signal.SIGHUP, prev)


# -- plan 04-06: WR-01 restart verified, WR-02 signal honoured after the report ----------------
def test_failed_restart_keeps_the_system_cleanup_retryable(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(sd, "RESTART_VERIFY_S", 0.0)
    monkeypatch.setenv("FAKE_ACTIVE", "failed")
    n = len(_calls(tmp_path))
    report = b.cleanup()
    assert report["restarted"] is False, report
    assert report["active"] == {INGEST: "failed", CORE: "failed"}, report
    assert b.cleaned is False
    for u in (CORE, INGEST):
        assert not (tmp_path / "run-systemd" / f"{u}.d" / sd.DROPIN_NAME).exists()
    verbs = _verbs_since(tmp_path, n)
    assert "restart" in verbs and verbs.index("restart") < verbs.index("umount"), verbs
    monkeypatch.setenv("FAKE_ACTIVE", "active")
    n = len(_calls(tmp_path))
    report = b.cleanup()  # atexit / --systemd-cleanup: redone in full
    verbs = _verbs_since(tmp_path, n)
    assert "daemon-reload" in verbs and "restart" in verbs, verbs
    assert report["restarted"] is True and b.cleaned is True, report
    n = len(_calls(tmp_path))
    b.cleanup()
    assert len(_calls(tmp_path)) == n  # done: no new systemctl verb


def test_restart_rc_failure_is_not_a_restart(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(sd, "RESTART_VERIFY_S", 0.0)
    real = b._ctl

    def ctl(*args: str, timeout: float = 60.0):
        if args and args[0] == "restart":
            return subprocess.CompletedProcess(["systemctl", *args], 1, "", "Job failed")
        return real(*args, timeout=timeout)

    monkeypatch.setattr(b, "_ctl", ctl)
    report = b.cleanup()
    assert report["restarted"] is False and report["restart_rc"] == 1, report
    assert report["active"] == {INGEST: "active", CORE: "active"}, report
    assert b.cleaned is False


def test_cleanup_fail_reasons() -> None:
    assert soak.cleanup_fail_reasons("system", {"restarted": True, "soak_lines_left": 0}) == []
    down = {
        "restarted": False,
        "restart_rc": 1,
        "active": {INGEST: "failed", CORE: "active"},
        "soak_lines_left": 0,
    }
    reasons = soak.cleanup_fail_reasons("system", down)
    assert len(reasons) == 1, reasons
    assert "--systemd-cleanup" in reasons[0] and "not active" in reasons[0], reasons
    reasons = soak.cleanup_fail_reasons("system", {"restarted": True, "soak_lines_left": 2})
    assert len(reasons) == 1 and "50-jabuka-soak" in reasons[0], reasons
    assert soak.cleanup_fail_reasons("user", {"scope": "user", "units": []}) == []
    assert soak.cleanup_fail_reasons(None, {}) == []


def test_systemd_cleanup_cli_exits_1_when_the_units_stay_down(
    tmp_path: Path,
    fake_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_unmount(tmp_path, monkeypatch)
    monkeypatch.setattr(sd, "RESTART_VERIFY_S", 0.0)
    monkeypatch.setenv("FAKE_ACTIVE", "failed")
    with pytest.raises(sd.CleanupIncomplete, match="systemctl status"):
        sd.cleanup_system(
            dropin_root=tmp_path / "run-systemd", assume_root=True, proc_mounts=tmp_path / "mounts"
        )

    def incomplete(**_kw: object) -> int:
        raise sd.CleanupIncomplete("x")

    monkeypatch.setattr(sd, "cleanup_system", incomplete)
    assert soak.main(["--systemd-cleanup"]) == 1
    assert "jabuka-soak: x" in capsys.readouterr().err


def test_systemctl_children_get_their_own_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal Ctrl-C reaches only the harness (which defers it during cleanup), never a
    `systemctl restart` client halfway (review WR-01)."""
    seen: list[dict[str, object]] = []

    def run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess:
        seen.append(kw)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sd.subprocess, "run", run)
    b = sd.SystemdBackend(
        "system", run_dir=tmp_path, dropin_root=tmp_path / "rs", assume_root=True, monitor=False
    )
    b._ctl("show", "x")
    assert seen and seen[-1].get("start_new_session") is True, seen


def test_run_soak_writes_the_report_before_honouring_a_deferred_signal(
    tmp_path: Path,
    fake_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_path / "site-packages" / "jabuka"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")

    def identity(self: soak.Harness) -> None:
        self.code = soak.rep.code_identity(
            pkg, python=None, source="units", units={CORE: "0" * 64, INGEST: "0" * 64}
        )
        self.code_error = None

    def run(self: soak.Harness) -> dict:
        self.sup.pending_signal = signal.SIGHUP  # a SIGHUP held back during the cleanup
        return {"verdict": "PASS", "fail_reasons": []}

    def write_report(run_dir: Path, report: dict) -> tuple[Path, Path]:
        jpath, mpath = run_dir / "report.json", run_dir / "report.md"
        jpath.write_text(json.dumps(report), encoding="utf-8")
        mpath.write_text("# report\n", encoding="utf-8")
        return jpath, mpath

    monkeypatch.setattr(soak.Harness, "compute_code_identity", identity)
    monkeypatch.setattr(soak.Harness, "run", run)
    monkeypatch.setattr(soak.rep, "write_report", write_report)
    out = tmp_path / "out"
    args = soak.build_arg_parser().parse_args(
        ["--systemd", "system", "--scenario", "tracer", "--out", str(out)]
    )
    assert soak.run_soak(args, load_scenario("tracer")) == 128 + signal.SIGHUP
    reports = list(out.glob("*-tracer/report.json"))
    assert len(reports) == 1, reports
    assert json.loads(reports[0].read_text(encoding="utf-8"))["verdict"] == "PASS"
    assert "report written" in capsys.readouterr().err


def test_protect_from_oom(tmp_path: Path) -> None:
    p = tmp_path / "oom_score_adj"
    p.write_text("0\n")
    assert sd.protect_from_oom(p) == -900
    assert p.read_text().strip() == "-900"
    assert sd.protect_from_oom(tmp_path / "missing" / "oom_score_adj") is None


def test_system_scope_refuses_a_tmpfs_log_fs() -> None:
    from jabuka.soak.scenario import compile_timeline, load_scenario

    race = load_scenario("race-36h")
    timeline = compile_timeline(race, None)
    assert any(f.kind == "disk-full" for f in timeline)
    for logs_fs in ("tmpfs:256M", race.logs_fs):
        assert "loop:" in (soak.system_logs_fs_error(logs_fs, []) or ""), logs_fs
    assert "loop:" in (soak.system_logs_fs_error("auto", timeline) or "")
    for ok in ("loop:512M", "none"):
        assert soak.system_logs_fs_error(ok, timeline) is None, ok
    assert soak.system_logs_fs_error("auto", []) is None


def test_cli_system_scope_refuses_tmpfs_before_the_root_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["--systemd", "system", "--scenario", "race-36h", "--out", str(tmp_path)]
    assert soak.main(base) == 2
    err = capsys.readouterr().err
    assert "loop:" in err and "sudo" not in err, err
    assert soak.main([*base, "--logs-fs", "tmpfs:64M"]) == 2
    assert "loop:" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
    if os.geteuid() != 0:
        assert soak.main([*base, "--logs-fs", "loop:512M"]) == 2
        assert "sudo" in capsys.readouterr().err  # past the tmpfs check, at the root check
        assert not list(tmp_path.iterdir())


# -- the end of a soak is never cut short by a signal (plan 04-07, review WR-02) -----------------
def test_signal_hold_records_and_restores() -> None:
    prev = {s: signal.signal(s, soak._on_signal) for s in (signal.SIGHUP, signal.SIGTERM)}
    try:
        hold = sd.SignalHold().start()
        signal.raise_signal(signal.SIGHUP)  # held: no SystemExit
        assert hold.start() is hold  # already active: keeps the first signal
        signal.raise_signal(signal.SIGTERM)
        assert hold.release() == signal.SIGHUP
        assert signal.getsignal(signal.SIGHUP) is soak._on_signal
        assert signal.getsignal(signal.SIGTERM) is soak._on_signal
        assert hold.release() == signal.SIGHUP  # idempotent
        assert signal.getsignal(signal.SIGHUP) is soak._on_signal
        assert sd.SignalHold().release() is None  # never started
        with sd.SignalHold() as held:
            signal.raise_signal(signal.SIGHUP)
        assert held.signal == signal.SIGHUP
        assert signal.getsignal(signal.SIGHUP) is soak._on_signal
    finally:
        for s, handler in prev.items():
            signal.signal(s, handler)


def test_signal_at_the_end_of_the_run_is_held_until_the_report_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real Harness.run end path (shim scope): a SIGHUP raised during shutdown() is held,
    the report is still built and returned, and the caller releases the hold."""
    out = tmp_path / "out"
    args = soak.build_arg_parser().parse_args(["--scenario", "tracer", "--out", str(out)])
    args.fixtures = tmp_path
    h = soak.Harness(soak.make_run_dir(out, "tracer"), load_scenario("tracer"), args)

    def stop_here(self: soak.Harness) -> None:
        raise soak.SoakAbort("stop here")

    real_shutdown = soak.Harness.shutdown
    fired: list[int] = []

    def shutdown(self: soak.Harness) -> None:
        if not fired:
            fired.append(1)
            signal.raise_signal(signal.SIGHUP)  # the SSH session drops at the end of the run
        real_shutdown(self)

    monkeypatch.setattr(soak.Harness, "mount_logs_tmpfs", stop_here)
    monkeypatch.setattr(soak.Harness, "shutdown", shutdown)
    prev = signal.signal(signal.SIGHUP, soak._on_signal)
    try:
        report = h.run()
        assert fired
        assert "stop here" in (report.get("setup_error") or ""), report.get("setup_error")
        assert h.end_signals.release() == signal.SIGHUP
        assert signal.getsignal(signal.SIGHUP) is soak._on_signal
    finally:
        hold = getattr(h, "end_signals", None)
        if hold is not None:
            hold.release()
        signal.signal(signal.SIGHUP, prev)
        h._tl.close()


def test_run_soak_honours_a_signal_held_at_the_end_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pkg = tmp_path / "site-packages" / "jabuka"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")

    def identity(self: soak.Harness) -> None:
        self.code = soak.rep.code_identity(pkg, python=None, source="children")
        self.code_error = None

    def run(self: soak.Harness) -> dict:
        self.end_signals.start()  # what the real Harness.run does after the main run
        signal.raise_signal(signal.SIGHUP)
        return {"verdict": "PASS", "fail_reasons": []}

    def write_report(run_dir: Path, report: dict) -> tuple[Path, Path]:
        jpath, mpath = run_dir / "report.json", run_dir / "report.md"
        jpath.write_text(json.dumps(report), encoding="utf-8")
        mpath.write_text("# report\n", encoding="utf-8")
        return jpath, mpath

    monkeypatch.setattr(soak.Harness, "compute_code_identity", identity)
    monkeypatch.setattr(soak.Harness, "run", run)
    monkeypatch.setattr(soak.rep, "write_report", write_report)
    out = tmp_path / "out"
    args = soak.build_arg_parser().parse_args(["--scenario", "tracer", "--out", str(out)])
    prev = signal.signal(signal.SIGHUP, soak._on_signal)
    try:
        assert soak.run_soak(args, load_scenario("tracer")) == 128 + signal.SIGHUP
        reports = list(out.glob("*-tracer/report.json"))
        assert len(reports) == 1, reports
        assert json.loads(reports[0].read_text(encoding="utf-8"))["verdict"] == "PASS"
        assert "report written" in capsys.readouterr().err
        assert signal.getsignal(signal.SIGHUP) is soak._on_signal
    finally:
        signal.signal(signal.SIGHUP, prev)


# -- the end-of-run journal copy is whole or FAILs (plan 04-08, review CR-01) -------------------
def _entry(unit: str, msg: str, ts: int) -> str:
    return json.dumps({"_SYSTEMD_UNIT": unit, "MESSAGE": msg, "__REALTIME_TIMESTAMP": str(ts)})


def _fake_journalctl(path: Path, body: str) -> str:
    """A bash fake journalctl; ``body`` is the script after the shebang."""
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return str(path)


def _say(*lines: str) -> str:
    return "".join(f"printf '%s\\n' {shlex.quote(ln)}\n" for ln in lines)


_GROUP_SIGINT_DRIVER = """\
import json, os, signal, sys, threading, time
from pathlib import Path

from jabuka.soak import report as rep
from jabuka.soak import systemd as sd
from jabuka.soak.supervisor import Policy

fake, out = sys.argv[1], Path(sys.argv[2])
b = sd.SystemdBackend(
    "system", run_dir=out, journalctl=fake, monitor=False, assume_root=True,
    dropin_root=out / "run-systemd",
)
b.add("core", ["x"], Policy())
hold = sd.SignalHold().start()


def fire():
    time.sleep(0.5)
    os.killpg(os.getpgrp(), signal.SIGINT)  # the terminal Ctrl-C: the whole foreground group


threading.Thread(target=fire, daemon=True).start()
b.dump_journal(out / "proc", 0)
held = hold.release()
core = out / "proc" / "core-journal.log"
print(json.dumps({
    "held": held,
    "journal": getattr(b, "journal", None),
    "blocks": len(rep.scan_tracebacks(sorted((out / "proc").glob("*.log")))),
    "text": core.read_text() if core.exists() else "",
}))
"""


def test_group_sigint_during_the_journal_copy_keeps_the_whole_journal(tmp_path: Path) -> None:
    """The verifier's cr01 repro made permanent: a Ctrl-C held by the harness at the end of a
    system-scope soak must not kill journalctl halfway (review CR-01, gap 07-5)."""
    fake = _fake_journalctl(
        tmp_path / "fake-journalctl",
        _say(_entry(CORE, "started", 1000000))
        + "sleep 2\n"
        + _say(
            _entry(CORE, "Traceback (most recent call last):", 2000000),
            _entry(CORE, '  File "x.py", line 1, in <module>', 2000001),
            _entry(CORE, "RuntimeError: boom", 2000002),
        ),
    )
    driver = tmp_path / "driver.py"
    driver.write_text(_GROUP_SIGINT_DRIVER)
    out = tmp_path / "out"
    out.mkdir()
    # the driver leads its own session: its killpg never reaches pytest's process group
    r = subprocess.run(
        [sys.executable, str(driver), fake, str(out)],
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["held"] == signal.SIGINT, res
    assert res["journal"] is not None and res["journal"]["complete"] is True, res
    assert res["journal"]["entries"]["core"] == 4, res
    assert "RuntimeError: boom" in res["text"], res
    assert res["blocks"] == 1, res


def test_a_failed_journal_copy_is_recorded_never_silent(
    tmp_path: Path, fake_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both = _say(_entry(CORE, "a", 1000000), _entry(INGEST, "b", 1000001))
    proc = tmp_path / "proc"

    def system(name: str, body: str) -> sd.SystemdBackend:
        return _system(tmp_path / name, journalctl=_fake_journalctl(tmp_path / name, body))

    # (a) journalctl exits 1 with a message on stderr
    b = system("rc1", both + "echo boom >&2\nexit 1\n")
    files = b.dump_journal(proc / "a", 0)
    assert b.journal["complete"] is False, b.journal
    assert b.journal["error"].startswith("journalctl rc 1:") and "boom" in b.journal["error"]
    assert sorted(p.name for p in files) == ["core-journal.log", "ingest-journal.log"]
    assert all(p.exists() for p in files)
    # (b) journalctl killed by a signal (SIGKILL: a background gate may ignore SIGINT)
    b = system("killed", _say(_entry(CORE, "a", 1000000)) + "kill -KILL $$\n")
    b.dump_journal(proc / "b", 0)
    assert b.journal["complete"] is False and "rc -9" in b.journal["error"], b.journal
    # (c) journalctl outlasts the timeout (exec: the kill on timeout leaves no orphan)
    monkeypatch.setattr(sd, "JOURNAL_TIMEOUT_S", 1.0)
    b = system("slow", _say(_entry(CORE, "a", 1000000)) + "exec sleep 10\n")
    t0 = time.monotonic()
    b.dump_journal(proc / "c", 0)
    assert time.monotonic() - t0 < 8
    assert b.journal["complete"] is False, b.journal
    assert "timed out after 1 s" in b.journal["error"], b.journal
    monkeypatch.undo()
    # (d) no journalctl at all
    b = _system(tmp_path / "missing-dir", journalctl=str(tmp_path / "missing"))
    assert b.dump_journal(proc / "d", 0) == []
    assert b.journal["complete"] is False and b.journal["error"].startswith("journalctl:")
    # (e) system scope: a unit with no entry at all means the journal was not read
    b = system("one", _say(_entry(CORE, "a", 1000000)))
    b.dump_journal(proc / "e", 0)
    assert b.journal["complete"] is False, b.journal
    assert b.journal["error"] == f"no journal entry for {INGEST}", b.journal
    # (f) user scope: an empty copy is legal (a laptop user journal may be volatile)
    u = sd.SystemdBackend(
        "user",
        run_dir=tmp_path / "u",
        journalctl=_fake_journalctl(tmp_path / "empty", "exit 0\n"),
        monitor=False,
        tag="t",
    )
    for role in ("core", "ingest"):
        u.add(role, ["x"], Policy())
    u.dump_journal(proc / "f", 0)
    assert u.journal == {"complete": True, "error": None, "entries": {"core": 0, "ingest": 0}}
    # (g) a whole copy
    b = system(
        "ok",
        _say(
            _entry(CORE, "a", 1000000),
            _entry(CORE, "b", 1000001),
            _entry(INGEST, "c", 1000002),
            _entry(INGEST, "d", 1000003),
        ),
    )
    b.dump_journal(proc / "g", 0)
    assert b.journal == {"complete": True, "error": None, "entries": {"core": 2, "ingest": 2}}
    assert b.info()["journal"] == b.journal


def test_end_of_run_children_get_their_own_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """journalctl, umount and vcgencmd run at the end of the run, when the harness holds a
    terminal Ctrl-C: they must not share its process group (review CR-01)."""
    from jabuka.soak import probes

    seen: list[tuple[list[str], dict[str, object]]] = []
    rc = {"value": 0}

    def run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess:
        seen.append((list(cmd), kw))
        out = "" if kw.get("text") else b""
        return subprocess.CompletedProcess(cmd, rc["value"], out, out)

    monkeypatch.setattr(sd.subprocess, "run", run)
    b = _system(tmp_path)
    b.dump_journal(tmp_path / "proc", 0)
    assert seen and seen[-1][1].get("start_new_session") is True, seen
    assert seen[-1][1].get("timeout") == sd.JOURNAL_TIMEOUT_S == 300.0, seen
    seen.clear()
    rc["value"] = 1  # both umount calls happen
    assert sd.unmount(tmp_path / "m") is False
    assert len(seen) == 2 and all(kw.get("start_new_session") is True for _, kw in seen), seen
    seen.clear()
    rc["value"] = 0
    probe = probes.pi_probe("/x/vcgencmd")
    assert probe is not None
    probe()
    assert seen and all(kw.get("start_new_session") is True for _, kw in seen), seen


def _shim_harness(tmp_path: Path) -> soak.Harness:
    out = tmp_path / "out"
    args = soak.build_arg_parser().parse_args(["--scenario", "tracer", "--out", str(out)])
    args.fixtures = tmp_path
    return soak.Harness(soak.make_run_dir(out, "tracer"), load_scenario("tracer"), args)


def _user_backend(h: soak.Harness, journalctl: str) -> sd.SystemdBackend:
    b = sd.SystemdBackend("user", run_dir=h.run_dir, journalctl=journalctl, monitor=False, tag="t")
    for role in ("core", "ingest"):
        b.add(role, ["x"], Policy())
    return b


def test_incomplete_journal_copy_fails_the_tracebacks_check_and_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _shim_harness(tmp_path)
    try:
        monkeypatch.setattr(sd, "JOURNAL_TIMEOUT_S", 1.0)
        b = _user_backend(h, _fake_journalctl(tmp_path / "slow", "exec sleep 10\n"))
        h.sup = b
        b.dump_journal(h.run_dir / "proc", 0)
        report = h.build_report()
        tb = report["checks"]["tracebacks"]
        assert tb["ok"] is False, tb
        assert tb["detail"].startswith("journal dump incomplete (journalctl timed out"), tb
        assert report["verdict"] == "FAIL"
        assert any(
            r.startswith("check tracebacks: journal dump incomplete")
            for r in report["fail_reasons"]
        ), report["fail_reasons"]
    finally:
        with contextlib.suppress(Exception):
            h._tl.close()


def test_complete_journal_copy_keeps_the_tracebacks_check(tmp_path: Path) -> None:
    h = _shim_harness(tmp_path)
    try:
        script = _say(
            _entry("jabuka-soak-t-core.service", "clean", 1000000),
            _entry("jabuka-soak-t-ingest.service", "clean", 1000001),
        )
        b = _user_backend(h, _fake_journalctl(tmp_path / "ok", script))
        h.sup = b
        b.dump_journal(h.run_dir / "proc", 0)
        tb = h.build_report()["checks"]["tracebacks"]
        assert tb["ok"] is True, tb
        assert "journal dump incomplete" not in tb["detail"], tb
    finally:
        with contextlib.suppress(Exception):
            h._tl.close()
    assert soak.journal_problem(object()) is None
    fresh = sd.SystemdBackend("user", run_dir=tmp_path / "fresh", monitor=False, tag="f")
    assert soak.journal_problem(fresh) == "journal not copied"


def test_a_held_signal_is_announced_once_and_never_raises(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Review IN-02: the operator sees why nothing stops; a dead tee never breaks the end."""
    prev = signal.signal(signal.SIGHUP, soak._on_signal)
    w = None
    try:
        hold = sd.SignalHold().start()
        signal.raise_signal(signal.SIGHUP)
        signal.raise_signal(signal.SIGHUP)
        assert hold.release() == signal.SIGHUP
        err = capfd.readouterr().err
        lines = [ln for ln in err.splitlines() if ln.startswith("jabuka-soak: signal")]
        assert len(lines) == 1, err
        assert lines[0].startswith(f"jabuka-soak: signal {int(signal.SIGHUP)} held"), lines
        assert "~15 min" in lines[0], lines
        r, w = os.pipe()
        os.close(r)  # a dead tee
        hold = sd.SignalHold(announce_fd=w).start()
        signal.raise_signal(signal.SIGHUP)  # must not raise (BrokenPipeError suppressed)
        assert hold.release() == signal.SIGHUP
    finally:
        signal.signal(signal.SIGHUP, prev)
        if w is not None:
            os.close(w)


# -- report.json records the signal held at the end of the run (plan 04-08, gap 07-5) -----------
def test_run_soak_records_the_end_signal_in_report_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = tmp_path / "site-packages" / "jabuka"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    mode = {"how": "end"}

    def identity(self: soak.Harness) -> None:
        self.code = soak.rep.code_identity(pkg, python=None, source="children")
        self.code_error = None

    def run(self: soak.Harness) -> dict:
        if mode["how"] == "end":
            self.end_signals.start()  # what the real Harness.run does after the main run
            signal.raise_signal(signal.SIGHUP)
        elif mode["how"] == "cleanup":
            self.sup.pending_signal = signal.SIGHUP  # held by the cleanup's own hold
        return {"verdict": "PASS", "fail_reasons": [], "end_signal": None}

    def write_report(run_dir: Path, report: dict) -> tuple[Path, Path]:
        jpath, mpath = run_dir / "report.json", run_dir / "report.md"
        jpath.write_text(json.dumps(report), encoding="utf-8")
        mpath.write_text("# report\n", encoding="utf-8")
        return jpath, mpath

    def soak_once(name: str) -> tuple[int, dict]:
        out = tmp_path / name
        args = soak.build_arg_parser().parse_args(["--scenario", "tracer", "--out", str(out)])
        rc = soak.run_soak(args, load_scenario("tracer"))
        reports = list(out.glob("*-tracer/report.json"))
        assert len(reports) == 1, reports
        return rc, json.loads(reports[0].read_text(encoding="utf-8"))

    monkeypatch.setattr(soak.Harness, "compute_code_identity", identity)
    monkeypatch.setattr(soak.Harness, "run", run)
    monkeypatch.setattr(soak.rep, "write_report", write_report)
    prev = signal.signal(signal.SIGHUP, soak._on_signal)
    try:
        rc, report = soak_once("a")
        assert rc == 128 + signal.SIGHUP
        assert report["end_signal"] == int(signal.SIGHUP), report
        mode["how"] = "cleanup"
        rc, report = soak_once("b")
        assert rc == 128 + signal.SIGHUP
        assert report["end_signal"] == int(signal.SIGHUP), report
        mode["how"] = "none"
        rc, report = soak_once("c")
        assert rc == 0
        assert report["end_signal"] is None, report
    finally:
        signal.signal(signal.SIGHUP, prev)


def test_report_md_marks_an_interrupted_soak() -> None:
    assert "Soak interrompu" in soak.rep.render_md({"git": {}, "end_signal": 1})
    for report in (
        {"git": {}, "end_signal": None},
        {"git": {}},
        {"git": {}, "end_signal": True},
    ):
        assert "Soak interrompu" not in soak.rep.render_md(report), report
