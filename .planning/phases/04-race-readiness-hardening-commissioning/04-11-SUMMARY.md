---
phase: 04-race-readiness-hardening-commissioning
plan: 11
subsystem: ui
tags: [helm, route, i18n, playwright, night-mode, gap-closure]
gap_ids: [G-4-R01, G-4-R03, G-4-R08]
plan_head_before: e2e80d418158254ea4040b9dd935e09af4808708

requires:
  - phase: 03-routing
    provides: core route block (countdown_s, wrong_tack, target_tack, tack_kind) and route_logic.js countdownView
  - phase: 02-live-helm
    provides: nav.wind.stale (manual wind max age) and the "stale but still used" contract
provides:
  - route_logic.tackCue(route) -> {word, tack, label, kind} | null
  - helm_logic.noPosition(nav), windStale(nav); primaryView takeover order; helmFlags gps flag; helmView windStale/noGps
  - DOM classes .primary-box.cue, #primary.cue-word, #primary-label.alert, #tab-barre.wind-stale; badge flag-gps
  - app.css --f-cue and the cue / alert / wind-stale rules
  - i18n helm.windStale, flag.noGps, route.cueNow (fr/en/sl)
affects: [04-12, 04-UAT tests 8 and 9, re-provision/re-soak on the final HEAD]

actuals:
  tokens: 10295
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Primary-box takeovers in one priority chain in primaryView (navFailed > PAS DE GPS > VENT PÉRIMÉ > tack cue > route > Phase 2)"
    - "Stale neutralisation lives in helmView; countdownView stays unchanged"

key-files:
  created: []
  modified:
    - src/jabuka/web/static/route_logic.js
    - src/jabuka/web/static/helm_logic.js
    - src/jabuka/web/static/helm.js
    - src/jabuka/web/static/app.css
    - src/jabuka/web/static/i18n.js
    - docs/I18N-SL-REVIEW.md
    - docs/TABLET-SETUP.md
    - docs/ROUTING.md
    - tests/test_route_logic.py
    - tests/test_helm_logic.py
    - tests/nav/test_wind.py
    - tests/ui/test_helm.py
    - tests/ui/test_helm_column.py
    - tests/ui/test_route_ui.py

key-decisions:
  - "noPosition keys on a boat block that carries the lat/lon keys with a non-numeric value (the core always sends them, null when lost); partial messages without lat/lon keys are not no-position"
  - "A frozen VIREZ/EMPANNEZ cue (link lost) loses its inverted red box, consistent with Pitfall 5"
  - "No core change for R01: stale manual wind still drives the numbers; the helm stops presenting it as live"

patterns-established:
  - "Helm takeover = one primaryView branch + one CSS class toggled in helm.js + theme tokens only"

requirements-completed: []

coverage:
  - id: D1
    description: "A due tack or the wrong tack turns the primary box into VIREZ/EMPANNEZ + the tack to go to, inverted, fitting the column in fr/en/sl and red-only at night (G-4-R03)"
    requirement: HELM-02
    verification:
      - kind: unit
        ref: "tests/test_route_logic.py#test_tack_cue"
        status: pass
      - kind: unit
        ref: "tests/test_helm_logic.py#test_primary_box_takeover_when_the_tack_is_due"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm_column.py#test_column_layout_fits_in_every_language"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm_column.py#test_on_reste_in_block_two_padding_per_tab_and_night"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm.py#test_helm_takeovers_on_the_live_page"
        status: pass
    human_judgment: false
  - id: D2
    description: "Stale manual wind reads VENT PÉRIMÉ, blocks 1-2 dimmed, no LOFER/ABATTRE, no alert style and no tack cue in the box or on the countdown line (G-4-R01)"
    requirement: WIND-04
    verification:
      - kind: unit
        ref: "tests/test_helm_logic.py#test_stale_wind_takes_over_the_label_and_neutralises_the_hints"
        status: pass
      - kind: unit
        ref: "tests/nav/test_wind.py#test_stale_manual_wind_is_flagged_not_dropped"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm.py#test_helm_takeovers_on_the_live_page"
        status: pass
    human_judgment: false
  - id: D3
    description: "A lost position shows a red PAS DE GPS badge and primary label (G-4-R08), with the takeover priority pinned"
    requirement: ROUT-06
    verification:
      - kind: unit
        ref: "tests/test_helm_logic.py#test_no_position_badge_and_label"
        status: pass
      - kind: unit
        ref: "tests/test_helm_logic.py#test_takeover_priority"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm.py#test_helm_takeovers_on_the_live_page"
        status: pass
    human_judgment: false
  - id: D4
    description: "Readability of the VIREZ/EMPANNEZ box at arm's length at night on the real 8\"/10\" tablet, and the proofread SL strings (VETER ZASTAREL, NI GPS, ZDAJ)"
    verification: []
    human_judgment: true
    rationale: "Physical tablet readability and native-speaker proofreading cannot be automated (04-UAT tests 8 and 9)"

duration: 46min
completed: 2026-11-09
status: complete
---

# Phase 4 Plan 11: Helm primary-box takeovers (VIREZ/EMPANNEZ, VENT PÉRIMÉ, PAS DE GPS) Summary

**The big helm box now states the one thing to do or distrust. A due tack or the wrong tack shows an inverted VIREZ/EMPANNEZ plus the tack to go to, sized to the column. Hours-old manual wind reads VENT PÉRIMÉ with dimmed numbers and no cue. A lost GPS shows a red PAS DE GPS badge and label. There is no core change.**

## Performance

- **Duration:** about 46 min
- **Started:** 2026-11-09T11:17:56Z
- **Completed:** 2026-11-09T12:03:00Z
- **Tasks:** 3 of 3
- **Files modified:** 14

## Accomplishments

- **G-4-R03:** `tackCue(route)` drives a primary-box takeover. The box shows MAINTENANT or MAUVAIS BORD as the label, VIREZ or EMPANNEZ as the word, and the tack to go to underneath. It is inverted with `var(--bad)`/`var(--bg)`, so it is red on black at night.
- **G-4-R01:** with `nav.wind.stale`, the box reads VENT PÉRIMÉ in the alert colour and `#tab-barre.wind-stale` dims the number, deviation, hint, countdown, layline distance and route band. ON RESTE is excluded. The LOFER/ABATTRE hint, the colours and the alert countdown all go away. A due-tack countdown reads VENT PÉRIMÉ instead of VIREZ.
- **G-4-R08:** a boat block with null lat/lon gives a red PAS DE GPS badge, shown first, and a PAS DE GPS label.
- **Takeover priority** in `primaryView`: ERREUR CALCUL > PAS DE GPS > VENT PÉRIMÉ > tack cue > route primary > Phase 2 primary.
- **Strings:** three new strings in FR, EN and SL. The SL review sheet is regenerated.
- **Docs:** TABLET-SETUP §9 and the ROUTING VIREZ row are updated.

## RED outputs (new logic tests, before the implementation)

Task 1 (route_logic.js at HEAD, without tackCue):
```
FAILED tests/test_route_logic.py::test_tack_cue - AssertionError: <anonymous_...
FAILED tests/test_helm_logic.py::test_primary_box_takeover_when_the_tack_is_due
2 failed, 32 deselected in 0.23s
```
Task 2:
```
FAILED tests/test_helm_logic.py::test_stale_wind_takes_over_the_label_and_neutralises_the_hints
FAILED tests/test_helm_logic.py::test_no_position_badge_and_label - IndexErro...
FAILED tests/test_helm_logic.py::test_takeover_priority - AssertionError: ass...
3 failed, 1 passed, 44 deselected in 0.48s
```
The test that passed is `tests/nav/test_wind.py::test_stale_manual_wind_is_flagged_not_dropped`. It pins the existing core contract, and it is expected to pass because the core is unchanged.

## --f-cue values

- Portrait (base `#tab-barre`): `--f-cue: min(var(--f-primary), 13vw)`.
- Landscape: `--f-cue: min(var(--f-primary), calc(var(--inner) / 6.2))`.
- **The fallback (`/ 7`, `12vw`) was not needed.** LAYOUT_JS reported nothing (`bad == []`) for the cue variant (EMPANNEZ / GYBE / KRIŽAJ) at 1280x800, 1024x600 and 800x1280.

## Playwright takeover readings (tests/ui/test_helm.py, day theme, fr)

| Variant | Label | Primary | Unit | Classes / colours |
|---|---|---|---|---|
| cue (countdown_s -5, stbd) | MAINTENANT | VIREZ | bâbord | box `.cue`, `#primary.cue-word`; #primary rgb(255, 255, 255) on the red box |
| wrong (wrong_tack, port) | MAUVAIS BORD | VIREZ | bâbord | box `.cue`, `#primary.cue-word` |
| stale (MANUEL 3600 s + the due route) | VENT PÉRIMÉ | 42° (route number) | — | `wind-stale`, label `.alert`, no cue; #primary rgb(85, 85, 85), label rgb(192, 0, 0); #helm-countdown "VENT PÉRIMÉ" without `.alert`; no VIREZ/EMPANNEZ in #helm-col |
| nogps (lat/lon null) | PAS DE GPS | — | — | badge "PAS DE GPS"; label `.alert` |

Each takeover disappears with the next live message: no `wind-stale`, no `cue` and no PAS DE GPS badge within 3 s. There were no external requests and no bad responses.

## Task Commits

1. **Task 1 (tracer): VIREZ/EMPANNEZ takeover (G-4-R03).** RED `52523aa`, GREEN `27b2e22`. The tracer gate re-ran `<verify>` (logic tests on both venvs plus test_helm_column under JABUKA_REQUIRE_UI=1) and it passed before the expansion.
2. **Task 2: VENT PÉRIMÉ and PAS DE GPS (G-4-R01, G-4-R08).** RED `2bc54f2`, GREEN `cea0dd2`.
3. **Task 3: docs plus the full gate.** Docs `003943c`. The gate fix is `9d59b38` (see Deviations).

## Gate

`var/gate-04-11.log`: `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh`
```
1663 passed, 4 skipped in 654.39s (0:10:54)   # Python 3.14
1663 passed, 4 skipped in 651.15s (0:10:51)   # Python 3.13
check: ok
EXIT=0
```
The first run (kept as `var/gate-04-11-run1.log`) had one failure, fixed in `9d59b38`.

## New src/jabuka fingerprint

`FINGERPRINT_SH` over `git archive cea0dd2 src/jabuka` (this plan's last code commit; `9d59b38` and `003943c` touch only tests and docs). The working tree's `package_fingerprint` gives the same value (146 files):

**`2afba8c4cd599d3194a53261a72a2c4588c174015387919d2db7a2dc9578160b`**

## Decisions Made

- `noPosition` requires the lat/lon keys to be present (see Deviation 1).
- When the link is lost, a frozen cue loses its red box (Deviation 2).
- The stale rule replaces only the due-tack ("alert") countdown text. A future countdown ("Virement dans 08:30") keeps its text and is dimmed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] noPosition fired on partial boat blocks without lat/lon keys**
- **Found during:** Task 2
- **Issue:** with the plan's literal predicate (boat object without numeric lat/lon), the existing `tests/test_i18n.py::test_helm_in_english_and_slovenian` and `test_route_band_in_english_and_slovenian` fixture `boat: {bsp_kn: 6.84}` read PAS DE GPS. The plan requires every existing test to pass unchanged.
- **Fix:** no position only when the boat block carries `lat` or `lon` (nav_service always sends both, null when unknown) and they are not both numeric.
- **Files modified:** src/jabuka/web/static/helm_logic.js
- **Verification:** test_i18n, test_helm_logic and the Playwright nogps variant all pass.
- **Committed in:** cea0dd2

**2. [Rule 2 - Missing critical] A frozen cue box stayed red when the link was lost**
- **Found during:** Task 1
- **Issue:** the link-lost rule dims colours only, so an inverted VIREZ box would stay red and look live (Pitfall 5).
- **Fix:** `#tab-barre.stale .primary-box.cue { background: transparent; }`.
- **Files modified:** src/jabuka/web/static/app.css
- **Committed in:** 27b2e22

**3. [Rule 3 - Blocking] tests/ui/test_route_ui.py expected "ROUTE" in the live primary label**
- **Found during:** Task 3 (full gate, run 1)
- **Issue:** the feeder boat sails a fixed TWA 45 on the other tack than the adopted route. The live helm now correctly reads MAUVAIS BORD / VIREZ bâbord (G-4-R03), and the test's wait for "ROUTE" timed out (probe: `['MAUVAIS BORD', 'VIREZ', True]`).
- **Fix:** the test waits for the route label or the cue label, then checks the cue word and the inverted box. The test file was not in the plan's file list.
- **Files modified:** tests/ui/test_route_ui.py
- **Verification:** test_route_ui.py passes (3 passed), and the full gate is green.
- **Committed in:** 9d59b38

**4. [Rule 1 - Robustness] LONG_NAV_JS forces `wrong_tack: false` for the hdg/twa variants**
- **Found during:** Task 1
- **Issue:** the live route of the routed fixture is on the wrong tack (see 3). Without the override, the long-value variants would render the cue instead of "358°"/"178°".
- **Fix:** `wrong_tack: false` was added to the common forced fields. No assertion changed.
- **Files modified:** tests/ui/test_helm_column.py
- **Committed in:** 52523aa

**Also:** `windStale` is written as `export function` rather than an arrow const, so that the acceptance grep (`export function windStale\|export function noPosition` = 2) holds.

---

**Total deviations:** 4 auto-fixed (2 bugs/robustness, 1 missing critical, 1 blocking).
**Impact on plan:** all four keep existing contracts or tests intact. There is no core change, and the scope is unchanged.

## Acceptance checks

- Task 1: tackCue export 1; tackCue in helm_logic 2; route.cueNow 3; --f-cue 3; `i18n_review --check` reports "à jour".
- Task 2: windStale/noPosition exports 2; flag.noGps 3; helm.windStale 3; wind-stale in app.css 4; "gps" in helm.js 1. The core/nav files changed by 04-11 commits number 0.
- Task 3: PAS DE GPS in TABLET-SETUP 2; VENT PÉRIMÉ in TABLET-SETUP 2; EMPANNEZ in ROUTING 1. tests/commissioning: 77 passed, 1 skipped (the full rehearsal needs JABUKA_REHEARSAL_FULL=1, pre-existing).

## Issues Encountered

- zsh noclobber blocked the second gate redirect onto the existing log. The first log was moved to `var/gate-04-11-run1.log` and the gate was re-run.

## User Setup Required

None.

## Next Phase Readiness

- 04-12 (wave 2: lock, diag night, brightness floor, primary label size, touch CSS) can build on these classes and strings.
- Human items: an SL speaker proofreads VETER ZASTAREL / NI GPS / ZDAJ (04-UAT test 9). Someone checks VIREZ/EMPANNEZ readability at night on the real tablet (04-UAT test 8). Rebuild, re-provision and re-soak on the final HEAD after 04-12 (the fingerprint above changes again).

## Self-Check: PASSED

- All 14 modified files exist.
- All six commits exist: 52523aa, 27b2e22, 2bc54f2, cea0dd2, 003943c, 9d59b38.
- `var/gate-04-11.log` ends with `check: ok` / `EXIT=0`.

---
*Phase: 04-race-readiness-hardening-commissioning*
*Completed: 2026-11-09*
