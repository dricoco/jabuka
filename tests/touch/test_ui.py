"""Screen state machine: navigation, confirmations, tap guard, busy state, layout rules."""

from __future__ import annotations

import pytest
from jabuka_touch import config
from jabuka_touch.selftest import ManualClock, sample_snapshot
from jabuka_touch.ui import RISKY, SCREENS, UI


class Harness:
    def __init__(self, clock: ManualClock, busy: bool = False, state=None):
        self.clock = clock
        self.submitted: list[str] = []
        self.busy = busy
        self.state = state
        self.extra: list[set[str]] = []
        self.cfg = config.Config()
        self.ui = UI(
            clock,
            self.cfg,
            self.submit,
            lambda: self.busy,
            state=lambda: self.state,
            set_extra=lambda names: self.extra.append(set(names)),
            wall=lambda: 0.0,
        )

    def submit(self, action: str) -> bool:
        self.submitted.append(action)
        return True

    def tap(self, bid: str, wait: float = 1.0) -> bool:
        self.clock.advance(wait)
        b = next(b for b in self.ui.buttons() if b.id == bid)
        return self.ui.on_tap(*b.centre)


@pytest.fixture
def h(clock: ManualClock) -> Harness:
    return Harness(clock)


def test_restart_flow_yes(h: Harness) -> None:
    assert h.ui.screen == "home"
    h.tap("system")
    assert h.ui.screen == "system"
    h.tap("restart_services")
    assert h.ui.screen == "confirm" and h.ui.confirm_action == "restart_services"
    assert h.submitted == []
    h.tap("yes")
    assert h.submitted == ["restart_services"] and h.ui.screen == "system"


def test_restart_flow_no(h: Harness) -> None:
    h.tap("system")
    h.tap("restart_services")
    h.tap("no")
    assert h.ui.screen == "system" and h.submitted == []


def test_confirmation_times_out(h: Harness) -> None:
    h.tap("system")
    h.tap("reboot")
    h.clock.advance(7.9)
    h.ui.tick()
    assert h.ui.screen == "confirm"
    assert h.ui.view().countdown == 1
    h.clock.advance(0.2)
    h.ui.tick()
    assert h.ui.screen == "system" and h.submitted == []


def test_tap_guard_after_screen_change(h: Harness) -> None:
    h.tap("system")
    assert not h.tap("restart_services", wait=0.3)
    assert h.ui.screen == "system"
    assert h.tap("restart_services", wait=0.4)  # 0.7 s after the change
    assert h.ui.screen == "confirm"
    assert not h.tap("yes", wait=0.5)
    assert h.submitted == []


def test_busy_disables_actions_but_not_navigation(h: Harness) -> None:
    h.tap("system")
    h.busy = True
    assert all(not b.enabled for b in h.ui.buttons() if b.kind == "action")
    assert not h.tap("restart_services") and h.ui.screen == "system"
    assert h.tap("back") and h.ui.screen == "home"


def test_non_risky_action_submits_directly(h: Harness) -> None:
    h.tap("system")
    h.tap("night_toggle")
    assert h.submitted == ["night_toggle"] and h.ui.screen == "system"


def _all_screens(clock: ManualClock) -> list[tuple[str, Harness]]:
    out = []
    for screen in SCREENS:
        for demo in (False, True):
            hh = Harness(clock)
            hh.ui.snapshot = sample_snapshot(demo=demo)
            if screen == "confirm":
                hh.ui.go("system")
                hh.ui.open_confirm("reboot")
            else:
                hh.ui.go(screen)
            out.append((screen, hh))
    return out


def test_buttons_big_and_inside(clock: ManualClock) -> None:
    for screen, hh in _all_screens(clock):
        for b in hh.ui.buttons():
            x0, y0, x1, y1 = b.rect
            assert y1 - y0 >= 80, (screen, b.id, b.rect)
            assert 0 <= x0 < x1 <= 480 and 0 <= y0 < y1 <= 320, (screen, b.id)


def test_oui_never_under_a_confirmation_opening_button(clock: ManualClock) -> None:
    hh = Harness(clock)
    hh.ui.open_confirm("reboot")
    yes = next(b for b in hh.ui.buttons() if b.id == "yes")
    openers = [
        (screen, b)
        for screen, h2 in _all_screens(clock)
        for b in h2.ui.buttons()
        if b.opens_confirm
    ]
    assert {b.target for _, b in openers} >= {"restart_services", "terminal", "reboot", "poweroff"}
    for screen, b in openers:
        assert not yes.contains(*b.centre), (screen, b.id)
    assert all(b.target in RISKY for _, b in openers)


def test_view_key_changes(clock: ManualClock) -> None:
    wall = [0.0]
    hh = Harness(clock)
    hh.ui.wall = lambda: wall[0]
    s1 = sample_snapshot(version=1)
    k1 = hh.ui.view_key(s1)
    assert hh.ui.view_key(s1) == k1 and hash(k1) == hash(hh.ui.view_key(s1))
    assert hh.ui.view_key(sample_snapshot(version=2)) != k1
    hh.ui.view_key(s1)
    wall[0] = 61.0
    assert hh.ui.view_key(s1) != k1
    wall[0] = 0.0
    hh.busy = True
    assert hh.ui.view_key(s1) != k1
    hh.busy = False
    hh.ui.go("system")
    assert hh.ui.view_key(s1) != k1


def test_prep_journal_details_navigation_and_extra(h: Harness) -> None:
    h.ui.snapshot = sample_snapshot()
    h.tap("prep")
    assert h.ui.screen == "prep" and h.extra[-1] == {"wifi_status"}
    lines = h.ui.view().lines
    assert lines[0].startswith("Prerace : OK") and "code 0" in lines[0]
    assert lines[1].startswith("Wi-Fi : point d'accès") and "2 clients" in lines[1]
    h.tap("journal")
    assert h.ui.screen == "journal" and h.extra[-1] == {"journal_prerace"}
    assert "jabuka-prep wind" in " ".join(h.ui.view().lines)
    h.tap("toggle")
    assert h.extra[-1] == {"prerace_status"}
    assert "résultat : OK" in h.ui.view().lines
    h.tap("back")
    assert h.ui.screen == "prep" and h.extra[-1] == {"wifi_status"}
    h.tap("back")
    assert h.ui.screen == "home" and h.extra[-1] == set()
    h.tap("details")
    assert h.ui.screen == "details" and len(h.ui.view().lines) == 10
    h.tap("back")
    assert h.ui.screen == "home"


def test_prep_actions_are_confirmed(h: Harness) -> None:
    h.tap("prep")
    for aid in ("prerace", "wifi_ap", "wifi_phone"):
        h.tap(aid)
        assert h.ui.screen == "confirm" and h.ui.confirm_action == aid
        assert h.ui.view().title.endswith("?")
        h.tap("no")
        assert h.ui.screen == "prep"
    assert h.submitted == []
    h.tap("prerace")
    h.tap("yes")
    assert h.submitted == ["prerace"]


def test_successful_prerace_opens_the_journal(clock: ManualClock) -> None:
    from jabuka_touch.actions import ActionResult

    hh = Harness(clock)
    hh.tap("prep")
    hh.state = ActionResult("prerace", "Prerace", "ok", ("Prerace lancé",), 1)
    hh.ui.tick()
    assert hh.ui.screen == "journal" and hh.extra[-1] == {"journal_prerace"}
    hh.tap("back")
    hh.ui.tick()
    assert hh.ui.screen == "prep"  # the same result does not switch again


def test_prep_shows_failure_lines(clock: ManualClock) -> None:
    from jabuka_touch.actions import PHONE_HINT, ActionResult

    hh = Harness(clock)
    hh.ui.snapshot = sample_snapshot()
    hh.ui.go("prep")
    hh.state = ActionResult(
        "wifi_phone", "Wi-Fi téléphone", "fail", ("ÉCHEC (code 1)", "pas de terminal", PHONE_HINT)
    )
    lines = hh.ui.view().lines
    assert lines[2] == "Wi-Fi téléphone : ÉCHEC (code 1)"
    assert lines[3:] == ("pas de terminal", PHONE_HINT)
