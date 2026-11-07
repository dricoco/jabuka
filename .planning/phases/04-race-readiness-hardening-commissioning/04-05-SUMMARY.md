---
phase: 04-race-readiness-hardening-commissioning
plan: 05
subsystem: nav-state-persistence, router-supervision
tags: [atomicio, pydantic, state-recovery, router-pool, watchdog, i18n, gap-closure]

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: "04-01 load_json_status (main/bak/missing/unreadable) and the 'illisible' alerts; 03-REVIEW CR-01 pool watchdog (_watch_pool/_recycle_pool); CR-02 failure accounting (_failed, _fail_streak, _withdrawal)"
provides:
  - "load_json_status(path, default, validate=None): a decoded candidate that fails validate falls through to NAME.bak"
  - "CourseStore / SettingsStore / ManualWindStore announce a state restored from NAME.bak ('restauré' alerts), schema-invalid main falls through to a valid .bak"
  - "i18n keys srv.courseFromBak / srv.settingsFromBak / srv.manualFromBak (fr/en/sl + SRV_EXACT)"
  - "RouterService._recycle_pool counts an in-flight cycle lost to a recycle as a failed cycle"
affects: [soak, commissioning, helm-display, diag]

actuals:
  tokens: 7600
  tasks: 3
  commits: 6
plan_head_before: cf03fe84205a1880a3aa7a32fd69e92b36ec0142

tech-stack:
  added: []
  patterns:
    - "State-file parse functions (_parse_course_file, _parse_settings_file, _parse_manual_file) passed as load_json_status(validate=...): validation lives in the parser, the store only switches on source"
    - "Every non-main source is announced: 'bak' -> 'restauré' alert, 'unreadable' -> 'illisible' alert, 'missing' silent (first boot)"

key-files:
  created: []
  modified:
    - src/jabuka/common/atomicio.py
    - src/jabuka/nav/course.py
    - src/jabuka/nav/settings.py
    - src/jabuka/core/router_service.py
    - src/jabuka/web/static/i18n.js
    - docs/I18N-SL-REVIEW.md
    - tests/nav/test_state_corruption.py
    - tests/soak/test_soak_probes.py
    - tests/routing/test_supervisor.py

key-decisions:
  - "load_json_status rejects a candidate on ValueError or TypeError from validate (pydantic ValidationError is a ValueError); validate=None is byte-for-byte the old behaviour, so load_json_with_bak, jabuka-logcheck and route.json/bias.json loading keep their contract"
  - "_recycle_pool counts the lost cycle once per recycle, only when last_request is set and a job is in flight, and passes self._last_fail ('routeur relancé : …') so no new UI string appears"
  - "SL alert wording follows the existing sl terms (boja for mark, varnostna kopija for backup); proofreading stays a human item"

patterns-established:
  - "Store load = load_json_status(path, None, validate=_parse_X_file) then switch on source"

requirements-completed: [REL-02]

coverage:
  - id: D1
    description: "A course restored from course.json.bak (torn or schema-invalid main) is served with the alert 'Parcours restauré depuis la sauvegarde : vérifier la marque active', which reaches /api/nav alerts"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_course_torn_main_restored_from_bak_with_alert"
        status: pass
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_course_schema_invalid_main_falls_through_to_bak"
        status: pass
      - kind: integration
        ref: "tests/nav/test_state_corruption.py#test_core_shows_the_course_restored_alert"
        status: pass
    human_judgment: false
  - id: D2
    description: "settings.json and wind_manual.json follow the same rule ('Réglages restaurés …', 'Vent manuel restauré …'); both invalid keeps the defaults with the 'illisible' alert"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_settings_garbage_main_restored_from_bak_with_alert"
        status: pass
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_manual_schema_invalid_main_falls_through_to_bak"
        status: pass
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_settings_both_invalid_gives_defaults_with_illisible"
        status: pass
    human_judgment: false
  - id: D3
    description: "Happy path unchanged: a valid main file loads the same value and version with no alert; a missing file stays silent; a cleared manual wind stays silent"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_course_valid_main_loads_unchanged_without_alert"
        status: pass
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_settings_valid_main_loads_unchanged_without_alert"
        status: pass
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_manual_valid_main_loads_unchanged_without_alert"
        status: pass
      - kind: unit
        ref: "tests/nav/test_state_corruption.py#test_missing_file_is_still_silent"
        status: pass
    human_judgment: false
  - id: D4
    description: "A routing cycle lost to a recycled (wedged) pool counts as failed: the route turns stale at once, a lost missed-tack reroute is released, two recycles with the route unconfirmed > 10 min withdraw it (outdated)"
    requirement: REL-02
    verification:
      - kind: integration
        ref: "tests/routing/test_supervisor.py#test_wedged_pool_losing_a_shown_routes_cycle_marks_it_stale"
        status: pass
      - kind: integration
        ref: "tests/routing/test_supervisor.py#test_repeated_wedge_withdraws_the_route_after_10_min"
        status: pass
      - kind: integration
        ref: "tests/routing/test_supervisor.py#test_wedged_missed_tack_reroute_is_released"
        status: pass
      - kind: integration
        ref: "tests/routing/test_supervisor.py#test_recycle_with_no_cycle_in_flight_counts_no_failure"
        status: pass
    human_judgment: false
  - id: D5
    description: "Three new Slovenian alert strings"
    verification: []
    human_judgment: true
    rationale: "Slovenian wording needs a native speaker's proofreading (already a phase-4 human item, docs/I18N-SL-REVIEW.md regenerated)"

duration: 30min
completed: 2026-11-07
status: complete
---

# Phase 4 Plan 05: WR-04 / WR-05 gap closure Summary

**State files restored from NAME.bak now raise a "restauré" alert on the helm tablet (course, settings, manual wind) and a schema-invalid main falls through to the good .bak; a routing cycle lost to a recycled wedged pool now counts as a failed cycle, so the route turns stale and a repeated wedge withdraws it after 10 min.**

## Performance

- **Duration:** about 30 min of work, plus the CI soak and a ~20 min full gate
- **Started:** about 2026-11-07T22:00Z
- **Completed:** 2026-11-07
- **Tasks:** 3/3
- **Files modified:** 9

## Accomplishments

- `load_json_status(path, default, validate=None)`. When `validate` raises ValueError or TypeError on a decoded candidate, the next candidate (NAME.bak) is tried. With `validate=None` the behaviour is unchanged.
- `CourseStore`, `SettingsStore` and `ManualWindStore` load through `_parse_course_file`, `_parse_settings_file` and `_parse_manual_file`.
  - Source `bak` adds the exact FR alerts:
    - "Parcours restauré depuis la sauvegarde : vérifier la marque active"
    - "Réglages restaurés depuis la sauvegarde : vérifier les réglages"
    - "Vent manuel restauré depuis la sauvegarde : vérifier le vent"
  - Source `unreadable` keeps the existing "illisible" alerts, and `missing` stays silent.
- i18n: `srv.courseFromBak`, `srv.settingsFromBak` and `srv.manualFromBak` are in the fr, en and sl tables and in SRV_EXACT. `docs/I18N-SL-REVIEW.md` was regenerated.
- `RouterService._recycle_pool`: 4 lines added, 0 removed. When a job is in flight, it adds 1 to `health()["failed"]` and calls `_failed(self.last_request, self._last_fail)` before cancelling the tasks. That drives `block["stale"]`, the retry trigger, `_missed_failed`, and the FAIL_WITHDRAW_N / ROUTE_FAIL_AGE_S withdrawal.

## Task Commits

1. **Task 1 (tracer): course restored from .bak + validate hook**
   - RED `156745c` (test)
   - GREEN `07d13bd` (fix)
   - Tracer gate: auto mode off, human_verify_mode end-of-phase, and `<verify>` is automated-only. `<verify>` was re-run on both venvs (268 passed each), then the plan continued.
2. **Task 2: settings + manual wind restored from .bak**
   - RED `dc23b79` (test)
   - GREEN `7ca05bd` (fix)
3. **Task 3: recycled pool counts the lost cycle as failed**
   - RED `d415de3` (test)
   - GREEN `98c6217` (fix)

## RED-then-GREEN evidence

Each RED record was checked with `gsd-tools check tdd-red-evidence`, and every one gave `RED_EVIDENCE_OK`.

**WR-04 course** (`test_course_torn_main_restored_from_bak_with_alert`)
- RED: `AssertionError: assert [] == ['Parcours restauré depuis la sauvegarde : vérifier la marque active']`. The .bak was adopted silently.
- Before the fix:
  - the schema-invalid case gave template 'A' (the defaults) instead of 'B' from the .bak;
  - the core-level test found only ['PAS DE VENT'] in the alerts;
  - the soak probe `truncate_half` case returned version 1 with no alert.
- GREEN: 268 passed on 3.14 and 3.13 (tests/nav, test_atomicio, test_i18n, soak probes).

**WR-04 settings / manual** (`test_settings_garbage_main_restored_from_bak_with_alert`)
- RED: `assert [] == ['Réglages restaurés depuis la sauvegarde : vérifier les réglages']`.
- The manual-wind cases gave `entry None` (the .bak was never tried for a schema-invalid main).
- GREEN: 291 passed on both venvs (tests/nav, tests/web/test_manual_wind.py, test_i18n, soak probes, test_atomicio).

**WR-05** (`test_repeated_wedge_withdraws_the_route_after_10_min`)
- RED, before the `_recycle_pool` change:
  - the route stayed `{'state': 'ok', ...}` after more than 10 min of wedges;
  - the stale-route test got `stale False`;
  - the missed-tack test got `_missed_failed False`.
- `test_recycle_with_no_cycle_in_flight_counts_no_failure` already passed in RED. It is a guard that protects behaviour which must not change.
- GREEN: test_supervisor 33 passed. `tests/routing` gave 81 passed and 2 skipped on both 3.14 and 3.13.
  - Both skips are the existing env-gated `test_real_pack_e2e.py` ("JABUKA_REAL_PACK not set", laptop dry run). They are unrelated to this plan.

## Whole-repo proof

- **CI soak:** `bash scripts/soak.sh --scenario ci`. Result: **verdict PASS** (exit 0), report var/soak/20261107T222754Z-ci/report.md.
- **Full gate:** `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh`. Result: **`check: ok`** (exit 0).
  - ruff check and format are clean.
  - Python 3.14: 1553 passed, 6 skipped (10 min 39 s). Python 3.13: 1553 passed, 6 skipped (11 min 25 s).
  - The 6 skips are environment-gated tests, such as the JABUKA_REAL_PACK laptop dry run. I did not list them individually because the gate runs pytest with `-q`.

## Files Created/Modified

- `src/jabuka/common/atomicio.py`: the `validate` keyword, plus docstrings stating that "bak" and "unreadable" must both be announced.
- `src/jabuka/nav/course.py`: `_parse_course_file`, the CourseStore source switch with the "restauré" alert, and the unused ValidationError import removed.
- `src/jabuka/nav/settings.py`: `_parse_settings_file` and `_parse_manual_file`, the SettingsStore / ManualWindStore source switch, and the unused ValidationError import removed.
- `src/jabuka/core/router_service.py`: failure accounting in `_recycle_pool` only (+4 lines).
- `src/jabuka/web/static/i18n.js`: three srv keys in each of fr, en and sl, and three SRV_EXACT names.
- `docs/I18N-SL-REVIEW.md`: regenerated with `python -m jabuka.tools.i18n_review`.
- `tests/nav/test_state_corruption.py`: validate-hook, bak-with-alert, schema-invalid fallthrough, both-invalid and happy-path cases for the three stores, plus the core-level /api/nav alert.
- `tests/soak/test_soak_probes.py`: the course branch accepts version 2 with no alert, version 1 with the "restauré" alert, or the default with the "illisible" alert.
- `tests/routing/test_supervisor.py`: four wedged-pool cases (stale, repeated-wedge withdrawal, missed-tack release, no job in flight).

## Decisions Made

- `validate` rejects on `(ValueError, TypeError)`, as the interface contract specifies. The parsers raise ValueError for a non-dict, so a JSON `null` / `[]` main now also falls through to .bak instead of loading silently as an empty state. That is stricter, and still announced.
- The SL wording uses "boja" for mark, the same as the existing sl `srv.nextMark` ("Naslednja boja"), instead of the plan's example "oznako".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Regenerated docs/I18N-SL-REVIEW.md**
- **Found during:** Task 1 (and again in Task 2)
- **Issue:** `tests/test_i18n.py::test_the_slovenian_review_sheet_is_up_to_date` fails whenever an sl key is added, until the review sheet is regenerated. The plan's file list did not include it.
- **Fix:** ran `python -m jabuka.tools.i18n_review`, which only adds the new rows. Its atomic write also left an untracked `docs/I18N-SL-REVIEW.md.bak`, which was deleted and not committed.
- **Files modified:** docs/I18N-SL-REVIEW.md. The 04-04 sibling plan does not own this file.
- **Committed in:** 07d13bd, 7ca05bd

**2. [Rule 3 - Blocking] Removed the now-unused `ValidationError` imports**
- **Found during:** Tasks 1 and 2.
- **Issue:** ruff F401 fired once the except branches moved into the parsers.
- **Fix:** removed the import in course.py and settings.py. Nothing re-exports it (checked with grep).
- **Committed in:** 07d13bd, 7ca05bd

---

**Total deviations:** 2 auto-fixed (both Rule 3, blocking). **Impact:** none on behaviour, and no scope creep.

## Issues Encountered

- The worktree had no venvs. `scripts/bootstrap-dev.sh` built `.venv` and `.venv313` inside the worktree, which is safe in worktrees by design.

## TDD Gate Compliance

All three tasks have a `test(04-05)` RED commit before their `fix(04-05)` GREEN commit. GREEN used `fix` instead of `feat` because these are review findings, i.e. bug fixes. No REFACTOR commits were needed.

## Known Stubs

None.

## User Setup Required

None.

## Next Phase Readiness

- WR-04 and WR-05 are closed in code and tests.
- Human items (not blocking):
  - a Slovenian speaker proofreads the three new sl strings;
  - re-run the laptop race-36h soak on the merged HEAD before the 2026-11-11 freeze (src changed, freeze-check F3).

## Self-Check: PASSED

- All 9 modified files are present.
- `git rev-list --count cf03fe8..HEAD` = 6 before the SUMMARY commit, covering 156745c, 07d13bd, dc23b79, 7ca05bd, d415de3 and 98c6217.
- Acceptance greps:
  - courseFromBak: 4;
  - settingsFromBak|manualFromBak: 8;
  - each FR string appears once in its store file and once in i18n.js;
  - `_failed(self.last_request` matches one line, inside `_recycle_pool`;
  - the router_service.py diff against the base is +4/-0.
- tests/test_atomicio.py, tests/nav/test_course_core.py, tests/nav/test_course_persistence.py, tests/web/test_manual_wind.py and tests/nav/test_heavy_wind.py were not edited, and they pass.

---
*Phase: 04-race-readiness-hardening-commissioning*
*Completed: 2026-11-07*
