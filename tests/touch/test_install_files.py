"""Packaging of jabuka-touch: unit, wrapper, example config, install/uninstall (DESTDIR dry runs
with a fake systemctl and a stub python; never for real here)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from jabuka_touch import config

TOUCH = Path(__file__).resolve().parents[2] / "touch"
UNIT = TOUCH / "jabuka-touch.service"


def _lines(path: Path) -> list[str]:
    return [
        ln.strip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def test_unit_is_isolated_from_navigation() -> None:
    lines = _lines(UNIT)
    for needed in (
        "Conflicts=getty@tty1.service",
        "Nice=10",
        "Restart=on-failure",
        "RestartMode=direct",
        "WorkingDirectory=/opt/jabuka-touch",
        "ExecStart=/usr/bin/python3 -s -m jabuka_touch run",
        "ExecStopPost=/usr/bin/python3 -s -m jabuka_touch restore-console",
        "OnFailure=getty@tty1.service",
        "WantedBy=multi-user.target",
    ):
        assert needed in lines, needed
    assert any(ln.startswith("MemoryMax=") for ln in lines)
    for ln in lines:
        key = ln.split("=", 1)[0]
        if key in ("Requires", "BindsTo", "PartOf", "Requisite", "After", "Wants"):
            assert "jabuka-core" not in ln and "jabuka-ingest-fastnet" not in ln, ln


def test_example_config_is_the_defaults() -> None:
    data = json.loads((TOUCH / "jabuka-touch.example.json").read_text())
    assert data == config.defaults_dict()


@pytest.mark.parametrize("name", ["install.sh", "uninstall.sh", "jabuka-touch", "jabuka-current"])
def test_scripts_syntax_and_no_boot_partition(name: str) -> None:
    p = subprocess.run(["bash", "-n", str(TOUCH / name)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    text = "\n".join(_lines(TOUCH / name))  # non-comment lines
    for forbidden in ("/boot", "config.txt", "cmdline.txt", "/opt/jabuka/", "deploy/"):
        assert forbidden not in text, (name, forbidden)
    assert os.access(TOUCH / name, os.X_OK)


def test_wrapper_usage() -> None:
    p = subprocess.run(
        ["bash", str(TOUCH / "jabuka-touch"), "--help"], capture_output=True, text=True
    )
    assert p.returncode == 0
    for word in ("menu", "status", "course", "calibrate"):
        assert word in p.stdout
    text = (TOUCH / "jabuka-touch").read_text()
    assert "jabuka_touch race-mode" in text and "jabuka_touch calibrate" in text
    assert "systemctl start jabuka-touch.service" in text


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    log = tmp_path / "log.txt"
    fake_ctl = tmp_path / "fake-systemctl"
    fake_ctl.write_text(f'#!/usr/bin/env bash\necho "systemctl $*" >> "{log}"\n')
    fake_ctl.chmod(0o755)
    stub_py = tmp_path / "stub-python"
    stub_py.write_text(f'#!/usr/bin/env bash\necho "python $* (cwd $(pwd))" >> "{log}"\nexit 0\n')
    stub_py.chmod(0o755)
    # CM_PYTHON: `-m venv DIR` creates DIR/bin/pip; that pip logs its arguments and, on install,
    # creates DIR/bin/copernicusmarine (version 2.5.1); its exit code comes from FAKE_PIP_RC.
    cm_py = tmp_path / "cm-python"
    cm_py.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "cmpython $*" >> "{log}"\n'
        '[ "$1 $2" = "-m venv" ] || exit 1\n'
        'mkdir -p "$3/bin"\n'
        "cat >\"$3/bin/pip\" <<'PIP'\n"
        "#!/usr/bin/env bash\n"
        'echo "pip $*" >> "$LOG"\n'
        'rc="${FAKE_PIP_RC:-0}"\n'
        'if [ "$1" = install ] && [ "$rc" = 0 ]; then\n'
        "    printf '#!/usr/bin/env bash\\necho \"copernicusmarine, version 2.5.1\"\\n' "
        '>"$(dirname "$0")/copernicusmarine"\n'
        '    chmod 755 "$(dirname "$0")/copernicusmarine"\n'
        "fi\n"
        'exit "$rc"\n'
        "PIP\n"
        'chmod 755 "$3/bin/pip"\n'
    )
    cm_py.chmod(0o755)
    stubs = tmp_path / "stubbin"
    stubs.mkdir()
    curl = stubs / "curl"
    curl.write_text(
        f'#!/usr/bin/env bash\necho "curl $*" >> "{log}"\nexit "${{FAKE_CURL_RC:-0}}"\n'
    )
    curl.chmod(0o755)
    dest = tmp_path / "root"
    dest.mkdir()
    return {
        **os.environ,
        "PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "DESTDIR": str(dest),
        "SYSTEMCTL": str(fake_ctl),
        "TOUCH_PYTHON": str(stub_py),
        "CM_PYTHON": str(cm_py),
        "LOG": str(log),
    }


def _sh(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(TOUCH / script)], capture_output=True, text=True, env=env, timeout=60
    )


def _log(env: dict[str, str]) -> list[str]:
    p = Path(env["LOG"])
    return p.read_text().splitlines() if p.exists() else []


def test_install_dry_run_idempotent_and_uninstall(env: dict[str, str]) -> None:
    dest = Path(env["DESTDIR"])
    p = _sh("install.sh", env)
    assert p.returncode == 0, p.stderr
    pkg = dest / "opt/jabuka-touch/jabuka_touch"
    assert (pkg / "__main__.py").is_file() and (pkg / "demo_wind.py").is_file()
    assert not list(pkg.rglob("__pycache__"))
    assert (pkg / "ui.py").stat().st_mode & 0o777 == 0o644
    unit = dest / "etc/systemd/system/jabuka-touch.service"
    assert unit.read_text() == UNIT.read_text() and unit.stat().st_mode & 0o777 == 0o644
    wrapper = dest / "usr/local/sbin/jabuka-touch"
    assert wrapper.stat().st_mode & 0o777 == 0o755
    conf = dest / "etc/jabuka-touch.json"
    assert json.loads(conf.read_text()) == config.defaults_dict()
    assert _log(env)[-3:] == [
        "systemctl daemon-reload",
        "systemctl enable jabuka-touch.service",
        "systemctl restart jabuka-touch.service",
    ]
    assert any(ln.startswith("python -c import PIL, numpy") for ln in _log(env))
    # an edited config survives a second run; the package is replaced
    conf.write_text('{"night": true}\n')
    (pkg / "stale.py").write_text("x")
    p = _sh("install.sh", env)
    assert p.returncode == 0, p.stderr
    assert conf.read_text() == '{"night": true}\n'
    assert not (pkg / "stale.py").exists()
    assert "gardée" in p.stdout
    # uninstall without a demo: no race-mode call, the config is kept
    Path(env["LOG"]).write_text("")
    p = _sh("uninstall.sh", env)
    assert p.returncode == 0, p.stderr
    log = _log(env)
    assert not any("race-mode" in ln for ln in log)
    assert log == [
        "systemctl disable --now jabuka-touch.service",
        "systemctl daemon-reload",
        "systemctl start getty@tty1.service",
    ]
    assert not (dest / "opt/jabuka-touch").exists() and not unit.exists() and not wrapper.exists()
    assert conf.exists()


def test_uninstall_runs_race_mode_first_when_a_demo_runs(env: dict[str, str]) -> None:
    dest = Path(env["DESTDIR"])
    assert _sh("install.sh", env).returncode == 0
    d = dest / "run/systemd/system/jabuka-core.service.d"
    d.mkdir(parents=True)
    (d / "zz-jabuka-touch-demo.conf").write_text("[Service]\n")
    Path(env["LOG"]).write_text("")
    p = _sh("uninstall.sh", env)
    assert p.returncode == 0, p.stderr
    log = _log(env)
    assert log[0].startswith("python -s -m jabuka_touch race-mode")
    assert log[0].endswith(f"(cwd {dest / 'opt/jabuka-touch'})")
    assert log[1] == "systemctl disable --now jabuka-touch.service"


def test_uninstall_stops_when_race_mode_fails(env: dict[str, str], tmp_path: Path) -> None:
    dest = Path(env["DESTDIR"])
    assert _sh("install.sh", env).returncode == 0
    d = dest / "run/systemd/system/jabuka-ingest-fastnet.service.d"
    d.mkdir(parents=True)
    (d / "zz-jabuka-touch-demo.conf").write_text("[Service]\n")
    failing = tmp_path / "failing-python"
    failing.write_text("#!/usr/bin/env bash\nexit 1\n")
    failing.chmod(0o755)
    p = _sh("uninstall.sh", {**env, "TOUCH_PYTHON": str(failing)})
    assert p.returncode != 0 and "redémarrer le Pi" in p.stderr
    assert (dest / "opt/jabuka-touch/jabuka_touch").is_dir()


def test_install_refuses_without_pillow(env: dict[str, str], tmp_path: Path) -> None:
    failing = tmp_path / "no-pil-python"
    failing.write_text("#!/usr/bin/env bash\nexit 1\n")
    failing.chmod(0o755)
    p = _sh("install.sh", {**env, "TOUCH_PYTHON": str(failing)})
    assert p.returncode != 0 and "python3-pil" in p.stderr
    assert not (Path(env["DESTDIR"]) / "opt/jabuka-touch").exists()


# -- jabuka-current + copernicusmarine venv -------------------------------------------------------


def test_constraints_pin_everything() -> None:
    lines = _lines(TOUCH / "copernicusmarine-constraints.txt")
    assert "copernicusmarine==2.5.1" in lines
    assert len(lines) >= 60
    for ln in lines:
        name, _, version = ln.partition("==")
        assert name and version and " " not in ln, ln


def test_install_current_and_copernicusmarine_venv(env: dict[str, str]) -> None:
    dest = Path(env["DESTDIR"])
    p = _sh("install.sh", env)
    assert p.returncode == 0, p.stderr
    script = dest / "usr/local/sbin/jabuka-current"
    assert script.read_bytes() == (TOUCH / "jabuka-current").read_bytes()
    assert script.stat().st_mode & 0o777 == 0o755
    venv = dest / "opt/copernicusmarine/venv"
    log = _log(env)
    assert f"cmpython -m venv {venv}" in log
    pips = [ln for ln in log if ln.startswith("pip ")]
    assert len(pips) == 1, log
    argv = pips[0].split()
    assert argv[1] == "install" and "--only-binary=:all:" in argv
    assert argv[argv.index("-c") + 1] == str(TOUCH / "copernicusmarine-constraints.txt")
    assert argv[-1] == "copernicusmarine==2.5.1"
    assert (venv / "bin/copernicusmarine").is_file()
    assert log[-3:] == [
        "systemctl daemon-reload",
        "systemctl enable jabuka-touch.service",
        "systemctl restart jabuka-touch.service",
    ]
    assert not (dest / "opt/jabuka").exists() and not (dest / "opt/jabuka-prep").exists()
    assert "copernicusmarine login" in p.stdout
    # second run: already there, pip is not called again
    Path(env["LOG"]).write_text("")
    p = _sh("install.sh", env)
    assert p.returncode == 0, p.stderr
    assert "copernicusmarine 2.5.1 déjà installé" in p.stdout
    assert not [ln for ln in _log(env) if ln.startswith(("pip ", "cmpython ", "curl "))]
    # uninstall removes the script, keeps the venv
    p = _sh("uninstall.sh", env)
    assert p.returncode == 0, p.stderr
    assert not script.exists()
    assert (venv / "bin/copernicusmarine").is_file()
    assert "/opt/copernicusmarine" in p.stdout


def test_install_without_internet_still_installs_the_menu(env: dict[str, str]) -> None:
    dest = Path(env["DESTDIR"])
    p = _sh("install.sh", {**env, "FAKE_CURL_RC": "7"})
    assert p.returncode == 0, p.stderr
    assert "copernicusmarine NON installé" in p.stdout + p.stderr
    assert "pas d'internet" in p.stdout + p.stderr
    assert not [ln for ln in _log(env) if ln.startswith(("pip ", "cmpython "))]
    assert (dest / "usr/local/sbin/jabuka-current").is_file()
    assert (dest / "opt/jabuka-touch/jabuka_touch/__main__.py").is_file()
    assert _log(env)[-1] == "systemctl restart jabuka-touch.service"


def test_install_pip_failure_is_not_fatal(env: dict[str, str]) -> None:
    dest = Path(env["DESTDIR"])
    p = _sh("install.sh", {**env, "FAKE_PIP_RC": "1"})
    assert p.returncode == 0, p.stderr
    assert "copernicusmarine NON installé" in p.stdout + p.stderr
    assert not (dest / "opt/copernicusmarine/venv/bin/copernicusmarine").exists()
    assert (dest / "usr/local/sbin/jabuka-current").is_file()
    assert _log(env)[-3:] == [
        "systemctl daemon-reload",
        "systemctl enable jabuka-touch.service",
        "systemctl restart jabuka-touch.service",
    ]
