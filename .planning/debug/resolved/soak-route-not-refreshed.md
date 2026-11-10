---
status: resolved
resolution_state: resolved-pending-soak (final human verification = next Pi system-scope race-36h soak by the user)
fix_commit: 35a61a7
trigger: "Soak race-36h sur le Pi (20261110T153632Z) : FAIL — route non recalculée dans les 60 s après f67/f70/f71/f79/f85 ; grib-gap harness error ; manual CHANGED après power-pull propre f55 ; 2 AssertionError dans le journal du cœur"
created: 2026-11-10
updated: 2026-11-10
---

## Symptoms

DATA_START
- **Expected:** after each fault of the soak (course-change, stay-toggle, clock-jump, kill-worker), a new route (version > previous) is published within 60 s real; grib-gap faults are actually played; a clean power-pull keeps course, settings AND manual values; no unexpected tracebacks.
- **Actual (report /home/drico/git/jabuka/var/soak/20261110T153632Z-race-36h/report.md, also report.json, timeline.jsonl, samples.csv, proc/, console.log):**
  1. f67 course-change (sim 66001 s, real 3314 s), f71 clock-jump (sim 70244), f79 kill-worker (sim 77592): "no new route (version > 114) within 60 s". Route version appears stuck at 114 from ~f67 to after f79. f70 and f85 stay-toggle: "no optimal route after On reste was switched off". Earlier identical faults (f50 kill-worker 9.8 s, f59/f61/f64/f66 stay-toggle) passed, and later ones too. route_after_recovery check value 15 / budget 60.
  2. 7 grib-gap faults (f33 f34 f42 f49 f51 f52 f65 f84): harness error ValueError('refusing to touch /var/lib/jabuka/soak-20261110T153632Z/racepack: outside the soak run dir /home/drico/jabuka/var/soak/20261110T153632Z-race-36h') — systemd system scope puts the racepack under /var/lib/jabuka/soak-<ts>, and the harness path guard only allows the run dir. Harness bug, fault never exercised.
  3. f55 power-pull (clean): persistence course same, settings same, manual "CHANGED by a clean pull" (later power-pulls f57 f77 f80 f81 passed).
  4. check tracebacks: core-journal.log:189 AssertionError; core-journal.log:414 AssertionError ("2 expected" — determine whether these are harness-injected/expected or real).
  5. Check recovery_gps "10 fault(s)", recovery_process "19 fault(s)", recovery_power "8 fault(s)" marked NON although listed measured values are within budget — check whether these NON come only from the grib-gap/route items above or are distinct failures.
- **Errors:** see above; core journal and timeline are in the report dir.
- **Timeline:** first soak run in system scope that reached the end. Previous runs failed on a harness watchdog clock bug (fixed in quick 261110-lqa) and on pty re-chown (fixed in 8b8fceb). Pi was on a powerbank with under-voltage 0x50000 during this soak (now replaced, throttled=0x0).
- **Reproduction:** `sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M` on the Pi (~2 h). Harness: src/jabuka/tools/soak.py, tests/soak/. Router service: src/jabuka/core/router_service.py (pool watchdog, _withdrawal, _last_fail), src/jabuka/route/.
DATA_END

## Constraints

- The race is 13 Nov 2026: priority is whether symptom 1 is a REAL app defect (routes not refreshed for ~10 min real / ~3 h sim at sea) vs a harness/under-voltage artefact.
- Do NOT touch the Pi (192.168.64.169) — analysis from the copied report only; no deploy, no soak rerun. Local tests only.
- Never touch cad/, stl/, hardware/, docs/SOAK.md, nor the quick-tasks table in .planning/STATE.md. Stage by explicit path only; no git add -A/stash/reset/clean; no push. Commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>". Do not stage docs/I18N-SL-REVIEW.md.bak.
- pytest is .venv313/bin/pytest; full gate `bash scripts/check.sh` (UI test test_switch_to_slovenian_then_english_persists_and_fits is known flaky).
- Under-voltage (0x50000) was present: consider it as a possible contributor but prove it from logs before blaming it.

## Current Focus

bug_class: Bohrbug (deterministic harness logic; reproducible from the recorded timeline)
hypothesis: CONFIRMED (H1) symptom 1 is a harness artefact — baseline `max_route_version()` is a run-wide high-water mark (114); after the f65 grib-gap core restart the router legitimately renumbered from 1 (course A finished -> B, older-course route not restored), so every non-restart check demanding `version > 114` could not pass although routes were refreshed within 4-15 s.
user_decision (checkpoint answered): symptom 4 -> option A (declare the ws-stall AssertionError expected in src/jabuka/soak/scenarios/race-36h.json, no app change); commit harness fixes by explicit paths, no push.
next_action: none in this session. Harness fixes + ws-stall rule committed (35a61a7); session archived resolved-pending-soak. Reopen only if the user's next Pi race-36h soak (`sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`) shows a route/grib-gap/power-pull/traceback failure again.

reasoning_checkpoint:
  hypothesis: "(1) faults.* use tablet.max_route_version() as the 'before' version; after a core restart that legitimately renumbers routes from 1, 'version > max' is unreachable for non-restart faults -> false 'no new route' / 'no optimal route'. (2) Harness.write_full_wind passes root=run_dir while the system-scope pack lives under state_root -> pack.inside() ValueError. (3) power_pull SIGKILLs ~0.4 s after POST /api/wind/manual, inside the core's documented background-durability window, so the manual change can be lost by design."
  confirming_evidence:
    - "report.json routes[]: v1..v59 adopted 3219-4341 s; new route 4-15 s after f67/f70/f71/f79/f85; route_version_before stays 114 on every fault record from f67 to f83 while route_version is 28..52 on the restart faults that passed"
    - "pack.inside raises with 'outside the soak run dir /home/drico/jabuka/var/soak/...' exactly as reported; write_full_wind is the only pack write using run_dir; alerts 'MÉTÉO INCOMPLÈTE' persist after f33"
    - "local repro: background ManualWindStore.set + no drain -> on-disk {} and None after reload, no alert"
  falsification_test: "(1) would be false if no route was adopted in the 60-s windows (refuted by routes[]). (2) false if write_full_wind used state_root (it doesn't). (3) false if the persisted manual wind were on disk before the SIGKILL — the new harness wait records manual_durable_s and fails explicitly if the file never reaches the posted value."
  fix_rationale: "Baseline = the version of the last adopted route (what the tablet shows now) — within one core process versions are monotonic, across a restart _route_after already accepts any other version. write_full_wind uses state_root like every other harness write into the stack's files. The clean pull is a power cut after the acknowledged change is durable (G-4-R05 contract): wait for it, bounded, and fail if it never lands (a stalled durability thread stays visible)."
  blind_spots: "Pi-only timing (SD stall length during the run) not observable; the websockets AssertionError trigger was not reproduced locally; the harness changes are verified by unit tests only (no soak rerun allowed)."
  candidate_causes:
    - "code (harness): version baseline / root path / pull timing"
    - "code (app): router pool stuck after worker kill — refuted by continuous routes"
    - "environment: under-voltage 0x50000 slowing the Pi — refuted for symptom 1 (route cadence unchanged); may lengthen SD stalls (symptom 3) but the window exists regardless"
    - "data: version numbering reset by course change at f65 (expected app behaviour, RouterService.restore)"
  and_gate: "yes for symptom 1: needs (a) max-based baseline AND (b) a core restart that renumbers (course changed since the saved route). Earlier restarts carried the version on (route restored), so (a) alone was harmless until f65. Fix targets (a); (b) is correct app behaviour."

## Evidence

- timestamp: 2026-11-10
  checked: report.json routes[] (tablet-adopted routes, t relative to t0_wall 1794324994.58) between 3100 and 4400 s real
  found: last pre-restart route v114 at 3108.7 (n_points 2, near finish of course A); course_finished A->B at ~3189; f65 grib-gap SIGTERMed core at 3195 (restart 3197); then routes v1 at 3219.5, v2 3226.3 ... v59 at 4340.9 — continuous, gaps 4-70 s. f67 (course-change at 3313.9): v7 adopted at 3326.2 (+12.3 s). f71 (clock-jump cleared ~3541): v21 at 3548.4. f79 (kill-worker at 3893.4): v39 at 3908.8 (+15.4 s, new worker 27057). f70 stay off at ~3463.9: v15 kind=optimal at 3468.5 (+4.6 s). f85 stay off at ~4262.2: v57 optimal at 4266.1 (+3.9 s).
  implication: the router DID refresh routes within budget after every "failed" fault; the version counter simply restarted at 1 in the new core process. Symptom 1 is not an app defect.

- timestamp: 2026-11-10
  checked: src/jabuka/soak/faults.py course_change/kill_worker/clock_jump (`v_before = h.tablet.max_route_version()`, `_route_after(..., restarted=False)` -> requires v > v_before) and stay_toggle (`v_off = h.tablet.max_route_version()`, optimal must have version > v_off when stay routes were seen); src/jabuka/soak/tablet.py max_route_version() = max over ALL self.routes of the run
  found: baseline is the max ever seen across core lifetimes, not the current route version. _route_after only tolerates a renumbering when restarted=True (kill-core/sigterm/power-pull paths), which is why f76/f77/f78/f80/f81/f83 (route_version_before 114, route_version 28..52) passed while f67/f70/f71/f79/f85 failed. Faults f59/f61/f64/f66 passed only because stay_routes was 0 (no version check).
  implication: harness bug. route_after_recovery "missing after f67,f71,f79" derives from the same records.

- timestamp: 2026-11-10
  checked: src/jabuka/web/static/route.js sync()/draw()
  found: the helm app redraws on ANY route message and refetches /api/route whenever nav.route.version !== drawn (no monotonic assumption).
  implication: the real tablet is unaffected by the numbering restart after a core restart; no app-side fix needed for symptom 1.

- timestamp: 2026-11-10
  checked: src/jabuka/tools/soak.py Harness.write_full_wind vs __init__ (system scope: state_root = pack parent = /var/lib/jabuka/soak-<ts>) and faults.grib_gap
  found: grib_gap writes the SHORT cube with root h.state_root (OK), SIGTERMs the core, then calls h.write_full_wind() which passes root=self.run_dir -> pack.inside() raises ValueError in system scope. So the short cube was installed and the core restarted on it, but the full cube was NEVER restored (alerts_after on f46/f55/f57/f77/f80/f81 show "MÉTÉO INCOMPLÈTE : vent jusqu'au ... seulement").
  implication: symptom 2 root cause = write_full_wind uses run_dir instead of state_root. Side effect: from f33 on, the stack ran on truncated wind cubes; the router kept routing anyway (routes continuous).

- timestamp: 2026-11-10
  checked: proc/core-journal.log tracebacks (wall 1794327009.287 = t0+2014.7 s; 1794328617.939 = t0+3623.4 s)
  found: both are "ERROR: keepalive ping failed ... websockets/legacy/protocol.py _drain_helper assert waiter is None or waiter.cancelled() AssertionError", inside fault windows f41 ws-stall (1994-2024) and f72 ws-stall (3603-3633) — the stalled client that never reads. The other journal tracebacks are ENOSPC during disk-full (expected).
  implication: symptom 4 is triggered by the ws-stall fault in uvicorn's deprecated legacy `websockets` implementation (journal also warns UvicornDeprecationWarning). Needs classification: expected-for-ws-stall vs app config fix (--ws websockets-sansio).

- timestamp: 2026-11-10
  checked: race-36h.json ws-stall entries vs the 8 ws-stall faults
  found: scheduled ws-stalls have dur 600 sim s (30 s real at 20x) = f41 and f72, exactly the two windows with the AssertionError; the six random ws-stalls have dur 300 (15 s real) and produced none. uvicorn default ws_ping_interval = 20 s; core/main.py forces ws="websockets" (legacy). The app's /ws endpoint has ONE sender per client (web.py), so the concurrent drain is websockets' own keepalive ping task vs the blocked sender on a paused transport. A local quick repro (uvicorn 0.54 / websockets 17.4, ping 0.5 s, client never reads, 6 s) did NOT reproduce it (timing-dependent); not pursued further.
  implication: symptom 4 = library behaviour of the deprecated legacy WS implementation under a client stalled > ~20 s; the keepalive task of that one connection dies (ERROR logged), core/tablet unaffected (ws-stall checks passed). Real-world analogue: tablet asleep with socket open. Fix = decision (expected rule for ws-stall vs switching uvicorn to websockets-sansio).

- timestamp: 2026-11-10
  checked: power-pull records (fault_start -> journal "Sent signal SIGKILL") and core persistence code
  found: in ALL 8 pulls the harness POSTs /api/wind/manual then SIGKILLs the core 0.29-0.49 s later (f55: 0.416 s). jabuka-core runs atomicio.enable_background() (main.serve, G-4-R05): atomic_write_json writes .wind_manual.json.<n>.tmp on the caller and returns; fsync(tmp) + .bak link + rename onto wind_manual.json run later on the single FIFO durability thread (shared with derived/events log fsyncs). The atomicio docstring documents the trade-off: "a power cut within an SD stall loses only the last change". Only the item written right before the pull (manual) changed; course/settings (not written just before) were "same"; no "Vent manuel restauré/illisible" alert -> main file loaded fine with its OLD content ({} from the previous pull's DELETE). Core CPU after the f55 boot ~0.5 CPU-s/s (samples.csv) -> no 5-s event-loop stall, so a GET timeout (snapshot None) is unlikely.
  implication: symptom 3 = the clean pull landed inside the documented durability window of the last change. Harness models a "clean" pull without waiting for the acknowledged change to be on disk.

- timestamp: 2026-11-10
  checked: local mechanism repro (scratchpad repro_f55.py): ManualWindStore with background mode, a job blocking the FIFO queue, set() -> "SIGKILL" (no drain) -> new ManualWindStore
  found: API shows the new entry; on disk {} ; orphan .wind_manual.json.0.tmp ; after boot to_api() None, alerts [] -> exactly "manual CHANGED by a clean pull" with no alert.
  implication: mechanism confirmed.

- timestamp: 2026-11-10
  checked: tools/soak.py compute_checks recovery(): recovery_gps = (gps-loss, clock-jump), recovery_process = (kill-core, kill-ingest, kill-worker, sigterm-storm, watchdog-hang), recovery_power = (power-pull); ok = all(fault_ok)
  found: recovery_gps NON only because of f71 (clock-jump route check), recovery_process NON only because of f79 (kill-worker route check), recovery_power NON only because of f55 (persistence). All measured recovery times are within budget.
  implication: symptom 5 has no distinct cause; it disappears with the fixes for symptoms 1 and 3.

- timestamp: 2026-11-10
  checked: alerts_after of every pull since f11 (garbage settings.json) + race-36h "settings": {} + faults._reapply
  found: "Réglages illisibles : valeurs par défaut" shows after every later boot: scenario settings == defaults so _reapply never PUTs, the garbage settings.json stays on disk for the rest of the run (app correctly re-reports it at each boot).
  implication: secondary harness weakness (later settings-corruption checks pass trivially); not one of the reported symptoms — reported only.

- timestamp: 2026-11-10
  checked: option A applied — race-36h.json expected_tracebacks["ws-stall"] rule (pattern: legacy/protocol.py ... in keepalive_ping ... assert waiter is None or waiter.cancelled() ... AssertionError at block end); tests/soak/test_soak_faults.py +6 cases written first (RED: 1 failed — the verbatim Pi block was unexpected), then GREEN after the rule; re-classified the real run (var/soak/20261110T153632Z-race-36h/proc/*.log, 4 blocks, margin 5 s) with load_scenario('race-36h')
  found: builtin-only rules -> unexpected = core-journal.log:189, :414 (AssertionError); with race-36h rules -> 189 expected by f41 ws-stall, 414 by f72 ws-stall, ENOSPC 138/383 still by disk-full f31/f63, unexpected = []. The rule does not match under ws-churn/kill-core windows, outside the window (+5 s margin), nor for an identical assert outside keepalive_ping.
  implication: symptom 4 classified as expected for ws-stall only, no app change (user decision A). Note: race-36h.json sha256 changes -> reports from earlier soaks no longer match HEAD's scenario for F3/F4 (a new full soak is needed anyway).

- timestamp: 2026-11-10
  checked: (session-manager observation, not fixed) src/jabuka/web/static/route.js nav-driven refetch fallback `nav.route.version !== drawn`
  found: after a core restart, if the new process reaches the SAME version number as the route already drawn AND the tablet misses that route push, the fallback does not refetch (stale geometry with equal number).
  implication: very low risk post-race follow-up (e.g. compare a per-process route id / course_version pair). Grouped with: settings.json garbage left after f11 (scenario settings == defaults so _reapply never rewrites it) and option B (uvicorn ws='websockets-sansio').

## Eliminated

- hypothesis: H0 — router service stuck (pool hang / _withdrawal / _last_fail) from ~f67 to after f79, possibly under-voltage induced
  evidence: report.json routes[] shows ~52 new routes (v7..v59) adopted and land-validated in that window, every 4-70 s, new routes within 4-15 s of each "failed" fault; kill-worker f79 produced new worker 27057 and v39 15 s later. Under-voltage played no visible role (route cadence unchanged).
  timestamp: 2026-11-10

- hypothesis: f55 manual change = GET timeout after boot (snapshot None)
  evidence: core CPU ~0.5 CPU-s/s after boot (no long event-loop block), GET course/settings/nav all answered; the durability-window mechanism reproduces the exact observation (None, no alert).
  timestamp: 2026-11-10

## Resolution

root_cause: "Symptom 1 (f67/f70/f71/f79/f85, route_after_recovery): harness baseline tablet.max_route_version() = run-wide max (114) AND a core restart (f65) that legitimately renumbered routes from 1 (course A finished -> B, older-course route not restored) -> 'version > 114' unreachable for non-restart faults; routes were in fact refreshed 4-15 s after each fault (NOT an app defect, under-voltage not involved); Symptom 2 (grib-gap x7): Harness.write_full_wind used run_dir as the guard root instead of state_root (system scope pack under /var/lib/jabuka/soak-<ts>); side effect: the stack ran on truncated wind cubes from f33 on; Symptom 3 (f55): clean pull SIGKILLs 0.3-0.5 s after POST /api/wind/manual, inside the core's documented background-durability window (atomicio G-4-R05) -> last change lost by design, harness did not wait for durability; Symptom 4 (2 AssertionError): websockets legacy keepalive_ping _drain_helper assertion on a client stalled > uvicorn's 20-s ping interval (only the two 30-s ws-stall faults f41/f72), deprecated legacy WS implementation forced by core/main.py ws='websockets' -> benign (core/tablet unaffected), fix needs a user decision; Symptom 5: recovery_gps/process/power NON derive only from f71, f79, f55."
fix: "Harness/scenario only (no app change): tablet.last_route_version() (version adopted last) used as the 'before' baseline in every fault (kill_core, kill_worker, sigterm_storm, power_pull, watchdog_hang, clock_jump, course_change, stay_toggle v_off); Harness.write_full_wind writes under state_root; power_pull waits (bounded MANUAL_DURABLE_S=10 s) until wind_manual.json on disk equals the acknowledged manual wind before the cut, records manual_durable_s, fails explicitly if it never lands. Symptom 4 (user decision A): race-36h.json expected_tracebacks['ws-stall'] = the legacy websockets keepalive_ping -> _drain_helper AssertionError (pattern anchored on legacy/protocol.py ... in keepalive_ping, the assert line and AssertionError as the block's last line, with a one-line why copied into the report); scoped to ws-stall windows only."
oracle_type: specified (fault contract: a newly adopted route after the fault; the run's recorded messages and values reproduced verbatim in RED; for symptom 4 the verbatim Pi journal block)
files_changed:
  - src/jabuka/soak/tablet.py
  - src/jabuka/soak/faults.py
  - src/jabuka/tools/soak.py
  - src/jabuka/soak/scenarios/race-36h.json
  - tests/soak/test_soak_faults.py (new)
post_race_follow_ups:
  - "uvicorn ws='websockets-sansio' instead of the deprecated legacy 'websockets' (option B for symptom 4; would remove the keepalive AssertionError at the source)"
  - "route.js nav fallback `v !== drawn`: after a core restart reaching the same version number as the drawn route, a missed push is not healed (very low risk)"
  - "soak: garbage settings.json left on disk after f11 for the rest of the run (scenario settings == defaults, _reapply never PUTs) -> later settings-corruption checks pass trivially"
verification:
  target_test: { result: pass, tests: tests/soak/test_soak_faults.py (13 = 7 harness + 6 ws-stall rule) }
  ws_stall_rule_on_real_run: "var/soak/20261110T153632Z-race-36h/proc/*.log (4 blocks) classified with load_scenario('race-36h'): core-journal.log:189 -> f41 ws-stall, :414 -> f72 ws-stall, ENOSPC :138/:383 -> disk-full f31/f63, unexpected [] (builtin-only rules: 189/414 unexpected)"
  final_gate: "tests/soak 113 passed; bash scripts/check.sh rc=0 (ruff check OK, 245 files formatted, 2054 passed 4 skipped on both interpreters; flaky UI test did not fail)"
  pending: "Pi system-scope race-36h soak rerun by the user (final human verification; not run in this session)"
  red_before_fix: "course_change -> 'no new route (version > 114) within 1.5 s'; stay_toggle -> 'no optimal route after On reste was switched off'; write_full_wind -> ValueError 'outside the soak run dir'; clean pull saw {} on disk instead of the posted manual wind"
  mutation_check: { result: pass, reason: "no Stryker for Python; manual mutants = the pre-fix code at each fix site (max baseline, run_dir root, no durability wait), each killed by its test (RED run above)" }
  no_op_deletion: { result: pass, deletion_justified_by_rca: n/a (additive change) }
  adjacent_tests: { result: pass, suites_run: [tests/soak (107 passed), bash scripts/check.sh: ruff check + format, 2048 passed 4 skipped on py3.14 AND py3.13, rc=0] }
  revert_and_reconfirm: { result: pass, bug_returned_on_revert: true (tests written and run RED before the fix; git stash forbidden by session constraints), fixed_on_reapply: true }
  boundary_neighbors: "last_route_version with no route -> 0; stay_toggle re-adopting the last stay version (same number) is still NOT counted as a new optimal route; manual wind never on disk -> bounded failure, nothing posted -> no wait"
  guardrail_verdict: accepted
  not_verifiable_locally: "Pi system-scope soak rerun (forbidden this session): grib-gap now runs its full body in system scope for the first time (short cube, coverage alert, route state, laylines, restore restart) — first exercised on the next Pi soak"

## Prevention

five_whys (branching, blameless):
  - branch code (harness baseline): faults failed after f65 -> they waited for version > 114 -> baseline = run-wide max -> the harness assumed route versions are monotonic across core lifetimes -> the restore path that renumbers (course changed since the saved route) was never exercised by the CI scenario before a non-restart fault -> no fake-harness unit test of a renumbering core existed.
  - branch config/environment (system scope): grib-gap raised ValueError -> pack root = run_dir -> system scope moves the pack to /var/lib/jabuka/soak-<ts> (state_root) -> write_full_wind was the one pack write still using run_dir -> user-scope runs (CI, laptop) have pack under run_dir, so the guard never tripped there.
  - branch code (timing): clean pull lost the manual change -> SIGKILL 0.4 s after the POST -> core persists in the background on purpose (G-4-R05) -> the harness modelled "clean" as "after the HTTP ack" instead of "after durability" -> laptop SD/disk is fast enough that the window was never hit locally.
  - branch environment (library): AssertionError in journal -> legacy websockets keepalive ping on a client stalled > 20 s -> uvicorn ws='websockets' (deprecated) -> only the 30-s ws-stall faults exceed ws_ping_interval; CI ws-stall is shorter.
why_not_caught: "No gate existed for these classes: tests/soak had no fake-harness tests of the fault functions (only units/scenario/systemd/identity), CI soak runs user scope (pack under run_dir) with short ws-stalls and fast disks; the first full system-scope Pi soak was the first gate able to see them."
recurrence_guard: "tests/soak/test_soak_faults.py (commit 35a61a7): test_last_route_version_follows_a_renumbering_core, test_course_change_after_a_renumbering_restart_sees_the_new_route, test_stay_toggle_after_a_renumbering_restart_sees_the_optimal_route, test_stay_toggle_still_waits_for_a_route_newer_than_the_stay_ones, test_full_wind_is_restored_under_the_state_root, test_clean_pull_waits_for_the_acknowledged_manual_wind_on_disk, test_manual_wind_never_on_disk_is_a_failure_not_a_hang, test_race_36h_expects_the_keepalive_assertion_inside_a_ws_stall, test_race_36h_keepalive_rule_expects_nothing_else[5 cases]; runtime: power_pull records manual_durable_s and fails explicitly if the acknowledged value never reaches disk; this KB entry."
