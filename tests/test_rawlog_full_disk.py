"""Soak finding (plan 04-01, disk-full): with the log partition full, a long line (a derived diag
line is several KiB) written through Python's BufferedWriter could land half on disk while the
rest was dropped; the next successful line was then glued to that fragment, a corrupted line in
the middle of the log (logcheck: "invalid JSON"). The writer must keep whole lines only.

The full disk is reproduced without root with RLIMIT_FSIZE (EFBIG: the same short-write-then-
error sequence as ENOSPC), in a child process."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHILD = r"""
import json, os, resource, signal, sys
from jabuka.ingest.rawlog import RotatingAppendLog

d, size, limit = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
t = [0.0]
lg = RotatingAppendLog(d, "derived", suffix=".jsonl", mono=lambda: t[0], wall=lambda: 1794000000.0)
failed = 0
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
for i in range(12):
    t[0] += 0.3
    try:
        lg.write_json({"n": i, "pad": "x" * size})
        lg.maybe_flush()
    except OSError:
        failed += 1
resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))  # space freed
for i in range(100, 104):
    t[0] += 2.0
    lg.write_json({"n": i, "pad": "y"})
    lg.maybe_flush()
lg.close()
print(json.dumps({"failed": failed}))
"""


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_FSIZE / SIGXFSZ")
@pytest.mark.parametrize(
    ("size", "limit"), [(12000, 14000), (9000, 10000), (300, 700), (6000, 20000)]
)
def test_full_disk_never_leaves_a_torn_line_mid_file(tmp_path: Path, size: int, limit: int) -> None:
    d = tmp_path / "derived"
    r = subprocess.run(
        [sys.executable, "-c", CHILD, str(d), str(size), str(limit)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1])["failed"] > 0  # the disk was full
    ns = []
    for p in sorted(d.iterdir()):
        data = p.read_bytes()
        assert data.endswith(b"\n"), "closed cleanly: no torn tail either"
        for k, line in enumerate(data.split(b"\n")[:-1], start=1):
            try:
                ns.append(json.loads(line)["n"])
            except ValueError:
                pytest.fail(f"{p.name} line {k} is not whole JSON: {line[:40]!r}...{line[-40:]!r}")
    assert ns[:1] == [0] and ns[-4:] == [100, 101, 102, 103], ns  # writes resume once freed
    assert ns == sorted(ns)  # whole lines, in order
