"""deploy/prerace (`sudo prerace`): weather prep on the Pi, run against a stubbed PATH.

Every external tool (id, systemctl, systemd-run, nmcli, curl, runuser, chown, sleep, jabuka-wifi,
jabuka-prep) is a tiny bash stub that appends `<name> <args>` to $FAKE_CALLS, so nothing here
touches the network, NetworkManager or systemd. The data dir is a tmp copy of /var/lib/jabuka.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "prerace"
LAUNCH_MSG = "suivre : journalctl -fu jabuka-prerace ; résultat : sudo prerace status"
NO_PROFILE_MSG = "lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de passe"
HAVE_JQ = shutil.which("jq") is not None

RECORD = 'printf "%s\\n" "$(basename "$0") $*" >>"$FAKE_CALLS"\n'

STUBS = {
    "id": '[ "${1:-}" = "-u" ] && { echo 0; exit 0; }\nexec REAL_ID "$@"\n',
    "systemctl": RECORD
    + 'if [ "${1:-}" = "is-active" ]; then exit "${FAKE_ACTIVE_RC:-3}"; fi\nexit 0\n',
    "systemd-run": RECORD + "exit 0\n",
    "nmcli": RECORD + 'echo jabuka-ap\n[ "${FAKE_PHONE:-0}" = 1 ] && echo jabuka-phone\nexit 0\n',
    "curl": RECORD
    + 'n=$(cat "$FAKE_CURL_COUNT" 2>/dev/null || echo 0); n=$((n + 1))\n'
    + 'echo "$n" >"$FAKE_CURL_COUNT"\n'
    + 'f="${FAKE_CURL_FAILS:-0}"\n'
    + '[ "$f" = always ] && exit 7\n[ "$n" -le "$f" ] && exit 7\nexit 0\n',
    "runuser": RECORD
    + 'while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n',
    "chown": RECORD + "exit 0\n",
    "sleep": RECORD + "exit 0\n",
}

WIFI_STUB = 'printf "%s\\n" "wifi $*" >>"$FAKE_CALLS"\nexit 0\n'

PREP_STUB = r"""printf '%s\n' "prep $*" >>"$FAKE_CALLS"
cmd="$1"; shift
out=""
while [ $# -gt 0 ]; do
    case "$1" in --out) out="$2"; shift ;; esac
    shift
done
case "$cmd" in
    wind)
        rc="${FAKE_RC_WIND:-0}"
        if [ "$rc" != 2 ]; then
            echo '{"model":"ICON-EU","run":"2026-11-13T12:00:00Z"}' >"$out/wind.json"
            echo npz >"$out/wind.npz"
        fi
        echo "fake wind done"
        exit "$rc" ;;
    waves)
        rc="${FAKE_RC_WAVES:-0}"
        [ "$rc" = 2 ] || echo '{"model":"EWAM","run":"2026-11-13T00:00:00Z"}' >"$out/waves.json"
        exit "$rc" ;;
    grib)
        echo '{"model":"organiser","run":"?"}' >"$out/wind_organiser.json"
        exit 0 ;;
    check)
        rc="${FAKE_RC_CHECK:-0}"
        if [ "$rc" = 3 ]; then
            echo "MÉTÉO INCOMPLÈTE : test" >"$out/coverage.txt"
        else
            echo "COUVERTURE MÉTÉO : OK" >"$out/coverage.txt"
        fi
        exit "$rc" ;;
esac
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@dataclass
class Env:
    tmp: Path
    data: Path
    calls_file: Path
    base_env: dict[str, str]
    run: Callable[..., subprocess.CompletedProcess[str]]

    @property
    def pack(self) -> Path:
        return self.data / "racepack"

    def calls(self) -> list[str]:
        if not self.calls_file.exists():
            return []
        return self.calls_file.read_text().splitlines()

    def result(self) -> str:
        return (self.data / "prerace-last.txt").read_text()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    data = tmp_path / "data"
    (data / "racepack").mkdir(parents=True)
    (data / "racepack" / "old.txt").write_text("old pack\n")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    real_id = shutil.which("id") or "/usr/bin/id"
    for name, body in STUBS.items():
        _write_exec(fakebin / name, body.replace("REAL_ID", real_id))
    wifi = tmp_path / "jabuka-wifi"
    _write_exec(wifi, WIFI_STUB)
    prep = tmp_path / "jabuka-prep"
    _write_exec(prep, PREP_STUB)
    calls = tmp_path / "calls.txt"
    base = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "PRERACE_"))}
    base.update(
        PATH=f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        PRERACE_DATA_DIR=str(data),
        PRERACE_PREP=str(prep),
        PRERACE_WIFI=str(wifi),
        FAKE_CALLS=str(calls),
        FAKE_CURL_COUNT=str(tmp_path / "curl-count"),
        LC_ALL="C.UTF-8",
    )

    def run(*args: str, cwd: Path | None = None, **extra: str) -> subprocess.CompletedProcess[str]:
        e = dict(base)
        e.update(extra)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            env=e,
            cwd=cwd or tmp_path,
        )

    return Env(tmp=tmp_path, data=data, calls_file=calls, base_env=base, run=run)


def _index(calls: list[str], prefix: str) -> int:
    for i, c in enumerate(calls):
        if c.startswith(prefix):
            return i
    raise AssertionError(f"no call starting with {prefix!r} in {calls}")


def _wifi(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("wifi ")]


def _prep(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("prep ")]


# -- static -----------------------------------------------------------------------------------


def test_bash_syntax() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_prerace_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)


def test_never_handles_the_phone_password() -> None:
    text = SCRIPT.read_text().lower()
    assert "psk" not in text
    assert "wifi-sec" not in text


# -- launch (U-10) ----------------------------------------------------------------------------


def test_launch_detaches_as_a_transient_unit(env: Env) -> None:
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    runs = [c for c in env.calls() if c.startswith("systemd-run ")]
    assert len(runs) == 1, env.calls()
    for token in ("--unit=jabuka-prerace", "--collect", str(SCRIPT.resolve()), "_run"):
        assert token in runs[0], (token, runs[0])
    assert LAUNCH_MSG in proc.stdout
    assert not _prep(env.calls())


def test_launch_refuses_while_a_run_is_active(env: Env) -> None:
    proc = env.run(FAKE_ACTIVE_RC="0")
    assert proc.returncode != 0
    assert "déjà en cours" in proc.stderr
    assert not [c for c in env.calls() if c.startswith("systemd-run ")]


def test_launch_with_organiser_passes_an_absolute_path(env: Env) -> None:
    (env.tmp / "rel").mkdir()
    grb = env.tmp / "rel" / "file.grb"
    grb.write_bytes(b"GRIB")
    proc = env.run("--organiser", "rel/file.grb", cwd=env.tmp)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    runs = [c for c in env.calls() if c.startswith("systemd-run ")]
    assert len(runs) == 1
    assert f"--organiser {grb.resolve()}" in runs[0]


def test_launch_with_missing_organiser_file_fails(env: Env) -> None:
    proc = env.run("--organiser", "nope.grb", cwd=env.tmp)
    assert proc.returncode != 0
    assert not [c for c in env.calls() if c.startswith("systemd-run ")]


def test_unknown_argument_exits_2(env: Env) -> None:
    proc = env.run("--bogus")
    assert proc.returncode == 2
    assert not [c for c in env.calls() if c.startswith("systemd-run ")]


# -- the detached body (U-11..U-14) -------------------------------------------------------------


def test_happy_path_with_internet(env: Env) -> None:
    proc = env.run("_run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (env.pack / "wind.json").is_file()
    assert (env.data / "racepack.prev" / "old.txt").is_file()
    assert not (env.data / "racepack.new").exists()
    calls = env.calls()
    order = [
        _index(calls, "prep wind"),
        _index(calls, "prep waves"),
        _index(calls, "prep check"),
        _index(calls, "systemctl restart jabuka-core"),
    ]
    assert order == sorted(order), calls
    for c in _prep(calls):
        assert f"--out {env.data}/racepack.new" in c, c
        assert f"--cache {env.data}/cache/prep" in c, c
    assert not _wifi(calls)
    res = env.result()
    assert "OK" in res
    assert "code : 0" in res
    assert "COUVERTURE MÉTÉO : OK" in res
    if HAVE_JQ:
        assert "ICON-EU run 2026-11-13T12:00:00Z" in res
    # the result is also printed to the journal
    assert "résultat : OK" in proc.stdout


def test_exactly_one_prev_is_kept(env: Env) -> None:
    assert env.run("_run").returncode == 0
    (env.pack / "old.txt").unlink()
    (env.pack / "run1.txt").write_text("first run\n")
    assert env.run("_run").returncode == 0
    prev = env.data / "racepack.prev"
    assert (prev / "run1.txt").is_file()
    assert not (prev / "old.txt").exists()
    assert (prev / "wind.json").is_file()
    packs = sorted(p.name for p in env.data.iterdir() if p.name.startswith("racepack"))
    assert packs == ["racepack", "racepack.prev"]


def test_incomplete_weather_is_installed_and_reported(env: Env) -> None:
    proc = env.run("_run", FAKE_RC_CHECK="3")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert (env.pack / "wind.json").is_file()
    assert any(c.startswith("systemctl restart jabuka-core") for c in env.calls())
    assert "MÉTÉO INCOMPLÈTE" in env.result()
    assert "!!! MÉTÉO INCOMPLÈTE" in proc.stdout


def test_wind_failure_keeps_the_old_pack(env: Env) -> None:
    proc = env.run("_run", FAKE_RC_WIND="2")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert (env.pack / "old.txt").is_file()
    assert not (env.pack / "wind.json").exists()
    assert not (env.data / "racepack.prev").exists()
    assert not (env.data / "racepack.new").exists()
    assert not [c for c in env.calls() if c.startswith("systemctl restart")]
    assert not [c for c in env.calls() if c.startswith("prep check")]
    res = env.result()
    assert "ÉCHEC" in res
    assert "fake wind done" in res  # the journal tail is in the result on failure


def test_waves_failure_is_not_fatal(env: Env) -> None:
    proc = env.run("_run", FAKE_RC_WAVES="2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (env.pack / "wind.json").is_file()
    assert "vagues : échec (code 2)" in env.result()


def test_no_internet_and_no_phone_profile(env: Env) -> None:
    proc = env.run("_run", FAKE_CURL_FAILS="always")
    assert proc.returncode == 2
    assert NO_PROFILE_MSG in proc.stdout + proc.stderr
    assert not _wifi(env.calls())
    assert not _prep(env.calls())
    assert sorted(p.name for p in env.pack.iterdir()) == ["old.txt"]
    assert not (env.data / "racepack.new").exists()
    assert NO_PROFILE_MSG in env.result()


def test_no_internet_switches_to_the_phone_and_back(env: Env) -> None:
    proc = env.run("_run", FAKE_CURL_FAILS="2", FAKE_PHONE="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = env.calls()
    assert _index(calls, "wifi _switch phone") < _index(calls, "prep wind")
    wifi = _wifi(calls)
    assert wifi[-1] == "wifi _switch ap"
    last_wifi = max(i for i, c in enumerate(calls) if c.startswith("wifi "))
    assert last_wifi > _index(calls, "systemctl restart jabuka-core")
    assert "retour au point d'accès" in env.result()


def test_phone_without_internet_still_returns_to_the_ap(env: Env) -> None:
    proc = env.run("_run", FAKE_CURL_FAILS="always", FAKE_PHONE="1")
    assert proc.returncode == 2
    calls = env.calls()
    assert "wifi _switch phone" in calls
    assert _wifi(calls)[-1] == "wifi _switch ap"
    assert not _prep(calls)
    assert sorted(p.name for p in env.pack.iterdir()) == ["old.txt"]
    curls = [c for c in calls if c.startswith("curl ")]
    sleeps = [c for c in calls if c.startswith("sleep ")]
    assert 2 <= len(curls) <= 13, len(curls)
    assert len(sleeps) <= 12
    assert "partage du téléphone" in env.result()


def test_organiser_grib_is_kept_beside_the_pack(env: Env) -> None:
    grb = env.tmp / "org.grb"
    grb.write_bytes(b"GRIB")
    proc = env.run("_run", "--organiser", str(grb))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    grib = [c for c in env.calls() if c.startswith("prep grib ")]
    assert len(grib) == 1
    assert f"prep grib {env.data}/cache/prep/org.grb --name wind_organiser" in grib[0]
    assert (env.pack / "wind_organiser.json").is_file()
    assert (env.pack / "wind.json").is_file()
    assert grb.is_file()  # the user's file is never moved


# -- status (U-14) --------------------------------------------------------------------------------


def test_status_without_any_run(env: Env) -> None:
    proc = env.run("status")
    assert proc.returncode == 0
    assert "aucune préparation enregistrée" in proc.stdout


def test_status_shows_the_last_result(env: Env) -> None:
    assert env.run("_run").returncode == 0
    proc = env.run("status")
    assert proc.returncode == 0
    assert proc.stdout.strip().endswith(env.result().strip())
    assert "résultat : OK" in proc.stdout


def test_status_says_when_a_run_is_in_progress(env: Env) -> None:
    proc = env.run("status", FAKE_ACTIVE_RC="0")
    assert proc.returncode == 0
    assert "en cours : journalctl -fu jabuka-prerace" in proc.stdout
