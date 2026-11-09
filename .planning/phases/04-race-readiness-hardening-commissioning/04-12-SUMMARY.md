---
phase: 04-race-readiness-hardening-commissioning
plan: 12
subsystem: ui
tags: [helm, lock, night-mode, diag, touch, i18n, playwright, gap-closure]
gap_ids: [G-4-R07, G-4-R09, G-4-R10, G-4-R11]
plan_head_before: b326c525a6c193d7a8b1799537adf32b6bcabd88

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: 04-11 #primary-label.alert / .primary-box.cue colours, 04-09 and 04-10 code (covered by the final gate)
provides:
  - lock_logic createLongPress({holdMs, maxMs}) with up() -> bool, ready(t), void after maxMs
  - lock.js MAX_MS, release-only unlock, .unlock-btn.ready
  - app.js TEXT_FLOOR (110) night text floor and theme propagation into the Diag frame
  - app.css --f-label / #primary-label, #diag-frame var(--bg), helm touch/selection/overscroll rules
  - diag-theme.js (classic, before first paint), diag.css html.theme-night, diag.js storage listener
affects: [04-UAT tests 1, 2, 5, 8, 9, freeze, wheelhouse rebuild, Pi re-provisioning]

actuals:
  tokens: 6200
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Unlock gestures act on release only (a resting pointer never unlocks)"
    - "Night text tiers floored at a fixed red; decoration (--line, map) dims freely"
    - "Early classic external script in <head> for pre-paint theme (CSP script-src 'self')"

key-files:
  created:
    - src/jabuka/web/static/diag-theme.js
    - tests/ui/test_tablet_hardening.py
  modified:
    - src/jabuka/web/static/lock_logic.js
    - src/jabuka/web/static/lock.js
    - src/jabuka/web/static/app.css
    - src/jabuka/web/static/app.js
    - src/jabuka/web/static/i18n.js
    - src/jabuka/web/static/diag.html
    - src/jabuka/web/static/diag.css
    - src/jabuka/web/static/diag.js
    - docs/I18N-SL-REVIEW.md
    - docs/TABLET-SETUP.md
    - docs/COMMISSIONING.md
    - docs/ROUTING.md
    - tests/test_lock_logic.py
    - tests/ui/test_lock_wake.py
    - tests/ui/test_i18n_ui.py
    - tests/ui/test_night.py

key-decisions:
  - "04-12: the padlock unlocks only on lifting the primary pointer after a 2-4 s press (inclusive bounds); a press past 4 s is void, so a resting water drop never unlocks"
  - "04-12: night text tiers (--fg, --good, --bad, --accent, --warn, --dim) are floored at rgb(110, 0, 0); --line and the map dim freely"
  - "04-12: the primary label uses --f-label = --f-word in var(--fg), single-id rule so the 04-11 alert/cue colours keep precedence; the landscape fallback was not needed"
  - "04-12: Diag night variant set before first paint by a classic diag-theme.js; the UA grey table border colour is overridden at night"

patterns-established:
  - "Release-only unlock: tick() draws feedback only, the pointerup handler alone unlocks"

requirements-completed: []

coverage:
  - id: D1
    description: "Only a 2-4 s press released on the padlock unlocks; a never-lifting or too-long press does nothing; ring + .ready show the window (G-4-R07)"
    requirement: HELM-04
    verification:
      - kind: unit
        ref: "tests/test_lock_logic.py#test_a_press_that_never_lifts_never_unlocks"
        status: pass
      - kind: unit
        ref: "tests/test_lock_logic.py#test_release_between_2_and_4_s_unlocks"
        status: pass
      - kind: unit
        ref: "tests/test_lock_logic.py#test_ready_marks_the_release_window"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_lock_wake.py#test_lock_swallows_everything_and_unlocks_on_a_long_press"
        status: pass
    human_judgment: false
  - id: D2
    description: "Night text floored at rgb(110, 0, 0); primary label glanceable and still fitting the column (G-4-R09)"
    requirement: HELM-03
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_night.py#test_night_toggle_is_red_only_and_persists"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_tablet_hardening.py#test_primary_label_is_glanceable"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm_column.py#test_column_layout_fits_in_every_language"
        status: pass
    human_judgment: false
  - id: D3
    description: "Diag red-on-black at night from the first paint, frame never white, follows theme switches (G-4-R10)"
    requirement: HELM-05
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_tablet_hardening.py#test_diag_follows_the_night_theme_without_a_white_flash"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_tablet_hardening.py#test_diag_theme_script_runs_before_the_module"
        status: pass
    human_judgment: false
  - id: D4
    description: "No selection, long-press callout or pull-to-refresh on the helm surfaces; inputs keep selection (G-4-R11)"
    requirement: HELM-04
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_tablet_hardening.py#test_helm_surfaces_refuse_selection_and_pull_to_refresh"
        status: pass
    human_judgment: false
  - id: D5
    description: "Wet-finger unlock on the real tablet, night readability at minimum brightness, SL proofreading of the new lock strings"
    verification: []
    human_judgment: true
    rationale: "Physical tablet behaviour and native-speaker proofreading cannot be automated (04-UAT tests 8 and 9)"

duration: 33min
completed: 2026-11-09
status: complete
---

# Phase 4 Plan 12: Tablet hardening (release-only unlock, night text floor, Diag at night, touch CSS) Summary

**The padlock now unlocks only when the finger lifts after a 2–4 s press, so a resting drop or palm can no longer unlock it. Night text never drops below rgb(110, 0, 0), and the primary label is as large as the tack word. Diag is red-on-black from its first paint. The helm surfaces no longer select text, show the long-press callout or pull-to-refresh. The full gate over all four gap plans is green.**

## Performance

- **Duration:** about 33 min
- **Started:** 2026-11-09T12:04:58Z
- **Completed:** 2026-11-09T12:38:00Z
- **Tasks:** 3 of 3
- **Files modified:** 18 (2 created)

## Accomplishments

- **G-4-R07:** `createLongPress({holdMs: 2000, maxMs: 4000})`. `up()` returns true only when the press lasted between 2000 and 4000 ms, both bounds included. `check()` never unlocks during a hold, and it voids any press longer than maxMs. `ready(t)` marks the release window. In lock.js, `tick()` only draws the ring and toggles `.unlock-btn.ready` (an inverted padlock, meaning "lift now"). The pointerup handler is the only path that unlocks. The hint and aria strings are updated in FR, EN and SL, and the SL review sheet was regenerated. The gesture is updated in TABLET-SETUP §8 and its checklist, the COMMISSIONING 12:00 row and the ROUTING lock line.
- **G-4-R09:** `TEXT_FLOOR = 110` applies to every night text tier. `#primary-label` uses `--f-label` (= `--f-word`) in `var(--fg)`. The 04-11 `#primary-label.alert` and `.primary-box.cue #primary-label` colours still take precedence, and `test_helm_takeovers_on_the_live_page` passes.
- **G-4-R10:** `#diag-frame` now has a `var(--bg)` background. The new classic script `diag-theme.js` runs in `<head>` after diag.css and before the module. diag.css has an `html.theme-night` red-on-black variant covering tokens, links, the input, placeholder, selection, scrollbar and table border colours. app.js propagates the theme into the loaded frame, and diag.js follows the `storage` event.
- **G-4-R11:** `#helm-col, #topbar, .map-ctrls` get `user-select: none`, `-webkit-user-select: none` and `-webkit-touch-callout: none`. `html, body` get `overscroll-behavior-y: none`. The Réglages inputs still allow text selection.

## RED outputs

Task 1 (lock_logic.js at HEAD, time-based latch):
```
FAILED tests/test_lock_logic.py::test_release_between_2_and_4_s_unlocks - Ass...
FAILED tests/test_lock_logic.py::test_release_restarts_from_zero - AssertionE...
FAILED tests/test_lock_logic.py::test_a_press_that_never_lifts_never_unlocks
FAILED tests/test_lock_logic.py::test_release_after_the_window_does_nothing
FAILED tests/test_lock_logic.py::test_ready_marks_the_release_window - Assert...
FAILED tests/test_lock_logic.py::test_up_of_another_pointer_does_not_end_the_press
FAILED tests/test_lock_logic.py::test_reset_after_unlock_locks_again - Assert...
7 failed, 4 passed in 0.54s
```
The 4 tests that passed are the ones kept unchanged: non-primary, second finger, cancel/progress and parse.

Task 2:
```
test_primary_label_is_glanceable: {'size': 16, 'color': 'rgb(85, 85, 85)', 'primary': 'rgb(0, 0, 0)'}
test_diag_follows_the_night_theme...: frame background 'rgb(255, 255, 255)' != 'rgb(0, 0, 0)'
test_diag_theme_script_runs_before_the_module: no diag-theme.js script tag
test_helm_surfaces_refuse_selection_and_pull_to_refresh: #helm-col userSelect 'auto'
test_night_toggle_is_red_only_and_persists: 'rgb(102, 0, 0)' != 'rgb(110, 0, 0)'
5 failed in 19.12s
```

## Computed night colours

| Brightness | #primary | --dim | --line | --map-k |
|---|---|---|---|---|
| 40 % | rgb(110, 0, 0) (was 102) | rgb(110, 0, 0) (was 51) | rgb(26, 0, 0) | 0.4 |
| 100 % | rgb(255, 0, 0) | rgb(128, 0, 0) | rgb(64, 0, 0) | 1 |

COLORS_JS reports `bad == []` at both brightness levels.

## Primary label size (day, measured in Chromium)

| Viewport | font-size |
|---|---|
| 1280x800 | 36.8 px |
| 1024x600 | 27.6 px |
| 800x1280 | 56 px |

**The landscape fallback (`max(18px, min(3.6vh, calc(var(--inner) / 12)))`) was not needed.** `tests/ui/test_helm_column.py` passes at all three sizes in fr, en and sl.

## Diag frame colour check (night, Diag tab)

The frame background is rgb(0, 0, 0), and `html.theme-night` is present in the frame. Every visible element of the frame was checked (465 elements, for color, background, four border colours and outline): **0 bad**. The frame's body background is rgb(0, 0, 0). Switching back to day removes `theme-night` from the frame without a reload. There were no external requests and no bad responses, which confirms diag-theme.js is served.

## Task Commits

1. **Task 1 (tracer): release-only unlock (G-4-R07).** RED `b2d175a`, GREEN `81219d9`. The tracer gate re-ran `<verify>` and it passed before the expansion: logic tests on both venvs, tests/commissioning, and test_lock_wake plus test_i18n_ui under JABUKA_REQUIRE_UI=1.
2. **Task 2: night floor, label, Diag at night, touch CSS (G-4-R09, R10, R11).** RED `680a121`, GREEN `89506ad`.
3. **Task 3: full gate.** Gate only, no edit needed.

## Gate (first over all four gap plans 04-09..04-12)

`var/gate-04-12.log`: `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh`. Green on the first run:
```
1670 passed, 4 skipped in 672.82s (0:11:12)   # Python 3.14
1670 passed, 4 skipped in 674.05s (0:11:14)   # Python 3.13
check: ok
EXIT=0
```
None of the wave-1 SUMMARYs reported a failure owned by another plan, and none showed up here. The soak flake did not occur.

## Final src/jabuka fingerprint (freeze, wheelhouse, Pi)

This is `FINGERPRINT_SH` (`jabuka.soak.report.fingerprint_entries`) over `git archive 89506ad src/jabuka`, this plan's last code commit. The working tree's `package_fingerprint` gives the same value over 147 files (146 + diag-theme.js):

**`c1bab550c801a27f878ac9c34414761e3403e218bc52d1b7913d20b1f00dba30`**

## Decisions Made

- Both ends of the release window are inclusive, so a lift at exactly 2000 or 4000 ms unlocks. `check()` voids a press only when it exceeds maxMs.
- When another pointer lifts while the press continues, the ring stays as it is (`up` returns false and the press goes on). The ring and `.ready` are cleared only when no press is running.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The UA grey table border colour in Diag at night**
- **Found during:** Task 2 (GREEN run of test_diag_follows_the_night_theme_without_a_white_flash)
- **Issue:** Chromium's UA stylesheet gives `table`/`tr` a `border-color: gray` (rgb(128, 128, 128)). The borders are zero-width, but the frame colour check flagged 344 grey values, and the contract's token list did not cover them.
- **Fix:** added `html.theme-night :is(table, thead, tbody, tfoot, tr) { border-color: var(--line); }` to diag.css.
- **Files modified:** src/jabuka/web/static/diag.css
- **Commit:** 89506ad

**Also:** the diag.css `html.theme-night` block sets `background: #000000` on the html element, as well as the tokens and `scrollbar-color` from the contract. This keeps the canvas black even before body styles apply.

---

**Total deviations:** 1 auto-fixed (Rule 1). **Impact:** the fix stays inside diag.css's night variant, and the scope is unchanged.

## Acceptance checks

- Task 1: `maxMs` in lock_logic.js 9; `ready(t)` 2; `MAX_MS` in lock.js 3; `lp.up(` 1; `relâcher` in COMMISSIONING 1 and in ROUTING 1; "then lift / then release" in TABLET-SETUP 2.
- Task 2: `TEXT_FLOOR` in app.js 2; `diag-frame` in app.js 2; `background: #fff` in app.css 0; `-webkit-touch-callout: none` 2; `overscroll-behavior-y: none` 1; `diag-theme.js` in diag.html 1; `html.theme-night` in diag.css 7. `git ls-files` lists diag-theme.js.
- Task 3: the gate log ends with `check: ok` and `EXIT=0`. `git status --porcelain -- cad stl hardware` is empty, and nothing under cad/stl/hardware was touched.

## Issues Encountered

None.

## User Setup Required

None.

## Next Phase Readiness

- All twelve review gaps (G-4-R01..R12) are closed in code. The final HEAD for the freeze carries the fingerprint above.
- Human items:
  - Wet-finger unlock and a drop or palm resting on the padlock, on the real tablet (12 Nov, COMMISSIONING 12:00).
  - Night readability at minimum brightness, and Diag with no white (04-UAT test 8).
  - An SL speaker proofreads "ZAKLENJENO · pridrži 2 s, nato spusti" and "Pridrži 2 s in spusti za odklep" (04-UAT test 9).
  - Rebuild the wheelhouse, re-provision the Pi, and run the laptop race-36h soak and the Pi system-scope soak on this fingerprint, then the freeze.

## Self-Check: PASSED

- All 18 files exist, including the new diag-theme.js and test_tablet_hardening.py.
- All four commits exist: b2d175a, 81219d9, 680a121, 89506ad.
- `var/gate-04-12.log` ends with `check: ok` and `EXIT=0`.

---
*Phase: 04-race-readiness-hardening-commissioning*
*Completed: 2026-11-09*
