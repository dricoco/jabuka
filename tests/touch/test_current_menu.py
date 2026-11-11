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


# -- LANCER PRERACE chains the current step --------------------------------------------------

WALL = 1794560000


def _prerace(runner, demo: bool = False):
    return actions.prerace(runner, lambda: demo, wall=lambda: WALL + 0.7)


def test_prerace_chains_the_current_step(runner: FakeRunner) -> None:
    out = _prerace(runner).fn(lambda line: None)
    assert out.ok
    assert runner.calls == [
        ["systemctl", "is-active", "jabuka-current.service"],
        ["/usr/local/sbin/prerace"],
        [CURRENT, "--after-prerace", str(WALL)],
    ]
    assert "Prerace lancé : suivre le journal" in out.lines
    assert "Courant : suivra prerace (si code 0 ou 3)" in out.lines


def test_prerace_failure_never_schedules_the_current(runner: FakeRunner) -> None:
    runner.set(("/usr/local/sbin/prerace",), CmdResult(1, "", "prerace: déjà en cours\n"))
    out = _prerace(runner).fn(lambda line: None)
    assert not out.ok
    assert out.lines == ("ÉCHEC (code 1)", "prerace: déjà en cours")
    assert not [c for c in runner.calls if c[0] == CURRENT]


@pytest.mark.parametrize(
    "res",
    [
        CmdResult(1, "", "jabuka-current: identifiants Copernicus absents : sudo ... login\n"),
        CmdResult(None, error=f"{CURRENT} introuvable"),
    ],
)
def test_prerace_ok_but_current_not_scheduled(runner: FakeRunner, res: CmdResult) -> None:
    runner.set((CURRENT,), res)
    out = _prerace(runner).fn(lambda line: None)
    assert out.ok
    assert out.lines[0] == "Prerace lancé : suivre le journal"
    line = next(ln for ln in out.lines if ln.startswith("Courant non programmé ("))
    assert line.endswith(": bouton COURANT après prerace")


@pytest.mark.parametrize("state", ["active", "activating"])
def test_prerace_refused_while_the_current_runs(runner: FakeRunner, state: str) -> None:
    runner.set(("systemctl", "is-active", "jabuka-current.service"), CmdResult(0, state + "\n"))
    out = _prerace(runner).fn(lambda line: None)
    assert not out.ok and out.lines == ("Courant en cours : attendre la fin (JOURNAL)",)
    assert runner.calls == [["systemctl", "is-active", "jabuka-current.service"]]


def test_prerace_refused_during_demo_runs_nothing(runner: FakeRunner) -> None:
    out = _prerace(runner, demo=True).fn(lambda line: None)
    assert not out.ok and runner.calls == []


def test_prerace_confirmation_mentions_the_current() -> None:
    assert "courant Copernicus" in CONFIRM_TEXTS["prerace"][1]


# -- collector: current state and MÉTÉO details ----------------------------------------------

CURRENT_LAST = (
    "courant : 2026-11-11T18:02:33Z\n"
    "résultat : OK : courant installé, jabuka-core redémarré\n"
    "code : 0\n"
    "fenêtre : 2026-11-13T11:00:00 -> 2026-11-15T11:00:00 UTC\n"
    "fichier : Courant : 49 échéances 2026-11-13T11:00Z -> 2026-11-15T11:00Z\n"
    "Wi-Fi : non utilisé\n"
    "--- coverage.txt (courant) ---\n"
    "(aucune ligne courant)\n"
)

NAV = {"route": {"pack": {"ok": True, "model": "ICON-EU", "run": "2026-11-12T06:00:00Z"}}}


def _paths(tmp_path: Path, last: str | None = CURRENT_LAST, npz: bool = True) -> config.Paths:
    (tmp_path / "temp").write_text("52000\n")
    pack = tmp_path / "racepack"
    pack.mkdir(exist_ok=True)
    if npz:
        (pack / "current.npz").write_bytes(b"npz")
    if last is not None:
        (tmp_path / "current-last.txt").write_text(last)
    return config.Paths(
        thermal=tmp_path / "temp",
        data_dir=tmp_path,
        prerace_last=tmp_path / "prerace-last.txt",
        current_last=tmp_path / "current-last.txt",
        current_npz=pack / "current.npz",
        demo_flag=tmp_path / "zz-jabuka-touch-demo.conf",
    )


def _collector(tmp_path: Path, runner: FakeRunner, **kw):
    from jabuka_touch import status

    def fetch(path: str):
        return {"/api/state": {}, "/api/nav": NAV}.get(path)

    return status.Collector(runner, fetch=fetch, paths=_paths(tmp_path, **kw))


def test_collector_reads_the_current_result(tmp_path: Path, runner: FakeRunner) -> None:
    snap = _collector(tmp_path, runner).collect_once()
    cur = snap.extra["current"]
    assert cur["running"] is False and cur["present"] is True
    assert cur["last"]["date"] == "2026-11-11T18:02:33Z" and cur["last"]["code"] == 0
    assert cur["last"]["result"].startswith("OK : courant installé")
    assert ["systemctl", "is-active", "jabuka-current.service"] in runner.calls
    detail = snap.item("pack").detail
    assert detail.endswith("courant : présent (téléchargé 2026-11-11T18:02:33Z)")
    assert snap.item("pack").level == "ok"
    # no accumulating suffix over collections
    assert _collector(tmp_path, runner).collect_once().item("pack").detail == detail


def test_collector_current_absent(tmp_path: Path, runner: FakeRunner) -> None:
    snap = _collector(tmp_path, runner, last=None, npz=False).collect_once()
    assert snap.item("pack").detail.endswith("courant : absent")
    assert snap.extra["current"]["last"] == {}


def test_collector_current_present_without_local_download(
    tmp_path: Path, runner: FakeRunner
) -> None:
    snap = _collector(tmp_path, runner, last=None).collect_once()
    assert snap.item("pack").detail.endswith("courant : présent")


def test_collector_current_running(tmp_path: Path, runner: FakeRunner) -> None:
    runner.set(("systemctl", "is-active", "jabuka-current.service"), CmdResult(0, "active\n"))
    snap = _collector(tmp_path, runner).collect_once()
    assert snap.extra["current"]["running"] is True
    assert snap.item("pack").detail.endswith("courant : téléchargement en cours")


def test_collector_current_never_raises(tmp_path: Path) -> None:
    from jabuka_touch import status

    r = FakeRunner(default=CmdResult(None, timed_out=True))
    r.set(("systemctl", "is-active", "jabuka-current.service"), RuntimeError("boom"))
    paths = config.Paths(
        thermal=tmp_path / "absent",
        data_dir=tmp_path / "absent",
        prerace_last=tmp_path / "absent",
        current_last=tmp_path / "absent-dir",
        current_npz=tmp_path / "absent",
        demo_flag=tmp_path / "absent",
    )
    (tmp_path / "absent-dir").mkdir()  # reading a directory raises IsADirectoryError
    snap = status.Collector(r, fetch=lambda p: None, paths=paths).collect_once()
    assert snap.extra["current"] == {"running": False, "present": False, "last": {}}


def test_parse_current_last() -> None:
    from jabuka_touch import status

    got = status.parse_current_last(CURRENT_LAST)
    assert got == {
        "running": False,
        "date": "2026-11-11T18:02:33Z",
        "result": "OK : courant installé, jabuka-core redémarré",
        "code": 0,
    }
    assert status.parse_current_last("en attente de la fin de prerace : x\n")["running"]
    assert status.parse_current_last("en cours : journalctl -fu jabuka-current\n")["running"]
    assert status.parse_prerace_last("prerace : D\nrésultat : R\ncode : 3\n")["code"] == 3


def test_journal_follows_both_units() -> None:
    from jabuka_touch import status

    argv = status.EXTRA_QUERIES["journal_prerace"]
    assert argv[0] == "journalctl"
    pairs = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-u"]
    assert pairs == ["jabuka-prerace.service", "jabuka-current.service"]


# -- prep info lines -------------------------------------------------------------------------


class Snap:
    def __init__(self, current: dict | None, prerace_running: bool = False):
        self.extra = {"prerace_last": {}, "wifi": {"mode": "ap", "ssid": "jabuka", "clients": 1}}
        if current is not None:
            self.extra["current"] = current
        self.prerace_running = prerace_running
        self.demo = False


@pytest.mark.parametrize(
    ("current", "prerace_running", "want"),
    [
        (
            {
                "running": False,
                "present": True,
                "last": {"result": "OK : courant installé", "date": "D", "code": 0},
            },
            False,
            "Courant : OK : courant installé · D · code 0",
        ),
        (
            {"running": True, "present": False, "last": {}},
            False,
            "Courant : en cours (JOURNAL pour suivre)",
        ),
        (
            {"running": True, "present": False, "last": {}},
            True,
            "Courant : en attente de la fin de prerace",
        ),
        (
            {"running": False, "present": False, "last": {}},
            False,
            "Courant : aucun téléchargement (bouton COURANT)",
        ),
        (None, False, "Courant : aucun téléchargement (bouton COURANT)"),
    ],
)
def test_prep_current_line(h: Harness, current, prerace_running: bool, want: str) -> None:
    h.ui.go("prep")
    lines = h.ui.prep_lines(Snap(current, prerace_running))
    assert lines[1] == want
    assert lines[0].startswith("Prerace : ")


def test_prep_lines_keep_two_action_lines(h: Harness) -> None:
    h.state = actions.ActionResult(
        "prerace", "Prerace", "ok", ("Prerace lancé", "a", "b", "Courant : suivra prerace"), 1
    )
    h.ui.go("prep")
    lines = h.ui.prep_lines(Snap(None))
    assert lines[-3:] == ("Prerace : OK", "b", "Courant : suivra prerace")


def test_journal_header(h: Harness) -> None:
    h.ui.go("journal")
    snap = Snap(None)
    snap.extra["journal_prerace"] = ("x",)
    h.ui.snapshot = snap
    assert h.ui.lines(snap)[0] == "Journal prerace + courant :"
