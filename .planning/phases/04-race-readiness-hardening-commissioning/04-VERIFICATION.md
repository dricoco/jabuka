---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-07T23:44:47Z
status: gaps_found
score: 29/34 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", "deploy/PI-SETUP.md", "docs/COMMISSIONING-SL.md", "docs/COMMISSIONING.md", "docs/FREEZE.md", "docs/SOAK.md", "docs/SPARE-SD.md", "pyproject.toml", "scripts/commissioning-rehearsal.sh", "scripts/freeze-check.sh", "scripts/soak.sh", "src/jabuka/common/atomicio.py", "src/jabuka/core/router_service.py", "src/jabuka/nav/course.py", "src/jabuka/nav/settings.py", "src/jabuka/soak/faults.py", "src/jabuka/soak/report.py", "src/jabuka/soak/supervisor.py", "src/jabuka/soak/systemd.py", "src/jabuka/tools/rehearsal.py", "src/jabuka/tools/soak.py", "src/jabuka/web/static/i18n.js", "tests/commissioning/test_freeze_check.py", "tests/nav/test_state_corruption.py", "tests/routing/test_supervisor.py", "tests/soak/test_soak_identity.py", "tests/soak/test_soak_systemd.py"]
covered_digest: "v1:sha256:94acf189cf70e0147f75b8fc065a7941fd294537126669f708784c7026297034"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 15/20
  gaps_closed:
    - "A Pi soak run as documented (rsync copy without .git, sudo --systemd system) can now reach freeze-check F4 PASS. The report carries code.sha256 (fingerprint of the installed units' venv package) and code.units, and F4 compares them with src/jabuka and deploy/systemd at HEAD. The harness refuses a system-scope run that cannot record this identity."
  gaps_remaining:
    - "02-4 (narrowed): F4 still PASSes an aarch64 race-36h report that is not a --systemd system soak (code.source 'children': shim or --systemd user on the Pi), with no unit check. A report with no code block falls back to the git rule (review CR-01, reproduced)."
  regressions: []
gaps:
  - truth: "The 2026-11-11 freeze checker passes only with a clean tree, a green gate, laptop AND Pi race-36h soak reports PASS on code identical to HEAD (04-02 truth 4; ROADMAP SC3; FREEZE.md step 2 requires the Pi soak in mode --systemd, CONTEXT §Pi specifics: the harness runs against the installed units)"
    status: partial
    reason: "The original defect is closed: a git-less Pi report from the documented system-scope run now reaches F4 PASS when the installed package and units equal HEAD, and FAILs otherwise. However, the PASS branch is not limited to that procedure. In scripts/freeze-check.sh, code_state() checks code.units only when code.source == 'units' (L131-142). Line 180 then PASSes any report with a matching fingerprint and git.head null, and F4 never reads mode, code.source or systemd.scope. I ran the reproduction against the real script (scratchpad test_cr01.py, 2 passed). An aarch64 race-36h report with code.source 'children', mode 'shim' and git null gives '[PASS] F4 Pi : … paquet installé = src/jabuka à HEAD'. The same happens when its code.units would mismatch. Such a report is easy to produce by mistake: on the Pi, running `bash scripts/soak.sh --python /opt/jabuka/venv/bin/python --scenario race-36h` without sudo/--systemd system, or `--systemd user` (mode is 'systemd' for both scopes, so only code.source tells them apart). That run never exercised the installed units' Restart=, WatchdogSec=, Type=notify, User=jabuka or hardening, and never hashed a unit file. Yet it certifies the Pi item of the freeze. A report with no code block still goes through the git rule (L182-191). This is the pre-04-04 behaviour, preserved by plan design, but every 04-04 harness report now carries `code`, so a missing block means a failed identity or a stale harness. Not a regression: the old git rule never checked mode either. 04-04 widened the PASS set to git-less shim/user Pi copies."
    artifacts:
      - path: "scripts/freeze-check.sh"
        issue: "code_state() treats any non-'units' source as fully matched once code.sha256 equals HEAD (L131-143). The `match && head == -` PASS (L180-181) ignores mode/source. A missing code block falls back to the git rule (L182-191)."
      - path: "tests/commissioning/test_freeze_check.py"
        issue: "There is no negative case for an aarch64 report with code.source 'children' (shim or user scope). test_f4_non_git_report_without_code_still_fails only fails because head is null."
    missing:
      - "In the freeze-check helper, for machine aarch64: when state == 'match' and code.source != 'units' (optionally also systemd.scope != 'system'), return a new state such as 'not-units'. Bash maps it to FAIL F4 '… pas un soak --systemd system (mode X, source Y) : sudo bash scripts/soak.sh --systemd system …'."
      - "Make cstate 'absent' a FAIL for F4 (and, for consistency, F3) with a hint to re-run the soak with the 04-04 harness, instead of falling back to the git rule"
      - "Tests: (a) aarch64 race-36h PASS report with code_identity(source='children'), git null, mode 'shim' → F4 FAIL; (b) the same with mode 'systemd' (user scope) → FAIL; (c) an aarch64 report with git at HEAD but no code block → FAIL"
advisory:
  - finding: "WR-01 (review): _cleanup_system marks the cleanup done and sets restarted = (rc == 0) even when `systemctl restart` failed or was killed. The verdict ignores restarted False, and --systemd-cleanup exits 0 when no soak lines are left (systemd.py L770-794, soak.py L785-793, L1329-1333)."
    category: other
    reason: "Confirmed in code. On the documented 10 Nov path it is backstopped: SOAK.md step 7 reboots the Pi (the /run drop-ins vanish and the enabled units start on their production config) and checks `systemctl is-active jabuka-core jabuka-ingest-fastnet` = active active. Hardening it (verify is-active, keep cleaned False, FAIL the verdict, start_new_session for systemctl) is cheap and worth doing with the gap fix, but it does not block."
    evidence_status: "code read; no failing test"
  - finding: "WR-02 (review): a signal deferred during cleanup is re-raised inside Harness.run(), before run_soak writes report.json (systemd.py L744-745, soak.py L785, L1305-1309), so a fully built report can be lost"
    category: other
    reason: "Confirmed in code. The window is the cleanup only (daemon-reload + restart + unmount, seconds to at most ~3 min) at the end of a 2-4 h run. A larger, pre-existing risk is that any SSH drop during the whole run sends SIGHUP and kills it with no report. main() installs its SIGHUP handler unconditionally, so `nohup` does not help, and SOAK.md tells the owner to run the Pi soak over SSH with no tmux/screen. Recommend: SOAK.md step 2 runs inside tmux or screen, and the deferred signal is honoured after write_report. Not blocking: the failure mode is 're-run the soak' (SOAK.md step 8), never a wrong PASS."
    evidence_status: "code read; no failing test"
  - finding: "WR-04 (review): the git-less fingerprint path covers src/jabuka plus the two jabuka unit files only. Post-soak changes to deploy/provision.sh, udev, gpsd/chrony config, fastnet2ip/relay units or pyproject.toml no longer invalidate F4."
    category: other
    reason: "F3 (laptop, git rule over src/deploy/pyproject), F5 (lock hash) and FREEZE.md step 8 (re-provision from the tag) cover most of this. The soak does not exercise udev/gpsd/chrony anyway."
    evidence_status: "none provided"
  - finding: "WR-03 / IN-01 (review): 'restauré' alerts can never be cleared until the core restarts. The first write after a .bak restore turns the corrupt main into the .bak."
    category: other
    reason: "UX and low-probability durability issues on the race path. 04-05's truths (alert shown, .bak adopted, happy path unchanged) hold."
    evidence_status: "none provided"
human_verification:
  - test: "Laptop race-36h soak on the merged HEAD (follow-up, not a code gap): `bash scripts/soak.sh --scenario race-36h` on a clean tree, so the report carries the 04-04 `code` block"
    expected: "Verdict PASS. freeze-check F3 then PASS (today F3 FAILs 'code modifié depuis le soak (0fff60c -> HEAD : atomicio.py, router_service.py, course.py …)', as expected after 04-04/04-05)"
    why_human: "About 36 min of wall time on the owner's laptop. It must run on the final pre-freeze HEAD."
  - test: "Pi 3B system-scope soak (ROADMAP SC1). First rebuild the wheelhouse (the current deploy/wheelhouse jabuka wheel predates phase 4: F6 shows jabuka/soak/* missing) and re-provision the Pi. Then on the Pi, inside tmux: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`. scp the run dir back, reboot, and check `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0 and `systemctl is-active jabuka-core jabuka-ingest-fastnet` = active active."
    expected: "Startup prints `jabuka-soak: code <12 hex> … source units`. Verdict PASS, tick ratio >= 0.95 (otherwise re-run at --speed 10), core/worker RSS <= 250 MB, no throttled/under-voltage bits, report.json systemd.cleanup.restarted true. freeze-check F4 PASS with 'paquet installé = src/jabuka à HEAD'."
    why_human: "Needs the real Pi 3B with its installed systemd units"
  - test: "Record the Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer' (also closes 03-05 'Pi memory')"
    expected: "Table filled; the numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j, 01-UAT #7)"
    expected: "Services come back on their own each time, logcheck OK, course and settings intact (a '.bak restauré' alert is acceptable and must be visible)"
    why_human: "Physical power interruption"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md: lock review and hash, tag race-2026, wheelhouse rebuilt from the tag, Pi re-provisioned, `bash scripts/freeze-check.sh` all PASS except F8 WARN and F9 HUMAN"
    expected: "freeze-check exit 0; only configuration changes after this point"
    why_human: "Owner decisions and a future-dated event"
  - test: "Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3). Step 5's FINGERPRINT_SH must give the same hex on both cards and equal the Pi report's code.sha256."
    expected: "jabuka-core and jabuka-ingest-fastnet active, logcheck OK, fastnet-probe --file exits 0, same fingerprint, tablet opens http://10.42.0.1"
    why_human: "Physical SD cards and Pi boot"
  - test: "12 Nov: replay the boat's real capture: `bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`"
    expected: "5 PASS lines; every decoded inventory path served by /api/state; logcheck OK"
    why_human: "The real Hercules capture only exists on 12 Nov"
  - test: "On-boat commissioning per docs/COMMISSIONING.md §2–§9 on 12–13 Nov"
    expected: "The helm tablet shows live wind (or MANUEL / GRIB) and laylines to the first mark over the boat Wi-Fi, readable at night (ROADMAP SC4)"
    why_human: "Real boat, instruments, tablet and night conditions"
  - test: "Owner reads docs/COMMISSIONING.md once and adjusts the 12 Nov timings; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md and the new SL 'obnovljen iz varnostne kopije' strings"
    expected: "Timings fit; wording correct"
    why_human: "Owner logistics and native-language review"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-07T23:44:47Z (main 8b35611; code identical to e521191, later commits are .planning only)
**Status:** gaps_found
**Re-verification:** Yes, after gap closure (04-04, 04-05)

## Verdict on the original F4 gap

**The original F4 gap is closed. A narrower part of the same truth is still open, and CR-01 is real.**

**What is closed.** A Pi soak run exactly as documented now yields a report that F4 can PASS. The documented run is: repo rsync'd without .git, then `sudo … --systemd system … --logs-fs loop:512M`. I checked this against the code, not the summary:
- `compute_code_identity` (system scope) reads the installed units' ExecStart and finds the package statically with `venv_package()`. It also hashes each unit's `FragmentPath`.
- `identity_messages` refuses (exit 2) when there is no identity, before any unit is touched.
- I built a wheel from HEAD with `uv build`, exactly as `scripts/build-wheelhouse.sh` does. Its `jabuka/` fingerprint is `ade59271…6862` (146 files), identical to `git archive HEAD src/jabuka` and to `src/jabuka`. So a Pi installed from a wheelhouse built at HEAD will match.
- `deploy/provision.sh` installs both unit files verbatim (`install -D -m 0644`), so `code.units` will match `deploy/systemd` at HEAD.
- Byte drift, a stale venv under a checkout at HEAD (WR-03) and unit drift all FAIL (tests pass).

**What is still open (CR-01, reproduced against the real script).** F4 does not check that the Pi report came from the system-scope procedure. `code_state()` checks units only when `code.source == "units"`. Every other source counts as a full match, and line 180 then PASSes whenever `git.head` is null.

I ran the scratchpad reproduction (`test_cr01.py`, 2 passed). An aarch64 race-36h report with `source: children`, `mode: shim` and git null gives `[PASS] F4 Pi : … paquet installé = src/jabuka à HEAD`.

On the Pi, forgetting `sudo … --systemd system`, or using `--systemd user`, produces exactly that report. Mode is `"systemd"` for both scopes, so only `code.source` distinguishes them. A green F4 would then certify a run that never exercised the installed units' Restart/Watchdog/notify/hardening. FREEZE.md step 2 and CONTEXT §Pi specifics say the Pi soak is the `--systemd` run against the installed units.

This is not a regression: the old git rule never looked at mode either. But it means F4 does not yet enforce "passes only for the documented Pi soak". The fix is about 10 lines plus 3 tests (see Gaps). Given the reproduction and the 2-day margin, I keep it as a gap rather than downgrading it to a warning. If the owner prefers to accept it, use the override below.

**Do the review warnings undermine the 10 Nov Pi soak path? No, both are backstopped. Both are confirmed in code and recorded as advisory.**
- **WR-01: a failed restart is accepted as done.** It is real: `restarted = rc == 0`, `cleaned = True` regardless, the verdict ignores it, and `--systemd-cleanup` exits 0. The documented step 7 catches it: it reboots, which clears the `/run` drop-ins and starts the enabled units on their production config, then checks `systemctl is-active … = active active`.
- **WR-02: the report is lost on a signal during cleanup.** It is real: the deferred signal is re-raised at `soak.py:785`, before `write_report` at L1309. The window is the end-of-run cleanup only. The failure mode is "no report, re-run" (step 8), never a false PASS.
- **A bigger risk for the same path:** any SSH drop during the whole 2-4 h run kills it. `main()` overrides SIGHUP even under `nohup`, and SOAK.md does not say to use tmux/screen. I added "inside tmux" to the Pi human item; consider adding it to SOAK.md step 2.

## User Flow Coverage (MVP mode)

The restated user story passes `user-story.validate` (same restatement as 04-04/04-05 plans): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Prove 36 h of faults on the laptop | One command, every CONTEXT fault, budgets | Harness unchanged and green in the gate. The race-36h report on merged HEAD is pending (F3 FAIL "code modifié depuis le soak", expected) | ✓ code / ? human re-run |
| Prove it on the Pi 3B | Same soak against the installed units, identity recorded | `--systemd system` + code identity + tmpfs refusal + reordered cleanup; tests pass | ? human (hardware) |
| Freeze on 11 Nov | Checklist + checker green, only for the right reports | Documented Pi report can now reach F4 PASS; **F4 also PASSes a shim/user Pi report (CR-01)** | ✗ partial (gap) |
| Spare SD | Clone boots to the same state | SPARE-SD.md step 5 quotes FINGERPRINT_SH verbatim (test-bound) | ? human |
| Commission on 12–13 Nov | Timed runbook, rehearsed | COMMISSIONING.md + rehearsal (unchanged, gate green) | ✓ doc / ? human on board |
| Tablet trustworthy at night | Wind + laylines; no silent fallback | 04-05: `.bak` restore now announced; a wedged pool turns the route stale and withdraws it | ✓ code / ? human on board |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h ~60× soak **on the Pi 3B** with faults; recovery, memory, tablet | ? HUMAN | Pi run due 2026-11-10. The harness path is now safe (tmpfs refused, OOM -900, identity gate) |
| SC2 | Runbook exists, dry-run against replayed capture, all listed topics | ✓ VERIFIED | Regression: test_runbook_docs / test_rehearsal in green gate (var/gate-e521191.log: 1588 passed, 4 skipped, both interpreters, `check: ok`) |
| SC3 | Frozen 2026-11-11; spare SD boots same; 12 Nov capture replays; config-only | ? HUMAN (+ 02-4 gap) | Future-dated events; the F4 integrity gap is tracked under 02-4 |
| SC4 | Helm tablet shows live/manual/GRIB wind + laylines at night | ? HUMAN | Software from Phase 2, unchanged |
| 01-1 | One command, SimClock ~60×, faults, report.json + report.md | ✓ VERIFIED | Regression: test_ci_soak in green gate; report now also carries `code` |
| 01-2 | Tablet sees data within budgets; new route after restart; no land crossing | ✓ VERIFIED | Regression (gate) |
| 01-3 | State survives pulls; corrupt state never stops the core | ✓ VERIFIED | test_state_corruption.py (passed in my targeted run) |
| 01-4 | RSS/leak/fd/threads/logs within budget | ✓ VERIFIED | Regression (gate) |
| 01-5 | No unexpected traceback / error counter | ✓ VERIFIED | Regression (gate) |
| 01-6 | GPS clock path end to end | ✓ VERIFIED | Regression (gate) |
| 01-7 | CI soak in the gate on both interpreters; findings regression-tested | ✓ VERIFIED | var/gate-e521191.log, both runs 1588 passed |
| 02-1 | French timed runbook, nine sections | ✓ VERIFIED | Unchanged; doc tests green |
| 02-2 | Rehearsal script PASS/FAIL/HUMAN, `--capture` | ✓ VERIFIED | Unchanged; tests green |
| 02-3 | Runbook bound to code | ✓ VERIFIED | Unchanged; tests green |
| 02-4 | Freeze checker passes **only** with laptop and Pi race-36h PASS on code identical to HEAD | ✗ PARTIAL | Documented Pi path now PASSes (closed). Fail-open: aarch64 `source children` / shim / user report PASSes F4, and a no-code report falls back to the git rule (CR-01, reproduced) |
| 02-5 | SPARE-SD.md: dd + rpi-clone, checks, swap, overlay | ✓ VERIFIED | Step 5 now uses FINGERPRINT_SH (grep: 1 match) |
| 03-1 | Pi `--systemd system` against installed units, cleanup always | ? HUMAN (software ✓) | Cleanup reordered and retryable (tests); real run human. WR-01 advisory |
| 03-2 | User-scope e2e on the laptop | ✓ VERIFIED | test_soak_systemd.py passed in my targeted run |
| 03-3 | Laptop race-36h PASS, leak fit enforced | ✓ VERIFIED (historic) | Report 20261107T133350Z on 0fff60c stands as evidence of harness behaviour. A re-run on merged HEAD is needed for F3 (human follow-up) |
| 03-4 | Pi report records temperature/throttling | ✓ VERIFIED (code) | Unchanged |
| 04-1 | Documented Pi run writes `code` (units' venv fingerprint, file count, dir, unit sha256s); git kept when present | ✓ VERIFIED | `compute_code_identity` L409-434 (system: `venv_package(core_bin)`, `_unit_file_sha256` via FragmentPath); test_compute_code_identity_system_scope_uses_the_units_venv; my wheel-vs-HEAD fingerprint check matches |
| 04-2 | F3/F4 PASS on code match (+units for system scope) even with head null; FAIL on differ/unit drift/no identity; git rules on top when head present | ✓ VERIFIED (as specified) | freeze-check.sh L121-191; 7 new tests pass. Note: the spec itself only checks units for source 'units' → CR-01 under 02-4 |
| 04-3 | WR-03: checkout at HEAD + different venv → F4 FAIL | ✓ VERIFIED | test_f4_non_git_checkout_at_head_with_a_stale_venv_is_rejected |
| 04-4 | Identity printed at start; system scope refuses without fingerprint; WARNING elsewhere | ✓ VERIFIED | `identity_messages` L1177-1211, run_soak L1289-1302; test_run_soak_refuses_system_scope_without_a_code_identity |
| 04-5 | WR-02: tmpfs refused in system scope (explicit, scenario default, auto+disk-full); harness oom -900 | ✓ VERIFIED | My CLI run: race-36h default → rc 2 "loop:" hint, run dir empty; `--logs-fs tmpfs:64M` → rc 2; `loop:512M` → passes to the sudo check (rc 2 "sudo"). `protect_from_oom` tested |
| 04-6 | WR-01: drop-ins → reload → restart → unmount; done only at end; retried after interruption; signals deferred | ✓ VERIFIED (as specified) | systemd.py L747-794; cleanup-order / interrupted-retry / deferred-SIGHUP tests pass. Residual: failed restart still marked done (advisory) |
| 04-7 | One fingerprint definition; docs quote it; parity tested | ✓ VERIFIED | FINGERPRINT_SH in SOAK/FREEZE/SPARE-SD (grep 1 each); parity test passes; my independent shell / wheel / git-archive hexes agree |
| 04-8 | Docs describe the rule; gate + CI soak green | ✓ VERIFIED | PI-SETUP §3 keeps `--exclude '.git'` + code.sha256 sentence; gate log green |
| 05-1 | Corrupt course.json + valid .bak → .bak course + "Parcours restauré…" alert (FR/EN/SL) | ✓ VERIFIED | course.py L247-251 `load_json_status(..., validate=_parse_course_file)`; i18n.js FR/EN/SL strings + SRV_EXACT; tests pass |
| 05-2 | Same for settings.json / wind_manual.json | ✓ VERIFIED | settings.py; i18n strings present; tests pass |
| 05-3 | Schema-invalid main falls through to valid .bak; neither → default + "illisible" | ✓ VERIFIED | atomicio.py L54-90 validate hook; tests pass |
| 05-4 | Happy path unchanged | ✓ VERIFIED | Happy-path tests; validate only runs on decoded candidates |
| 05-5 | WR-05: recycled pool with in-flight cycle counts as failed → stale, retry, withdrawal | ✓ VERIFIED | router_service.py L868-871 `_failed(self.last_request, …)` when `_inflight > 0`; test_supervisor passes |
| 05-6 | Gate + CI soak green | ✓ VERIFIED | var/gate-e521191.log |

**Score:** 29/34 truths verified (0 present-but-behavior-unverified; 1 partial gap; 4 human-only)

### Advisory (New Scope, Unevidenced)

| # | Finding | Category | Why Advisory |
|---|---------|----------|--------------|
| 1 | WR-01 failed restart marked done, verdict unaffected, `--systemd-cleanup` exit 0 | other | Confirmed in code. SOAK.md step 7 reboot + `is-active` backstops it; no failing test |
| 2 | WR-02 deferred signal re-raised before `write_report` → report lost | other | Confirmed in code. Short window, failure mode is "re-run", never a false PASS. Larger related risk: SSH drop over the whole run (no tmux in SOAK.md) |
| 3 | WR-04 git-less path covers src/jabuka + 2 units only | other | F3 git rule, F5 and the FREEZE step 8 re-provision cover most of it |
| 4 | WR-03 / IN-01 un-clearable "restauré" badges; corrupt main becomes .bak on next write | other | UX / low-probability durability; 04-05 truths hold |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/jabuka/soak/report.py` | FINGERPRINT_SH, fingerprint_entries, package_fingerprint, locate_package, venv_package, code_identity | ✓ VERIFIED | Present, used by tools/soak.py, parity-tested |
| `src/jabuka/tools/soak.py` | compute_code_identity, identity_messages, system_logs_fs_error, refusals | ✓ VERIFIED | Wired in run_soak / main; CLI spot-checks pass |
| `src/jabuka/soak/systemd.py` | Reordered retryable cleanup, deferred signals, protect_from_oom | ✓ VERIFIED (WR-01 residual) | L718-817 |
| `scripts/freeze-check.sh` | F3/F4 fingerprint rule | ⚠️ PARTIAL | Rule works for the documented path; no source/mode check (CR-01) |
| `tests/soak/test_soak_identity.py` | parity, locate/venv, gate, docs | ✓ VERIFIED | Passed |
| `tests/commissioning/test_freeze_check.py` | non_git accept/reject | ✓ VERIFIED / ⚠️ missing negative case for source 'children' | Passed |
| `src/jabuka/common/atomicio.py`, `nav/course.py`, `nav/settings.py`, `web/static/i18n.js` | .bak alerts | ✓ VERIFIED | |
| `src/jabuka/core/router_service.py` | recycle counts as failure | ✓ VERIFIED | |
| docs SOAK/FREEZE/SPARE-SD, deploy/PI-SETUP.md | New rule described | ✓ VERIFIED | |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| tools/soak.py | soak/report.py | compute_code_identity → rep.code_identity; build_report writes `code` | ✓ WIRED | |
| tools/soak.py | installed jabuka-core.service | `_installed_argv` → `venv_package`; FragmentPath sha256 | ✓ WIRED | provision.sh installs units verbatim |
| freeze-check.sh | var/soak/*/report.json | code.sha256 vs `git archive HEAD src/jabuka`; code.units vs `git show HEAD:deploy/systemd/<unit>` | ⚠️ PARTIAL | code.units read only when source == 'units'; mode/source not enforced for aarch64 |
| docs/SPARE-SD.md | report.py | FINGERPRINT_SH verbatim | ✓ WIRED | doc test |
| nav/course.py | atomicio.py | `load_json_status(..., validate=)` | ✓ WIRED | |
| router_service.py | `_failed` / withdrawal | `_recycle_pool` → `_failed(self.last_request, …)` | ✓ WIRED | |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| report.json `code` (system scope) | sha256 / units | installed venv files + unit FragmentPath | Yes (static read; wheel from HEAD fingerprints equal to HEAD) | ✓ FLOWING |
| report.json `code` (shim) | sha256 | `locate_package(python -I)` | Yes (tracer/CI reports per 04-04 SUMMARY; parity test) | ✓ FLOWING |
| freeze-check F4 | cstate | report `code` + git archive HEAD | Yes | ✓ FLOWING (but accepts any source) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Gap-closure test files | `.venv313/bin/python -m pytest tests/commissioning/test_freeze_check.py tests/soak/test_soak_identity.py tests/soak/test_soak_systemd.py tests/nav/test_state_corruption.py tests/routing/test_supervisor.py tests/soak/test_soak_probes.py` | 124 passed in 31 s | ✓ PASS |
| Full gate (orchestrator log) | `tail var/gate-e521191.log` | 1588 passed, 4 skipped ×2, `check: ok`, EXIT=0 | ✓ PASS |
| CR-01 reproduction | `pytest scratchpad/t/test_cr01.py -s` | Both tests pass: `('PASS', 'Pi : …/20261110T070000Z-race-36h-pi/report.json PASS, paquet installé = src/jabuka à HEAD …')` for source 'children', mode 'shim' | ✗ FAIL (gap confirmed) |
| Documented install fingerprints to HEAD | `uv build --wheel` → extract → FINGERPRINT_SH; vs src/jabuka; vs `git archive HEAD src/jabuka` + fingerprint_entries | `ade592717aa1…6862` (146 files) all three | ✓ PASS |
| tmpfs refusal (system scope) | `python -m jabuka.tools.soak --systemd system --scenario race-36h --out <scratch>` | rc 2, "loop:" hint, no run dir | ✓ PASS |
| explicit tmpfs | `… --logs-fs tmpfs:64M` | rc 2 | ✓ PASS |
| loop accepted past the check | `… --logs-fs loop:512M` | rc 2 with the sudo hint (non-root) | ✓ PASS |
| freeze-check on repo | `bash scripts/freeze-check.sh --pre --skip-gate` | F1 PASS; F3 FAIL code changed since 0fff60c (laptop re-soak pending); F4 FAIL no Pi report; F5 FAIL (À REMPLIR); F6 FAIL stale wheelhouse (no jabuka/soak); F8 WARN 18; F9 HUMAN; exit 1 | ✓ as expected today |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and the plans declare none. The phase's runnable checks were run directly above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-02 | 04-01, 04-03, 04-04, 04-05 | ~36 h unattended on the Pi 3B, verified by an accelerated fault-injected soak | ? NEEDS HUMAN (software ✓; freeze gate partial) | Harness and Pi path ready; the Pi run is human (10 Nov); F4 integrity gap open |
| REL-03 | 04-02, 04-04 | On-boat commissioning runbook for 12–13 Nov | ✓ SATISFIED (doc) | COMMISSIONING/FREEZE/SPARE-SD; on-board execution human |

No orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and both are claimed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| scripts/freeze-check.sh | 131-143, 180-181 | Fail-open PASS branch (source not checked) | 🛑 Blocker (gap 02-4) | F4 can certify a non-system-scope Pi soak |
| src/jabuka/soak/systemd.py | 778-791 | rc-only restart outcome, marked done anyway | ⚠️ Warning | Backstopped by SOAK.md step 7 |
| src/jabuka/tools/soak.py | 785 vs 1309 | Re-raised signal before report write | ⚠️ Warning | Report lost in the cleanup window |
| docs/FREEZE.md | 67 | `Lock revu : sha256 À REMPLIR` | ℹ️ Info | Intentional owner input, enforced by F5 |
| — | — | TBD/FIXME/XXX/TODO/HACK in 04-04/04-05 files | none | Scan clean |

### Human Verification Required

1. **Laptop race-36h on merged HEAD.** Run `bash scripts/soak.sh --scenario race-36h` on a clean tree, then check that F3 PASSes.
2. **Pi 3B system-scope soak.** Rebuild the wheelhouse first (the current one predates phase 4) and re-provision. Run the soak inside tmux with `--logs-fs loop:512M`. Expect PASS, a "source units" identity line, and RSS within budget. Then reboot and check: no drop-in left, units active.
3. **Pi budgets.** Fill in SOAK.md "Budgets Pi à confirmer".
4. **5 real power pulls.** Run logcheck after each pull.
5. **Freeze on 11 Nov.** Follow FREEZE.md. `freeze-check` must give exit 0, after the 02-4 gap is fixed.
6. **Spare SD.** Clone and boot it; the fingerprint must equal the original card's and the Pi report's `code.sha256`.
7. **12 Nov capture replay.** Run the rehearsal with `--capture`.
8. **On-board commissioning on 12–13 Nov.** The helm tablet must show wind and laylines at night.
9. **Runbook timings and SL proofreading.** Include the new "obnovljen iz varnostne kopije" strings.

### Gaps Summary

One gap remains. It is the same freeze-gate truth as before, now much narrower.

The original defect was that the documented Pi soak could never pass F4. It is fixed and verified independently:
- the system-scope identity is read from the installed units' venv;
- a wheel built at HEAD fingerprints identically to `src/jabuka` at HEAD;
- the units are installed verbatim;
- drift of any kind FAILs.

What remains is that F4 does not insist the aarch64 report came from the system-scope procedure. Any report whose package fingerprint matches HEAD and whose `git.head` is null PASSes, including a shim or `--systemd user` run on the Pi. I reproduced this against the real script. Reports with no `code` block still fall back to the git rule.

The fix is small:
- require `code.source == "units"` for F4 (`mode` cannot tell user scope from system scope);
- make an absent `code` block a FAIL;
- add three negative tests.

It should land before the 11 Nov freeze; the 10 Nov Pi soak does not depend on it.

**If the owner decides to accept this instead** (the docs prescribe `sudo … --systemd system`, and report.md shows mode and source), add to this file's frontmatter:

```yaml
overrides:
  - must_have: "The 2026-11-11 freeze checker passes only with a clean tree, a green gate, laptop AND Pi race-36h soak reports PASS on code identical to HEAD"
    reason: "F4 proves the installed package equals HEAD; the system-scope procedure is enforced by docs/SOAK.md and visible in report.md (mode/source), not by freeze-check"
    accepted_by: "<owner>"
    accepted_at: "<ISO timestamp>"
```

WR-01 and WR-02 are confirmed in code. They do not compromise the 10 Nov Pi soak path:
- WR-01 (a failed restart counted as done) is caught by SOAK.md step 7, which reboots and checks `is-active`.
- WR-02 (a signal during cleanup loses report.json) can only cost a re-run, never produce a false PASS.

Both are cheap to fix alongside the gap. Separately, I recommend that SOAK.md step 2 tell the owner to run the Pi soak inside tmux, because an SSH drop at any point of the 2-4 h run kills it.

---

_Verified: 2026-11-07T23:44:47Z_
_Verifier: Claude (gsd-verifier)_
