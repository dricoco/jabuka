"""deploy/provision.sh (dry run only, never for real here) and the device/time config files."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

PSK = "Unit-Test-Passphrase-q7Zr"


def _provision(deploy_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "JABUKA_PSK"}
    return subprocess.run(
        ["bash", str(deploy_dir / "provision.sh"), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.fixture
def psk_file(tmp_path: Path) -> Path:
    p = tmp_path / "secrets.env"
    p.write_text(f"# test\nJABUKA_PSK={PSK}\n")
    return p


@pytest.fixture
def dry_run(deploy_dir: Path, psk_file: Path) -> subprocess.CompletedProcess[str]:
    return _provision(deploy_dir, "--dry-run", "--psk-file", str(psk_file))


def test_bash_syntax(deploy_dir: Path) -> None:
    proc = subprocess.run(
        ["bash", "-n", str(deploy_dir / "provision.sh")], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_dry_run_prints_every_required_step(dry_run) -> None:
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    out = dry_run.stdout
    for token in (
        "apt-get install -y gpsd gpsd-clients chrony python3-venv jq dnsmasq-base",
        "apt-get purge -y modemmanager brltty",
        "/etc/default/gpsd",
        "/etc/udev/rules.d/99-jabuka.rules",
        "udevadm control --reload",
        "udevadm trigger",
        "/etc/chrony/conf.d/gps.conf",
        "makestep 1 -1",
        "useradd --system",
        "--groups dialout jabuka",
        "python3 -m venv /opt/jabuka/venv",
        "--require-hashes",
        "--no-index",
        "python3 -m venv /opt/fastnet2ip/venv",
        "/opt/fastnet2ip/venv/bin/pip install --no-index --find-links "
        "/opt/jabuka/wheelhouse/fastnet2ip --require-hashes -r /opt/jabuka/fastnet2ip.lock",
        "/etc/systemd/system/jabuka-fastnet-relay.service",
        # g2: emergency weather prep venv on the Pi, separate from the app venv
        "python3 -m venv /opt/jabuka-prep/venv",
        "/opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse "
        "--require-hashes -r /opt/jabuka/requirements.lock",
        "/opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse/prep "
        "--require-hashes -r /opt/jabuka/prep.lock",
        "--no-deps --force-reinstall /opt/jabuka/wheelhouse/jabuka-",
        "prep.lock /opt/jabuka/prep.lock",
        "ln -sfn /opt/jabuka-prep/venv/bin/jabuka-prep /usr/local/bin/jabuka-prep-pi",
        "/usr/local/sbin/prerace",
        "/etc/systemd/system/fastnet2ip.service",
        "/etc/systemd/system.conf.d/jabuka-watchdog.conf",
        "/etc/systemd/journald.conf.d/jabuka.conf",
        "systemctl daemon-reload",
        "systemctl enable jabuka-ingest-fastnet.service jabuka-core.service",
        "systemctl restart systemd-journald.service",
        "con-name jabuka-ap",
        "802-11-wireless.mode ap",
        "802-11-wireless.band bg",
        "802-11-wireless.channel 6",
        "802-11-wireless.powersave 2",
        "ipv4.method shared",
        "ipv4.addresses 10.42.0.1/24",
        "ipv6.method disabled",
        "wifi-sec.key-mgmt wpa-psk",
        "wifi-sec.proto rsn",
        "wifi-sec.pairwise ccmp",
        "wifi-sec.group ccmp",
        "wifi-sec.pmf disable",
        "connection.autoconnect-priority 100",
        "nmcli connection up jabuka-ap",
    ):
        assert token in out, token


def test_dry_run_order(dry_run) -> None:
    out = dry_run.stdout
    order = [
        "apt-get install",
        "apt-get purge",
        "udevadm trigger",
        "systemctl enable --now chrony.service",
        "systemctl enable --now gpsd.service",
        "useradd",
        "--require-hashes",
        "/opt/fastnet2ip/venv/bin/pip install",
        "/opt/jabuka-prep/venv/bin/pip install",
        "/usr/local/sbin/prerace",
        "systemctl enable jabuka-ingest-fastnet.service",
        "nmcli connection add",
        "nmcli connection up jabuka-ap",
    ]
    positions = [out.index(t) for t in order]
    assert positions == sorted(positions), list(zip(order, positions, strict=True))
    # the AP comes up last of all mutating commands
    commands = [line for line in out.splitlines() if line.startswith("+ ")]
    assert commands[-1] == "+ nmcli connection up jabuka-ap"


def test_dry_run_never_leaks_the_psk(dry_run) -> None:
    assert PSK not in dry_run.stdout
    assert PSK not in dry_run.stderr
    assert "wifi-sec.psk ***" in dry_run.stdout


def test_fastnet2ip_never_enabled(dry_run) -> None:
    for line in dry_run.stdout.splitlines():
        if line.startswith("+ ") and "systemctl" in line and "enable" in line:
            assert "fastnet2ip" not in line, line
            assert "relay" not in line, line


def test_plan_b_is_hash_locked_never_live_pypi(dry_run) -> None:
    """WR-03: no `pipx install` (root, unpinned dependencies resolved from PyPI)."""
    commands = [line for line in dry_run.stdout.splitlines() if line.startswith("+ ")]
    assert not [c for c in commands if "pipx install" in c]
    f2i = [c for c in commands if "/opt/fastnet2ip/venv/bin/pip install" in c]
    assert len(f2i) == 1
    assert "--no-index" in f2i[0] and "--require-hashes" in f2i[0]


def test_prep_venv_is_hash_locked_and_separate(dry_run) -> None:
    """Step g2 never touches the app venv; both lock installs are offline and hash-checked."""
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    commands = [line for line in dry_run.stdout.splitlines() if line.startswith("+ ")]
    prep = [c for c in commands if "/opt/jabuka-prep/venv/bin/pip install" in c]
    assert len(prep) == 3, prep
    assert all("--no-index" in c for c in prep), prep
    locked = [c for c in prep if " -r " in c]
    assert len(locked) == 2 and all("--require-hashes" in c for c in locked), locked
    wheel = [c for c in prep if " -r " not in c]
    assert len(wheel) == 1 and "--no-deps" in wheel[0], wheel
    app = [c for c in commands if "/opt/jabuka/venv/bin/pip install" in c]
    assert len(app) == 2, app  # step f only
    out = dry_run.stdout
    g2 = out[out.index("\n== g2.") : out.index("\n== h.")]
    for line in g2.splitlines():
        if line.startswith("+ "):
            assert "/opt/jabuka/venv/" not in line, line


def test_prep_step_warns_when_wheelhouse_prep_absent(deploy_dir: Path) -> None:
    text = (deploy_dir / "provision.sh").read_text()
    assert '"$OPT/wheelhouse/prep"' in text
    assert "emergency weather prep NOT installed" in text


def test_only_mutations_through_run(dry_run) -> None:
    """Every printed command is a '+ ' line; no other system tool runs in dry-run mode."""
    assert "DRY RUN" in dry_run.stdout
    assert not re.search(r"^\+ .*(hostapd|dhcpcd)", dry_run.stdout, re.M)


@pytest.mark.parametrize("bad", ["12345", "x" * 64, ""])
def test_bad_psk_length_exits_2(deploy_dir: Path, tmp_path: Path, bad: str) -> None:
    p = tmp_path / "bad.env"
    p.write_text(f"JABUKA_PSK={bad}\n")
    proc = _provision(deploy_dir, "--dry-run", "--psk-file", str(p))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "8-63" in proc.stderr
    if bad:
        assert bad not in proc.stdout + proc.stderr


def test_missing_psk_file_exits_2(deploy_dir: Path, tmp_path: Path) -> None:
    proc = _provision(deploy_dir, "--dry-run", "--psk-file", str(tmp_path / "nope.env"))
    assert proc.returncode == 2


def test_quoted_psk_is_accepted(deploy_dir: Path, tmp_path: Path) -> None:
    p = tmp_path / "q.env"
    p.write_text(f'JABUKA_PSK="{PSK}"\n')
    proc = _provision(deploy_dir, "--dry-run", "--psk-file", str(p))
    assert proc.returncode == 0, proc.stderr
    assert PSK not in proc.stdout


def test_skip_ap_with_example_secrets(deploy_dir: Path) -> None:
    proc = _provision(
        deploy_dir, "--dry-run", "--psk-file", str(deploy_dir / "secrets.env.example"), "--skip-ap"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nmcli" not in proc.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="the root check needs a non-root user")
def test_real_run_requires_root(deploy_dir: Path, psk_file: Path) -> None:
    proc = _provision(deploy_dir, "--psk-file", str(psk_file))
    assert proc.returncode == 1
    assert "root" in proc.stderr
    assert proc.stdout == ""


def test_unknown_argument_exits_2(deploy_dir: Path) -> None:
    assert _provision(deploy_dir, "--dry-run", "--bogus").returncode == 2


def test_udev_rules(deploy_dir: Path) -> None:
    rules = [
        line
        for line in (deploy_dir / "udev" / "99-jabuka.rules").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(rules) == 2
    fastnet = next(r for r in rules if 'SYMLINK+="fastnet"' in r)
    for token in (
        'SUBSYSTEM=="tty"',
        'ATTRS{idVendor}=="0403"',
        'ATTRS{idProduct}=="6001"',
        'GROUP="dialout"',
        'MODE="0640"',
        'ENV{ID_MM_DEVICE_IGNORE}="1"',
    ):
        assert token in fastnet, token
    gps = next(r for r in rules if 'SYMLINK+="gps"' in r)
    for token in (
        'ATTRS{idVendor}=="1546"',
        'ATTRS{idProduct}=="01a7"',
        'ENV{ID_MM_DEVICE_IGNORE}="1"',
        'TAG+="systemd"',
    ):
        assert token in gps, token
    text = (deploy_dir / "udev" / "99-jabuka.rules").read_text()
    assert "ATTRS{serial}" in text  # the comment on pinning one of several FT232 adapters


def test_gpsd_default(deploy_dir: Path) -> None:
    text = (deploy_dir / "gpsd.default").read_text()
    for token in (
        'START_DAEMON="true"',
        'DEVICES="/dev/gps"',
        'GPSD_OPTIONS="-n"',
        'USBAUTO="false"',
    ):
        assert token in text.splitlines(), token


def test_chrony_conf(deploy_dir: Path) -> None:
    lines = [
        line
        for line in (deploy_dir / "chrony-gps.conf").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines == ["refclock SHM 0 refid GPS precision 1e-1 offset 0.2 delay 0.2"]
    assert "chronyc sourcestats" in (deploy_dir / "chrony-gps.conf").read_text()


def test_secrets_example(deploy_dir: Path, repo_root: Path) -> None:
    text = (deploy_dir / "secrets.env.example").read_text()
    assert "JABUKA_PSK=change-me-8-to-63-chars" in text.splitlines()
    assert "gitignored" in text
    assert "deploy/secrets.env" in (repo_root / ".gitignore").read_text().splitlines()


def test_no_competing_ap_stack(deploy_dir: Path) -> None:
    """CLAUDE.md: no hostapd/dhcpcd AP recipes, NetworkManager only."""
    for p in deploy_dir.rglob("*"):
        if not p.is_file() or "wheelhouse" in p.parts or p.suffix == ".whl":
            continue
        text = p.read_text(errors="replace").lower()
        assert "hostapd" not in text, p
        assert "dhcpcd" not in text, p


def test_ssh_key_only_drop_in_sorts_first_and_is_verified(deploy_dir: Path) -> None:
    """WR-10: sshd keeps the first value per keyword and reads drop-ins in lexical order, so the
    drop-in must sort first, and the effective config must be checked (sshd -T)."""
    text = (deploy_dir / "provision.sh").read_text()
    assert "/etc/ssh/sshd_config.d/00-jabuka.conf" in text
    assert "write_file /etc/ssh/sshd_config.d/jabuka.conf" not in text
    assert "PasswordAuthentication no\nKbdInteractiveAuthentication no" in text
    assert "run sshd -t" in text
    assert "sshd -T" in text
    assert '"passwordauthentication no" "kbdinteractiveauthentication no"' in text
    assert "SSH is NOT key-only" in text
