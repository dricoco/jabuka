---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-09T17:35:00Z
status: human_needed
score: 103/107 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-09-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-09-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-10-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-10-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-11-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-11-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-12-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-12-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-13-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-13-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-14-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-14-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-15-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-15-SUMMARY.md", "deploy/systemd/fastnet2ip.service", "deploy/systemd/jabuka-core.service", "deploy/systemd/jabuka-fastnet-relay.service", "docs/COMMISSIONING.md", "docs/I18N-SL-REVIEW.md", "docs/ROUTING.md", "docs/TABLET-SETUP.md", "src/jabuka/common/atomicio.py", "src/jabuka/core/main.py", "src/jabuka/ingest/fastnet_main.py", "src/jabuka/ingest/rawlog.py", "src/jabuka/nav/course.py", "src/jabuka/nav/polar.py", "src/jabuka/route/pool.py", "src/jabuka/route/pool_probe.py", "src/jabuka/web/static/app.css", "src/jabuka/web/static/app.js", "src/jabuka/web/static/diag-theme.js", "src/jabuka/web/static/diag.css", "src/jabuka/web/static/diag.html", "src/jabuka/web/static/diag.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/i18n.js", "src/jabuka/web/static/lock.js", "src/jabuka/web/static/lock_logic.js", "src/jabuka/web/static/route_logic.js", "tests/bus/test_ingest_resilience.py", "tests/deploy/test_units.py", "tests/nav/test_course.py", "tests/nav/test_polar_vmg.py", "tests/nav/test_wind.py", "tests/route/test_pool.py", "tests/test_background_durability.py", "tests/test_helm_logic.py", "tests/test_lock_logic.py", "tests/test_route_logic.py", "tests/ui/test_helm.py", "tests/ui/test_helm_column.py", "tests/ui/test_i18n_ui.py", "tests/ui/test_lock_wake.py", "tests/ui/test_night.py", "tests/ui/test_route_ui.py", "tests/ui/test_tablet_hardening.py"]
covered_digest: "v1:sha256:a94e8429a8755923e93d5a35674307edce10c307efcfb1d131a4e9f3bb9e3739"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 87/92
  gaps_closed:
    - "Previous gaps[0] (04-13 truth 13-2; CR-01 of review 93cb8b3): an edit of the next mark / side / add_mark at the default position / delete of the next mark while the boat is still in the zone after the rounding no longer resets the evidence. course.py:656-678 splits the key (_fsm_geometry = idx, mark, radius, previous pos, active pos; _fsm_outgoing = side, next pos -> only _cand_since cleared, :816-824). My independent grid on HEAD (committee mark, turn 45/60/75/89, tack 0/45, error 0/0.011/0.05/0.09 nm, radius 0.005/0.01/0.02 nm, 9 edit kinds, edit at 0.08/0.16/0.22/0.28 nm, 3 m noise, 2 seeds; 6912 runs): 0 stuck, 0 double advance. The previous verification's 96/96 stuck cells now advance"
    - "Review ccbbdc2 CR-01 (found after 04-14): an edit that nulled suppress_idx after Annuler while the boat was still in the zone left the course stuck. Fixed by CourseStore._carry_suppress in _commit (course.py:312-340). My Annuler-then-edit grid (same 6912-run shape, early in-zone abeam advance + Annuler + the real rounding while suppressed): HEAD 0 stuck, every run exactly 2 course_advance; the same grid on the 2ebbd25 source (before 04-15): 294/768 stuck for each of add_default, add_end, delete_next, finish_later, activate_same, reorder_later (so the probe discriminates). Carried suppression survives a store restart (6/6 Jabuka edit kinds: suppress_idx 2 after reload, then one advance)"
    - "Previous advisory WR-01 (Annuler in the zone re-advances on an approach-side retreat): fixed for retreats on the outside of the turn (04-14, course.py:843-856); the inside-of-the-turn remainder is accepted residual R10 (owner delegate), pinned"
    - "Previous advisory WR-02 (one-sample latch): accepted residual R9 (owner delegate), pinned by test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances"
    - "Previous advisory WR-03 (Plan B test stand-in sleep infinity): the stand-in now exits 1 when the relay PID disappears; test asserts both active, NRestarts >= 1 on both, new Plan B MainPID. Ran here on user systemd: pass, 0 throwaway units left"
    - "Previous advisory IN-02 (pre-queue fsync failure logs every second): rawlog.py advances _last_fsync on that path; test_a_failed_submit_retries_on_the_fsync_cadence passes"
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
advisory:
  - finding: "Accepted false-advance residuals R1, R9, R10 and stuck residuals R2-R8 (04-15-SUMMARY table). R10 (new): after Annuler in the zone of a normal mark, a zone exit on the inside of the turn advances although the boat never came within radius + MARK_TOL_NM"
    category: other
    reason: "Owner rule (via the delegate): never trade a stuck course for fewer false advances; documented, test-pinned, each with a crew fallback (Annuler / « Préc. » for false advances, « Suiv. » for stuck). R10 pin also proves the fallback does not loop (second Annuler outside the zone, no third advance). Not a gap; the fallbacks must be on the hand-written course card (human item)"
    evidence_status: "pins pass on 3.14 and 3.13 (tests/nav/test_course.py 274 passed x2, run here)"
  - finding: "Review 04-15 IN-01: a kept edit that changes the incoming leg (reorder of two legs before the active one, no index shift) keeps suppress_idx but the key change clears _suppressed_in_zone; if the zone exit happens in the same second as the edit, a fresh entry is needed. The _carry_suppress docstring says the stand-in is kept unconditionally, and the R6 row omits this"
    category: other
    reason: "R6 class with the « Suiv. » fallback; one-second window; was already stuck before 04-15; no template switch reaches it. Doc-only fix after the race"
    evidence_status: "reviewer probe; code read confirms (course.py:816-819 reset on key change, :831 left_this_zone)"
  - finding: "Review 04-15 IN-02: the banner-drop list in the module and _fsm_outgoing docstrings names add_mark/delete_leg/reorder only; select(), set_finish(idx > active), set_finish(None) and activate(active) also drop the banner. The _carry_suppress docstring omits 'a delete of later legs that leaves the active leg the last one' as a clear case"
    category: other
    reason: "Comment-only; the guard is right (code read, course.py:329-331). The course-card rule 'an edit inside the 60 s banner window removes Annuler; use « Préc. »' is general and covers the crew"
    evidence_status: "code read"
  - finding: "04-14 boundary note: a retreat exactly along the extension of the incoming leg at a turn of exactly 90.000 deg gives dot_out = +6e-17 and advances after Annuler"
    category: other
    reason: "Float boundary only reachable by a noiseless synthetic track; now also inside the R10 class"
    evidence_status: "04-14-SUMMARY scratch grid wr01_committee_in_zone_90 (2, 2)"
  - finding: "Carried, deferred: 04-14 IN-01 (ingest crash-path drain can outlast WatchdogSec), earlier WR-02 Diag red alert line, WR-04 night fg/dim floor, WR-05 unknown-age MANUEL, IN-01..IN-04 of earlier rounds, 04-08 WR-01/IN-01/IN-03/WR-04, '.bak restauré' wording; untracked docs/I18N-SL-REVIEW.md.bak"
    category: other
    reason: "Untouched since the previous verification: git diff 6019d70..HEAD outside .planning touches only course.py, rawlog.py and three test files; same classification"
    evidence_status: "git diff --name-only 6019d70 HEAD"
behavior_unverified_items: []
coincidental_reliance_items: []
human_verification:
  - test: "Swap the Pi PSU (vcgencmd get_throttled = 0x50005 today), then confirm the installed code identity: on the Pi, the installed package fingerprint must equal HEAD's 8b0a3bc46c45900632b975c164a215dd8207a8c883a5b50f4470c705358f19c8 (147 files, recomputed by me with package_fingerprint(src/jabuka) on a clean tree). The orchestrator reports the Pi was re-provisioned today from this HEAD with that fingerprint, services active, watchdog armed (15 s), relay unit RestartMode=direct; not re-checked by me. If any src/jabuka commit lands before the freeze, rebuild the wheelhouse and re-provision again"
    expected: "Installed fingerprint = HEAD; vcgencmd get_throttled = 0x0 after a run under load"
    why_human: "Physical PSU swap and Pi access"
  - test: "Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length, no Ctrl-C"
    expected: "PASS, exit 0, end_signal null, duration_s 129600, scenario_sha256 of HEAD; freeze-check F3 PASS"
    why_human: "About 40 min of wall time on the final HEAD"
  - test: "Pi 3B system-scope soak (ROADMAP SC1) in tmux, after the PSU swap: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`; scp the run dir, reboot, `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0"
    expected: "Exit 0, PASS, journal.complete true, tick ratio >= 0.95, core/worker RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true; bg_write_errors 0 in the Cœur and Fastnet Diag tables; freeze-check F4 PASS"
    why_human: "Needs the real Pi 3B with its installed units and a healthy PSU"
  - test: "Record Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer'"
    expected: "Table filled; numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j); at least one right after a course change"
    expected: "Services come back, logcheck OK, course/settings intact or a visible '.bak restauré' alert, no .NAME.<n>.tmp left after the next write"
    why_human: "Physical power interruption"
  - test: "Plan B single-crash check on the Pi (system scope): `sudo systemctl start fastnet2ip; sudo kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 15; systemctl is-active fastnet2ip jabuka-fastnet-relay; systemctl show -p NRestarts fastnet2ip jabuka-fastnet-relay`; then, with a replay or the bus connected (the Fastnet adapter is not connected today), `timeout 15 nc -ul 2002 | head -3` on the laptop joined to the jabuka AP"
    expected: "Both active; relay NRestarts >= 1 (fastnet2ip may also show 1: it exits on pty EIO and restarts); NMEA lines arrive on UDP 2002 after the kill"
    why_human: "Needs the Pi's system-scope systemd, the deployed units and a data source on the relay"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md (delete or ignore the untracked docs/I18N-SL-REVIEW.md.bak first)"
    expected: "freeze-check exit 0 (F8 WARN / F9 HUMAN only); only configuration changes afterwards"
    why_human: "Owner decisions and a future-dated event"
  - test: "Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3)"
    expected: "Both units active, logcheck OK, fastnet-probe --file exits 0, same fingerprint on both cards (8b0a3bc4…19c8 unless the code changes), tablet opens http://10.42.0.1"
    why_human: "Physical SD cards and Pi boot"
  - test: "12 Nov: replay the boat's real capture (`bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`)"
    expected: "5 PASS lines; every decoded inventory path served by /api/state; logcheck OK"
    why_human: "The real Hercules capture only exists on 12 Nov"
  - test: "On-board commissioning per docs/COMMISSIONING.md §2-§9 (12-13 Nov; GPS arrives 2026-11-10), incl. the 04-11/04-12 helm behaviours at night at the lowest brightness (VIREZ/EMPANNEZ, VENT PÉRIMÉ, PAS DE GPS, lock release gesture, no pull-to-refresh, Diag red with no white flash, stale vs live dim tiers)"
    expected: "Helm tablet shows live/MANUEL/GRIB wind and laylines to the first mark over the boat Wi-Fi, readable at night (SC4)"
    why_human: "Real boat, instruments, GPS, tablet, night"
  - test: "On-board rounding drills at a real buoy (04-13..04-15): (a) a mark tapped ~50 m beyond the buoy, rounded and left on a beat, advances with the banner; a tack away on the approach side, outside the turn, well outside the radius keeps the mark. (b) Course-change drill right after a rounding, still in the zone: add a next mark at the default position (« Ajouter »), or move the next mark, then steer to it: the course moves on once. (c) Annuler-then-edit drill: after an early advance tap Annuler, finish the rounding, and while still in the zone use « Finir ici » on a later mark (or « Ajouter »): the course moves on once after leaving the zone past the mark. (d) R10 check: after an Annuler in the zone, if the course moves on while still inside the turn before passing the mark, a second Annuler (outside the zone) brings it back and it does not loop"
    expected: "Each drill behaves as stated; any stuck course is recovered with Carte → « Suiv. », any false advance with Annuler / « Préc. »"
    why_human: "Real GPS track at a real buoy and real crew timing"
  - test: "Course card, written by hand (no repo doc change before the freeze): (1) enter committee marks as close to the real buoy as known; (2) if the course does not move on after a rounding (bearing points back, distance grows) -> Carte → « Suiv. »; (3) after changing the next mark right after a rounding, steer to the new mark, otherwise « Suiv. » (R8); (4) if you move the rounded mark itself, its radius or the mark before it after rounding it -> « Suiv. » (R6); (5) if the course moves on right after Annuler while you are still inside the turn, before passing the mark -> Annuler again or « Préc. » (R10); (6) an edit made inside the 60 s banner window removes Annuler: use « Préc. » (IN-01/IN-02); (7) any false advance -> Annuler on the banner or « Préc. » (R1, R9)"
    expected: "Card on board, read by the crew before the start"
    why_human: "Owner logistics"
  - test: "Owner reads COMMISSIONING/SOAK/FREEZE and adjusts 12 Nov timings; a Slovenian speaker proofreads COMMISSIONING-SL.md and I18N-SL-REVIEW.md"
    expected: "Timings fit; FR clear; SL correct"
    why_human: "Owner logistics and native-language review"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-09T17:35:00Z (HEAD 899a451; last code commit 871ce0d at 17:26 local; var/gate-04-15.log written 17:49 local, after it)
**Status:** human_needed
**Re-verification:** Yes, after gap-closure plans 04-14 and 04-15 (previous: gaps_found 87/92, gap = FSM reset on a next-mark/side edit in the zone after the rounding)

## Verdict on the previous gap and on the reviews since

| Finding | Source | Status now | Evidence (mine unless stated) |
| --- | --- | --- | --- |
| Previous gap: outgoing edit in the zone after the rounding → stuck | 04-VERIFICATION 6019d70 / review 93cb8b3 CR-01 | ✓ **CLOSED** | Key split in course.py:656-678, :814-824. Independent grid 0/6912 stuck, 0 double advances |
| Annuler + an edit that nulls `suppress_idx` → stuck | review ccbbdc2 CR-01 | ✓ **CLOSED** | `_carry_suppress` course.py:312-332, called at :340 before `_write`. Annuler grid: HEAD 0/6912 stuck; the 2ebbd25 source 294/768 stuck per clearing edit kind; persists across a store restart |
| Annuler in the zone, approach-side retreat re-advances | review 93cb8b3 WR-01 | ✓ closed (outside of the turn) + R10 (inside) | course.py:843-856; 4 regression tests + R10 pin pass |
| One-sample latch false advance | review 93cb8b3 WR-02 | Accepted residual R9 | Pinned; evidence table in 04-14 |
| Plan B test fidelity | review 93cb8b3 WR-03 | ✓ closed | Stand-in exits 1 on relay loss; test passes here on user systemd, 0 units left |
| Pre-queue fsync failure logs every second | review 93cb8b3 IN-02 | ✓ closed | rawlog.py `_last_fsync = now` on the failure path; test passes |
| 04-15 review IN-01 / IN-02 | review 899a451 | ℹ️ advisory | Doc imprecision; R6 class; code guard correct |

### Why the 04-15 carry adds no new stuck or false-advance class

I checked this by reading the code, not only from the review.

**The guard (course.py:321-331).** It carries `suppress_idx` only when all of these hold:
- the old suppression is on the old active leg;
- the new course has the suppression nulled, no banner, and is not finished;
- the active index and the mark id are the same;
- the active leg is not the finish.

**Paths that never carry.**
- `undo` sets its own `suppress_idx`.
- `_advance` sets a banner.
- `_finish` sets `finished`.

**Paths where the carry never fires.**
- `_save_quiet`, the path where `_fsm` lifts the suppression, does not go through `_commit`.
- A 409 raises in `_check_version` before the carry.

**After a carry.**
- `_set` does not reset, because the active leg is unchanged.
- The CR-02 stand-in runs exactly as on the no-edit path.

**Grid result.**
- The "none" row and every keep-the-leg edit row give identical outcomes: 768/768 advance exactly twice.
- The "Finir ici on the active leg" clear case finishes on entering the 0.05 nm radius (test `[finish_here_active]`).

## User Flow Coverage (MVP mode)

User story (04-04..04-15): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence | Status |
| --- | --- | --- | --- |
| Prove 36 h on the laptop | One command, faults, budgets | Harness unchanged since 04-08; full race-36h on the final HEAD pending | ✓ code / ? human |
| Prove it on the Pi 3B | System-scope soak | Pi reported on 8b0a3bc4 = my HEAD fingerprint; PSU 0x50005 must be swapped first | ? human |
| Freeze, spare SD | Same state | Unchanged | ? human |
| Commission 12–13 Nov | Timed runbook | COMMISSIONING.md, dry-run tests green (gate) | ✓ doc / ? on board |
| Plan B survives a relay crash | Fallback feed stays up | RestartMode=direct; realistic exit-1 stand-in test passes | ✓ (Pi check pending) |
| Tablet trustworthy for the whole race | Correct next mark after every rounding, including after in-race edits and Annuler | No stuck run in 13 824 independent runs. The residuals left (R1–R10) are documented, test-pinned, each with a crew fallback | ✓ code / ? on board drills |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h soak on the Pi 3B with faults | ? HUMAN | PSU under-voltage; run pending |
| SC2 | Runbook exists, dry-run, all topics | ✓ VERIFIED | Gate 04-15 green (1915 passed, 4 skipped ×2, `check: ok`, EXIT=0) |
| SC3 | Freeze, spare SD, 12 Nov capture | ? HUMAN | Future-dated |
| SC4 | Helm tablet wind + laylines at night | ? HUMAN | Software present |
| 01..12, 13-1, 13-3..13-10 (87 truths incl. 03-1 human) | Previous rounds | ✓ VERIFIED (regression); 03-1 ? HUMAN | `git diff 6019d70..HEAD` outside .planning touches only course.py, rawlog.py and three test files. `_abeam`/`_leg_dots`/`_past_mark` are byte-identical to f96025b and 2ebbd25. 0 lines removed from test_course.py and test_background_durability.py. Gate green |
| 13-2 | Residual table lists every known no-auto-advance case (the previous FAILED truth) | ✓ VERIFIED | The CR-01 class is fixed (not listed, it no longer occurs). The R1–R10 table in 04-15-SUMMARY covers every stuck case I could produce: none outside it in 13 824 runs |
| 14-1 | Outgoing edit in the zone after the rounding advances exactly once (CR-01) | ✓ VERIFIED | `test_an_outgoing_edit_in_the_zone_after_the_rounding_still_advances`: 140 cases, 5 kinds incl. delete_next, noise 0/3 m, pass ×2 venvs. My grid: 0 stuck |
| 14-2 | Evidence keyed on (idx, mark, radius, prev, active); outgoing only restarts `_cand_since`; old 04-13 tests unchanged | ✓ VERIFIED | course.py:656-666, 668-678, 814-824; the suppress block re-stores `_fsm_out` (:835). `test_a_geometry_edit_restarts_the_rounding_debounce` and `test_a_rename_keeps_the_rounding_debounce` pass |
| 14-3 | R3-by-edit and R8 pinned stuck; « Suiv. » moves on; steering to the new mark advances | ✓ VERIFIED | The 3 named tests pass |
| 14-4 | WR-01: Annuler in the zone, then an approach-side retreat, never re-advances (stated tracks); CR-02 exit past the mark still advances | ✓ VERIFIED (stated tracks) | Plić and committee 45/60/90 at b_in + 210 deg pass; CR-02 guard passes. The general wording is narrowed by 04-15's correction: an inside-of-the-turn exit is accepted residual R10 |
| 14-5 | G-4-R02 holds; the three FSM helpers byte-identical | ✓ VERIFIED | Span diff empty vs f96025b |
| 14-6 | WR-02 = R9, pinned | ✓ VERIFIED | `test_one_fix_past_the_abeam_line_then_an_approach_side_exit_advances` passes |
| 14-7 | WR-03 realistic Plan B test | ✓ VERIFIED | Ran here: passes; `jabuka-wr06-*` units after the run: 0 |
| 14-8 | IN-02 retry on the fsync cadence | ✓ VERIFIED | rawlog.py diff; `test_a_failed_submit_retries_on_the_fsync_cadence` passes |
| 14-9 | Gate green, fingerprint recorded | ✓ VERIFIED | Superseded by 15-6 |
| 15-1 | CR-01 at Jabuka: 6 keep-the-leg edits keep `suppress_idx` 2, 2 advances | ✓ VERIFIED | 8-kind test passes. Restart probe: 6/6 keep `suppress_idx` 2 after reload and advance once |
| 15-2 | CR-01 at committee marks, turn 60/75 | ✓ VERIFIED | 14-case test passes; my Annuler grid 0/6912 stuck (2ebbd25 source: 294/768 per clearing kind) |
| 15-3 | Carry guard exactly as specified; clear cases still clear; « Finir ici » on the active leg finishes | ✓ VERIFIED | course.py:320-332 matches the contract; 5 clear-case tests pass |
| 15-4 | WR-01 = R10 pinned with the crew fallback; 04-14 D3 corrected | ✓ VERIFIED | `test_annuler_in_the_zone_then_an_inside_of_the_turn_retreat_advances` (45/60/90) passes; the correction is in 04-15-SUMMARY |
| 15-5 | Docs corrected; outside `_carry_suppress` + one call, only docstrings changed | ✓ VERIFIED | `var/ast-04-15.py 2ebbd25` gives `carry_method=1 commit_calls=1 rest_identical=True`, exit 0 (run here). Remaining imprecision is advisory (review IN-01/IN-02) |
| 15-6 | 274 course tests, both venvs green, gate log, fingerprint | ✓ VERIFIED | 274 passed ×2 (run here); gate log 1915 ×2 / `check: ok` / EXIT=0, written after the last code commit; `package_fingerprint(src/jabuka)` = 8b0a3bc4…19c8, 147 files (recomputed here) |

**Score:** 103/107 truths verified. 4 human-only (SC1, SC3, SC4, 03-1). 0 failed. 0 present-but-behaviour-unverified.

### Required Artifacts

| Artifact | Status | Details |
| --- | --- | --- |
| src/jabuka/nav/course.py | ✓ VERIFIED | `_seq_pos`, split `_fsm_geometry`/`_fsm_outgoing`, `_fsm_out`, CR-02 `_near`/hairpin `_beyond`, `_carry_suppress` + call in `_commit` |
| tests/nav/test_course.py | ✓ VERIFIED | 274 tests; outgoing-edit grid, Annuler-then-edit grids, clear-case guards, R3/R8/R9/R10 pins |
| src/jabuka/ingest/rawlog.py | ✓ VERIFIED | IN-02 |
| tests/test_background_durability.py | ✓ VERIFIED | IN-02 test + 04-13 WR-03 test |
| tests/deploy/test_units.py | ✓ VERIFIED | Exit-1 stand-in, NRestarts, new MainPID |
| deploy/systemd/* | ✓ unchanged | `git diff 6019d70..HEAD -- deploy` empty |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| `_fsm` key block | `_reset_fsm` / `_cand_since` | key change → full reset; outgoing change → `_cand_since = None` only | ✓ WIRED (:814-824) |
| Suppress block | `_fsm_out` | re-stores `_fsm_key` and `_fsm_out` after `_reset_fsm()` | ✓ WIRED (:833-835) |
| CR-02 `left_this_zone` | `_past_mark` | `_near = True`; `_beyond` only at a hairpin / with no outgoing leg | ✓ WIRED (:843-856) |
| `_commit` | `_carry_suppress` → `_write` → `_set` | after `_check_version`, before `_write` | ✓ WIRED (:339-344); persisted (restart probe) |
| Plan B stand-in | relay `RestartMode=direct` | copied directives | ✓ WIRED (test run) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| Active mark → router/laylines | `course.active_idx` | Rounding FSM on GPS ticks | Advances after real roundings, including after in-zone edits and Annuler + edit | ✓ FLOWING |
| `suppress_idx` | course.json | `_carry_suppress` in `_commit` | Persisted, survives reload | ✓ FLOWING |
| Diag Fastnet `bg_write_errors` | `atomicio.background_status()` | Durability thread | Yes (unchanged) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Course tests 3.14 / 3.13 | `pytest tests/nav/test_course.py` on both venvs | 274 passed ×2 | ✓ PASS |
| Deploy, durability, heartbeat, sim | `pytest tests/deploy/test_units.py tests/test_background_durability.py tests/bus/test_ingest_resilience.py::test_heartbeat_payload_contract tests/sim -k "not soak"` | 63 passed, no skip (Plan B test ran on user systemd) | ✓ PASS |
| Lint/format | `ruff check src tests`, `ruff format --check src tests` | clean / 234 formatted | ✓ PASS |
| FSM helpers unchanged | span diff vs f96025b and 2ebbd25 | empty | ✓ PASS |
| Minimal 04-15 change | `python -I var/ast-04-15.py 2ebbd25` | 1/1/True, exit 0 | ✓ PASS |
| Outgoing-edit grid (mine) | scratchpad `v0415/probe.py plain` | 6912 runs: 0 stuck, 0 multi (half advanced by abeam before the edit point) | ✓ PASS |
| Annuler-then-edit grid (mine) | `v0415/probe.py annuler` | HEAD 6912/6912 exactly 2 advances; 2ebbd25 source 294/768 stuck per clearing kind | ✓ PASS (discriminating) |
| Carry persistence | `v0415/restart.py` | 6/6 kinds: suppress_idx 2 after reload, then one advance | ✓ PASS |
| Fingerprint | `package_fingerprint(Path('src/jabuka'))` | 8b0a3bc4…19c8, 147 files; matches the orchestrator's Pi report | ✓ PASS |
| Debt markers | grep TBD/FIXME/XXX in the files changed by 04-14/04-15 | none | ✓ PASS |
| Leftover throwaway units | `systemctl --user list-units --all 'jabuka-wr06-*'` | 0 | ✓ PASS |

I did not re-run the full gate. var/gate-04-15.log (1915 passed, 4 skipped on both venvs, `check: ok`, `EXIT=0`) is newer than the last code commit, and the working tree is clean under src/tests/deploy/scripts.

### Probe Execution

There are no `scripts/*/tests/probe-*.sh` files, and no plan declares one. I ran the runnable checks above directly.

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| REL-02 | 04-01, 04-03..04-08, 04-10, 04-13, 04-14 | ✓ SATISFIED (software) / ? NEEDS HUMAN | Harness, recovery and Plan B are proven on the laptop. The Pi soak is pending the PSU swap |
| REL-03 | 04-02, 04-04, 04-06..04-08, 04-12 | ✓ SATISFIED (doc + dry run) / ? on board | Unchanged since the previous verification |
| CRSE-02/03/04 (Phase 2, touched by 04-09, 04-13..04-15) | 04-14, 04-15 | ✓ SATISFIED (automated) | Auto-advance after real roundings, after in-zone edits, and after Annuler + edit. Residuals R1–R10 are pinned |
| REL-01 (04-13 D4, 04-14 IN-02) | 04-14 | ✓ | Ingest durability tail |

There are no orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4. Its traceability rows still read "Gaps Found". The orchestrator should update them to reflect human-pending once this report is accepted.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| src/jabuka/nav/course.py | 312-319, 29-31, 674-676 | Docstrings slightly incomplete (review 04-15 IN-01/IN-02) | ℹ️ Info | Maintainer clarity only |
| src/jabuka/nav/course.py | 843-856 | Stand-in assumes "came near" (R10) | ℹ️ Info (accepted residual) | Visible false advance with a banner; crew fallback |
| docs/I18N-SL-REVIEW.md.bak | — | Untracked backup | ℹ️ Info | Clean-tree freeze step |

No blocker. No debt markers.

### Human Verification Required

See the `human_verification` frontmatter (13 items). Changes from the last round:
- **Code identity.** The item now targets 8b0a3bc4…19c8. The orchestrator says the Pi is already on it; I did not check that on the Pi. The PSU swap comes first.
- **Rounding drills (new item).** It holds the 04-13..04-15 on-board drills: the off-buoy committee mark, the course-change drill right after a rounding, Annuler-then-edit with « Finir ici » / « Ajouter », and the R10 second-Annuler check.
- **Course card.** It now lists all seven crew rules, R1–R10 plus the banner-window rule.
- **Plan B check.** It keeps NRestarts and NMEA on UDP 2002, and notes that a data source is needed because the adapter is not connected today.

### Gaps Summary

There are no gaps.
- **The previous blocker is closed.** A next-mark, side, add-at-default or delete edit in the zone after the rounding no longer resets the evidence.
- **The new blocker found after 04-14 is closed.** That was an Annuler followed by an edit that nulled the suppression.

I checked both with my own grids, separate from the plans' tests: 13 824 runs, 0 stuck, 0 unexpected double advances. The Annuler grid fails 294/768 per clearing edit kind on the pre-04-15 source, so it does discriminate.

The remaining false-advance and stuck residuals (R1–R10) are documented, pinned by tests and each has a crew fallback. The owner's delegate accepted them under the rule "never trade a stuck course for fewer false advances".

What remains is human and hardware work:
- the PSU swap and Pi soak (SC1);
- the freeze and spare SD (SC3);
- the 12 Nov capture;
- on-board commissioning and drills (SC4);
- the hand-written course card.

---

_Verified: 2026-11-09T17:35:00Z_
_Verifier: Claude (gsd-verifier)_
