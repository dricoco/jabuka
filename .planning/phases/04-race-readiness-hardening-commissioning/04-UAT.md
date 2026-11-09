---
status: testing
phase: 04-race-readiness-hardening-commissioning
source: [04-VERIFICATION.md]
started: 2026-11-08T20:40:00Z
updated: 2026-11-09T09:24:00Z
---

## Current Test

number: 1
name: Laptop race-36h soak on the final pre-freeze HEAD (full length, no Ctrl-C at the end)
expected: |
  `bash scripts/soak.sh --scenario race-36h` on a clean tree, no --duration. Verdict PASS, exit 0,
  report.json end_signal null, duration_s 129600, sim_s >= 129600, scenario_sha256 = sha256 of
  race-36h.json at HEAD, no "after the end of the run" skips. freeze-check F3 PASS.
  Quick runs go to `--out var/soak-essais`, never var/soak/.
awaiting: user response

## Tests

### 1. Laptop race-36h soak on the final pre-freeze HEAD (full length, no Ctrl-C at the end)
expected: Verdict PASS, exit 0, end_signal null, duration_s 129600, sim_s >= 129600, scenario_sha256 matches HEAD, no late skips; freeze-check F3 PASS (today F3 FAILs by design: older reports predate end_signal/scenario_sha256)
result: [pending]

### 2. Pi 3B system-scope soak (ROADMAP SC1)
expected: Rebuild wheelhouse from final HEAD (`bash scripts/build-wheelhouse.sh`), re-provision the Pi (installed fingerprint = c36c79860a3a2f8d97b0f60a5721adc50e131db0760ac6e6b1f337b34a9e2c58 if src/jabuka unchanged). `sudo apt install -y tmux` while online. In `tmux new -s soak`: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`; no Ctrl-C at the end. No startup WARNING; exit 0, verdict PASS, end_signal null, systemd.journal.complete true with core > 0 and ingest > 0 entries, non-empty proc/*-journal.log, tick ratio >= 0.95, RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true. After scp of that run dir + reboot: `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0 and both units active. freeze-check F4 PASS.
result: [pending]

### 3. Pi budgets recorded in docs/SOAK.md "Budgets Pi à confirmer"
expected: RSS, temperature and throttling filled in; numbers fit the 1 GB Pi (also closes 03-05 "Pi memory")
result: [pending]

### 4. 5 real power pulls on the Pi, each followed by jabuka-logcheck
expected: Services come back each time, logcheck OK, course and settings intact (a visible ".bak restauré" alert is acceptable)
result: [pending]

### 5. Feature freeze on 2026-11-11 per docs/FREEZE.md
expected: Lock reviewed and hashed, tag race-2026, wheelhouse from the tag, Pi re-provisioned; `bash scripts/freeze-check.sh` exit 0 (all PASS except F8 WARN and F9 HUMAN); only configuration changes afterwards
result: [pending]

### 6. Spare SD cloned per docs/SPARE-SD.md and booted (ROADMAP SC3)
expected: jabuka-core and jabuka-ingest-fastnet active, logcheck OK, fastnet-probe --file exits 0, FINGERPRINT_SH identical on both cards and equal to the Pi report's code.sha256, tablet opens http://10.42.0.1
result: [pending]

### 7. 12 Nov: replay of the boat's real Fastnet capture
expected: `bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log` gives 5 PASS lines; every decoded inventory path served by /api/state; logcheck OK
result: [pending]

### 8. On-board commissioning per docs/COMMISSIONING.md §2–§9 on 12–13 Nov (ROADMAP SC4)
expected: The helm tablet shows live wind (or MANUEL / GRIB) and laylines to the first mark over the boat Wi-Fi, readable at night
result: [pending]

### 9. Runbook timings and proofreading
expected: Owner reads docs/COMMISSIONING.md, docs/SOAK.md (Pi steps 6 and 8) and docs/FREEZE.md and adjusts 12 Nov timings; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md and the SL "obnovljen iz varnostne kopije" strings
result: [pending]

## Summary

total: 9
passed: 0
issues: 0
pending: 9
skipped: 0
blocked: 0

## Gaps

Source of G-4-R*: 04-PROJECT-REVIEW.md (whole-project review of 2026-11-09, owner chose to fix). Tests 1–9 are still pending; these gaps come from code review, not from a failed test.

```yaml
- gap_id: G-4-R01
  truth: "A MANUEL wind older than manual_wind_max_age_min never drives a confident helm target: the steer block shows VENT PÉRIMÉ and blocks 1–2 are dimmed (or helm.target is nulled as for NONE), laylines/countdown are not presented as live"
  status: failed
  reason: "Review: WindSolution.ok ignores sol.stale (nav/wind.py:197,387); nav_service.py:209-215,265-287 keeps computing target/laylines/countdown; only the top badge turns PÉRIMÉ (helm_logic.js:69), the 115 px number and deviation colours render as live (helm_logic.js:168-185)"
  severity: blocker
  test: review
  artifacts: ["src/jabuka/nav/wind.py", "src/jabuka/core/nav_service.py", "src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/app.css"]
  missing: ["stale gate on helm target or explicit VENT PÉRIMÉ takeover of the steer block + .stale dimming; tests in tests/nav and tests/test_helm_logic.py"]
- gap_id: G-4-R02
  truth: "Leaving a mark's zone without having passed the mark does not advance the course; the zone-exit branch requires the boat to be past the mark along the incoming leg (outgoing leg for hairpins), as _abeam already does"
  status: failed
  reason: "Review: course.py:699-707 candidate is `d > zone or _abeam(...)`; reproduced on Plić Sestre: approach from NNW to 0.45 nm then retreat on the same side → active_idx 1→2 after 10 s; only safeguard is the 60 s Annuler banner"
  severity: blocker
  test: review
  artifacts: ["src/jabuka/nav/course.py", "tests/nav"]
  missing: ["past-the-mark condition on the zone-exit branch; regression test: enter zone, back out on the same side, no advance; existing hairpin/CR-02 (left_this_zone after Annuler) tests still pass"]
- gap_id: G-4-R03
  truth: "When countdown_s <= 0 or wrong_tack, the primary helm box itself shows VIREZ / EMPANNEZ with the new tack word, at primary size, instead of a 26 px countdown line"
  status: failed
  reason: "Review: route_logic.js:49 emits tackNow as the countdown line (.countdown.alert, --f-countdown, app.css:120,165-171) while helm_logic.js:198-212 keeps the current-tack target until the core flips target_tack; a missed cue costs a forced recompute after MISSED_S"
  severity: blocker
  test: review
  artifacts: ["src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/route_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/app.css", "src/jabuka/web/static/i18n.js", "tests/test_helm_logic.py", "tests/test_route_logic.js"]
  missing: ["primary-box takeover rule + FR/EN/SL strings; logic tests"]
- gap_id: G-4-R04
  truth: "Helm polar targets (Polar.targets) and router targets (PolarGrid) agree: downwind target 180° at >= 14 kn on the shipped X35 polar (VMG-linear interpolation between knots >= VMG_SEGMENT_MIN_DEG)"
  status: failed
  reason: "Review: nav/polar.py:116-129,146-169 interpolates speed linearly between 150° and 180°, inventing a VMG bump; measured TWA CIBLE ↓ 170–171° at 14/16/20/25 kn vs router 180° (polar_grid.py:100-105); target jumps 10° when the route drops"
  severity: major
  test: review
  artifacts: ["src/jabuka/nav/polar.py", "src/jabuka/route/polar_grid.py", "tests/nav"]
  missing: ["same VMG-linear rule in Polar (speed or targets) or helm targets derived from PolarGrid; test asserting agreement on the shipped polar"]
- gap_id: G-4-R05
  truth: "No fsync runs on the core/ingest event loop: RotatingAppendLog cadence fsyncs, event fsync_now, settings/course/route/bias atomic writes fsync in a worker thread (asyncio.to_thread) or are staggered so a multi-second SD stall cannot freeze tick, WS and UDP consumption"
  status: failed
  reason: "Review: ingest/rawlog.py:192-202, core/main.py:204-230, core/nav_api.py:81-96, core/course_api.py:102-115, common/atomicio.py:28-42, router_service.py:727-733 do write+fsync(+dir fsync) inline on the loop; three logs share the 10 s cadence"
  severity: major
  test: review
  artifacts: ["src/jabuka/ingest/rawlog.py", "src/jabuka/common/atomicio.py", "src/jabuka/core/main.py", "src/jabuka/core/nav_api.py", "src/jabuka/core/course_api.py", "src/jabuka/core/router_service.py", "tests/test_rawlog_full_disk.py", "tests/test_atomicio.py"]
  missing: ["off-loop fsync (keep durability semantics: ENOSPC rollback, .bak, rename order); tests still pass; no wall-clock use"]
- gap_id: G-4-R06
  truth: "The routing worker process is not protected from the OOM killer like the core: _pool_init raises /proc/self/oom_score_adj to a positive value so gpsd, NetworkManager and journald outlive it under memory pressure"
  status: failed
  reason: "Review: jabuka-core.service:31 OOMScoreAdjust=-500 is inherited by the forkserver worker; route/pool.py:47-50 only calls os.nice; no oom_score_adj anywhere in src/"
  severity: major
  test: review
  artifacts: ["src/jabuka/route/pool.py", "deploy/systemd/jabuka-core.service", "tests/route"]
  missing: ["best-effort write of oom_score_adj in _pool_init (ignore errors, Linux only); unit test with a fake /proc path or a documented manual check"]
- gap_id: G-4-R07
  truth: "The lock cannot be released by a single pointer that never lifts: unlock fires on pointerup after a hold of 2 to ~4 s, a hold that never releases or exceeds the window does nothing"
  status: failed
  reason: "Review: lock.js:155-167 and lock_logic.js:44-47 unlock inside tick() as soon as the primary pointer has been down 2 s; only a second pointer cancels (lock_logic.js:26-30); a resting water drop is a single primary pointer"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/lock.js", "src/jabuka/web/static/lock_logic.js", "tests/test_lock_logic.py"]
  missing: ["release-based unlock window; ring feedback; logic tests"]
- gap_id: G-4-R08
  truth: "When the position is stale/missing the helm shows a red PAS DE GPS badge and the primary label says so, instead of unexplained dashes next to a green LIVE wind badge"
  status: failed
  reason: "Review: state.py:20 drops the position row after 3 s, helm stays the envelope default (nav_service.py:131,260), helm_logic.js:174-177 renders — with no text, helmFlags (156-164) has no position badge; only route_logic.js:131 shows a 15–17 px 'pas de position GPS'"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/i18n.js", "tests/test_helm_logic.py"]
  missing: ["position badge + primary label text FR/EN/SL; logic tests"]
- gap_id: G-4-R09
  truth: "Night brightness never erases the dim tier (--dim floored, e.g. >= rgb(110,0,0)) and the primary label (what the big number is: TWA CIBLE ↑ / CAP À SUIVRE / TWA ROUTE ↓) is glanceable (--f-word size, --fg colour)"
  status: failed
  reason: "Review: app.js:125-133 scales every night colour, at 40 % --dim = rgb(51,0,0) on black; #primary-label uses .label (app.css:150, 16 px, --dim)"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/app.js", "src/jabuka/web/static/app.css", "tests/ui"]
  missing: ["dim floor in the brightness scaler; primary label sizing"]
- gap_id: G-4-R10
  truth: "Opening Diag in night mode does not flash white: diag.html follows jabuka.theme with a red-on-black variant (or asks for confirmation before opening in night mode)"
  status: failed
  reason: "Review: diag.css:1-10 white text on green/yellow/red backgrounds and #diag-frame{background:#fff} (app.css:240); the Diag tab sits in the helm top bar"
  severity: major
  test: review
  artifacts: ["src/jabuka/web/static/diag.css", "src/jabuka/web/static/diag.js", "src/jabuka/web/static/diag.html", "src/jabuka/web/static/app.css", "src/jabuka/web/static/app.js"]
  missing: ["night variant for the diag page and frame background"]
- gap_id: G-4-R11
  truth: "Unlocked helm surfaces cannot select text, open the Android long-press sheet, or pull-to-refresh: user-select:none, -webkit-touch-callout:none on #helm-col/#topbar/.map-ctrls and overscroll-behavior-y:none on html, body (inputs in Réglages/Carte keep selection)"
  status: failed
  reason: "Review: app.css:249-250 sets these only on #lock-overlay"
  severity: minor
  test: review
  artifacts: ["src/jabuka/web/static/app.css"]
  missing: ["CSS rules; keep text inputs selectable"]
- gap_id: G-4-R12
  truth: "The Plan-B units jabuka-fastnet-relay.service and fastnet2ip.service set StartLimitIntervalSec=0 so a crash loop cannot leave them permanently dead"
  status: failed
  reason: "Review: both units have Restart= with RestartSec but no StartLimitIntervalSec; systemd default 5 starts / 10 s then the unit stays failed. The two main units are protected"
  severity: minor
  test: review
  artifacts: ["deploy/systemd/jabuka-fastnet-relay.service", "deploy/systemd/fastnet2ip.service", "tests/deploy"]
  missing: ["[Unit] StartLimitIntervalSec=0 in both; deploy test if one checks unit keys"]
```
