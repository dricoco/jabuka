---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-09T13:02:22Z
status: gaps_found
score: 77/82 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-09-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-09-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-10-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-10-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-11-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-11-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-12-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-12-SUMMARY.md", "deploy/systemd/fastnet2ip.service", "deploy/systemd/jabuka-core.service", "deploy/systemd/jabuka-fastnet-relay.service", "docs/COMMISSIONING.md", "docs/I18N-SL-REVIEW.md", "docs/ROUTING.md", "docs/TABLET-SETUP.md", "src/jabuka/common/atomicio.py", "src/jabuka/core/main.py", "src/jabuka/ingest/fastnet_main.py", "src/jabuka/ingest/rawlog.py", "src/jabuka/nav/course.py", "src/jabuka/nav/polar.py", "src/jabuka/route/pool.py", "src/jabuka/route/pool_probe.py", "src/jabuka/web/static/app.css", "src/jabuka/web/static/app.js", "src/jabuka/web/static/diag-theme.js", "src/jabuka/web/static/diag.css", "src/jabuka/web/static/diag.html", "src/jabuka/web/static/diag.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/i18n.js", "src/jabuka/web/static/lock.js", "src/jabuka/web/static/lock_logic.js", "src/jabuka/web/static/route_logic.js", "tests/deploy/test_units.py", "tests/nav/test_course.py", "tests/nav/test_polar_vmg.py", "tests/nav/test_wind.py", "tests/route/test_pool.py", "tests/test_background_durability.py", "tests/test_helm_logic.py", "tests/test_lock_logic.py", "tests/test_route_logic.py", "tests/ui/test_helm.py", "tests/ui/test_helm_column.py", "tests/ui/test_i18n_ui.py", "tests/ui/test_lock_wake.py", "tests/ui/test_night.py", "tests/ui/test_route_ui.py", "tests/ui/test_tablet_hardening.py"]
covered_digest: "v1:sha256:96c71f475a3c5964eddcf708f852b88f9c38ddc7f3bec70362c8215a3ca95c6d"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 51/55
  gaps_closed:
    - "G-4-R01 stale MANUEL wind: VENT PÉRIMÉ label, blocks 1-2 dimmed, no tack cue on stale wind (helm_logic windStale/primaryView/helmView; logic + Playwright tests pass)"
    - "G-4-R02 (narrow truth): an approach-side retreat no longer advances (test_leaving_the_zone_on_the_approach_side_never_advances, hairpin variants pass). BUT see gap CR-01: the fix regresses real roundings"
    - "G-4-R03 VIREZ/EMPANNEZ takeover of the primary box (route_logic tackCue -> primaryView; layout test fr/en/sl at 3 sizes)"
    - "G-4-R04 helm polar VMG-linear on deep segments: shipped X35 down target 180.0 deg at 14/16/20/25 kn (my run); helm/router agreement test passes"
    - "G-4-R05 durability thread: fsync/.bak/rename tail off the loop in core and ingest; stalled-fsync promptness tests pass; CI soak PASS with background mode (var/soak-04-10/20261109T105127Z-ci)"
    - "G-4-R06 routing worker raise_oom_score_adj(500) first in _pool_init; real forkserver test passes"
    - "G-4-R07 lock unlocks only in pointerup after a 2-4 s press (lp.up), void after MAX_MS"
    - "G-4-R08 PAS DE GPS badge (flag key gps) + primary label"
    - "G-4-R09 text colours floored at rgb(110,0,0); #primary-label at --f-label / --fg (see advisory WR-04)"
    - "G-4-R10 diag-theme.js in <head>, html.theme-night red-on-black, #diag-frame background var(--bg), theme propagated to the frame"
    - "G-4-R11 user-select/-webkit-touch-callout none on #helm-col/#topbar/.map-ctrls; overscroll-behavior-y none on html, body"
    - "G-4-R12 StartLimitIntervalSec=0 in both Plan-B units, asserted by tests/deploy/test_units.py (see advisory WR-06)"
  gaps_remaining: []
  regressions:
    - "CRSE-03 auto-advance (Phase 2 behaviour, re-touched by 04-09): a real rounding of a non-hairpin mark (turn <= 90 deg) that leaves the zone on the approach side of the abeam line never advances any more; dbcd536 advanced the same tracks (review CR-01, reproduced independently)"
gaps:
  - truth: "04-09 / G-4-R02: real roundings still advance after the past-the-mark gate (CRSE-03 auto-advance is not regressed by the gap closure)"
    status: failed
    reason: "_past_mark() (course.py:675-688) accepts a non-hairpin zone exit only if dot_in > 0 AT THE EXIT; the _beyond latch set at :754 is read only in the hairpin branch. When the boat leaves the zone with dot_in < 0 and spent < 10 s continuously past the abeam line (the _abeam debounce), the candidate never fires; at 2 nm the gate reset clears _entered and the course stays on the rounded mark for good, the router and laylines steering back to it. Independent repro (proper-arc rounding, 3 m GPS noise, 5 seeds): a committee mark (CRSE-02 add_mark, default radius 0.05) entered only 19 m beyond the real buoy along the incoming leg, rounded at 0.01 nm, then sailed out at more than 90 deg from the incoming leg (turn 45-90 deg + the beat tack away from the incoming leg, or a 90 deg turn sailed straight) is STUCK in 4/5 to 5/5 runs for every error >= 19 m; dbcd536's course.py advances every one of these tracks (0/5 stuck). Reviewer's tight-rounding repro also reproduced: rounding at 0.005 nm (60-89 deg turn, +45/50) STUCK; at 0.008 nm, 9 kn, STUCK. The shipped Course A/B marks (Plić 43, Blitvenica 41, Mulo -61; rounded at 0.02-0.2 nm) still advance in my runs (0/5 stuck), so the defect hits committee/tapped marks and very tight roundings, which CRSE-02 makes a supported race path."
    artifacts:
      - path: "src/jabuka/nav/course.py"
        issue: "_past_mark non-hairpin branch ignores the _beyond latch and the outgoing leg; the CR-02 Annuler path sets _beyond as rounding evidence (:741) but a non-hairpin exit ignores it too. _set() (:301-309) resets the FSM only on (active_idx, mark_id) change, so edit_mark/set_leg on the active mark keep a latch computed against the old geometry (review WR-01): this must be fixed together, since the fix makes the latch matter at every mark"
      - path: "tests/nav/test_course.py"
        issue: "no regression for a committee mark entered beyond the buoy, nor for a tight rounding with a > 90 deg exit"
    missing:
      - "Non-hairpin zone exit accepts the latch and/or past-along-the-outgoing-leg. The reviewer's version (`self._beyond or dot_in > 0.0 or (dot_out is not None and dot_out > 0.0)`) was checked by me via monkeypatch: tests/nav/test_course.py 36/36 still pass (incl. the G-4-R02 approach-side regressions) and all my committee-mark tracks advance (0 stuck). The planner must add a test that a same-side approach retreat heading toward the outgoing-leg side (dot_out > 0 while dot_in < 0, never past) still does not advance, or justify accepting it"
      - "Reset the rounding FSM (or at least _beyond/_entered/_cand_since) when the active mark's lat/lon, its leg side/radius, or the next mark (turn) changes (review WR-01)"
      - "Regression tests: committee mark entered 20-90 m beyond the buoy with a > 90 deg exit advances; tight rounding (<= 0.008 nm) with a 60-89 deg turn + 45-50 deg advances; edit of the active mark after the latch is set does not advance without passing the corrected mark"
      - "Re-run the full gate on both venvs, recompute the freeze fingerprint and re-provision the Pi (the installed c1bab550... will no longer equal HEAD)"
advisory:
  - finding: "Review WR-02: in background mode a failure of the fsync/.bak/rename tail is only logged + counted. CourseStore._commit clears 'Écriture du parcours impossible' right after the synchronous temp write; core Diag shows bg_write_errors only as a raw kv row (CORE_ERRORS in diag_logic.js:56 does not list it, no red line); the ingest's own durability counter is never exported (bus_stats/raw_errors no longer see fsync failures)"
    category: other
    reason: "Confirmed by code read. Not a gap: the 04-10 truth scopes 'never silent' to 'logged and counted (diag core bg_write_errors)', which holds; ENOSPC/EACCES/EROFS still raise synchronously (503 / alert); only fsync EIO/link/rename failures on a dying SD go background. Cheap fix before the freeze: add bg_write_errors to CORE_ERRORS (+fr/en/sl string) and export the ingest's background_status()['errors'] in its heartbeat as a SOURCE_ERRORS key"
    evidence_status: "code read (atomicio.py:197-237, course.py:289-299, diag_logic.js:56-57, fastnet_main.py)"
  - finding: "Review WR-03: rawlog._cadence sets _fsync_inflight=True before atomicio.fsync_fd; if os.dup (EMFILE) or the first worker Thread.start raises, on_done never runs and every later cadence fsync is skipped for the process lifetime"
    category: other
    reason: "Confirmed by code read (rawlog.py:208-213). Trigger needs fd exhaustion or a failed thread start; once the worker is alive _submit never starts a thread again, and the worker loop survives job exceptions. Rotation/close still fsync. Two-line fix (reset on exception, and in _open)"
    evidence_status: "code read; no deterministic trigger in procedure"
  - finding: "Review WR-04: the night text floor collapses the --fg / --dim tiers: at brightness 0.4 both are rgb(110,0,0) (before 04-12: 102 vs 51); at 0.5, 127 vs 110; the floor compresses dim for every k < 0.86. At night --good/--bad/--accent are already #ff0000, so dimming is the only colour cue for link-lost (#tab-barre.stale) and stale wind (wind-stale)"
    category: other
    reason: "Deterministic from app.js:95,128-136 and app.css:19-29 (arithmetic). Not counted as a gap: the 04-12 truth itself specifies --dim = rgb(110,0,0) at 40 %, and the stale states keep a textual cue (VENT PÉRIMÉ label now at --f-label size, PAS DE GPS, link-lost banner), so no stale number is presented without words. Recommended: keep a ratio (e.g. floor --fg at ~160 and --dim at ~70, or dim = fg x 0.5 floored) and assert fg - dim >= N at min brightness in tests/ui/test_night.py. Also checked on board (human item 8)"
    evidence_status: "deterministic code arithmetic; perceptual impact needs the real tablet"
  - finding: "Review WR-05: a MANUEL wind entered while trusted UTC was unknown (t_set_wall None), or evaluated while UTC is unknown, is never stale, so the VIREZ/MAUVAIS BORD cue can run on a TWD of unknown age"
    category: other
    reason: "Confirmed by code read (wind.py:380-388, helm_logic.js:167-169). Pre-existing design (WR-03 'MANUEL âge ?' badge); the window is a power cycle at sea before the GPS fix with Fastnet also down. Fix suggested by the reviewer (treat unknown-age MANUEL as stale for cues, or age on t_set_mono)"
    evidence_status: "code read"
  - finding: "Review WR-06: one crash of jabuka-fastnet-relay (Restart=on-failure, default RestartMode=normal, StopWhenUnneeded=yes) can stop fastnet2ip through BindsTo= (a stop, not a failure, so its Restart=on-failure does not fire), and the restarted relay is then stopped as unneeded: Plan B stays down. StartLimitIntervalSec=0 does not address this path"
    category: other
    reason: "Unit text confirmed (relay :18-19,:29; fastnet2ip :24,:27,:34). The systemd transition (auto-restart through failed/inactive with RestartMode=normal) is per systemd.service(5) and not reproduced here (no unit mutation allowed in verification). Plan B is the fallback feed, not the helm path; G-4-R12's literal truth holds. Recommended: RestartMode=direct on the relay (Trixie systemd 257) or Requires=+PartOf=; then the reviewer's kill -9 check on the Pi (human item 10)"
    evidence_status: "unit text + systemd docs; Pi check pending"
  - finding: "Review WR-07: an exception from rawlog.close() in fastnet_main._run's finally skips disable_background(20.0) and sock.close()"
    category: other
    reason: "Confirmed (fastnet_main.py:443-451). Consequence on a clean stop: queued fsyncs of data already in the page cache are not awaited; the kernel still writes it back. Only a power cut within seconds of a stop that also hit ENOSPC/EIO loses tail lines. try/except/finally fix"
    evidence_status: "code read"
  - finding: "Review IN-01..IN-04 (polar header overstates agreement beyond the last TWA; duplicated leg geometry in _abeam/_leg_dots; Diag night red ignores the brightness slider; rawlog keeps a dead os import for test patching)"
    category: other
    reason: "Info only. IN-02 is worth doing with the CR-01 fix (one geometry helper). IN-03 adds to WR-04: Diag at night is the brightest red screen on a dimmed tablet"
    evidence_status: "code read"
  - finding: "Carried from the previous rounds: 04-08 WR-01 (user-scope empty journal counted complete, off-procedure), IN-01/IN-03 (journald loss, end_signal race), WR-04 git-less F4 scope, '.bak restauré' alert wording"
    category: other
    reason: "Unchanged by 04-09..04-12 (soak/freeze files untouched in dbcd536..HEAD); still fail closed or off-procedure"
    evidence_status: "unchanged code; previous repros"
human_verification:
  - test: "After the CR-01 fix: rebuild the wheelhouse from the final HEAD and re-provision the Pi; the installed fingerprint must equal FINGERPRINT_SH of HEAD src/jabuka (today both are c1bab550c801a27f878ac9c34414761e3403e218bc52d1b7913d20b1f00dba30, which the fix will change). Replace the Pi PSU first: vcgencmd get_throttled = 0x50005 (under-voltage now and since boot)"
    expected: "Installed fingerprint = HEAD; vcgencmd get_throttled = 0x0 after a run under load"
    why_human: "Physical PSU swap and Pi provisioning"
  - test: "Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length, never Ctrl-C at the end"
    expected: "Verdict PASS, exit 0, end_signal null, duration_s 129600, sim_s >= 129600, scenario_sha256 of HEAD; freeze-check F3 PASS"
    why_human: "About 40 min of wall time on the final HEAD"
  - test: "Pi 3B system-scope soak (ROADMAP SC1), inside tmux: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`; no Ctrl-C at the end; scp the run dir, reboot, `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0"
    expected: "Exit 0, PASS, end_signal null, journal.complete true with core/ingest entries > 0, tick ratio >= 0.95, core/worker RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true; freeze-check F4 PASS. This is also the first Pi run with the durability thread and the worker oom_score_adj +500"
    why_human: "Needs the real Pi 3B with its installed units"
  - test: "Record the Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer'"
    expected: "Table filled; numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j); at least one pull right after a course change (the background durability tail)"
    expected: "Services come back, logcheck OK, course/settings intact or a visible '.bak restauré' alert, no .NAME.<n>.tmp left after the next write"
    why_human: "Physical power interruption"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md (lock review/hash, tag race-2026, wheelhouse from the tag, Pi re-provisioned, freeze-check all PASS except F8 WARN / F9 HUMAN)"
    expected: "freeze-check exit 0; only configuration changes afterwards"
    why_human: "Owner decisions and a future-dated event"
  - test: "Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3)"
    expected: "Both units active, logcheck OK, fastnet-probe --file exits 0, same fingerprint on both cards = the Pi report's code.sha256, tablet opens http://10.42.0.1"
    why_human: "Physical SD cards and Pi boot"
  - test: "12 Nov: replay the boat's real capture (`bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`)"
    expected: "5 PASS lines; every decoded inventory path served by /api/state; logcheck OK"
    why_human: "The real Hercules capture only exists on 12 Nov"
  - test: "On-board commissioning per docs/COMMISSIONING.md §2–§9 (12–13 Nov), including the 04-11/04-12 helm behaviours on the real tablet at night at the lowest brightness: VIREZ/EMPANNEZ takeover, VENT PÉRIMÉ, PAS DE GPS (GPS unplugged), padlock release-to-unlock with a wet finger, a resting finger never unlocks, no pull-to-refresh / long-press sheet on the helm, Diag opens red-on-black with no white flash; can a stale (dimmed) block be told from a live one (WR-04)?"
    expected: "Helm tablet shows live/MANUEL/GRIB wind and laylines to the first mark over the boat Wi-Fi, readable at night (ROADMAP SC4); every takeover readable at a glance"
    why_human: "Real boat, instruments, Android tablet and night conditions"
  - test: "Plan B single-crash check on the Pi (review WR-06): `sudo systemctl start fastnet2ip; sudo kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 10; systemctl is-active fastnet2ip jabuka-fastnet-relay`"
    expected: "Both active (if not, apply RestartMode=direct or Requires=+PartOf= before the freeze)"
    why_human: "Needs the Pi's systemd and the deployed units"
  - test: "Owner reads docs/COMMISSIONING.md, docs/SOAK.md and docs/FREEZE.md and adjusts the 12 Nov timings; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md and docs/I18N-SL-REVIEW.md (new 04-11/04-12 strings: helm.windStale, flag.noGps, route.cueNow, the lock hint)"
    expected: "Timings fit; FR wording clear; SL wording correct"
    why_human: "Owner logistics and native-language review"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-09T13:02:22Z (main bfed642; last code commit 89506ad, gate var/gate-04-12.log 13:37 after it)
**Status:** gaps_found
**Re-verification:** Yes, after gap-closure plans 04-09..04-12 (G-4-R01..R12 from 04-PROJECT-REVIEW / 04-UAT)

## Verdict on review CR-01: confirmed, and it is a blocker

I reproduced CR-01 myself. It falsifies the 04-09 must-have "real roundings still advance" and regresses CRSE-03 (auto-advance after rounding) on the race path. The phase core value is a trustworthy "steer this" after every mark. A course that stays on a mark the boat has already rounded, with the router and laylines steering back to it, is a confident wrong answer. The previous code (dbcd536) advanced on these same tracks.

**Mechanism (code read, course.py:675-688, :752-758).** For a mark whose turn is 90 deg or less, a zone exit counts only if `dot_in > 0` at the moment of the exit. The `_beyond` latch is updated on every tick but read only in the hairpin branch. The only other trigger is `_abeam`, which needs 10 consecutive seconds past the abeam line. If the boat leaves the zone on the approach side of the abeam line without those 10 s, it is stuck. At 2 nm the gate reset clears `_entered`, and nothing can advance the course after that.

**Reviewer's scripts.** I ran them on HEAD.
- `stuck.py`: rounding at 0.005 nm with a 60-89 deg turn and +45/50 → STUCK in every case. At 9 kn, a 0.008 nm rounding is also STUCK. Roundings at 0.01 nm or more advance through `_abeam`.
- `stuck2.py`: a committee mark entered 0.05 nm beyond the buoy, or a 0.0 nm error with an instant turn → STUCK.
- The same `stuck2` on `git show dbcd536:src/jabuka/nav/course.py`: all five tracks advance.

**My own model** (`verify_cr01.py` in the scratchpad: proper circular arc, 3 m GPS noise, 5 seeds):

| Scenario | HEAD | dbcd536 |
| --- | --- | --- |
| Shipped marks (Course A/B: Plić 43, Blitvenica 41, Mulo -61), rounded at 0.02-0.2 nm, exit along the leg or +45 | 0/5 stuck in every case | — |
| Committee mark (add_mark, radius 0.05) entered **19 m** beyond the buoy, rounded at 0.01 nm, turn 45/60/75 + beat tack away from the incoming leg | 4/5 to 5/5 stuck | 0/5 stuck |
| Same, error 37/56/93 m | 5/5 stuck | 0/5 stuck |
| Committee mark, **90 deg turn sailed straight**, error >= 19 m | 4/5 to 5/5 stuck | 0/5 stuck |

So the fixed race marks are safe in my model. The defect hits marks that are tapped or typed (CRSE-02, which is how committee marks are entered) and very tight roundings. An error of 19 m is normal for a mark tapped on the map, so this is a realistic race path, not an edge case. The crew can recover by pressing "next" by hand (CRSE-03), but nothing tells them to.

**Fix check.** I monkeypatched the reviewer's proposed `_past_mark` (latch, or `dot_in > 0`, or `dot_out > 0`).
- `tests/nav/test_course.py`: 36/36 pass, including the G-4-R02 approach-side regressions.
- Every committee-mark track above advances.
- Open point: the `dot_out > 0` term may accept a retreat on the approach side towards the outgoing-leg side. The planner must pin that case with a test.
- WR-01 (the latch survives an edit of the active mark) must be fixed together, because after the fix the latch matters at every mark.

## User Flow Coverage (MVP mode)

User story (as in 04-04..04-12): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Prove 36 h on the laptop | One command, all faults, budgets | Harness unchanged since 04-08. CI soak PASS with background mode (var/soak-04-10, d7c3f11e…). The full race-36h on the final HEAD is still to run | ✓ code / ? human |
| Prove it on the Pi 3B | System-scope soak, identity, journal | Pi provisioned with HEAD: installed c1bab550… = my FINGERPRINT_SH of `git archive HEAD src/jabuka`. **get_throttled 0x50005 (under-voltage)** | ? human (PSU swap first) |
| Freeze on 11 Nov | Checker green only for real runs | Unchanged since 04-08 | ✓ checker / ? event |
| Spare SD | Same state | SPARE-SD.md | ? human |
| Commission 12–13 Nov | Timed runbook | COMMISSIONING.md (lock gesture rows updated by 04-12) | ✓ doc / ? on board |
| **Tablet trustworthy for the whole race** | Correct next mark after every rounding; takeovers on stale wind / no GPS / tack due; readable at night | Takeovers ✓ (tests). **The course gets stuck after some real roundings of committee marks (CR-01)** | ✗ **FAILED** |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h soak on the Pi 3B with faults | ? HUMAN | Pi under-voltage today; run pending |
| SC2 | Runbook exists, dry-run, all topics | ✓ VERIFIED | Regression: gate-04-12 green (1670 passed, 4 skipped ×2, `check: ok`, EXIT=0); docs tests bind the 04-12 gesture edits |
| SC3 | Freeze, spare SD, 12 Nov capture | ? HUMAN | Future-dated |
| SC4 | Helm tablet wind + laylines at night | ? HUMAN | Software present; CR-01 is a separate failed truth |
| 01..08 (51 truths) | Previous rounds | ✓ VERIFIED (regression) | soak/freeze/tools files untouched in dbcd536..HEAD; gate green |
| 09-1 | G-4-R02: a Plić approach-side retreat never advances | ✓ VERIFIED | `test_leaving_the_zone_on_the_approach_side_never_advances` and `test_hairpin_approach_side_retreat_never_advances[A/B]` pass (3.13 + 3.14) |
| 09-2 | Zone exit gated on past-the-mark (non-hairpin dot_in > 0; hairpin latch + dot_out > 0) | ✓ VERIFIED (as specified) | course.py:675-688, :756. **The specified rule is itself the cause of 09-3** |
| 09-3 | Real roundings still advance | ✗ FAILED | The enumerated cases pass. Committee-mark and tight-rounding roundings are stuck forever (CR-01, my repro, regression vs dbcd536) |
| 09-4 | Helm polar VMG-linear; down 180 deg from 14 kn; helm/router agree within 0.1 deg | ✓ VERIFIED | My run: down_twa 180.0 at 14/16/20/25 kn. `test_helm_and_router_targets_agree_on_the_shipped_polar` and `test_threshold_matches_the_router` pass. `_interp_curve` is wired into `Polar.speed` |
| 09-5 | Both venvs green; gate-04-09 | ✓ VERIFIED | gate-04-09.log; my targeted runs |
| 10-1 | No fsync on the loop; logs and the atomic tail go to jabuka-durable | ✓ VERIFIED | atomicio.py:122-149, 197-257. rawlog uses `fsync_fd`. `enable_background` is called in core serve() (:536) and ingest _run() (:393) |
| 10-2 | Stalled fsync: tick, course, settings, manual wind and event each return < 0.5 s; drain completes | ✓ VERIFIED | `tests/test_background_durability.py` passes (3.13 + 3.14) |
| 10-3 | Durability semantics: sync temp write raises ENOSPC; FIFO order; .bak; failures logged and counted in diag core | ✓ VERIFIED | Tests pass; main.py:237-259 `bg_write_errors`. See advisory WR-02 (no red alert; ingest counter not exported) |
| 10-4 | Orphan `.NAME.<n>.tmp` swept once per file per process; readers never sweep | ✓ VERIFIED | `_sweep_orphans` (:165-194); tests pass |
| 10-5 | Opt-in per process; drain at exit | ✓ VERIFIED | main.py:553, fastnet_main.py:449. See WR-07: a close exception skips the ingest drain |
| 10-6 | Worker oom_score_adj = max(500, current); parent unchanged | ✓ VERIFIED | pool.py:49-72; the real forkserver test in tests/route/test_pool.py passes |
| 10-7 | StartLimitIntervalSec=0 in both Plan-B units, tested | ✓ VERIFIED | relay:19, fastnet2ip:27; `tests/deploy/test_units.py` passes. WR-06 single-crash path → advisory + human item 10 |
| 10-8 | Both venvs, CI soak PASS with background mode, gate-04-10 | ✓ VERIFIED | var/soak-04-10/20261109T105127Z-ci PASS, end_signal null; gate-04-10.log |
| 11-1 | VIREZ/EMPANNEZ primary-box takeover (due or wrong tack), inverted | ✓ VERIFIED | route_logic `tackCue` → helm_logic primaryView:200 → helm.js:150 `cue-word`; logic + Playwright tests pass |
| 11-2 | Cue word fits fr/en/sl at 3 sizes; night red-only | ✓ VERIFIED | `tests/ui/test_helm_column.py` passes |
| 11-3 | Stale MANUEL: VENT PÉRIMÉ, blocks dimmed, no tack cue anywhere | ✓ VERIFIED | helm_logic:167, 196-198, 259-271; `wind-stale` class (helm.js:153). Tests pass. See WR-04 and WR-05 advisories |
| 11-4 | PAS DE GPS badge and label when lat/lon are missing | ✓ VERIFIED | `noPosition` (:158), flag key `gps` (:176, helm.js:178) |
| 11-5 | Takeover priority order; existing tests unchanged | ✓ VERIFIED | primaryView order (192 → 196 → 200); logic tests pass |
| 11-6 | New strings in FR/EN/SL; SL sheet regenerated | ✓ VERIFIED | tests/test_i18n.py parity passes |
| 11-7 | Node logic + UI (JABUKA_REQUIRE_UI=1) green; gate-04-11 | ✓ VERIFIED | My 3.13 run with JABUKA_REQUIRE_UI=1: 400 passed |
| 12-1 | Unlock only on lift after a 2-4 s press; a never-lifting press is void | ✓ VERIFIED | lock_logic `up()` window (:42-57), lock.js:208 `lp.up` → `apply(false)`; tick only calls `check`. `tests/test_lock_logic.py` and `test_lock_wake.py` pass |
| 12-2 | Lock hint/aria and docs describe the release gesture | ✓ VERIFIED | i18n + docs diffs; i18n UI test passes |
| 12-3 | Text colours floored at rgb(110,0,0); dim at 40 % = 110 | ✓ VERIFIED (as specified) | app.js:95, 130-136; test_night passes. Tier collapse → advisory WR-04 |
| 12-4 | Primary label at --f-label / --fg; still fits | ✓ VERIFIED | app.css:169; test_tablet_hardening and test_helm_column pass |
| 12-5 | Diag night: no white flash | ✓ VERIFIED | diag.html:8 classic `diag-theme.js` before the module; app.css:272 frame background var(--bg); app.js:157 propagates to the frame |
| 12-6 | No selection, callout or pull-to-refresh on the helm; inputs keep selection | ✓ VERIFIED | app.css:45, 274-278 |
| 12-7 | Both venvs green; gate-04-12 | ✓ VERIFIED | var/gate-04-12.log: 1670 passed, 4 skipped ×2, `check: ok`, EXIT=0 (13:37, after 89506ad) |

**Score:** 77/82 truths verified. 1 failed (09-3, CR-01). 4 human-only (SC1, SC3, SC4, 03-1). 0 present-but-behaviour-unverified.

### Review warnings: gap or advisory

| Finding | Reproduced / confirmed | Classification | Why |
| --- | --- | --- | --- |
| CR-01 | Yes, independently (table above) | **🛑 GAP (blocker)** | Failed truth 09-3; CRSE-03 regression on the race path |
| WR-01 latch survives an edit of the active mark | Code read (_set :301-309) | **Folded into the CR-01 gap** | It becomes a live hole at every mark as soon as CR-01 is fixed with the latch |
| WR-02 background write failures not alerted; ingest counter not exported | Code read | 📋 Advisory | The truth's scope holds; the trigger is a dying SD (fsync EIO); recommended before the freeze |
| WR-03 `_fsync_inflight` stuck on a pre-queue raise | Code read | 📋 Advisory | Needs EMFILE or a failed first thread start |
| WR-04 night floor collapses fg/dim | Deterministic arithmetic | 📋 Advisory + human item 9 | The plan specified the values; stale states keep text cues |
| WR-05 unknown-age MANUEL never stale | Code read | 📋 Advisory | Pre-existing design; narrow window |
| WR-06 Plan B dies after one relay crash | Unit text + systemd doc | 📋 Advisory + human item 10 | Fallback feed, not the helm path; needs a Pi check |
| WR-07 ingest close exception skips the drain | Code read | 📋 Advisory | Data is already in the page cache |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| src/jabuka/nav/course.py | `_beyond`, `_leg_dots`, `_past_mark`, gated zone exit | ⚠️ PRESENT, WIRED, DEFECTIVE | Behaves as planned; the planned rule causes CR-01 |
| src/jabuka/nav/polar.py | VMG_SEGMENT_MIN_DEG, `_interp_curve` used by speed() | ✓ VERIFIED | |
| src/jabuka/common/atomicio.py | Background mode, fsync_fd, sweep | ✓ VERIFIED | |
| src/jabuka/ingest/rawlog.py | fsync_fd, `_fsync_inflight` | ✓ VERIFIED | WR-03 advisory |
| src/jabuka/core/main.py, src/jabuka/ingest/fastnet_main.py | enable + drain | ✓ VERIFIED | WR-07 advisory |
| src/jabuka/route/pool.py, pool_probe.py | `raise_oom_score_adj` | ✓ VERIFIED | |
| deploy/systemd/jabuka-fastnet-relay.service, fastnet2ip.service | StartLimitIntervalSec=0 | ✓ VERIFIED | WR-06 advisory |
| web/static route_logic.js, helm_logic.js, helm.js, app.css, i18n.js | Takeovers | ✓ VERIFIED | |
| web/static lock_logic.js, lock.js, app.js, diag-theme.js, diag.css, diag.html | Lock / night / Diag | ✓ VERIFIED | |
| tests (test_course, test_polar_vmg, test_background_durability, test_pool, test_units, helm/route/lock logic, ui/*) | New regressions | ✓ VERIFIED, with one gap | Missing: committee-mark and tight-rounding tests |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| course `_fsm` | `_advance` | `_abeam(...) or (d > zone and _past_mark(dots))` | ✓ WIRED; the logic is wrong for non-hairpin marks (CR-01) |
| polar.speed / targets | nav_service helm target | `_interp_curve` | ✓ WIRED |
| core serve / ingest _run | atomicio background | `enable_background` | ✓ WIRED |
| atomic_write_json callers | `_finish_atomic` on jabuka-durable | `_submit` | ✓ WIRED |
| `_pool_init` | /proc/self/oom_score_adj | `raise_oom_score_adj(500)` | ✓ WIRED |
| tackCue | primaryView → helm.js | `cue` / `cue-word` | ✓ WIRED |
| nav.wind.stale | windStale → `wind-stale` | helmView | ✓ WIRED |
| lock.js pointerup | `lp.up` | `apply(false)` | ✓ WIRED |
| diag.html head | diag-theme.js | classic script | ✓ WIRED |
| app.js theme switch | diag-frame | `classList.toggle('theme-night')` | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| Active mark → router/laylines | `course.active_idx` | Rounding FSM on GPS ticks | Yes, but it never advances after some real roundings | ✗ HOLLOW on the CR-01 path |
| Helm downwind target | `polar.targets` | Shipped .exp polar | 180.0 deg from 14 kn | ✓ FLOWING |
| Diag core `bg_write_errors` | `atomicio._errors` | Durability thread | Counted, not alerted | ⚠️ advisory WR-02 |
| Ingest background errors | `atomicio._errors` (ingest process) | Durability thread | Not exported | ⚠️ advisory WR-02 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Gap-plan tests (3.14) | `.venv/bin/python -m pytest tests/nav tests/route/test_pool.py tests/route/test_polar_grid.py tests/test_background_durability.py tests/deploy/test_units.py tests/test_*logic.py tests/test_i18n.py tests/test_no_wallclock.py` | 383 passed | ✓ PASS |
| Same + UI (3.13, JABUKA_REQUIRE_UI=1) | ui/test_tablet_hardening, test_night, test_helm, test_helm_column, test_lock_wake | 400 passed | ✓ PASS |
| CR-01, reviewer scripts | stuck.py / stuck2.py on HEAD; stuck2 on dbcd536 course.py | HEAD STUCK; dbcd536 all advance | ✗ FAIL (regression) |
| CR-01, my model | verify_cr01.py (arc, noise, seeds) | Shipped marks 0 stuck; committee mark ≥ 19 m error 4-5/5 stuck; dbcd536 0/5 | ✗ FAIL |
| Reviewer fix candidate | monkeypatched `_past_mark` → test_course.py and my sim | 36/36 pass, 0 stuck | ℹ️ fix is viable |
| Helm polar | `default_polar().targets(tws)` | Down 180.0 at ≥ 14 kn | ✓ PASS |
| Freeze fingerprint at HEAD | `package_fingerprint(git archive HEAD src/jabuka)` | c1bab550c801…dba30 = Pi installed | ✓ PASS (changes with the fix) |
| Full gate | var/gate-04-12.log | 1670 passed, 4 skipped ×2, `check: ok`, EXIT=0 | ✓ PASS |
| Debt markers / removed asserts | `git diff dbcd536..HEAD` | No TBD/FIXME/XXX/TODO/HACK added; 0 `assert` lines removed in tests | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exists, and no plan declares one. I ran the runnable checks above directly.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-02 | 04-01, 04-03..04-08, 04-10 | ~36 h unattended on the Pi 3B, accelerated soak | ✓ SATISFIED (software) / ? NEEDS HUMAN | The durability thread and worker OOM ordering are added; CI soak PASS. The Pi soak is pending, and the PSU must be changed first |
| REL-03 | 04-02, 04-04, 04-06..04-08, 04-12 (docs) | Commissioning runbook | ✓ SATISFIED (doc) / ? on board | Lock gesture rows updated |
| CRSE-03 (Phase 2, touched by 04-09) | 04-09 | Auto-advance after rounding | ✗ REGRESSED | CR-01 |
| WIND-01, NAV-01 (04-09); REL-01 (04-10); HELM-02, ROUT-06, WIND-04 (04-11); HELM-03/04/05 (04-12) | Gap plans | Cross-phase IDs | ✓ (evidence above) | Phase 2/3 traceability rows are not changed by this phase |

There are no orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and plans claim both. REQUIREMENTS.md still shows "Gaps Found" for both, which is correct.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| src/jabuka/nav/course.py | 686-687 | Latch computed but ignored for non-hairpin marks | 🛑 Blocker | CR-01 |
| src/jabuka/nav/course.py | 301-309 | FSM not reset on a geometry edit | ⚠️ Warning (folded into the gap) | WR-01 |
| src/jabuka/web/static/diag_logic.js | 56 | `bg_write_errors` not in CORE_ERRORS | 📋 Advisory | WR-02 |
| src/jabuka/ingest/rawlog.py | 210-213 | Flag set before a call that can raise | 📋 Advisory | WR-03 |
| src/jabuka/web/static/app.js | 130-136 | Floor equalises fg/dim at low brightness | 📋 Advisory | WR-04 |
| src/jabuka/ingest/fastnet_main.py | 446-451 | Drain skipped on a close exception | 📋 Advisory | WR-07 |
| docs/I18N-SL-REVIEW.md.bak | — | Untracked backup in docs/ | ℹ️ Info | Delete or ignore before the freeze (F-clean tree) |

### Human Verification Required

See the `human_verification` frontmatter. In short:

1. **PSU and Pi (first).** Swap the PSU (0x50005), then re-provision the Pi after the CR-01 fix.
2. **Laptop soak.** race-36h on the final HEAD.
3. **Pi soak.** System-scope run (SC1).
4. **Pi budgets.** Fill in SOAK.md.
5. **Power pulls.** 5 pulls, one right after a course change.
6. **Freeze.** On 11 Nov.
7. **Spare SD.** Clone it and boot it.
8. **Capture replay.** The 12 Nov capture.
9. **On-board night check.** Include the 04-11/04-12 behaviours and the WR-04 dim-vs-live question.
10. **Plan B.** The single-crash check on the Pi (WR-06).
11. **Proofreading.** Owner reading; Slovenian proofreading of the new strings.

### Gaps Summary

**One blocker: review CR-01, which I reproduced independently.** Gap closure G-4-R02 replaced the lenient zone-exit rule with "past the mark along the incoming leg *at the exit*" for every mark that is not a hairpin.
- It fixes the approach-side retreat it was aimed at.
- It also stops some real roundings from ever advancing. The case that matters is a committee or tapped mark (CRSE-02) entered 20 m or more beyond the buoy, then left at more than 90 deg from the incoming leg (a beat on the far tack, or a 90 deg reach).
- The course then stays on the rounded mark for the rest of the race unless the crew notices and presses "next".
- dbcd536 advanced every one of these tracks, so this is a regression of CRSE-03 on the race path.

**The fix is small:**
- Use the `_beyond` latch, and possibly `dot_out > 0`, in the non-hairpin branch.
- Reset the FSM when the active mark's geometry is edited (WR-01).
- Add the missing regression tests.
- Re-run the gate and re-provision the Pi.

The reviewer's candidate keeps all 36 course tests green and clears my repro. The planner must pin the `dot_out > 0` approach-side case with a test.

**The other 11 G-4-R gaps are closed in code and tests.** Reviews WR-02..WR-07 are confirmed but non-blocking (see advisory). WR-02 (Diag alert for background write errors) and WR-06 (Plan B `RestartMode=direct`) are cheap and recommended before the 11 Nov freeze.

**Human-only items remain:** the Pi with a new PSU, the soaks, power pulls, the freeze, the spare SD, the capture replay, the on-board night commissioning, and proofreading.

---

_Verified: 2026-11-09T13:02:22Z_
_Verifier: Claude (gsd-verifier)_
