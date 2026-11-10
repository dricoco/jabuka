---
phase: quick-261110-klg
plan: 01
subsystem: routing, core router service, i18n, carte
tags: [routing, rounding, course-edit, i18n, carte]
status: complete
requires: []
provides:
  - "rounding.expand: last-mark finish waypoint on its radius circle (approach side, pushed to clear water) for stbd/port or non-clear centres"
  - "router_service: _fail_course_version; course-change withdrawal names the current-version failure"
  - "i18n: srv.rOutCourseWhy, srv.rCannotRound (FR/EN/SL) + SRV_RULES"
  - "carte.js: exported endInsertAt(course) used by 'À la fin'"
affects: [route display after a mid-race course edit, helm withdrawal reason, Carte add-mark sheet]
tech-stack:
  added: []
  patterns: ["failure tagged with the course version it was computed for", "node-import tests of carte.js pure helpers"]
key-files:
  created:
    - tests/test_carte_logic.py
  modified:
    - src/jabuka/route/rounding.py
    - src/jabuka/core/router_service.py
    - src/jabuka/web/static/i18n.js
    - src/jabuka/web/static/carte.js
    - docs/ROUTING.md
    - docs/I18N-SL-REVIEW.md
    - tests/route/test_rounding.py
    - tests/route/test_course_routes.py
    - tests/routing/test_route_expiry.py
    - tests/test_i18n.py
    - tests/ui/test_carte.py
decisions:
  - "Last mark: centre kept when side none and centre clear (Vodice); otherwise circle point facing the previous mark (boat when none), pushed outward; if no clear point on that bearing, fall back to the centre so the router's snap/'cible dans la terre' still applies"
  - "_pool_alarm also records the current course version in _fail_course_version (plan-checker advisory)"
  - "'À la fin' inserts before finish_idx or a start-finish last leg (index >= 1), else appends (seq.length)"
metrics:
  duration: "~70 min (incl. 24 min full gate)"
  completed: 2026-11-10
estimate:
  tokens: 130000
actuals:
  tokens: 6500
  tasks: 3
  commits: 3
plan_head_before: 46a356fdee0c973d501eeb82b1a5a9c2696a5107
---

# Phase quick-261110-klg Plan 01: course-edit fixes (islet finish, withdrawal reason, "À la fin") Summary

A course ending on Blitvenica now routes to a clear point of its 0.55 nm circle facing the previous mark. After a course edit, the helm sees the real failure for the current course version, translated in EN/SL, instead of "recalcul en cours" forever. "À la fin" appends after the last mark unless that mark is a real finish.

## Tasks

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | (tracer) last mark on an islet routes to its circle | 06779b3 | src/jabuka/route/rounding.py, tests/route/test_rounding.py, tests/route/test_course_routes.py, docs/ROUTING.md |
| 2 | withdrawal reason = current-version failure (FR/EN/SL) | dccada6 | src/jabuka/core/router_service.py, tests/routing/test_route_expiry.py, src/jabuka/web/static/i18n.js, tests/test_i18n.py, docs/I18N-SL-REVIEW.md |
| 3 | "À la fin" appends unless the last mark is a real finish | 3b04ef3 | src/jabuka/web/static/carte.js, tests/test_carte_logic.py, tests/ui/test_carte.py |

RED was confirmed before each fix:
- Unit tests got the centre instead of a circle point.
- The real router returned `ok False` with "cible dans la terre, aucune eau libre à 1 nm : Blitvenica".
- The routing reason stayed "recalcul en cours".
- The i18n texts were not translated.
- `endInsertAt` was missing, and the UI's second add posted `insert_at` 4.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The last-mark push replaced "cible dans la terre" for targets deep on land**
- **Found during:** Task 1 (`tests/route/test_isochrone_tracer.py::test_target_inside_an_island_fails_in_french`)
- **Issue:** A radius-0 point mark inside Prvić went through `_push`. `_push` raised "impossible de contourner Prvić …" (0.5 nm search on one bearing) instead of the router's snap, which searches 1 nm in every direction and reports "cible dans la terre".
- **Fix:** When `_push` raises for the last mark, keep the centre (the previous behaviour). The router then snaps it or fails with "cible dans la terre". Added the unit test `test_unplaceable_last_mark_keeps_its_centre`. Updated the module docstring.
- **Commit:** 06779b3

**2. [Advisory] `_pool_alarm` records `_fail_course_version`**
- Following the plan-checker, `_pool_alarm` now also sets `_fail_course_version = self.nav.course.version` (the plan said to leave it unchanged). `_recycle_pool` then overrides it with the cancelled request's version through `_failed`.
- **Commit:** dccada6

## Verification

- `.venv313/bin/pytest -q tests/route tests/routing`: 361 passed, 3 skipped.
- Task 2 verify set (`test_route_expiry`, `test_i18n`, `test_route_logic`, `test_supervisor`): 66 passed. `i18n_review --check`: up to date.
- `tests/test_carte_logic.py`, `tests/ui/test_carte.py` and `tests/ui/test_carte_coords.py`: 17 passed.
- Full gate `bash scripts/check.sh`: `check: ok`. ruff check and format were clean; pytest gave 2029 passed and 4 skipped on .venv, and 2029 passed and 4 skipped on .venv313. The known flaky i18n UI test did not fail.

## Threat Flags

None. The new surface stays inside the plan's threat model:
- `insert_at` values are still validated by `add_mark`.
- Reasons are rendered as text through `trServer`.

## Self-Check: PASSED

All three commits were found: 06779b3, dccada6 and 3b04ef3. `tests/test_carte_logic.py` exists. `docs/I18N-SL-REVIEW.md.bak` is still untracked and unstaged. Nothing changed under cad/, stl/, hardware/ or docs/SOAK.md, nor in nav/course.py or route/isochrone.py.
