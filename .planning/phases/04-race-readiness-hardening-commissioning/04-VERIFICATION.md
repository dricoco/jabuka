---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-09T14:54:57Z
status: gaps_found
score: 87/92 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-09-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-09-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-10-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-10-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-11-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-11-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-12-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-12-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-13-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-13-SUMMARY.md", "deploy/systemd/fastnet2ip.service", "deploy/systemd/jabuka-core.service", "deploy/systemd/jabuka-fastnet-relay.service", "docs/COMMISSIONING.md", "docs/I18N-SL-REVIEW.md", "docs/ROUTING.md", "docs/TABLET-SETUP.md", "src/jabuka/common/atomicio.py", "src/jabuka/core/main.py", "src/jabuka/ingest/fastnet_main.py", "src/jabuka/ingest/rawlog.py", "src/jabuka/nav/course.py", "src/jabuka/nav/polar.py", "src/jabuka/route/pool.py", "src/jabuka/route/pool_probe.py", "src/jabuka/web/static/app.css", "src/jabuka/web/static/app.js", "src/jabuka/web/static/diag-theme.js", "src/jabuka/web/static/diag.css", "src/jabuka/web/static/diag.html", "src/jabuka/web/static/diag.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/i18n.js", "src/jabuka/web/static/lock.js", "src/jabuka/web/static/lock_logic.js", "src/jabuka/web/static/route_logic.js", "tests/bus/test_ingest_resilience.py", "tests/deploy/test_units.py", "tests/nav/test_course.py", "tests/nav/test_polar_vmg.py", "tests/nav/test_wind.py", "tests/route/test_pool.py", "tests/test_background_durability.py", "tests/test_helm_logic.py", "tests/test_lock_logic.py", "tests/test_route_logic.py", "tests/ui/test_helm.py", "tests/ui/test_helm_column.py", "tests/ui/test_i18n_ui.py", "tests/ui/test_lock_wake.py", "tests/ui/test_night.py", "tests/ui/test_route_ui.py", "tests/ui/test_tablet_hardening.py"]
covered_digest: "v1:sha256:b8caa4070f8e6a4f4efbce993b70cb58f1046df8382b953fcf3e9b491d501841"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 77/82
  gaps_closed:
    - "Previous CR-01 (non-hairpin zone exit on the approach side of the abeam line never advanced): closed for the reported tracks. My grid with no edit (committee error 0/0.011/0.05/0.09 nm x rounding radius 0.005/0.008/0.01/0.02 nm x 8 turn+tack geometries x 3 seeds, 3 m GPS noise): 0/384 stuck on HEAD; the same tracks were stuck on 1b9ae57 (04-12)"
    - "Previous WR-01 (latch survived an edit of the active mark): closed; test_a_geometry_edit_restarts_the_rounding_debounce and test_moving_the_active_hairpin_mark_needs_the_corrected_mark_rounded pass"
    - "Review WR-03/WR-07/WR-02-ingest/WR-06 of the previous round: code read + named tests pass; WR-06 also reproduced by me with a stand-in that exits 1 on relay loss, like the real fastnet2ip 3.3.1 (relay back at ~2 s, Plan B at ~5 s)"
  gaps_remaining:
    - "Same 'course stuck on the mark just rounded' class as the previous CR-01, now through the 04-13 WR-01 reset scope (see gaps[0])"
  regressions:
    - "Against dbcd536 only (not against 04-12, which was stuck on these tracks even without an edit): an edit of the next mark or of the active leg's side while the boat is still in the zone after the rounding, more than radius + 0.1 nm from the entered point, leaves the course stuck (dbcd536: 0 stuck on the same tracks)"
gaps:
  - truth: "04-13: 'The plan's Accepted residuals table lists every known case where a real rounding does not auto-advance after this fix' and 'a real rounding of a mark whose turn is <= 90 deg always advances when the entered mark is within about 0.1 nm of the real buoy' (CRSE-03 auto-advance, review CR-01 of 93cb8b3)"
    status: failed
    reason: "_fsm_geometry (course.py:612-631) puts leg.side and pos(idx + 1) in the state-machine key, so editing the next mark (any move, even 1 m), inserting a mark at the add_mark default position (active_idx + 1), deleting/reordering the next mark, or set_leg(side) runs a full _reset_fsm(). None of the stored evidence depends on those: _beyond uses dot_in (previous + active mark), _near and _entered use the active mark and radius. If the edit lands while the boat is still inside the zone but beyond leg radius + MARK_TOL_NM (0.15-0.30 nm for a committee mark, about 75 s at 7 kn), the evidence never comes back and the course stays on the rounded mark; the router and laylines steer back to it. My independent grid (real CourseStore, continuous 1 Hz arc tracks, 3 m GPS noise, edit at 0.2 nm out): committee mark entered 0.05 or 0.09 nm beyond the buoy -> 96/96 stuck for BOTH 'next mark nudged 1 m' and 'add_mark at the default position', at every rounding radius 0.005-0.02 nm and every geometry; 0.011 nm (20 m) error -> 66/96; mark exactly on the buoy -> 21/96 (tight roundings 0.005-0.008 nm only). Same tracks with no edit: 0/384. This is broader than the review's 'tight rounding' framing: the 04-13 fix made _near the only evidence for an off-buoy committee mark, and the reset wipes it. Not covered by R1-R7: R6 says 'after the zone exit', this is before it. The runbook's course-change drill (SC2) trains exactly this kind of in-race edit."
    artifacts:
      - path: "src/jabuka/nav/course.py"
        issue: "_fsm_geometry keys the evidence on the outgoing geometry (leg.side, pos(idx + 1)); _fsm (:767-770) resets everything on any key change. The docstring's claim that the latch/near evidence was 'measured against the old outgoing leg' is wrong"
      - path: "tests/nav/test_course.py"
        issue: "No test edits the next mark / adds a mark / changes the side while the boat is in the zone after the rounding; test_a_geometry_edit_restarts_the_rounding_debounce pins the over-broad reset"
      - path: ".planning/phases/04-race-readiness-hardening-commissioning/04-13-SUMMARY.md"
        issue: "Residual R6 window misdescribed ('after the zone exit')"
    missing:
      - "Key the evidence (_entered, _beyond, _near, _suppressed_in_zone) only on (idx, mark_id, radius, previous position, active position); on an outgoing-only change (side, next mark) reset only _cand_since (reviewer's fix). Verifier check of that fix by monkeypatch (scratchpad v0413r/patchfix.py): tests/nav/test_course.py 83/83 pass; my edit grid 0/1728 stuck for exact marks; the only remaining stuck runs are turns pushed over HAIRPIN_DEG by the edit (90 deg + 1 m nudge, or +10 deg new mark at 85/89/90 deg) with an off-buoy mark, i.e. accepted residual R3"
      - "Regression tests: committee mark 0.05 nm beyond the buoy and an exact tight rounding (75+45 at 0.005 nm), each with (a) next mark nudged, (b) add_mark at the default position, (c) set_leg(side) at 0.2 nm out -> exactly one course_advance; keep the moved-active / moved-previous / radius tests"
      - "Fix the _fsm_geometry docstring and residual R6; re-run the gate on both venvs, recompute the fingerprint (c6fb70b0... will change), rebuild the wheelhouse and re-provision the Pi"
      - "OR (owner decision) accept it as an extended R6 via the override below and write it on the course card: 'after rounding, do not edit the next mark/side until the course has moved on; if it does not, Carte -> « Suiv. »'"
deferred: []
advisory:
  - finding: "Review WR-01 (93cb8b3): at a normal mark, Annuler tapped while the boat is inside the zone forces _beyond = True, so the next zone exit in any direction advances, including an approach-side retreat"
    category: other
    reason: "Reproduced with a continuous track: Plić, abeam advance in the zone (10 s just past abeam at 0.4 nm), Annuler at once, back to the approach side, retreat to 0.9 nm -> advanced again (HEAD 2 advances; 04-12 1; dbcd536 2). Same for a committee mark (turn 45/60/90). The review's second repro (R1 advance, Annuler OUTSIDE the zone, then re-entry) does NOT reproduce with a continuous track (HEAD: 1 advance): it relied on the boat jumping from 0.5 nm to 0.25 nm in one tick, which skips the outside tick that clears suppress_idx. Warning, not gap: the boat had passed abeam for 10 s before the Annuler (the abeam rule's definition of rounded); the false advance shows the 60 s banner, and a second Annuler is then outside the zone (R7: no auto-advance until a fresh entry). Plan 04-13 line 414 chose this on purpose but did not list it as a false-advance residual. Cheap fix with the gap: set _near (not _beyond) on the suppressed exit at normal marks"
    evidence_status: "deterministic repro (scratchpad v0413r/probe_wr.py wr01_plic, wr01_committee_in_zone)"
  - finding: "Review WR-02: _beyond latches on a single fix with dot_in > 0 anywhere inside the 2 nm gate after the first entry; outside the zone that fix holds the candidate and advances 10 s later"
    category: other
    reason: "Reproduced: a boat sailing along the abeam line (the layline when the rhumb line is 45 deg off the wind) with 3 m GPS noise, then turning back to the approach side: 20/20 advance on HEAD (Plić and committee mark, tack-away at 0.1/0.2/0.28 nm), 0/20 on 04-12. Correction to the review: its repro D fix is at 0.28 nm, INSIDE Plić's 0.55 nm zone (radius 0.3), so the proposed 'latch only inside the zone' fix does not fix D (verified: still advances) nor my layline track. A plain margin is not free either: dot_in > 0.008 nm clears WR-02 but brings back 139/1152 stuck roundings in my grid (the latch is what saves tight roundings). Warning, not gap: low exposure (tacking away from that layline points the boat past the mark, not back), banner + Annuler. Needs a hysteresis design (e.g. 2-3 consecutive samples), not a one-line change, two days before the freeze"
    evidence_status: "deterministic repro + fix candidates tested (scratchpad v0413r/probe_wr.py wr02, wr02fix.py, wr02margin.py)"
  - finding: "Review WR-03: test_one_relay_crash_keeps_plan_b_up uses `sleep infinity` for Plan B and asserts the same MainPID; the real fastnet2ip 3.3.1 exits 1 when the relay's pty goes away"
    category: other
    reason: "Confirmed by reading the 3.3.1 wheel: read_input_source does select + Serial.read and only KeyboardInterrupt is caught, so a SerialException on pty EIO ends the process. I ran the review's exit-1 stand-in (planb_exp.sh, relay kill -9) on user-scope systemd 260: relay restarted at ~2 s (NRestarts 1), Plan B restarted at ~5 s (NRestarts 1), both active at 6/12/20 s, no unit left behind. So the WR-06 behaviour holds; the committed test proves a different scenario. Fix the test (stand-in exits 1, assert both active and NRestarts >= 1) and add an NMEA data check to the Pi human item"
    evidence_status: "wheel source read + user-scope systemd run"
  - finding: "Review IN-01 (ingest crash-path drain can outlast WatchdogSec=30) and IN-02 (persistent pre-queue fsync failure logs at ERROR every second)"
    category: other
    reason: "Code read confirms both; outcome on IN-01 is the same restart, noisier. Info level"
    evidence_status: "code read (fastnet_main.py:445-460, rawlog.py:210-219)"
  - finding: "Carried, deferred by plan 04-13 with rationale: previous WR-02 Diag red alert line for bg_write_errors (counters are now shown in both Diag tables), WR-04 night fg/dim floor, WR-05 unknown-age MANUEL never stale, IN-01..IN-04, 04-08 WR-01/IN-01/IN-03/WR-04, '.bak restauré' wording; untracked docs/I18N-SL-REVIEW.md.bak"
    category: other
    reason: "Unchanged since the previous verification (04-13 did not touch web/, common/, soak or freeze code: empty diff); same classification"
    evidence_status: "git diff 1b9ae57..0ca639c"
behavior_unverified_items: []
coincidental_reliance_items: []
human_verification:
  - test: "After the gap is closed (or overridden): rebuild the wheelhouse from the final HEAD and re-provision the Pi; installed fingerprint = package_fingerprint(src/jabuka) of HEAD. Today HEAD = c6fb70b03329019122eb8dab3e6dffbd88d74ecaed793ddef777a691ec46a737 (147 files, computed by me) and the orchestrator reports the Pi has it (not re-checked by me). Replace the PSU first: get_throttled 0x50005"
    expected: "Installed fingerprint = HEAD; vcgencmd get_throttled = 0x0 after a run under load"
    why_human: "Physical PSU swap and Pi provisioning"
  - test: "Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length, no Ctrl-C"
    expected: "PASS, exit 0, end_signal null, duration_s 129600, scenario_sha256 of HEAD; freeze-check F3 PASS"
    why_human: "About 40 min of wall time on the final HEAD"
  - test: "Pi 3B system-scope soak (ROADMAP SC1) in tmux: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`; scp the run dir, reboot, `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0"
    expected: "Exit 0, PASS, journal.complete true, tick ratio >= 0.95, core/worker RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true; bg_write_errors 0 in the Cœur and Fastnet Diag tables; freeze-check F4 PASS"
    why_human: "Needs the real Pi 3B with its installed units"
  - test: "Record Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer'"
    expected: "Table filled; numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j); at least one right after a course change"
    expected: "Services come back, logcheck OK, course/settings intact or a visible '.bak restauré' alert, no .NAME.<n>.tmp left after the next write"
    why_human: "Physical power interruption"
  - test: "Plan B single-crash check on the Pi (system scope, systemd 257): `sudo systemctl start fastnet2ip; sudo kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 15; systemctl is-active fastnet2ip jabuka-fastnet-relay; systemctl show -p NRestarts fastnet2ip jabuka-fastnet-relay`, then with a replay or the bus connected `timeout 15 nc -ul 2002 | head -3`"
    expected: "Both active, NMEA lines arrive on UDP 2002 after the kill (fastnet2ip may show NRestarts 1: it exits on pty EIO and restarts)"
    why_human: "Needs the Pi's system-scope systemd and the deployed units"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md"
    expected: "freeze-check exit 0 (F8 WARN / F9 HUMAN only); only configuration changes afterwards"
    why_human: "Owner decisions and a future-dated event"
  - test: "Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3)"
    expected: "Both units active, logcheck OK, fastnet-probe --file exits 0, same fingerprint on both cards, tablet opens http://10.42.0.1"
    why_human: "Physical SD cards and Pi boot"
  - test: "12 Nov: replay the boat's real capture (`bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`)"
    expected: "5 PASS lines; every decoded inventory path served by /api/state; logcheck OK"
    why_human: "The real Hercules capture only exists on 12 Nov"
  - test: "On-board commissioning per docs/COMMISSIONING.md §2-§9 (12-13 Nov), incl. 04-11/04-12 helm behaviours at night at the lowest brightness (VIREZ/EMPANNEZ, VENT PÉRIMÉ, PAS DE GPS, lock release gesture, no pull-to-refresh, Diag red with no white flash, stale vs live dim tiers), and the 04-13 rounding checks: a mark tapped ~50 m beyond a real buoy, rounded and left on a beat, advances with the banner; a tack away on the approach side well outside the radius keeps the mark"
    expected: "Helm tablet shows live/MANUEL/GRIB wind and laylines to the first mark over the boat Wi-Fi, readable at night (SC4); rounding checks behave as stated"
    why_human: "Real boat, instruments, GPS track at a real buoy, tablet, night"
  - test: "Course card (by hand): committee marks entered as close to the real buoy as known; if the course does not move on after a rounding (bearing points back, distance grows) -> Carte -> « Suiv. »; if the gap is overridden instead of fixed, also: do not edit the next mark/side right after a rounding until the course has moved on"
    expected: "Card on board"
    why_human: "Owner logistics"
  - test: "Owner reads COMMISSIONING/SOAK/FREEZE and adjusts 12 Nov timings; a Slovenian speaker proofreads COMMISSIONING-SL.md and I18N-SL-REVIEW.md"
    expected: "Timings fit; FR clear; SL correct"
    why_human: "Owner logistics and native-language review"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-09T14:54:57Z (main 93cb8b3; last code commit 0ca639c; var/gate-04-13.log 15:25 local, after it)
**Status:** gaps_found
**Re-verification:** Yes, after gap-closure plan 04-13 (previous: gaps_found 77/82, gap = previous CR-01 + WR-01)

## Verdict on the 04-13 review findings

| Finding | Reproduced independently | Classification | Why |
| --- | --- | --- | --- |
| **CR-01** next-mark / side edit in the zone after the rounding → stuck | Yes, and it is broader than reported | 🛑 **GAP** | Falsifies the 04-13 truths (residual table complete; real roundings advance). Hits off-buoy committee marks at **any** rounding radius, not only tight roundings |
| WR-01 Annuler in the zone → any later exit advances | Yes (continuous track). The review's "Annuler outside the zone" variant is a teleport artifact | ⚠️ Warning / advisory | Boat had passed abeam 10 s; visible banner; second Annuler is outside the zone (R7) |
| WR-02 one-sample latch | Yes. The review's own fix does not fix its repro | ⚠️ Warning / advisory | Low exposure, banner; needs hysteresis design, a margin brings back stuck roundings |
| WR-03 Plan B test models `sleep infinity` | Yes (wheel read + exit-1 stand-in run) | 📋 Advisory | The recovery chain works; the test proves a different scenario |
| IN-01, IN-02 | Code read | ℹ️ Info | |

### CR-01 in detail (why it is a gap, not an advisory)

**Mechanism (code read).** `_fsm_geometry` (course.py:612-631) returns `(idx, mark_id, side, radius, pos(idx-1), pos(idx), pos(idx+1))`. `_fsm` (:767-770) calls `_reset_fsm()` on any change. The evidence does not depend on `side` or `pos(idx+1)`:
- `_beyond` uses `dot_in` (previous mark → active mark);
- `_near` and `_entered` use the active mark and the radius.

After an off-buoy committee mark is rounded, `_near` is the *only* evidence (the boat is never past the entered point along the incoming leg). Once the boat is more than radius + 0.1 nm out, it can never be set again.

**My grid** (scratchpad `v0413r/probe.py`, `breakdown.py`). Setup: the real `CourseStore`, the `_committee` geometry, a continuous 1 Hz arc, 3 m GPS noise, 8 turn+tack geometries × 4 rounding radii (0.005–0.02 nm) × 3 seeds, with the edit at 0.2 nm out:

| Mark error beyond buoy | No edit | Next mark nudged 1 m | add_mark at default position |
| --- | --- | --- | --- |
| 0 | 0/96 stuck | 21/96 (tight only) | 21/96 |
| 0.011 nm (20 m) | 0/96 | 66/96 | 66/96 |
| 0.05 nm | 0/96 | **96/96** | **96/96** |
| 0.09 nm | 0/96 | **96/96** | **96/96** |

`set_leg(side)` and moving the next mark 0.5 nm behave like the nudge (exact-mark sub-grid: 15/24 at 0.005 nm, 6/24 at 0.008 nm, 0 from 0.01 nm).

**Against earlier code.**
- 04-12 (1b9ae57) is stuck on the tight tracks even without an edit, so 04-13 is strictly better than what the Pi ran before.
- dbcd536 advances on all of them, so against dbcd536 this is a CRSE-03 regression.

**Why a gap.**
- It is the same failure class the previous verification called a blocker: a confident "steer back to the mark you rounded", with no banner and no prompt.
- 20–90 m is the normal error of a tapped mark (the very case 04-13 set out to fix).
- In-race course edits are a trained, runbook path (SC2: the course-change drill).
- R6 does not cover it: R6 is "after the zone exit", and this happens before it.

**My own share of the blame.** The previous verification's "missing" list asked for a reset when "the next mark (turn) changes". That prescription was too broad, and 04-13 implemented it faithfully.

**The fix is small and checked.** I applied the reviewer's split by monkeypatch (`v0413r/patchfix.py`): evidence keyed on the incoming leg, active mark and radius; outgoing changes reset only the debounce.
- `tests/nav/test_course.py`: 83/83 pass.
- Exact-mark edit grid: 0/1728 stuck.
- Off-buoy runs still stuck: only turns pushed over `HAIRPIN_DEG` by the edit itself (a 90° turn plus a 1 m nudge; a +10° new mark at 85/89/90°). That is accepted residual R3.

**The owner may accept it instead.** If so, record this override and extend R6 on the course card:

```yaml
overrides:
  - must_have: "The plan's Accepted residuals table lists every known case where a real rounding does not auto-advance after this fix"
    reason: "Extended R6: an edit of the next mark / side / add_mark at the default position while the boat is still in the zone after the rounding resets the evidence; crew fallback Carte -> « Suiv. », written on the course card; no code change two days before the freeze"
    accepted_by: "{owner}"
    accepted_at: "{ISO timestamp}"
```

## User Flow Coverage (MVP mode)

User story (04-04..04-13): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence | Status |
| --- | --- | --- | --- |
| Prove 36 h on the laptop | One command, faults, budgets | Harness unchanged since 04-08; full race-36h on the final HEAD pending | ✓ code / ? human |
| Prove it on the Pi 3B | System-scope soak | Pi reported on c6fb70b0 = my HEAD fingerprint; PSU 0x50005 | ? human |
| Freeze, spare SD | Same state | Unchanged | ? human |
| Commission 12–13 Nov | Timed runbook | COMMISSIONING.md, dry-run tests green | ✓ doc / ? on board |
| Plan B survives a relay crash | Fallback feed stays up | RestartMode=direct; my exit-1 stand-in run recovers | ✓ (Pi check pending) |
| **Tablet trustworthy for the whole race** | Correct next mark after every rounding | Reported CR-01 tracks now advance. **A next-mark/side edit right after rounding an off-buoy committee mark leaves the course stuck** | ✗ **FAILED** |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h soak on the Pi 3B with faults | ? HUMAN | PSU under-voltage; run pending |
| SC2 | Runbook exists, dry-run, all topics | ✓ VERIFIED | Gate 04-13 green (1722 passed, 4 skipped ×2, `check: ok`, EXIT=0) |
| SC3 | Freeze, spare SD, 12 Nov capture | ? HUMAN | Future-dated |
| SC4 | Helm tablet wind + laylines at night | ? HUMAN | Software present |
| 01..08 (51), 10-*, 11-*, 12-* | Previous rounds | ✓ VERIFIED (regression) | 04-13 diff touches only course.py, rawlog.py, fastnet_main.py, the relay unit and tests; 0 test lines removed; gate green |
| 09-1, 09-2, 09-4, 09-5 | G-4-R02 retreats, past-the-mark gate, polar, gate | ✓ VERIFIED | As before; `test_leaving_the_zone_on_the_approach_side_never_advances` passes (3.14 + 3.13) |
| 09-3 | Real roundings still advance (previous gap) | ✓ VERIFIED | No-edit grid 0/384 stuck (error 0–0.09 nm, radius 0.005–0.02 nm) |
| 13-1 | Committee marks up to 0.09 nm and tight roundings advance exactly once | ✓ VERIFIED (enumerated tracks) | `test_committee_mark_entered_beyond_the_buoy_advances`, `test_tight_rounding_then_a_beat_out_advances` pass; my grid 0 stuck, 0 double advance without edits |
| 13-2 | Residuals pinned; the table lists **every known** no-auto-advance case | ✗ FAILED | R2/R3 pins pass, but the in-zone outgoing-edit case (CR-01) is not listed and is not R6 |
| 13-3 | Exact CR-01 rule | ✓ VERIFIED | course.py:731-739 matches; `_abeam` and `_leg_dots` unchanged |
| 13-4 | G-4-R02 still holds for the stated retreats | ✓ VERIFIED (stated tracks) | The inside-of-the-turn and approach-side tests pass. Two narrower false-advance paths exist: WR-01 and WR-02 (advisory) |
| 13-5 | WR-01: geometry edits restart the FSM, a rename does not | ✓ VERIFIED (as specified) | The tests pass. **The specified scope (next mark, side) causes 13-2** |
| 13-6 | WR-03: a failed submit clears `_fsync_inflight` and re-raises | ✓ VERIFIED | rawlog.py:208-218; `test_cadence_fsync_recovers_after_a_failed_submit` passes |
| 13-7 | WR-07: drain and socket close survive a close error | ✓ VERIFIED | fastnet_main.py:451-460; test passes |
| 13-8 | WR-06: `RestartMode=direct`; single crash keeps Plan B | ✓ VERIFIED | Unit :34; test passes; my exit-1 stand-in run recovers (advisory WR-03 on test fidelity) |
| 13-9 | WR-02 ingest: heartbeat exports `bg_write_errors` | ✓ VERIFIED | fastnet_main.py:185; `test_heartbeat_payload_contract` passes |
| 13-10 | Both venvs green, gate log, fingerprint recorded | ✓ VERIFIED | var/gate-04-13.log; my `package_fingerprint(src/jabuka)` = c6fb70b0…a737, 147 files |

**Score:** 87/92 truths verified. 1 failed (13-2). 4 human-only (SC1, SC3, SC4, 03-1). 0 present-but-behaviour-unverified.

### Required Artifacts

| Artifact | Status | Details |
| --- | --- | --- |
| src/jabuka/nav/course.py | ⚠️ PRESENT, WIRED, DEFECTIVE | `MARK_TOL_NM`, `_near`, `_past_mark`, `_fsm_geometry` all present; the reset scope causes the gap |
| tests/nav/test_course.py | ✓ (one hole) | 83 tests; no in-zone outgoing-edit test |
| src/jabuka/ingest/rawlog.py, fastnet_main.py | ✓ VERIFIED | |
| tests/test_background_durability.py, tests/bus/test_ingest_resilience.py | ✓ VERIFIED | |
| deploy/systemd/jabuka-fastnet-relay.service | ✓ VERIFIED | `RestartMode=direct`; fastnet2ip.service unchanged |
| tests/deploy/test_units.py | ✓ (advisory WR-03) | The stand-in does not exit like the real fastnet2ip |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| `_fsm` | `_advance` | `_abeam or (d > zone and _past_mark(dots))` with `_beyond`/`_near` | ✓ WIRED |
| edit_mark / set_leg / add_mark / select | `_reset_fsm` | `_fsm_geometry` key compare each tick | ✓ WIRED; over-broad (gap) |
| Relay `RestartMode=direct` | fastnet2ip `BindsTo=` | Auto-restart skips inactive | ✓ WIRED (my systemd 260 run) |
| `_run` finally | `atomicio.disable_background(20.0)` | try / except / finally | ✓ WIRED |
| `FastnetIngest.health` | Diag Fastnet table | heartbeat → `health.fastnet` | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| Active mark → router/laylines | `course.active_idx` | Rounding FSM on GPS ticks | Advances after real roundings, except after an in-zone outgoing edit | ✗ HOLLOW on the CR-01 path |
| Diag Fastnet `bg_write_errors` | `atomicio.background_status()` (ingest process) | Durability thread | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Course tests (3.14 / 3.13) | `pytest tests/nav/test_course.py` on both venvs | 83 passed ×2 | ✓ PASS |
| 04-13 tail tests | `pytest tests/test_background_durability.py tests/bus/test_ingest_resilience.py::test_heartbeat_payload_contract tests/deploy/test_units.py` | 33 passed | ✓ PASS |
| Review scripts | `fsm_probe.py`, `fsm_probe2.py` on HEAD | A/B/D and nudge/side stuck reproduce as reported | ✓ reproduced |
| CR-01, my grid | `v0413r/probe.py cr01`, `breakdown.py` | Table above | ✗ FAIL |
| Reviewer CR-01 fix | `PYTHONPATH=v0413r pytest -p patchfix tests/nav/test_course.py` + grid | 83/83; 0/1728 exact-mark stuck | ℹ️ fix viable |
| WR-01 / WR-02 | `v0413r/probe_wr.py` | Plić re-advance after an in-zone Annuler; 20/20 layline false advance; review B2 not reproducible continuously | ⚠️ advisory |
| WR-02 fixes | `wr02fix.py` (zone-only), `wr02margin.py` (0.008 nm) | Zone-only: D still advances. Margin: 139/1152 stuck | ℹ️ needs design |
| Plan B real-exit chain | `planb_exp.sh` (relay kill -9, exit-1 stand-in) | Both active, NRestarts 1/1, 0 units left | ✓ PASS |
| Fingerprint | `package_fingerprint(Path('src/jabuka'))` | c6fb70b0…a737, 147 files | ✓ PASS |
| Debt markers / removed asserts | `git diff 1b9ae57..0ca639c` | None added; 0 test lines removed | ✓ PASS |

### Probe Execution

There are no `scripts/*/tests/probe-*.sh` files, and no plan declares one. I ran the runnable checks above directly.

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| REL-02 | 04-01, 04-03..04-08, 04-10, 04-13 | ✓ SATISFIED (software) / ? NEEDS HUMAN | Plan B single-crash fixed; Pi soak pending after the PSU swap |
| REL-03 | 04-02, 04-04, 04-06..04-08, 04-12 | ✓ SATISFIED (doc) / ? on board | Unchanged by 04-13 |
| CRSE-03 / CRSE-02 (Phase 2, touched by 04-09/04-13) | 04-13 | ✗ PARTIAL | Auto-advance fixed without edits; stuck after an in-zone outgoing edit (gap) |
| REL-01 (04-13 D4) | 04-13 | ✓ | Ingest durability tail |

There are no orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and both show "Gaps Found", which stays correct.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| src/jabuka/nav/course.py | 631, 767-770 | Evidence keyed on geometry it does not depend on | 🛑 Blocker | CR-01 gap |
| src/jabuka/nav/course.py | 788-794 | Annuler forces the latch at normal marks | ⚠️ Warning | WR-01 |
| src/jabuka/nav/course.py | 811-814 | Latch with no hysteresis | ⚠️ Warning | WR-02 |
| tests/deploy/test_units.py | 197-209, 246 | Stand-in behaviour differs from the real binary | ℹ️ Info | WR-03 |
| docs/I18N-SL-REVIEW.md.bak | — | Untracked backup | ℹ️ Info | Clean-tree freeze step |

### Human Verification Required

See the `human_verification` frontmatter (12 items). Changes from last round:
- **Plan B check.** It now also checks NRestarts and that NMEA arrives on UDP 2002 (review WR-03).
- **Course card.** It carries the « Suiv. » fallback, plus the edit rule if CR-01 is overridden.
- **Re-provisioning.** It depends on whether the gap is fixed or overridden.

### Gaps Summary

**One blocker, CR-01 of the 04-13 review, which I confirmed independently.** It is broader than the review says.

**What triggers it.** Any of these resets all rounding evidence:
- moving the next mark;
- inserting a mark at the default position;
- deleting or reordering the next mark;
- changing the active leg's side.

**When it bites.** The boat is still in the zone after rounding, but more than radius + 0.1 nm from the entered point (about the 75 s after a committee-mark rounding).

**Effect.**
- A committee mark tapped 0.05–0.09 nm off the buoy stays active for good in every one of my runs.
- With a 20 m error, two thirds of my runs stick.
- Only tight roundings of an exactly placed mark stick.

**The fix.** It is the reviewer's split of the state-machine key: about 15 lines plus one parametrised test. I checked it: 83/83 course tests pass and it leaves only accepted residual R3.

**The alternative.** The owner accepts it as an extended R6 via the override above, with the rule on the course card.

**Not gaps.** WR-01, WR-02 and WR-03 are real but are advisories:
- WR-01 and WR-02 are visible false advances on narrow paths, with the banner.
- WR-02 needs a hysteresis design. The review's one-line fix does not fix its own repro, and a margin reintroduces stuck roundings.
- WR-03 is test fidelity only: the real recovery chain works.

The rest of 04-13 (WR-03/WR-07/WR-02-ingest/WR-06 of the previous review) is verified in code, tests and my systemd run.

---

_Verified: 2026-11-09T14:54:57Z_
_Verifier: Claude (gsd-verifier)_
