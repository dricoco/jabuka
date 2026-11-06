"""systemd units and drop-ins for the Pi: supervision, hardening, Plan B exclusivity."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from jabuka.core.main import build_arg_parser as core_parser
from jabuka.ingest.fastnet_main import build_arg_parser as ingest_parser

INGEST = "jabuka-ingest-fastnet.service"
CORE = "jabuka-core.service"
PLANB = "fastnet2ip.service"
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
    assert "fastnet2ip.service" in _words(u, "Unit", "Conflicts")
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
    assert _one(planb, "Service", "User") == "root"
    assert _one(planb, "Service", "Restart") == "on-failure"
    assert "BindsTo" not in planb["Unit"]
    argv = shlex.split(_one(planb, "Service", "ExecStart"))
    assert argv == [
        "/usr/local/bin/fastnet2ip",
        "--output",
        "nmea0183",
        "--serial",
        "/dev/fastnet",
        "--udp-port",
        "2002",
        "--host",
        "10.42.0.255",
        "--log-level",
        "WARNING",
    ]


def test_plan_b_header_documents_manual_use(deploy_dir: Path) -> None:
    text = (deploy_dir / "systemd" / PLANB).read_text()
    header = "\n".join(line for line in text.splitlines() if line.startswith("#"))
    assert "NOT enabled at boot" in header
    assert "3.3.1" in header
    assert "no serial write call" in header


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
    names = (INGEST, CORE, PLANB)
    for name in names:
        text = (deploy_dir / "systemd" / name).read_text()
        text = text.replace("/opt/jabuka/venv/bin/", venv_bin)
        text = text.replace("/usr/local/bin/fastnet2ip", shutil.which("true") or "/bin/true")
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
