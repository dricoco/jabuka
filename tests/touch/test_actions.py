"""Whitelisted runner, action builders and the single-flight worker."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest
from jabuka_touch import actions, config
from jabuka_touch.actions import CmdResult, FakeRunner, Runner, Worker
from jabuka_touch.selftest import FakeConsole


def _registry(runner, tmp_path: Path, cfg=None):
    cfg = cfg or config.Config()
    return actions.build_registry(runner, FakeConsole(), cfg, tmp_path / "t.json", save=config.save)


def _run(reg: dict, action_id: str):
    return reg[action_id].fn(lambda line: None)


def test_system_action_argv(runner: FakeRunner, tmp_path: Path) -> None:
    reg = _registry(runner, tmp_path)
    for aid in ("restart_services", "reboot", "poweroff", "terminal"):
        assert _run(reg, aid).ok
    assert runner.calls == [
        ["systemctl", "restart", "jabuka-ingest-fastnet.service", "jabuka-core.service"],
        ["systemctl", "reboot"],
        ["systemctl", "poweroff"],
        ["systemctl", "--no-block", "start", "getty@tty1.service"],
    ]
    assert runner.timeouts[0] == 90.0 and runner.timeouts[2] == 30.0


def test_terminal_restores_text_console_first(runner: FakeRunner, tmp_path: Path) -> None:
    order = []
    console = FakeConsole()
    console.text = lambda: order.append("text") or True  # type: ignore[method-assign]
    runner.set(("systemctl", "--no-block"), lambda argv: order.append("getty") or CmdResult(0))
    reg = actions.build_registry(runner, console, config.Config(), tmp_path / "t.json")
    assert _run(reg, "terminal").ok
    assert order == ["text", "getty"]


def test_night_toggle_saves(tmp_path: Path, runner: FakeRunner) -> None:
    cfg = config.Config()
    reg = _registry(runner, tmp_path, cfg)
    assert _run(reg, "night_toggle").ok
    assert cfg.night is True
    assert config.load(tmp_path / "t.json").night is True
    assert runner.calls == []


def test_runner_refuses_non_whitelisted() -> None:
    r = Runner()
    for argv in (["bash", "-c", "true"], ["/tmp/systemctl", "status"], ["systemctl", 3], []):
        with pytest.raises(ValueError):
            r.run(argv, 1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        FakeRunner().run(["rm", "-rf", "/"], 1.0)


def test_runner_never_raises(monkeypatch) -> None:
    r = Runner()

    def missing(*a, **k):
        raise FileNotFoundError("x")

    monkeypatch.setattr(subprocess, "run", missing)
    res = r.run(["systemctl", "status"], 1.0)
    assert res.rc is None and "introuvable" in (res.error or "") and not res.ok

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1.0, output=b"partiel\n")

    monkeypatch.setattr(subprocess, "run", slow)
    res = r.run(["systemctl", "status"], 1.0)
    assert res.timed_out and res.out == "partiel\n" and not res.ok

    seen = {}

    def ok(argv, **k):
        seen.update(k)
        return subprocess.CompletedProcess(argv, 0, "a\nb\n", "")

    monkeypatch.setattr(subprocess, "run", ok)
    res = r.run(["systemctl", "status"], 2.0)
    assert res.ok and res.tail(1) == ["b"]
    assert "shell" not in seen and seen["stdin"] is subprocess.DEVNULL
    assert seen["env"]["PATH"].startswith("/usr/local/sbin") and seen["timeout"] == 2.0


def test_worker_single_flight() -> None:
    gate = threading.Event()

    def slow(progress):
        progress("étape 1")
        gate.wait(5)
        return actions.Outcome(True, ("fini",))

    w = Worker({"slow": actions.Action("slow", "Lent", slow)})
    assert w.submit("slow") is True
    assert w.busy and w.submit("slow") is False
    st = w.state()
    assert st is not None and st.state == "running" and st.title == "Lent"
    gate.set()
    assert w.wait(5)
    st = w.state()
    assert st is not None and st.state == "ok" and st.lines == ("fini",) and not w.busy
    assert w.submit("unknown") is False


def test_worker_records_failure_and_crash() -> None:
    def boom(progress):
        raise RuntimeError("bug")

    w = Worker(
        {
            "boom": actions.Action("boom", "Boum", boom),
            "fail": actions.Action(
                "fail", "Rate", lambda p: actions.cmd_outcome(CmdResult(2, "", "non\n"), "ok")
            ),
        }
    )
    w.submit("boom")
    w.wait(5)
    st = w.state()
    assert st.state == "fail" and "erreur interne" in st.lines[0]
    w.submit("fail")
    w.wait(5)
    st = w.state()
    assert st.state == "fail" and st.lines == ("ÉCHEC (code 2)", "non")
