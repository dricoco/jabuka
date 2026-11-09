"""systemd units and drop-ins for the Pi: supervision, hardening, Plan B exclusivity."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jabuka.core.main import build_arg_parser as core_parser
from jabuka.ingest.fastnet_main import build_arg_parser as ingest_parser

INGEST = "jabuka-ingest-fastnet.service"
CORE = "jabuka-core.service"
PLANB = "fastnet2ip.service"
RELAY = "jabuka-fastnet-relay.service"
JABUKA_UNITS = (INGEST, CORE)

COMMON_SERVICE = {
    "Type": "notify",
    "Restart": "always",
    "RestartSec": "2",
    "WatchdogSec": "30",
    "User": "jabuka",
    "StateDirectory": "jabuka",
    "NoNewPrivileges": "yes",
    "ProtectSystem": "strict",
    "ProtectHome": "yes",
    "PrivateTmp": "yes",
    "ReadWritePaths": "/var/lib/jabuka",
    "Environment": "PYTHONUNBUFFERED=1",
}


def _one(unit: dict, section: str, key: str) -> str:
    values = unit.get(section, {}).get(key)
    assert values, f"[{section}] {key}= missing"
    assert len(values) == 1, f"[{section}] {key}= set {len(values)} times: {values}"
    return values[0]


def _words(unit: dict, section: str, key: str) -> set[str]:
    return {w for v in unit.get(section, {}).get(key, []) for w in v.split()}


@pytest.mark.parametrize("name", JABUKA_UNITS)
def test_jabuka_units_supervised_and_hardened(parse_unit, name: str) -> None:
    u = parse_unit(name)
    assert _one(u, "Unit", "StartLimitIntervalSec") == "0"
    for key, value in COMMON_SERVICE.items():
        assert _one(u, "Service", key) == value, key
    assert _one(u, "Install", "WantedBy") == "multi-user.target"


@pytest.mark.parametrize("name", JABUKA_UNITS)
def test_jabuka_units_not_bound_to_a_device(parse_unit, name: str) -> None:
    """Anti-pattern: binding to dev-fastnet.device would stop the service on unplug and keep it
    from reporting "device missing". The in-process reconnect handles absence."""
    u = parse_unit(name)
    assert "BindsTo" not in u["Unit"]
    assert "PartOf" not in u["Unit"]
    for key in ("Requires", "Requisite", "After", "Wants"):
        assert not any(w.endswith(".device") for w in _words(u, "Unit", key)), key


def test_ingest_unit(parse_unit) -> None:
    u = parse_unit(INGEST)
    assert _one(u, "Service", "SupplementaryGroups") == "dialout"
    assert _one(u, "Service", "OOMScoreAdjust") == "-700"
    assert {"fastnet2ip.service", RELAY} <= _words(u, "Unit", "Conflicts")
    # no capabilities at all: the ingest only reads a device and sends UDP to localhost
    assert "AmbientCapabilities" not in u["Service"]


def test_core_unit(parse_unit) -> None:
    u = parse_unit(CORE)
    assert "gpsd.service" in _words(u, "Unit", "Wants")
    assert {"network.target", "chrony.service", "gpsd.service"} <= _words(u, "Unit", "After")
    assert _one(u, "Service", "AmbientCapabilities") == "CAP_NET_BIND_SERVICE"
    assert _one(u, "Service", "CapabilityBoundingSet") == "CAP_NET_BIND_SERVICE"
    assert _one(u, "Service", "OOMScoreAdjust") == "-500"
    # the core never touches the serial devices (GPS comes via gpsd TCP)
    assert "SupplementaryGroups" not in u["Service"]
    assert _one(u, "Service", "PrivateDevices") == "yes"  # WR-01: no tty reachable at all


def test_plan_b_conflicts_both_ways_and_not_enabled(parse_unit) -> None:
    planb = parse_unit(PLANB)
    ingest = parse_unit(INGEST)
    assert "jabuka-ingest-fastnet.service" in _words(planb, "Unit", "Conflicts")
    assert "fastnet2ip.service" in _words(ingest, "Unit", "Conflicts")
    # no [Install] section: `systemctl enable fastnet2ip` cannot wire it into boot
    assert "Install" not in planb
    assert _one(planb, "Service", "Restart") == "on-failure"
    # G-4-R12: a crash loop must not leave Plan B dead (systemd's default: 5 starts in 10 s)
    assert _one(planb, "Unit", "StartLimitIntervalSec") == "0"
    argv = shlex.split(_one(planb, "Service", "ExecStart"))
    assert argv == [
        "/opt/fastnet2ip/venv/bin/fastnet2ip",
        "--output",
        "nmea0183",
        "--serial",
        "/run/jabuka-relay/fastnet-ro",
        "--udp-port",
        "2002",
        "--host",
        "10.42.0.255",
        "--log-level",
        "WARNING",
    ]


def test_plan_b_never_gets_the_bus(parse_unit) -> None:
    """WR-03: fastnet2ip runs unprivileged, without dialout (cannot open /dev/fastnet), and reads
    the receive-only relay's pty."""
    planb = parse_unit(PLANB)
    assert _one(planb, "Service", "User") == "jabuka"
    assert _one(planb, "Service", "Group") == "jabuka"
    assert "SupplementaryGroups" not in planb["Service"]
    assert "AmbientCapabilities" not in planb["Service"]
    assert planb["Service"]["CapabilityBoundingSet"] == [""]
    assert _one(planb, "Service", "NoNewPrivileges") == "yes"
    assert _one(planb, "Service", "ProtectSystem") == "strict"
    assert "/dev/fastnet" not in _one(planb, "Service", "ExecStart")
    assert RELAY in _words(planb, "Unit", "BindsTo")
    assert RELAY in _words(planb, "Unit", "After")


def test_relay_unit(parse_unit) -> None:
    relay = parse_unit(RELAY)
    assert "Install" not in relay  # only ever pulled in by fastnet2ip
    assert _one(relay, "Unit", "StartLimitIntervalSec") == "0"  # G-4-R12: never stays dead
    assert _one(relay, "Unit", "StopWhenUnneeded") == "yes"
    # WR-06: an auto-restart never passes through inactive/failed, so fastnet2ip's BindsTo= never
    # stops Plan B on a single relay crash
    assert _one(relay, "Service", "RestartMode") == "direct"
    assert "jabuka-ingest-fastnet.service" in _words(relay, "Unit", "Conflicts")
    assert _one(relay, "Service", "Type") == "notify"
    assert _one(relay, "Service", "User") == "jabuka"
    assert _one(relay, "Service", "SupplementaryGroups") == "dialout"
    assert _one(relay, "Service", "RuntimeDirectory") == "jabuka-relay"
    assert _one(relay, "Service", "NoNewPrivileges") == "yes"
    argv = shlex.split(_one(relay, "Service", "ExecStart"))
    assert argv[0] == "/opt/jabuka/venv/bin/jabuka-fastnet-relay"
    from jabuka.tools.fastnet_relay import build_arg_parser as relay_parser

    args = relay_parser().parse_args(argv[1:])
    assert args.device == "/dev/fastnet"
    assert str(args.link) == "/run/jabuka-relay/fastnet-ro"
    # the link lives in the relay's RuntimeDirectory, which fastnet2ip reads
    planb_argv = shlex.split(_one(parse_unit(PLANB), "Service", "ExecStart"))
    assert planb_argv[planb_argv.index("--serial") + 1] == str(args.link)


def _user_systemd() -> tuple[str, Path] | None:
    """(systemctl, the user manager's runtime unit dir) when a user manager is running."""
    exe = shutil.which("systemctl")
    rt = os.environ.get("XDG_RUNTIME_DIR")
    if exe is None or not rt or sys.platform != "linux":
        return None
    try:
        r = subprocess.run(
            [exe, "--user", "is-system-running"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.stdout.strip() not in ("running", "degraded"):
        return None
    return exe, Path(rt) / "systemd" / "user"


def _copied(unit: dict, section: str, keys: tuple[str, ...]) -> str:
    return "".join(f"{k}={v}\n" for k in keys for v in unit.get(section, {}).get(k, []))


def test_one_relay_crash_keeps_plan_b_up(parse_unit) -> None:
    """WR-06 on a real (user-scope) systemd: throwaway units carrying the shipped relay and
    fastnet2ip dependency/restart directives. The Plan B stand-in models fastnet2ip 3.3.1, which
    exits 1 when the relay's pty goes away (SerialException on EIO; read from the 3.3.1 wheel).
    With RestartMode=direct the relay never passes through inactive/failed, so BindsTo= does
    not stop Plan B on the relay's crash, and Plan B's own Restart=on-failure brings it back on
    the restarted relay (review WR-03 of 93cb8b3). One kill -9 of the relay: both units active
    again with NRestarts >= 1, and Plan B runs a new process."""
    planb = parse_unit(PLANB)
    relay = parse_unit(RELAY)
    assert RELAY in _words(planb, "Unit", "BindsTo")
    assert RELAY in _words(planb, "Unit", "After")
    found = _user_systemd()
    if found is None:
        pytest.skip("no user systemd manager (XDG_RUNTIME_DIR / systemctl --user)")
    exe, unit_dir = found
    sleep = shutil.which("sleep") or "/bin/sleep"
    sh = shutil.which("sh") or "/bin/sh"
    rname = f"jabuka-wr06-{os.getpid()}-relay.service"
    pname = f"jabuka-wr06-{os.getpid()}-planb.service"
    relay_text = (
        "[Unit]\nDescription=WR-06 throwaway relay\n"
        + _copied(relay, "Unit", ("StopWhenUnneeded", "StartLimitIntervalSec"))
        + f"\n[Service]\nType=simple\nExecStart={sleep} infinity\n"
        + _copied(relay, "Service", ("Restart", "RestartSec", "RestartMode"))
    )
    # the fastnet2ip stand-in: read the relay's MainPID once, exit 1 once that process is gone
    # ($$ is systemd's escape for a literal $)
    script = (
        f"p=$$({exe} --user show -p MainPID --value {rname}); "
        '[ "$$p" -gt 0 ] || exit 1; '
        'while kill -0 "$$p" 2>/dev/null; do sleep 0.2; done; exit 1'
    )
    planb_text = (
        f"[Unit]\nDescription=WR-06 throwaway Plan B\nBindsTo={rname}\nAfter={rname}\n"
        + _copied(planb, "Unit", ("StartLimitIntervalSec",))
        + f"\n[Service]\nType=simple\nExecStart={sh} -c '{script}'\n"
        + _copied(planb, "Service", ("Restart", "RestartSec"))
    )

    def ctl(*args: str, check: bool = True) -> str:
        r = subprocess.run(
            [exe, "--user", *args], capture_output=True, text=True, timeout=30, check=False
        )
        if check:
            assert r.returncode == 0, (args, r.stdout, r.stderr)
        return r.stdout.strip()

    def show(unit: str, prop: str) -> str:
        return ctl("show", "-p", prop, "--value", unit)

    def restarts(unit: str) -> int:
        return int(show(unit, "NRestarts") or 0)

    unit_dir.mkdir(parents=True, exist_ok=True)
    files = [unit_dir / rname, unit_dir / pname]
    files[0].write_text(relay_text)
    files[1].write_text(planb_text)
    try:
        ctl("daemon-reload")
        ctl("start", pname)
        time.sleep(1.0)
        assert show(pname, "ActiveState") == "active"
        assert show(rname, "ActiveState") == "active"
        assert show(pname, "NRestarts") == "0"
        planb_pid = show(pname, "MainPID")
        relay_pid = int(show(rname, "MainPID"))
        assert relay_pid > 0 and planb_pid not in ("", "0")
        os.kill(relay_pid, signal.SIGKILL)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if (
                restarts(rname) >= 1
                and restarts(pname) >= 1
                and show(rname, "ActiveState") == "active"
                and show(pname, "ActiveState") == "active"
            ):
                break
            time.sleep(0.2)
        time.sleep(3.0)  # and both stay up
        assert show(rname, "ActiveState") == "active"
        assert restarts(rname) >= 1
        assert show(pname, "ActiveState") == "active"
        assert restarts(pname) >= 1
        assert show(pname, "MainPID") not in ("", "0", planb_pid)
    finally:
        ctl("stop", pname, rname, check=False)
        for f in files:
            f.unlink(missing_ok=True)
        ctl("daemon-reload", check=False)
        ctl("reset-failed", pname, rname, check=False)


def test_plan_b_header_documents_manual_use(deploy_dir: Path) -> None:
    text = (deploy_dir / "systemd" / PLANB).read_text()
    header = "\n".join(line for line in text.splitlines() if line.startswith("#"))
    assert "NOT enabled at boot" in header
    assert "3.3.1" in header
    assert "no serial write call" in header
    assert "require-hashes" in header
    assert "WITHOUT the dialout group" in header


def test_ingest_execstart_parses_with_the_real_cli(parse_unit) -> None:
    argv = shlex.split(_one(parse_unit(INGEST), "Service", "ExecStart"))
    assert argv[0] == "/opt/jabuka/venv/bin/jabuka-ingest-fastnet"
    args = ingest_parser().parse_args(argv[1:])
    assert args.device == "/dev/fastnet"
    assert str(args.data_dir) == "/var/lib/jabuka"
    assert args.udp == ("127.0.0.1", 47100)


def _core_knows_gpsd() -> bool:
    return any("--gpsd" in a.option_strings for a in core_parser()._actions)


def test_core_execstart_parses_with_the_real_cli(parse_unit) -> None:
    argv = shlex.split(_one(parse_unit(CORE), "Service", "ExecStart"))
    assert argv[0] == "/opt/jabuka/venv/bin/jabuka-core"
    assert argv[1:] == [
        "--http-host",
        "0.0.0.0",
        "--http-port",
        "80",
        "--data-dir",
        "/var/lib/jabuka",
        "--clock",
        "gps",
        "--gpsd",
        "127.0.0.1:2947",
    ]
    if not _core_knows_gpsd():
        pytest.skip("01-03 not merged yet; phase-level check covers it")
    args = core_parser().parse_args(argv[1:])
    assert args.http_host == "0.0.0.0"  # the dev default is 127.0.0.1 (IN-08)
    assert core_parser().parse_args([]).http_host == "127.0.0.1"
    assert args.http_port == 80
    assert str(args.data_dir) == "/var/lib/jabuka"
    assert args.clock == "gps"


def test_drop_ins(deploy_dir: Path, parse_unit) -> None:
    wd = parse_unit(deploy_dir / "systemd" / "watchdog.conf")
    assert _one(wd, "Manager", "RuntimeWatchdogSec") == "15"
    jd = parse_unit(deploy_dir / "systemd" / "journald-jabuka.conf")
    assert _one(jd, "Journal", "Storage") == "volatile"
    assert _one(jd, "Journal", "RuntimeMaxUse") == "32M"


SYSTEMD_ANALYZE = "/usr/bin/systemd-analyze"
BAD = re.compile(r"Unknown key|Unknown section|Unknown lvalue|Failed to parse|Invalid")


@pytest.mark.skipif(not Path(SYSTEMD_ANALYZE).exists(), reason="systemd-analyze not installed")
def test_systemd_analyze_verify(tmp_path: Path, deploy_dir: Path) -> None:
    venv_bin = str(Path(sys.executable).parent) + "/"
    names = (INGEST, CORE, PLANB, RELAY)
    for name in names:
        text = (deploy_dir / "systemd" / name).read_text()
        text = text.replace("/opt/jabuka/venv/bin/", venv_bin)
        text = text.replace(
            "/opt/fastnet2ip/venv/bin/fastnet2ip", shutil.which("true") or "/bin/true"
        )
        (tmp_path / name).write_text(text)
    proc = subprocess.run(
        [SYSTEMD_ANALYZE, "verify", "--man=no", *(str(tmp_path / n) for n in names)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = proc.stdout + proc.stderr
    # only our units: the host's own units may print unrelated warnings
    ours = [
        line
        for line in output.splitlines()
        if str(tmp_path) in line or any(n in line for n in names)
    ]
    bad = [line for line in ours if BAD.search(line)]
    assert bad == [], output


def test_systemd_analyze_detector(tmp_path: Path) -> None:
    """The verify check above would catch a typo'd directive."""
    if not Path(SYSTEMD_ANALYZE).exists():
        pytest.skip("systemd-analyze not installed")
    unit = tmp_path / "typo.service"
    unit.write_text("[Service]\nExecStart=/bin/true\nRestartz=always\n")
    proc = subprocess.run(
        [SYSTEMD_ANALYZE, "verify", "--man=no", str(unit)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert any(
        BAD.search(line) and "typo.service" in line
        for line in (proc.stdout + proc.stderr).splitlines()
    ), proc.stdout + proc.stderr
