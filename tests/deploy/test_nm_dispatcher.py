"""deploy/nm-dispatcher/90-jabuka-ap-keymgmt, run against a stubbed PATH.

The NetworkManager dispatcher script that resets wpa_supplicant's key_mgmt of the "jabuka" AP to
WPA-PSK (brcmfmac firmware without PSK-SHA256). wpa_cli, logger and sleep are tiny bash stubs that
append `<name> <args>` to $FAKE_CALLS; the fake wpa_cli is stateful (key_mgmt kept in a file), so
nothing here touches the real wpa_supplicant, NetworkManager or the journal. JABUKA_WPA_CLI always
points at the fake (or at a non-existent path), never at the dev machine's wpa_cli.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "nm-dispatcher" / "90-jabuka-ap-keymgmt"
SHA = "WPA-PSK WPA-PSK-SHA256"

RECORD = 'printf "%s\\n" "$(basename "$0") $*" >>"$FAKE_CALLS"\n'

FAKE_WPA_CLI = (
    RECORD
    + r"""if [ "${FAKE_WPA_FAIL:-0}" = 1 ]; then
    echo "Failed to connect to non-global ctrl_ifname: wlan0  error: No such file or directory" >&2
    exit 255
fi
[ "${1:-}" = "-i" ] && shift 2
cmd="${1:-}"
[ $# -gt 0 ] && shift
case "$cmd" in
    list_networks)
        echo "network id / ssid / bssid / flags"
        n=$(cat "$FAKE_LIST_COUNT" 2>/dev/null || echo 0)
        n=$((n + 1))
        echo "$n" >"$FAKE_LIST_COUNT"
        [ "$n" -le "${FAKE_LIST_EMPTY_FIRST:-0}" ] && exit 0
        cat "$FAKE_NETWORKS" ;;
    get_network)
        if [ "${FAKE_GET_FAIL:-0}" = 1 ]; then echo FAIL; exit 0; fi
        cat "$FAKE_STATE" ;;
    set_network)
        if [ "${FAKE_SET_FAIL:-0}" = 1 ]; then echo FAIL; exit 0; fi
        [ "${FAKE_STICKY:-0}" = 1 ] || printf '%s\n' "${!#}" >"$FAKE_STATE"
        echo OK ;;
    disconnect | select_network) echo OK ;;
    *) echo FAIL ;;
esac
exit 0
"""
)

STUBS = {
    "wpa_cli": FAKE_WPA_CLI,
    "logger": RECORD + "exit 0\n",
    "sleep": RECORD + "exit 0\n",
}

AP_ROWS = [("0", "other", "any", "[DISABLED]"), ("3", "jabuka", "any", "[CURRENT]")]


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@dataclass
class Env:
    tmp: Path
    fakebin: Path
    calls_file: Path
    state_file: Path
    networks_file: Path
    run_dir: Path
    run: Callable[..., subprocess.CompletedProcess[str]]

    def calls(self) -> list[str]:
        if not self.calls_file.exists():
            return []
        return self.calls_file.read_text().splitlines()

    def wpa(self, sub: str = "") -> list[str]:
        prefix = "wpa_cli " + ("-i wlan0 " + sub if sub else "")
        return [c for c in self.calls() if c.startswith(prefix)]

    def logs(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("logger ")]

    def sleeps(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("sleep")]

    def set_networks(self, rows: list[tuple[str, str, str, str]]) -> None:
        self.networks_file.write_text("".join("\t".join(r) + "\n" for r in rows))

    def set_state(self, key_mgmt: str) -> None:
        self.state_file.write_text(key_mgmt + "\n")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for name, body in STUBS.items():
        _write_exec(fakebin / name, body)
    calls = tmp_path / "calls.txt"
    state = tmp_path / "key_mgmt.txt"
    networks = tmp_path / "networks.txt"
    run_dir = tmp_path / "run"

    def run(
        iface: str = "wlan0",
        action: str = "up",
        connection_id: str | None = "jabuka-ap",
        **extra: str,
    ) -> subprocess.CompletedProcess[str]:
        e = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("FAKE_", "JABUKA_", "CONNECTION_"))
        }
        e["PATH"] = str(fakebin) + os.pathsep + e.get("PATH", "/usr/bin:/bin")
        e["FAKE_CALLS"] = str(calls)
        e["FAKE_STATE"] = str(state)
        e["FAKE_NETWORKS"] = str(networks)
        e["FAKE_LIST_COUNT"] = str(tmp_path / "list_count.txt")
        e["JABUKA_WPA_CLI"] = str(fakebin / "wpa_cli")
        e["JABUKA_WIFI_RUN_DIR"] = str(run_dir)
        if connection_id is not None:
            e["CONNECTION_ID"] = connection_id
        e.update(extra)
        return subprocess.run(
            ["bash", str(SCRIPT), iface, action],
            capture_output=True,
            text=True,
            timeout=30,
            env=e,
        )

    return Env(tmp_path, fakebin, calls, state, networks, run_dir, run)


def test_bash_syntax() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_script_is_executable_with_absolute_bash_shebang() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text().splitlines()[0] == "#!/bin/bash"


def test_sha256_is_reset_to_wpa_psk_on_the_listed_id(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = env.calls()
    expected = [
        "wpa_cli -i wlan0 set_network 3 key_mgmt WPA-PSK",
        "wpa_cli -i wlan0 disconnect",
        "wpa_cli -i wlan0 select_network 3",
    ]
    positions = [calls.index(c) for c in expected]
    assert positions == sorted(positions), calls
    for c in env.wpa():
        assert " 0" not in c.split("wlan0", 1)[1], c  # never assumes network id 0
    logs = env.logs()
    assert len(logs) == 1, logs
    assert logs[0].startswith("logger -t jabuka-wifi ")
    for token in ("WPA-PSK-SHA256", "-> WPA-PSK", " 3 "):
        assert token in logs[0], logs[0]
    assert env.state_file.read_text().strip() == "WPA-PSK"


def test_already_wpa_psk_is_left_alone(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state("WPA-PSK")
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for sub in ("set_network", "disconnect", "select_network"):
        assert not env.wpa(sub), env.calls()
    logs = env.logs()
    assert len(logs) == 1 and "rien à faire" in logs[0], logs


def test_second_up_event_is_a_no_op(env: Env) -> None:
    """The re-select may fire another "up" for jabuka-ap: the stateful fake now says WPA-PSK."""
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    assert env.run().returncode == 0
    assert env.run().returncode == 0
    assert len(env.wpa("set_network")) == 1, env.calls()
    logs = env.logs()
    assert len(logs) == 2 and "rien à faire" in logs[1], logs


@pytest.mark.parametrize(
    ("iface", "action", "connection_id"),
    [
        ("wlan0", "up", "jabuka-phone"),
        ("wlan0", "up", "Wired connection 1"),
        ("wlan0", "down", "jabuka-ap"),
        ("wlan0", "pre-down", "jabuka-ap"),
        ("wlan0", "dhcp4-change", "jabuka-ap"),
        ("wlan0", "reapply", "jabuka-ap"),
        ("eth0", "up", "jabuka-ap"),
        ("none", "hostname", None),
        ("wlan0", "connectivity-change", None),
    ],
)
def test_every_other_event_is_silent(
    env: Env, iface: str, action: str, connection_id: str | None
) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    proc = env.run(iface, action, connection_id)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert env.calls() == []


def test_missing_wpa_cli_logs_and_exits_0_without_waiting(env: Env) -> None:
    proc = env.run(JABUKA_WPA_CLI=str(env.tmp / "no-such-wpa_cli"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    logs = env.logs()
    assert len(logs) == 1 and "wpa_cli introuvable" in logs[0], logs
    assert not env.sleeps()


def test_wpa_cli_failing_waits_bounded_then_gives_up(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    proc = env.run(FAKE_WPA_FAIL="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(env.wpa("list_networks")) == 10, env.calls()
    assert env.sleeps() == ["sleep 1"] * 9
    assert not env.wpa("set_network")
    logs = env.logs()
    assert len(logs) == 1 and "non appliqué" in logs[0], logs


def test_get_network_fail_is_bounded_and_changes_nothing(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    proc = env.run(FAKE_GET_FAIL="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(env.wpa("list_networks")) == 10, env.calls()
    assert len(env.sleeps()) == 9
    assert not env.wpa("set_network")
    logs = env.logs()
    assert len(logs) == 1 and "non appliqué" in logs[0], logs


def test_set_network_fail_leaves_the_ap_running(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    proc = env.run(FAKE_SET_FAIL="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(env.wpa("set_network")) == 1
    assert not env.wpa("disconnect"), env.calls()
    assert not env.wpa("select_network"), env.calls()
    logs = env.logs()
    assert len(logs) == 1 and "ÉCHEC set_network" in logs[0], logs


def test_waits_for_wpa_supplicant_to_list_the_network(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    proc = env.run(FAKE_LIST_EMPTY_FIRST="2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert env.sleeps() == ["sleep 1"] * 2
    assert env.wpa("set_network") == ["wpa_cli -i wlan0 set_network 3 key_mgmt WPA-PSK"]
    assert env.wpa("select_network") == ["wpa_cli -i wlan0 select_network 3"]


def test_falls_back_to_the_current_network(env: Env) -> None:
    env.set_networks([("2", "x", "any", "[DISABLED]"), ("5", "other-ssid", "any", "[CURRENT]")])
    env.set_state(SHA)
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert env.wpa("set_network") == ["wpa_cli -i wlan0 set_network 5 key_mgmt WPA-PSK"]
    assert env.wpa("select_network") == ["wpa_cli -i wlan0 select_network 5"]


def test_loop_guard_stops_after_three_fixes_in_60s(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    for _ in range(4):
        assert env.run(FAKE_STICKY="1").returncode == 0
    assert len(env.wpa("set_network")) == 3, env.calls()
    last = env.logs()[-1]
    assert "boucle" in last, env.logs()
    assert len(env.wpa("disconnect")) == 3


def test_stale_stamps_do_not_block_the_fix(env: Env) -> None:
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    env.run_dir.mkdir()
    old = "1000000000\n1000000001\n1000000002\n"
    (env.run_dir / "ap-keymgmt-fixes").write_text(old)
    proc = env.run(FAKE_STICKY="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(env.wpa("set_network")) == 1, env.calls()
    assert "boucle" not in " ".join(env.logs())
    stamps = (env.run_dir / "ap-keymgmt-fixes").read_text().split()
    assert len(stamps) == 1 and int(stamps[0]) > 1000000002


def test_errexit_never_enabled() -> None:
    for line in SCRIPT.read_text().splitlines():
        s = line.strip()
        if s.startswith("set "):
            assert "-e" not in s and "errexit" not in s, line


def test_future_and_junk_stamps_do_not_block_the_fix(env: Env) -> None:
    """Clock stepped back by chrony: stamps in the future are dropped, junk lines ignored."""
    env.set_networks(AP_ROWS)
    env.set_state(SHA)
    env.run_dir.mkdir()
    (env.run_dir / "ap-keymgmt-fixes").write_text("9999999999\n9999999998\n9999999997\nx\n08\n")
    proc = env.run(FAKE_STICKY="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    assert len(env.wpa("set_network")) == 1, env.calls()
