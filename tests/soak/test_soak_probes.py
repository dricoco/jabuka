"""Soak probes and state corruption (plan 04-01 Task 2): /proc readers on a fake tree, router
worker discovery, the leak fit, growth/CPU checks, and the corruption actions against the real
loaders."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from jabuka.common.atomicio import load_json_with_bak
from jabuka.core.router_service import RouterService
from jabuka.nav.course import CourseStore
from jabuka.nav.settings import Settings, SettingsStore
from jabuka.soak import probes
from jabuka.soak.faults import corrupt, drop_main, garbage, stray_tmp, truncate_half
from jabuka.soak.probes import Sample


def _proc(
    root: Path, pid: int, ppid: int, *, rss_kb=1000, threads=3, fds=5, ut=150, st=50, cmd="python"
):
    d = root / str(pid)
    (d / "fd").mkdir(parents=True)
    for i in range(fds):
        (d / "fd" / str(i)).write_text("")
    rest = ["S", str(ppid)] + ["0"] * 9 + [str(ut), str(st)] + ["0"] * 10
    (d / "stat").write_text(f"{pid} (py thon) " + " ".join(rest) + "\n")
    (d / "status").write_text(f"Name:\tpython\nVmRSS:\t  {rss_kb} kB\nThreads:\t{threads}\n")
    (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode() + b"\0")


def test_proc_readers_and_router_tree(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    _proc(root, 100, 1, rss_kb=81234, threads=9, fds=12, ut=250, st=50)
    _proc(root, 101, 100, cmd="python -c from multiprocessing.forkserver import main")
    _proc(root, 102, 100, cmd="python -c from multiprocessing.resource_tracker import main")
    _proc(root, 103, 101, rss_kb=120000)
    r = probes.read(100, root)
    assert r == {"rss_kb": 81234, "threads": 9, "fds": 12, "cpu_s": 3.0}  # 300 ticks / 100
    assert probes.children(100, root) == [101, 102]
    assert probes.router_tree(100, root) == {"forkserver": 101, "workers": [103]}
    assert probes.router_tree(103, root) == {"forkserver": None, "workers": []}
    assert probes.read(999, root) is None


def _series(role: str, pid: int, hours: float, mb0: float, mb_per_36h: float, noise: float = 0.0):
    rng = random.Random(1)
    out = []
    n = int(hours * 60)  # one sample per sim minute
    for i in range(n):
        t = i * 60.0
        mb = mb0 + mb_per_36h * t / (36 * 3600.0) + rng.uniform(-noise, noise)
        out.append(Sample(1000.0 + i, t, role, pid, int(mb * 1024), 10, 5, i * 0.1))
    return out


def test_leak_fit_fails_a_linear_rise_and_passes_flat_noise() -> None:
    kw = {"budget_mb_36h": 20.0, "min_segment_s": 3 * 3600.0, "warmup_s": 1800.0}
    rising = probes.leak_check(_series("core", 1, 36, 80, 30), "core", **kw)
    assert rising["ok"] is False and rising["value"] == pytest.approx(30.0, abs=0.5)
    flat = probes.leak_check(_series("core", 1, 36, 80, 0, noise=3.0), "core", **kw)
    assert flat["ok"] is True and abs(flat["value"]) < 5.0
    short = probes.leak_check(_series("core", 1, 2, 80, 30), "core", **kw)
    assert short["ok"] is None and short["detail"].startswith("insufficient data")
    # the longest restart-free segment is the one fitted
    segs = _series("core", 1, 1, 80, 300) + _series("core", 2, 10, 80, 0, noise=1.0)
    assert probes.leak_check(segs, "core", **kw)["ok"] is True


def test_growth_cpu_and_rss_checks() -> None:
    s = _series("core", 7, 2, 80, 0)
    assert probes.max_rss_check(s, "core", 250.0)["ok"] is True
    assert probes.max_rss_check(s, "core", 50.0)["ok"] is False
    assert probes.max_rss_check(s, "worker", 250.0)["ok"] is None
    grow = [
        Sample(x.t_wall, x.t_sim, x.role, x.pid, x.rss_kb, 10 + i // 10, 5, x.cpu_s)
        for i, x in enumerate(s)
    ]
    assert probes.growth_check(grow, ("core",), "fds", 8.0, 600.0)["ok"] is False
    assert probes.growth_check(s, ("core",), "threads", 4.0, 600.0)["ok"] is True
    cpu = probes.cpu_check(s, "core", 0.10)  # 0.1 CPU s per 60 sim s
    assert cpu["ok"] is True and cpu["value"] == pytest.approx(0.1 / 60.0, abs=1e-4)


def test_corruption_actions_stay_inside_the_run_dir(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "data").mkdir(parents=True)
    outside = tmp_path / "course.json"
    outside.write_text("{}")
    for fn in (truncate_half, drop_main, stray_tmp):
        with pytest.raises(ValueError, match="outside the soak run dir"):
            fn(outside, run)
    with pytest.raises(ValueError):
        garbage(outside, run)
    assert outside.read_text() == "{}"


def _write_state(data: Path) -> None:
    cs = CourseStore(data)
    cs.select("B")
    cs.select("A")  # second write: course.json.bak exists
    st = SettingsStore(data)
    st.update({"efficiency": 0.85}, base_version=0)  # single write: no settings.json.bak
    route = {"v": 1, "version": 3}
    (data / "route.json").write_text(json.dumps(route))
    (data / "route.json.bak").write_text(json.dumps(route | {"version": 2}))


@pytest.mark.parametrize("action", ["truncate_half", "garbage", "drop_main", "stray_tmp"])
def test_corruption_leaves_a_whole_version_or_a_default_with_alert(
    tmp_path: Path, action: str
) -> None:
    run = tmp_path / "run"
    data = run / "data"
    data.mkdir(parents=True)
    _write_state(data)
    target, desc = corrupt(action, data, run, random.Random(3))
    assert desc
    cs, st = CourseStore(data), SettingsStore(data)  # never raises
    if target == "course.json":
        # the main file as written, the .bak announced (04-05 WR-04), or the default announced
        main = cs.version == 2 and not cs.alerts
        bak = cs.version == 1 and cs.alerts == [
            "Parcours restauré depuis la sauvegarde : vérifier la marque active"
        ]
        assert main or bak or "Parcours illisible : Parcours A par défaut" in cs.alerts
    if target == "settings.json":
        if st.alerts:
            assert st.settings == Settings()
            assert "Réglages illisibles : valeurs par défaut" in st.alerts
        else:
            assert st.settings.efficiency == 0.85
    if target == "route.json":
        raw = load_json_with_bak(data / "route.json", None)
        assert raw == {"v": 1, "version": 2}  # the .bak
        with pytest.raises((KeyError, ValueError)):  # a partial document is refused
            RouterService._parse_saved(raw)
