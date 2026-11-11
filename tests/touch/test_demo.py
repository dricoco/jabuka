"""DÉMO / MODE COURSE: volatile drop-ins built from the effective ExecStart, verified before and
after the restart, rolled back on any mismatch; the race data is only ever read."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from jabuka_touch import config, demo
from jabuka_touch.actions import CORE_UNIT, INGEST_UNIT, CmdResult, FakeRunner
from jabuka_touch.demo import DROPIN_NAME, DemoPaths
from jabuka_touch.selftest import ManualClock

REPO = Path(__file__).resolve().parents[2]
UNIT_SRC = REPO / "deploy" / "systemd"
RACE_FILES = (
    "race.pmtiles",
    "coastline.geojson",
    "seamarks.geojson",
    "racepack.json",
    "polar.json",
    "landmask.npz",
    "landmask.json",
    "wind.npz",
    "wind.json",
    "waves.npz",
    "current.npz",
    "coverage.txt",
)
OVERRIDE = (
    "[Service]\nExecStart=\nExecStart=/opt/jabuka/venv/bin/jabuka-ingest-fastnet --device "
    "/dev/fastnet --data-dir /var/lib/jabuka --udp 127.0.0.1:47100 --awa-sign -1\n"
)


def _hash_tree(root: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class FakeSystem:
    """A tmp systemd: unit files from deploy/systemd, drop-ins of /etc and /run merged in
    filename order (as systemd applies them), a tmp /proc with the main processes' cmdlines."""

    PIDS = {CORE_UNIT: 1001, INGEST_UNIT: 1002}

    def __init__(self, tmp: Path, race_files=RACE_FILES):
        self.tmp = tmp
        self.paths = DemoPaths(
            race_data=tmp / "var/lib/jabuka",
            race_pack=tmp / "var/lib/jabuka/racepack",
            demo_root=tmp / "var/lib/jabuka-demo",
            run_dir=tmp / "run/jabuka-demo",
            dropin_root=tmp / "run/systemd/system",
            etc_root=tmp / "etc/systemd/system",
            proc=tmp / "proc",
        )
        self.paths.etc_root.mkdir(parents=True)
        self.paths.dropin_root.mkdir(parents=True)
        for unit in self.PIDS:
            (self.paths.etc_root / unit).write_text((UNIT_SRC / unit).read_text())
        self.paths.race_pack.mkdir(parents=True)
        for name in race_files:
            (self.paths.race_pack / name).write_bytes(f"race {name}".encode())
        (self.paths.race_data / "course.json").write_text('{"course": "A"}')
        self.stale: set[str] = set()
        self.inactive: set[str] = set()
        self.prerace = "inactive"
        self.fail: dict[tuple[str, ...], CmdResult] = {}
        self.runner = FakeRunner(default=self.handle)
        self.clock = ManualClock(0.0)
        for unit in self.PIDS:
            self._spawn(unit)

    # -- fake systemd ----------------------------------------------------------------------
    def operator(self, unit: str, name: str, text: str, root: str = "etc") -> Path:
        base = self.paths.etc_root if root == "etc" else self.paths.dropin_root
        p = base / f"{unit}.d" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def cat(self, unit: str) -> str:
        text = f"# {self.paths.etc_root / unit}\n" + (self.paths.etc_root / unit).read_text()
        confs = []
        for base in (self.paths.etc_root, self.paths.dropin_root):
            d = base / f"{unit}.d"
            if d.is_dir():
                confs += [p for p in d.iterdir() if p.suffix == ".conf"]
        for p in sorted(confs, key=lambda p: p.name):
            text += f"\n# {p}\n" + p.read_text()
        return text

    def _spawn(self, unit: str) -> None:
        argv = demo.effective_execstart(self.cat(unit))
        d = self.paths.proc / str(self.PIDS[unit])
        d.mkdir(parents=True, exist_ok=True)
        tokens = ["/opt/jabuka/venv/bin/python3", *argv]
        (d / "cmdline").write_bytes(b"\0".join(t.encode() for t in tokens) + b"\0")

    def handle(self, argv: list[str]) -> CmdResult:
        for prefix, res in self.fail.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return res
        if argv[:2] == ["systemctl", "cat"]:
            return CmdResult(0, self.cat(argv[2]))
        if argv[:2] == ["systemctl", "restart"]:
            for unit in argv[2:]:
                if unit not in self.stale:
                    self._spawn(unit)
            return CmdResult(0)
        if argv[:3] == ["systemctl", "show", "-p"]:
            return CmdResult(0, f"{self.PIDS[argv[-1]]}\n")
        if argv[:2] == ["systemctl", "is-active"]:
            states = []
            for u in argv[2:]:
                if u == demo.PRERACE_UNIT:
                    states.append(self.prerace)
                else:
                    states.append("failed" if u in self.inactive else "active")
            rc = 0 if all(s == "active" for s in states) else 3
            return CmdResult(rc, "\n".join(states) + "\n")
        if argv[0] == "systemd-run":
            self.paths.pty.symlink_to("/dev/pts/7")
            return CmdResult(0, "Running as unit: jabuka-demo-sim.service\n")
        if argv[0] == "runuser":
            dest = Path(argv[7])
            (dest / "wind.npz").write_bytes(b"demo wind")
            (dest / "wind.json").write_text("{}")
            return CmdResult(0, str(dest / "wind.npz") + "\n")
        return CmdResult(0)

    # -- helpers ---------------------------------------------------------------------------
    def start(self, fetch=None):
        lines: list[str] = []
        fetch = fetch or (lambda path: {"wind": {"source": "LIVE"}})
        out = demo.start_demo(
            self.runner,
            self.paths,
            config.Config(),
            lambda port: fetch,
            lines.append,
            sleep=self.clock.advance,
            clock=self.clock,
        )
        return out, lines

    def stop(self):
        lines: list[str] = []
        out = demo.stop_demo(
            self.runner, self.paths, lines.append, sleep=self.clock.advance, clock=self.clock
        )
        return out, lines

    def called(self, *prefix: str) -> list[list[str]]:
        return [c for c in self.runner.calls if tuple(c[: len(prefix)]) == prefix]


@pytest.fixture
def fs(tmp_path: Path) -> FakeSystem:
    return FakeSystem(tmp_path)


# -- unit parsing ----------------------------------------------------------------------------
def test_effective_execstart_operator_override_survives(fs: FakeSystem) -> None:
    fs.operator(INGEST_UNIT, "override.conf", OVERRIDE)
    argv = demo.effective_execstart(fs.cat(INGEST_UNIT))
    assert argv[-2:] == ["--awa-sign", "-1"]
    assert demo.effective_execstart(fs.cat(CORE_UNIT))[0] == "/opt/jabuka/venv/bin/jabuka-core"


@pytest.mark.parametrize(
    "text",
    [
        "[Service]\nType=simple\n",
        "[Service]\nExecStart=/a\nExecStart=/b\n",
        "[Service]\nExecStart=-/opt/x --y\n",
        "[Service]\nExecStart=@/opt/x x\n",
        "[Service]\nExecStart=+/opt/x\n",
        "[Service]\nExecStart=!/opt/x\n",
        "[Service]\nExecStart=:/opt/x\n",
    ],
)
def test_effective_execstart_refuses(text: str) -> None:
    with pytest.raises(ValueError):
        demo.effective_execstart(text)


def test_demo_argv_and_dropin_text() -> None:
    p = DemoPaths()
    core = demo.effective_execstart((UNIT_SRC / CORE_UNIT).read_text())
    got = demo.demo_argv("core", core, p)
    assert got == [
        "/opt/jabuka/venv/bin/jabuka-core",
        "--http-host",
        "0.0.0.0",
        "--http-port",
        "80",
        "--data-dir",
        "/var/lib/jabuka-demo/data",
        "--clock",
        "sim",
        "--gpsd",
        "127.0.0.1:2948",
        "--racepack",
        "/var/lib/jabuka-demo/racepack",
    ]
    ingest = demo.effective_execstart(OVERRIDE)
    got = demo.demo_argv("ingest", ingest, p)
    assert got == [
        "/opt/jabuka/venv/bin/jabuka-ingest-fastnet",
        "--device",
        "/run/jabuka-demo/fastnet-pty",
        "--data-dir",
        "/var/lib/jabuka-demo/data",
        "--udp",
        "127.0.0.1:47100",
        "--awa-sign",
        "-1",
    ]
    with pytest.raises(ValueError):
        demo.demo_argv("core", core, p, gpsd_port=2947)
    text = demo.dropin_text(got)
    lines = text.splitlines()
    i = lines.index("ExecStart=")
    assert lines[i + 1] == "ExecStart=" + " ".join(got)
    assert lines[i + 2] == "ReadWritePaths=-/var/lib/jabuka-demo"
    assert lines[lines.index("[Service]") + 1] == "ExecStart="
    with pytest.raises(ValueError):
        demo.dropin_text(["/bin/x", "a b"])
    with pytest.raises(ValueError):
        demo.dropin_text(["/bin/x", "$(reboot)"])
    assert "100%%" in demo.dropin_text(["/bin/x", "100%"])
    assert demo.set_flag(["a", "--x=1"], "--x", "2") == ["a", "--x=2"]


# -- demo pack -------------------------------------------------------------------------------
def test_demo_pack_copies_map_only_and_never_writes_race(fs: FakeSystem) -> None:
    before = _hash_tree(fs.paths.race_data)
    warnings = demo.build_demo_pack(fs.paths.race_pack, fs.paths.demo_pack)
    assert warnings == []
    assert sorted(p.name for p in fs.paths.demo_pack.iterdir()) == sorted(demo.PACK_FILES)
    assert _hash_tree(fs.paths.race_data) == before


def test_demo_pack_without_mask_warns(tmp_path: Path) -> None:
    fs = FakeSystem(tmp_path, race_files=("race.pmtiles", "polar.json", "wind.npz"))
    warnings = demo.build_demo_pack(fs.paths.race_pack, fs.paths.demo_pack)
    assert warnings == ["pas de masque terre : la route ne sera pas calculée"]
    assert sorted(p.name for p in fs.paths.demo_pack.iterdir()) == ["polar.json", "race.pmtiles"]


# -- start -----------------------------------------------------------------------------------
def _index(calls: list[list[str]], pred, start: int = 0) -> int:
    for i in range(start, len(calls)):
        if pred(calls[i]):
            return i
    raise AssertionError(f"call not found after {start}: {calls}")


def test_start_demo_sequence(fs: FakeSystem) -> None:
    before = _hash_tree(fs.paths.race_data)
    out, progress = fs.start()
    assert out.ok, out.lines
    assert out.lines[0].startswith("Démo lancée")
    calls = fs.runner.calls
    i = _index(calls, lambda c: c == ["systemctl", "stop", "jabuka-demo-sim.service"])
    i = _index(calls, lambda c: c == ["systemctl", "reset-failed", "jabuka-demo-sim.service"], i)
    i = _index(calls, lambda c: c[:4] == ["runuser", "-u", "jabuka", "--"], i)
    w = calls[i]
    assert w[4:7] == [
        "/opt/jabuka/venv/bin/python",
        "-I",
        "/opt/jabuka-touch/jabuka_touch/demo_wind.py",
    ]
    assert w[7:9] == [str(fs.paths.demo_pack), str(fs.paths.demo_root)]
    start = 1794592800.0  # 2026-11-13T18:00:00Z
    assert [float(v) for v in w[9:]] == [start, start + 4 * 86400, 161.0, 12.0, 6.0]
    i = _index(calls, lambda c: c[:2] == ["systemctl", "cat"], i)
    assert {calls[i][2], calls[i + 1][2]} == {CORE_UNIT, INGEST_UNIT}
    i = _index(calls, lambda c: c == ["systemctl", "daemon-reload"], i)
    j = _index(calls, lambda c: c[:2] == ["systemctl", "cat"], i)
    assert {calls[j][2], calls[j + 1][2]} == {CORE_UNIT, INGEST_UNIT}
    i = _index(calls, lambda c: c[0] == "systemd-run", j)
    sim = calls[i]
    assert sim[:14] == [
        "systemd-run",
        "--unit=jabuka-demo-sim",
        "--collect",
        "-p",
        "User=jabuka",
        "-p",
        "Group=jabuka",
        "-p",
        "Nice=5",
        "-p",
        "MemoryMax=200M",
        "-p",
        "Restart=on-failure",
        "/opt/jabuka/venv/bin/jabuka-sim",
    ]
    for pair in (
        ("--link", str(fs.paths.pty)),
        ("--gpsd-port", "2948"),
        ("--follow", "http://127.0.0.1:80"),
        ("--start-utc", "2026-11-13T18:00:00+00:00"),
        ("--variation", "4.7"),
        ("--twd", "161"),
        ("--shift", "6"),
    ):
        k = sim.index(pair[0])
        assert sim[k + 1] == pair[1], pair
    assert "--follow-route" in sim and "--follow-nowait" in sim
    i = _index(calls, lambda c: c == ["systemctl", "restart", INGEST_UNIT, CORE_UNIT], i)
    i = _index(calls, lambda c: c[:5] == ["systemctl", "show", "-p", "MainPID", "--value"], i)
    assert {calls[i][-1], calls[i + 1][-1]} == {CORE_UNIT, INGEST_UNIT}
    for unit in (CORE_UNIT, INGEST_UNIT):
        p = fs.paths.dropin(unit)
        assert p.is_file() and p.parent == fs.paths.dropin_root / f"{unit}.d"
        assert f"ReadWritePaths=-{fs.paths.demo_root}" in p.read_text()
    assert (fs.paths.demo_root / demo.MARKER).is_file()
    assert (fs.paths.demo_pack / "wind.npz").read_bytes() == b"demo wind"
    assert _hash_tree(fs.paths.race_data) == before
    assert demo.demo_active(fs.paths)
    assert progress and all(isinstance(x, str) for x in progress)


def test_start_demo_warns_without_live(fs: FakeSystem) -> None:
    out, _ = fs.start(fetch=lambda path: {"wind": {"source": "GRIB"}})
    assert out.ok and out.lines[0] == "démo lancée, vent LIVE pas encore là"


@pytest.mark.parametrize("why", ["dropin", "soak", "soak-etc", "prerace", "nopack"])
def test_start_demo_refusals(tmp_path: Path, why: str) -> None:
    fs = FakeSystem(tmp_path)
    if why == "dropin":
        fs.operator(CORE_UNIT, DROPIN_NAME, "[Service]\n", root="run")
    elif why == "soak":
        fs.operator(INGEST_UNIT, demo.SOAK_DROPIN, "[Service]\n", root="run")
    elif why == "soak-etc":
        fs.operator(CORE_UNIT, demo.SOAK_DROPIN, "[Service]\n", root="etc")
    elif why == "prerace":
        fs.prerace = "active"
    else:
        import shutil

        shutil.rmtree(fs.paths.race_pack)
    out, _ = fs.start()
    assert not out.ok and out.lines[0].startswith("ÉCHEC démo")
    assert fs.called("systemctl", "daemon-reload") == []
    assert fs.called("systemctl", "restart") == []
    assert not fs.paths.demo_root.exists()


def test_operator_override_before_ours_keeps_awa_sign(fs: FakeSystem) -> None:
    op = fs.operator(INGEST_UNIT, "override.conf", OVERRIDE)
    out, _ = fs.start()
    assert out.ok, out.lines
    eff = demo.effective_execstart(fs.cat(INGEST_UNIT))
    assert eff[eff.index("--device") + 1] == str(fs.paths.pty)
    assert eff[-2:] == ["--awa-sign", "-1"]
    assert op.read_text() == OVERRIDE


def test_operator_dropin_after_ours_rolls_back_before_restart(fs: FakeSystem) -> None:
    race = (UNIT_SRC / INGEST_UNIT).read_text().split("ExecStart=")[1].splitlines()[0]
    local = fs.operator(INGEST_UNIT, "zzz-local.conf", f"[Service]\nExecStart=\nExecStart={race}\n")
    out, _ = fs.start()
    assert not out.ok
    assert out.lines[0] == (
        "ÉCHEC démo : ExecStart effectif de jabuka-ingest-fastnet.service différent de la démo "
        "(drop-in appliqué après zz-jabuka-touch-demo.conf)"
    )
    assert out.lines[1] == "retour en mode course : OK"
    calls = fs.runner.calls
    reload_i = _index(calls, lambda c: c == ["systemctl", "daemon-reload"])
    assert fs.called("systemd-run") == []
    first_restart = _index(calls, lambda c: c[:2] == ["systemctl", "restart"])
    assert first_restart > reload_i
    # the only restart is the rollback's (after the second daemon-reload)
    assert len(fs.called("systemctl", "restart")) == 1
    assert len(fs.called("systemctl", "daemon-reload")) == 2
    assert not fs.paths.dropin(CORE_UNIT).exists() and not fs.paths.dropin(INGEST_UNIT).exists()
    assert local.is_file()
    assert not fs.paths.demo_root.exists()


def test_stale_main_process_rolls_back(fs: FakeSystem) -> None:
    fs.stale.add(CORE_UNIT)
    out, _ = fs.start()
    assert not out.ok and out.lines[0].startswith("ÉCHEC démo : le processus de jabuka-core")
    assert not demo.any_dropin(fs.paths)
    assert len(fs.called("systemctl", "restart")) == 2


def test_failing_step_rolls_back(fs: FakeSystem) -> None:
    fs.fail[("runuser",)] = CmdResult(1, "", "demo_wind : ValueError: refusing\n")
    out, _ = fs.start()
    assert not out.ok
    assert out.lines[0] == "ÉCHEC démo : vent démo (code 1 : demo_wind : ValueError: refusing)"
    assert out.lines[1] == "retour en mode course : OK"
    assert not demo.any_dropin(fs.paths) and not fs.paths.demo_root.exists()


def test_rollback_failure_shows_reboot_hint(fs: FakeSystem) -> None:
    fs.stale.add(INGEST_UNIT)
    fs.inactive.add(INGEST_UNIT)
    out, _ = fs.start()
    assert not out.ok and out.lines[1] == "retour en mode course : ÉCHEC"
    assert any("redémarrer le Pi rétablit le mode course" in ln for ln in out.lines)


# -- stop ------------------------------------------------------------------------------------
def test_stop_removes_only_ours_and_is_idempotent(fs: FakeSystem) -> None:
    out, _ = fs.start()
    assert out.ok
    soak = fs.operator(CORE_UNIT, demo.SOAK_DROPIN, "[Service]\n", root="run")
    override = fs.operator(INGEST_UNIT, "override.conf", OVERRIDE)
    local = fs.operator(INGEST_UNIT, "zzz-local.conf", "[Service]\nNice=1\n", root="run")
    out, _ = fs.stop()
    assert out.ok, out.lines
    assert out.lines[0] == "Mode course : capteurs réels, données de course"
    assert not demo.any_dropin(fs.paths)
    assert soak.is_file() and override.is_file() and local.is_file()
    assert not fs.paths.demo_root.exists() and not fs.paths.run_dir.exists()
    assert fs.paths.race_pack.is_dir()
    assert fs.runner.calls[-1] == ["systemctl", "cat", CORE_UNIT]
    out2, _ = fs.stop()
    assert out2.ok


def test_stop_not_active_after_30s_says_reboot(fs: FakeSystem) -> None:
    fs.start()
    fs.inactive.add(CORE_UNIT)
    out, _ = fs.stop()
    assert not out.ok
    assert (
        "Drop-ins démo retirés, mais jabuka-core.service pas actif : "
        "redémarrer le Pi rétablit le mode course"
    ) in out.lines
    assert not demo.any_dropin(fs.paths)
    assert fs.clock() >= 30.0


def test_wipe_guards(fs: FakeSystem) -> None:
    with pytest.raises(demo.DemoFailure):
        demo.safe_wipe(fs.paths.race_data, fs.paths)
    with pytest.raises(demo.DemoFailure):
        demo.safe_wipe(fs.paths.race_pack, fs.paths)
    with pytest.raises(demo.DemoFailure):
        demo.safe_wipe(fs.paths.race_data.parent, fs.paths)
    other = fs.tmp / "other"
    other.mkdir()
    (other / "keep").write_text("x")
    assert demo.safe_wipe(other, fs.paths) is False and (other / "keep").exists()
    with pytest.raises(demo.DemoFailure):
        demo.fresh_dir(other, fs.paths, None)
    (other / demo.MARKER).write_text("")
    assert demo.safe_wipe(other, fs.paths) is True and not other.exists()


# -- parity with the jabuka package (dev venv only) -------------------------------------------
def test_parity_with_jabuka() -> None:
    from jabuka.nav import geo
    from jabuka.nav.settings import Settings
    from jabuka.tools import rehearsal

    lat, lon = geo.offset(*rehearsal.PLIC, math.radians(341.0), 2.0)
    got = demo.demo_start_point()
    assert abs(got[0] - lat) < 1e-9 and abs(got[1] - lon) < 1e-9
    assert demo.DEMO_VARIATION == Settings().variation_deg
    assert (demo.DEMO_TWD, demo.DEMO_TWS, demo.DEMO_TWA) == (
        rehearsal.BOAT_TWD,
        rehearsal.BOAT_TWS,
        rehearsal.BOAT_TWA,
    )
    assert demo.PLIC == rehearsal.PLIC
    assert config.Config().demo.start_utc == rehearsal.BOAT_START_UTC.isoformat()


def test_demo_wind_script_writes_the_wind(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    dest = root / "racepack"
    dest.mkdir(parents=True)
    start = 1794592800.0
    script = REPO / "touch" / "jabuka_touch" / "demo_wind.py"
    args = [str(dest), str(root), f"{start:g}", f"{start + 4 * 86400:g}", "161", "12", "6"]
    p = subprocess.run(
        [sys.executable, "-I", str(script), *args], capture_output=True, text=True, timeout=120
    )
    assert p.returncode == 0, p.stderr
    assert (dest / "wind.npz").is_file() and (dest / "wind.json").is_file()
    meta = json.loads((dest / "wind.json").read_text())
    assert meta.get("sha256")
    t = np.load(dest / "wind.npz")["t"]
    assert t[0] <= start - 2 * 3600 and t[-1] >= start + 4 * 86400
    bad = subprocess.run(
        [sys.executable, "-I", str(script), str(tmp_path / "out"), str(root), *args[2:]],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert bad.returncode == 1 and "demo_wind" in bad.stderr


def test_demo_actions_registered(fs: FakeSystem) -> None:
    from jabuka_touch import actions
    from jabuka_touch.selftest import FakeConsole

    reg = actions.build_registry(
        fs.runner,
        FakeConsole(),
        config.Config(),
        fs.tmp / "t.json",
        **demo.demo_actions(fs.runner, fs.paths, config.Config(), lambda port: lambda p: None),
    )
    assert {"demo_start", "race_mode"} <= set(reg)
    assert reg["race_mode"].fn(lambda line: None).ok
