---
phase: quick-261110-lqa
verified: 2026-11-10T00:00:00Z
status: passed
score: 8/8 must-haves verified
covered_files:
  - .planning/quick/261110-lqa-soak-chien-de-garde-routeur-temps-reel/261110-lqa-PLAN.md
  - .planning/quick/261110-lqa-soak-chien-de-garde-routeur-temps-reel/261110-lqa-SUMMARY.md
  - docs/ROUTING.md
  - src/jabuka/common/clock.py
  - src/jabuka/core/router_service.py
  - src/jabuka/tools/soak.py
  - tests/routing/conftest.py
  - tests/routing/test_supervisor.py
  - tests/soak/test_soak_units.py
  - tests/test_no_wallclock.py
covered_digest: "v1:sha256:fb0a8b4c3443dbef3aadf32dced47e2e3790e7767456df40d75697bc23860efc"
behavior_unverified: 0
overrides_applied: 0
---

# Quick 261110-lqa: Real-time router pool watchdog — Verification Report

**Goal:** The router pool watchdog (stuck threshold POOL_STUCK_S and re-creation back-off POOL_RETRY_S) measures REAL time, so the Pi soak (`--clock sim --speed 20`) no longer recycles the first routing job after about 6 real seconds. The soak waits 180 real seconds for the first route. Production (`--clock gps`) behaviour is unchanged.
**Status:** passed
**Re-verification:** No (initial verification)

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Under sim x20, a job that has run less than 120 real s is never recycled (200 sim s = 10 real s), and the route is adopted once released | VERIFIED | `router_service.py:842` `mono = self.real_monotonic()` feeds the stuck timer (`:867`, `:868`). The test `test_accelerated_sim_clock_never_recycles_a_slow_job` passes. **RED reproduced by the verifier:** in a scratch copy of 9062bb5 with the pre-fix `router_service.py`, the test fails with `AssertionError: a job running 10 real s must not be recycled` |
| 2 | A job that really runs longer than 120 s is recycled with the unchanged alert, even when the sim clock is frozen | VERIFIED | `test_stuck_job_is_recycled_on_real_time_while_the_sim_clock_stands_still` passes. It asserts the alert contains "calcul bloqué depuis plus de 120 s" and that the sim clock moved by at most 1 s. The alert format is unchanged (`f"calcul bloqué depuis plus de {POOL_STUCK_S:.0f} s"`). POOL_TIMEOUT_S=60, POOL_STUCK_S=2×60 and POOL_RETRY_S=30 are unchanged |
| 3 | After a failed pool re-creation, the next attempt waits 30 real s | VERIFIED | `_recycle_pool` sets `_pool_retry_mono = self.real_monotonic()` (`:895`), and `_watch_pool` compares against the same real `mono` (`:849`). `test_pool_recreation_retry_waits_real_seconds` passes: no new attempt after 200 sim s / 10 real s, then the third factory call after `advance_real(30)` |
| 4 | In production (`--clock gps`) the watchdog's real clock and the core clock are the same | VERIFIED | `GpsClock.__init__(mono=time.monotonic)` and `monotonic()` returns `self._mono()` (`clock.py:223`, `:297`). The only construction is `GpsClock(years=gps_years)` (`clock.py:365`), with no mono override. `os_monotonic()` returns `time.monotonic()` (`clock.py:42`). `main.py:118` constructs `RouterService` positionally, so the default `real_monotonic=os_monotonic` applies. main.py and route/pool.py are untouched since 3570af3 |
| 5 | Alert lifetimes, the bias save period and the pack re-check stay on the core clock | VERIFIED | `_pool_alarm` `self.clock.monotonic() + POOL_ALERT_S` (`:813`), `_invalid_alert` (`:1050`), `_observe_bias` (`:741`) and `_watch_pack` (`:823`) all still use `self.clock.monotonic()`. This is documented in the comment at `:812` and in docs/ROUTING.md |
| 6 | The RouterPool per-job timeout already runs on asyncio loop time (real) | VERIFIED | `route/pool.py` `t0 = loop.time()`, `elapsed = loop.time() - t0`, `asyncio.wait_for(..., self.timeout_s)`. The file was not modified |
| 7 | The soak waits for the first route in real seconds, `FIRST_ROUTE_TIMEOUT_S = 180` (at least 2×POOL_TIMEOUT_S + RETRY_NO_ROUTE_S), independent of `--speed` | VERIFIED | `soak.py:72` `FIRST_ROUTE_TIMEOUT_S = 180.0`, with a comment block. `wait_first` (`:649`) calls `TabletClient.wait`, whose deadline is `time.monotonic()` (`tablet.py:348-356`). The abort message says "wall s". The parity test `test_first_route_wait_is_real_seconds_and_covers_a_pool_retry` passes, including a check of the patched module-reference monotonic |
| 8 | Full gate `bash scripts/check.sh` is green on 3.14 and 3.13 | VERIFIED (scoped) | The orchestrator told the verifier not to re-run the full gate. The executor reports 2040 passed on both venvs. The verifier ran the targeted suites on 3.13 (57 passed) and `ruff check` on all 7 touched Python files (All checks passed) |

**Score:** 8/8 truths verified (0 present but behavior-unverified)

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/jabuka/common/clock.py` | VERIFIED | `def os_monotonic` at line 37. Docstring scopes it to process supervision |
| `src/jabuka/core/router_service.py` | VERIFIED | `real_monotonic: Callable[[], float] = os_monotonic` (`:222`) is stored (`:228`). `self.real_monotonic()` is used in `_watch_pool` and `_recycle_pool`. The module docstring is amended |
| `tests/routing/conftest.py` | VERIFIED | Has `real_t`, `real_rate`, `advance_real` and `tick` advancing `real_t`. `real_clock=True` installs `router.real_monotonic` |
| `tests/routing/test_supervisor.py` | VERIFIED | 3 new tests. `real_clock=True` appears 6 times: the wedge tests, `_shown_route_then_wedge` and the shutdown test are migrated |
| `tests/test_no_wallclock.py` | VERIFIED | Has the `_os_monotonic_uses` AST scan (allowed only in clock.py and router_service.py) plus a detector self-test. A grep of `src/` finds no other use |
| `src/jabuka/tools/soak.py` | VERIFIED | `FIRST_ROUTE_TIMEOUT_S = 180.0` with a comment |
| `tests/soak/test_soak_units.py` | VERIFIED | Parity test plus a real-clock wait proof. It patches only `tablet.time` |
| `docs/ROUTING.md` | VERIFIED | `### Worker supervision: which clock` (line 153) mentions `os_monotonic` |

## Key Link Verification

| From | To | Status |
|------|----|--------|
| `_watch_pool` | `self.real_monotonic` (default `os_monotonic` -> `time.monotonic`) | WIRED (`mono = self.real_monotonic()`, `:842`) |
| `RoutingCore` | `ctx.router.real_monotonic` | WIRED (`conftest.py`, `lambda: self.real_t`, used when `real_clock=True`) |
| `soak.py::wait_first` | `TabletClient.wait` (time.monotonic deadline) | WIRED (`:649`, `FIRST_ROUTE_TIMEOUT_S`) |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Targeted suites | `.venv313/bin/pytest tests/routing/test_supervisor.py tests/test_no_wallclock.py tests/soak/test_soak_units.py` | 57 passed in 7.62 s | PASS |
| The 3 new watchdog tests | `pytest test_supervisor.py -k "real_time or real_seconds or accelerated"` | 3 passed | PASS |
| RED on the pre-fix router | Scratch copy of 9062bb5 with `router_service.py` from 9062bb5^, `PYTHONPATH` set to the scratch `src` | 1 failed: "a job running 10 real s must not be recycled" | PASS (regression test discriminates) |
| Lint | `ruff check` on the touched files | All checks passed | PASS |

## Commit Hygiene

9062bb5, 6997902 and 8b806f5 each end with the Co-Authored-By line. None of them touches docs/SOAK.md, .planning/STATE.md, the `.bak` file, cad/, stl/, hardware/ or any i18n/reglages (kxm) file.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| REL-02 (36 h Pi soak can run) | SATISFIED (code side) | The watchdog no longer kills the first job under x20, and the setup wait is 180 wall s. The real Pi rerun is still owed by the orchestrator |
| ROUT-02 (routing reruns, never stops silently, never wrongly killed) | SATISFIED | Truths 1 to 3 |

## Anti-Patterns Found

None. There are no TBD/FIXME/XXX markers in the changed lines.

## Advisory / Notes (non-blocking)

- Pi watch item (from SUMMARY, confirmed unchanged): the `soak/scenario.py` DEFAULT_BUDGETS `"route": 60.0` is wall seconds for re-adoption after a restart. On the Pi 3B, a restart (forkserver spawn, worker init and an L0 cycle) must fit in 60 s. Watch this in the rerun.
- Under sim x20, RETRY_NO_ROUTE_S (core clock, 60 sim s) is about 3 real s. That is acceptable and documented ("less when accelerated").

## Gaps Summary

None.

---

_Verified: 2026-11-10_
_Verifier: Claude (gsd-verifier)_
