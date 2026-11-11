"""Whitelisted commands and the single-flight action worker.

Every command is an argv list (never a shell) whose executable is in ALLOWED; only constants and
validated numbers are formatted into argv. Runner.run never raises for a runtime failure (missing
binary, timeout, OS error): it returns a CmdResult. A ValueError (non-whitelisted executable,
non-str argument) is a programming error and is raised.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("jabuka_touch.actions")

ALLOWED = frozenset(
    {
        "systemctl",
        "systemd-run",
        "journalctl",
        "prerace",
        "jabuka-current",
        "jabuka-wifi",
        "runuser",
        "nmcli",
        "iw",
        "vcgencmd",
        "chronyc",
    }
)
ALLOWED_DIRS = ("/usr/bin", "/usr/sbin", "/bin", "/sbin", "/usr/local/sbin", "/usr/local/bin")
SBIN = "/usr/local/sbin"
PRERACE = f"{SBIN}/prerace"
CURRENT = f"{SBIN}/jabuka-current"
WIFI = f"{SBIN}/jabuka-wifi"
ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "SYSTEMD_PAGER": "",
    "SYSTEMD_COLORS": "0",
}
CORE_UNIT = "jabuka-core.service"
INGEST_UNIT = "jabuka-ingest-fastnet.service"
GETTY_UNIT = "getty@tty1.service"
CURRENT_UNIT = "jabuka-current.service"
ACTIVE_STATES = ("active", "activating", "reloading")


def check_argv(argv: list[str]) -> None:
    if not isinstance(argv, list) or not argv:
        raise ValueError("argv doit être une liste non vide")
    for a in argv:
        if not isinstance(a, str):
            raise ValueError(f"argument non texte : {a!r}")
    exe = argv[0]
    name = exe.rsplit("/", 1)[-1]
    if name not in ALLOWED:
        raise ValueError(f"exécutable hors liste blanche : {exe}")
    if "/" in exe and str(Path(exe).parent) not in ALLOWED_DIRS:
        raise ValueError(f"exécutable hors des répertoires système : {exe}")


@dataclass(frozen=True)
class CmdResult:
    rc: int | None
    out: str = ""
    err: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out and self.error is None

    def tail(self, n: int = 4) -> list[str]:
        """Last non-empty lines, stdout then stderr (what the script said)."""
        lines = [ln.rstrip() for ln in (self.out or "").splitlines() if ln.strip()]
        lines += [ln.rstrip() for ln in (self.err or "").splitlines() if ln.strip()]
        return lines[-n:] if n else lines

    def describe(self) -> str:
        if self.error:
            return self.error
        if self.timed_out:
            return "délai dépassé"
        return f"code {self.rc}"


class Runner:
    """subprocess.run with an argv list, no stdin, a fixed environment and a timeout."""

    def run(self, argv: list[str], timeout: float) -> CmdResult:
        check_argv(argv)
        try:
            p = subprocess.run(  # noqa: S603 - whitelisted argv list, no shell
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                errors="replace",
                env=dict(ENV),
                timeout=timeout,
                check=False,
            )
            return CmdResult(p.returncode, p.stdout or "", p.stderr or "")
        except FileNotFoundError:
            return CmdResult(None, error=f"{argv[0]} introuvable")
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else ""
            err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else ""
            return CmdResult(None, out, err, timed_out=True)
        except Exception as e:  # noqa: BLE001 - never raise into the worker or the collector
            return CmdResult(None, error=f"{argv[0]} : {e}")


class FakeRunner:
    """Test double: records calls; responses keyed by argv prefix (longest prefix wins). A value
    may be a CmdResult, a callable(argv) -> CmdResult, or an exception instance (raised)."""

    def __init__(self, responses: dict | None = None, default: CmdResult | None = None):
        self.responses: dict[tuple[str, ...], object] = {}
        for k, v in (responses or {}).items():
            self.set(k, v)
        self.default = default if default is not None else CmdResult(0, "", "")
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []
        self.lock = threading.Lock()

    def set(self, prefix: tuple[str, ...] | list[str] | str, value: object) -> None:
        key = (prefix,) if isinstance(prefix, str) else tuple(prefix)
        self.responses[key] = value

    def run(self, argv: list[str], timeout: float) -> CmdResult:
        check_argv(argv)
        with self.lock:
            self.calls.append(list(argv))
            self.timeouts.append(timeout)
        best: tuple[str, ...] | None = None
        for k in self.responses:
            if tuple(argv[: len(k)]) == k and (best is None or len(k) > len(best)):
                best = k
        value = self.responses[best] if best is not None else self.default
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            return value(list(argv))
        return value  # type: ignore[return-value]


# -- actions -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Outcome:
    ok: bool
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    id: str
    title: str
    state: str  # running | ok | fail
    lines: tuple[str, ...] = ()
    seq: int = 0


Progress = Callable[[str], None]


@dataclass(frozen=True)
class Action:
    id: str
    title: str
    fn: Callable[[Progress], Outcome] = field(compare=False)


class Worker:
    """Runs one action at a time on a thread; the display loop only reads state()."""

    MAX_LINES = 8

    def __init__(self, registry: dict[str, Action]):
        self.registry = dict(registry)
        self.lock = threading.Lock()
        self.current: ActionResult | None = None
        self.last: ActionResult | None = None
        self.thread: threading.Thread | None = None
        self.seq = 0

    @property
    def busy(self) -> bool:
        with self.lock:
            return self.current is not None

    def is_busy(self) -> bool:
        return self.busy

    def state(self) -> ActionResult | None:
        """The running action (with its progress lines), else the last result."""
        with self.lock:
            return self.current if self.current is not None else self.last

    def submit(self, action_id: str) -> bool:
        action = self.registry.get(action_id)
        if action is None:
            log.warning("action inconnue : %s", action_id)
            return False
        with self.lock:
            if self.current is not None:
                return False
            self.seq += 1
            self.current = ActionResult(action.id, action.title, "running", (), self.seq)
        self.thread = threading.Thread(target=self._run, args=(action,), daemon=True)
        self.thread.start()
        return True

    def _progress(self, line: str) -> None:
        with self.lock:
            cur = self.current
            if cur is not None:
                lines = (*cur.lines, str(line))[-self.MAX_LINES :]
                self.current = ActionResult(cur.id, cur.title, cur.state, lines, cur.seq)
        log.info("%s", line)

    def _run(self, action: Action) -> None:
        try:
            out = action.fn(self._progress)
        except Exception as e:  # noqa: BLE001 - an action bug must not kill the menu
            log.exception("action %s", action.id)
            out = Outcome(False, (f"erreur interne : {e}",))
        with self.lock:
            cur = self.current
            seq = cur.seq if cur is not None else self.seq
            self.last = ActionResult(
                action.id, action.title, "ok" if out.ok else "fail", tuple(out.lines), seq
            )
            self.current = None
        log.info("action %s : %s %s", action.id, "ok" if out.ok else "échec", list(out.lines))

    def wait(self, timeout: float = 10.0) -> bool:
        t = self.thread
        if t is not None:
            t.join(timeout)
            return not t.is_alive()
        return True


def cmd_outcome(res: CmdResult, ok_text: str, hint: str | None = None, n: int = 3) -> Outcome:
    """OK: the success text + the command's last lines. Failure: code/timeout, last lines, hint."""
    if res.ok:
        return Outcome(True, (ok_text, *res.tail(n)))
    lines = [f"ÉCHEC ({res.describe()})", *res.tail(n)]
    if hint:
        lines.append(hint)
    return Outcome(False, tuple(lines))


def _simple(runner, action_id: str, title: str, argv: list[str], timeout: float, ok: str):
    def fn(progress: Progress) -> Outcome:
        progress(f"{title}…")
        return cmd_outcome(runner.run(argv, timeout), ok)

    return Action(action_id, title, fn)


def restart_services(runner) -> Action:
    return _simple(
        runner,
        "restart_services",
        "Redémarrage des services",
        ["systemctl", "restart", INGEST_UNIT, CORE_UNIT],
        90.0,
        "Services redémarrés",
    )


def reboot(runner) -> Action:
    return _simple(
        runner,
        "reboot",
        "Redémarrage du Pi",
        ["systemctl", "reboot"],
        30.0,
        "Redémarrage en cours…",
    )


def poweroff(runner) -> Action:
    return _simple(
        runner,
        "poweroff",
        "Extinction",
        ["systemctl", "poweroff"],
        30.0,
        "Extinction : attendre ~20 s avant de couper le courant",
    )


def terminal(runner, console) -> Action:
    def fn(progress: Progress) -> Outcome:
        console.text()
        res = runner.run(["systemctl", "--no-block", "start", GETTY_UNIT], 15.0)
        return cmd_outcome(res, "Terminal sur l'écran (retour : sudo jabuka-touch)")

    return Action("terminal", "Terminal", fn)


def night_toggle(cfg, cfg_path, save: Callable | None = None) -> Action:
    def fn(progress: Progress) -> Outcome:
        cfg.night = not cfg.night
        try:
            if save is not None:
                save(cfg_path, cfg)
        except OSError as e:
            return Outcome(
                True, (f"mode {'nuit' if cfg.night else 'jour'} (non enregistré : {e})",)
            )
        return Outcome(True, (f"mode {'nuit' if cfg.night else 'jour'}",))

    return Action("night_toggle", "Nuit / jour", fn)


PHONE_HINT = "sudo jabuka-wifi phone depuis le Terminal pour enregistrer le mot de passe"
DEMO_REFUSAL = "Démo en cours : revenir en mode course avant prerace"
CURRENT_RUNNING_REFUSAL = "Courant en cours : attendre la fin (JOURNAL)"


def prerace(
    runner,
    demo_active: Callable[[], bool] = lambda: False,
    wall: Callable[[], float] = time.time,
) -> Action:
    """Launch prerace (detached unit jabuka-prerace, returns at once), then schedule
    `jabuka-current --after-prerace <launch time>`: that detached unit waits for prerace by itself
    and runs only if prerace ends with code 0 or 3, so this worker is never blocked for the whole
    prerace and a menu restart does not lose the chain. Refused during a demo and while a current
    run is active."""

    def fn(progress: Progress) -> Outcome:
        if demo_active():
            return Outcome(False, (DEMO_REFUSAL,))
        cur = runner.run(["systemctl", "is-active", CURRENT_UNIT], 10.0)
        if cur.out.strip() in ACTIVE_STATES:
            return Outcome(False, (CURRENT_RUNNING_REFUSAL,))
        since = int(wall())  # before the launch: the prerace result written later is newer
        progress("Lancement de prerace…")
        res = runner.run([PRERACE], 30.0)
        if not res.ok:
            return cmd_outcome(res, "Prerace lancé : suivre le journal")
        progress("Programmation du courant après prerace…")
        cres = runner.run([CURRENT, "--after-prerace", str(since)], 30.0)
        lines = ["Prerace lancé : suivre le journal", *res.tail(2)]
        if cres.ok:
            lines.append("Courant : suivra prerace (si code 0 ou 3)")
        else:
            lines.append(
                f"Courant non programmé ({cres.describe()}) : bouton COURANT après prerace"
            )
            lines += cres.tail(1)
        return Outcome(True, tuple(lines))

    return Action("prerace", "Prerace", fn)


CURRENT_DEMO_REFUSAL = "Démo en cours : revenir en mode course avant le courant"


def current(runner, demo_active: Callable[[], bool] = lambda: False) -> Action:
    """Launch jabuka-current alone (detached unit jabuka-current, returns at once); refused during
    a demo (the script refuses too)."""

    def fn(progress: Progress) -> Outcome:
        if demo_active():
            return Outcome(False, (CURRENT_DEMO_REFUSAL,))
        progress("Lancement du courant Copernicus…")
        res = runner.run([CURRENT], 30.0)
        return cmd_outcome(res, "Courant lancé : suivre le journal")

    return Action("current", "Courant", fn)


def wifi_ap(runner) -> Action:
    def fn(progress: Progress) -> Outcome:
        progress("Retour au point d'accès jabuka…")
        return cmd_outcome(runner.run([WIFI, "ap"], 30.0), "Bascule vers le Wi-Fi bateau lancée")

    return Action("wifi_ap", "Wi-Fi bateau", fn)


def wifi_phone(runner) -> Action:
    def fn(progress: Progress) -> Outcome:
        progress("Bascule vers le partage du téléphone…")
        res = runner.run([WIFI, "phone"], 30.0)
        return cmd_outcome(res, "Bascule vers le téléphone lancée", hint=PHONE_HINT, n=1)

    return Action("wifi_phone", "Wi-Fi téléphone", fn)


def build_registry(
    runner,
    console,
    cfg,
    cfg_path,
    save: Callable | None = None,
    demo_active: Callable[[], bool] | None = None,
    wall: Callable[[], float] = time.time,
    **extra,
):
    """The fixed registry of action ids (tasks 2/3 add theirs through ``extra``)."""
    reg = {
        a.id: a
        for a in (
            restart_services(runner),
            reboot(runner),
            poweroff(runner),
            terminal(runner, console),
            night_toggle(cfg, cfg_path, save),
            prerace(runner, demo_active or (lambda: False), wall),
            current(runner, demo_active or (lambda: False)),
            wifi_ap(runner),
            wifi_phone(runner),
        )
    }
    for a in extra.values():
        if a is not None:
            reg[a.id] = a
    return reg
