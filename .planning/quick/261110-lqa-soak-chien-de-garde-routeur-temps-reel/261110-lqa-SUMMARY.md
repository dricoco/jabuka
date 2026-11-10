---
phase: quick-261110-lqa
plan: 01
status: complete
subsystem: routing / soak harness
tags: [router, watchdog, clock, soak, REL-02, ROUT-02]
requires: []
provides:
  - "jabuka.common.clock.os_monotonic (OS clock for process supervision only)"
  - "RouterService(real_monotonic=...) real-time pool watchdog and re-creation back-off"
  - "RoutingCore(real_clock=True) manual real clock for tests (real_t, real_rate, advance_real)"
  - "soak FIRST_ROUTE_TIMEOUT_S = 180 wall s"
affects: [src/jabuka/core/router_service.py, src/jabuka/tools/soak.py, Pi soak rerun]
tech-stack:
  added: []
  patterns: ["injectable real clock next to the injected domain Clock, AST-guarded scope"]
key-files:
  created: []
  modified:
    - src/jabuka/common/clock.py
    - src/jabuka/core/router_service.py
    - tests/routing/conftest.py
    - tests/routing/test_supervisor.py
    - tests/test_no_wallclock.py
    - src/jabuka/tools/soak.py
    - tests/soak/test_soak_units.py
    - docs/ROUTING.md
decisions:
  - "The pool watchdog's POOL_STUCK_S and the POOL_RETRY_S back-off run on the OS monotonic clock (os_monotonic, injectable as real_monotonic). Alert lifetimes, BIAS_SAVE_S and PACK_CHECK_S stay on the core clock"
  - "os_monotonic is allowed only in common/clock.py and core/router_service.py (test_no_wallclock guard)"
  - "The soak waits 180 wall s for the first route (>= 2 x POOL_TIMEOUT_S + RETRY_NO_ROUTE_S, parity-tested)"
metrics:
  duration: "~28 min"
  completed: 2026-11-10
estimate:
  tokens: 95000
  tasks: 3
actuals:
  tokens: 5900   # chars/4 over the three commits' diffs (23 625 chars)
  tasks: 3
  commits: 4     # MEASURED git rev-list --count plan_head_before..HEAD; includes 1 interleaved kxm commit (3fe7782)
plan_head_before: 3570af32436ce65c436bf26a82ff3e6b05a76cb5
plan_commits: [9062bb5, 6997902, 8b806f5]
---

# Quick 261110-lqa: Real-time router pool watchdog (Pi soak) Summary

The router pool watchdog now measures real OS seconds (`os_monotonic`, injectable as `RouterService(real_monotonic=...)`). Under the soak's `--clock sim --speed 20` it therefore no longer recycles the Pi's first routing job after about 6 real seconds. The soak waits 180 wall seconds for the first route.

## Root cause

`RouterService._watch_pool` read `self.clock.monotonic()`. In the soak the core runs a SimClock that follows sim message time (`observe_utc`) at x20. POOL_STUCK_S (120 s) therefore elapsed after about 6 real seconds. The Pi's first job takes longer than that: forkserver spawn, then `cycle.init_worker` loading the pack, land mask and geofields, then about 5 s of L0 routing. So every first job was killed, in a loop. The POOL_RETRY_S re-creation back-off (`_watch_pool` and `_recycle_pool`) had the same problem.

## Clock decision per timer

| Timer | Clock | Why |
|---|---|---|
| `_pool_watch` stuck threshold POOL_STUCK_S (120 s) | **REAL** (`self.real_monotonic()`) | It supervises a real OS process whose run time is real seconds |
| `_pool_retry_mono` back-off POOL_RETRY_S (30 s), set in `_watch_pool` and `_recycle_pool` | **REAL** | Same reason. Both reads and writes use the same clock, because mixing clocks would break the back-off. It also stops an accelerated clock from retrying fork every 1.5 real s after ENOMEM |
| `_pool_alarm` lifetime POOL_ALERT_S (5 min) | core (unchanged) | UI-facing, part of the displayed/simulated timeline the soak tablet observes. Consistent with INVALID_ALERT_S |
| `_invalid` lifetime INVALID_ALERT_S | core (unchanged) | UI-facing |
| `_observe_bias` BIAS_SAVE_S | core (unchanged) | Domain timeline |
| `_watch_pack` PACK_CHECK_S | core (unchanged) | Cheap sidecar JSON reads (`pack_fingerprint`) |
| Routing UTC (`now()`) | core (unchanged) | Domain time |
| RouterPool per-job timeout (60 s) | already REAL (unchanged) | `src/jabuka/route/pool.py` `_execute`: `t0 = loop.time()` (line 250), `elapsed = loop.time() - t0` (254), `asyncio.wait_for(asyncio.wrap_future(cfut), self.timeout_s)` (277). asyncio loop time is the OS monotonic clock. pool.py was not edited |

In production (`--clock gps`), `GpsClock` monotonic is `time.monotonic`, the same clock that `os_monotonic` reads, so race behaviour is unchanged. The POOL_* values and the alert text `ROUTEUR RELANCÉ : calcul bloqué depuis plus de 120 s` are unchanged.

## Soak setup wait

`src/jabuka/tools/soak.py::wait_first` calls `TabletClient.wait` (`src/jabuka/soak/tablet.py` lines 348-356), which sets `deadline = time.monotonic() + timeout`. These are real seconds, independent of `--speed`. FIRST_ROUTE_TIMEOUT_S went from 120 to 180 wall s, which covers:
- one RouterPool job killed at POOL_TIMEOUT_S (60 s);
- the RETRY_NO_ROUTE_S retry delay (60 s at speed 1);
- one complete second attempt (≤ 60 s).

A parity test (`test_first_route_wait_is_real_seconds_and_covers_a_pool_retry`) locks `180 >= 2 x 60 + 60` and `> POOL_STUCK_S`. It also proves that the deadline is read from tablet's `time.monotonic`, by replacing the module reference inside tablet.py only. The SoakAbort message now says "wall s". STARTUP_TIMEOUT_S and DEFAULT_BUDGETS are unchanged.

## TDD evidence (RED, then GREEN)

- RED: `test_accelerated_sim_clock_never_recycles_a_slow_job` ran against the unchanged router_service, with the conftest support already in place, and failed: `AssertionError: a job running 10 real s must not be recycled; assert 2 == 1`. The captured log showed `router pool: calcul bloqué depuis plus de 120 s`.
- GREEN: after the router_service change, `tests/routing/test_supervisor.py` + `tests/test_no_wallclock.py` gave 39 passed on 3.14, and test_supervisor gave 34 passed on 3.13 (the plan-checker advisory).
- Task 2: `-k "real_time or real_seconds or accelerated"` selects 3 tests, all passing. These tests passed on Task 1's implementation without any further router_service change. The Task 2 verify set (supervisor, no_wallclock, route_expiry, tack_advice_core) gave 65 passed on both 3.14 and 3.13. The held-pool tests no longer depend on a sim-time recycle.

## Gate

`bash scripts/check.sh` → ruff check OK, format OK, **2040 passed, 4 skipped** on 3.14 and **2040 passed, 4 skipped** on 3.13, ending with `check: ok`. The flaky UI test did not fail, so no rerun was needed.

## Commits (this plan, pinned SHAs)

| Task | SHA | Files |
|---|---|---|
| 1 | 9062bb5 | src/jabuka/common/clock.py, src/jabuka/core/router_service.py, tests/routing/conftest.py, tests/routing/test_supervisor.py |
| 2 | 6997902 | tests/routing/test_supervisor.py, tests/test_no_wallclock.py |
| 3 | 8b806f5 | src/jabuka/tools/soak.py, tests/soak/test_soak_units.py, docs/ROUTING.md |

None of these commits touches docs/SOAK.md, .planning/STATE.md, docs/I18N-SL-REVIEW.md.bak, cad/, stl/, hardware/ or any 261110-kxm file. `git rev-list --count 3570af3..HEAD` = 4, because a kxm docs commit (3fe7782) was interleaved by someone else between Task 2 and Task 3.

## Deviations from Plan

**1. [Rule 3 - Blocking] Parity test builds the TabletClient before patching `tablet.time`**
- **Found during:** Task 3
- **Issue:** `Signal.__init__` stamps `time.time()` (tablet.py line 54), so patching the module reference with a `SimpleNamespace(monotonic, sleep)` before construction raised AttributeError.
- **Fix:** Construct the client first, then patch only `tablet.time`. The assertion is unchanged: the `wait` deadline uses the patched counter and calls it ≤ 8 times.
- **Files:** tests/soak/test_soak_units.py. **Commit:** 8b806f5

Otherwise the plan was executed as written. main.py and route/pool.py were not edited.

## Watch item for the Pi rerun

`src/jabuka/soak/scenario.py` DEFAULT_BUDGETS `"route": 60.0` (wall s: a new route adopted after a restart) was left unchanged. It is a recovery check, not setup. On the Pi, a restart costs a forkserver spawn, worker init and one L0 cycle, so check that the post-restart route fits within 60 wall s in the rerun.

## Known Stubs

None.

## Self-Check: PASSED

- Files exist: all 8 modified files are present. `def os_monotonic` (clock.py), `self.real_monotonic()` ×2 and `real_monotonic: Callable` (router_service.py), `real_clock=True` ×6 (test_supervisor.py), `FIRST_ROUTE_TIMEOUT_S = 180.0` (soak.py), `### Worker supervision` + `os_monotonic` (ROUTING.md).
- Commits found: 9062bb5, 6997902, 8b806f5.
