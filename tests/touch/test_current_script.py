"""touch/jabuka-current (`sudo jabuka-current`): Copernicus current step, stubbed PATH.

Every external tool (id, systemctl, systemd-run, nmcli, curl, runuser, chown, sleep, jabuka-wifi,
jabuka-prep, copernicusmarine) is a tiny bash stub that appends `<name> <args>` to $FAKE_CALLS, so
nothing here touches the network, NetworkManager, systemd or Copernicus. The data dir is a tmp copy
of /var/lib/jabuka. The `python` beside the fake jabuka-prep is the dev venv's interpreter, so the
REAL race window code (jabuka.route.racepack) computes the download window.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "touch" / "jabuka-current"
LAUNCH_MSG = "suivre : journalctl -fu jabuka-current ; résultat : sudo jabuka-current status"
NO_PROFILE_MSG = "lancer d'abord sudo jabuka-wifi phone une fois pour enregistrer le mot de passe"
SECRET = "S3CRET-TOKEN-do-not-leak-7f3a"
DATASET = "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m"

RECORD = 'printf "%s\\n" "$(basename "$0") $*" >>"$FAKE_CALLS"\n'

# systemctl is-active: jabuka-current per FAKE_CURRENT_ACTIVE; jabuka-prerace active when
# FAKE_PRERACE_ACTIVE=1, while the flag file $FAKE_PRERACE_FLAG exists, or for the first
# FAKE_PRERACE_POLLS queries.
SYSTEMCTL = (
    RECORD
    + r"""if [ "${1:-}" = "is-active" ]; then
    unit="${*: -1}"
    case "$unit" in
        jabuka-current*) [ "${FAKE_CURRENT_ACTIVE:-0}" = 1 ] && exit 0; exit 3 ;;
        jabuka-prerace*)
            [ "${FAKE_PRERACE_ACTIVE:-0}" = 1 ] && exit 0
            [ -n "${FAKE_PRERACE_FLAG:-}" ] && [ -e "$FAKE_PRERACE_FLAG" ] && exit 0
            if [ -n "${FAKE_PRERACE_POLLS:-}" ]; then
                n=$(cat "$FAKE_PRERACE_COUNT" 2>/dev/null || echo 0); n=$((n + 1))
                echo "$n" >"$FAKE_PRERACE_COUNT"
                [ "$n" -le "$FAKE_PRERACE_POLLS" ] && exit 0
            fi
            exit 3 ;;
    esac
    exit 3
fi
exit 0
"""
)

STUBS = {
    "id": '[ "${1:-}" = "-u" ] && { echo 0; exit 0; }\nexec REAL_ID "$@"\n',
    "systemctl": SYSTEMCTL,
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
    # rsync: optionally modifies the live pack while "copying" (FAKE_RSYNC_MUTATE=1), then copies
    "rsync": RECORD
    + r"""if [ "${FAKE_RSYNC_MUTATE:-0}" = 1 ]; then
    src="${*: -2:1}"
    echo '{"model":"ICON-EU","run":"changed-during-rsync"}' >"${src%/}/wind.json"
fi
exec REAL_RSYNC "$@"
""",
    # mv: fails only when its source is the staging dir (FAKE_MV_FAIL_STAGE=1)
    "mv": r"""for a in "$@"; do
    case "$a" in -*) ;; *) src="$a"; break ;; esac
done
if [ "${FAKE_MV_FAIL_STAGE:-0}" = 1 ] && [ "$(basename "${src:-}")" = racepack.current-new ]; then
    echo "mv: simulated failure" >&2
    exit 1
fi
exec REAL_MV "$@"
""",
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
    current)
        rc="${FAKE_RC_CURRENT:-0}"
        if [ "$rc" != 2 ]; then
            echo npz >"$out/current.npz"
            echo '{"model":"MEDSEA","run":""}' >"$out/current.json"
            echo "Courant : 49 échéances 2026-11-13T11:00Z -> 2026-11-15T11:00Z," \
                "grille 41x44 -> $out/current.npz"
        else
            echo "erreur : fichier courant illisible"
        fi
        exit "$rc" ;;
    check)
        rc="${FAKE_RC_CHECK:-0}"
        printf '%s\n' "${FAKE_COVERAGE:-COUVERTURE MÉTÉO : OK}" >"$out/coverage.txt"
        if [ -n "${FAKE_CHECK_TOUCH:-}" ]; then
            mkdir -p "$(dirname "$FAKE_CHECK_TOUCH")"
            : >"$FAKE_CHECK_TOUCH"
        fi
        if [ "${FAKE_SWAP_DURING_CHECK:-0}" = 1 ]; then
            # a whole `sudo prerace` run (never seen active) swapping the live pack meanwhile
            data="$(dirname "$out")"
            rm -rf "$data/racepack.prev"
            mv "$data/racepack" "$data/racepack.prev"
            mkdir "$data/racepack"
            echo '{"model":"ICON-EU","run":"fresh-prerace"}' >"$data/racepack/wind.json"
            echo "prerace : fresh" >"$data/prerace-last.txt"
        fi
        exit "$rc" ;;
esac
exit 0
"""

# the `python` next to jabuka-prep: the dev interpreter (jabuka is installed there), so the real
# window code runs; FAKE_PY_RC fails it, FAKE_PY_TOUCH creates a file after it ran.
PY_STUB = r"""[ "${FAKE_PY_RC:-0}" = 0 ] || exit "$FAKE_PY_RC"
REAL_PY "$@"
rc=$?
[ -z "${FAKE_PY_TOUCH:-}" ] || { mkdir -p "$(dirname "$FAKE_PY_TOUCH")"; : >"$FAKE_PY_TOUCH"; }
exit "$rc"
"""

CM_STUB = r"""printf '%s\n' "cm $*" >>"$FAKE_CALLS"
dir=""; name=""
while [ $# -gt 0 ]; do
    case "$1" in
        --output-directory) dir="$2"; shift ;;
        --output-filename) name="$2"; shift ;;
    esac
    shift
done
rc="${FAKE_RC_CM:-0}"
if [ "$rc" != 0 ]; then
    echo "ERROR - fake copernicusmarine: invalid credentials"
    exit "$rc"
fi
echo "INFO - fake copernicusmarine: downloading"
printf 'CDF-fake' >"$dir/$name"
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


@dataclass
class Env:
    tmp: Path
    data: Path
    units: Path
    calls_file: Path
    creds: Path
    cm: Path
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
        return (self.data / "current-last.txt").read_text()

    def log(self) -> str:
        p = self.data / "current-last.log"
        return p.read_text() if p.exists() else ""


@pytest.fixture
def env(tmp_path: Path) -> Env:
    data = tmp_path / "data"
    (data / "racepack").mkdir(parents=True)
    (data / "racepack" / "old.txt").write_text("old pack\n")
    (data / "racepack" / "wind.json").write_text('{"model":"ICON-EU","run":"old"}\n')
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    real = {
        "REAL_ID": shutil.which("id") or "/usr/bin/id",
        "REAL_RSYNC": shutil.which("rsync") or "/usr/bin/rsync",
        "REAL_MV": "/usr/bin/mv" if Path("/usr/bin/mv").exists() else "/bin/mv",
    }
    for name, body in STUBS.items():
        for k, v in real.items():
            body = body.replace(k, v)
        _write_exec(fakebin / name, body)
    wifi = tmp_path / "jabuka-wifi"
    _write_exec(wifi, WIFI_STUB)
    prepdir = tmp_path / "prepvenv" / "bin"
    prepdir.mkdir(parents=True)
    prep = prepdir / "jabuka-prep"
    _write_exec(prep, PREP_STUB)
    _write_exec(prepdir / "python", PY_STUB.replace("REAL_PY", sys.executable))
    cm = tmp_path / "cmvenv" / "bin" / "copernicusmarine"
    cm.parent.mkdir(parents=True)
    _write_exec(cm, CM_STUB)
    creds = tmp_path / "root" / ".copernicusmarine" / ".copernicusmarine-credentials"
    creds.parent.mkdir(parents=True)
    creds.write_text(f"[credentials]\nusername=someone\npassword={SECRET}\n")
    units = tmp_path / "run-units"
    units.mkdir()
    calls = tmp_path / "calls.txt"
    base = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "CURRENT_"))}
    base.update(
        PATH=f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        CURRENT_DATA_DIR=str(data),
        CURRENT_PREP=str(prep),
        CURRENT_WIFI=str(wifi),
        CURRENT_CM=str(cm),
        CURRENT_CREDS=str(creds),
        CURRENT_RUN_UNITS=str(units),
        FAKE_CALLS=str(calls),
        FAKE_CURL_COUNT=str(tmp_path / "curl-count"),
        FAKE_PRERACE_COUNT=str(tmp_path / "prerace-count"),
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

    return Env(
        tmp=tmp_path,
        data=data,
        units=units,
        calls_file=calls,
        creds=creds,
        cm=cm,
        base_env=base,
        run=run,
    )


def _index(calls: list[str], prefix: str) -> int:
    for i, c in enumerate(calls):
        if c.startswith(prefix):
            return i
    raise AssertionError(f"no call starting with {prefix!r} in {calls}")


def _wifi(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("wifi ")]


def _prep(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("prep ")]


def _cm(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("cm ")]


def _opts(argv: list[str]) -> dict[str, list[str]]:
    """--flag value pairs (repeatable) and bare --flags (empty list) of a recorded argv."""
    out: dict[str, list[str]] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                out.setdefault(a, []).append(argv[i + 1])
                i += 2
                continue
            out.setdefault(a, [])
        i += 1
    return out


def _restarted(calls: list[str]) -> bool:
    return any(c.startswith("systemctl restart") for c in calls)


# -- static -----------------------------------------------------------------------------------


def test_bash_syntax() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_script_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)


def test_help_prints_usage(env: Env) -> None:
    proc = env.run("--help")
    assert proc.returncode == 0
    assert "sudo jabuka-current status" in proc.stdout
    assert "--after-prerace" in proc.stdout


# -- launch -----------------------------------------------------------------------------------


def test_launch_detaches_as_a_transient_unit(env: Env) -> None:
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    runs = [c for c in env.calls() if c.startswith("systemd-run ")]
    assert len(runs) == 1, env.calls()
    argv = runs[0].split()
    for token in (
        "--unit=jabuka-current",
        "--collect",
        "--property=RuntimeMaxSec=5400",
        str(SCRIPT.resolve()),
        "_run",
    ):
        assert token in argv, (token, runs[0])
    assert LAUNCH_MSG in proc.stdout
    assert not _cm(env.calls()) and not _prep(env.calls())


# -- the detached body ------------------------------------------------------------------------


def test_happy_path_with_internet(env: Env) -> None:
    proc = env.run("_run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = env.calls()
    cms = _cm(calls)
    assert len(cms) == 1, calls
    argv = shlex.split(cms[0])[1:]
    assert argv[0] == "subset"
    o = _opts(argv)
    assert o["--dataset-id"] == [DATASET]
    assert o["--variable"] == ["uo", "vo"]
    assert o["--minimum-longitude"] == ["14.75"]
    assert o["--maximum-longitude"] == ["16.55"]
    assert o["--minimum-latitude"] == ["42.55"]
    assert o["--maximum-latitude"] == ["44.25"]
    assert o["--start-datetime"] == ["2026-11-13T11:00:00"]
    assert o["--end-datetime"] == ["2026-11-15T11:00:00"]
    assert o["--output-directory"] == [f"{env.data}/cache/current"]
    assert o["--output-filename"] == ["current_med.nc"]
    assert o["--credentials-file"] == [str(env.creds)]
    assert "--overwrite" in o and "--disable-progress-bar" in o
    order = [
        _index(calls, "cm subset"),
        _index(calls, "prep current"),
        _index(calls, "prep check"),
        _index(calls, "systemctl restart jabuka-core"),
    ]
    assert order == sorted(order), calls
    preps = _prep(calls)
    assert len(preps) == 2
    assert preps[0].startswith(f"prep current {env.data}/cache/current/current_med.nc")
    for c in preps:
        assert f"--out {env.data}/racepack.current-new" in c, c
    runusers = [c for c in calls if c.startswith("runuser ")]
    assert runusers and all(c.startswith("runuser -u jabuka -- ") for c in runusers)
    assert (env.pack / "current.npz").is_file()
    assert (env.pack / "old.txt").is_file()
    assert (env.data / "racepack.prev" / "old.txt").is_file()
    assert not (env.data / "racepack.prev" / "current.npz").exists()
    assert not (env.data / "racepack.current-new").exists()
    assert not (env.data / "cache" / "current" / "current_med.nc").exists()
    assert not _wifi(calls)
    res = env.result()
    assert res.startswith("courant : ")
    assert "résultat : OK" in res
    assert "code : 0" in res
    assert "2026-11-13T11:00:00 -> 2026-11-15T11:00:00 UTC" in res
    assert "fichier : Courant : 49 échéances" in res
    assert "résultat : OK" in proc.stdout  # the result is also printed to the journal


def test_secret_never_leaks(env: Env) -> None:
    for args, extra in ((("_run",), {}), (("_run",), {"FAKE_RC_CM": "1"}), (("status",), {})):
        proc = env.run(*args, **extra)
        for text in (proc.stdout, proc.stderr, env.result(), env.log()):
            assert SECRET not in text
        assert SECRET not in env.calls_file.read_text()
