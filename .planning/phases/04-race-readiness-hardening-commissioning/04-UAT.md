---
status: testing
phase: 04-race-readiness-hardening-commissioning
source: [04-VERIFICATION.md]
started: 2026-11-09T18:30:00Z
updated: 2026-11-09T18:30:00Z
---

## Current Test

number: 1
name: Swap the Pi PSU (vcgencmd get_throttled = 0x50005 today), then confirm the installed code identity
expected: |
  Installed fingerprint = HEAD; vcgencmd get_throttled = 0x0 after a run under load
awaiting: user response

## Tests

### 1. Swap the Pi PSU (vcgencmd get_throttled = 0x50005 today), then confirm the installed code identity
test: Swap the Pi PSU (vcgencmd get_throttled = 0x50005 today), then confirm the installed code identity: on the Pi, the installed package fingerprint must equal HEAD's 8b0a3bc46c45900632b975c164a215dd8207a8c883a5b50f4470c705358f19c8 (147 files, recomputed by me with package_fingerprint(src/jabuka) on a clean tree). The orchestrator reports the Pi was re-provisioned today from this HEAD with that fingerprint, services active, watchdog armed (15 s), relay unit RestartMode=direct; not re-checked by me. If any src/jabuka commit lands before the freeze, rebuild the wheelhouse and re-provision again
expected: Installed fingerprint = HEAD; vcgencmd get_throttled = 0x0 after a run under load
why_human: Physical PSU swap and Pi access
result: [pending]

### 2. Laptop race-36h soak on the final pre-freeze HEAD
test: Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length, no Ctrl-C
expected: PASS, exit 0, end_signal null, duration_s 129600, scenario_sha256 of HEAD; freeze-check F3 PASS
why_human: About 40 min of wall time on the final HEAD
result: [pending]

### 3. Pi 3B system-scope soak (ROADMAP SC1) in tmux, after the PSU swap
test: Pi 3B system-scope soak (ROADMAP SC1) in tmux, after the PSU swap: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`; scp the run dir, reboot, `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0
expected: Exit 0, PASS, journal.complete true, tick ratio >= 0.95, core/worker RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true; bg_write_errors 0 in the Cœur and Fastnet Diag tables; freeze-check F4 PASS
why_human: Needs the real Pi 3B with its installed units and a healthy PSU
result: [pending]

### 4. Record Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer'
test: Record Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer'
expected: Table filled; numbers fit the 1 GB Pi
why_human: Hardware measurement
result: [pending]

### 5. 5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j); at least one right a
test: 5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j); at least one right after a course change
expected: Services come back, logcheck OK, course/settings intact or a visible '.bak restauré' alert, no .NAME.<n>.tmp left after the next write
why_human: Physical power interruption
result: [pending]

### 6. Plan B single-crash check on the Pi (system scope)
test: Plan B single-crash check on the Pi (system scope): `sudo systemctl start fastnet2ip; sudo kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 15; systemctl is-active fastnet2ip jabuka-fastnet-relay; systemctl show -p NRestarts fastnet2ip jabuka-fastnet-relay`; then, with a replay or the bus connected (the Fastnet adapter is not connected today), `timeout 15 nc -ul 2002 | head -3` on the laptop joined to the jabuka AP
expected: Both active; relay NRestarts >= 1 (fastnet2ip may also show 1: it exits on pty EIO and restarts); NMEA lines arrive on UDP 2002 after the kill
why_human: Needs the Pi's system-scope systemd, the deployed units and a data source on the relay
result: [pending]

### 7. Feature freeze on 2026-11-11 per docs/FREEZE.md (delete or ignore the untracked docs/I18N-SL-REVIEW
test: Feature freeze on 2026-11-11 per docs/FREEZE.md (delete or ignore the untracked docs/I18N-SL-REVIEW.md.bak first)
expected: freeze-check exit 0 (F8 WARN / F9 HUMAN only); only configuration changes afterwards
why_human: Owner decisions and a future-dated event
result: [pending]

### 8. Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3)
test: Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3)
expected: Both units active, logcheck OK, fastnet-probe --file exits 0, same fingerprint on both cards (8b0a3bc4…19c8 unless the code changes), tablet opens http://10.42.0.1
why_human: Physical SD cards and Pi boot
result: [pending]

### 9. 12 Nov: replay of the boat's real Fastnet capture
test: 12 Nov: replay the boat's real capture (`bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`)
expected: 5 PASS lines; every decoded inventory path served by /api/state; logcheck OK
why_human: The real Hercules capture only exists on 12 Nov
result: [pending]

### 10. On-board commissioning per docs/COMMISSIONING.md §2-§9 (12-13 Nov; GPS arrives 2026-11-10), incl. th
test: On-board commissioning per docs/COMMISSIONING.md §2-§9 (12-13 Nov; GPS arrives 2026-11-10), incl. the 04-11/04-12 helm behaviours at night at the lowest brightness (VIREZ/EMPANNEZ, VENT PÉRIMÉ, PAS DE GPS, lock release gesture, no pull-to-refresh, Diag red with no white flash, stale vs live dim tiers)
expected: Helm tablet shows live/MANUEL/GRIB wind and laylines to the first mark over the boat Wi-Fi, readable at night (SC4)
why_human: Real boat, instruments, GPS, tablet, night
result: [pending]

### 11. On-board rounding drills at a real buoy (04-13..04-15)
test: On-board rounding drills at a real buoy (04-13..04-15): (a) a mark tapped ~50 m beyond the buoy, rounded and left on a beat, advances with the banner; a tack away on the approach side, outside the turn, well outside the radius keeps the mark. (b) Course-change drill right after a rounding, still in the zone: add a next mark at the default position (« Ajouter »), or move the next mark, then steer to it: the course moves on once. (c) Annuler-then-edit drill: after an early advance tap Annuler, finish the rounding, and while still in the zone use « Finir ici » on a later mark (or « Ajouter »): the course moves on once after leaving the zone past the mark. (d) R10 check: after an Annuler in the zone, if the course moves on while still inside the turn before passing the mark, a second Annuler (outside the zone) brings it back and it does not loop
expected: Each drill behaves as stated; any stuck course is recovered with Carte → « Suiv. », any false advance with Annuler / « Préc. »
why_human: Real GPS track at a real buoy and real crew timing
result: [pending]

### 12. Course card, written by hand (no repo doc change before the freeze)
test: Course card, written by hand (no repo doc change before the freeze): (1) enter committee marks as close to the real buoy as known; (2) if the course does not move on after a rounding (bearing points back, distance grows) -> Carte → « Suiv. »; (3) after changing the next mark right after a rounding, steer to the new mark, otherwise « Suiv. » (R8); (4) if you move the rounded mark itself, its radius or the mark before it after rounding it -> « Suiv. » (R6); (5) if the course moves on right after Annuler while you are still inside the turn, before passing the mark -> Annuler again or « Préc. » (R10); (6) an edit made inside the 60 s banner window removes Annuler: use « Préc. » (IN-01/IN-02); (7) any false advance -> Annuler on the banner or « Préc. » (R1, R9)
expected: Card on board, read by the crew before the start
why_human: Owner logistics
result: [pending]

### 13. Owner reads COMMISSIONING/SOAK/FREEZE and adjusts 12 Nov timings; a Slovenian speaker proofreads COM
test: Owner reads COMMISSIONING/SOAK/FREEZE and adjusts 12 Nov timings; a Slovenian speaker proofreads COMMISSIONING-SL.md and I18N-SL-REVIEW.md
expected: Timings fit; FR clear; SL correct
why_human: Owner logistics and native-language review
result: [pending]

## Summary

total: 13
passed: 0
issues: 0
pending: 13
skipped: 0
blocked: 0
## Gaps

Source of G-4-R*: 04-PROJECT-REVIEW.md (whole-project review of 2026-11-09, owner chose to fix). Tests 1–9 are still pending; these gaps come from code review, not from a failed test.

```yaml
- gap_id: G-4-R01
  truth: "A MANUEL wind older than manual_wind_max_age_min never drives a confident helm target: the steer block shows VENT PÉRIMÉ and blocks 1–2 are dimmed (or helm.target is nulled as for NONE), laylines/countdown are not presented as live"
  status: resolved
  resolved_by: 04-11
  reason: "Review: WindSolution.ok ignores sol.stale (nav/wind.py:197,387); nav_service.py:209-215,265-287 keeps computing target/laylines/countdown; only the top badge turns PÉRIMÉ (helm_logic.js:69), the 115 px number and deviation colours render as live (helm_logic.js:168-185)"
  severity: blocker
  test: review
  artifacts: ["src/jabuka/nav/wind.py", "src/jabuka/core/nav_service.py", "src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/app.css"]
  missing: ["stale gate on helm target or explicit VENT PÉRIMÉ takeover of the steer block + .stale dimming; tests in tests/nav and tests/test_helm_logic.py"]
- gap_id: G-4-R02
  truth: "Leaving a mark's zone without having passed the mark does not advance the course; the zone-exit branch requires the boat to be past the mark along the incoming leg (outgoing leg for hairpins), as _abeam already does"
  status: resolved
  resolved_by: 04-09
  reason: "Review: course.py:699-707 candidate is `d > zone or _abeam(...)`; reproduced on Plić Sestre: approach from NNW to 0.45 nm then retreat on the same side → active_idx 1→2 after 10 s; only safeguard is the 60 s Annuler banner"
  severity: blocker
  test: review
  artifacts: ["src/jabuka/nav/course.py", "tests/nav"]
  missing: ["past-the-mark condition on the zone-exit branch; regression test: enter zone, back out on the same side, no advance; existing hairpin/CR-02 (left_this_zone after Annuler) tests still pass"]
- gap_id: G-4-R03
  truth: "When countdown_s <= 0 or wrong_tack, the primary helm box itself shows VIREZ / EMPANNEZ with the new tack word, at primary size, instead of a 26 px countdown line"
  status: resolved
  resolved_by: 04-11
  reason: "Review: route_logic.js:49 emits tackNow as the countdown line (.countdown.alert, --f-countdown, app.css:120,165-171) while helm_logic.js:198-212 keeps the current-tack target until the core flips target_tack; a missed cue costs a forced recompute after MISSED_S"
  severity: blocker
  test: review
  artifacts: ["src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/route_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/app.css", "src/jabuka/web/static/i18n.js", "tests/test_helm_logic.py", "tests/test_route_logic.js"]
  missing: ["primary-box takeover rule + FR/EN/SL strings; logic tests"]
- gap_id: G-4-R04
  truth: "Helm polar targets (Polar.targets) and router targets (PolarGrid) agree: downwind target 180° at >= 14 kn on the shipped X35 polar (VMG-linear interpolation between knots >= VMG_SEGMENT_MIN_DEG)"
  status: resolved
  resolved_by: 04-09
  reason: "Review: nav/polar.py:116-129,146-169 interpolates speed linearly between 150° and 180°, inventing a VMG bump; measured TWA CIBLE ↓ 170–171° at 14/16/20/25 kn vs router 180° (polar_grid.py:100-105); target jumps 10° when the route drops"
  severity: major
  test: review
  artifacts: ["src/jabuka/nav/polar.py", "src/jabuka/route/polar_grid.py", "tests/nav"]
  missing: ["same VMG-linear rule in Polar (speed or targets) or helm targets derived from PolarGrid; test asserting agreement on the shipped polar"]
- gap_id: G-4-R05
  truth: "No fsync runs on the core/ingest event loop: RotatingAppendLog cadence fsyncs, event fsync_now, settings/course/route/bias atomic writes fsync in a worker thread (asyncio.to_thread) or are staggered so a multi-second SD stall cannot freeze tick, WS and UDP consumption"
  status: resolved
  resolved_by: 04-10
  reason: "Review: ingest/rawlog.py:192-202, core/main.py:204-230, core/nav_api.py:81-96, core/course_api.py:102-115, common/atomicio.py:28-42, router_service.py:727-733 do write+fsync(+dir fsync) inline on the loop; three logs share the 10 s cadence"
  severity: major
  test: review
  artifacts: ["src/jabuka/ingest/rawlog.py", "src/jabuka/common/atomicio.py", "src/jabuka/core/main.py", "src/jabuka/core/nav_api.py", "src/jabuka/core/course_api.py", "src/jabuka/core/router_service.py", "tests/test_rawlog_full_disk.py", "tests/test_atomicio.py"]
  missing: ["off-loop fsync (keep durability semantics: ENOSPC rollback, .bak, rename order); tests still pass; no wall-clock use"]
- gap_id: G-4-R06
  truth: "The routing worker process is not protected from the OOM killer like the core: _pool_init raises /proc/self/oom_score_adj to a positive value so gpsd, NetworkManager and journald outlive it under memory pressure"
  status: resolved
  resolved_by: 04-10
  reason: "Review: jabuka-core.service:31 OOMScoreAdjust=-500 is inherited by the forkserver worker; route/pool.py:47-50 only calls os.nice; no oom_score_adj anywhere in src/"
  severity: major
  test: review
  artifacts: ["src/jabuka/route/pool.py", "deploy/systemd/jabuka-core.service", "tests/route"]
  missing: ["best-effort write of oom_score_adj in _pool_init (ignore errors, Linux only); unit test with a fake /proc path or a documented manual check"]
- gap_id: G-4-R07
  truth: "The lock cannot be released by a single pointer that never lifts: unlock fires on pointerup after a hold of 2 to ~4 s, a hold that never releases or exceeds the window does nothing"
  status: resolved
  resolved_by: 04-12
  reason: "Review: lock.js:155-167 and lock_logic.js:44-47 unlock inside tick() as soon as the primary pointer has been down 2 s; only a second pointer cancels (lock_logic.js:26-30); a resting water drop is a single primary pointer"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/lock.js", "src/jabuka/web/static/lock_logic.js", "tests/test_lock_logic.py"]
  missing: ["release-based unlock window; ring feedback; logic tests"]
- gap_id: G-4-R08
  truth: "When the position is stale/missing the helm shows a red PAS DE GPS badge and the primary label says so, instead of unexplained dashes next to a green LIVE wind badge"
  status: resolved
  resolved_by: 04-11
  reason: "Review: state.py:20 drops the position row after 3 s, helm stays the envelope default (nav_service.py:131,260), helm_logic.js:174-177 renders — with no text, helmFlags (156-164) has no position badge; only route_logic.js:131 shows a 15–17 px 'pas de position GPS'"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/i18n.js", "tests/test_helm_logic.py"]
  missing: ["position badge + primary label text FR/EN/SL; logic tests"]
- gap_id: G-4-R09
  truth: "Night brightness never erases the dim tier (--dim floored, e.g. >= rgb(110,0,0)) and the primary label (what the big number is: TWA CIBLE ↑ / CAP À SUIVRE / TWA ROUTE ↓) is glanceable (--f-word size, --fg colour)"
  status: resolved
  resolved_by: 04-12
  reason: "Review: app.js:125-133 scales every night colour, at 40 % --dim = rgb(51,0,0) on black; #primary-label uses .label (app.css:150, 16 px, --dim)"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/app.js", "src/jabuka/web/static/app.css", "tests/ui"]
  missing: ["dim floor in the brightness scaler; primary label sizing"]
- gap_id: G-4-R10
  truth: "Opening Diag in night mode does not flash white: diag.html follows jabuka.theme with a red-on-black variant (or asks for confirmation before opening in night mode)"
  status: resolved
  resolved_by: 04-12
  reason: "Review: diag.css:1-10 white text on green/yellow/red backgrounds and #diag-frame{background:#fff} (app.css:240); the Diag tab sits in the helm top bar"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/diag.css", "src/jabuka/web/static/diag.js", "src/jabuka/web/static/diag.html", "src/jabuka/web/static/app.css", "src/jabuka/web/static/app.js"]
  missing: ["night variant for the diag page and frame background"]
- gap_id: G-4-R11
  truth: "Unlocked helm surfaces cannot select text, open the Android long-press sheet, or pull-to-refresh: user-select:none, -webkit-touch-callout:none on #helm-col/#topbar/.map-ctrls and overscroll-behavior-y:none on html, body (inputs in Réglages/Carte keep selection)"
  status: resolved
  resolved_by: 04-12
  reason: "Review: app.css:249-250 sets these only on #lock-overlay"
  severity: minor
  test: review
  artifacts: ["src/jabuka/web/static/app.css"]
  missing: ["CSS rules; keep text inputs selectable"]
- gap_id: G-4-R12
  truth: "The Plan-B units jabuka-fastnet-relay.service and fastnet2ip.service set StartLimitIntervalSec=0 so a crash loop cannot leave them permanently dead"
  status: resolved
  resolved_by: 04-10
  reason: "Review: both units have Restart= with RestartSec but no StartLimitIntervalSec; systemd default 5 starts / 10 s then the unit stays failed. The two main units are protected"
  severity: minor
  test: review
  artifacts: ["deploy/systemd/jabuka-fastnet-relay.service", "deploy/systemd/fastnet2ip.service", "tests/deploy"]
  missing: ["[Unit] StartLimitIntervalSec=0 in both; deploy test if one checks unit keys"]
```
