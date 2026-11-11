"""Touch menu side of the Copernicus current step: COURANT button, `current` action, chaining
after LANCER PRERACE, the current info line and the MÉTÉO details."""

from __future__ import annotations

from pathlib import Path

import pytest
from jabuka_touch import actions, config
from jabuka_touch.actions import CmdResult, FakeRunner
from jabuka_touch.selftest import FakeConsole, ManualClock
from jabuka_touch.ui import CONFIRM_TEXTS, RISKY, UI

CURRENT = "/usr/local/sbin/jabuka-current"


class Harness:
    def __init__(self, clock: ManualClock, state=None):
        self.clock = clock
        self.submitted: list[str] = []
        self.state = state
        self.cfg = config.Config()
        self.ui = UI(
            clock,
            self.cfg,
            self.submit,
            lambda: False,
            state=lambda: self.state,
            set_extra=lambda names: None,
            wall=lambda: 0.0,
        )

    def submit(self, action: str) -> bool:
        self.submitted.append(action)
        return True

    def button(self, bid: str):
        return next(b for b in self.ui.buttons() if b.id == bid)

    def tap(self, bid: str, wait: float = 1.0) -> bool:
        self.clock.advance(wait)
        return self.ui.on_tap(*self.button(bid).centre)


@pytest.fixture
def h(clock: ManualClock) -> Harness:
    return Harness(clock)


def _registry(runner, tmp_path: Path, demo: bool = False):
    return actions.build_registry(
        runner, FakeConsole(), config.Config(), tmp_path / "t.json", demo_active=lambda: demo
    )


def _run(reg: dict, action_id: str):
    return reg[action_id].fn(lambda line: None)


# -- COURANT button ------------------------------------------------------------------------------


def test_courant_button_geometry(h: Harness) -> None:
    h.ui.go("prep")
    b = h.button("current")
    assert b.kind == "action" and b.target == "current" and b.label == "COURANT"
    assert b.risky and b.opens_confirm and "current" in RISKY
    x0, y0, x1, y1 = b.rect
    assert y1 - y0 >= 80 and x1 - x0 >= 100
    h.ui.open_confirm("current")
    yes = h.button("yes")
    h.ui.close_confirm()
    h.ui.go("prep")
    for bid in ("current", "prerace"):
        assert not yes.contains(*h.button(bid).centre), bid
    assert "current" in CONFIRM_TEXTS


def test_courant_then_oui_submits_current(h: Harness) -> None:
    h.ui.go("prep")
    h.tap("current")
    assert h.ui.screen == "confirm" and h.ui.confirm_action == "current"
    assert h.submitted == []
    h.tap("yes")
    assert h.submitted == ["current"] and h.ui.screen == "prep"


def test_courant_then_non_runs_nothing(h: Harness) -> None:
    h.ui.go("prep")
    h.tap("current")
    h.tap("no")
    assert h.submitted == [] and h.ui.screen == "prep"


def test_successful_current_opens_the_journal(clock: ManualClock) -> None:
    hh = Harness(clock)
    hh.ui.go("prep")
    hh.state = actions.ActionResult("current", "Courant", "ok", ("Courant lancé",), 1)
    hh.ui.tick()
    assert hh.ui.screen == "journal"


# -- current action ------------------------------------------------------------------------------


def test_current_action_argv(runner: FakeRunner, tmp_path: Path) -> None:
    out = _run(_registry(runner, tmp_path), "current")
    assert out.ok and out.lines[0] == "Courant lancé : suivre le journal"
    assert runner.calls == [[CURRENT]]
    assert runner.timeouts == [30.0]


def test_current_refused_during_demo(runner: FakeRunner, tmp_path: Path) -> None:
    out = _run(_registry(runner, tmp_path, demo=True), "current")
    assert not out.ok and out.lines == (actions.CURRENT_DEMO_REFUSAL,)
    assert runner.calls == []


def test_current_failure_shows_the_script_output(runner: FakeRunner, tmp_path: Path) -> None:
    runner.set(
        (CURRENT,),
        CmdResult(1, "", "jabuka-current: identifiants Copernicus absents : sudo ... login\n"),
    )
    out = _run(_registry(runner, tmp_path), "current")
    assert not out.ok and out.lines[0] == "ÉCHEC (code 1)"
    assert "identifiants Copernicus absents" in out.lines[1]
