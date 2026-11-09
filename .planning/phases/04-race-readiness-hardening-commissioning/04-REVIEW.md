---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-09T16:04:47Z
depth: standard
scope: incremental (93cb8b3..HEAD ccbbdc2, gap-closure plan 04-14; previous review CR-01, WR-01, WR-02 (accepted R9), WR-03, IN-02)
files_reviewed: 5
files_reviewed_list:
  - src/jabuka/nav/course.py
  - src/jabuka/ingest/rawlog.py
  - tests/nav/test_course.py
  - tests/test_background_durability.py
  - tests/deploy/test_units.py
findings:
  critical: 1
  warning: 1
  info: 1
  total: 3
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-14)

**Reviewed:** 2026-11-09T16:04:47Z
**Depth:** standard. The diff 93cb8b3..HEAD, plus the code it calls (`_set`, the edit commands, `undo`, `carte.js` course actions).
**Files Reviewed:** 5
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

Plan 04-14 does what it set out to do on its own test grid.

**The key split is correct.** `_fsm_geometry` is now (idx, mark, radius, previous pos, active pos). `_fsm_outgoing` is (side, next pos). This matches what each piece of evidence is actually measured against:
- `_beyond` comes from `dot_in`;
- `_near`, `_entered` and `_suppressed_in_zone` come from the distance and the radius.

The ordering is also right:
- the gap check runs first, then the key check, then the outgoing check;
- the suppress block re-stores both `_fsm_key` and `_fsm_out`, so the debounce does not restart one tick late;
- `_set` still resets on an `(active_idx, mark_id)` change, so index shifts stay in R6.

**The other fixes are correct:**
- **IN-02:** the change to `rawlog._cadence` is correct. Data is still written at the flush cadence; only the fsync retry is delayed.
- **WR-03:** the rewritten Plan B test now models the real fastnet2ip exit on EIO.

I traced every finding below with the real `CourseStore` (`.venv/bin/python -I`, scratch scripts only, no source change). Two state-machine defects remain:

1. **Blocker (CR-01):** CR-01 of 93cb8b3 is closed only when no Annuler is pending. Several common course edits null `suppress_idx` even though the active leg is unchanged, and that throws away the CR-02 "left the suppressed zone" stand-in:
   - "Finir ici" (the shortened-course drill);
   - « Ajouter » at its default position;
   - deleting or reordering a later leg;
   - « Rendre active » on the active leg;
   - `select()`.

   The suppressed ticks never collect real evidence. So when one of these edits comes after Annuler, with the boat still in the zone after a real rounding, the course stays on the rounded mark for good. This is reproduced at **Jabuka** on the repo's own `test_hairpin_annuler_then_real_rounding_advances` track. It is outside R1-R9.
2. **WR-01:** the WR-01 fix of 93cb8b3 covers only the outer half of the approach side. After Annuler in the zone, `_near` is *assumed*. So a retreat on the approach side, **inside** the turn, advances again even though the boat never came within radius + `MARK_TOL_NM`. That widens R1 from radius + 0.1 nm to the whole zone, and nothing documents or pins it.

### Previous findings: status

| Previous finding (review of 93cb8b3) | Status after 04-14 |
|---|---|
| CR-01: an edit of the next mark or the side in the zone after a tight rounding leaves the course stuck | **Closed when no Annuler is pending.** The key split is correct, and the 140-case grid reproduces as claimed. The same stuck class is still reachable through edits that clear `suppress_idx` after an Annuler; see CR-01 below. That path already existed at 93cb8b3; it is not a 04-14 regression. It was not covered by the grid, which never combines Annuler with an edit |
| WR-01: after Annuler at a normal mark, a zone exit in any direction advances (G-4-R02 reopened) | **Partially closed.** Retreats in the outer approach quadrant (b_in + 210 deg) no longer advance; the repro at 93cb8b3 advanced in every direction. Inside-of-the-turn approach-side retreats still advance; see WR-01 below |
| WR-02: a one-fix `_beyond` latch outside the zone | **Accepted residual R9**, pinned by `test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances`, with evidence that each candidate fix either fails to lower the false advances or adds a stuck rounding. Not re-raised |
| WR-03: the Plan B test asserted a fastnet2ip behaviour that does not happen | **Closed** (`tests/deploy/test_units.py:207-267`). The stand-in exits 1 on relay loss, and the test asserts that both units are active, that NRestarts >= 1 on both, and that Plan B has a new MainPID |
| IN-01: the crash-path exit drain can outlast the watchdog | Open (advisory, deferred by plan 04-14) |
| IN-02: a persistent pre-queue fsync failure logs at ERROR every second | **Closed** (`rawlog.py:219-221`, `test_a_failed_submit_retries_on_the_fsync_cadence[dup/submit]`) |
| Older WR-02 part (Diag/helm alert for background write failures), WR-04, WR-05, IN-01..IN-04 of earlier rounds | Open (advisory, deferred), unchanged by 04-14 |

## Critical Issues

### CR-01: An edit that clears `suppress_idx` while the boat is in the suppressed zone after Annuler leaves the course stuck on the mark just rounded, outside R1-R9

**File:** `src/jabuka/nav/course.py`:
- the commands that null `suppress_idx` while the active leg is unchanged:
  - `:379` (`select`, through `course_from_template`);
  - `:412` (`activate`);
  - `:452` (`add_mark`);
  - `:546` (`delete_leg`);
  - `:579` (`reorder`);
  - `:598` (`set_finish`);
- `:794-821`, the CR-02 path that the edit bypasses.

**Issue:**

**How the Annuler path works.** After `undo()`:
- `_reset_fsm()` runs, so `_entered`, `_near` and `_beyond` are all False.
- Every suppressed in-zone tick returns at line 797 before any evidence is collected.
- The only thing that carries the rounding forward is the CR-02 branch at lines 798-821. When the boat leaves the zone it was suppressed in, that branch sets `_entered` and `_near`, plus `_beyond` at a hairpin.

**What the edits break.** That branch runs only while `c.suppress_idx is not None`. The six commands above set `suppress_idx=None` even when the active leg stays the same leg (same index and mark). In that case `_set` does not reset the FSM, but the stand-in is gone. On the next tick the boat is handled as a fresh entry:
- `_near` is set only if d <= radius + 0.1 nm **now**;
- `_beyond` is set only if `dot_in > 0` **now**.

A boat that has already rounded and is beating or reaching out, past radius + 0.1 nm and with `dot_in < 0`, never gets either one again. At a hairpin, the exit then needs `_beyond`; at a normal mark with a turn of 60 deg or more, it needs `_near`. Neither comes back, and at 2 nm the gate clears `_entered`. The course stays on the rounded mark, and the router steers back to it.

**Reproduction 1: Jabuka.** This is the real `CourseStore` on Course A, using the track of `test_hairpin_annuler_then_real_rounding_advances`:
- the far-side wedge advance;
- Annuler;
- 5 s suppressed at 300 deg / 0.7 nm (zone 0.85 nm);
- **the edit**;
- 5 s more at 300 deg / 0.7 nm;
- out north along 009 deg to 2.6 nm.

Results:

```
no edit                                   -> active 3 (Blitvenica), 2 advances  (as the test)
edit_mark Blitvenica (keeps suppress_idx) -> active 3, 2 advances
set_finish(3)  "Finir ici" at Blitvenica  -> active 2 (Jabuka), 1 advance   STUCK
add_mark default position (« Ajouter »)   -> active 2, 1 advance            STUCK
select("B")                               -> active 2, 1 advance            STUCK
delete_leg(3)                             -> active 2, 1 advance            STUCK
activate(2)  (« Rendre active » on it)    -> active 2, 1 advance            STUCK
```

**Reproduction 2: committee mark.** The setup is the `_committee` geometry (radius 0.05 nm, zone 0.30 nm):
- the in-zone abeam advance of `_committee_advance_then_annuler`, then Annuler;
- a suppressed rounding at 0.02 nm;
- the boat then at turn + 45 deg / 0.2 nm, where the edit is made;
- a beat out to 1.7 nm.

Results: with a turn of 60 or 75 deg, `add_mark` default, `delete_leg(2)`, `set_finish` and `activate(1)` all give **STUCK** (1 advance). `edit_mark` of the next mark and `set_leg(side)` both advance, because they keep `suppress_idx`.

**Why this matters.** The edits are the ones the UI offers on the active mark (`carte.js:608`, `:769`, `:771-774`):
- « Ajouter » posts `insert_at: null`, which is the default `active_idx + 1`;
- "Finir ici" is offered on every leg;
- « Rendre active » stays enabled on the active leg.

The precondition is also an expected event at Jabuka:
- Annuler at Jabuka is exactly the CR-02 scenario the code was designed for;
- the 0.85 nm zone keeps the boat inside it for minutes after the rounding;
- a shortened course ("Finir ici" at Blitvenica) is a common committee signal on a long night leg.

**Scope and residuals.** The plan claims (04-14-SUMMARY D1, and the `_fsm_outgoing` docstring) that an edit of the next mark, including one "added at the default position, deleted or reordered", restarts only the debounce. That claim is false when an Annuler is pending. None of R1-R9 covers this:
- R6 is about active, radius and previous-mark edits;
- R7 is about Annuler tapped outside the zone.

The same scripts against a `git archive 93cb8b3` tree give the identical STUCK rows, so this is pre-existing rather than a 04-14 regression. Under the owner's rule it is still a stuck course on the mark just rounded, with only the crew's « Suiv. » to recover.

**Fix.** Keep the suppression (the CR-02 stand-in) through any edit that leaves the active leg unchanged and does not turn it into the finish. One central place is `_commit`, or a helper called by the six commands:

```python
def _carry_suppress(self, new: Course) -> Course:
    """An edit that keeps the active leg keeps the Annuler suppression (CR-02 stand-in)."""
    old = self.course
    if (
        old.suppress_idx is not None
        and old.suppress_idx == old.active_idx
        and new.suppress_idx is None
        and not new.finished
        and new.active_idx == old.active_idx
        and new.seq[new.active_idx].mark_id == old.seq[old.active_idx].mark_id
    ):
        last = new.finish_idx if new.finish_idx is not None else len(new.seq) - 1
        if new.active_idx < last:  # never on a leg that became the finish
            return new.model_copy(update={"suppress_idx": new.active_idx})
    return new
```

I checked this by monkeypatching `CourseStore._commit` in scratch:
- all seven Jabuka rows advance exactly once more (2 advances);
- every committee row advances;
- `tests/nav/test_course.py` still passes, 244/244, with the patch loaded as a pytest plugin.

`_step` (« Suiv. »/« Préc. ») must keep clearing it; the guard does that automatically, because the active leg changes. Add regression tests:
- the Jabuka hairpin Annuler track with `set_finish(3)`, `add_mark` default and `activate(2)` in the zone;
- the committee Annuler track at turn 60/75 with `add_mark` default and `delete_leg` of the next mark.

Each must give exactly 2 `course_advance` events. Also correct the `_fsm_outgoing` docstring and D1 in the summary.

## Warnings

### WR-01: After Annuler in the zone of a normal mark, an approach-side retreat on the inside of the turn advances again, though the boat never came within radius + MARK_TOL_NM (R1 widened, not documented or pinned)

**File:** `src/jabuka/nav/course.py:810-821` (the `left_this_zone` stand-in `_near = True`) with `:747-752` (`_past_mark`, normal rule); test `tests/nav/test_course.py` `test_annuler_in_the_zone_at_a_committee_mark_then_an_approach_side_retreat_never_advances`

**Issue:** At a normal mark, the CR-02 exit now sets `_near = True` without checking it. The normal rule `dot_out > 0 and _near` then accepts any exit with `dot_out > 0`. That includes the approach-side quadrant on the inside of the turn (`dot_in < 0`, `dot_out > 0`).

R1 accepts that quadrant only after the boat has really come within radius + 0.1 nm, because only then is it indistinguishable from rounding a mark entered off the buoy. After Annuler, the bar drops to "was anywhere in the zone" (radius + 0.25 nm). The regression test retreats only at b_in + 210 deg, the outer quadrant (its docstring says so), so this half of G-4-R02 is untested. 04-14-SUMMARY D3 ("an approach-side retreat never re-advances") overstates the fix.

Reproduction (real `CourseStore`, committee mark, radius 0.05 nm, zone 0.30 nm, near bound 0.15 nm):

- **The plan's own helper.** `_committee_advance_then_annuler`, then 5 s suppressed at b_in + rel / 0.2 nm, then out to 0.6 nm:
  - turn 45: rel 120 gives **2 advances**;
  - turn 60 and 90: rel 120 and rel 150 give **2 advances**;
  - rel 210 gives 1 advance (the pinned case).
- **Never within 0.25 nm of the mark at any point.** The R9 single-fix advance at 0.28 nm, then the boat tacks back into the zone at b_in + 150 / 0.27 nm, Annuler there, then a retreat to b_in + 120 / 0.7 nm:
  - turns 45, 60, 75 and 90 all give **2 advances**;
  - b_in + 150 gives 2 advances at turns 60, 75 and 90;
  - b_in + 210 gives 1 advance at every turn.

  The same track with no Annuler (fresh entry at 0.27 nm) would never advance, because `_near` would be False and `dot_in < 0`.

This is a false advance, and the crew can recover with Annuler and the banner. A second Annuler tapped outside the zone falls into the R7 fresh-entry path, so it does not loop forever. The plan's reason for not collecting real near/latch evidence on the suppressed ticks also holds: that would make an Annuler tapped beyond radius + 0.1 nm, after a correct advance, stuck on a beat-out. Under the owner's rule, that trade is not allowed.

**Fix:** Do not trade a stuck course for this. Record it in the residual table and pin it:

- Extend R1 (or add R10): "After Annuler in the zone of a normal mark, a zone exit on the inside of the turn (`dot_out > 0`) advances even without having come within radius + 0.1 nm. Crew: Annuler / « Préc. »".
- Add a pin test next to the b_in + 210 one, e.g. `test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances` (turn 60, b_in + 120, 2 advances), so a later change to the stand-in has to update the table.
- Correct D3 in 04-14-SUMMARY to "an approach-side retreat on the outside of the turn".
- A code narrowing for after the race, to be measured on the stuck grids first: collect real `_near` on the suppressed in-zone ticks (`d <= radius + MARK_TOL_NM`), and use the stand-in only when the boat was already past the mark along the outgoing leg (`dot_out > 0`) at the first suppressed tick, i.e. Annuler of a correct advance during the beat-out.

## Info

### IN-01: `_fsm_outgoing` and module docstrings promise more than the edit commands deliver

**File:** `src/jabuka/nav/course.py:27-29`, `:638-645`

**Issue:** Both docstrings say that a change of the side or of the next mark ("next mark moved, added at the default position, deleted or reordered") "restarts only the debounce". `add_mark`, `delete_leg` and `reorder` also clear the banner (the pending Annuler offer) and `suppress_idx`. The first is a UX side effect: a crew edit inside the 60 s window removes Annuler. The second is CR-01. A maintainer reading the docstrings would assume these edits are neutral for the state machine.

**Fix:** After CR-01 is fixed, state in `_fsm_outgoing` that these edits keep the evidence and the Annuler suppression but drop the banner. Alternatively, also carry the banner when the active leg is unchanged.

---

_Reviewed: 2026-11-09T16:04:47Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
