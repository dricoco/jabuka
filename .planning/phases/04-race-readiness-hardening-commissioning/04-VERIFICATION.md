---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-08T19:20:29Z
status: gaps_found
score: 43/48 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-SUMMARY.md", "deploy/PI-SETUP.md", "docs/COMMISSIONING-SL.md", "docs/COMMISSIONING.md", "docs/FREEZE.md", "docs/SOAK.md", "docs/SPARE-SD.md", "pyproject.toml", "scripts/commissioning-rehearsal.sh", "scripts/freeze-check.sh", "scripts/soak.sh", "src/jabuka/common/atomicio.py", "src/jabuka/core/router_service.py", "src/jabuka/nav/course.py", "src/jabuka/nav/settings.py", "src/jabuka/soak/faults.py", "src/jabuka/soak/report.py", "src/jabuka/soak/scenario.py", "src/jabuka/soak/supervisor.py", "src/jabuka/soak/systemd.py", "src/jabuka/tools/rehearsal.py", "src/jabuka/tools/soak.py", "src/jabuka/web/static/i18n.js", "tests/commissioning/test_freeze_check.py", "tests/nav/test_state_corruption.py", "tests/routing/test_supervisor.py", "tests/soak/test_soak_identity.py", "tests/soak/test_soak_systemd.py"]
covered_digest: "v1:sha256:cc254df8e343efa6e5313f0c16b1c4fa0631e914e1f52241c67cbc0e8dceb0e0"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 35/41
  gaps_closed:
    - "02-4 / 06-1 (previous blocker): freeze-check F3/F4 accepted a shortened `--duration` race-36h run. CLOSED. The helper's head_scenario() + run_state() (scripts/freeze-check.sh L162-195, L221-230) require scenario_sha256 and seed = race-36h.json at HEAD, duration_s >= 129600, sim_s >= 0.99 x 129600 and no skip 'after the end of the run'; not-scenario / short FAIL right after the verdict branch (L246-249), before every PASS branch; missing fields and an unreadable HEAD scenario fail closed. My own real `--scenario race-36h --duration 900` run (verdict PASS, sim_s 1318.2, 93 late skips) now gives `[FAIL] F3 portable : … essai raccourci` on a clone of HEAD 0c12a90 (the previous verification got `[PASS] F3` for the same command). The same report edited to full length gives `[PASS] F3 … PASS sur 0c12a901680b`. The real historic full runs (0832f7f, 0fff60c) have sim_s 129640.6-129654.8, seed 2026 and no skips, so a genuine run satisfies the rule."
    - "WR-01 (previous warning, F3 fingerprint-only PASS when git.head is null): CLOSED. The PASS branch now needs `machine = aarch64` (L258); an x86_64 head-null report FAILs 'git.head inconnu (rapport sans git)' (L260-261). Reproduced on my real report with git.head nulled and a code block matching HEAD: F3 FAIL. Named test passes."
    - "WR-02 (previous warning, a signal during shutdown()/build_report() lost report.json): CLOSED for report loss. Harness.end_signals (SignalHold) starts after the main run (soak.py L795) and is released in run_soak's finally after write_report and _give_back (L1385-1396); 128+n returned after the report. Named tests pass. BUT see the new gap: the hold now lets a PASS be written from a journal that the same signal truncated."
  gaps_remaining: []
  regressions:
    - "New review CR-01 (introduced by 04-07's end-of-run hold): a terminal Ctrl-C/SIGHUP during the end of a `--systemd system` Pi soak kills journalctl (same process group), dump_journal silently writes the truncated journal, the tracebacks check sees no traceback and the verdict can be PASS, which F4 then certifies. Reproduced."
gaps:
  - truth: "WR-02 (04-07 truth 5): from the end of the main run until report.json is written, SIGINT/SIGTERM/SIGHUP are held, never acted on; the window covers shutdown and the journal dump. Consequence for ROADMAP SC1 / 01-5 / 02-4: the Pi soak's PASS (the evidence F4 certifies) must mean the units' journal was scanned for tracebacks."
    status: failed
    reason: "The hold protects only the harness process. In system scope, shutdown() calls dump_journal (src/jabuka/soak/systemd.py L730-770), which runs `journalctl … -o json` with subprocess.run(capture_output=True, timeout=120) and NO start_new_session, ignores the return code, and turns TimeoutExpired/OSError into out = \"\". scripts/soak.sh L76 runs the harness as `\"$PY\" -m jabuka.tools.soak … | tee`, so a terminal Ctrl-C (or a SIGHUP to the foreground group) reaches python (held), tee and journalctl (killed). Before 04-07 the harness died too (no report: fail-safe). Now it carries on: the partial stdout is parsed, proc/core-journal.log is truncated, scan_tracebacks (soak.py L953-970) finds fewer or no blocks, c['tracebacks'] is ok, and the verdict can be PASS. report.json records nothing about the held signal (only the exit code 128+n and a stderr line say so), and freeze-check F4 reads only the verdict. Reproduced with the real SystemdBackend.dump_journal under SignalHold (setsid, fake journalctl printing one line, sleeping 3 s, then a Traceback/RuntimeError): without a signal -> journal has the traceback, 1 block; with os.killpg(SIGINT) at 1 s -> held signal 2, journal '1.000 started\\n' only, 0 traceback blocks. Same silent-empty outcome without any signal when journalctl exceeds 120 s (mocked TimeoutExpired -> no journal file, no error recorded). docs/SOAK.md L101-104 tells the operator that a Ctrl-C during 'copie du journal' is harmless, which is false. The files were modified by 04-07 (0c44c59) and the evidence is deterministic, so the evidence gate keeps this blocking. It is the false-PASS class every earlier round treated as blocking, whereas report loss was only a warning because it never produced a false PASS."
    artifacts:
      - path: "src/jabuka/soak/systemd.py"
        issue: "dump_journal L740-744: no start_new_session, return code ignored, timeout/OSError -> silent empty journal; no journal_error recorded. Same group-sharing for unmount() L899-906 (masked by the umount -l retry)."
      - path: "src/jabuka/tools/soak.py"
        issue: "compute_checks tracebacks L953-970 cannot tell a complete journal from a truncated or missing one; a signal held by end_signals is not recorded in report.json."
      - path: "docs/SOAK.md"
        issue: "L101-104 promise that a Ctrl-C/SIGTERM/SIGHUP during the end of the soak (including 'copie du journal') does not interrupt it."
    missing:
      - "dump_journal: subprocess.run(..., start_new_session=True, timeout ~300); record self.journal_error when rc != 0, on TimeoutExpired or OSError."
      - "compute_checks: when journal_error is set (system/user scope), the tracebacks check is not ok (or None with a fail reason), so the verdict cannot be PASS; say 'journal dump incomplete (…)' in the detail."
      - "Optionally: record the held end-of-run signal in report.json (e.g. end_signal) so a reader and freeze-check can see it; start_new_session for unmount() too."
      - "Test: send SIGINT to the process group during a fake journalctl inside dump_journal under SignalHold; expect the full output or a non-PASS tracebacks check. Plus a TimeoutExpired case."
      - "docs/SOAK.md L101-104: keep the promise only once the journal copy is isolated, or tell the operator not to press Ctrl-C at the end."
advisory:
  - finding: "WR-04 (carried): the git-less F4 path fingerprints src/jabuka plus the two jabuka unit files only; post-soak changes to other deploy/** files or pyproject.toml do not invalidate F4"
    category: other
    reason: "Deferred by 04-06/04-07 with rationale. Its compensating control (F3's git rule) is mandatory again since the WR-01 fix, which I confirmed."
    evidence_status: "none provided"
  - finding: "WR-03 / IN-01 (04-05 era, carried): 'restauré' alerts cannot be cleared until the core restarts; the first write after a .bak restore turns the corrupt main into the .bak"
    category: other
    reason: "Deferred with rationale (race-path change too close to the freeze); 04-05 truths hold."
    evidence_status: "none provided"
  - finding: "Review IN-01 (0c12a90): the newest race-36h report per machine is judged by run-dir name; a quick run left in var/soak masks an older full run (loud FAIL with the var/soak-essais remedy, never a false PASS); a backwards Pi clock could change which report is judged"
    category: other
    reason: "Fail-closed behaviour, tested by test_newest_quick_run_is_judged_and_named. Wording improvement only."
    evidence_status: "test shows FAIL + remedy, not a false PASS"
  - finding: "Review IN-02 (0c12a90): a held Ctrl-C prints nothing and tee dies on it, so the operator sees no further lines; SOAK.md's '~10 min' kill -9 threshold is close to the bounded worst case"
    category: other
    reason: "UX; a kill -9 loses the report (fail-safe, re-run). Becomes more relevant together with the gap above."
    evidence_status: "code read"
  - finding: "Review IN-03 (0c12a90): the laptop userns parent waits only 30 s after terminate() (soak.py L1499-1503) before re-raising while the child may still be writing report.json"
    category: other
    reason: "Laptop only, end of run normally < 30 s; never a false PASS."
    evidence_status: "code read"
human_verification:
  - test: "Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length (no --duration). Quick runs go to `--out var/soak-essais`."
    expected: "Verdict PASS, report.json duration_s 129600, sim_s >= 129600, scenario_sha256 = sha256 of race-36h.json at HEAD (dca4d6aecc19… today), no 'after the end of the run' skips. freeze-check F3 PASS (today F3 FAILs: the 0fff60c report has no scenario_sha256)."
    why_human: "About 40 min of wall time on the owner's laptop, on the final HEAD"
  - test: "Pi 3B system-scope soak (ROADMAP SC1). Rebuild the wheelhouse from the final HEAD (`bash scripts/build-wheelhouse.sh`; F6 FAILs today), re-provision the Pi, install tmux. Inside `tmux new -s soak`: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`. Do NOT press Ctrl-C at the end until the gap above is fixed. scp only that run dir back, reboot, check `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0 and both units active."
    expected: "Startup prints `jabuka-soak: code <fingerprint of src/jabuka at HEAD> … source units`, no WARNING line (in particular no 'shortened run'). Exit code 0 (not 128+n), verdict PASS, proc/core-journal.log and proc/ingest-journal.log present and non-empty, tick ratio >= 0.95, core/worker RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true. freeze-check F4 PASS 'paquet installé = src/jabuka à HEAD'."
    why_human: "Needs the real Pi 3B with its installed systemd units"
  - test: "Record the Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer' (also closes 03-05 'Pi memory')"
    expected: "Table filled; numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j, 01-UAT #7)"
    expected: "Services come back each time, logcheck OK, course and settings intact (a visible '.bak restauré' alert is acceptable)"
    why_human: "Physical power interruption"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md: lock review and hash, tag race-2026, wheelhouse from the tag, Pi re-provisioned, `bash scripts/freeze-check.sh` all PASS except F8 WARN and F9 HUMAN"
    expected: "freeze-check exit 0; only configuration changes afterwards"
    why_human: "Owner decisions and a future-dated event"
  - test: "Clone the spare SD per docs/SPARE-SD.md and boot it (ROADMAP SC3); step 5 FINGERPRINT_SH must give the same hex on both cards and equal the Pi report's code.sha256"
    expected: "jabuka-core and jabuka-ingest-fastnet active, logcheck OK, fastnet-probe --file exits 0, same fingerprint, tablet opens http://10.42.0.1"
    why_human: "Physical SD cards and Pi boot"
  - test: "12 Nov: replay the boat's real capture: `bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`"
    expected: "5 PASS lines; every decoded inventory path served by /api/state; logcheck OK"
    why_human: "The real Hercules capture only exists on 12 Nov"
  - test: "On-boat commissioning per docs/COMMISSIONING.md §2–§9 on 12–13 Nov"
    expected: "The helm tablet shows live wind (or MANUEL / GRIB) and laylines to the first mark over the boat Wi-Fi, readable at night (ROADMAP SC4)"
    why_human: "Real boat, instruments, tablet and night conditions"
  - test: "Owner reads docs/COMMISSIONING.md once and adjusts the 12 Nov timings; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md and the SL 'obnovljen iz varnostne kopije' strings"
    expected: "Timings fit; wording correct"
    why_human: "Owner logistics and native-language review"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-08T19:20:29Z (main 0c12a90; code at ee8d5e2, later commits are .planning only)
**Status:** gaps_found
**Re-verification:** Yes, after gap closure 04-07

## Verdict on the three items 04-07 had to close

| Item | Status | Evidence (my own runs, not the SUMMARY) |
| --- | --- | --- |
| **Blocker 02-4 / 06-1**: F3/F4 accepted a shortened `--duration` race-36h run | **CLOSED** | Real `python -m jabuka.tools.soak --scenario race-36h --duration 900 --out <scratchpad>`: rc 0, verdict PASS, `WARNING: shortened run` on stderr, report.json `duration_s 900.0`, `scenario_duration_s 129600.0`, `scenario_source scenarios/race-36h.json`, `scenario_sha256 dca4d6ae…` (= sha256 of the file), `sim_s 1318.2`, 93 skips, report.md "**Essai raccourci**". In a clone of HEAD: `[FAIL] F3 portable : … essai raccourci (duration_s 900.0 / 129600, sim_s 1318.2, 93 panne(s) après la fin)`. The previous verification got `[PASS] F3` for the same command. The same report edited to full length (duration_s 129600, sim_s 129640.6, no skips) → `[PASS] F3 … PASS sur 0c12a901680b`. The 9 new fixture cases pass, including the Pi system-scope sim_s 600 case (F4 FAIL). |
| **WR-01**: F3 fingerprint-only PASS with `git.head` null | **CLOSED** | `freeze-check.sh` L258 now needs `machine = aarch64`; L260-261 FAIL "git.head inconnu (rapport sans git)". My real report with `git` nulled (code block matching HEAD) → F3 FAIL. Named test passes. |
| **WR-02**: end-of-run signal lost report.json | **CLOSED for report loss** | `Harness.end_signals.start()` at soak.py L795, release in `run_soak` finally after `write_report` + `_give_back` (L1385-1396), 128+n afterwards. Named tests pass. **But it introduces the new blocker below.** |

## New review CR-01: confirmed, and blocking

**Confirmed independently.** I reproduced it, then traced it through the code.

The repro uses the real `SystemdBackend.dump_journal` under the real `SignalHold`, isolated with `setsid`. A fake journalctl prints one entry, sleeps 3 s, then prints a Traceback/RuntimeError:

| Run | Held signal | `core-journal.log` | `rep.scan_tracebacks` blocks |
| --- | --- | --- | --- |
| no signal | None | started + 3 traceback lines | 1 |
| `os.killpg(getpgrp(), SIGINT)` at 1 s | 2 | `'1.000 started\n'` | **0** |

The second run shows the problem: the harness keeps running and the traceback evidence is gone. I also forced a `TimeoutExpired` (journalctl taking more than 120 s). That gives no journal file and no recorded error, so it is the same silent-empty result with no signal involved.

How it reaches F4 in the documented Pi run:
- `scripts/soak.sh` L76 runs the harness as `python … | tee`, so the harness, `tee` and `journalctl` share one process group under the sudo pty.
- A Ctrl-C in the tmux pane reaches all three. Python holds it; `tee` and `journalctl` die.
- `dump_journal` ignores the return code (systemd.py L740-744).
- The tracebacks check (soak.py L953-970) only scans the `proc/*.log` that exist.
- report.json does not record the held signal. F4 reads only `verdict`.

**Why it blocks:**
- 04-07 truth 5 explicitly says the hold covers "the journal dump" and that signals are "never acted on". docs/SOAK.md L101-104 tells the owner a Ctrl-C during "copie du journal" is harmless. Both are false in system scope.
- This is a **regression introduced by 04-07**. Before the hold, the same Ctrl-C killed the harness, so no report was written (fail-safe). Now it can produce a false PASS that F4 certifies as the 36 h Pi evidence (SC1/SC3).
- Every earlier round blocked this false-PASS class. Report loss was rated only a warning because it never certified anything.
- The files were modified this round and the evidence is deterministic, so the evidence gate keeps it blocking.

**Mitigating context (for the owner's decision):**
- The trigger needs a group-wide signal during a short window at the very end of the run (stop, plus a dump of up to 120 s). A plain `kill <pid>` or an SSH drop under tmux does not trigger it.
- The run then exits 130, not 0, and prints "signal 2 received at the end of the run".
- The timeout path is older than 04-07 and its likelihood on the Pi 3B is unmeasured.

**The fix is small.** It is the review's suggestion:
- `start_new_session=True` and a `journal_error` on rc ≠ 0 or timeout.
- A non-PASS tracebacks check when `journal_error` is set.
- One test sending a process-group SIGINT during a fake journalctl.
- Optionally, record the held signal in report.json.

It should land before the 10 Nov Pi soak. Otherwise, follow the human item: do not press Ctrl-C at the end, accept only exit code 0, and check that both `proc/*-journal.log` files are non-empty.

Review IN-01, IN-02 and IN-03 are confirmed by reading the code. They are informational: none produces a false PASS (see Advisory).

## User Flow Coverage (MVP mode)

User story (same restatement as plans 04-04 to 04-07): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Prove 36 h of faults on the laptop | One command, every CONTEXT fault, budgets | Harness green in gate-04-07; CI soak PASS at ee8d5e2 (`var/soak/20261108T190356Z-ci`, code f7ddf1810645). Full race-36h re-run on HEAD pending | ✓ code / ? human re-run |
| Prove it on the Pi 3B | Same soak against the installed units, identity recorded, units restored, verdict trustworthy | `--systemd system`, identity, verified restart, end-of-run hold. **A Ctrl-C at the end can truncate the journal and still give PASS** | ✗ gap (CR-01) / ? human (hardware) |
| Freeze on 11 Nov | Checker green **only** for the real full-length soaks | Full-length rule + F3 git rule closed and reproduced | ✓ checker / ? human event |
| Spare SD | Clone boots to the same state | SPARE-SD.md step 5 FINGERPRINT_SH | ? human |
| Commission on 12–13 Nov | Timed runbook, rehearsed | COMMISSIONING.md + rehearsal (gate green) | ✓ doc / ? human on board |
| Tablet trustworthy at night | Wind + laylines; no silent fallback | 04-05 `.bak` alerts; stale-route withdrawal | ✓ code / ? human on board |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h ~60× soak **on the Pi 3B** with faults; recovery, memory, tablet | ? HUMAN (+ CR-01 gap on verdict integrity) | Pi run due 2026-11-10 |
| SC2 | Runbook exists, dry-run against replayed capture, all listed topics | ✓ VERIFIED | Doc/rehearsal tests in gate-04-07 (1620 passed ×2, `check: ok`, EXIT=0) |
| SC3 | Frozen 2026-11-11; spare SD boots same; 12 Nov capture replays; config-only | ? HUMAN | Future-dated events; freeze gate now counts only full-length runs |
| SC4 | Helm tablet shows live/manual/GRIB wind + laylines at night | ? HUMAN | Phase 2 software, unchanged |
| 01-1 | One command, SimClock ~60×, faults, report.json + report.md | ✓ VERIFIED | My short run produced both; gate |
| 01-2 | Tablet data within budgets; route after restart; no land crossing | ✓ VERIFIED | Regression (gate) |
| 01-3 | State survives pulls; corrupt state never stops the core | ✓ VERIFIED | Regression (gate) |
| 01-4 | RSS/leak/fd/threads/logs within budget | ✓ VERIFIED | Regression (gate) |
| 01-5 | No unexpected traceback / error counter | ✓ VERIFIED (shim/user paths) | Gate. System-scope journal integrity under an end-of-run signal is the 07-5 gap |
| 01-6 | GPS clock path end to end | ✓ VERIFIED | Regression (gate) |
| 01-7 | CI soak in the gate on both interpreters | ✓ VERIFIED | gate-04-07; CI soak PASS at ee8d5e2 |
| 02-1 | French timed runbook, nine sections | ✓ VERIFIED | Unchanged; doc tests green |
| 02-2 | Rehearsal script PASS/FAIL/HUMAN, `--capture` | ✓ VERIFIED | Unchanged; tests green |
| 02-3 | Runbook bound to code | ✓ VERIFIED | Unchanged; tests green |
| 02-4 | Freeze checker passes **only** with laptop and Pi race-36h PASS on code identical to HEAD | ✓ VERIFIED (was PARTIAL) | Full-length rule (L162-195, L221-230, L246-249); real shortened run → F3 FAIL; full-length variant → PASS; 9 fixture cases pass |
| 02-5 | SPARE-SD.md: dd + rpi-clone, checks, swap, overlay | ✓ VERIFIED | Unchanged |
| 03-1 | Pi `--systemd system` against installed units, cleanup always | ? HUMAN (software ✓) | Real run human |
| 03-2 | User-scope e2e on the laptop | ✓ VERIFIED | test_soak_systemd.py passes |
| 03-3 | Laptop race-36h PASS, leak fit enforced | ✓ VERIFIED (historic) | Reports on 0832f7f / 0fff60c; re-run on HEAD is human (F3 needs the new fields) |
| 03-4 | Pi report records temperature/throttling | ✓ VERIFIED (code) | Unchanged |
| 04-1 | Documented Pi run writes `code` (units' venv fingerprint, units) | ✓ VERIFIED | Unchanged; tests pass |
| 04-2 | F3/F4 fingerprint rule (+units for system scope) | ✓ VERIFIED | L137-159; F3 now also always git (L258-261) |
| 04-3 | Checkout at HEAD + stale venv → F4 FAIL | ✓ VERIFIED | Test passes |
| 04-4 | Identity printed; system scope refuses without fingerprint | ✓ VERIFIED | My run printed `jabuka-soak: code f7ddf1810645 (146 files, …, source children); git 0c12a901680b` |
| 04-5 | tmpfs refused in system scope; harness oom -900 | ✓ VERIFIED | Regression (tests) |
| 04-6 | Cleanup order drop-ins → reload → restart → unmount; retryable | ✓ VERIFIED | systemd.py L806-869; tests pass |
| 04-7 | One fingerprint definition; docs quote it; parity tested | ✓ VERIFIED | Harness f7ddf1810645 = SUMMARY's HEAD value |
| 04-8 | Docs describe the rule; gate + CI soak green | ✓ VERIFIED | gate-04-07 |
| 05-1 | Corrupt course.json + valid .bak → .bak + "restauré" alert | ✓ VERIFIED | Unchanged; tests in gate |
| 05-2 | Same for settings.json / wind_manual.json | ✓ VERIFIED | Unchanged |
| 05-3 | Schema-invalid main falls through to .bak; else default + "illisible" | ✓ VERIFIED | Unchanged |
| 05-4 | Happy path unchanged | ✓ VERIFIED | Unchanged |
| 05-5 | Recycled pool with in-flight cycle → stale, retry, withdrawal | ✓ VERIFIED | Unchanged |
| 05-6 | Gate + CI soak green | ✓ VERIFIED | gate-04-07 |
| 06-1 | F4 PASSes an aarch64 report **only** from the documented `--systemd system … --scenario race-36h` run | ✓ VERIFIED (was PARTIAL) | mode/source/code rule (L214-220) + full-length rule; test_f4_shortened_pi_report_fails passes |
| 06-2 | F4 FAILs shim / user-scope / code-less / malformed-sha Pi reports | ✓ VERIFIED | Tests pass |
| 06-3 | F3 laptop report without code judged by the git rule | ✓ VERIFIED | Test passes; head-null now FAILs too |
| 06-4 | Verified restart; retryable; verdict FAIL; `--systemd-cleanup` exit 1; own session | ✓ VERIFIED | `_ctl` start_new_session (L331), `_await_active`, `restarted` (L843); tests pass |
| 06-5 | Signal during cleanup recorded; report written; return 128+n | ✓ VERIFIED | `_deferred_signals` on SignalHold (L791-804); test passes |
| 06-6 | aarch64 shim/user run prints WARNING quoting `--systemd system` | ✓ VERIFIED | Test passes |
| 06-7 | SOAK.md tmux / F4 rule / cleanup outcome; FREEZE.md F4 rule | ✓ VERIFIED | Doc tests pass |
| 07-1 | F3/F4 PASS a race-36h report only when it proves a full-length run of race-36h at HEAD (sha, seed, duration_s, sim_s, no late skip); fail closed | ✓ VERIFIED | Helper L162-230; 9 named cases pass (shortened Pi/laptop, late skip alone, early stop, missing fields / skipped "x", foreign sha / absent / seed 7, scenario missing at HEAD, newest quick run, head-null) |
| 07-2 | Real `--duration 900` run → `[FAIL] F3 … essai raccourci` on a clone of HEAD | ✓ VERIFIED | My own run (sim_s 1318.2, 93 late skips) on a clone of 0c12a90 |
| 07-3 | Harness writes duration_s, scenario_duration_s, scenario_source, scenario_sha256; a genuine full run satisfies the rule; positive fixtures unchanged | ✓ VERIFIED | My report carries all four with correct values; real historic full runs: sim_s ≥ 129640.6, seed 2026, `skipped: []`; full-length variant → F3 PASS; 0 `assert` lines removed in `git diff c02c43a..HEAD` of the test files |
| 07-4 | WR-01: x86_64 head-null → F3 FAIL "git.head inconnu" | ✓ VERIFIED | L258-261; my real-report variant FAILs; named test passes |
| 07-5 | WR-02: signals held from end of main run until report written; window covers shutdown **and the journal dump**; never acted on | ✗ FAILED | Report loss closed, but in system scope the signal kills journalctl (same pgrp, no `start_new_session`) and the truncated journal yields a PASS (repro above). Behaviour-dependent: the named shim-scope tests pass, my system-scope repro fails |
| 07-6 | Shortened run WARNING at start; report.md "Essai raccourci"; SOAK.md/FREEZE.md state the full-length rule, var/soak-essais, F3 git.head, end-of-run hold + kill -9; cleanup docstring fixed | ✓ VERIFIED (content) | WARNING and "Essai raccourci" seen in my run; FREEZE.md L41, L44, L90, L96-101; SOAK.md L48-52, L61, L227-229, L279-283; doc test passes. The L101-104 promise about the journal copy is wrong (part of the 07-5 gap) |
| 07-7 | Both venvs pass tests/soak + tests/commissioning; CI soak PASS; gate `check: ok` / EXIT=0; REQUIREMENTS.md unchanged | ✓ VERIFIED | My targeted run: 91 passed (3.13); var/gate-04-07.log 1620 passed ×2, `check: ok`, EXIT=0; CI soak PASS; `git diff c02c43a..HEAD -- .planning/REQUIREMENTS.md` empty |

**Score:** 43/48 truths verified. 1 failed (07-5). 4 human-only (SC1, SC3, SC4, 03-1). 0 present-but-behaviour-unverified.

### Prohibitions (04-07, test tier)

| Prohibition | Enforcement evidence | Status |
| --- | --- | --- |
| F3/F4 must not PASS a shortened / early-stopped / custom-scenario / other-seed / late-skip / field-less race-36h report | 8 named FAIL tests pass + my real end-to-end run | ✓ enforced |
| Must not reject a genuine full-length report | test_frozen_repo_passes, test_f4_non_git_pi_copy_…, test_report_records_… pass; real historic full runs fit the rule | ✓ enforced |
| F3 must not PASS on a fingerprint alone | test_f3_laptop_report_without_git_head_… passes; my repro | ✓ enforced |
| Must not lose a soak report to a signal between the end of the main run and write_report | Shim-scope tests pass | ✓ enforced (the hold now creates the false-PASS path in 07-5) |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `scripts/freeze-check.sh` | head_scenario/run_state, not-scenario/short FAILs, aarch64-only fingerprint PASS, header + `-h` | ✓ VERIFIED | `-h` contains scenario_sha256, no `set ` line |
| `src/jabuka/soak/scenario.py` | Scenario.sha256 from raw bytes | ✓ VERIFIED | Report sha = `sha256sum` of the file |
| `src/jabuka/tools/soak.py` | SKIP_AFTER_END, new report keys, run_length_messages, end_signals | ✓ VERIFIED | Wired; my run shows all of them |
| `src/jabuka/soak/systemd.py` | SignalHold; `_deferred_signals` on it; docstring | ⚠️ PARTIAL | Present and wired; `dump_journal` not isolated from the held signal (gap) |
| `src/jabuka/soak/report.py` | "Essai raccourci" | ✓ VERIFIED | Seen in my report.md |
| `tests/commissioning/test_freeze_check.py` | 9 new cases | ✓ VERIFIED | Pass |
| `tests/soak/test_soak_identity.py` | run-length/scenario, parity, WARNING, render_md, doc tests | ✓ VERIFIED | Pass |
| `tests/soak/test_soak_systemd.py` | SignalHold, real Harness.run end hold, run_soak | ✓ VERIFIED | Pass; no system-scope journal case (gap) |
| `docs/SOAK.md`, `docs/FREEZE.md` | Full-length rule, var/soak-essais, F3 git.head, hold + kill -9 | ⚠️ PARTIAL | Present; SOAK.md L101-104 overpromises for the journal copy |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| freeze-check.sh | var/soak/*/report.json | head_scenario + run_state → not-scenario / short before any PASS | ✓ WIRED | L221-230 → L246-249 |
| tools/soak.py | soak/scenario.py | build_report writes sc.sha256 / source / duration_s / self.duration | ✓ WIRED | Values seen in my report |
| tools/soak.py | soak/systemd.py | end_signals.start → shutdown/build_report/cleanup → write_report → release → 128+n | ✓ WIRED | L795-811, L1385-1412 |
| SKIP_AFTER_END | freeze-check.sh | parity test | ✓ WIRED | test_freeze_check_matches_the_harness_skip_reason passes |
| SignalHold | journalctl child | the held signal must not reach the evidence-producing child | ✗ NOT_WIRED | No `start_new_session` in dump_journal (gap) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| report.json run length | duration_s / sim_s / skipped / scenario_sha256 | Harness (real run: 900.0 / 1318.2 / 93 / dca4d6ae…) | Yes | ✓ FLOWING |
| freeze-check F3/F4 | state short / not-scenario | report keys + `git show HEAD:…race-36h.json` | Yes | ✓ FLOWING |
| tracebacks check (system scope) | proc/*-journal.log | journalctl stdout | Truncated or empty under a group signal or timeout, with no error recorded | ⚠️ HOLLOW under that condition |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 04-07 test files (3.13) | `pytest tests/commissioning/test_freeze_check.py tests/soak/test_soak_identity.py tests/soak/test_soak_systemd.py` | 91 passed in 31 s | ✓ PASS |
| Full gate (orchestrator log) | `var/gate-04-07.log` | 1620 passed, 4 skipped ×2, `All checks passed!`, `check: ok`, EXIT=0 | ✓ PASS |
| CI soak at HEAD code | `var/soak/20261108T190356Z-ci/report.json` | PASS, git ee8d5e2 clean, code f7ddf1810645, scenario_sha256 present | ✓ PASS |
| Real shortened race-36h | `python -m jabuka.tools.soak --scenario race-36h --duration 900 --out <scratchpad>` | rc 0, PASS, WARNING, 4 new keys, "Essai raccourci" | ✓ PASS |
| Shortened run through freeze-check | clone of 0c12a90 + that report → `freeze-check --pre --skip-gate` | `[FAIL] F3 portable : … essai raccourci (… 93 panne(s) après la fin)` | ✓ PASS (gap closed) |
| Full-length variant | same report, duration_s 129600 / sim_s 129640.6 / skipped [] | `[PASS] F3 … PASS sur 0c12a901680b` | ✓ PASS |
| WR-01 | same full report, git nulled | `[FAIL] F3 … git.head inconnu (rapport sans git)` | ✓ PASS |
| CR-01 repro (signal) | real dump_journal under SignalHold, `setsid`, fake journalctl, killpg SIGINT at 1 s | held 2; journal truncated; 0 traceback blocks (control: 1) | ✗ FAIL (gap) |
| CR-01 repro (timeout) | dump_journal with TimeoutExpired | no file, no error recorded | ✗ FAIL (gap) |
| Debt markers in the 04-07 diff | grep TBD/FIXME/XXX/TODO/HACK on added lines | none | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and the plans declare none. The phase's runnable checks were run directly above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-02 | 04-01, 04-03, 04-04, 04-05, 04-06, 04-07 | ~36 h unattended on the Pi 3B, verified by an accelerated fault-injected soak | ✗ BLOCKED (gap 07-5) + ? NEEDS HUMAN | Freeze gate now sound. The Pi soak verdict can be a false PASS after an end-of-run Ctrl-C. The Pi run itself is human (10 Nov). REQUIREMENTS.md correctly unchecked ("Gaps Found") |
| REL-03 | 04-02, 04-04, 04-06, 04-07 | On-boat commissioning runbook for 12–13 Nov | ✓ SATISFIED (doc) / ? human on board | COMMISSIONING/FREEZE/SOAK/SPARE-SD; FREEZE.md steps 1-2 now say "complet (sans `--duration`)" |

No orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and both are claimed by plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| src/jabuka/soak/systemd.py | 740-744 | Evidence child shares the process group of a signal-holding parent; rc ignored; timeout → silent empty | 🛑 Blocker (gap 07-5) | False PASS of the Pi soak, certified by F4 |
| docs/SOAK.md | 101-104 | Doc promises a Ctrl-C during the journal copy is harmless | ⚠️ Warning (part of the gap) | Invites the trigger |
| src/jabuka/soak/systemd.py | 899-906 | `unmount()` in the same group | ℹ️ Info | Masked by the `umount -l` retry |
| src/jabuka/tools/soak.py | 1499-1503 | userns parent waits 30 s (IN-03) | ℹ️ Info | Laptop; never a false PASS |
| docs/FREEZE.md | "Lock revu" line | `À REMPLIR` | ℹ️ Info | Intentional owner input, enforced by F5 |

### Human Verification Required

1. **Laptop race-36h on the final HEAD, full length.** Quick runs go to `--out var/soak-essais`.
2. **Pi 3B system-scope soak.** Rebuild the wheelhouse and re-provision first. Run inside tmux, and do not press Ctrl-C at the end. Expect exit 0 and non-empty journal copies.
3. **Pi budgets.** Fill in SOAK.md "Budgets Pi à confirmer".
4. **5 real power pulls.** Run logcheck after each one.
5. **Freeze on 11 Nov.** freeze-check must exit 0.
6. **Spare SD.** Clone and boot it; the fingerprint must match.
7. **12 Nov capture replay.**
8. **On-board commissioning on 12–13 Nov.**
9. **Runbook timings and SL proofreading.**

### Gaps Summary

**All three items 04-07 targeted are closed, verified by my own runs rather than the SUMMARY.**
- The freeze gate now counts only a full-length race-36h run of the scenario at HEAD. The verifier's previous `[PASS] F3` reproduction is now `[FAIL] … essai raccourci`, while a full-length report still PASSes.
- F3 always needs `git.head`.
- A signal at the end of a run no longer loses report.json.

**One new blocker, introduced by the WR-02 fix itself (review CR-01, confirmed).**
- The end-of-run hold keeps the harness alive, but a terminal Ctrl-C or a group SIGHUP still kills its `journalctl` child.
- `dump_journal` then silently writes a truncated journal, and the tracebacks check passes on it. A Pi soak can therefore report PASS without its traceback evidence, and F4 certifies it.
- A journalctl timeout over 120 s gives the same silent-empty result. That path is older than 04-07.

**The fix is small:** isolate the child, record a journal error, make the tracebacks check non-PASS on that error, add one test, and correct SOAK.md L101-104. It should land before the 10 Nov Pi soak.

**If the owner prefers to accept the residual instead,** the documented run uses tmux and no Ctrl-C, and the owner checks exit code 0 and the journal files. Add this to the frontmatter:

```yaml
overrides:
  - must_have: "WR-02 (04-07 truth 5): from the end of the main run until report.json is written, SIGINT/SIGTERM/SIGHUP are held, never acted on; the window covers shutdown and the journal dump"
    reason: "Pi soak runs in tmux and is never interrupted at the end; the owner accepts the Pi report only with exit code 0 (not 128+n) and non-empty proc/core-journal.log and proc/ingest-journal.log"
    accepted_by: "<owner>"
    accepted_at: "<ISO timestamp>"
```

---

_Verified: 2026-11-08T19:20:29Z_
_Verifier: Claude (gsd-verifier)_
