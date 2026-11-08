"""/proc probes for the soak: RSS, fds, threads and CPU of the core, the ingest, the forkserver and
the router worker, sampled every wall second into samples.csv, plus the checks over them.

The worker is found through the process tree: the core starts the forkserver (a child whose
command line mentions "forkserver"), the forkserver forks the worker. ``root`` lets the tests use
a fake /proc tree.

On a Raspberry Pi (vcgencmd on PATH) the sampler also records the SoC temperature and the
throttling bits every 10 wall seconds, as rows of role "pi" (plan 04-03: reported only, the Pi
numbers are still to confirm).
"""

from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROC = Path("/proc")
try:
    CLK_TCK = os.sysconf("SC_CLK_TCK")
except (ValueError, OSError, AttributeError):  # pragma: no cover - non-POSIX
    CLK_TCK = 100
FIELDS = (
    "t_wall",
    "t_sim",
    "role",
    "pid",
    "rss_kb",
    "fds",
    "threads",
    "cpu_s",
    "temp_c",
    "throttled",
)
SECONDS_36H = 36 * 3600.0
PI_INTERVAL_S = 10.0
# vcgencmd get_throttled bits (Raspberry Pi documentation)
THROTTLE_BITS: dict[int, str] = {
    0: "under-voltage now",
    1: "arm frequency capped now",
    2: "throttled now",
    3: "soft temperature limit now",
    16: "under-voltage occurred",
    17: "arm frequency capping occurred",
    18: "throttled occurred",
    19: "soft temperature limit occurred",
}


@dataclass
class Sample:
    t_wall: float
    t_sim: float
    role: str
    pid: int
    rss_kb: int
    fds: int
    threads: int
    cpu_s: float
    temp_c: float | None = None
    throttled: int | None = None


# -- Raspberry Pi ------------------------------------------------------------------------------
def parse_temp(text: str) -> float | None:
    """ "temp=48.3'C" -> 48.3."""
    m = re.search(r"temp=([-\d.]+)", text or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def parse_throttled(text: str) -> int | None:
    """ "throttled=0x50005" -> 0x50005."""
    m = re.search(r"throttled=(0x[0-9a-fA-F]+|\d+)", text or "")
    return int(m.group(1), 0) if m else None


def throttled_flags(bits: int) -> list[str]:
    return [name for bit, name in sorted(THROTTLE_BITS.items()) if bits & (1 << bit)]


def pi_probe(exe: str | None = None) -> Callable[[], tuple[float | None, int | None]] | None:
    """A (temp_c, throttled bits) reader when vcgencmd is on PATH (a Pi), else None."""
    exe = exe or shutil.which("vcgencmd")
    if exe is None:
        return None

    def run(arg: str) -> str:
        try:
            # review CR-01: keep the end-of-run children out of the harness's process group
            return subprocess.run(
                [exe, arg], capture_output=True, text=True, timeout=5, start_new_session=True
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def probe() -> tuple[float | None, int | None]:
        return parse_temp(run("measure_temp")), parse_throttled(run("get_throttled"))

    return probe


def pi_summary(samples: list[Sample]) -> dict[str, Any] | None:
    """report.json "pi": max temperature and every throttling bit seen (None off a Pi)."""
    rows = [s for s in samples if s.role == "pi"]
    if not rows:
        return None
    temps = [s.temp_c for s in rows if s.temp_c is not None]
    bits = 0
    for s in rows:
        bits |= s.throttled or 0
    return {
        "samples": len(rows),
        "temp_c_max": max(temps) if temps else None,
        "throttled_bits_seen": hex(bits),
        "throttled_flags_seen": throttled_flags(bits),
    }


def _stat_fields(pid: int, root: Path) -> list[str] | None:
    try:
        text = (root / str(pid) / "stat").read_text()
    except OSError:
        return None
    # comm may contain spaces/parens: split after the last ')'
    return text.rsplit(")", 1)[1].split()


def ppid(pid: int, root: Path = PROC) -> int | None:
    f = _stat_fields(pid, root)
    return int(f[1]) if f else None


def cpu_seconds(pid: int, root: Path = PROC, clk_tck: int = CLK_TCK) -> float | None:
    """utime + stime of the process (fields 14 and 15 of /proc/PID/stat) in seconds."""
    f = _stat_fields(pid, root)
    if not f or f[0] == "Z":
        return None
    return (int(f[11]) + int(f[12])) / float(clk_tck)


def status(pid: int, root: Path = PROC) -> dict[str, int] | None:
    """VmRSS (kB) and Threads from /proc/PID/status."""
    try:
        text = (root / str(pid) / "status").read_text()
    except OSError:
        return None
    out = {"rss_kb": 0, "threads": 0}
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            out["rss_kb"] = int(line.split()[1])
        elif line.startswith("Threads:"):
            out["threads"] = int(line.split()[1])
    return out


def fd_count(pid: int, root: Path = PROC) -> int | None:
    try:
        return len(os.listdir(root / str(pid) / "fd"))
    except OSError:
        return None


def cmdline(pid: int, root: Path = PROC) -> str:
    try:
        return (
            (root / str(pid) / "cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8", "replace")
        )
    except OSError:
        return ""


def children(pid: int, root: Path = PROC) -> list[int]:
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        if name.isdigit() and ppid(int(name), root) == pid:
            out.append(int(name))
    return sorted(out)


def router_tree(core_pid: int, root: Path = PROC) -> dict[str, Any]:
    """{"forkserver": pid | None, "workers": [pids]} under the core."""
    fs = None
    for c in children(core_pid, root):
        if "forkserver" in cmdline(c, root):
            fs = c
            break
    workers = children(fs, root) if fs is not None else []
    return {"forkserver": fs, "workers": workers}


def read(pid: int, root: Path = PROC) -> dict[str, Any] | None:
    st = status(pid, root)
    cpu = cpu_seconds(pid, root)
    fds = fd_count(pid, root)
    if st is None or cpu is None or fds is None:
        return None
    return {"rss_kb": st["rss_kb"], "threads": st["threads"], "fds": fds, "cpu_s": cpu}


class Sampler(threading.Thread):
    """Every ``interval`` wall seconds: one Sample per role from ``pids()`` -> samples.csv."""

    def __init__(
        self,
        path: Path,
        pids: Callable[[], dict[str, int | None]],
        sim_now: Callable[[], float],
        interval: float = 1.0,
        root: Path = PROC,
        pi_probe: Callable[[], tuple[float | None, int | None]] | None = None,
        pi_interval: float = PI_INTERVAL_S,
    ) -> None:
        super().__init__(name="soak-probes", daemon=True)
        self.path = Path(path)
        self.pids = pids
        self.sim_now = sim_now
        self.interval = interval
        self.root = root
        self.pi_probe = pi_probe
        self.pi_interval = pi_interval
        self._pi_last = -math.inf
        self.samples: list[Sample] = []
        self.lock = threading.Lock()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def sample_once(self) -> list[Sample]:
        t, ts = time.time(), self.sim_now()
        got = []
        try:
            roles = self.pids()
        except Exception:  # noqa: BLE001 - a probe never breaks the run
            roles = {}
        for role, pid in roles.items():
            if pid is None:
                continue
            r = read(pid, self.root)
            if r is None:
                continue
            got.append(Sample(t, ts, role, pid, r["rss_kb"], r["fds"], r["threads"], r["cpu_s"]))
        if self.pi_probe is not None and t - self._pi_last >= self.pi_interval:
            self._pi_last = t
            try:
                temp, thr = self.pi_probe()
            except Exception:  # noqa: BLE001 - a probe never breaks the run
                temp, thr = None, None
            got.append(Sample(t, ts, "pi", 0, 0, 0, 0, 0.0, temp, thr))
        with self.lock:
            self.samples.extend(got)
        return got

    def run(self) -> None:
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            while not self._stop.is_set():
                for s in self.sample_once():
                    w.writerow(
                        [
                            round(s.t_wall, 3),
                            round(s.t_sim, 1),
                            s.role,
                            s.pid,
                            s.rss_kb,
                            s.fds,
                            s.threads,
                            round(s.cpu_s, 3),
                            "" if s.temp_c is None else s.temp_c,
                            "" if s.throttled is None else hex(s.throttled),
                        ]
                    )
                f.flush()
                self._stop.wait(self.interval)


# -- analysis ----------------------------------------------------------------------------------
def segments(samples: list[Sample], role: str) -> list[list[Sample]]:
    """Samples of one role split per pid lifetime (a restart starts a new segment)."""
    out: dict[int, list[Sample]] = {}
    for s in samples:
        if s.role == role:
            out.setdefault(s.pid, []).append(s)
    return sorted(out.values(), key=lambda seg: seg[0].t_wall)


def longest(segs: list[list[Sample]]) -> list[Sample]:
    if not segs:
        return []
    return max(segs, key=lambda seg: seg[-1].t_sim - seg[0].t_sim)


def slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx


def leak_check(
    samples: list[Sample],
    role: str,
    *,
    budget_mb_36h: float,
    min_segment_s: float,
    warmup_s: float,
) -> dict[str, Any]:
    """Linear fit of RSS over the longest restart-free segment after the warm-up, as MB per
    36 sim-hours. Shorter than min_segment_s: ok None, "insufficient data"."""
    seg = longest(segments(samples, role))
    if not seg:
        return {
            "ok": None,
            "value": None,
            "budget": budget_mb_36h,
            "detail": f"insufficient data: no {role} samples",
        }
    t0 = seg[0].t_sim + warmup_s
    pts = [s for s in seg if s.t_sim >= t0]
    span = (pts[-1].t_sim - pts[0].t_sim) if len(pts) >= 2 else 0.0
    if span < min_segment_s or len(pts) < 10:
        return {
            "ok": None,
            "value": None,
            "budget": budget_mb_36h,
            "detail": f"insufficient data: {role} segment {span / 3600.0:.2f} sim-h after warm-up"
            f" < {min_segment_s / 3600.0:.1f} h",
        }
    k = slope([s.t_sim for s in pts], [s.rss_kb / 1024.0 for s in pts])
    mb = k * SECONDS_36H
    return {
        "ok": mb <= budget_mb_36h,
        "value": round(mb, 2),
        "budget": budget_mb_36h,
        "detail": f"{role} pid {pts[0].pid}: {len(pts)} samples over {span / 3600.0:.1f} sim-h",
    }


def max_rss_check(samples: list[Sample], role: str, budget_mb: float) -> dict[str, Any]:
    vals = [s.rss_kb / 1024.0 for s in samples if s.role == role]
    if not vals:
        return {
            "ok": None,
            "value": None,
            "budget": budget_mb,
            "detail": f"insufficient data: no {role} samples",
        }
    m = max(vals)
    return {
        "ok": m <= budget_mb,
        "value": round(m, 1),
        "budget": budget_mb,
        "detail": f"max over {len(vals)} samples (MB)",
    }


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def growth_check(
    samples: list[Sample], roles: tuple[str, ...], field: str, budget: float, warmup_s: float
) -> dict[str, Any]:
    """Growth of ``field`` within each segment after its warm-up: median of the last 5 samples
    minus median of the first 5 (worst segment reported)."""
    worst: tuple[float, str] | None = None
    for role in roles:
        for seg in segments(samples, role):
            t0 = seg[0].t_sim + min(warmup_s, (seg[-1].t_sim - seg[0].t_sim) / 4.0)
            pts = [float(getattr(s, field)) for s in seg if s.t_sim >= t0]
            if len(pts) < 10:
                continue
            g = _median(pts[-5:]) - _median(pts[:5])
            if worst is None or g > worst[0]:
                worst = (g, f"{role} pid {seg[0].pid}")
    if worst is None:
        return {
            "ok": None,
            "value": None,
            "budget": budget,
            "detail": "insufficient data: no segment with 10 samples",
        }
    return {"ok": worst[0] <= budget, "value": worst[0], "budget": budget, "detail": worst[1]}


def cpu_check(samples: list[Sample], role: str, budget: float) -> dict[str, Any]:
    """CPU seconds per sim second over every segment of ``role`` (clock jumps excluded)."""
    cpu = sim = 0.0
    for seg in segments(samples, role):
        for a, b in zip(seg, seg[1:], strict=False):
            dt = b.t_sim - a.t_sim
            if 0 < dt <= 600.0:  # a clock-jump step is not simulated time
                sim += dt
                cpu += max(0.0, b.cpu_s - a.cpu_s)
    if sim <= 0:
        return {"ok": None, "value": None, "budget": budget, "detail": "insufficient data"}
    v = cpu / sim
    return {
        "ok": v <= budget,
        "value": round(v, 4),
        "budget": budget,
        "detail": f"{cpu:.1f} CPU s over {sim:.0f} sim s",
    }


def finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)
