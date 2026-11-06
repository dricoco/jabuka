---
phase: 03-weather-routing-tack-advice
plan: 05
subsystem: core/routing-integration
status: complete
tags: [routing, supervisor, tack-advice, grib-only, grib-bias, persistence, coverage, numpy-lock, WIND-05, WIND-06, ROUT-02, ROUT-05, ROUT-06, ROUT-07, ROUT-08, ROUT-09, ROUT-10, GRIB-02, ROUT-11]

requires:
  - phase: 02-01
    provides: "CoreContext, tick_once, Hub, web create_app, pyproject/lock, bootstrap"
  - phase: 02-03
    provides: "NavService, WindPipeline (LIVE/LIVE_BG/MANUEL/NONE), Settings/_f, ManualWindStore, /api/wind/manual"
  - phase: 02-04
    provides: "CourseStore (seq, active_idx, last_idx, version), /api/course/*"
  - phase: 03-03
    provides: "route.cycle (init_worker, run_cycle), types (CycleRequest/Result, LEVELS), fields (WindField.at)"
  - phase: 03-04
    provides: "route.advice (TackDetector, RouteFollower, OffRouteWatch, MissedTackWatch, StayOnTack, Triggers, should_replace, cost_text), route.bias (BiasEstimator), route.pool (RouterPool)"
provides:
  - "jabuka.core.router_service.RouterService: pack load + coverage, RouterPool supervision from the tick, triggers, hysteresis, route following, On reste, cost, missed tack, invalid-route discard, GRIB wind provider, GRIB bias, route.json / bias.json persistence, health src router"
  - "jabuka.core.route_api: GET /api/route, POST /api/route/stay, POST /api/route/recompute"
  - "nav message: route block (every tick) and wind.source GRIB; WS route message on adoption and on connect"
  - "Settings: routing_enabled, route_level, route_cadence_min, tack_penalty_s, stay_extra_min, route_waves, route_current, grib_wind_fallback, bias_enabled, bias_tau_decay_h, race_start_local, race_end_local"
  - "numpy==2.5.4 runtime dependency in pyproject, requirements.in and the aarch64/cp313 hash lock; prep extra pygrib/shapely/netCDF4; console scripts jabuka-prep, jabuka-route-bench"
affects: [03-06, phase-4]

actuals:
  tokens: 31000
  tasks: 3
  commits: 6
plan_head_before: 640c36c71246bfa356e0d11203110a234084c42d
commits: 6

tech-stack:
  added: ["numpy 2.5.4 (Pi runtime, hash-locked)", "pygrib 2.1.8, shapely 2.2.0, netCDF4 1.7.5.1.post1 (prep extra, laptop only)"]
  patterns:
    - "Router tick inside update_nav: every nav message (1 Hz tick and every REST-triggered publish) carries the route block, so a course change or 'On reste' starts its job at once"
    - "Jobs scheduled on the core loop from any thread (call_soon_threadsafe when ticked outside the loop)"
    - "Integration tests drive the core tick by tick inside the event-loop thread (TestClient portal), 1 Hz loop disabled; a scripted FakePool with RouterPool coalescing semantics"

key-files:
  created:
    - src/jabuka/core/router_service.py
    - src/jabuka/core/route_api.py
    - tests/routing/conftest.py
    - tests/routing/test_route_tracer.py
    - tests/routing/test_tick_latency.py
    - tests/routing/test_supervisor.py
    - tests/routing/test_tack_advice_core.py
    - tests/routing/test_pack_alerts.py
    - tests/routing/test_grib_only.py
    - tests/routing/test_bias_core.py
  modified:
    - pyproject.toml
    - deploy/requirements.in
    - deploy/requirements.lock
    - tests/deploy/test_lock.py
    - scripts/bootstrap-dev.sh
    - tests/test_no_wallclock.py
    - src/jabuka/core/main.py
    - src/jabuka/core/web.py
    - src/jabuka/core/nav_service.py
    - src/jabuka/nav/wind.py
    - src/jabuka/nav/settings.py
    - tests/fixtures/nav/tracer_nav.json

key-decisions:
  - "The route block is added in CoreContext.update_nav, so every published nav message has it and a REST change (course, On reste, manual wind, settings) is seen by the router immediately"
  - "Coverage is checked for the course actually sailed (active course marks and legs), so selecting Course B adds Mulo and Course A never alerts for a Course B-only mark"
  - "A forced trigger stays forced when its request is superseded (carried to the next result); a change of route kind (optimal <-> stay) is always adopted"
  - "Off-route outdates the current route (hysteresis sees an age above 20 min); results computed for an older course version are dropped"
  - "The bias appearing (even +0 deg x1.00) fires a bias trigger, per 03-04 bias_changed"
  - "A manual wind entry restored from disk at startup is not re-observed as a fresh bias"

requirements-completed: [WIND-05, WIND-06, ROUT-02, ROUT-05, ROUT-06, ROUT-07, ROUT-08, ROUT-09, ROUT-10, GRIB-02, ROUT-11]

coverage:
  - id: D1
    description: "Live core routes Course A in the real forkserver worker; every nav message carries target TWA/tack, heading TWD - TWA, countdown, ETA, age; GET /api/route and exactly one WS route message per version"
    requirement: ROUT-02
    verification:
      - kind: integration
        ref: "tests/routing/test_route_tracer.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "1 Hz tick within 1 s +- 200 ms while the real worker routes Course A five times"
    requirement: ROUT-02
    verification:
      - kind: integration
        ref: "tests/routing/test_tick_latency.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Triggers (timer, course, manual, off-route, stay, missed), hysteresis max(3 min, 1 %), outdated/invalid old route, coalescing, ROUTE INVALIDE discard, timeout/crash keep the last route, route.json restore"
    requirement: ROUT-05
    verification:
      - kind: integration
        ref: "tests/routing/test_supervisor.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "On reste (forced route, cancel, detected tack, land release), cost text, L5 cadence, missed tack once, real-worker stay round trip"
    requirement: ROUT-07
    verification:
      - kind: integration
        ref: "tests/routing/test_tack_advice_core.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "MÉTÉO INCOMPLÈTE in nav alerts and router health; Course B coverage with Mulo; routing settings labels and bounds"
    requirement: GRIB-02
    verification:
      - kind: integration
        ref: "tests/routing/test_pack_alerts.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "GPS + GRIB-only wind, source ranking, slow boat, fallback switch"
    requirement: WIND-05
    verification:
      - kind: integration
        ref: "tests/routing/test_grib_only.py"
        status: pass
    human_judgment: false
  - id: D7
    description: "GRIB bias learned, shown, applied (router + GRIB-only wind), frozen at Jabuka, not after a tack, toggle, manual entry, bias.json restore"
    requirement: WIND-06
    verification:
      - kind: integration
        ref: "tests/routing/test_bias_core.py"
        status: pass
    human_judgment: false
  - id: D8
    description: "End-of-phase package review of the Pi lock (numpy 2.5.4 + hashes) and the prep pins"
    verification:
      - kind: manual_procedural
        ref: "git log -p -- deploy/requirements.lock"
        status: unknown
    human_judgment: true
    rationale: "Package policy (Phase 1/2): one end-of-phase human lock review, no blocking checkpoint during the unattended run"

duration: about 40 min
completed: 2026-11-06
---

# Phase 3 Plan 05: Core routing integration Summary

**The live core now routes the boat to the remaining marks in a supervised forkserver worker and
puts the route's advice into every 1 Hz nav message: target TWA/tack, heading TWD − TWA,
countdown to the next tack, cost of not tacking, ETA, age and state. "On reste", the missed-tack
recompute, hysteresis, invalid-route discard, route/bias persistence, MÉTÉO INCOMPLÈTE alerts,
the GPS + GRIB-only wind source and the GRIB bias all run end to end. numpy is in the hashed Pi
lock.**

## Performance

- **Duration:** about 40 min (first commit 11:06, last 11:32 local, plus the gate)
- **Tasks:** 3 (1 tracer, 2 TDD), 6 commits (RED + GREEN per task)
- **Files:** 10 created, 12 modified

## Accomplishments

- **Dependencies.** numpy==2.5.4 is in `[project].dependencies`, `deploy/requirements.in` and the
  aarch64/cp313 hash lock. The relock added only numpy (68 lines). `EXPECTED_LOCKED` includes it.
  `bash scripts/build-wheelhouse.sh` (no `--relock`) downloaded the 19 Pi wheels and passed the
  offline `--require-hashes` install simulation. The prep extra gains pygrib 2.1.8, shapely 2.2.0
  and netCDF4 1.7.5.1.post1. Console scripts `jabuka-prep` and `jabuka-route-bench` both answer
  `--help`. weatherrouting and latlon3 are in no dependency list.
- **RouterService.**
  - At startup it loads the pack (wind + land mask) and runs coverage, then restores
    `route.json` and `bias.json` and creates the `RouterPool(cycle.init_worker, (pack,), 60 s,
    nice 10)`. The worker itself starts on the first job.
  - Every tick it applies the gates in order: disabled, `blocked_clock` ("heure GPS non valide"),
    `no_pack` (the loader's French error), `no_course`, `no_position`.
  - It follows the adopted route and runs the triggers and hysteresis, then submits a
    `CycleRequest` snapshot as a loop task.
  - On adoption it bumps the version, creates a new `RouteFollower`, calls `OffRouteWatch.reset()`,
    saves `route.json` atomically and publishes the route message.
- **Route block.** It follows the interfaces contract and every key is always present.
  - `primary` is "twa" when |target TWA| is under 70° or over 110°, otherwise "hdg".
    `target`/`deviation` mirror the Phase 2 helm semantics.
  - The block also carries the countdown and tack point, plus `missed`/`updating`.
  - It shows the cost and `cost_text`, the `stay` state with its land release, the `bias` block,
    `pack` (model, run, alerts) and pool `health`.
  - The Diag rows `nav.route.countdown`, `nav.route.cost`, `nav.bias.dir` and `nav.bias.ratio`
    come from this block.
- **REST and WS.**
  - `GET /api/route` returns the route message, or 404 with `{state, reason}`.
  - `POST /api/route/stay` takes a strict `{"active": bool}` body. It answers 422 for a bad body
    and 409 when the tack is unknown.
  - `POST /api/route/recompute` forces a reroute.
  - `/ws` sends the current route on connect.
- **GRIB-only wind.**
  - `WindPipeline` ranks the sources LIVE > LIVE_BG > MANUEL > GRIB > NONE.
  - In GRIB mode the heading is COG above 1 kn. Slower than that there is no TWA and no laylines,
    but the TWD/TWS are kept.
  - SOG stands in for BSP for % polar and the laylines, and the helm shows "VENT GRIB (pas
    d'instruments)".
  - The GRIB comes from `RouterService.grib_wind_at` (bias-corrected `WindField.at`), and is None
    outside the pack grid.
- **Bias.**
  - The `BiasEstimator` gets one sample per tick, with the pack current at the boat, the detector's
    last tack, the zone flag and the toggle. τ comes from the settings.
  - A manual entry becomes one observation. The parameters go into every request, and the bias
    trigger compares the effective values.
  - The helm text reads like "+10° ×1.20" and comes with a state and a reason.
  - `bias.json` is written every 60 s, on a change and at shutdown, and restored at startup.

## Task Commits

1. **Task 1 (tracer): live router + route block + numpy lock.** RED `36b9b84` (test), GREEN `7ad8a42` (feat).
   Tracer feedback gate: the automated verify was re-run end to end on .venv (3.14) and .venv313
   (3.13) after the GREEN commit, and it was green.
2. **Task 2: triggers, hysteresis, On reste, cost, missed tack, persistence, pack alerts.** RED `3d96ab7`, GREEN `756d153`.
3. **Task 3: GPS + GRIB-only wind and the GRIB bias.** RED `06f437c`, GREEN `b483dd3`.

## TDD Gate Compliance

The plan type is `execute`, so no plan-level gate applies. Each task still has a RED commit whose
new tests failed on assertions or missing attributes before its GREEN commit:

- Task 1: KeyError 'route'.
- Task 2: ROUTE INVALIDE / settings / stay assertions.
- Task 3: GRIB source and bias assertions (9 of 11 failing).

## Verification

- **Gate.** `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh` printed
  `check: ok`.
  - ruff check is clean and ruff format --check reports 185 files formatted.
  - Python 3.14: 1148 passed, 1 skipped.
  - Python 3.13: 1148 passed, 1 skipped.
  - The only skip is `tests/route/test_oracle_lwr.py`, because weatherrouting is not installed
    (by policy).
  - The two wheelhouse tests ran rather than skipping, because the wheelhouse was built in this
    worktree.
- **Route tests.** All of them ran on both interpreters, with numpy, pygrib, shapely and netCDF4
  installed in .venv and .venv313: 309 in tests/route + tests/racepack (one of them is the oracle
  skip) and 43 in tests/routing.
- **Acceptance greps.**
  - `^numpy==2.5.4` appears once in the lock and `numpy==2.5.4` once in requirements.in.
  - `jabuka-route-bench` appears once and `jabuka-prep =` once in pyproject.
  - `ROUTE INVALIDE` is in router_service.py, `MÉTÉO INCOMPLÈTE` in racepack.py, `route_level` in
    settings.py, `"GRIB"` in wind.py (via the source docstring and `sol.source = "GRIB"`) and
    `bias.json` in router_service.py.

## Deviations from Plan

### Auto-fixed Issues

1. **[Rule 3 - Blocking] The Phase 2 polar has TWA 0 points.**
   - **Issue:** `route.polar_grid.normalize_curves` rejects them, so the first request raised.
   - **Fix:** `RouterService._polar_curves` keeps only 0 < TWA ≤ 180. The router grid adds its own
     0 knot.
   - **Commit:** `7ad8a42`.
2. **[Rule 1] The nav tracer shape fixture needed the new block.**
   - **Issue:** `tests/fixtures/nav/tracer_nav.json` is shape-checked by
     `tests/nav/test_nav_tracer.py`, so the new route block broke the check.
   - **Fix:** the fixture gains the route block (state no_pack, all keys).
   - **Commits:** `7ad8a42`, plus the `bias.reason` key in `b483dd3`.
3. **[Rule 2] A failed first route was never retried.**
   - **Issue:** 03-04 `Triggers` only fires "first" once, so the first route could stay missing
     after a timeout or crash.
   - **Fix:** a "retry" trigger fires after 60 s when there is no route, no job in flight and the
     last request failed.
   - **Commit:** `7ad8a42`.
4. **[Rule 1] Forced semantics could be lost or misapplied.**
   - **Superseded forced request:** a forced request superseded by a later one now passes its
     forced flag to the next result.
   - **Kind change:** a change of route kind (optimal ↔ stay) is always adopted.
   - **Stale course:** a result computed for an older course version is dropped.
   - **Commit:** `756d153`.
5. **[Rule 1] A restored manual wind entry would have become a fresh bias.**
   - **Issue:** an entry restored from disk at startup was treated as a new observation, so an
     hours-old manual entry would have counted as a fresh bias.
   - **Fix:** the first tick only records the entry.
   - **Commit:** `b483dd3`.
6. **[Rule 2] Safety extras.**
   - `POST /api/route/stay` answers 409 "amure inconnue : On reste impossible" when neither the
     detector nor the TWA gives a tack.
   - The race window must end after its start (422).
   - `bias.json` is also saved at shutdown, so a restart never loses the last minute of learning.
   - **Commits:** `756d153`, `b483dd3`.

### Choices made with the user away (recommended option auto-accepted)

7. **Coverage points.** The plan said "active course marks plus both templates' marks and legs".
   Only the active course is checked, so that selecting Course B adds Mulo and Course A never
   alerts for a mark it does not sail. This is what the plan's own test describes.
8. **Manual wind change source.** The change is detected from the in-process `ManualWindStore`
   (`entry.t_set_wall`) instead of re-reading `wind_manual.json` by mtime. Every write goes through
   that store, so the result is the same.
9. **Route block extra key.** The `bias` block has an additional `reason` key, used for "the state
   shows the reason" after a tack. Everything else follows the interfaces contract.
10. **Off-route.** It is implemented as "current route outdated": `should_replace` receives an age
    above 20 min.
11. **Router tick placement.** The router tick runs inside `CoreContext.update_nav`. Every publish,
    whether from the 1 Hz tick or from a REST change, therefore carries the route block, and a
    course change or "On reste" starts its job immediately.
12. **Bias trigger.** When the bias first appears, even at +0° ×1.00, it fires a bias trigger, per
    03-04 `bias_changed`. `test_timer_fires_at_the_cadence` switches the bias off so that only the
    timer is measured.
13. **Bootstrap fallback.** When the prep extra cannot install, the bootstrap installs pygrib and
    shapely alone so the race-pack tests still run. netCDF4 stays optional.
14. **Test harness.** `tests/routing` disables the 1 Hz loop and drives ticks inside the event loop
    thread (TestClient portal). The latency test uses a real-time clock whose UTC maps into the
    fixture wind. Helpers are reached through the `rh` fixture, because `--import-mode=importlib`
    forbids importing the conftest.

## Known Stubs

None. One limitation is documented: for a route of kind "stay", `eta_utc` is that route's own
(current-leg) ETA, because the forced routing is `leg_only`. The whole-course ETA shows again on
the next optimal route.

## Threat Flags

None beyond the plan's register.
- **T-03-05-01:** strict bodies (422) and pool coalescing.
- **T-03-05-02:** settings bounds and enums (422) plus the version check (409).
- **T-03-05-03:** worker at nice +10 with a 60 s kill, a guarded tick (`router_errors`) and the
  latency test.
- **T-03-05-04:** `load_pack` sha256 checks; failures give a visible `no_pack` reason.
- **T-03-05-05:** ROUTE INVALIDE discard, hysteresis, clock gate and coverage alerts.
- **T-03-05-06:** atomic files and shape validation; a corrupt `route.json` raises the alert
  "Route sauvegardée illisible : ignorée".
- **T-03-05-SC:** pins and hashes, the offline simulation passed, and weatherrouting/latlon3 were
  not added.

## Human items (end of phase, non-blocking)

- **Package review.** Run `git log -p -- deploy/requirements.lock` for this plan and check that only
  numpy 2.5.4 was added, with its hashes. Also check the prep pins: pygrib 2.1.8, shapely 2.2.0,
  netCDF4 1.7.5.1.post1, laptop only. weatherrouting/latlon3 ([SUS], github.com/dakk/libweatherrouting)
  are still uninstalled. Install them only after review, to run the optional oracle test.
- **Pi benchmark gate (2026-11-09, from 03-03).** Put the first passing level into Réglages
  "Niveau de routage (banc Pi)" (`route_level`).
- **Pi memory.** The core now imports numpy and keeps the wind cube for the GRIB-only wind and the
  bias. Check the core RSS on the Pi 3B, alongside the worker's RSS from the benchmark.

## Next Phase Readiness

03-06 can render:
- the `route` block (countdown, cost text, On reste, missed/updating, bias text and state, pack
  alerts, health);
- the WS `route` message (polyline, tack points, next tack);
- `wind.source` "GRIB", using `POST /api/route/stay` and `/api/route/recompute`.

## Self-Check: PASSED
