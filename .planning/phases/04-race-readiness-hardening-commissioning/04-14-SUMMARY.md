---
phase: 04-race-readiness-hardening-commissioning
plan: 14
subsystem: nav
tags: [rounding, course, state-machine, annuler, durability, rawlog, systemd, plan-b, gap-closure, freeze]
gap_ids: [CR-01, WR-01, WR-02, WR-03, IN-01, IN-02]
gap_dispositions:
  CR-01: fixed (state-machine key split; outgoing edits restart only the debounce)
  WR-01: fixed (CR-02 suppressed-zone exit sets _near at normal marks, _beyond only at hairpins / no outgoing leg)
  WR-02: accepted residual R9 (pinned by test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances)
  WR-03: fixed (test fidelity; Plan B stand-in exits 1 on relay loss; Pi human item gains NRestarts + UDP 2002 NMEA)
  IN-01: advisory, not done
  IN-02: fixed (pre-queue fsync failure advances _last_fsync)
plan_head_before: f96025b61494f402e99e78c1d12e08504cc1e25a
commits: 6

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: 04-13 _fsm_geometry key, MARK_TOL_NM/_near latch, CR-02 suppressed-zone exit, WR-03 in-flight flag clear, WR-06 relay RestartMode=direct
provides:
  - CourseStore._seq_pos(i) -> (mark id, lat, lon) | None
  - CourseStore._fsm_geometry(idx) = (idx, mark id, radius, previous pos, active pos) -> resets the rounding evidence
  - CourseStore._fsm_outgoing(idx) = (side, next pos) and _fsm_out -> a change restarts only _cand_since
  - CR-02 suppressed-zone exit: _entered + _near always; _beyond only at a hairpin or without a usable outgoing leg
  - RotatingAppendLog._cadence advances _last_fsync on a pre-queue fsync failure
affects: [freeze 2026-11-11, wheelhouse rebuild, Pi re-provisioning, 04 re-verification, course card]

actuals:
  tokens: 5100
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Two-level state-machine key: incoming geometry resets the evidence, outgoing geometry restarts only the debounce"
    - "User-scope systemd behavioural test whose stand-in process models the real dependency's exit-on-EIO"

key-files:
  created: []
  modified:
    - src/jabuka/nav/course.py
    - tests/nav/test_course.py
    - src/jabuka/ingest/rawlog.py
    - tests/test_background_durability.py
    - tests/deploy/test_units.py

key-decisions:
  - "CR-01: the rounding evidence (entry, latch, near, suppressed zone) is keyed by _fsm_geometry = (idx, mark, radius, previous pos, active pos); the side and the next mark (_fsm_outgoing) only restart the 10 s debounce. Active/previous/radius edits still reset (R6); a rename resets nothing"
  - "WR-01: after Annuler inside the zone of a normal mark, leaving that zone stands in for 'came near' (_near), not for the latch, so the exit must be past the mark along either leg; at a hairpin or without an outgoing leg it still stands in for the latch (CR-02 unchanged there)"
  - "WR-02 accepted as false-advance residual R9 (banner + Annuler): no measured candidate both keeps stuck = 0 and lowers the false advances; the approach-quadrant rule is the post-race candidate"
  - "Accepted residuals after 04-14: stuck R2-R8 (crew: Carte → « Suiv. »), false advance R1/R9 (crew: Annuler / « Préc. »); R3 now also covers a normal mark turned into a hairpin by an in-zone edit; R8 is new (big next-mark change while sailing the old leg, mark off the buoy)"
  - "IN-02: a pre-queue fsync failure waits for fsync_s before the retry (one ERROR line per fsync_s instead of per second); IN-01 stays advisory"

patterns-established:
  - "Outgoing-edit grid (rounding x edit kind x GPS noise) as permanent parametrised tests for course-edit/rounding interactions"

requirements-completed: []

coverage:
  - id: D1
    description: "An outgoing edit in the zone after the rounding (next mark nudged 1 m or moved 10 deg in, added at the default position, deleted, side changed) keeps the evidence: exact tight roundings and committee marks up to 0.09 nm off advance exactly once, noiseless and with 3 m GPS noise (CR-01)"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_an_outgoing_edit_in_the_zone_after_the_rounding_still_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_after_a_big_next_mark_change_steering_to_the_new_mark_advances"
        status: pass
    human_judgment: false
  - id: D2
    description: "Residuals R3-by-edit and R8 stay stuck and « Suiv. » moves on; incoming/active/radius edits still restart the evidence; a rename does not (R6, 04-13 tests unchanged)"
    requirement: CRSE-02
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_an_edit_that_makes_an_off_buoy_mark_a_hairpin_needs_a_manual_next"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_a_big_next_mark_change_while_sailing_the_old_leg_needs_a_manual_next"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_a_geometry_edit_restarts_the_rounding_debounce"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_a_rename_keeps_the_rounding_debounce"
        status: pass
    human_judgment: false
  - id: D3
    description: "Annuler in the zone at a normal mark then an approach-side retreat never re-advances (Plić; committee at 45/60/90 deg); leaving past the mark along the next leg still advances (CR-02); hairpin Annuler unchanged (WR-01)"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_annuler_in_the_zone_then_an_approach_side_retreat_never_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_annuler_in_the_zone_at_a_committee_mark_then_an_approach_side_retreat_never_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_annuler_in_the_zone_then_leaving_past_the_mark_along_the_next_leg_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_hairpin_annuler_then_real_rounding_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_undo_restores_and_suppresses_until_exit"
        status: pass
    human_judgment: false
  - id: D4
    description: "WR-02 accepted false advance R9 is pinned"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances"
        status: pass
    human_judgment: false
  - id: D5
    description: "Plan B survives one kill -9 of the relay with a stand-in that exits 1 on relay loss like fastnet2ip 3.3.1 (both active, NRestarts >= 1, new Plan B PID), on the laptop's user systemd 260 (WR-03)"
    requirement: REL-02
    verification:
      - kind: integration
        ref: "tests/deploy/test_units.py#test_one_relay_crash_keeps_plan_b_up"
        status: pass
    human_judgment: false
  - id: D6
    description: "A failed pre-queue fsync retries on the fsync_s cadence (IN-02); the 04-13 WR-03 recovery still holds"
    requirement: REL-01
    verification:
      - kind: unit
        ref: "tests/test_background_durability.py#test_a_failed_submit_retries_on_the_fsync_cadence"
        status: pass
      - kind: unit
        ref: "tests/test_background_durability.py#test_cadence_fsync_recovers_after_a_failed_submit"
        status: pass
    human_judgment: false
  - id: D7
    description: "On-boat course-change rounding check and the Pi system-scope Plan B check with NRestarts and NMEA on UDP 2002"
    verification: []
    human_judgment: true
    rationale: "A real GPS track at a real buoy and the Pi's system-scope systemd are outside the automated gate (Human Items)"

duration: 31min
completed: 2026-11-09
status: complete
---

# Phase 04 Plan 14: CR-01 key split, WR-01 Annuler stand-in, WR-02 as R9, WR-03 Plan B fidelity, IN-02 Summary

**The rounding evidence is now keyed only by the incoming leg, the active mark and its radius. An edit of the side or of the next mark (moved, added at the default position, deleted) right after a rounding restarts only the 10 s debounce, so the course no longer stays stuck on the mark just rounded: 140/140 outgoing-edit cases advance once. Annuler in the zone of a normal mark can no longer re-advance on an approach-side retreat. WR-02 is an accepted, pinned residual (R9). The Plan B single-crash test now models fastnet2ip's exit on relay loss, and a lasting pre-queue fsync failure logs once per fsync_s. New src/jabuka fingerprint f4a6fa25…9cc8 (147 files).**

## Performance

- Started 2026-11-09T15:25:51Z. The code commits ran from cafa90f to 06d81dd, followed by the full gate (about 23 min, 3.14 then 3.13). Wall time: 31 min (15:25:51Z to 15:56:26Z).
- 3 tasks, 6 commits (3 RED, 3 GREEN), 5 files changed. Measured diff: 443 insertions and 42 deletions, about 20.3 k characters.

## Gaps closed

| Id | Disposition | Fix | Commits |
|---|---|---|---|
| CR-01 (blocker) | Fixed | `_fsm_geometry` = (idx, mark, radius, previous pos, active pos) resets the evidence. `_fsm_outgoing` = (side, next pos) restarts only `_cand_since`. The suppress block re-stores `_fsm_out` | cafa90f (RED), ee9371c |
| WR-01 (advisory) | Fixed | The CR-02 `left_this_zone` sets `_entered` and `_near`, and sets `_beyond` only when `_leg_dots` is None, its turn is None, or abs(turn) > HAIRPIN_DEG | 3b0d6ba (RED), 029f655 |
| WR-02 (advisory) | Accepted residual R9, pinned | No code change (see the evidence table) | 3b0d6ba |
| WR-03 (advisory) | Fixed (test fidelity) | The Plan B stand-in exits 1 once the relay's PID is gone. The test asserts both units active, NRestarts >= 1 on both, and a new Plan B MainPID | f2bfea6 |
| IN-02 (info) | Fixed | `_cadence` sets `_last_fsync = now` on the pre-queue failure path | f2bfea6 (RED), 06d81dd |
| IN-01 (info) | Advisory, not done | Changing `STOPPING=1` semantics under `Restart=always` + `WatchdogSec` would need its own systemd test. The outcome is the same either way (a restart) | — |

## WR-02: decision with evidence (accepted residual R9)

This is the planner's measurement, done by monkeypatch on top of the CR-01 split and the WR-01 fix. The baseline row was re-run on the committed tree (see "Scratch grid outputs").

| Candidate | WR-02 tracks (verifier `wr02`: Plić / committee, tack-away at 0.28 / 0.2 / 0.1 nm, 3 m noise, 20 seeds each) | Reviewer repro D | Stuck roundings | Verdict |
|---|---|---|---|---|
| none (this plan) | 20/20 on all six | advances | breakdown 118/1152 (all R3 by edit), exact-edit 0/1728 | baseline |
| latch needs 2 consecutive fixes | 20, 20, 20, 18, 20, 20 /20 | no advance | — | no real drop: noise on the line gives runs |
| latch needs 3 consecutive fixes | 20, 20, 20, 12, 20, 20 /20 | no advance | — | same |
| latch only inside the zone (review) | verifier: D still advances | advances | — | does not fix |
| latch margin 0.008 nm (verifier) | clears WR-02 | — | 139/1152 stuck | trades stuck for false advances |
| approach-quadrant rule (`dot_in > 0 or (dot_out > 0 and (_beyond or _near))` at normal marks) | 0/20 on all six | no advance | same outcomes on the 1152 breakdown, 1728 exact, 1920 lateral and 360 verify_cr01 runs, **but** 19/92 stuck on a new grid (exact tight rounding at 0.005 nm, next mark moved 60-150 deg in the zone, boat keeps its heading; with the split only: 0/92). The inside-of-the-turn variant is still 20/20 | rejected: trades a stuck course for fewer false advances |

WR-02 therefore stays an accepted false-advance residual (R9). The crew fallback is the 60 s banner and Annuler. The approach-quadrant rule is the candidate for after the race.

## Accepted residuals after this plan (R1-R9)

None of these is fixed before the freeze.
- **Stuck (R2-R8):** the rounded mark stays active, its bearing points back and the distance grows. Crew fallback: Carte → « Suiv. » (`CourseStore.next()`, the `course-next` button).
- **False advance (R1, R9):** crew fallback: « Annuler » on the 60 s banner, or Carte → « Préc. ».

| # | Case | Why accepted | Crew fallback | Pinned by |
|---|---|---|---|---|
| R1 | (false advance) The boat comes near a normal mark (within radius + 0.1 nm) on the approach side, then leaves on the inside of the turn | It cannot be told apart from rounding a mark entered up to 0.1 nm off (04-13) | Annuler / « Préc. » | test_inside_of_the_turn_exit_after_coming_near_advances |
| R2 | A normal mark entered so far beyond the buoy that the boat never comes within radius + MARK_TOL_NM (measured over 0.15 nm) | A wider tolerance would eat the G-4-R02 band (04-13) | « Suiv. » | test_committee_mark_beyond_the_bound_needs_a_manual_next |
| R3 | A hairpin mark (turn > 90 deg) entered beyond the buoy along the incoming leg. **Now also covers** a normal mark that becomes a hairpin through an in-zone edit of the next mark (a 90 deg turn nudged, or a new next mark 10 deg further round at 85-90 deg: 118/1152 in the breakdown grid), or through a lateral entry error that tips the turn over 90 deg (36/1920 in the lateral grid, same on HEAD) | The near term at a hairpin would reopen G-4-R02 at Jabuka | « Suiv. » | test_committee_mark_beyond_the_bound_needs_a_manual_next (turn 150) + test_an_edit_that_makes_an_off_buoy_mark_a_hairpin_needs_a_manual_next |
| R4 | The track never enters the zone | Pre-existing zone design | Set the leg radius; « Suiv. » | existing design |
| R5 | No usable fix from the zone exit out to 2 nm | Pre-existing debounce/gate | « Suiv. » once PAS DE GPS clears | existing design |
| R6 | **Narrowed.** Any of these edits, made after the rounding and before the advance, in the zone or after it: moving the active mark, changing its radius, or changing its previous mark. That includes a leg inserted, deleted or reordered before it (index shift), and a select() A<->B that gives it a different previous mark. Edits of the side or of the next mark are no longer in R6 (CR-01) | The evidence was measured against the old incoming leg, mark or radius, so the corrected mark must be rounded again | « Suiv. » | 04-13 WR-01 tests (moved hairpin, brief abeam move, radius shrink, previous_moved) |
| R7 | Annuler on a correct advance once the boat is already outside the zone | Pre-existing CR-02 rule | « Suiv. » | test_undo_outside_the_zone_needs_a_fresh_entry |
| R8 | **New.** A mark entered off the buoy (no latch). The crew moves the next mark by 60 deg or more while still in the zone after the rounding, and the boat keeps sailing the old leg. There is no advance until the boat is past the mark along the NEW next leg. A boat that steers to the new next mark advances (0/92 stuck). One that keeps the old leg for 2 nm needs « Suiv. » (28/92 stuck with a 0.05 nm error). Under HEAD the same edit wiped everything (CR-01) | By the new outgoing leg, the boat is on the approach side | Steer to the new mark; otherwise « Suiv. » | test_a_big_next_mark_change_while_sailing_the_old_leg_needs_a_manual_next |
| R9 | **New, from WR-02.** (false advance) One fix past the abeam line after entering the zone (e.g. sailing along a layline that is the abeam line), then a zone exit, including on the approach side, advances | No fix keeps stuck = 0 and lowers it (table above) | Annuler / « Préc. » | test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances |

## TDD evidence (RED outputs)

| Task | RED commit | RED result on the tree before the fix | GREEN commit | GREEN result |
|---|---|---|---|---|
| 1 (tracer) | cafa90f | `140 failed, 96 passed` on f96025b. All 140 failures are the outgoing-edit grid (`assert (None is not None)`: the course stays stuck). The R3/R8 pins and the steer-to guard pass, as specified | ee9371c | tests/nav/test_course.py 236 passed on 3.14 and 3.13; tests/nav + sim + web 556 passed |
| 2 | 3b0d6ba | `4 failed, 240 passed` on ee9371c: the Plić test and the three committee approach-side tests (a second course_advance) | 029f655 | test_course.py 244 passed on both venvs; tests/nav + sim + web 564 passed |
| 3 | f2bfea6 | `2 failed, 32 passed` (tests/deploy/test_units.py + tests/test_background_durability.py) on 029f655: test_a_failed_submit_retries_on_the_fsync_cadence[dup/submit] (`['jabuka-durable']`, an fsync 2 s after the failure). The rewritten single-crash test passes | 06d81dd | 107 passed on both venvs (tests/deploy, durability, full-disk, atomicio, no-wallclock) |

Tracer gate (Task 1): the `<verify>` ran end-to-end after ee9371c and passed (both venvs, tests/nav/sim/web, ruff check and format on src and tests) before Task 2 started.

## test_one_relay_crash_keeps_plan_b_up

- Precondition met: `systemctl --user is-system-running` printed `degraded`, and XDG_RUNTIME_DIR is set.
- **PASSED on both venvs** (3.14 and 3.13, about 10 s each) on the laptop's user systemd 260.
- After each run, `systemctl --user list-units --all --no-legend 'jabuka-wr06-*'` lists 0 units.
- `git diff f96025b -- deploy/systemd` is empty: no unit changed.

## Scratch grid outputs (Task 2 step 3, NOPATCH=1 on the committed tree 029f655)

The planner's scratch directory p0414/ was still present. Each grid ran with `/home/drico/git/jabuka/.venv/bin/python`. patch0414.py was never imported.

`grids.py post.json all`:
```
breakdown add_default|0.0 stuck 0/96 multi 0
breakdown add_default|0.011 stuck 19/96 multi 0
breakdown add_default|0.05 stuck 36/96 multi 0
breakdown add_default|0.09 stuck 36/96 multi 0
breakdown none|0.0 stuck 0/96 multi 0
breakdown none|0.011 stuck 0/96 multi 0
breakdown none|0.05 stuck 0/96 multi 0
breakdown none|0.09 stuck 0/96 multi 0
breakdown nudge_next_1m|0.0 stuck 0/96 multi 0
breakdown nudge_next_1m|0.011 stuck 3/96 multi 0
breakdown nudge_next_1m|0.05 stuck 12/96 multi 0
breakdown nudge_next_1m|0.09 stuck 12/96 multi 0
breakdown total stuck 118 / 1152 multi 0
exact-mark edit grid: stuck 0/1728, multi-advance 0
wr wr01_plic (1, 1)
wr wr01_committee_45 (1, 1, 0.32)
wr wr01_committee_in_zone_45 (1, 1)
wr wr01_committee_60 (1, 1, 0.32)
wr wr01_committee_in_zone_60 (1, 1)
wr wr01_committee_90 (1, 1, 0.32)
wr wr01_committee_in_zone_90 (2, 2)
wr wr02_plic_0.28 20/20 advanced
wr wr02_plic_0.2 20/20 advanced
wr wr02_plic_0.1 20/20 advanced
wr wr02_committee_0.28 20/20 advanced
wr wr02_committee_0.2 20/20 advanced
wr wr02_committee_0.1 20/20 advanced
fsm_probe A 60 45 60 0.16 (2, 1, 1.5)
fsm_probe A 60 45 120 0.16 (2, 1, 1.5)
fsm_probe A 75 45 75 0.2 (2, 1, 1.5)
fsm_probe A 60 45 0 0.16 (2, 1, 1.5)
fsm_probe A 60 45 30 0.16 (2, 1, 1.5)
fsm_probe A 89 45 89 0.2 (2, 1, 1.5)
fsm_probe B (1, 1)
fsm_probe B2 (1, 1)
fsm_probe D (160.72759748320058, 2, 1)
```
`lateral.py post_lateral.json`: `lateral grid: stuck 36/1920 multi 0`.

`nextchange.py x` with R=0.005 and with R=0.01 (identical output): `{('H', 0.0): 0, ('H', 'n'): 92, ('H', 0.05): 28, ('T', 0.0): 0, ('T', 'n'): 92, ('T', 0.05): 0}`. The 28 stuck runs are all H at 0.05 nm (turn 60/75/45/89, delta -60 to -150, 2 seeds), which is R8.

Every number matches the plan's expectation:
- breakdown 118/1152: all add_default/nudge with err >= 0.011, so R3 by edit; no double advances;
- exact 0/1728;
- wr01_plic (1, 1);
- wr01 committee in-zone 45/60 (1, 1), and 90 (2, 2), the documented 90.000 deg boundary artifact;
- wr02 20/20 (R9);
- fsm_probe A all (2, 1, 1.5), B and B2 (1, 1), D advanced (R9);
- lateral 36/1920;
- nextchange H 0.05 = 28 (R8), every other cell 0.

## Acceptance checks

BASE = plan_head_before = f96025b61494f402e99e78c1d12e08504cc1e25a.
- course.py counts:
  - `_fsm_outgoing`: 3 (needed >= 2);
  - `self._fsm_out`: 6 (>= 5);
  - `_seq_pos`: 4 (>= 4);
  - `select()` in the `_fsm_geometry` docstring: 1;
  - `debounce` in the `_fsm_outgoing` docstring: 1;
  - `self._near = True` and `HAIRPIN_DEG` in the `if left_this_zone:` block: 1 each.
- The `_abeam` → `on_tick` span (`_abeam`, `_leg_dots`, `_past_mark`) is byte-identical to BASE (empty diff), checked after Task 1 and after Task 2.
- `git diff BASE -- tests/nav/test_course.py` and `git diff BASE -- tests/test_background_durability.py` have 0 removed lines. The only test lines removed or edited belong to the reviewer-requested rewrite of test_one_relay_crash_keeps_plan_b_up.
- tests/deploy/test_units.py:
  - `show(pname, "MainPID") == planb_pid`: 0;
  - `NRestarts`: 3 lines (>= 3);
  - `$$` escape: 4 lines (>= 1).
- `self._last_fsync = now` in rawlog.py: 4.
- `git diff BASE -- deploy/systemd` is empty. No web/, common/, i18n, docs or unit file changed.

## Gate (var/gate-04-14.log)

The log was removed first, then `(JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh; echo "EXIT=$?") > var/gate-04-14.log 2>&1` ran on HEAD 06d81dd:

```
bootstrap: ok
All checks passed!            (ruff check)
234 files already formatted   (ruff format --check)
3.14: 1885 passed, 4 skipped in 686.65s (0:11:26)
3.13: 1885 passed, 4 skipped in 682.05s (0:11:22)
check: ok
EXIT=0
```

1885 = 1722 (04-13) + 163 new tests (153 in Task 1, 8 in Task 2, 2 in Task 3; the single-crash test was rewritten in place). The plan expected about 1857 for its 135 new tests; the 28 extra are the delete_next kind (see Deviations). The 4 skips are the same pre-existing ones as in 04-13. The 04-04 soak flake did not occur.

## New src/jabuka fingerprint

- **FINGERPRINT_SH** (`git archive HEAD src/jabuka`, HEAD 06d81dd = the last code commit of this plan): `f4a6fa25bdacf0555af57536fd4e96cd5b4a0b46ac935b05797c941bfccc9cc8`, **147 files**.
- Cross-check: `jabuka.soak.report.package_fingerprint(Path('src/jabuka'))` on the working tree (clean under src/jabuka) gives `{'sha256': 'f4a6fa25bdacf0555af57536fd4e96cd5b4a0b46ac935b05797c941bfccc9cc8', 'files': 147}`.
- It replaces `c6fb70b03329019122eb8dab3e6dffbd88d74ecaed793ddef777a691ec46a737` (147 files, 04-13, reported installed on the Pi).
- **The wheelhouse must be rebuilt and the Pi re-provisioned from this HEAD.** No unit file changed in this plan. The orchestrator or the owner does this; this plan did not.

## Deviations from Plan

**1. [Orchestrator advisory 2] Added a `delete_next` kind to the outgoing-edit grid.**
- **Found during:** Task 1.
- **Change:** the grid now has five kinds: nudge_next, move_next, add_default, side and delete_next. delete_next first adds a 4th leg "N2" right after "N" (helper `_after_next`, at turn - 10 deg, 3 nm), then deletes leg 2 in the zone after the rounding. The deletion of the next mark is now pinned by a test, not only claimed.
- **Effect on counts:** the grid has 14 × 5 × 2 = 140 cases instead of 112. RED was 140 failed instead of 112. tests/nav/test_course.py has 83 + 153 = 236 tests after Task 1 (plan: 208) and 244 after Task 2 (plan: 216). All 140 pass after the fix.
- **Files modified:** tests/nav/test_course.py.
- **Commit:** cafa90f.

**2. [Minor] `from collections.abc import Callable` added next to `import random`** for the helper annotations. No other existing line was touched.

There were no other deviations. BASE was fixed at the start to the literal f96025b61494f402e99e78c1d12e08504cc1e25a (orchestrator advisory 1).

## Known Stubs

None.

## Threat Flags

None. No new network, auth, file or schema surface. The Plan B test only creates PID-suffixed units in the runtime user unit directory and removes them in `finally` (T-04-14-08).

## Human Items (before the freeze 2026-11-11)

| Item | Due | Source |
|---|---|---|
| Rebuild the wheelhouse from the final HEAD and re-provision the Pi. The installed fingerprint must equal f4a6fa25…9cc8 (147 files), which replaces c6fb70b0…a737. Swap the PSU first (get_throttled 0x50005) | 2026-11-10 / 11 | 04-VERIFICATION human item 1 |
| Laptop race-36h soak and Pi system-scope soak on this HEAD (procedure unchanged) | 2026-11-10 / 11 | 04-VERIFICATION human items 2-3 |
| Plan B single-crash check on the Pi after re-provisioning (see below) | after re-provisioning | 04-VERIFICATION human item 6, review WR-03 |
| On the boat: a mark tapped about 50 m beyond a real buoy, rounded and left on a beat, advances with the Annuler banner. A tack away on the approach side, well outside the radius, keeps the mark. **New:** right after a rounding, add a new next mark at the default position (course-change drill) and steer to it. The course moves on | 12 Nov | CR-01 |
| Course card, by hand (no repo doc change before the freeze). See the three rules below | 13 Nov, course card | residuals R1-R9 |
| Diag: the Cœur and Fastnet tables show `bg_write_errors` 0 during the Pi soak and on board | Pi soak, 12 Nov | 04-13 |
| Delete or ignore the untracked docs/I18N-SL-REVIEW.md.bak before the freeze clean-tree check | freeze | 04-VERIFICATION anti-patterns |

Plan B single-crash check, run on the Pi:
1. `sudo systemctl start fastnet2ip; sudo kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 15; systemctl is-active fastnet2ip jabuka-fastnet-relay; systemctl show -p NRestarts fastnet2ip jabuka-fastnet-relay`
2. With the bus or a replay connected, run `timeout 15 nc -ul 2002 | head -3`. Run it on the laptop joined to the jabuka AP, or on the Pi if netcat is installed.

Expected: both units active. The relay shows NRestarts >= 1. fastnet2ip may show 1, because it exits on pty EIO and restarts. NMEA sentences arrive after the kill.

Course card rules:
- Enter committee marks from the committee's coordinates, as close to the real buoy as known.
- After changing the next mark right after a rounding, steer to the new mark. If the course has not moved on once you are past the rounded mark on the new leg (the bearing points back, the distance grows), use Carte → « Suiv. ».
- If you move the rounded mark itself after rounding it, use « Suiv. ».

## Next Phase Readiness

All 14 plans of phase 4 have a SUMMARY. Next: re-verify phase 4 (CR-01 closed; WR-01/WR-03/IN-02 closed; WR-02 = R9), then the freeze, the wheelhouse rebuild and Pi re-provisioning, and the Human Items above.

## Self-Check: PASSED

- All 5 modified files and var/gate-04-14.log exist.
- Commits cafa90f, ee9371c, 3b0d6ba, 029f655, f2bfea6 and 06d81dd are in `git log`. Measured: `git rev-list --count f96025b..06d81dd` = 6.
- The gate log ends with `check: ok` / `EXIT=0`.
- The fingerprint was cross-checked against package_fingerprint.
