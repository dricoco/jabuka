---
phase: 04-race-readiness-hardening-commissioning
plan: 10
subsystem: reliability
tags: [fsync, sd-stall, durability-thread, atomic-write, oom, systemd, gap-closure]
gap_ids: [G-4-R05, G-4-R06, G-4-R12]
plan_head_before: 6b3aa5264c5b03a43bd408b879aa8cefb5c6d2e1
status: complete

requires:
  - phase: 01
    provides: "ingest/rawlog.py RotatingAppendLog (ENOSPC whole-line rollback), common/atomicio.py atomic_write_json"
  - phase: 03
    provides: "route/pool.py RouterPool (forkserver worker, _pool_init)"
  - phase: 04
    provides: "deploy/systemd units, CI soak harness (scripts/soak.sh), check.sh gate"
provides:
  - "jabuka.common.atomicio durability thread: WORKER_NAME 'jabuka-durable', enable_background/disable_background/background_enabled/drain/background_status, fsync_fd(fd, on_done)"
  - "atomic_write_bytes background branch: synchronous .NAME.<n>.tmp write, _finish_atomic tail (fsync -> .bak -> rename -> dir fsync) FIFO; _sweep_orphans once per file per process"
  - "RotatingAppendLog: every fsync via atomicio.fsync_fd; cadence fsync skipped while _fsync_inflight"
  - "jabuka-core serve() and jabuka-ingest-fastnet _run() enable background mode and drain it at exit (DRAIN_TIMEOUT_S = 20 s)"
  - "diag core bg_write_pending / bg_write_errors"
  - "route.pool.raise_oom_score_adj, WORKER_OOM_SCORE_ADJ = 500, OOM_SCORE_ADJ_PATH; pool_probe.whoami oom_score_adj"
  - "StartLimitIntervalSec=0 in [Unit] of jabuka-fastnet-relay.service and fastnet2ip.service"
affects: [04-11, 04-12, commissioning, wheelhouse-rebuild, pi-soak]

actuals:
  tokens: 10000     # chars/4 over the plan's diff (src + tests + deploy, 39860 chars)
  tasks: 3
  commits: 6        # MEASURED rev-list 6b3aa52..68336a5 before the SUMMARY commit (3 RED + 3 GREEN)

tech-stack:
  added: []
  patterns:
    - "Opt-in process-wide durability thread: one FIFO daemon thread owns every fsync; entry points switch it on, tests/tools stay synchronous"
    - "fsync on a dup'd fd so the caller may close/rotate at once"
    - "Two-phase atomic write: temp written synchronously (errors stay on the caller), crash-safe tail queued in order"
    - "Best-effort self-demotion of a child process for the OOM killer (oom_score_adj raised, never lowered)"

key-files:
  created:
    - tests/test_background_durability.py
  modified:
    - src/jabuka/common/atomicio.py
    - src/jabuka/ingest/rawlog.py
    - src/jabuka/core/main.py
    - src/jabuka/ingest/fastnet_main.py
    - src/jabuka/route/pool.py
    - src/jabuka/route/pool_probe.py
    - deploy/systemd/jabuka-fastnet-relay.service
    - deploy/systemd/fastnet2ip.service
    - deploy/systemd/jabuka-core.service
    - tests/route/test_pool.py
    - tests/deploy/test_units.py

key-decisions:
  - "04-10: in jabuka-core and jabuka-ingest-fastnet every fsync runs on ONE FIFO thread (jabuka-durable); atomic_write_json callers (settings, course, manual wind, route.json, bias.json) are unchanged and inherit it; tests/tools never enable it"
  - "04-10: background atomic write = synchronous .NAME.<n>.tmp write (ENOSPC/EACCES/EROFS still 503 on the caller) then fsync -> .bak -> rename -> dir fsync queued; an API 200 may precede the fsync during an SD stall (accepted, drain at exit)"
  - "04-10: background failures are logged and counted (Diag core bg_write_errors), no tablet alert (accepted residual)"
  - "04-10: the routing worker raises its oom_score_adj to max(500, inherited) in _pool_init; the core keeps OOMScoreAdjust=-500"

patterns-established:
  - "Tests that need a stalled SD monkeypatch os.fsync to block only on the jabuka-durable thread and assert no fsync on any other thread"

requirements-completed: []  # REL-01/REL-02 already complete; gap closure only

coverage:
  - id: R05-tick
    description: "With fsync stalled on the durability thread, CoreContext.tick_once keeps its pace and no fsync runs on the caller"
    requirement: "REL-02"
    verification:
      - kind: unit
        ref: "tests/test_background_durability.py#test_tracer_a_stalled_fsync_never_blocks_the_core_tick"
        status: pass
  - id: R05-api
    description: "course next, settings put, manual wind post and event marker return < 0.5 s under a stalled fsync; files hold the last values after drain"
    requirement: "REL-02"
    verification:
      - kind: unit
        ref: "tests/test_background_durability.py#test_api_writes_return_promptly_under_a_stalled_fsync"
        status: pass
  - id: R05-semantics
    description: "Order + .bak, synchronous caller error, counted background EIO, orphan sweep once per file, cadence in-flight skip, sync mode unchanged"
    requirement: "REL-01"
    verification:
      - kind: unit
        ref: "tests/test_background_durability.py"
        status: pass
      - kind: integration
        ref: "tests/deploy/test_crash_recovery.py (real core + ingest in background mode, SIGKILL, logcheck)"
        status: pass
      - kind: soak
        ref: "var/soak-04-10/20261109T105127Z-ci (verdict PASS)"
        status: pass
  - id: R06
    description: "A real forkserver worker reports oom_score_adj = max(500, parent's); parent unchanged"
    requirement: "REL-02"
    verification:
      - kind: unit
        ref: "tests/route/test_pool.py#test_worker_raises_its_oom_score_adj"
        status: pass
  - id: R12
    description: "Both Plan B units carry StartLimitIntervalSec=0; systemd-analyze verify passes"
    requirement: "REL-01"
    verification:
      - kind: unit
        ref: "tests/deploy/test_units.py#test_relay_unit, #test_plan_b_conflicts_both_ways_and_not_enabled, #test_systemd_analyze_verify"
        status: pass

metrics:
  duration: 31 min
  completed: 2026-11-09
---

# Phase 4 Plan 10: SD-stall-proof durability thread, routing worker OOM demotion, Plan B start limit Summary

**A FIFO `jabuka-durable` thread owns every fsync and atomic-write tail in jabuka-core and jabuka-ingest-fastnet, so a 2 s SD stall now delays the core tick by 0.001 s instead of 2.001 s. The routing worker raises its oom_score_adj to +500, and both Plan B units restart forever.**

## Performance

- **Duration:** 31 min
- **Started:** 2026-11-09T10:45:25Z
- **Completed:** 2026-11-09T11:16:11Z
- **Tasks:** 3 (one tracer, two auto; all TDD with RED commits)
- **Files modified:** 12 (1 created)

## Accomplishments

- **G-4-R05 (major).** `common/atomicio.py` gains an opt-in, process-wide durability thread:
  - `RotatingAppendLog` hands its cadence, rotation, close and `fsync_now` fsyncs to it through a dup of the fd.
  - `atomic_write_bytes` writes `.NAME.<n>.tmp` on the caller, then queues fsync → `.bak` → rename → dir fsync in FIFO order.
  - jabuka-core `serve()` and jabuka-ingest `_run()` switch it on and drain it at exit (20 s).
  - Diag core shows `bg_write_pending` and `bg_write_errors`.
  - The callers (`nav/`, `course_api.py`, `nav_api.py`, `router_service.py`) are not edited. Grep over this plan's commits prints 0.
- **G-4-R06 (major).** `_pool_init` calls `raise_oom_score_adj(500)` first, best effort.
- **G-4-R12 (minor).** `StartLimitIntervalSec=0` is now in `[Unit]` of `jabuka-fastnet-relay.service` and `fastnet2ip.service`, and the unit tests assert it.

## Evidence

### Tracer timings (tick duration under a stalled fsync)

Measured with the real `CoreContext` and `SimClock`: 15 ticks, with `os.fsync` stalled 2 s.

| | Max tick | fsync thread(s) recorded |
|---|---|---|
| RED (before, sync code at `6b3aa52`) | **2.001 s** | `['MainThread']` |
| GREEN (after, background mode) | **0.001 s** | `['jabuka-durable']` |

In the test itself (15 s stall until release), every tick is under 0.5 s. The recorder holds only `jabuka-durable` entries and 0 `MainThread` entries. In the API test, every recorded fsync thread name is `jabuka-durable`. That covers course next, settings, manual wind and event, although the TestClient portal thread is the caller.

### CI soak

`bash scripts/soak.sh --scenario ci --out var/soak-04-10` gave **verdict PASS (exit 0)**. The report is `var/soak-04-10/20261109T105127Z-ci/report.md`, run with the real core and ingest in background mode (at commit state 29da7c8, code fingerprint d7c3f11ee505…).

### Worker oom_score_adj on the laptop

The parent's `/proc/self/oom_score_adj` is `0`, and the real forkserver worker's `whoami()["oom_score_adj"]` is `500`. `test_worker_raises_its_oom_score_adj` passes on Python 3.14 and 3.13.

### Gate tail (`var/gate-04-10.log`)

```
1656 passed, 4 skipped in 645.35s (0:10:45)
check: ok
EXIT=0
```

The plan's verification set (`test_background_durability`, `test_atomicio`, `test_rawlog_full_disk`, `test_logging`, `test_event_marker`, `test_no_wallclock`, `route/test_pool`, `tests/deploy`) gives 134 passed on `.venv` and 134 passed on `.venv313`.

## New src/jabuka fingerprint

This is `FINGERPRINT_SH` over `git archive 68336a5 src/jabuka`, the plan's last code commit. The working tree's `package_fingerprint` gives the same value (146 files).

**`76de7651e3753d7a90515ef9d4e8897b45df9bd001cb76a952ecd1887072072c`**

## Task Commits

1. **Task 1 (tracer): the durability thread and every log fsync through fsync_fd.** RED `a4cb7ba`, GREEN `e5cc205`.
2. **Task 2: background atomic writes, ingest switch-on, Diag counters, soak.** RED `dcd82ee`, GREEN `29da7c8`.
3. **Task 3: worker oom_score_adj +500 and Plan B `StartLimitIntervalSec=0`.** RED `5db377e`, GREEN `68336a5`.

## Decisions Made

- `_submit` starts the worker thread and counts the job under the condition. A failed thread start therefore never leaves `pending` stuck, which would make `drain()` hang.
- On failure, `_finish_atomic` also removes `.NAME.bak.tmp`. Otherwise a background EIO on the `.bak` replace would leave a stray hidden temp until the next write.
- `rawlog.py` keeps `import os` (marked `noqa: F401`) because existing sync tests patch `rawlog_mod.os.fsync`. That attribute is the process-wide `os.fsync`, so the patch still intercepts calls through `atomicio`.
- The tracer test polls briefly for the worker's first fsync. Right after a quick tick the worker may not have been scheduled yet (GIL switch interval). The poll does not hide blocking: the < 0.5 s tick bound and the 0 main-thread assertion stay strict.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test isolation of process-wide counters in the new test file**
- **Found during:** Task 2
- **Issue:** `background_status()["errors"]` and the temp-name counter are process-wide. The EIO test raised the error count for later tests, and the orphan test's own temp could reuse the number `12` of a swept orphan.
- **Fix:** Tests compare errors against their starting value. The orphan test checks that exactly one numbered temp is left and that it holds this write's own JSON, instead of checking names.
- **Files modified:** `tests/test_background_durability.py`
- **Commit:** `dcd82ee`

**2. [Rule 1 - Bug] The `background` fixture originally depended on `stall`**
- **Found during:** Task 2
- **Issue:** Tests that only wanted background mode got a 15 s fsync stall, so `drain(10)` returned False.
- **Fix:** `background` no longer depends on `stall`. Its teardown releases any live stall, through a module list, before draining.
- **Files modified:** `tests/test_background_durability.py`
- **Commit:** `dcd82ee`

No source deviation; the implementation follows the plan's contracts.

## Accepted Residuals

- During an SD stall, an API 200 precedes the fsync. A power cut inside the stall window loses only the last change. The temp write is synchronous, so the file is never torn and `.bak` is kept. `drain()` covers clean exits.
- A background EIO after a successful temp write raises no tablet alert. It is logged in the journal and counted in Diag core `bg_write_errors`. Full or read-only disks still fail synchronously with the existing 503 and alert.

## Known Stubs

None.

## Human Items (after merge, from the plan)

- Re-provision the Pi after 04-09..04-12 (the deploy units changed), then check that `systemctl show fastnet2ip -p StartLimitIntervalUSec` reads 0.
- During the Pi soak, the worker's `/proc/<pid>/oom_score_adj` should read 500 and the core's -500.
- In the Diag "Cœur" table, `bg_write_errors` should stay 0 and `bg_write_pending` should return to 0.
- Run the laptop race-36h soak and the Pi soak on the final HEAD.

## Self-Check: PASSED

- All 12 key files exist on disk.
- Commits a4cb7ba, e5cc205, dcd82ee, 29da7c8, 5db377e and 68336a5 are present in `git log`.
- `var/gate-04-10.log` ends with `check: ok` / `EXIT=0`. The soak report says verdict PASS.
