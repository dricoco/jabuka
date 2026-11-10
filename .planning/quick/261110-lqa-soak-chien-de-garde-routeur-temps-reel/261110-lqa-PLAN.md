---
phase: quick-261110-lqa
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/jabuka/common/clock.py
  - src/jabuka/core/router_service.py
  - tests/routing/conftest.py
  - tests/routing/test_supervisor.py
  - tests/test_no_wallclock.py
  - src/jabuka/tools/soak.py
  - tests/soak/test_soak_units.py
  - docs/ROUTING.md
autonomous: true
requirements: [REL-02, ROUT-02]

estimate:
  tokens: 95000
  raw_tokens: 95000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Under --clock sim accelerated x20 (the Pi soak), a router job that has run less than POOL_STUCK_S (120 s) of REAL time is never recycled, however much sim time elapses (regression test: 200 sim s = 10 real s held job, pool not recycled, no ROUTEUR RELANCE alert, route adopted once released)"
    - "A job that really runs longer than POOL_STUCK_S real seconds is still recycled with the unchanged alert text 'ROUTEUR RELANCÉ : calcul bloqué depuis plus de 120 s', even when the sim clock barely moves"
    - "After a failed pool re-creation, the next attempt waits POOL_RETRY_S (30 s) of REAL time, not sim time"
    - "In production (--clock gps, GpsClock mono = time.monotonic) the watchdog's real clock and the core clock are the same OS monotonic clock: race behaviour identical"
    - "UI-facing alert lifetimes (POOL_ALERT_S, INVALID_ALERT_S), the bias save period and the pack re-check stay on the core clock (unchanged, documented)"
    - "RouterPool's per-job timeout_s (60 s) already runs on asyncio loop time = real monotonic (confirmed, unchanged)"
    - "The soak setup waits for the first route in REAL seconds (TabletClient.wait on time.monotonic) for FIRST_ROUTE_TIMEOUT_S = 180 s >= 2 x POOL_TIMEOUT_S + RETRY_NO_ROUTE_S, independent of --speed"
    - "Full gate bash scripts/check.sh green on 3.14 and 3.13"
  artifacts:
    - path: "src/jabuka/common/clock.py"
      provides: "os_monotonic(): the OS monotonic clock, never simulated, for supervising real OS processes"
      contains: "def os_monotonic"
    - path: "src/jabuka/core/router_service.py"
      provides: "RouterService(real_monotonic=...) injectable real clock used by _watch_pool (stuck check + POOL_RETRY_S) and _recycle_pool"
      contains: "self.real_monotonic()"
    - path: "tests/routing/conftest.py"
      provides: "RoutingCore(real_clock=True): manual real clock (real_t, real_rate, advance_real) installed as router.real_monotonic"
      contains: "real_rate"
    - path: "tests/routing/test_supervisor.py"
      provides: "regression test (accelerated sim clock never recycles a slow job), real-time stuck test, real-time retry test; existing watchdog tests migrated to real_clock=True"
      contains: "real_clock=True"
    - path: "src/jabuka/tools/soak.py"
      provides: "FIRST_ROUTE_TIMEOUT_S = 180.0 wall seconds, documented"
      contains: "FIRST_ROUTE_TIMEOUT_S = 180.0"
    - path: "docs/ROUTING.md"
      provides: "Worker supervision clocks note (real vs core clock)"
      contains: "os_monotonic"
  key_links:
    - from: "src/jabuka/core/router_service.py::_watch_pool"
      to: "self.real_monotonic (default jabuka.common.clock.os_monotonic -> time.monotonic)"
      via: "stuck-job timer and POOL_RETRY_S back-off read the real clock, never self.clock.monotonic"
      pattern: "mono = self.real_monotonic()"
    - from: "tests/routing/conftest.py::RoutingCore"
      to: "ctx.router.real_monotonic"
      via: "real_clock=True installs a lambda over real_t; tick(dt) advances real_t by dt * real_rate"
      pattern: "router.real_monotonic"
    - from: "src/jabuka/tools/soak.py::wait_first"
      to: "jabuka.soak.tablet.TabletClient.wait"
      via: "deadline on time.monotonic (real seconds), timeout FIRST_ROUTE_TIMEOUT_S"
      pattern: "FIRST_ROUTE_TIMEOUT_S"
---

<objective>
Make the router pool watchdog measure REAL elapsed time instead of the (possibly accelerated) core
clock, so the Pi soak (`--clock sim`, `--speed 20`) stops recycling the routing worker every ~6 real
seconds and the first route can be adopted.

Root cause (observed at planning time): `src/jabuka/core/router_service.py::_watch_pool` (line ~829)
reads `self.clock.monotonic()`. Under the soak the core runs a SimClock that follows sim message time
(`src/jabuka/core/main.py` lines 155-156 and 178-183, `observe_utc`), i.e. x20. POOL_STUCK_S
(= 2 x POOL_TIMEOUT_S = 120 s, line 83) therefore elapses after ~6 real seconds, while the Pi's first
job (forkserver spawn + `cycle.init_worker` loading pack/landmask/geofields + ~5 s L0 routing) takes
longer, so it is killed forever. The same applies to the POOL_RETRY_S (30 s) creation back-off
(lines 836-838 and 882). With `--clock gps` (production) GpsClock's monotonic is `time.monotonic`, so
the race is not affected — the fix must keep production behaviour identical.

Clock decision per timer in router_service (justify in SUMMARY):
- REAL clock (supervision of a real OS process): `_pool_watch` stuck timer (POOL_STUCK_S), the
  `_pool_retry_mono` back-off (POOL_RETRY_S) set in `_watch_pool` and `_recycle_pool`.
- CORE clock, unchanged: `_pool_alarm` alert lifetime POOL_ALERT_S and `_invalid` INVALID_ALERT_S
  (UI-facing, part of the displayed/simulated timeline the soak's tablet observes, consistent with
  each other); `_observe_bias` BIAS_SAVE_S; `_watch_pack` PACK_CHECK_S (cheap sidecar JSON reads,
  `route/racepack.py::pack_fingerprint`); all routing UTC (`now()`).
- Already REAL, unchanged: `src/jabuka/route/pool.py` RouterPool `_execute` timeout uses
  `asyncio.wait_for(..., self.timeout_s)` and `loop.time()` — asyncio loop time is the OS monotonic
  clock. Confirm by reading lines ~255-275 and state it in SUMMARY; do not edit pool.py.

Soak harness finding (observed): `src/jabuka/tools/soak.py::wait_first` (line ~643) waits through
`TabletClient.wait` (`src/jabuka/soak/tablet.py` line ~348), whose deadline is `time.monotonic()` —
REAL seconds, independent of `--speed`. FIRST_ROUTE_TIMEOUT_S is 120 s (line 66). Raise it to 180 s
real (one RouterPool job killed at POOL_TIMEOUT_S 60 s + RETRY_NO_ROUTE_S 60 s retry delay at speed 1
+ one complete second attempt <= 60 s), documented in a comment and locked by a parity test.

Purpose: REL-02 (36 h soak on the Pi 3B must be able to run) and ROUT-02 (routing reruns
automatically, never stops silently, never wrongly killed) — the Pi soak is the last gate before the
2026-11-11 freeze.
Output: real-clock watchdog with an injectable real clock, regression tests, soak setup wait fixed and
documented, docs/ROUTING.md note, full gate green.
</objective>

<execution_context>
@/home/drico/.claude/gsd-core/workflows/execute-plan.md
@/home/drico/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@src/jabuka/common/clock.py
@src/jabuka/core/router_service.py
@src/jabuka/route/pool.py
@tests/routing/conftest.py
@tests/routing/test_supervisor.py
@tests/test_no_wallclock.py
@src/jabuka/tools/soak.py
@src/jabuka/soak/tablet.py

<interfaces>
Observed at planning time (do not re-derive):

- `tests/test_no_wallclock.py` BANS any call to `time.time()` / `time.monotonic()` and
  `from time import monotonic` in `core/`, `common/` (except `common/clock.py`), `nav/`, `route/`.
  So the real clock MUST be provided by `common/clock.py` and injected; router_service must never
  call the time module itself.
- `RouterService.__init__(self, state, clock, nav, hub, data_dir, racepack_dir, *, pool_factory=None)`
  constructed only in `src/jabuka/core/main.py:118` (positional args, no pool_factory). Tests set
  `ctx.router.pool_factory` after construction (`tests/routing/conftest.py` line ~260); the same
  post-construction pattern works for the real clock because `startup()` runs later in the
  TestClient lifespan.
- `RouterService._tick` calls `self._watch_pool()` FIRST (line ~428), before `_maybe_request`: the
  first tick submits the job, the second tick sees `stats["running"] == 1` and starts the watch.
- `_watch_pool` uses one local `mono` for both the retry back-off and the stuck timer; `_recycle_pool`
  sets `self._pool_retry_mono` from the core clock (line ~882).
- Alert text: `f"calcul bloqué depuis plus de {POOL_STUCK_S:.0f} s"` with ALERT_POOL prefix
  "ROUTEUR RELANCÉ : " — pinned by `tests/test_i18n.py` line 339 and an i18n.js regex. Do NOT change
  POOL_STUCK_S, POOL_TIMEOUT_S, POOL_RETRY_S values or this message.
- `RoutingCore.tick(dt)` advances the SimClock by dt then calls `ctx.tick_once` in the loop thread;
  `RoutingCore.settle()` waits in real time until `router.busy()` is False.
- `FakePool` (conftest): `hold = True` keeps the running job running; `stats` returns
  `{"jobs", "ok", ..., "running", "pending"}`; `start()` / `close()` are no-ops/flags.
- Existing tests that rely on the watchdog firing via sim-time ticks (must migrate to the injected
  real clock): `test_wedged_pool_is_recycled_with_an_alert`, `_shown_route_then_wedge` (used by
  `test_wedged_pool_losing_a_shown_routes_cycle_marks_it_stale`,
  `test_repeated_wedge_withdraws_the_route_after_10_min`, `test_wedged_missed_tack_reroute_is_released`
  via `_tick_until_recycled`), and `test_watchdog_never_recreates_a_pool_after_shutdown`
  ("past POOL_RETRY_S"). `test_pool_fault_raises_a_routing_health_alert` checks the 5-min alert on
  the core clock and must keep passing unchanged.
- Other held-pool tests (`tests/routing/test_route_expiry.py` lines ~95, ~172, ~233;
  `tests/routing/test_tack_advice_core.py` ~325; `test_supervisor.py` ~136, ~217, ~237) do not need the
  watchdog to fire; with the production default (real clock not advancing during a fast test) they
  see no recycle. The missed-tack expiry test at test_route_expiry.py ~172 then withdraws via
  MISSED_MAX_S instead of via a recycle; both paths produce a reason starting "virement manqué", so it
  must still pass — run it to confirm.
</interfaces>
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end "slow job under an accelerated sim clock is not recycled" — real clock for the stuck watchdog</name>
  <files>src/jabuka/common/clock.py, src/jabuka/core/router_service.py, tests/routing/conftest.py, tests/routing/test_supervisor.py</files>
  <read_first>src/jabuka/common/clock.py (whole), src/jabuka/core/router_service.py lines 1-20, 78-125, 207-310, 801-890, 1252-1270; tests/routing/conftest.py lines 240-360; tests/routing/test_supervisor.py lines 1-40 and 424-579; tests/test_no_wallclock.py</read_first>
  <behavior>
    - New regression test `test_accelerated_sim_clock_never_recycles_a_slow_job` (quick-261110-lqa): pools made by a factory (list `made`), first pool `hold = True`; core built with `real_clock=True` and `core.real_rate = 1.0 / 20.0` (the soak's --speed 20); record `t0 = core.clock.monotonic()`; 200 iterations of sail + `tick(1.0)` (200 sim s, 10 real s). Assert sim elapsed `core.clock.monotonic() - t0 > POOL_STUCK_S` (proves the old code would have recycled), `len(made) == 1`, `core.router.health()["pool_recycled"] == 0`, no alert starting "ROUTEUR RELANCÉ" in the last nav, `core.router.busy()` is True. Then `hold = False`, `settle()`, `tick(0.0)`: route state "ok" and version >= 1. Release holds in a finally/at end like the existing wedge tests.
    - Existing watchdog tests still pass once they pass `real_clock=True` (lock-step real clock, real_rate 1.0: each 1 s tick is 1 real s, so the 125-tick / POOL_STUCK_S+10-tick loops still reach the 120 s real threshold).
    - RED first: write the regression test and the conftest support, run it against the unchanged router_service and see it FAIL (pool recycled), then implement.
  </behavior>
  <action>
1. `src/jabuka/common/clock.py`: add a module-level function `os_monotonic() -> float` returning the time module's monotonic reading. Docstring: the OS monotonic clock in seconds, never simulated or accelerated; only for supervising real OS processes (the router worker pool watchdog and its re-creation back-off), whose run time is real seconds whatever the injected Clock (SimClock follows sim message time, x20 under the soak); domain time still comes from the injected Clock (quick-261110-lqa). Add one bullet to the module docstring naming it. This file is the only one allowed to read the time module (tests/test_no_wallclock.py), so the helper lives here.

2. `src/jabuka/core/router_service.py`:
   - Import `os_monotonic` alongside `Clock` from `jabuka.common.clock`.
   - Add keyword-only constructor parameter `real_monotonic: Callable[[], float] = os_monotonic` after `pool_factory`; store as `self.real_monotonic`. Comment: real OS time for supervising the worker process; injectable for tests; with --clock gps it is the same clock as `clock.monotonic` so production behaviour is identical.
   - In `_watch_pool`, take `mono` from `self.real_monotonic()` instead of the core clock (this single local feeds both the stuck timer and the retry back-off). Update the docstring: POOL_STUCK_S and POOL_RETRY_S are measured in real seconds because the worker is a real process; under --clock sim x20 the core clock turned a 6 s Pi job into "stuck for 120 s" (quick-261110-lqa).
   - In `_recycle_pool`, set `self._pool_retry_mono` from `self.real_monotonic()` (same clock as the comparison in `_watch_pool`; mixing clocks would break the back-off).
   - Comments: POOL_STUCK_S and POOL_RETRY_S constants gain "real s (OS monotonic, never the sim clock)"; the `_pool_watch` and `_pool_retry_mono` attribute comments say "real t". Keep `_pool_alarm` (POOL_ALERT_S) and `_invalid` (INVALID_ALERT_S) on `self.clock.monotonic()` and add one comment at `_pool_alarm` saying alert lifetimes are UI-facing and stay on the core clock like INVALID_ALERT_S. Leave `_observe_bias` and `_watch_pack` on the core clock.
   - Amend the module docstring line "Every time comes from the injected clock..." to add: except the pool watchdog and its re-creation back-off, which supervise a real OS process and run on real monotonic time (`real_monotonic`).
   - Do NOT change POOL_STUCK_S / POOL_TIMEOUT_S / POOL_RETRY_S values or the "calcul bloqué depuis plus de" alert format (pinned by tests/test_i18n.py and i18n.js). Do not edit main.py or route/pool.py.

3. `tests/routing/conftest.py` `RoutingCore`:
   - New keyword `real_clock: bool = False` in `__init__`. Always create `self.real_t = 0.0` and `self.real_rate = 1.0` (manual real seconds per sim second of `tick(dt)`; 1/20 = the soak's --speed 20). When `real_clock` is True, set `self.ctx.router.real_monotonic` to a lambda returning `self.real_t` (same post-construction pattern as `pool_factory`). When False the router keeps the production default (`os_monotonic`).
   - `tick(dt)`: after advancing the SimClock, add `dt * self.real_rate` to `self.real_t`.
   - New method `advance_real(seconds: float) -> None` adding to `self.real_t` (real time passing while the sim clock stands still).
   - Update the module docstring / RoutingCore docstring with one line about `real_clock`.

4. `tests/routing/test_supervisor.py`:
   - Write the regression test from <behavior> FIRST (import POOL_STUCK_S from jabuka.core.router_service inside the test like `_tick_until_recycled` does), run it and confirm it fails before step 2 is applied, then apply step 2.
   - Migrate the watchdog tests to the injected real clock by passing `real_clock=True` to `routing_core(...)` in `test_wedged_pool_is_recycled_with_an_alert`, in `_shown_route_then_wedge` (covers the three tests using it), and in `test_watchdog_never_recreates_a_pool_after_shutdown`. No other change to their bodies.
   - Keep the comment-header style of the section ("# -- pool watchdog (03-REVIEW CR-01) ---") and add a short comment above the new test referencing quick-261110-lqa (Pi soak: --clock sim x20).

5. Run `.venv/bin/ruff check src tests` and `.venv/bin/ruff format src/jabuka/common/clock.py src/jabuka/core/router_service.py tests/routing/conftest.py tests/routing/test_supervisor.py`.

6. Commit with explicit paths only (never git add -A, never stash/reset/clean/branch switch): `git add src/jabuka/common/clock.py src/jabuka/core/router_service.py tests/routing/conftest.py tests/routing/test_supervisor.py`, message in the repo's style, e.g. "fix(quick-261110-lqa): chien de garde du routeur en temps réel (soak --clock sim ×20)", body ending with the line "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv/bin/python -m pytest -q tests/routing/test_supervisor.py tests/test_no_wallclock.py -x && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n "def os_monotonic" src/jabuka/common/clock.py` returns 1 line.
    - `grep -c "self.real_monotonic()" src/jabuka/core/router_service.py` returns 2 or more (in `_watch_pool` and `_recycle_pool`).
    - `grep -n "real_monotonic: Callable" src/jabuka/core/router_service.py` returns 1 line.
    - `grep -c "real_clock=True" tests/routing/test_supervisor.py` returns 4 or more.
    - `.venv/bin/python -m pytest -q tests/routing/test_supervisor.py -k accelerated_sim_clock` passes; the same test was observed failing before the router_service change (state it in SUMMARY).
    - `tests/test_no_wallclock.py` passes (no direct time-module call added outside common/clock.py).
  </acceptance_criteria>
  <done>Under an accelerated sim clock (x20) a held job is not recycled before 120 real seconds; all existing watchdog tests pass on the injected real clock; production default is os_monotonic; committed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Prove both directions — real-time stuck detection with a frozen sim clock, real-time POOL_RETRY_S back-off, and guard os_monotonic's scope</name>
  <files>tests/routing/test_supervisor.py, tests/test_no_wallclock.py, src/jabuka/core/router_service.py</files>
  <read_first>tests/routing/test_supervisor.py (the pool watchdog section after Task 1), src/jabuka/core/router_service.py `_watch_pool`, `_new_pool`, `_recycle_pool` (lines ~826-890), tests/test_no_wallclock.py</read_first>
  <behavior>
    - `test_stuck_job_is_recycled_on_real_time_while_the_sim_clock_stands_still`: factory pools, first `hold = True`, `real_clock=True`. sail + `tick(1.0)` once (submits), then up to 5 sail + `tick(0.0)` until `core.call(lambda: core.router._pool_watch is not None)`; assert it became True. Record sim time, then `core.advance_real(POOL_STUCK_S + 1.0)`, sail + `tick(0.0)`: `len(made) == 2`, `pool_recycled == 1`, an alert starting "ROUTEUR RELANCÉ" whose text contains "calcul bloqué depuis plus de 120 s", and the sim clock moved by <= 1 s overall. Release holds at the end.
    - `test_pool_recreation_retry_waits_real_seconds`: factory call 1 returns a held FakePool, call 2 raises OSError(12, "Cannot allocate memory"), call 3+ returns a fresh FakePool; `real_clock=True`, `core.real_rate = 1.0 / 20.0`. Submit, wait for the watch as above, `advance_real(POOL_STUCK_S + 1.0)`, tick -> recycled, `core.router.pool is None`, factory called twice. Then 200 sail + `tick(1.0)` (200 sim s, 10 real s < POOL_RETRY_S): factory still called exactly twice and pool still None. Then `advance_real(POOL_RETRY_S)` + one `tick(0.0)`: factory called 3 times and `core.router.pool` is the third pool. Release holds.
    - `tests/test_no_wallclock.py::test_os_monotonic_stays_in_process_supervision`: AST-scan the same `_scanned()` files plus `common/clock.py`; any `ast.Name` or `ast.Attribute` whose id/attr is `os_monotonic` is allowed only in `common/clock.py` and `core/router_service.py`; assert the violation list is empty. Plus a detector self-test on a tmp sample file (like `test_detector_catches_violations`).
  </behavior>
  <action>
1. Add the two tests from <behavior> to the pool-watchdog section of `tests/routing/test_supervisor.py`, importing POOL_STUCK_S and POOL_RETRY_S from jabuka.core.router_service inside the tests. Use a small local helper (e.g. `_wait_watch(core, pos)`) for "tick with dt 0 until the watchdog is timing the running job" so both tests share it. Factories follow the existing `made` list pattern (append then return); the raising factory call must raise before appending a pool so `made`-style counting stays clear — keep a separate call counter.
2. Run them. They should pass on Task 1's implementation. If `test_pool_recreation_retry_waits_real_seconds` fails because some path still sets or compares `_pool_retry_mono` with the core clock, fix `src/jabuka/core/router_service.py` so every read and write of `_pool_retry_mono` and `_pool_watch` uses `self.real_monotonic()` (no other behaviour change). Only touch router_service.py if a test proves it necessary.
3. Add the os_monotonic scope guard and its detector self-test to `tests/test_no_wallclock.py` (module docstring gains one sentence: os_monotonic is the OS clock for process supervision only, allowed in core/router_service.py). Reuse `_attr_chain`/`ast.walk` style already in the file; report "relative/path:lineno os_monotonic".
4. `.venv/bin/ruff check src tests` and `.venv/bin/ruff format` on the touched files.
5. Commit explicit paths only: `git add tests/routing/test_supervisor.py tests/test_no_wallclock.py` (plus `src/jabuka/core/router_service.py` only if step 2 changed it), message e.g. "test(quick-261110-lqa): chien de garde et relance du pool en temps réel, horloge OS bornée à la supervision", ending with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv/bin/python -m pytest -q tests/routing/test_supervisor.py tests/test_no_wallclock.py tests/routing/test_route_expiry.py tests/routing/test_tack_advice_core.py -x && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests</automated>
  </verify>
  <acceptance_criteria>
    - `.venv/bin/python -m pytest -q tests/routing/test_supervisor.py -k "real_time or real_seconds or accelerated"` runs 3 tests, all pass.
    - `.venv/bin/python -m pytest -q tests/test_no_wallclock.py` passes and includes the new os_monotonic scope test.
    - `.venv/bin/python -m pytest -q tests/routing/test_route_expiry.py tests/routing/test_tack_advice_core.py` passes (held-pool tests no longer depend on a sim-time recycle).
  </acceptance_criteria>
  <done>The watchdog is proven to follow real time in both directions (no recycle under x20 sim for a 10 s real job; recycle after 121 real s with the sim clock frozen), the creation back-off waits 30 real seconds, os_monotonic cannot leak into domain code; committed.</done>
</task>

<task type="auto">
  <name>Task 3: Soak setup waits the first route in real seconds long enough for the Pi; document the clocks; full gate</name>
  <files>src/jabuka/tools/soak.py, tests/soak/test_soak_units.py, docs/ROUTING.md</files>
  <read_first>src/jabuka/tools/soak.py lines 60-70 and 636-650; src/jabuka/soak/tablet.py lines 337-356; src/jabuka/route/pool.py lines 245-285; docs/ROUTING.md lines 113-153; tests/soak/test_soak_units.py lines 1-50</read_first>
  <action>
1. `src/jabuka/tools/soak.py`: change FIRST_ROUTE_TIMEOUT_S from 120.0 to 180.0 with a comment block above it: WALL (real) seconds — `TabletClient.wait` runs on time.monotonic, so the wait does not shrink with --speed; on the Pi 3B the first route = forkserver spawn + worker init (pack, land mask, geofields) + one L0 cycle (bench p95 5.04 s), about 15-30 s real; 180 s covers one RouterPool job killed at POOL_TIMEOUT_S (60 s) + the RETRY_NO_ROUTE_S retry delay (60 s at speed 1, less when accelerated) + a complete second attempt (<= 60 s) (quick-261110-lqa). Make the SoakAbort message say the unit explicitly, e.g. "no route adopted within 180 wall s: ...", keeping the existing f-string on the constant. Do not import jabuka.core.router_service into tools/soak.py (keep the harness import-light); the parity test below ties the numbers together. Leave STARTUP_TIMEOUT_S and DEFAULT_BUDGETS in src/jabuka/soak/scenario.py untouched (the "route" 60 wall-s restart budget is a recovery check, not setup — mention it in SUMMARY as a watch item for the Pi rerun, do not change it).
2. `tests/soak/test_soak_units.py`: add `test_first_route_wait_is_real_seconds_and_covers_a_pool_retry`: import FIRST_ROUTE_TIMEOUT_S from jabuka.tools.soak and POOL_TIMEOUT_S, RETRY_NO_ROUTE_S, POOL_STUCK_S from jabuka.core.router_service; assert FIRST_ROUTE_TIMEOUT_S >= 2 * POOL_TIMEOUT_S + RETRY_NO_ROUTE_S and FIRST_ROUTE_TIMEOUT_S > POOL_STUCK_S. Also assert the wait is on the real monotonic clock without sleeping: `monkeypatch.setattr(jabuka.soak.tablet, "time", types.SimpleNamespace(monotonic=counter, sleep=noop))` where `counter` returns 0.0, 1.0, 2.0, ... per call (replace the module REFERENCE inside tablet.py only — never patch attributes of the global time module, other threads share it). Build `TabletClient("ws://127.0.0.1:9/ws")` WITHOUT calling start() (its __init__, observed at tablet.py lines 98-127, only creates a lock, an Event and Signals: no socket, no thread start). Assert `wait(lambda tb: None, 5.0)` returns None and that the counter was called a bounded number of times (<= 8), proving the deadline is measured by tablet's `time.monotonic`.
3. `docs/ROUTING.md`: at the end of the "## Router (isochrones, ROUT-01/03/04/07/08)" section (after the geofields code block, before "## Banc d'essai Pi"), add a subsection "### Worker supervision: which clock" in English, 6-10 lines: the pool watchdog's stuck threshold (POOL_STUCK_S 120 s) and creation back-off (POOL_RETRY_S 30 s) run on the OS monotonic clock (`jabuka.common.clock.os_monotonic`, injectable as `RouterService(real_monotonic=...)`), never the core clock, because the worker is a real process — under `--clock sim` (replay, soak at `--speed 20`) the core clock runs x20 and recycled a 6 s Pi job as "stuck for 120 s" (quick-261110-lqa); RouterPool's 60 s job timeout is asyncio loop time (real); alert lifetimes (ROUTEUR RELANCÉ, ROUTE INVALIDE, 5 min), the bias save period and the pack re-check stay on the core clock (the displayed timeline); with `--clock gps` both clocks are the same, so race behaviour is unchanged; the soak waits up to 180 wall s for the first route. Do NOT touch docs/SOAK.md (repo rule).
4. Run the full gate: `bash scripts/check.sh`. Known flaky UI test `test_switch_to_slovenian_then_english_persists_and_fits`: if it is the SOLE failure, rerun it alone (`.venv/bin/python -m pytest -q tests/ui -k test_switch_to_slovenian_then_english_persists_and_fits`) and record both runs in SUMMARY. Quick task 261110-kxm (i18n.js, reglages.js, reglages.css, i18n_review.py, docs/I18N-SL-REVIEW.md, tests/test_i18n.py, tests/ui/test_reglages.py) may have landed before this runs: never edit or stage those files; if one of its tests fails, report it rather than fixing it here.
5. Commit explicit paths only: `git add src/jabuka/tools/soak.py tests/soak/test_soak_units.py docs/ROUTING.md`, message e.g. "fix(quick-261110-lqa): attente de la première route du soak en secondes réelles (180 s), horloges du superviseur documentées", ending with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". Never stage docs/I18N-SL-REVIEW.md.bak, .planning/STATE.md, cad/, stl/, hardware/, docs/SOAK.md. No push, no deploy, do not touch the demo on port 8080 (the orchestrator deploys and reruns the Pi soak).
6. SUMMARY (`.planning/quick/261110-lqa-soak-chien-de-garde-routeur-temps-reel/261110-lqa-SUMMARY.md`) must record: root cause, the per-timer clock decision table (real vs core, with the justification from <objective>), confirmation that route/pool.py timeout is asyncio real time (cite the lines), that the soak setup wait is real time (tablet.py lines) and why 180 s, the RED-then-GREEN evidence for the regression test, gate results, and the watch item for the Pi rerun (DEFAULT_BUDGETS "route" 60 wall s after a restart). Do not edit the quick-task table in .planning/STATE.md.
  </action>
  <verify>
    <automated>cd /home/drico/git/jabuka && .venv/bin/python -m pytest -q tests/soak/test_soak_units.py -x && bash scripts/check.sh</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n "FIRST_ROUTE_TIMEOUT_S = 180.0" src/jabuka/tools/soak.py` returns 1 line.
    - `grep -n "### Worker supervision" docs/ROUTING.md` returns 1 line and `grep -c "os_monotonic" docs/ROUTING.md` returns 1 or more.
    - For each of this plan's three commit SHAs (record them in SUMMARY), `git show --name-only --format= <sha>` lists no docs/SOAK.md, .planning/STATE.md, docs/I18N-SL-REVIEW.md.bak, cad/, stl/, hardware/ or 261110-kxm file (pinned SHAs, not a relative anchor: kxm commits may interleave).
    - `bash scripts/check.sh` ends with "check: ok" (or the sole flaky UI test passes when rerun alone, recorded in SUMMARY).
  </acceptance_criteria>
  <done>The soak's first-route setup wait is 180 real seconds, locked by a parity test against the router constants; docs/ROUTING.md explains which clock each supervision timer uses; full gate green; committed; SUMMARY written.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| core event loop -> router worker process | The core supervises an OS process (forkserver worker) it cannot trust to finish: wedge, crash, ENOMEM |
| injected Clock (sim/gps) -> supervision timers | Simulated or GPS-disciplined time must not drive decisions about real OS processes |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-lqa-01 | Denial of Service | router_service._watch_pool | high | mitigate | Stuck timer on os_monotonic (real); regression test proves no recycle under x20 sim for a 10 real-s job, so routing is not killed in a loop |
| T-lqa-02 | Denial of Service | router_service._watch_pool (wedged worker never recycled) | high | mitigate | Converse test: a job held 121 real s with the sim clock frozen IS recycled with the unchanged alert; production GpsClock monotonic is time.monotonic, so identical race behaviour |
| T-lqa-03 | Denial of Service | pool re-creation after fork ENOMEM | medium | mitigate | POOL_RETRY_S back-off on real time (test): an accelerated clock can no longer hammer fork every 1.5 real s on the Pi |
| T-lqa-04 | Tampering | domain timing using the OS clock | low | mitigate | test_no_wallclock guard: os_monotonic allowed only in common/clock.py and core/router_service.py |
| T-lqa-05 | Denial of Service | soak setup false abort | low | accept | 180 wall-s first-route wait, parity-tested against POOL_TIMEOUT_S/RETRY_NO_ROUTE_S; a genuinely broken router only aborts 60 s later |
</threat_model>

<verification>
- `.venv/bin/python -m pytest -q tests/routing/ tests/test_no_wallclock.py tests/soak/test_soak_units.py` green.
- `bash scripts/check.sh` -> "check: ok" (3.14 and 3.13).
- Regression test observed RED before the router_service change and GREEN after.
- No change to POOL_* values, the alert text, main.py, route/pool.py, docs/SOAK.md, or any 261110-kxm file.
</verification>

<success_criteria>
- A router job under --clock sim x20 is recycled only after 120 REAL seconds; the first Pi route can complete and be adopted during the soak setup.
- Production (--clock gps) watchdog behaviour unchanged.
- Soak first-route wait documented as real seconds and long enough (180 s).
- Three atomic commits with explicit paths, each ending with the Co-Authored-By line; nothing pushed or deployed.
</success_criteria>

<output>
Create `.planning/quick/261110-lqa-soak-chien-de-garde-routeur-temps-reel/261110-lqa-SUMMARY.md` when done
</output>
