---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-09T16:57:06Z
depth: standard
scope: incremental (984bcb9..HEAD df20c5b, gap-closure plan 04-15; previous review ccbbdc2 CR-01, WR-01 (accepted R10), IN-01)
files_reviewed: 2
files_reviewed_list:
  - src/jabuka/nav/course.py
  - tests/nav/test_course.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-15)

**Reviewed:** 2026-11-09T16:57:06Z
**Depth:** standard. The diff 984bcb9..HEAD covers `_carry_suppress`, its call in `_commit`, the docstrings and the 30 new tests. I also read the code it interacts with: every `_commit` caller, `_set`, `_save_quiet`, `_fsm`, `undo`, `_advance`, `_finish`, and the `course_api.mutate` serialization.
**Files Reviewed:** 2
**Status:** issues_found (Info only)

## Narrative Findings (AI reviewer)

## Summary

Plan 04-15 closes CR-01 of review ccbbdc2 correctly, and I found no new blocker or warning.

**How `_carry_suppress` works.** It is a pure function of (old course, new course). It runs in the single commit path, after the version check and before the atomic write, so `course.json` persists the carried value. It carries `suppress_idx` only when all of these hold:
- the old suppression is on the old active leg;
- the command nulled the suppression;
- there is no banner and the course is not finished;
- the active index and the active mark id are unchanged;
- the active leg is not the finish.

I traced each path below by reading the code. Where it says "probe", I also reproduced it with the real `CourseStore` (`.venv/bin/python -I`, scratch scripts only, no source changes).

**1. Tick commits never carry.** `_advance` changes the active index and carries a banner. `_finish` is finished and carries a banner. `undo` sets `suppress_idx` itself. So the `_commit_tick` OSError fallback, which applies the uncarried course, cannot diverge.

**2. A carried suppression never lands on a stale index or a different leg.** All callers keep the invariant `suppress_idx == active_idx < last_idx`:
- Every command that changes the active index or mark (`_step`, `activate(other)`, `delete_leg(active)`, an index shift, `select` to another mark) fails the guard.
- `reorder` tracks the active leg through `order.index`. So "same index and same mark id" always means the same leg.
- A consecutive duplicate mark id, which `delete_leg(active)` would need in order to put a different leg with the same id at the same index, cannot be produced. `add_mark` always mints a new id, the templates repeat only Vodice, and the start never moves.

**3. A carried suppression never blocks a finish.** The guard refuses the finish leg, whether it became the finish through `set_finish(active)` or through a delete that leaves the active leg as the last one. That refusal is required, not just defensive. A suppressed finish leg returns early on every in-zone tick, and outside the zone `d > radius`, so it could never finish. Probe: Annuler at Jabuka, then « Finir ici » at Blitvenica, then a restart from disk. The suppression survives the restart, the exit advances once, and entering Blitvenica's radius gives `ARRIVÉE — Blitvenica`.

**4. A carried suppression never blocks a legitimate advance that clearing would allow.** After a carry, the state machine follows exactly the path it would follow with no edit:
- `_set` does not reset, because the active leg is the same.
- For every carried edit except the one in IN-01, `_fsm_geometry` is unchanged, so `_suppressed_in_zone` survives. Only the debounce restarts.

The previous review established that the no-edit Annuler path is a superset of the cleared path for zone exits:
- **Normal mark:** the stand-in sets `_near`.
- **Hairpin:** the stand-in sets `_beyond`.

The only thing the carry gives up is an advance inside the zone. Suppressing that is the point of Annuler.

**5. The 409 and concurrency paths are safe.** `_check_version` runs before the carry, so a 409 leaves both the course and the suppression untouched. Probe: `set_finish(3, base_version=v-1)` raises, and afterwards `suppress_idx` is still 2 and `finish_idx` is still None. The course API handlers are `async def` and call the synchronous store, so they are serialized with the tick on the event loop. Nothing yields between building the new course and `_commit`, so `old = self.course` is never stale.

**6. The banner window cannot interact with the carry.** A banner and a suppression never coexist: `_advance` runs only once the suppression has been cleared or returned early, and `undo` nulls the banner. So the banner guard is defensive only. Edits made inside the window drop the banner exactly as they did before 04-15.

**7. Kept versus cleared matches the summary's lists.** The one exception is the boundary case in IN-01, which falls under R6. Apart from it, no edit that keeps the active leg (same index and mark) and does not make it the finish still clears the suppression.

**Verification.** `tests/nav/test_course.py` passes, 274 tests (re-run here). The new grids test real tracks, not just the flag: each one asserts exactly 2 `course_advance` events, plus `suppress_idx` before and after.

### Previous findings: status

| Previous finding (review of ccbbdc2) | Status after 04-15 |
|---|---|
| CR-01: an edit that nulls `suppress_idx` after Annuler, with the boat still in the zone, leaves the course stuck on the rounded mark | **Closed.** `_carry_suppress` in `_commit`. The 6 Jabuka and 10 committee stuck rows from the previous repro now advance exactly once more, pinned by `test_jabuka_annuler_then_an_edit_that_keeps_the_active_leg_still_advances` and `test_committee_annuler_then_an_edit_that_keeps_the_active_leg_still_advances`. The clear cases are pinned by `test_an_edit_that_changes_the_active_leg_or_makes_it_the_finish_clears_the_suppression`. Re-checked by probe, including persistence across a restart and the 409 path |
| WR-01: after Annuler in the zone of a normal mark, an inside-of-the-turn retreat advances | **Accepted residual R10**, pinned by `test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances` (turn 45/60/90). The test also proves the crew fallback: a second Annuler outside the zone does not loop. The R10 comment in `_fsm` and the module docstring are accurate. Not re-raised |
| IN-01: the `_fsm_outgoing` and module docstrings promise more than the edits deliver | **Closed in substance.** Both now say that the evidence and the suppression are kept and the banner is dropped. One completeness gap remains in the list of banner-dropping edits; see IN-02 |
| Advisories from earlier rounds (crash-path drain, Diag/helm write alert, and others) | Open (advisory, deferred), unchanged by 04-15 |

## Info

### IN-01: A kept edit that changes the incoming leg loses the CR-02 stand-in when the very next fix is already outside the zone (R6 boundary; the docstring and R6 row are imprecise)

**File:**
- `src/jabuka/nav/course.py:312-319` (the `_carry_suppress` docstring: "keeps the Annuler suppression, and with it the CR-02 ... stand-in");
- `:814-819` (a key change calls `_reset_fsm()`, which clears `_suppressed_in_zone`);
- `:831` (`left_this_zone`).

**Issue:** `_carry_suppress` keeps `suppress_idx` for any edit that leaves the active index and mark unchanged. That includes `reorder` of two legs before the active one, which changes its previous mark without an index shift. On the next tick, `_fsm_geometry` differs, so `_reset_fsm()` clears `_suppressed_in_zone` while `suppress_idx` stays set:
- If that tick is still inside the zone, the flag is set again and the stand-in works.
- If the boat crossed the zone boundary within the same second as the edit, `left_this_zone` is False and the course needs a fresh entry.

Probe (Course A plus a mark X inserted at 1, Jabuka active at 3, the Jabuka Annuler track, the last suppressed fix at 0.84 nm, the edit, then out along 009 deg from 0.86 nm):

```
none             -> active 4, 2 advances
activate(3)      -> active 4, 2 advances
reorder(1, 2)    -> active 3, 1 advance   STUCK ("Suiv.")
```

With one more in-zone fix after the reorder, it advances (2 advances).

**Severity calibration.** This is not a new defect, for three reasons:
- It is the R6 class ("changing its previous mark"), with the documented « Suiv. » fallback.
- Before 04-15 the same reorder cleared the suppression, so it was already stuck, and the window is one second wide.
- No template switch reaches it, because A and B have the same mark before Plić Sestre and before Jabuka.

The text is still inexact in two places:
- The docstring says the stand-in is kept unconditionally.
- The R6 row in 04-15-SUMMARY names only "an index shift" for the Annuler case, and the summary lists the kept reorder as "later legs only", although a reorder of earlier legs is kept too.

**Fix:** After the race, add one clause to the docstring and to R6: "an edit that keeps the active leg but changes its incoming leg (previous mark moved or reordered) keeps `suppress_idx`, but restarts `_suppressed_in_zone` (R6)". Optional code narrowing, also after the race: in the key-change branch of `_fsm`, preserve `_suppressed_in_zone` when `c.suppress_idx == idx`. The suppressed zone is the active mark's, and it is unchanged by a previous-mark edit.

### IN-02: The banner-drop and clear-case lists in the docstrings are incomplete

**File:** `src/jabuka/nav/course.py:29-31` (module docstring), `:674-676` (`_fsm_outgoing`), `:316-319` (`_carry_suppress`)

**Issue:** There are two gaps.
- **Banner-drop list.** The module and `_fsm_outgoing` docstrings say that "add_mark, delete_leg and reorder also drop the banner". But four more commands set `banner=None` while keeping the active leg:
  - `select()` (A to B also changes the side and the next mark);
  - `set_finish(idx > active)` (« Finir ici » at a later mark);
  - `set_finish(None)`;
  - `activate(active_idx)`.

  Each of these removes Annuler inside the 60 s window too. The hand-written course-card rule ("An edit made inside the 60 s banner window removes Annuler; use « Préc. »") is general, so the crew is covered; only a maintainer reading the docstring is misled.
- **Clear-case list.** The `_carry_suppress` docstring names « Finir ici » on the active leg as the finish case. It does not name a `delete_leg` of later legs that leaves the active leg as the last one, which also turns it into the finish and is also cleared. The guard is right; only the text omits the case.

**Fix:** After the race, as a comment-only change:
- Make the module and `_fsm_outgoing` text say "every edit command except edit_mark, set_leg and confirm_sides drops a pending banner".
- In `_carry_suppress`, replace "« Finir ici » on the active leg" with "an edit that makes the active leg the finish (« Finir ici » on it, or deleting every later leg)".

---

_Reviewed: 2026-11-09T16:57:06Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
