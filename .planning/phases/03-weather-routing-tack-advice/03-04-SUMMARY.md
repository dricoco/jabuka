---
phase: 03-weather-routing-tack-advice
plan: 04
subsystem: routing
tags: [tack-advice, grib-bias, hysteresis, process-pool, forkserver, stdlib]

requires:
  - phase: 01-foundation
    provides: jabuka.common.conventions (true_wind_from_apparent, apparent_from_true, uv_from_wind_from, wind_from_uv), jabuka.common.units
provides:
  - "jabuka.route.advice: TackDetector, RouteFollower/Follow, MissedTackWatch, OffRouteWatch, StayOnTack, Triggers/TriggerInputs/Trigger, should_replace, cost_text, target_heading, to_xy/from_xy"
  - "jabuka.route.bias: BiasParams (apply_uv/weights/effective), BiasSample, BiasEstimator (gated EMA, manual entry, JSON state), bias_changed"
  - "jabuka.route.pool: RouterPool (forkserver, nice +10, timeout kill, crash recreate, coalescing), PoolOutcome, kill_pool, WORKER_START_METHOD"
  - "jabuka.route.pool_probe: init_probe, whoami, sleep_for, crash, boom, echo"
affects: [03-03, 03-05]

actuals:
  tokens: 19150
  tasks: 3
  commits: 5
plan_head_before: 347437420f839a8c03cfa35e69e883cab2603c4d

tech-stack:
  added: []
  patterns:
    - "Clock-injected pure state machines (every time is an argument, no clock reads)"
    - "TDD with interface skeletons in the RED commit so RED fails on assertions, not imports"
    - "Process pool driven from asyncio: submit/kill in asyncio.to_thread, wait_for(wrap_future) timeout"

key-files:
  created:
    - src/jabuka/route/advice.py
    - src/jabuka/route/bias.py
    - src/jabuka/route/pool.py
    - src/jabuka/route/pool_probe.py
    - tests/route/test_advice.py
    - tests/route/test_bias.py
    - tests/route/test_decisions.py
    - tests/route/test_pool.py
  modified: []

key-decisions:
  - "Heading to steer = TWD - TWA (project sign), golden-tested against conventions.py on both tacks"
  - "RouteFollower keeps an advised tack as next_tack with a negative wall-time countdown while COG/TWD show the boat still on the old tack; otherwise MissedTackWatch could never fire"
  - "Triggers latch off_route and missed on their rising edge until the next mark_requested; version counters and bias compare with the inputs of the last request"
  - "should_replace checks no_route before forced; cost_text shows '< 1 min' for any cost under 60 s, negatives included (Pitfall 9)"
  - "Bias gate reasons in French; extra reasons 'mesures périmées' (stale) and 'COG absent'; a gated sample counts for at most 10 s; 'actif' while the last gated sample is under 10 s old, else 's'estompe'"
  - "Newer observation wins between the manual entry and a valid EMA"
  - "Pool workers record their start method in WORKER_START_METHOD (the 3.13 child's multiprocessing default stays 'fork'); the test also proves forkserver by ppid != parent pid"

patterns-established:
  - "Route path point (t, lat, lon, twa_deg, tack, ...) and tack point (t, lat, lon, from_tack, to_tack, kind) consumed as plain tuples"
  - "Picklable job/initializer functions live in the package (pool_probe), never in test modules"

requirements-completed: [WIND-06, ROUT-02, ROUT-05, ROUT-06, ROUT-07, ROUT-09, ROUT-10]

coverage:
  - id: D1
    description: "Followed route gives target TWA/tack, heading from live TWD (sign golden-tested), route-time countdown, monotonic projection, XTE, finish; wind shift moves heading not TWA"
    requirement: ROUT-06
    verification:
      - kind: unit
        ref: "tests/route/test_advice.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Tack detector (30 s confirmation, 15-165 deg band, None pauses) and missed tack fired once, 2 min late"
    requirement: ROUT-10
    verification:
      - kind: unit
        ref: "tests/route/test_advice.py#test_overdue_tack_counts_down_negative_and_fires_missed_once"
        status: pass
    human_judgment: false
  - id: D3
    description: "GRIB bias estimator: gate, 300 s validity, circular mean, clamps, decay, Jabuka freeze, toggle, current correction, manual entry, JSON round trip"
    requirement: WIND-06
    verification:
      - kind: unit
        ref: "tests/route/test_bias.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Reroute triggers, hysteresis max(3 min, 1 %), off-route watch, stay-on-tack state"
    requirement: ROUT-05
    verification:
      - kind: unit
        ref: "tests/route/test_decisions.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "RouterPool on 3.13 and 3.14: forkserver + nice, timeout kill/recreate, crash recreate, error keeps pool, coalescing, loop jitter < 200 ms, close"
    requirement: ROUT-02
    verification:
      - kind: integration
        ref: "tests/route/test_pool.py (.venv and .venv313)"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-11-06
status: complete
---

# Phase 3 Plan 04: Tack advice, GRIB bias, reroute decisions and router pool Summary

**Pure-stdlib route following with a TWD − TWA heading and route-time countdown, a gated EMA GRIB bias (±35°, 0.6–1.5, τ 2.5 h decay, Jabuka freeze), explicit reroute triggers with max(3 min, 1 %) hysteresis, and a forkserver RouterPool that survives hangs and crashes on Python 3.13 and 3.14 without blocking the loop.**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-11-06T03:30Z
- **Completed:** 2026-11-06T03:48Z
- **Tasks:** 3
- **Files created:** 8

## Accomplishments
- `RouteFollower` projects the boat forwards only (40-segment window, then a global search past 2 nm). It returns target TWA/tack, heading `TWD − TWA`, XTE, course deviation, route-time countdown, ETA from the projection and a finished flag. Through a 15° shift the target TWA stays the same and the heading moves 15°.
- `TackDetector` only confirms a side change after 30 s inside the 15–165° band. Oscillation head to wind or dead downwind never confirms. `MissedTackWatch` fires once per advised tack.
- `BiasEstimator` follows Pattern 8 steps 1–9. The helm gets French states and reasons. A current correction converts the measured wind from water to ground through `conventions.uv_from_wind_from`/`wind_from_uv`. Manual observations work, and the state round-trips through JSON. `bias_changed` implements the 5° / 0.10 reroute threshold.
- Reroute decisions are explicit functions: `Triggers`, `should_replace`, `OffRouteWatch` and `StayOnTack`.
- `RouterPool` uses explicit forkserver with nice +10 and kills via `kill_workers()` on 3.14 or `_processes` on 3.13. It recreates the pool after a crash. One job runs and one waits, and the newest request wins. Submit and kill run off the event loop. A ticker sees no gap of 200 ms or more while a 1.5 s job runs, worker spawn included.

## Task Commits

1. **Task 1 (tracer): route following, tack detector, missed tack**: `2788f34` (feat)
2. **Task 2: GRIB bias**: RED `8d0c313` (test), GREEN `1f89886` (feat)
3. **Task 3: triggers, hysteresis, pool**: RED `7ebc6a9` (test), GREEN `f926b94` (feat)

## TDD Gate Compliance
- Task 2: the RED commit `8d0c313` held the tests plus an interface skeleton. `check tdd-red-evidence` returned RED_EVIDENCE_OK, with target `test_rotation_is_clockwise_for_positive_offset` failing on its assertion (−0.0 vs 90.0). GREEN is `1f89886`.
- Task 3: the RED commit `7ebc6a9` held the tests plus skeletons. RED_EVIDENCE_OK for both `test_should_replace` and `test_worker_identity_forkserver_and_nice`. GREEN is `f926b94`.
- No REFACTOR commits were needed.

## Files Created
- `src/jabuka/route/advice.py`: route following, tack detection, missed tack, cost text, triggers, hysteresis, off-route, stay-on-tack
- `src/jabuka/route/bias.py`: BiasParams, BiasSample, BiasEstimator, bias_changed
- `src/jabuka/route/pool.py`: RouterPool, PoolOutcome, kill_pool
- `src/jabuka/route/pool_probe.py`: picklable probe jobs for tests and diagnostics
- `tests/route/test_{advice,bias,decisions,pool}.py`: 69 tests, pass on .venv (3.14) and .venv313

`src/jabuka/route/__init__.py` was not created (03-01 owns it). Until then `jabuka.route` imports as a PEP 420 namespace package. This works on both venvs and in the full suite.

## Decisions Made
See `key-decisions` in the frontmatter. These two matter most for 03-05:
- **Overdue advised tack.** Per the plan formula, next_tack is "the first tack with t > t_route_here". Under that rule the countdown can never go negative: once the boat passes the tack point, the projection moves to the next leg. So the follower keeps the advised tack while COG and TWD show the boat on the tack it was supposed to leave, and the countdown then becomes wall time since the advised moment. This is what lets MissedTackWatch work end to end (test `test_overdue_tack_counts_down_negative_and_fires_missed_once`). Without COG or TWD the follower moves on and does not flag the tack.
- **Triggers.** `off_route` and `missed` latch on their rising edge and stay latched until `mark_requested`. A first check with no earlier request returns "first" if there is no route, or "timer" if a route was restored. 03-05 must call `OffRouteWatch.reset()` when a new route replaces the current one.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] A missed tack could not be detected from the follower's countdown**
- **Found during:** Task 1
- **Issue:** under the plan's next_tack rule (first tack with t > t_route_here) the countdown never goes negative, so the missed-tack trigger (ROUT-10) could never fire.
- **Fix:** the follower keeps an advised tack pending while COG/TWD show the boat still on `from_tack`, and reports a negative wall-time countdown.
- **Files modified:** src/jabuka/route/advice.py
- **Commit:** 2788f34

**2. [Rule 2] Extra bias gate reasons and a dt cap**
- **Found during:** Task 2
- **Issue:** the plan named no reasons for the stale and missing-COG gates, and a long gap between samples would count as steady-sailing time.
- **Fix:** added the reasons "mesures périmées" and "COG absent", and a gated sample now counts for at most 10 s.
- **Commit:** 1f89886

**3. [Rule 2] cost_text for negative costs**
- **Issue:** the plan's formula shows "+0 min" when cost ≤ −60 s.
- **Fix:** any cost under 60 s now shows "< 1 min", per Pitfall 9.
- **Commit:** 2788f34

**4. [Rule 2] RouterPool.close() resolves waiters**
- **Fix:** after `close()` the running request returns "error" ("pool closed") and the pending one returns "superseded". Any later `run_latest` raises RuntimeError. Without this, `close()` would leave awaiting callers hanging forever.
- **Commit:** f926b94

## Issues Encountered
- On Python 3.13, a forkserver child's `multiprocessing.get_start_method()` still returns the parent default (`fork`), so it cannot prove which start method was used. The worker therefore records its configured start method in `WORKER_START_METHOD`, and the test also asserts that the worker's parent pid is not the test process (it is the fork server).

## Verification
- `.venv/bin/python -m pytest tests/route -q` passes 69 tests, and so does `.venv313/bin/python -m pytest tests/route -q` (each repeated 3× with no flakes, about 4 s).
- `bash scripts/check.sh` gives `check: ok`: ruff clean, 640 passed and 2 skipped on both 3.14 and 3.13. The 2 skips already existed and are not in tests/route.
- Acceptance greps: `forkserver` and `_processes` appear in pool.py, `uv_from_wind_from` and `gelé (Jabuka)` in bias.py, `true_wind_from_apparent` in test_advice.py, and advice.py has no numpy import.

## Next Phase Readiness
- 03-03 can use BiasParams.apply_uv for each field step and RouterPool/pool_probe for the bench.
- 03-05 wires these into the core loop: TackDetector, RouteFollower, MissedTackWatch, OffRouteWatch, StayOnTack, Triggers, should_replace, BiasEstimator and RouterPool.
- 03-01's purity / no-wallclock scan should include these modules. They read no clock; pool_probe uses only `time.sleep`.

## Self-Check: PASSED
