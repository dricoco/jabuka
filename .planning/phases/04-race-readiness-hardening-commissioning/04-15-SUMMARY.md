---
phase: 04-race-readiness-hardening-commissioning
plan: 15
subsystem: nav
tags: [rounding, course, state-machine, annuler, course-edit, gap-closure, freeze]
gap_ids: [CR-01, WR-01, IN-01]
gap_dispositions:
  CR-01: fixed (CourseStore._carry_suppress in _commit; an edit that keeps the active leg keeps the Annuler suppression)
  WR-01: accepted residual R10, pinned (test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances), no code change
  IN-01: fixed (comment-only; module, _fsm_outgoing and CR-02 stand-in documentation)
plan_head_before: 2ebbd259b4daad12aea3e7c71a5ea69a98812bc9
commits: 4

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: 04-14 _fsm_geometry/_fsm_outgoing key split, CR-02 suppressed-zone stand-in (_near at normal marks, _beyond at hairpins)
provides:
  - CourseStore._carry_suppress(new) -> Course (carries suppress_idx through an edit that keeps the active leg)
  - _commit calls it after the version check, before the atomic write (course.json persists the carried suppression)
  - corrected keep/drop/clear documentation in course.py (R10 named)
affects: [freeze 2026-11-11, wheelhouse rebuild, Pi re-provisioning, 04 re-verification, course card]

actuals:
  tokens: 2700
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Central carry of per-leg state in the single commit path, guarded by same-index + same-mark + not-finish + no-banner + not-finished"
    - "AST equality check (docstrings stripped, one named method and one call removed) as proof that a pre-freeze edit is minimal"

key-files:
  created: []
  modified:
    - src/jabuka/nav/course.py
    - tests/nav/test_course.py

key-decisions:
  - "04-15 CR-01: _carry_suppress in _commit keeps the Annuler suppression through an edit that keeps the active leg (same index and mark id, not the finish leg, no banner, not finished, old suppress_idx == old active_idx); « Suiv. »/« Préc. », activate of another leg, index shift (R6), select() to another mark and « Finir ici » on the active leg still clear it"
  - "04-15 WR-01 accepted as false-advance residual R10 (Annuler in the zone of a normal mark, then an inside-of-the-turn exit advances); crew fallback: Annuler again outside the zone (no loop) or « Préc. »; post-race candidate: real _near on suppressed ticks, stand-in only when already past along the outgoing leg"
  - "04-15: 04-14 D3 corrected: 'Annuler in the zone then an approach-side retreat never re-advances' holds only for a retreat on the OUTSIDE of the turn"
  - "04-15: new src/jabuka fingerprint 8b0a3bc4...19c8 (147 files) replaces f4a6fa25...9cc8 -> wheelhouse rebuild + Pi re-provision"

patterns-established:
  - "Annuler-then-edit grid (Jabuka 8 kinds, committee 7 kinds x turn 60/75) plus clear-case guards as permanent parametrised tests"

requirements-completed: []

coverage:
  - id: D1
    description: "CR-01 at Jabuka (CR-02 track): after Annuler, « Finir ici » at Blitvenica, « Ajouter » at the default position, select B, delete leg 3, « Rendre active » on Jabuka or reorder(3, 4) keep suppress_idx 2, and the run north advances exactly once more (2 course_advance, active 3, suppress None); no edit / Blitvenica moved unchanged"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_jabuka_annuler_then_an_edit_that_keeps_the_active_leg_still_advances"
        status: pass
    human_judgment: false
  - id: D2
    description: "CR-01 at a committee mark (turn 60/75): after Annuler and the real rounding while suppressed, add_mark default, delete_leg(2), set_finish(2), activate(1), reorder(3, 2) keep suppress_idx 1 and the beat out advances exactly once more; edit_mark of the next mark and set_leg(side) unchanged"
    requirement: CRSE-02
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_committee_annuler_then_an_edit_that_keeps_the_active_leg_still_advances"
        status: pass
    human_judgment: false
  - id: D3
    description: "The limits: « Finir ici » on the active leg (finishes on entering the 0.05 nm radius), activate another leg, « Suiv. », an index shift (R6), select() to another mark all clear the suppression"
    requirement: CRSE-04
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_an_edit_that_changes_the_active_leg_or_makes_it_the_finish_clears_the_suppression"
        status: pass
    human_judgment: false
  - id: D4
    description: "Accepted residual R10 pinned (turn 45/60/90) with the crew fallback (second Annuler outside the zone, no third advance)"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances"
        status: pass
    human_judgment: false
  - id: D5
    description: "On-boat drill: early advance, Annuler, finish the rounding, « Finir ici » on a later mark (or « Ajouter ») inside the zone; the course moves on after leaving the zone past the mark"
    verification: []
    human_judgment: true
    rationale: "A real GPS track at a real mark is outside the automated gate (Human Items)"

duration: 27min
completed: 2026-11-09
status: complete
---

# Phase 04 Plan 15: CR-01 Annuler suppression survives a keep-the-leg edit, WR-01 as R10, IN-01 Summary

**After Annuler, a crew edit that keeps the active leg (« Finir ici » at a later mark, « Ajouter » at the default position, deleting or reordering a later leg, « Rendre active » on the active leg, an A↔B switch that keeps the mark) no longer leaves the course stuck on the mark just rounded. A new `CourseStore._carry_suppress` in `_commit` keeps `suppress_idx`, and with it the CR-02 stand-in. The 16 previously stuck cases (6 at Jabuka, 10 at committee marks) now advance exactly once more. WR-01 is the accepted, pinned residual R10. The docstrings now state what an edit keeps, drops and clears. New src/jabuka fingerprint 8b0a3bc4…19c8 (147 files).**

## Performance

- Started 2026-11-09T16:23:43Z and finished 2026-11-09T16:51Z, so 27 min wall time, of which the full gate took about 23 min (3.14, then 3.13).
- 2 tasks and 4 commits (2 test, 1 fix, 1 docs). 2 files changed: 251 insertions and 10 deletions in src and tests, about 10.7 k characters of diff.

## Gaps closed

| Id (04-REVIEW, review ccbbdc2) | Disposition | Fix | Commits |
|---|---|---|---|
| CR-01 (blocker) | Fixed | `CourseStore._carry_suppress(new)`. `_commit` calls `course = self._carry_suppress(course)` right after `_check_version` and before `_write` | e39e414 (RED), 9caa866 |
| WR-01 (warning) | Accepted residual R10, pinned. No code change | `test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances` (turn 45/60/90), which also proves the crew fallback | 96afc49 |
| IN-01 (info) | Fixed (comment-only) | Corrected the module docstring, the `_fsm_outgoing` docstring and the CR-02 stand-in comment in `_fsm` (keep/drop/clear, R10) | 871ce0d |

## CR-01: which edits keep the suppression and which clear it

The rule: an Annuler suppression (`suppress_idx`) belongs to one leg. It stays exactly as long as that leg stays active and the boat must still round it.

**Kept** (`_carry_suppress` puts it back, or the command never cleared it). The active index, the active mark and the "not the finish" status are all unchanged:
- add_mark after the active leg: « Ajouter » at the default position, and « À la fin » when the active leg is not the finish;
- delete_leg of a later leg, including the finish leg (finish_idx falls back to None);
- a reorder that leaves the active leg at its index (later legs only);
- set_finish(idx) with idx > active_idx (« Finir ici » at a later checkpoint), and set_finish(None) (« Parcours complet »);
- activate(active_idx) (« Rendre active » on the active leg);
- a select() that keeps the same mark at the same index (A↔B at Plić Sestre or Jabuka);
- edit_mark, set_leg and confirm_sides. These never cleared it and are unchanged.

**Cleared** (the guard does not carry it):
- « Suiv. »/« Préc. » (`_step`) and activating another leg: the crew picked another mark;
- set_finish(active_idx) (« Finir ici » on the active leg). The finish fires on entering the radius, and the radius lies inside the zone;
- set_finish(idx < active_idx): the active mark moves back;
- delete_leg of the active leg, or the add_mark IN-03 case (a mark inserted before the active finish becomes active);
- a delete of a later leg that leaves the active leg as the last one: it becomes the finish;
- an index shift of the active leg. `_set` resets the whole state machine (residual R6);
- a select() that puts another mark active (custom → A, or Blitvenica ↔ Mulo);
- `undo`, `_advance` and `_finish`. The guard never applies to them: undo starts from suppress_idx None, and advance/finish carry a banner.

## WR-01 → accepted residual R10, and the correction of 04-14 D3

**Correction of 04-14 D3.** 04-14 claimed: "Annuler in the zone at a normal mark then an approach-side retreat never re-advances". That holds **only for a retreat on the OUTSIDE of the turn** (dot_out <= 0, the b_in + 210 deg tracks of the 04-14 tests). A retreat on the inside of the turn (dot_in < 0, dot_out > 0, e.g. b_in + 120 deg) **advances** after Annuler, even though the boat never came within radius + MARK_TOL_NM. That is R10.

**Why it is accepted.** At a normal mark the CR-02 stand-in sets `_near = True`. The alternative is to collect real `_near` on the suppressed ticks. That would leave an Annuler tapped beyond radius + 0.1 nm, after a correct advance, stuck on the beat-out. The owner rule is never to trade a stuck course for fewer false advances.

**Post-race candidate**, to be measured on the stuck grids first: collect real `_near` on the suppressed in-zone ticks, and use the stand-in only when the boat was already past the mark along the outgoing leg (dot_out > 0) at the first suppressed tick.

## Accepted residuals after this plan (R1-R10)

None of these is fixed before the freeze.
- **Stuck (R2-R8):** crew fallback Carte → « Suiv. ».
- **False advance (R1, R9, R10):** crew fallback « Annuler » on the 60 s banner, or Carte → « Préc. ».

| # | Case | Why accepted | Crew fallback | Pinned by |
|---|---|---|---|---|
| R1 | (false advance) The boat comes near a normal mark (within radius + 0.1 nm) on the approach side, then leaves on the inside of the turn | It cannot be told apart from rounding a mark entered up to 0.1 nm off (04-13) | Annuler / « Préc. » | test_inside_of_the_turn_exit_after_coming_near_advances |
| R2 | A normal mark entered so far beyond the buoy that the boat never comes within radius + MARK_TOL_NM (measured over 0.15 nm) | A wider tolerance would eat the G-4-R02 band (04-13) | « Suiv. » | test_committee_mark_beyond_the_bound_needs_a_manual_next |
| R3 | A hairpin mark (turn > 90 deg) entered beyond the buoy along the incoming leg. Also covers a normal mark that becomes a hairpin through an in-zone edit of the next mark, or through a lateral entry error that tips the turn over 90 deg | The near term at a hairpin would reopen G-4-R02 at Jabuka | « Suiv. » | test_committee_mark_beyond_the_bound_needs_a_manual_next (turn 150) + test_an_edit_that_makes_an_off_buoy_mark_a_hairpin_needs_a_manual_next |
| R4 | The track never enters the zone | Pre-existing zone design | Set the leg radius; « Suiv. » | existing design |
| R5 | No usable fix from the zone exit out to 2 nm | Pre-existing debounce/gate | « Suiv. » once PAS DE GPS clears | existing design |
| R6 | Any of these edits, made after the rounding and before the advance, in the zone or after it: moving the active mark, changing its radius, or changing its previous mark. That includes a leg inserted, deleted or reordered before it (an index shift), and a select() A<->B that gives it a different previous mark. Edits of the side or of the next mark are not in R6. **After Annuler, an index shift of the active leg also clears the Annuler suppression (with the evidence).** | The evidence was measured against the old incoming leg, mark or radius, so the corrected mark must be rounded again | « Suiv. » | 04-13 WR-01 tests (moved hairpin, brief abeam move, radius shrink, previous_moved) + test_an_edit_that_changes_the_active_leg_or_makes_it_the_finish_clears_the_suppression[insert_before] |
| R7 | Annuler on a correct advance once the boat is already outside the zone | Pre-existing CR-02 rule | « Suiv. » | test_undo_outside_the_zone_needs_a_fresh_entry |
| R8 | A mark entered off the buoy (no latch). The crew moves the next mark by 60 deg or more while still in the zone after the rounding, and the boat keeps sailing the old leg | By the new outgoing leg, the boat is on the approach side | Steer to the new mark; otherwise « Suiv. » | test_a_big_next_mark_change_while_sailing_the_old_leg_needs_a_manual_next |
| R9 | (false advance) One fix past the abeam line after entering the zone, then a zone exit (including on the approach side) advances | No fix keeps stuck = 0 and lowers it (04-14 table) | Annuler / « Préc. » | test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances |
| R10 | **New, from review ccbbdc2 WR-01.** (false advance) After Annuler in the zone of a normal mark, a zone exit on the inside of the turn (dot_in < 0, dot_out > 0) advances, even though the boat never came within radius + MARK_TOL_NM. The stay in the suppressed zone stands in for "came near" | Real near evidence on the suppressed ticks would leave an Annuler tapped on the beat-out stuck (owner rule). Post-race candidate above | Annuler again (now outside the zone, so the R7 fresh-entry path applies and it does not loop) or « Préc. » | test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances |

## TDD evidence

| Task | RED commit | RED result | GREEN commit | GREEN result |
|---|---|---|---|---|
| 1 (tracer) | e39e414 | `16 failed, 255 passed` on 2ebbd25. The 16 failures are the 6 Jabuka edit kinds (finir_ici_next, add_default, select_B, delete_next, activate_same, reorder_later) and the 10 committee cases (add_default, delete_next, finir_ici_next, activate_same, reorder_later × turn 60/75). All fail on the post-edit `suppress_idx` assertion (`None == 1` / `None == 2`). The guards ("none", "move_next", "edit_next", "side") and the 5 clear-case tests pass, as specified | 9caa866 | tests/nav/test_course.py: 271 passed on 3.14 and 3.13. tests/nav + sim + web + test_no_wallclock: 596 passed (3.14) |
| 2 (pin) | 96afc49 | It is a pin, so it passes before and after the fix: 3 new cases | — | tests/nav/test_course.py: 274 passed on 3.14 and 3.13 |

**Tracer gate (Task 1).** After 9caa866 the full `<verify>` ran end to end and passed before Task 2 started. It covered both venvs, tests/nav, sim, web and no-wallclock, ruff check and format on src and tests, and the AST check.

## Acceptance checks

BASE = plan_head_before = 2ebbd259b4daad12aea3e7c71a5ea69a98812bc9 (var/base-04-15.txt).
- `var/ast-04-15.py`: the planner's scratch was empty, so this was written from the plan's spec (stdlib only, `python -I`). On BASE itself it prints `carry_method=0 commit_calls=0 rest_identical=True` (exit 1, as expected).
  - After Task 1 (9caa866): `carry_method=1 commit_calls=1 rest_identical=True`, exit 0.
  - After Task 2 (871ce0d): `carry_method=1 commit_calls=1 rest_identical=True`, exit 0.
- The `_abeam` → `on_tick` span (`_abeam`, `_leg_dots`, `_past_mark`) is byte-identical to BASE: the diff was empty after both tasks.
- `_carry_suppress` occurs 5 times in course.py: the def, the call, and the `_commit`, module and `_fsm_outgoing` docstrings.
- R10 is in the module docstring and in the `if left_this_zone:` block. `banner` is in the `_fsm_outgoing` span.
- `git diff BASE -- tests/nav/test_course.py` removes 0 lines (`^-[^-]` count 0).
- `git diff --name-only BASE -- src tests deploy docs scripts` lists exactly src/jabuka/nav/course.py and tests/nav/test_course.py.
- tests/nav/test_course.py has 274 tests (244 + 30). Each of 3.14 and 3.13 reports 274 passed.

## Gate (var/gate-04-15.log)

The log was removed first. Then `(JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh; echo "EXIT=$?") > var/gate-04-15.log 2>&1` ran on HEAD 871ce0d:

```
bootstrap: ok
All checks passed!            (ruff check)
234 files already formatted   (ruff format --check)
3.14: 1915 passed, 4 skipped in 696.66s (0:11:36)
3.13: 1915 passed, 4 skipped in 687.12s (0:11:27)
check: ok
EXIT=0
```

1915 = 1885 (04-14) + 30 new tests. The 4 skips are the same pre-existing ones. The 04-04 soak flake did not occur.

## New src/jabuka fingerprint

- **FINGERPRINT_SH** (`git archive HEAD src/jabuka` at HEAD 871ce0d, the last src commit of this plan): `8b0a3bc46c45900632b975c164a215dd8207a8c883a5b50f4470c705358f19c8`, **147 files**.
- Cross-check: `jabuka.soak.report.package_fingerprint(Path('src/jabuka'))` on the working tree (clean under src/jabuka) gives `{'sha256': '8b0a3bc46c45900632b975c164a215dd8207a8c883a5b50f4470c705358f19c8', 'files': 147}`.
- It replaces `f4a6fa25bdacf0555af57536fd4e96cd5b4a0b46ac935b05797c941bfccc9cc8` (04-14).
- **The wheelhouse must be rebuilt and the Pi re-provisioned from this HEAD.** No unit file changed. The orchestrator or the owner does this; this plan did not.

## Deviations from Plan

**1. [Rule 3 - Blocking] I wrote var/ast-04-15.py from the plan's spec.** The planner's scratch directory p0415/ was empty, which the orchestrator had already noted. The script follows the spec exactly:
- it strips the module, class and function docstrings;
- it drops the `_carry_suppress` FunctionDef and every `_commit` statement that mentions it;
- it compares `ast.dump`;
- it exits 0 only for 1/1/True.

It is gitignored and not committed.

There were no other deviations. Test counts matched the plan exactly: RED 16 failed / 255 passed, then 271, then 274, and the gate 1915.

## Deferred / accepted advisories

| Finding | Decision | Rationale |
|---|---|---|
| IN-01 alternative "also carry the banner when the active leg is unchanged" | Not done | It is a UX change with its own timing semantics. The docstrings now say that add_mark/delete_leg/reorder drop the banner. Crew fallback: « Préc. » |
| WR-01 code narrowing | Post-race | See R10 |
| Advisories carried from 04-14 (IN-01 crash-path drain and others) | Unchanged | Untouched by this plan |
| docs/I18N-SL-REVIEW.md.bak (untracked) | Not touched | The owner removes it in the freeze clean-tree step |

## Known Stubs

None.

## Threat Flags

None. The change adds no network, auth, file or schema surface. course.json keeps its format; only the value of `suppress_idx` after some edits differs.

## Human Items (before the freeze 2026-11-11)

| Item | Due | Source |
|---|---|---|
| Rebuild the wheelhouse from the final HEAD and re-provision the Pi. The installed fingerprint must equal 8b0a3bc4…19c8 (147 files), which replaces f4a6fa25…9cc8. Swap the PSU first (get_throttled 0x50005) | 2026-11-10 / 11 | 04-VERIFICATION human item 1 |
| Laptop race-36h soak and Pi system-scope soak on this HEAD (procedure unchanged) | 2026-11-10 / 11 | 04-VERIFICATION human items 2-3 |
| Plan B single-crash check on the Pi after re-provisioning (04-14 procedure, unchanged) | after re-provisioning | 04-14 Human Items |
| On the boat, **new**: after an early advance, tap Annuler, then finish the rounding. While still in the zone, use « Finir ici » on a later mark (or « Ajouter »). The course moves on once the boat leaves the zone past the mark | 12 Nov | CR-01 (review ccbbdc2) |
| Course card, written by hand (no repo doc change before the freeze). Add to the 04-14 rules two items. First: "If the course moves on right after Annuler while you are still inside the turn, before passing the mark, tap Annuler again or Carte → « Préc. »" (R10). Second: "An edit made inside the 60 s banner window removes Annuler; use « Préc. »" (IN-01) | 13 Nov, course card | R10, IN-01 |
| Delete or ignore the untracked docs/I18N-SL-REVIEW.md.bak before the freeze clean-tree check | freeze | 04-VERIFICATION anti-patterns |

## Next Phase Readiness

All 15 plans of phase 4 have a SUMMARY. The next steps are:
- re-verify phase 4 (CR-01 of review ccbbdc2 closed; WR-01 = R10; IN-01 closed);
- the freeze;
- the wheelhouse rebuild and Pi re-provisioning to fingerprint 8b0a3bc4…19c8;
- the Human Items above.

## Self-Check: PASSED

- src/jabuka/nav/course.py, tests/nav/test_course.py, var/base-04-15.txt, var/ast-04-15.py and var/gate-04-15.log exist.
- Commits e39e414, 9caa866, 96afc49 and 871ce0d are in `git log`. Measured `git rev-list --count 2ebbd25..871ce0d` = 4.
- The gate log ends with `check: ok` / `EXIT=0`.
- The fingerprint was cross-checked against package_fingerprint.
