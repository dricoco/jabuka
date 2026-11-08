"""Code identity of a soak run (plan 04-04, 04-VERIFICATION gap 1, review WR-03).

The report names the jabuka package that actually ran by a sha256 fingerprint. Its single
definition is the shell pipeline jabuka.soak.report.FINGERPRINT_SH; the Python implementation
(harness), the freeze-check helper and the docs must all give the same hex.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jabuka.soak import report as rep
from jabuka.soak.scenario import load_scenario
from jabuka.tools import soak

REPO = Path(__file__).resolve().parents[2]


def _shell_fingerprint(pkg: Path) -> str:
    out = subprocess.run(
        ["bash", "-c", rep.FINGERPRINT_SH], cwd=pkg, capture_output=True, text=True, check=True
    ).stdout
    return out.split()[0]


def _package(root: Path) -> Path:
    """A package whose names sort differently in the C locale and in en_US (case, '_', digits)."""
    pkg = root / "pkg"
    files = {
        "__init__.py": b"",
        "A_mod.py": b"A = 1\n",
        "a_mod.py": b"a = 1\n",
        "_priv.py": b"P = 0\n",
        "9lives.txt": b"nine\n",
        "Zeta/x1.py": b"x = 1\n",
        "sub_dir/B.py": b"b = 2\n",
        "sub/x10.py": b"x = 10\n",
        "sub/x2.py": b"x = 2\n",
        "web/static/app.js": b"console.log(1)\n",
    }
    for rel, data in files.items():
        p = pkg / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return pkg


def _add_pyc(pkg: Path) -> None:
    (pkg / "__pycache__").mkdir(exist_ok=True)
    (pkg / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"\x00compiled")
    (pkg / "sub" / "__pycache__").mkdir(exist_ok=True)
    (pkg / "sub" / "__pycache__" / "x2.cpython-313.pyc").write_bytes(b"\x01")
    (pkg / "stale.pyc").write_bytes(b"\x02stale")


# -- fingerprint parity --------------------------------------------------------------------------
def test_fingerprint_matches_the_shell_pipeline(tmp_path: Path) -> None:
    pkg = _package(tmp_path)
    fp = rep.package_fingerprint(pkg)
    assert fp["sha256"] == _shell_fingerprint(pkg)
    assert fp["files"] == 10
    assert fp["package_dir"] == str(pkg)


def test_fingerprint_ignores_compiled_files(tmp_path: Path) -> None:
    pkg = _package(tmp_path)
    before = rep.package_fingerprint(pkg)["sha256"]
    _add_pyc(pkg)
    after = rep.package_fingerprint(pkg)
    assert after["sha256"] == before == _shell_fingerprint(pkg)
    assert after["files"] == 10
    for p in [*pkg.rglob("*.pyc")]:
        p.unlink()
    assert rep.package_fingerprint(pkg)["sha256"] == before


def test_fingerprint_changes_with_one_byte(tmp_path: Path) -> None:
    pkg = _package(tmp_path)
    before = rep.package_fingerprint(pkg)["sha256"]
    (pkg / "sub_dir" / "B.py").write_bytes(b"b = 3\n")
    after = rep.package_fingerprint(pkg)["sha256"]
    assert after != before
    assert after == _shell_fingerprint(pkg)


def test_fingerprint_entries_sorts_by_bytes_and_skips_compiled() -> None:
    entries = [("b.py", b"1"), ("B.py", b"2"), ("_x.py", b"3"), ("__pycache__/b.pyc", b"4")]
    hexd, n = rep.fingerprint_entries(entries)
    assert n == 3
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
        for name, data in sorted(entries[:3], key=lambda e: ("./" + e[0]).encode())
    )
    assert hexd == hashlib.sha256(manifest.encode()).hexdigest()


def test_fingerprint_of_this_checkout_matches_the_shell(tmp_path: Path) -> None:
    pkg = REPO / "src" / "jabuka"
    assert rep.package_fingerprint(pkg)["sha256"] == _shell_fingerprint(pkg)


# -- locating the package that runs ---------------------------------------------------------------
def test_locate_package_of_this_interpreter() -> None:
    assert rep.locate_package(sys.executable) == (REPO / "src" / "jabuka").resolve()


def test_locate_package_reports_a_missing_interpreter(tmp_path: Path) -> None:
    with pytest.raises(rep.CodeIdentityError):
        rep.locate_package(str(tmp_path / "nope" / "python"))


def _venv(root: Path, *pythons: str) -> Path:
    venv = root / "venv"
    (venv / "bin").mkdir(parents=True)
    for py in pythons:
        pkg = venv / "lib" / py / "site-packages" / "jabuka"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("X = 1\n")
    return venv


def test_venv_package_finds_the_installed_jabuka(tmp_path: Path) -> None:
    venv = _venv(tmp_path, "python3.13")
    got = rep.venv_package(venv / "bin" / "jabuka-core")
    assert got == venv / "lib" / "python3.13" / "site-packages" / "jabuka"


def test_venv_package_refuses_none_or_two(tmp_path: Path) -> None:
    empty = tmp_path / "a"
    (empty / "venv" / "bin").mkdir(parents=True)
    with pytest.raises(rep.CodeIdentityError):
        rep.venv_package(empty / "venv" / "bin" / "jabuka-core")
    two = _venv(tmp_path / "b", "python3.13", "python3.14")
    with pytest.raises(rep.CodeIdentityError):
        rep.venv_package(two / "bin" / "jabuka-core")


def test_code_identity_block(tmp_path: Path) -> None:
    pkg = _package(tmp_path)
    code = rep.code_identity(pkg, python="/x/python", source="children")
    assert code["algorithm"] == rep.FINGERPRINT_ALGO == "sha256sum-v1"
    assert code["sha256"] == _shell_fingerprint(pkg)
    assert code["files"] == 10
    assert code["python"] == "/x/python" and code["source"] == "children"
    assert code["units"] is None
    md = rep.render_md({"git": {"head": None, "dirty": None}, "code": code})
    assert f"- Code : empreinte {code['sha256'][:12]} (10 fichiers" in md
    md = rep.render_md({"git": {}, "code": None, "code_error": "no venv"})
    assert "- Code : aucune empreinte (no venv)" in md


# -- the harness records the units' package in system scope ---------------------------------------
def _stub(tmp_path: Path, *, ingest_venv: Path | None = None, unit_err: bool = False):
    venv = _venv(tmp_path, "python3.13")
    other = ingest_venv or venv
    hexes = {"jabuka-core.service": "a" * 64, "jabuka-ingest-fastnet.service": "b" * 64}

    def installed_argv(role: str) -> list[str]:
        if role == "core":
            return [str(venv / "bin" / "jabuka-core"), "--http-port", "80"]
        return [str(other / "bin" / "jabuka-ingest-fastnet"), "--device", "/dev/fastnet"]

    def unit_sha(unit: str) -> str:
        if unit_err:
            raise rep.CodeIdentityError(f"{unit}: no FragmentPath")
        return hexes[unit]

    stub = SimpleNamespace(
        scope="system",
        py="/opt/jabuka/venv/bin/python",
        code=None,
        code_error=None,
        _installed_argv=installed_argv,
        _unit_file_sha256=unit_sha,
    )
    return stub, venv, hexes


def test_compute_code_identity_system_scope_uses_the_units_venv(tmp_path: Path) -> None:
    stub, venv, hexes = _stub(tmp_path)
    soak.Harness.compute_code_identity(stub)  # type: ignore[arg-type]
    assert stub.code_error is None
    code = stub.code
    assert code["source"] == "units" and code["python"] is None
    assert Path(code["package_dir"]).is_relative_to(venv)
    assert code["units"] == hexes
    assert code["files"] == 2


def test_compute_code_identity_refuses_two_venvs(tmp_path: Path) -> None:
    other = tmp_path / "other"
    stub, venv, _ = _stub(tmp_path, ingest_venv=other)
    soak.Harness.compute_code_identity(stub)  # type: ignore[arg-type]
    assert stub.code is None
    assert str(venv) in stub.code_error and str(other) in stub.code_error


def test_compute_code_identity_never_raises_on_unit_errors(tmp_path: Path) -> None:
    stub, _, _ = _stub(tmp_path, unit_err=True)
    soak.Harness.compute_code_identity(stub)  # type: ignore[arg-type]
    assert stub.code is None
    assert "FragmentPath" in stub.code_error


def test_compute_code_identity_children_scope(tmp_path: Path) -> None:
    stub = SimpleNamespace(scope=None, py=sys.executable, code=None, code_error=None)
    soak.Harness.compute_code_identity(stub)  # type: ignore[arg-type]
    assert stub.code_error is None
    assert stub.code["source"] == "children" and stub.code["python"] == sys.executable
    assert stub.code["units"] is None
    assert stub.code["sha256"] == _shell_fingerprint(REPO / "src" / "jabuka")


# -- run-start identity gate (plan 04-04 Task 2, 04-VERIFICATION gap 1 "missing" item 2) ----------
CODE = {"sha256": "c" * 64, "files": 146, "package_dir": "/x/jabuka", "source": "children"}


def test_identity_messages_refuse_system_scope_without_a_fingerprint() -> None:
    with pytest.raises(soak.sd.SetupError, match="fingerprint") as exc:
        soak.identity_messages("system", None, "no lib/python3*/site-packages/jabuka", {})
    assert "no lib/python3*/site-packages/jabuka" in str(exc.value)


def test_identity_messages_warn_loudly_without_any_identity() -> None:
    for scope in (None, "user"):
        lines = soak.identity_messages(scope, None, "cannot locate jabuka", {"head": None})
        assert len(lines) >= 3
        assert all(ln.startswith("jabuka-soak: WARNING") for ln in lines), lines
        assert any("F3/F4" in ln for ln in lines) and any("cannot locate" in ln for ln in lines)


def test_identity_messages_with_a_fingerprint() -> None:
    lines = soak.identity_messages("system", CODE, None, {"head": None, "dirty": None})
    assert len(lines) == 2
    assert lines[0].startswith("jabuka-soak: code cccccccccccc")
    assert lines[1].startswith("jabuka-soak: note:")
    assert not any("WARNING" in ln for ln in lines)
    lines = soak.identity_messages(None, CODE, None, {"head": "d" * 40, "dirty": False})
    assert len(lines) == 1 and lines[0].startswith("jabuka-soak: code cccccccccccc")
    assert "dddddddddddd" in lines[0]


def test_identity_messages_warn_when_a_pi_run_is_not_system_scope() -> None:
    """Plan 04-06: freeze-check F4 counts only the `--systemd system` Pi soak; a shim or
    `--systemd user` run on the Pi says so at start."""
    git = {"head": None, "dirty": None}
    for scope in (None, "user"):
        lines = soak.identity_messages(scope, CODE, None, git, machine="aarch64")
        warn = [ln for ln in lines if ln.startswith("jabuka-soak: WARNING")]
        assert warn and all("--systemd system" in ln for ln in warn), lines
    for scope, machine in (("system", "aarch64"), (None, "x86_64")):
        lines = soak.identity_messages(scope, CODE, None, git, machine=machine)
        assert not [ln for ln in lines if "WARNING" in ln], (scope, machine, lines)
    today = soak.identity_messages(None, CODE, None, git)
    assert today == soak.identity_messages(None, CODE, None, git, machine="x86_64")
    assert len(today) == 2 and not any("WARNING" in ln for ln in today), today


def _fake_systemctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The fake systemctl of tests/soak/test_soak_systemd.py (cat/show answered, calls logged)."""
    spec = importlib.util.spec_from_file_location(
        "_soak_systemd_fake", Path(__file__).with_name("test_soak_systemd.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    b = tmp_path / "bin"
    b.mkdir()
    for name in ("systemctl", "systemd-run", "journalctl"):
        p = b / name
        p.write_text(mod.FAKE.format(py=sys.executable))
        p.chmod(0o755)
    units = tmp_path / "units"
    units.mkdir()
    for u in ("jabuka-core.service", "jabuka-ingest-fastnet.service"):
        shutil.copy(REPO / "deploy" / "systemd" / u, units / u)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SYSTEMD_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_UNITS", str(units))
    return tmp_path / "calls.jsonl"


def test_run_soak_refuses_system_scope_without_a_code_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    log = _fake_systemctl(tmp_path, monkeypatch)

    def no_identity(self: soak.Harness) -> None:
        self.code, self.code_error = None, "no lib/python3*/site-packages/jabuka in /opt/x"

    def never(self: soak.Harness) -> dict:
        raise AssertionError("Harness.run must not be called")

    monkeypatch.setattr(soak.Harness, "compute_code_identity", no_identity)
    monkeypatch.setattr(soak.Harness, "run", never)
    out = tmp_path / "out"
    args = soak.build_arg_parser().parse_args(
        ["--systemd", "system", "--scenario", "tracer", "--out", str(out)]
    )
    assert soak.run_soak(args, load_scenario("tracer")) == 2
    err = capsys.readouterr().err
    assert "fingerprint" in err and "/opt/x" in err, err
    assert not list(out.iterdir())  # the run dir it created is gone
    verbs = {json.loads(ln)[1] for ln in log.read_text().splitlines()}
    assert verbs <= {"cat", "show"}, verbs


# -- the report records what ran, for freeze-check F3/F4 (plan 04-07, review CR-01) --------------
def test_report_records_the_run_length_and_the_scenario(tmp_path: Path) -> None:
    raw = (REPO / "src" / "jabuka" / "soak" / "scenarios" / "race-36h.json").read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    sc = load_scenario("race-36h")
    assert sc.sha256 == sha and sc.source == "scenarios/race-36h.json"
    doc = json.loads(raw)
    doc["duration_s"] = 600
    custom = tmp_path / "race-36h.json"
    custom.write_text(json.dumps(doc), encoding="utf-8")
    other = load_scenario(str(custom))
    assert other.sha256 != sha and other.source == str(custom)
    for i, (extra, want) in enumerate(((["--duration", "900"], 900.0), ([], 129600.0))):
        out = tmp_path / f"out{i}"
        args = soak.build_arg_parser().parse_args(
            ["--scenario", "race-36h", *extra, "--out", str(out)]
        )
        args.fixtures = tmp_path
        h = soak.Harness(soak.make_run_dir(out, "race-36h"), sc, args)
        try:
            r = h.build_report()
        finally:
            h._tl.close()
        assert r["duration_s"] == want, r["duration_s"]
        assert r["scenario_duration_s"] == 129600.0
        assert r["scenario_source"] == "scenarios/race-36h.json"
        assert r["scenario_sha256"] == sha
        assert r["seed"] == 2026


def test_freeze_check_matches_the_harness_skip_reason() -> None:
    assert soak.SKIP_AFTER_END == "after the end of the run"
    assert soak.SKIP_AFTER_END in (REPO / "scripts" / "freeze-check.sh").read_text(encoding="utf-8")
    src = inspect.getsource(soak.Harness.run_faults)
    assert "SKIP_AFTER_END" in src and "after the end of the run" not in src, src


def test_shortened_run_is_announced_at_start() -> None:
    sc = load_scenario("race-36h")
    lines = soak.run_length_messages(sc, 900.0)
    assert len(lines) == 1, lines
    assert lines[0].startswith("jabuka-soak: WARNING: shortened run"), lines
    assert "F3/F4" in lines[0] and "--out var/soak-essais" in lines[0], lines
    assert soak.run_length_messages(sc, 129600.0) == []
    assert soak.run_length_messages(sc, 200000.0) == []


def test_report_md_marks_a_shortened_run() -> None:
    md = rep.render_md({"git": {}, "duration_s": 900.0, "scenario_duration_s": 129600.0})
    assert "Essai raccourci" in md, md
    md = rep.render_md({"git": {}, "duration_s": 129600.0, "scenario_duration_s": 129600.0})
    assert "Essai raccourci" not in md, md
    assert "Essai raccourci" not in rep.render_md({"git": {}})


# -- the docs quote the one fingerprint definition (plan 04-04 Task 3) ----------------------------
DOCS = REPO / "docs"


def _doc(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_docs_quote_the_fingerprint_command() -> None:
    for name in ("SPARE-SD.md", "FREEZE.md", "SOAK.md"):
        assert rep.FINGERPRINT_SH in _doc(name), name
    pi_dir = "/opt/jabuka/venv/lib/python3.13/site-packages/jabuka"
    assert f"cd {pi_dir} && {rep.FINGERPRINT_SH}" in _doc("SPARE-SD.md")
    assert f"cd {pi_dir} && {rep.FINGERPRINT_SH}" in _doc("SOAK.md")


def test_pi_soak_procedure_describes_the_code_identity() -> None:
    text = _doc("SOAK.md")
    pi = text[text.index("## Soak sur le Pi 3B") : text.index("## Budgets Pi à confirmer")]
    for word in ("code.sha256", "sans .git", "jabuka-soak: code", "tmpfs", "--logs-fs none"):
        assert word in pi, word
    step2 = pi[pi.index("2. Lancer") : pi.index("3. ")]
    assert "--logs-fs loop:512M" in step2
    cleanup = text[text.index("- **Nettoyage, toujours**") : text.index("- **Chien de garde**")]
    assert cleanup.index("relancées") < cleanup.index("démontage")
    assert "--systemd-cleanup" in cleanup and "oom_score_adj" in cleanup
    freeze = _doc("FREEZE.md")
    for word in ("empreinte", "code.sha256", "## Empreinte du code", "différent de src/jabuka"):
        assert word in freeze, word
    pi_setup = (REPO / "deploy" / "PI-SETUP.md").read_text(encoding="utf-8")
    sec3 = pi_setup[pi_setup.index("## 3. Install") : pi_setup.index("## 4.")]
    assert "code.sha256" in sec3 and "--exclude '.git'" in sec3


def test_docs_describe_the_f4_system_scope_rule_and_tmux() -> None:
    """Plan 04-06: the Pi soak runs inside tmux, F4 counts only the `--systemd system` report
    (code.source units), and the cleanup outcome (restart verified, report before 128+signal)."""
    text = _doc("SOAK.md")
    pi = text[text.index("## Soak sur le Pi 3B") : text.index("## Budgets Pi à confirmer")]
    step2 = pi[pi.index("2. Lancer") : pi.index("3. ")]
    assert "tmux new -s soak" in step2 and "tmux attach -t soak" in step2, step2
    for word in ("code.source", "--systemd user", "WARNING"):
        assert word in pi, word
    step8 = pi[pi.index("8. ") : pi.index("9. ")]
    assert "code 1" in step8, step8
    cleanup = text[text.index("- **Nettoyage, toujours**") : text.index("- **Chien de garde**")]
    for word in ("restarted", "report.json", "128"):
        assert word in cleanup, word
    freeze = _doc("FREEZE.md")
    for word in ("code.source", "--systemd system", "--systemd user"):
        assert word in freeze, word


def test_docs_describe_the_full_length_rule_and_the_f3_git_rule() -> None:
    """Plan 04-07: only a full-length race-36h soak counts for F3/F4, quick runs go to
    var/soak-essais, F3 needs git.head, and the end of the soak holds Ctrl-C (kill -9 escape)."""
    text = _doc("SOAK.md")
    for word in ("essai raccourci", "var/soak-essais", "scenario_sha256", "WARNING: shortened run"):
        assert word in text, word
    pi = text[text.index("## Soak sur le Pi 3B") : text.index("## Budgets Pi à confirmer")]
    assert "sans `--duration`" in pi, pi
    step8 = pi[pi.index("8. ") : pi.index("9. ")]
    assert "kill -9" in step8, step8
    cleanup = text[text.index("- **Nettoyage, toujours**") : text.index("- **Chien de garde**")]
    assert "fin du soak" in cleanup, cleanup
    freeze = _doc("FREEZE.md")
    for word in ("essai raccourci", "scenario_sha256", "var/soak-essais", "git.head inconnu"):
        assert word in freeze, word
    steps = freeze[
        freeze.index("1. **Endurance sur le portable**") : freeze.index("3. **Porte verte**")
    ]
    assert steps.count("sans `--duration`") == 2, steps
