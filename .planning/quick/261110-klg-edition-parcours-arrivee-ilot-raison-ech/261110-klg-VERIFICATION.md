---
phase: quick-261110-klg
verified: 2026-11-10T00:00:00Z
status: passed
score: 7/7 must-haves verified
covered_files:
  - ".planning/quick/261110-klg-edition-parcours-arrivee-ilot-raison-ech/261110-klg-PLAN.md"
  - ".planning/quick/261110-klg-edition-parcours-arrivee-ilot-raison-ech/261110-klg-SUMMARY.md"
  - "docs/I18N-SL-REVIEW.md"
  - "docs/ROUTING.md"
  - "src/jabuka/core/router_service.py"
  - "src/jabuka/route/rounding.py"
  - "src/jabuka/web/static/carte.js"
  - "src/jabuka/web/static/i18n.js"
  - "tests/route/test_course_routes.py"
  - "tests/route/test_rounding.py"
  - "tests/routing/test_route_expiry.py"
  - "tests/test_carte_logic.py"
  - "tests/test_i18n.py"
  - "tests/ui/test_carte.py"
covered_digest: "v1:sha256:ac22918f2794b9084bc87694f20960154d24765d78bb86fdc08ad1e2f0aa4f51"
behavior_unverified: 0
overrides_applied: 0
---

# Quick 261110-klg: course-edit fixes (islet finish, withdrawal reason, "À la fin") Verification Report

**Goal:** after a mid-race course edit the helm gets a route again (last mark on an islet) and sees why when it cannot; "À la fin" appends unless the last mark is a real finish.
**Verified:** 2026-11-10
**Status:** passed
**Re-verification:** No (initial verification)

Commits checked on main: 06779b3, dccada6, 3b04ef3 (base 46a356f). The diff touches 12 files. `src/jabuka/nav/course.py`, `src/jabuka/route/isochrone.py` and `docs/I18N-SL-REVIEW.md.bak` are not in the diff.

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A last mark on an islet (Blitvenica, side stbd or none) routes ok to a clear point on its radius circle on the approach side (bearing to the previous mark, or to the boat when there is none), pushed outward. "cible dans la terre … Blitvenica" no longer occurs. | VERIFIED | `rounding.expand` has a new branch for `i == n-1 and (side in port/stbd or not _clear(centre))`. It uses `_bearing(mark, prev_pos)`, falls back to the boat, then calls `_push`. Passing tests: `test_last_islet_mark_targets_its_circle_on_the_approach_side[stbd-0.55, none-0.55, none-0.0]` (point is clear, within r..r+0.5 nm, within 1.5° of the bearing to Plić) and `test_single_last_mark_faces_the_previous_mark_else_the_boat`. The real router passes `test_course_ending_on_an_islet_routes_to_its_circle[plic-blit-stbd, plic-blit-none, a-without-finish]`: `r.ok`, legs match, the path is valid against the mask, the path ends within 0.05 nm of the finish point, and the reason and notes contain no "cible dans la terre". |
| 2 | A last mark with side stbd/port targets its circle even when its centre is clear. A side-none last mark with a clear centre (Vodice) keeps the exact centre, so Course A/B are unchanged. A mark that cannot be placed falls back to the centre. | VERIFIED | Side stbd/port triggers the branch regardless of whether the centre is clear. Passing tests: `test_last_buoy_with_a_side_targets_its_circle` (distance exactly 0.1 nm, bearing to Plić) and `test_vodice_finish_keeps_its_centre_with_the_mask` (lat/lon equal the centre, no note). When `_push` raises ValueError, the branch keeps the centre and the router snaps it; `test_unplaceable_last_mark_keeps_its_centre` passes. All 8 `test_course_scenario[A/B-*]` cases and the stability/ETA tests pass. |
| 3 | Intermediate marks, rounding waypoints and the rounding FSM in course.py are unchanged. | VERIFIED | `git diff --name-only` shows no change to `nav/course.py` or `isochrone.py`. The new branch only runs when `i == n-1` (the last mark), and the `_arc` path is untouched. All pre-existing `test_rounding` and `test_course_routes` cases pass. |
| 4 | After a course edit the reason is "parcours modifié : recalcul en cours" until a cycle for the current course version has failed. After that it is "parcours modifié : <that failure>". | VERIFIED | `_withdrawal` returns `f"parcours modifié : {self._last_fail}"` only when `_fail_course_version == self.nav.course.version`. `_on_outcome` passes `course_version` to `_failed`/`_invalid` on every failure path. `_recycle_pool` uses `_last_req_course_version`. `_pool_alarm` stamps the current version (a documented deviation). `test_course_change_reason_while_computing_then_failed` passes: an older-version timeout is ignored and the reason reads "recalcul en cours" while held; after the current-version crash it reads "parcours modifié : crashed: BrokenProcessPool". `test_course_change_withdraws_the_route` was updated and passes. |
| 5 | EN and SL translate the prefix, the inner reason and "impossible de contourner …"; FR is untouched; the SL review sheet is in sync. | VERIFIED | `i18n.js` adds `srv.rOutCourseWhy` and `srv.rCannotRound` in FR, EN and SL. It also adds SRV_RULES `/^parcours modifié : (.+)$/s` (the `*r` group is translated recursively) and the rCannotRound regex. `test_every_core_text_is_translated_in_en_and_sl_and_untouched_in_fr` asserts the exact EN string "course changed: target on land, no open water within 1 nm: Blitvenica" and the exact SL string "proga spremenjena: cilj na kopnem, ni proste vode v 1 nm: Blitvenica". The rounding string is in COMPOSITES. Placeholder parity test passes. `python -m jabuka.tools.i18n_review --check` reports "à jour". |
| 6 | "À la fin" inserts before the last mark only when it is a real finish (finish_idx set, or a start-finish last leg at index >= 1); otherwise it appends at seq.length. | VERIFIED | `carte.js` exports `endInsertAt(course)`, which implements exactly that rule, and `openAddSheet` uses `endInsertAt(course)` for `st.pos === "end"`. `lastIdx` is unchanged. Five node tests in `tests/test_carte_logic.py` pass. The Playwright test `test_add_at_end_*` passes on its own ephemeral port: the first add posts insert_at 4 (before Vodice); after the finish is deleted, the second add posts insert_at 5 (appended). |
| 7 | `bash scripts/check.sh` is green. | VERIFIED (per orchestrator instruction, not re-run) | The executor reports `check: ok`, with 2029 passed on both .venv and .venv313. The targeted re-runs here are all green (see below). No debt markers were added in the diff. |

**Score:** 7/7 truths verified (0 present but behavior-unverified)

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| isochrone.py | rounding.expand | `expand(req.prev_mark, req.marks, …, ctx.env.mask, …)` at isochrone.py:575 | WIRED (exercised by the real-router islet tests) |
| router_service `_on_outcome` / `_recycle_pool` / `_pool_alarm` | `_withdrawal` | `_fail_course_version` compared with `nav.course.version` | WIRED |
| i18n.js SRV_RULES | router_service reason | `/^parcours modifié : (.+)$/s` → `rOutCourseWhy` (`*r`) | WIRED (node test of trServer) |
| carte.js openAddSheet | POST /api/marks → add_mark | `insert_at = endInsertAt(course)` | WIRED (Playwright checks the posted body) |

## Behavioral Spot-Checks (run by verifier)

| Command | Result |
|---------|--------|
| `.venv313/bin/pytest -v tests/route/test_rounding.py tests/route/test_course_routes.py tests/routing/test_route_expiry.py tests/test_carte_logic.py tests/test_i18n.py` | 57 passed |
| same set + `tests/route/test_isochrone_tracer.py` (`-q`) | 73 passed |
| `.venv313/bin/pytest -q tests/ui/test_carte.py -k add_at_end` | 1 passed (test server on an ephemeral port, not 8080) |
| `.venv313/bin/python -m jabuka.tools.i18n_review --check` | up to date, rc 0 |

## Anti-Patterns

There are no TODO/FIXME/XXX/HACK markers in added lines. Nothing in the diff is a stub.

Info: when the last mark is also the first remaining mark and has no previous mark, the finish point faces the boat, so it moves as the boat moves. The plan intends this.

## Human Verification Required

None needed to pass this task. The demo on port 8080 and the Pi were not touched. An optional on-device check is to repeat the reported edit on the demo (delete the Vodice finish, then "À la fin" M2) and confirm that a route appears to Blitvenica.

## Gaps Summary

None.

---
_Verifier: Claude (gsd-verifier)_
