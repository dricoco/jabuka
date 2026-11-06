---
phase: 02-helm-mvp-laylines-marks-map
plan: 03
subsystem: nav-engine, api, ui
tags: [true-wind, damping, manual-wind, jabuka-zone, laylines, current, sailed-angles, efficiency]

requires:
  - phase: 02-helm-mvp-laylines-marks-map
    provides: "02-01 nav package, NavService, nav message v1, settings fields, /api/settings, Réglages schema form, tests/ui harness"
provides:
  - "WindPipeline: TRUE boundary, LIVE > LIVE_BG > MANUEL > NONE, VectorEma/ScalarEma damping (twd vs twd_lay), cross-check, leeway, Jabuka zone"
  - "ManualWindStore (wind_manual.json) + POST/DELETE/GET /api/wind/manual + wind_manual event lines"
  - "TackTracker (nav/tacks.py): tack/gybe detection, settled sailed angles per side"
  - "laylines.solve: per-side polar/sailed vectors, current opt-in (never in sailed sides or in the zone), actual-track countdown, overstood time, current-corrected CTS (fetching + reach)"
  - "polar.efficiency_for / polar.apply_efficiency (speeds only, up/down factors)"
  - "Diag/derived rows nav.heading.true/src, nav.wind.dtwa/dtws/inZone/twdLay, nav.tacks.stbd/port"
  - "Réglages 'Vent manuel' panel (°M default)"
affects: [02-04, 02-05, phase-3-routing]

actuals:
  tokens: 26000      # chars/4 over the realized diff (git diff 5c3e0ea..HEAD + new tacks.py), code + tests
  tasks: 3
  commits: 5         # MEASURED: git rev-list --count 5c3e0ea..HEAD before this SUMMARY commit
plan_head_before: 5c3e0ea818552d3aedfe616ee9747cef6bca2557

tech-stack:
  added: []
  patterns:
    - "One TRUE boundary (heading_true) for heading, Hercules direction and current set"
    - "Time-based EMAs on the injected monotonic clock; same instant twice = no-op, clock back = reset"
    - "Filters reset on source change or a new manual entry so a typed value applies at once"
    - "Sailed angles are ground-referenced: the current is never added to them (Pitfall 8)"

key-files:
  created:
    - src/jabuka/nav/tacks.py
    - tests/nav/test_wind.py
    - tests/nav/test_laylines.py
    - tests/nav/test_tacks.py
    - tests/nav/test_efficiency.py
    - tests/web/test_manual_wind.py
    - tests/ui/test_reglages.py
  modified:
    - src/jabuka/nav/wind.py
    - src/jabuka/nav/settings.py
    - src/jabuka/nav/laylines.py
    - src/jabuka/nav/polar.py
    - src/jabuka/core/nav_service.py
    - src/jabuka/core/nav_api.py
    - src/jabuka/web/static/reglages.js
    - src/jabuka/web/static/reglages.css
    - tests/fixtures/nav/tracer_nav.json

key-decisions:
  - "Manual °M entry converted to TRUE once at entry with the variation in force then; twd_entered/ref_entered kept for the form and the log"
  - "Hercules direction and current set go through heading_true (offset + variation for ref M or unknown), same as the heading: they are derived from the same compass"
  - "Without a compass (or in the zone, slow), MANUEL/LIVE_BG still get a TWA from COG when SOG > 1 kn; computed wind outside the zone still requires the compass"
  - "Efficiency split by point of sail at |TWA| 70/110 (same as the helm primary): up factor below 70, down factor above 110, general factor in between (% polar and reach target speed)"
  - "Sailed side other_tack_hdg_t reports the measured ground track (the sailed heading is not recorded); layline.current is true when the current was added to at least one polar side"
  - "Countdown along the actual track also needs the ray to meet the other-tack layline ahead; otherwise (or SOG <= 1 kn, no COG) it falls back to the polar a; dist_nm follows the same choice"
  - "Tack samples: run minus its first 30 s, settled at >= 120 s, a settled run keeps refreshing its own sample; reaching (70 < |TWA| < 110) ends the run"

requirements-completed: [WIND-01, WIND-02, WIND-03, WIND-04, WIND-07, NAV-01, NAV-02, NAV-03, CRSE-05]

coverage:
  - id: D1
    description: "Silent bus: manual TWD/TWS (°M/°T) keeps laylines with source MANUEL; LIVE wins when fresh; back to MANUEL after 5 s stale; aged entry stale + alert; persisted across restart; 422 on bad input; event lines"
    requirement: WIND-04
    verification:
      - kind: integration
        ref: "tests/web/test_manual_wind.py"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_reglages.py#test_manual_wind_form_and_settings"
        status: pass
    human_judgment: false
  - id: D2
    description: "TRUE boundary (M, T, ?), vector damping without wrap glitch, step response, TWS scalar EMA, filter reset on source change"
    requirement: WIND-03
    verification:
      - kind: unit
        ref: "tests/nav/test_wind.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Instrument fallback (LIVE_BG) and computed/B&G cross-check with alert after 60 s above 10 deg, rows on Diag"
    requirement: WIND-03
    verification:
      - kind: unit
        ref: "tests/nav/test_wind.py#test_cross_check_alert_after_60_s"
        status: pass
      - kind: integration
        ref: "tests/nav/test_wind.py#test_cross_check_rows_reach_diag"
        status: pass
    human_judgment: true
    rationale: "Which source is right on the boat (computed vs Hercules) is decided from a capture on 12 Nov (Addendum)"
  - id: D4
    description: "Jabuka zone: COG heading, Hercules direction and set ignored, alert, no tack learning"
    requirement: WIND-07
    verification:
      - kind: unit
        ref: "tests/nav/test_wind.py#test_jabuka_zone_uses_cog"
        status: pass
      - kind: integration
        ref: "tests/nav/test_laylines.py#test_nav_service_current_ignored_in_the_zone"
        status: pass
    human_judgment: false
  - id: D5
    description: "Laylines: prototype a/b with and without current, sailed mode without current, per-side polar fallback, leg hysteresis on twd_lay, actual-track countdown, overstood time, fetching/reach current-corrected CTS"
    requirement: NAV-01
    verification:
      - kind: unit
        ref: "tests/nav/test_laylines.py"
        status: pass
      - kind: unit
        ref: "tests/nav/test_laylines_core.py"
        status: pass
    human_judgment: true
    rationale: "Polar vs real tacking angles (A5) checked against the B&G on 12 Nov"
  - id: D6
    description: "TackTracker medians, 30 s flip hold, 120 s settle, zone freeze"
    requirement: NAV-02
    verification:
      - kind: unit
        ref: "tests/nav/test_tacks.py"
        status: pass
    human_judgment: false
  - id: D7
    description: "Efficiency on speeds only, up/down/general factors"
    requirement: WIND-02
    verification:
      - kind: unit
        ref: "tests/nav/test_efficiency.py"
        status: pass
    human_judgment: false

duration: 75min
completed: 2026-11-06
status: complete
---

# Phase 2 Plan 03: Wind pipeline + laylines complete Summary

**The helm now gets TRUE, damped, cross-checked wind from computed, B&G or manually typed values, and stops trusting the compass near Jabuka. The laylines run on polar or actually sailed angles, add the Hercules current only when asked (never twice), and count down along the boat's real track, with overstood time and a current-corrected course to steer when fetching.**

## Performance

- **Duration:** about 75 min of active work. Wall clock 03:15Z to 09:25Z includes an idle stall after the gate run, before the final commit.
- **Started:** 2026-11-06T03:15Z
- **Tasks:** 3 (tracer + 2 TDD)
- **Files modified:** 16 (9 source/fixture, 7 new test files)

## Accomplishments
- **Manual wind (WIND-04).** `ManualWindStore` writes `wind_manual.json` atomically and restores it after a restart; the age continues from `t_set_wall`.
  - REST: `POST /api/wind/manual {twd, tws_kn, ref}` validates its input with pydantic and returns 422 on bad values. `DELETE` clears the entry, and `GET` returns the stored one.
  - Every change writes an fsync'd `wind_manual` event line and pushes a fresh nav message to every tablet.
  - The Réglages tab has a "Vent manuel" panel: TWD, TWS, a °M/°T selector (default °M), Appliquer and Effacer buttons, and the live source and manual age.
- **Wind pipeline (WIND-03/07).** Everything goes TRUE at one boundary, including the Hercules direction and the current set.
  - Sources: computed LIVE with leeway, then the Hercules LIVE_BG, then MANUEL (marked stale past `manual_wind_max_age_min`), then NONE. `true_wind_source` chooses between computed and instrument.
  - Damping: `VectorEma` with τ helm 10 s / τ layline 60 s, and a scalar EMA for TWS. The filters reset on a source change or a new manual entry.
  - Cross-check: dTWA and dTWS are computed, with an alert after 60 s above 10°.
  - Jabuka zone: the heading comes from COG, the instrument direction and set are ignored, and "CAP NON FIABLE (zone Jabuka)" shows.
- **Laylines (NAV-01/02/03).**
  - Each side uses polar or sailed vectors, with a per-side polar fallback. `src` is "sailed" only when both sides are sailed.
  - The current is added only when `use_current` is on, never inside the zone and never to sailed sides.
  - The countdown follows the boat's actual track: it intersects the COG ray with the other-tack layline.
  - Also covered: overstood time, current-corrected CTS when fetching and on reaches, and leg-type hysteresis on `twd_lay`.
- **TackTracker:** a tack or gybe is a sign flip of the damped TWA held 30 s. Each run settled for 120 s or more records θ = COG − TWD and the mean SOG. The tracker keeps the last 3 per side and point of sail, uses the median, and learns nothing inside the zone.
- **Efficiency:** `apply_efficiency` and `efficiency_for` scale speeds only. Separate upwind and downwind factors are supported, with the general factor on a reach.
- **Diag/derived log:** new rows `nav.heading.true`, `nav.heading.src`, `nav.wind.dtwa`, `nav.wind.dtws`, `nav.wind.inZone`, `nav.wind.twdLay`, `nav.tacks.stbd` and `nav.tacks.port`.

## Task Commits

1. **Task 1 (tracer): manual wind keeps the laylines alive** - `76d3e38` (feat)
2. **Task 2: TRUE, damped, cross-checked wind + Jabuka zone** - RED `d0588d6` (test), GREEN `0a354d0` (feat)
3. **Task 3: laylines that match the water** - RED `dae131d` (test), GREEN `c84ece9` (feat)

Tracer feedback gate: the Task 1 `<verify>` command (`tests/web/test_manual_wind.py tests/ui/test_reglages.py tests/nav`, with JABUKA_REQUIRE_UI=1) was re-run on the committed tree and passed (91 tests) before Tasks 2 and 3 started.

## TDD Gate Compliance
- Task 2: RED `d0588d6` failed at collection (ImportError: VectorEma missing), then GREEN `0a354d0`.
- Task 3: RED `dae131d` failed at collection (`jabuka.nav.tacks`, `apply_efficiency` and `efficiency_for` missing), then GREEN.
- No REFACTOR commits were needed.

## Test results
- `JABUKA_REQUIRE_UI=1 bash scripts/check.sh`: ruff lint and format are clean. **639 passed, 2 skipped on Python 3.14 and on 3.13** (exit 0).
- The 2 skips are environment-only and come from earlier phases: `tests/deploy/test_lock.py:100` and `:151` need the gitignored `deploy/wheelhouse`, which is absent in a fresh worktree. All 7 UI tests (headless Chromium) ran with no skip.
- New tests in this plan (68): test_wind 21, test_laylines 16, test_tacks 9, test_efficiency 9, test_manual_wind 12, test_reglages 1. The 02-01 tests (`test_laylines_core`, `test_nav_tracer`, `test_helm_logic`) still pass.

## Decisions Made
See `key-decisions` in the frontmatter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The tracer shape fixture pinned `wind.check: null`**
- **Found during:** Task 2
- **Issue:** the 02-01 tracer feeds both computed and Hercules values, so the cross-check now fills `wind.check` with the contract dict `{dtwa, dtws_kn, alert}`. `tests/nav/test_nav_tracer.py` compares the message shape against `tests/fixtures/nav/tracer_nav.json`, which still had `check: null`.
- **Fix:** in the fixture, `wind.check` became `{"dtwa": 0.0, "dtws_kn": 0.0, "alert": false}`. No other change to the fixture; `helm_logic.js` does not read `check`. This file was not in the plan's `files_modified`. A 02-05 edit to the same fixture may need a trivial merge.
- **Commit:** 0a354d0

**2. [Rule 1 - Bug] A changed manual entry was damped in instead of applied**
- **Found during:** Task 2
- **Issue:** two manual entries in a row kept the source MANUEL, so the helm filter moved towards the new value over τ instead of applying it at once.
- **Fix:** the filter-reset key now includes the manual entry. A test in `tests/web/test_manual_wind.py` covers it.
- **Commit:** 0a354d0

**3. [Rule 1 - Bug] An API push between ticks could reset the filters**
- **Issue:** RESEARCH's VectorEma resets when `t <= last t`. A nav push from `POST /api/wind/manual` or `PUT /api/settings` runs at the same `t_mono` as the tick, so it would throw the damping away.
- **Fix:** the filters and TackTracker reset only when `t < last t`; the same instant twice is a no-op. Tested in `test_vector_ema_clock_backwards_resets`.
- **Commit:** 0a354d0

**4. [Rule 1 - Bug] Native form validation blocked the French error**
- **Issue:** with `max=359.9`, the browser refused to submit out-of-range values and showed its own bubble, so the inline French error never appeared.
- **Fix:** the form has `novalidate`, and `manualBody()` checks the values and shows the French message.
- **Commit:** 76d3e38

**5. [Test design] The overstood case was built from the decomposition**
- **Issue:** the RESEARCH "6 nm west" case has β = 50.19°, just outside the +5° beat hysteresis, so its leg is a reach (same finding as 02-01 deviation 2).
- **Fix:** the test places the boat at D = −0.118·g_stbd + 2·g_port (β ≈ 48.4°, a beat) and asserts overstood_s = 425 ± 2.

**6. [Test design] Tack runs of 130 s**
- **Issue:** at 1 Hz, a run of exactly 120 samples spans 119 s, so it never reaches the 120 s settle threshold.
- **Fix:** the synthetic runs last 130 s. The medians are the ones the plan specifies: −50 and 49.

**Total deviations:** 6 (1 Rule 3, 3 Rule 1, 2 test-design notes). **Impact:** no contract field was renamed. 02-04 (`CourseStore.on_tick`/`status` calls unchanged) and 02-05 (it renders wind/layline fields that keep the 02-01 names and units) are unaffected.

## Known Stubs
None for this plan's scope. Every 02-01 stub this plan owned is now live: `true_wind_source`, `layline_source`, `use_current`, `leeway_deg`, `tau_*`, `zone_*` and `manual_wind_max_age_min`.

## Threat Flags
None beyond the plan's threat model. `GET /api/wind/manual` is a new read-only route: it returns the stored entry, with no secrets.

## User Setup Required
None. End-of-phase human items, all non-blocking:
1. **12 Nov, motoring in calm water:** compare Diag `nav.heading.true` with GPS COG and the B&G heading. Once sailing, read `nav.wind.dtwa`/`dtws` and decide `true_wind_source` (computed or instrument).
2. **12 Nov:** compare the tablet laylines with the B&G "heading on next tack" and the real tacking angles. If the polar angles are too tight (A5), switch "Angles des lay-lines" to `sailed` after two tacks each way.
3. **Manual wind drill (Phase 4 runbook):** with the bus unplugged, type the B&G TWD (°M) and TWS on Réglages. The badge should show MANUEL and the laylines should come back.

## Next Phase Readiness
Phase 3 can use:
- `WindSolution.in_zone` to freeze the bias estimator.
- `TackTracker` for tack detection on the damped TWA sign (ROUT-09).
- `laylines.solve` as the countdown fallback when there is no route.

The heading convention stays hdg = TWD − TWA, with TWA negative to port.

## Self-Check: PASSED
- Files present: src/jabuka/nav/tacks.py and the 6 new test files (all collected and passing in the gate run).
- Commits present: 76d3e38, d0588d6, 0a354d0, dae131d, c84ece9.
