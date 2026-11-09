---
phase: 04-race-readiness-hardening-commissioning
plan: 13
subsystem: nav
tags: [rounding, course, state-machine, durability, rawlog, ingest, systemd, plan-b, gap-closure, freeze]
gap_ids: [CR-01, WR-01, WR-02, WR-03, WR-06, WR-07]
plan_head_before: 1b9ae5735012796cc5cd5fedf0f754c0260b4a1c

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: 04-09 G-4-R02 zone-exit rule and _beyond latch, 04-10 durability thread (atomicio background mode), 04-08/G-4-R12 relay + fastnet2ip units
provides:
  - jabuka.nav.course.MARK_TOL_NM = 0.1 and the CourseStore._near latch
  - CourseStore._past_mark non-hairpin rule = _beyond or dot_in > 0 or (dot_out > 0 and _near)
  - CourseStore._fsm_geometry(idx) as the rounding state-machine key (WR-01)
  - RotatingAppendLog._cadence clears _fsync_inflight when fsync_fd raises before queueing
  - fastnet_main._run guarded raw-log close; drain + socket close always run
  - FastnetIngest.health()["bg_write_errors"]
  - jabuka-fastnet-relay.service RestartMode=direct
affects: [freeze 2026-11-11, wheelhouse rebuild, Pi re-provisioning, 04 re-verification, course card]

actuals:
  tokens: 6000
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Rounding evidence is keyed by the leg geometry it was measured against (any edit restarts the state machine)"
    - "Proximity latch (radius + MARK_TOL_NM) gates the outgoing-leg zone-exit term at normal marks"
    - "systemd RestartMode=direct on a unit that another unit BindsTo="

key-files:
  created: []
  modified:
    - src/jabuka/nav/course.py
    - tests/nav/test_course.py
    - src/jabuka/ingest/rawlog.py
    - src/jabuka/ingest/fastnet_main.py
    - tests/test_background_durability.py
    - tests/bus/test_ingest_resilience.py
    - deploy/systemd/jabuka-fastnet-relay.service
    - tests/deploy/test_units.py

key-decisions:
  - "CR-01: at a normal mark (turn <= 90 deg) a zone exit counts with the _beyond latch, or dot_in > 0 now, or dot_out > 0 now after coming within leg radius + MARK_TOL_NM (0.1 nm). The hairpin rule is unchanged. _abeam and _leg_dots are byte-identical"
  - "WR-01: the state-machine key is _fsm_geometry (index, mark, side, radius, previous/active/next mark positions). A rename keeps the state. A select() A<->B that changes the active mark's neighbours restarts it on purpose (residual R6)"
  - "Accepted no-auto-advance residuals R2-R7 have a one-tap crew fallback, Carte → « Suiv. ». R2 (0.2 nm) and R3 (hairpin, 0.05 nm) are pinned by a test"
  - "WR-02 Diag red alert line deferred (needs FR/EN/SL strings two days before the freeze); the counter shows in the Diag Fastnet table"
  - "Relay unit RestartMode=direct (systemd >= 254; Trixie 257); fastnet2ip.service unchanged"

patterns-established:
  - "User-scope systemd behavioural test: throwaway PID-suffixed units in $XDG_RUNTIME_DIR/systemd/user built from the shipped directives, cleaned up in finally"

requirements-completed: []

coverage:
  - id: D1
    description: "A committee mark entered up to 0.09 nm beyond the real buoy, and a tight rounding with a beat out, both advance exactly once (CR-01)"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_committee_mark_entered_beyond_the_buoy_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_tight_rounding_then_a_beat_out_advances"
        status: pass
    human_judgment: false
  - id: D2
    description: "Approach-side and inside-of-the-turn retreats never advance (G-4-R02 holds); residuals R1/R2/R3 are pinned, and « Suiv. » moves on from R2/R3"
    requirement: CRSE-03
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_inside_of_the_turn_retreat_never_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_inside_of_the_turn_exit_after_coming_near_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_committee_mark_beyond_the_bound_needs_a_manual_next"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_leaving_the_zone_on_the_approach_side_never_advances"
        status: pass
    human_judgment: false
  - id: D3
    description: "Geometry edits (active/previous/next mark moved, side, radius) restart the rounding state machine; a rename does not (WR-01)"
    requirement: CRSE-02
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_a_geometry_edit_restarts_the_rounding_debounce"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_moving_the_active_hairpin_mark_needs_the_corrected_mark_rounded"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_a_rename_keeps_the_rounding_debounce"
        status: pass
    human_judgment: false
  - id: D4
    description: "Ingest durability tail: failed cadence submit clears the in-flight flag (WR-03), shutdown drain and socket close survive a raw-log close error (WR-07), heartbeat exports bg_write_errors (WR-02 ingest)"
    requirement: REL-01
    verification:
      - kind: unit
        ref: "tests/test_background_durability.py#test_cadence_fsync_recovers_after_a_failed_submit"
        status: pass
      - kind: integration
        ref: "tests/test_background_durability.py#test_ingest_drains_even_if_the_raw_log_close_fails"
        status: pass
      - kind: unit
        ref: "tests/test_background_durability.py#test_ingest_health_exports_background_write_errors"
        status: pass
      - kind: unit
        ref: "tests/bus/test_ingest_resilience.py#test_heartbeat_payload_contract"
        status: pass
    human_judgment: false
  - id: D5
    description: "Plan B survives one kill -9 of the relay (WR-06), proven on the laptop's user-scope systemd 260"
    requirement: REL-02
    verification:
      - kind: integration
        ref: "tests/deploy/test_units.py#test_one_relay_crash_keeps_plan_b_up"
        status: pass
      - kind: unit
        ref: "tests/deploy/test_units.py#test_relay_unit"
        status: pass
    human_judgment: false
  - id: D6
    description: "On-boat behaviour of committee-mark roundings and the Plan B single-crash check on the Pi (system scope)"
    verification: []
    human_judgment: true
    rationale: "Real GPS track at a real buoy and the Pi's system-scope systemd are outside the automated gate (Human Items)"

duration: 31min
completed: 2026-11-09
status: complete
---

# Phase 04 Plan 13: Rounding CR-01/WR-01 and pre-freeze durability/Plan B fixes Summary

**Normal-mark zone exit now counts on the incoming-leg latch, on being past the mark now, or on leaving along the next leg after coming within radius + 0.1 nm. The state machine restarts on any leg geometry edit. Also in this plan: a stuck fsync flag, a skipped ingest drain, the missing ingest bg_write_errors counter and Plan B dying on one relay crash are fixed. Full gate green on 3.14 and 3.13 (1722 passed). The new src/jabuka fingerprint is c6fb70b0…**

## Performance

- **Duration:** 31 min
- **Started:** 2026-11-09T13:54:19Z
- **Completed:** 2026-11-09T14:25:22Z
- **Tasks:** 3 (all TDD: RED commit, then fix commit)
- **Files modified:** 8
- **plan_head_before:** 1b9ae5735012796cc5cd5fedf0f754c0260b4a1c

## Gaps closed

| Gap | Fix | Commit |
|---|---|---|
| CR-01 (blocker) | `_past_mark` non-hairpin: `_beyond or dot_in > 0 or (dot_out > 0 and _near)`, with `MARK_TOL_NM = 0.1` | 029f4c7 |
| WR-01 | `_fsm_geometry(idx)` is the state-machine key (index, mark, side, radius, previous/active/next positions) | 029f4c7 |
| WR-03 | `_cadence` clears `_fsync_inflight` and re-raises when `fsync_fd` raises before queueing | df256a1 |
| WR-07 | `_run` finally: `rawlog.close()` in try/except (`log.exception`). The `disable_background(20.0)` drain and `sock.close()` run in its finally | df256a1 |
| WR-02 (ingest part) | `FastnetIngest.health()["bg_write_errors"]` | df256a1 |
| WR-06 | `RestartMode=direct` on jabuka-fastnet-relay.service | 0ca639c |

An A<->B `select()` that keeps the active mark but changes its previous or next mark restarts the rounding state machine on purpose. The latch and near evidence were measured against the old incoming and outgoing legs (direction, turn, hairpin or not). The `_fsm_geometry` docstring states this. If the boat has already left the zone, the crew uses « Suiv. » (R6).

## Accepted residuals: every known case where a real rounding does not auto-advance (plus R1)

None of these is fixed before the freeze. Each has the same one-tap crew fallback once the buoy is rounded: Carte tab → « Suiv. » (`CourseStore.next()`, the `course-next` button). In R2-R7 the rounded mark stays active: its bearing points back and the distance grows. R1 is the opposite case (a false advance), listed for completeness.

| # | Case | Why it is accepted | Crew fallback | Pinned by |
|---|---|---|---|---|
| R1 | (false advance) The boat comes near a normal mark on the approach side, then leaves on the inside of the turn | Cannot be told apart from rounding a mark entered up to 0.1 nm off | « Annuler » on the banner within 60 s, or Carte → « Préc. » | test_inside_of_the_turn_exit_after_coming_near_advances |
| R2 | A normal mark (turn <= 90 deg) entered so far beyond the real buoy that the boat never comes within leg radius + MARK_TOL_NM of the entered point. Claimed bound about 0.1 nm; measured over 0.15 nm with the default radius | A wider MARK_TOL_NM eats the 0.15 nm band where an approach-side retreat never advances | Carte → « Suiv. » | test_committee_mark_beyond_the_bound_needs_a_manual_next (0.2 nm, 45+50 and 90+45) |
| R3 | A hairpin mark (turn > 90 deg) entered beyond the real buoy along the incoming leg by more than the rounding distance. The built-in Jabuka is not affected | The near term at a hairpin would reopen G-4-R02 at Jabuka | Carte → « Suiv. » | the same test (turn 150, 0.05 nm) |
| R4 | The track never enters the zone (leg radius + 0.25 nm), e.g. an island rounded wider than its zone, or a mark entered more than about 0.3 nm off | Pre-existing zone-entry design | Set the leg radius to the planned rounding distance (COMMISSIONING §7 13:00); otherwise « Suiv. » | existing design |
| R5 | No usable fix (gaps over FSM_GAP_S) from the zone exit until the boat is more than 2 nm from the mark | Pre-existing debounce and gate (IN-05) | « Suiv. » once PAS DE GPS clears | existing design |
| R6 | A geometry edit, or a select() A<->B that changes the active mark's previous or next mark, after the zone exit and before the 10 s debounce ends | Intended: the evidence was measured against the old legs | « Suiv. » | WR-01 tests |
| R7 | « Annuler » tapped on a correct advance once the boat is already outside the zone | Pre-existing CR-02 rule | « Suiv. » | test_undo_outside_the_zone_needs_a_fresh_entry |

## Deferred / accepted advisories

| Finding | Decision | Rationale |
|---|---|---|
| WR-02 Diag red alert line and helm alert | Deferred | It needs new FR/EN/SL strings, a regenerated SL review sheet and a proofreading round two days before the freeze. Both counters are now visible in the Diag tables. Full or read-only disks still fail synchronously with the existing alert |
| WR-03 reset in `_open()` | Not done | Once a job is queued, its `finally` always runs `on_done` |
| WR-04 night fg/dim floor | Advisory | Needs the night check on the real tablet. Stale states keep their text cue |
| WR-05 MANUEL wind of unknown age is never stale | Advisory | Changes the meaning of a helm cue. Narrow window. The "MANUEL âge ?" badge stays |
| IN-02 `_abeam`/`_leg_dots` duplication | Not done | Kept byte-identical as a gate of this change |
| IN-01, IN-03, IN-04 | Not done | Info level, out of scope |

## TDD evidence (RED outputs)

- **Task 1 (bb4c6e9):** 37 failed, 46 passed in tests/nav/test_course.py on HEAD:
  - all 25 committee-mark cases;
  - tight roundings 75/85/89 deg at 0.005 nm (3);
  - the near-exit residual (3);
  - the moved hairpin mark (1);
  - the geometry-edit debounce for all 5 kinds.

  The guards passed on HEAD as planned: the residual pins, the inside-of-the-turn retreats, the brief-abeam move and the radius shrink.
- **Task 1 GREEN (029f4c7):** 83 passed on both venvs. tests/nav + tests/sim + tests/web: 403 passed on both.
- **Task 2 (c2c4cac):** 6 failed, 23 passed:
  - 2 WR-03 cases (0 worker fsyncs);
  - WR-07 (OSError EIO escaped `_run`);
  - WR-02 (KeyError);
  - test_heartbeat_payload_contract and test_silent_bus_heartbeats_at_1hz_and_core_shows_silent (the new HEALTH_KEYS).

  After df256a1: 47 passed on both venvs.
- **Task 3 (dd32d67):** 2 failed, 69 passed in tests/deploy. RestartMode was missing, and after one kill -9 Plan B was no longer active while the relay sat in `activating` (auto-restart). After 0ca639c: 71 passed on both venvs.

**Single-crash test (test_one_relay_crash_keeps_plan_b_up):** it passed on both venvs (`.venv` 3.14 and `.venv313` 3.13) against the laptop's user manager (systemd 260, state `degraded`, XDG_RUNTIME_DIR=/run/user/1000). It also ran, not skipped, inside the gate: the gate still shows the same 4 skips as 04-12. No `jabuka-wr06-*` unit was left behind (`systemctl --user list-units --all 'jabuka-wr06-*'` returns 0 lines).

**Scratch repro scripts:** the planner's scratchpad directories (cr01plan/, cr01rev/) no longer existed, so there are no stuck counts to report. The committed parametrized tests cover the same tracks.

## Acceptance checks

- `MARK_TOL_NM` appears 6 times in course.py, `self._near` 5 times, `_fsm_geometry` 3 times, and `select()` is in the `_fsm_geometry` docstring.
- The `_abeam` → `_past_mark` span is byte-identical to plan_head_before (diff exit 0). No existing test line was removed or edited (0 `-` lines).
- rawlog.py has 3 `_fsync_inflight = False`. fastnet_main.py has `bg_write_errors` and `atomicio.disable_background(20.0)`. `git diff BASE -- src/jabuka/web src/jabuka/common` is empty.
- The relay unit has exactly one `RestartMode=direct` line. `git diff BASE -- deploy/systemd/fastnet2ip.service` is empty.

## Gate (var/gate-04-13.log)

The gate ran `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh` on HEAD 0ca639c:

```
ruff check: All checks passed!
3.14: 1722 passed, 4 skipped in 674.35s (0:11:14)
3.13: 1722 passed, 4 skipped in 667.41s (0:11:07)
check: ok
EXIT=0
```

That is 1670 + 52 new tests. The 4 skips are the same pre-existing ones as in var/gate-04-12.log.

## New src/jabuka fingerprint

- **FINGERPRINT_SH** (`git archive HEAD src/jabuka`, HEAD 0ca639c8b86726448a6e767549c05a9199cad599): `c6fb70b03329019122eb8dab3e6dffbd88d74ecaed793ddef777a691ec46a737`, **147 files**.
- Cross-check: `jabuka.soak.report.package_fingerprint(Path('src/jabuka'))` on the working tree, which is clean under src/jabuka, gives the same sha256 and 147 files.
- It replaces `c1bab550c801a27f878ac9c34414761e3403e218bc52d1b7913d20b1f00dba30`, the fingerprint installed on the Pi today.
- **The wheelhouse must be rebuilt and the Pi re-provisioned from this HEAD.** The units are included because jabuka-fastnet-relay.service changed. The orchestrator or the owner does this; this plan did not.

## Deviations from Plan

None. The plan was executed exactly as written. One addition: test_silent_bus_heartbeats_at_1hz_and_core_shows_silent also went RED with the new HEALTH_KEYS. It asserts HEALTH_KEYS against the core's forwarded health, and it went green with the ingest fix without being edited.

## Known Stubs

None.

## Human Items (before the freeze 2026-11-11)

- Rebuild the wheelhouse from this HEAD and re-provision the Pi. The installed fingerprint must equal c6fb70b0…a737. Swap the PSU first (get_throttled 0x50005).
- Run the laptop race-36h soak and the Pi system-scope soak on this HEAD.
- Plan B single-crash check on the Pi, after re-provisioning: `sudo systemctl start fastnet2ip; sudo kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 10; systemctl is-active fastnet2ip jabuka-fastnet-relay`. Both must be active.
- On the boat (12 Nov), two checks:
  - A mark tapped about 50 m beyond a real buoy, rounded and left on a beat, advances with the Annuler banner.
  - A tack away on the approach side, well outside the mark's radius, keeps the mark.
- Course card (by hand):
  - Enter committee marks from the committee's coordinates, as close to the real buoy as known.
  - If the course does not move on after a rounding (bearing points back, distance grows), use Carte → « Suiv. ».
- Diag: `bg_write_errors` shows 0 in the Cœur and Fastnet tables during the Pi soak.
- Delete or ignore the untracked docs/I18N-SL-REVIEW.md.bak before the freeze clean-tree check.

## Next Phase Readiness

All 13 plans of phase 4 have a SUMMARY. Next: re-verify phase 4 (CR-01 closed), then the freeze and the Human Items above.

## Self-Check: PASSED

- All 8 modified files exist.
- Commits bb4c6e9, 029f4c7, c2c4cac, df256a1, dd32d67 and 0ca639c are in `git log`.
- The gate log ends with `check: ok` / `EXIT=0`.
- The fingerprint was cross-checked.
