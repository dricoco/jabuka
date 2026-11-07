---
phase: 04-race-readiness-hardening-commissioning
plan: 03
subsystem: soak/systemd-backend
status: partial
tags: [soak, systemd, reliability, raspberry-pi, REL-02]

requires:
  - phase: 04-01
    provides: "soak harness (shim supervisor, faults, probes, report schema 1, race-36h scenario, scripts/soak.sh)"
provides:
  - "jabuka.soak.systemd.SystemdBackend: --systemd user (transient user units) and --systemd system (installed units + volatile /run drop-ins), cleanup always, --systemd-cleanup"
  - "ProcessBackend protocol in jabuka.soak.supervisor (shim and systemd implement it; faults call the backend)"
  - "report.md 'Mesures et budgets' table (report.budget_rows); report.json 'systemd' and 'pi' blocks"
  - "Pi metrics: vcgencmd temperature + throttling bits every 10 s (samples.csv rows of role 'pi')"
  - "scripts/soak.sh --systemd user|system, --systemd-cleanup, root check"
  - "docs/SOAK.md: systemd mode, laptop race-36h results, Pi 3B procedure, Pi budgets to confirm"
affects: [04-02 freeze-check F3/F4, phase-4-verification]

actuals:
  tokens: 72000
  tasks: 2
  commits: 10
plan_head_before: b04dae839a02d7dc6ba9687de9ca246ba1ef2c83
commits: 10

tech-stack:
  added: []
  patterns:
    - "Process control behind a small protocol: the same fault actions drive the laptop shim and real systemd"
    - "System scope touches production units only through volatile /run drop-ins that override ExecStart; cleanup in finally + atexit + signal handlers + a standalone --systemd-cleanup"
    - "The harness talks to port 80 only after checking the unit's new invocation runs the soak argv (never the production core)"

key-files:
  created:
    - src/jabuka/soak/systemd.py
    - tests/soak/test_soak_systemd.py
  modified:
    - src/jabuka/soak/supervisor.py
    - src/jabuka/soak/faults.py
    - src/jabuka/soak/probes.py
    - src/jabuka/soak/report.py
    - src/jabuka/soak/scenario.py
    - src/jabuka/tools/soak.py
    - scripts/soak.sh
    - docs/SOAK.md
    - tests/soak/test_soak_units.py
    - tests/soak/test_soak_tracer.py

decisions:
  - "watchdog-hang under systemd: the harness waits for systemd's own watchdog (SubState *-watchdog), then SIGCONTs the frozen pid so the WatchdogSignal lands at once; otherwise systemd waits TimeoutAbortSec (90 s), an artefact of SIGSTOP"
  - "Tracebacks in systemd mode come from journalctl -o json, written to proc/<role>-journal.log in the classifier's '<wall> <text>' format (includes the manager's exit/watchdog lines)"
  - "User scope copies Type/Restart/RestartSec/WatchdogSec (+ StartLimitIntervalSec=0, KillMode=control-group); hardening is not applied and disk-full is SKIPPED (services outside the harness's namespace)"
  - "System scope ignores scenario shim overrides (drop-ins override ExecStart only) and says so in the findings"
  - "Leak budget and warm-up left unchanged: the RSS curve plateaus, the 12 h fit stays under 20 MB/36 h (9.76 and 16.55)"

metrics:
  duration: "about 2 h 15 min (11:15-13:30 UTC), three full runs of ~36 min each in the background"
  completed: 2026-11-07
---

# Phase 4 Plan 03: Soak under real systemd and the 36 h laptop run Summary

The soak harness now drives real systemd: `--systemd user` runs the core and the ingest as
transient user units on the laptop (proven end to end: systemd itself restarts the killed core,
NRestarts 1, and the whole `ci` scenario passes including systemd's own watchdog), and
`--systemd system` points the Pi's installed units at the soak through volatile /run drop-ins
that override ExecStart only, with guaranteed cleanup. The full race-36h scenario ran three times
on the laptop: run 1 PASS, run 2 FAIL on a harness defect (fixed with a regression test), run 3
killed by Claude Code at 60 % because the laptop ran out of memory (other workloads), so **a PASS
report on the final HEAD is still owed** (see "Open item").

## What was built

- **`src/jabuka/soak/systemd.py`**: `render_dropins` / `soak_argv` / `dropin_text` (the shipped
  ExecStart with only --data-dir, --racepack, --clock sim, --gpsd <fake port>, --device changed;
  refuses a data dir outside /var/lib/jabuka/soak-* and port 2947), `SystemdBackend` (start,
  kill main|all, power_off/power_on/power_pull = kill all, stop, between, start, NRestarts banked
  across manual starts, exit codes and starts from a 0.5 s `systemctl show` monitor, watchdog
  detection, journal dump, cleanup), `cleanup_system`, `mount_logs` (loop ext4 image with no root
  reserve, or tmpfs), `soak_mounts`.
- **`supervisor.ProcessBackend`** protocol; the shim gained `starts`, `exit_codes`,
  `kill(whom=)`, `power_off/on/pull`, `watchdog_sec/kills`, `wait_watchdog`, `info`, behaviour
  unchanged. faults.py no longer reaches into `sup.services`.
- **`tools/soak.py`**: `--systemd user|system`, `--systemd-cleanup`, `--logs-fs loop:SIZE`
  (system only, max 1G); system scope prepares /var/lib/jabuka/soak-<ts>/ owned by the units'
  User=, chowns every pty slave (including unplug reopens), keeps port 80 for the tablet, chowns
  rewritten state files back, gives the run dir back to SUDO_UID; `checkout()` so the report
  names ~/jabuka when the Pi runs the installed wheel. No unshare re-exec in systemd mode.
- **Pi metrics** (`probes.pi_probe/pi_summary`): `vcgencmd measure_temp` / `get_throttled` every
  10 wall s, `report.json` → `pi.temp_c_max`, `throttled_flags_seen`.
- **Report**: `budget_rows` → report.md "Mesures et budgets" (recovery per class worst + p95,
  RSS, leak slope core/worker, fd/thread growth, CPU per sim s, tick ratio, log usage, land
  crossings, unexpected tracebacks); systemd and Pi lines.
- **scripts/soak.sh**: `--systemd`, `--systemd-cleanup`, refuses system scope without root (one
  line, exit 2).
- **docs/SOAK.md** (363 lines): systemd mode, laptop validation, "Résultats portable",
  "Soak sur le Pi 3B (à faire avant le 2026-11-10)" (9 steps), "Budgets Pi à confirmer", finding.

## Systemd mode on the laptop (systemd 260, user manager)

| Scenario | Verdict | Evidence |
|---|---|---|
| `--systemd user --scenario tracer` | PASS (twice) | NRestarts core 1, journal "Scheduled restart job, restart counter is at 1", recovery 3.0 s, ~22 s wall, no jabuka-soak-* unit left |
| `--systemd user --scenario ci` | PASS | 18 faults (disk-full SKIPPED: user scope), NRestarts core 5 / ingest 2, "Watchdog timeout (limit 5s)!" then restart, recovery 6.5 s, 23 routes no land, 0 unexpected tracebacks, 92 s wall |

System scope (root) cannot run on the laptop: its drop-ins are parsed by the real core/ingest
parsers and pass `systemd-analyze verify` with the shipped units (a broken drop-in is detected,
so verify really loads them); kill/power-pull order, cleanup on exception, stale-drop-in refusal,
`--systemd-cleanup`, the blocking restart and the "runs the soak argv" check are tested with a
fake systemctl.

## Full 36 h-equivalent runs (laptop, Python 3.13, shim, `bash scripts/soak.sh --scenario race-36h`)

Run under `nice -n 5 ionice -c2 -n7` in the background, waited on by polling for the report.

| Run | Report | Code | Result |
|---|---|---|---|
| 1 | `var/soak/20261107T113002Z-race-36h/report.json` | started on b04dae8; report stamped 0832f7f clean | **PASS**, 94 faults, 59.96x, 2162 s wall |
| 2 | `var/soak/20261107T120650Z-race-36h/report.json` | 0832f7f clean | FAIL: f92 clock-jump, no route within 60 s (harness defect, below) |
| 3 | `var/soak/20261107T124725Z-race-36h/` (no report) | 394aa31 clean | killed at sim 78 040 s (f80 of 94, 0 faults failed so far) by Claude Code's low-memory reaper; swap full, load 23 from other workloads; not restarted (instruction) |

The product code (`src/jabuka/{core,ingest,nav,route,sim,common}`) did not change in this plan;
only the harness did. Run 1's PASS therefore holds for the product, with the leak fit enforced on
the quiet tail.

### Budgets table (run 1, PASS)

| measure | measured | budget | ok |
|---|---|---|---|
| recovery bus (s) | worst 0.55, p95 0.54 (20 faults) | 10 | yes |
| recovery GPS (s) | worst 0.03, p95 0.03 (4 faults) | 10 | yes |
| recovery process restart (s) | worst 3.1, p95 3.1 (12 faults) | 30 | yes |
| recovery watchdog hang (s) | worst 25.93 (2 faults) | 60 (WatchdogSec + 30) | yes |
| recovery power pull (s) | worst 3.4, p95 3.4 (8 faults) | 60 | yes |
| route after fault (s) | worst 1.74, p95 1.06 (23 faults) | 60 | yes |
| restart with a short GRIB (s) | worst 4.36 (8 faults) | 30 | yes |
| log writes resume after disk full (s) | worst 0 (2 faults) | 30 | yes |
| max RSS core / worker (MB) | 79.3 / 150.4 | 250 / 250 | yes |
| leak slope core / worker (MB/36 h) | 9.76 / 4.71 (run 2: 16.55 / 0.84) | 20 | yes |
| fd growth / thread growth | 1 / 0 | 8 / 4 | yes |
| CPU per sim s | 0.0046 | 0.10 | yes |
| tick ratio | 1.0 | ≥ 0.95 | yes |
| log usage (MB) | 44 (128 MB tmpfs, 31 retention deletions) | 128 | yes |
| land crossings | 0 of 320 routes | 0 | yes |
| unexpected tracebacks | 0 (221 expected ENOSPC in disk-full windows) | 0 | yes |

Leak note: the core RSS is a plateau, not a ramp (65 MB at start, ~73-75 MB after 1-2 h, one
+4 MB step around sim 97 000 s in run 2, then flat ±1 MB for 8-10 h). The linear fit over the
whole 12 h segment overstates it; budget and warm-up were left unchanged.

### Findings

| Fault | Symptom | Cause | Fix | Test |
|---|---|---|---|---|
| clock-jump (run 2, f92) | no new route within 60 s after the clock stepped back | **harness**: course B finished inside the fault window (route state `no_course`, correct), and the harness selected the next course only between faults | `_route_after` runs the course upkeep while waiting (394aa31, RED b5565b5) | tests/soak/test_soak_tracer.py::test_route_wait_selects_the_next_course_when_the_boat_finished_during_a_fault |
| (review) system scope start | the harness could have configured the **production** core if it talked to port 80 before the drop-in restart landed | `restart --no-block` + an InvocationID counted on the old instance | blocking restart, new InvocationID required, main pid must carry every soak argument (0832f7f) | tests/soak/test_soak_systemd.py::test_harness_never_takes_the_production_core_for_the_soak_one |
| (review) soak.sh | exit 1 instead of the harness's 2 on a setup error | `grep` without a match under `pipefail` + `set -e` | grep runs under `set +e`; exit 2 passed through (d7b3293) | tests/soak/test_soak_units.py::test_soak_sh_refuses_system_scope_without_root |

No product defect was found by the full runs.

## Gate

`JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh` on 394aa31 (the final code;
only docs after it): ruff clean; Python 3.14 **1532 passed, 6 skipped** (620 s); Python 3.13
**1532 passed, 6 skipped** (619 s); `check: ok`, exit 0. No new skip (the user-scope end-to-end test
runs, ~22 s per interpreter).
`tests/soak` alone: 47 passed on 3.13 and 3.14 (~2 min each).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] soak.sh masked the harness's exit code 2** — found in Task 2 RED; grep under
pipefail aborted the script with 1; fixed in d7b3293.

**2. [Rule 2 - Missing safety] production core could receive soak HTTP calls** — found in
review before the Pi ever ran it (T-04-03-02); blocking restart + soak-argv check (0832f7f). The
test was written alongside the fix, not before it (small deviation from strict RED-first).

**3. [Rule 3 - Blocking] report git.head on the Pi** — the Pi runs the installed wheel, so
`repo_root()` is None and git.head would be null (freeze-check F4 fails); `checkout()` falls back
to the current directory (120be6f).

**4. [Rule 1 - Harness bug] f92 route wait during a finished course** — see Findings.

**5. watchdog-hang under systemd** uses SIGCONT after systemd's watchdog fires (documented
decision, not in the plan text): without it the hang fault would measure TimeoutAbortSec (90 s),
an artefact of SIGSTOP.

### Not as planned

- **Run 3 was killed by the environment** (Claude Code low-memory reaper, not a soak failure) and
  was not restarted, as instructed. The plan's "at most 3 full runs" cap is reached in count, but
  run 3 never reached a verdict.

## Open item (blocking freeze-check F3, not a product defect)

A race-36h PASS report on the final code is still needed: run 1 PASSed but its recorded head
(0832f7f) differs from HEAD in `src/jabuka/soak/faults.py`, so 04-02 `freeze-check.sh` F3 will
report "code modifié depuis le soak". When the laptop is quiet (no parallel gates, enough free
RAM), from the main checkout after merge:

```bash
nice -n 5 bash scripts/soak.sh --scenario race-36h     # ~36 min, verdict PASS expected
```

Also: the run dirs above live in this worktree's `var/soak/` (gitignored). They disappear with the
worktree unless copied to the main checkout's `var/soak/`. The report's git.head must stay an
ancestor of master (merge, not rebase/cherry-pick), or the re-run above is needed anyway.

## Human items (end of phase, non-blocking)

| Item | Due | Source |
|---|---|---|
| Re-run `bash scripts/soak.sh --scenario race-36h` on the final HEAD, laptop quiet (freeze-check F3) | before the freeze 2026-11-11 | 04-03 |
| System-scope soak on the Pi 3B (docs/SOAK.md "Soak sur le Pi 3B", race-36h at --speed 20 or 10), report copied back to the laptop's var/soak/, Pi rebooted, `systemctl cat jabuka-core \| grep -c 50-jabuka-soak` = 0 | 2026-11-10 | 04-03 |
| Record Pi RSS, temperature and throttling in docs/SOAK.md "Budgets Pi à confirmer" (closes 03-05 "Pi memory") | 2026-11-10 | 04-03 |
| 5 real power pulls with jabuka-logcheck (PI-SETUP §4 j) | before 2026-11-12 | 01-04 |
| Pi wheelhouse rebuilt after this plan so /opt/jabuka/venv has jabuka.soak.systemd | before the Pi soak | 04-03 |

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-04-03-01..06 mitigated as planned; T-04-03-02 hardened
further by the soak-argv check).

## Self-Check: PASSED

Files exist: src/jabuka/soak/systemd.py, tests/soak/test_soak_systemd.py, docs/SOAK.md (363
lines, "Soak sur le Pi 3B" present). Commits bbefb08, 38c275a, a3556e6, d7b3293, 120be6f,
330ed76, 0832f7f, b5565b5, 394aa31, 37f79bc are in the log (10 from b04dae8). No STATE.md or
ROADMAP.md change. No jabuka-soak-* user unit left loaded.
