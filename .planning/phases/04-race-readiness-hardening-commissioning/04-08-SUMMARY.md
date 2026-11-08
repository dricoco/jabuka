---
phase: 04-race-readiness-hardening-commissioning
plan: 08
subsystem: testing
tags: [soak, systemd, journalctl, signals, freeze-check, docs]
status: complete

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: "04-07 end-of-run SignalHold, full-length F3/F4 rule, freeze-check helper"
provides:
  - "journalctl/umount/vcgencmd run in their own session at the end of a soak (CR-01)"
  - "SystemdBackend.journal {complete, error, entries} -> report.json systemd.journal"
  - "journal_problem(): an incomplete or missing journal copy FAILs the tracebacks check and the verdict"
  - "report.json end_signal; report.md 'Soak interrompu'"
  - "freeze-check end_state(): F3/F4 FAIL « soak interrompu » and « copie du journal des unités incomplète »"
  - "IN-01 un-mask remedy, IN-02 held-signal stderr line + tee -i, SOAK.md/FREEZE.md rules"
affects: [pi-soak-2026-11-10, freeze-2026-11-11, wheelhouse]

plan_head_before: 7dcfab8011a1ee67ab05a4ad1c8cd50c1e4eac35
actuals:
  tokens: 7900
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - "Every end-of-run child process runs with start_new_session=True"
    - "Evidence copies record {complete, error, entries}; an incomplete copy FAILs closed"
    - "freeze-check states ordered: error > not-scenario/short > interrupted/journal > code states"

key-files:
  created: []
  modified:
    - src/jabuka/soak/systemd.py
    - src/jabuka/soak/probes.py
    - src/jabuka/tools/soak.py
    - src/jabuka/soak/report.py
    - scripts/freeze-check.sh
    - scripts/soak.sh
    - tests/soak/test_soak_systemd.py
    - tests/commissioning/test_freeze_check.py
    - tests/soak/test_soak_identity.py
    - docs/SOAK.md
    - docs/FREEZE.md

key-decisions:
  - "JOURNAL_TIMEOUT_S = 300 s; an empty unit is an error only in system scope (user journal may be volatile)"
  - "end_signal = end hold signal, else the cleanup's pending_signal; absent end_signal FAILs F3/F4 (older bench, fail closed)"
  - "IN-03 (laptop userns parent 30 s wait) and run ordering by t0_wall stay deferred per plan"

requirements-completed: []

coverage:
  - id: D1
    description: "Group SIGINT during the journal copy no longer truncates it; failed copies are recorded and FAIL the verdict"
    requirement: REL-02
    verification:
      - kind: integration
        ref: "tests/soak/test_soak_systemd.py#test_group_sigint_during_the_journal_copy_keeps_the_whole_journal"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_a_failed_journal_copy_is_recorded_never_silent"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_incomplete_journal_copy_fails_the_tracebacks_check_and_the_verdict"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_end_of_run_children_get_their_own_session"
        status: pass
      - kind: e2e
        ref: "tests/soak/test_soak_systemd.py#test_user_scope_tracer_end_to_end"
        status: pass
    human_judgment: false
  - id: D2
    description: "report.json end_signal; freeze-check F3/F4 refuse an interrupted / end_signal-less soak and an incomplete journal copy; a genuine full-length report still PASSes"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/commissioning/test_freeze_check.py#test_f3_f4_interrupted_soak_fails"
        status: pass
      - kind: unit
        ref: "tests/commissioning/test_freeze_check.py#test_f3_f4_report_without_end_signal_fails_closed"
        status: pass
      - kind: unit
        ref: "tests/commissioning/test_freeze_check.py#test_f4_incomplete_journal_copy_fails"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_run_soak_records_the_end_signal_in_report_json"
        status: pass
      - kind: e2e
        ref: "var/soak-04-08/freeze-full.txt [PASS] F3 + var/soak-04-08/freeze-interrupted.txt [FAIL] soak interrompu"
        status: pass
    human_judgment: false
  - id: D3
    description: "SOAK.md / FREEZE.md describe the isolation, interrupted and journal rules, ~15 min threshold; soak.sh tee -i"
    requirement: REL-03
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_docs_describe_the_interrupted_soak_and_the_journal_copy"
        status: pass
    human_judgment: true
    rationale: "French operator wording for the 10-11 Nov procedures should be read by the owner; tests only bind keywords"
  - id: D4
    description: "Real Pi system-scope soak confirms journald behaviour (journal complete, end_signal null) under the new rules"
    requirement: REL-02
    verification: []
    human_judgment: true
    rationale: "Needs the real Pi 3B and installed units (Human Item, 2026-11-10)"

duration: 37min
completed: 2026-11-08
---

# Phase 4 Plan 08: Journal copy isolated, interrupted soaks refused Summary

**journalctl, umount and vcgencmd now run in their own session at the end of a soak. Every failed journal copy (rc, signal, 300 s timeout, error, or an empty unit in system scope) is recorded in `systemd.journal` and FAILs the tracebacks check and the verdict. report.json records `end_signal`, and freeze-check F3/F4 refuse an interrupted soak or an incomplete journal copy. This closes gap 07-5 / review CR-01.**

REL-02 and REL-03 are addressed but **not completed**: REQUIREMENTS.md is untouched (`requirements-completed: []`). The real Pi soak and the full laptop re-run remain human items.

## Performance

- **Duration:** 37 min
- **Started:** 2026-11-08T19:43:20Z
- **Completed:** 2026-11-08T20:20:04Z
- **Tasks:** 3 (tracer + 2)
- **Files modified:** 11
- **plan_head_before:** 7dcfab8011a1ee67ab05a4ad1c8cd50c1e4eac35 (7 commits measured)

## Accomplishments

- **CR-01 closed.** The cr01 repro is now a permanent child-process test. It uses the real `dump_journal` and the real `SignalHold`, with an `os.killpg` SIGINT at 0.5 s, inside a driver that leads its own session.
  - Before the fix: `{'held': 2, 'journal': None, 'blocks': 0, 'text': '1.000 started\n'}`.
  - After: `held` is 2 (SIGINT) and `journal.complete` is true. `entries.core` is 4, the copy contains `RuntimeError: boom`, and **1 traceback block** is found.
  - Timeout variant (`JOURNAL_TIMEOUT_S` = 1, `exec sleep 10`): the error is `journalctl timed out after 1 s`. `dump_journal` returns well under 8 s. Through `build_report`, the tracebacks detail reads `journal dump incomplete (journalctl timed out after 1 s); `, the verdict is FAIL, and the fail reason starts with `check tracebacks: journal dump incomplete`.
  - Other variants recorded:
    - rc 1 gives `journalctl rc 1: boom` (both role files are still written);
    - a journalctl killed by SIGKILL gives `rc -9`;
    - a missing binary gives `journalctl: FileNotFoundError(…)`;
    - in system scope, a unit with no entry gives `no journal entry for jabuka-ingest-fastnet.service`;
    - in user scope, an empty copy is complete;
    - a whole copy gives `{core: 2, ingest: 2}`, matching `info()['journal']`.
- **IN-02:** the first held signal prints `jabuka-soak: signal <n> held until the end of the soak is finished (journal copy, checks, cleanup, report.json; up to ~15 min); do not kill -9 before`. It is written with `os.write`, so a dead pipe never raises (tested). `scripts/soak.sh` now pipes through `tee -i`.
- **end_signal:** `build_report` writes `null`. `run_soak` sets it to the end-hold signal, otherwise the cleanup's `pending_signal`, just before `write_report`. All three paths are tested. report.md shows « Soak interrompu » for an int (not a bool).
- **freeze-check** `end_state()` FAILs with these lines (from the new fixtures):
  - Interrupted: `[FAIL] F3 portable : var/soak/20261110T060000Z-race-36h-laptop/report.json soak interrompu (signal 2 reçu à la fin du soak) : F3/F4 ne comptent qu'un soak terminé sans signal : le refaire et attendre « jabuka-soak: verdict » sans Ctrl-C (docs/SOAK.md)`
  - end_signal absent (F3 and F4 alike): `[FAIL] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json soak interrompu (end_signal absent : banc antérieur au plan 04-08) : …`
  - Incomplete journal: `[FAIL] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json copie du journal des unités incomplète (journalctl rc -2:) : les traces n'ont pas toutes été lues : refaire le soak (docs/SOAK.md)`
  - IN-01 suffix (short / not-scenario): `… ; si un soak complet plus ancien est dans var/soak, déplacer var/soak/20261111T000000Z-race-36h-quick/report.json vers var/soak-essais/ puis relancer freeze-check`
- **Real-report evidence** (a real `--duration 900` harness run in var/soak-04-08/e2e: report `end_signal` null, verdict PASS, git.head 87d01a2). The run was copied into a `--depth 1` clone of HEAD and reshaped to full length:
  - var/soak-04-08/freeze-full.txt: `[PASS] F3 portable : var/soak/20261108T195354Z-race-36h/report.json PASS sur 87d01a21daa3, code identique à HEAD`
  - var/soak-04-08/freeze-interrupted.txt (`end_signal` 2): `[FAIL] F3 portable : var/soak/20261108T195354Z-race-36h/report.json soak interrompu (signal 2 reçu à la fin du soak) : F3/F4 ne comptent qu'un soak terminé sans signal : le refaire et attendre « jabuka-soak: verdict » sans Ctrl-C (docs/SOAK.md)`
- **`bash scripts/freeze-check.sh -h`:** prints the whole header, lines 2–36. It now includes the F3+F4 « soak interrompu » / « copie du journal des unités incomplète » sentence and ends with `… skipped[].reason, end_signal and systemd.journal.complete.`, with no `set` line.
- **Docs:** SOAK.md now covers the report.json keys, the corrected end-of-soak sentence (« propre session », « soak interrompu », « journal dump incomplete », `systemd.journal`), the journal paragraph (300 s, own session), Pi step 6 acceptance (exit 0, PASS, non-empty journal files) and step 8 (`~15 min`, do not press Ctrl-C, wait for `jabuka-soak: verdict`). FREEZE.md gains the rule « F3 et F4 (soak terminé sans signal) ».

## Verification

- `tests/soak/test_soak_systemd.py` and `tests/commissioning/test_freeze_check.py`: 76 passed on both .venv (3.14) and .venv313. `tests/soak` + `tests/commissioning` on 3.13: 164 passed, 1 skipped. The 7 targeted Task 1 tests (`-rA`) gave 8 PASSED, including the real user-scope e2e with `systemd.journal.complete` true and `end_signal` null.
- CI soak: `bash scripts/soak.sh --scenario ci --out var/soak-04-08` printed `soak: scenario ci, report …/var/soak-04-08/20261108T201811Z-ci/report.md, verdict PASS (exit 0)`.
- Full gate (`var/gate-04-08.log`): `1633 passed, 4 skipped` per interpreter, `All checks passed!`, then `check: ok` and `EXIT=0`.
- `bash scripts/freeze-check.sh --pre --skip-gate` on this repo exits 1 with F1–F9. The FAILs are the ones the plan expects:
  - `[PASS] F1 arbre de travail propre (fichiers suivis)`
  - `[SKIP] F2 porte non lancée (--skip-gate)`
  - `[FAIL] F3 portable : var/soak/20261107T133350Z-race-36h/report.json ne prouve pas le scénario race-36h de HEAD (scenario_sha256 absent / …) … ; si un soak complet plus ancien est dans var/soak, déplacer … vers var/soak-essais/ puis relancer freeze-check`
  - `[FAIL] F4 pas de rapport race-36h Pi (aarch64) dans var/soak`
  - `[FAIL] F5 verrou non revu ou modifié : docs/FREEZE.md dit « À REMPLIR »`
  - `[FAIL] F6 roue jabuka différente de src/` (wheelhouse is stale)
  - `[SKIP] F7`, `[WARN] F8 18 éléments UAT en attente`, `[HUMAN] F9`
- Invariants:
  - `git diff 7dcfab8..HEAD -- .planning/REQUIREMENTS.md src/jabuka/nav src/jabuka/core src/jabuka/web` is empty.
  - No pre-existing assert was removed (`var/04-08-task1-test.diff` and `var/04-08-task2-test.diff` both have 0 `-assert` lines).
  - No race-36h run dir was added under var/soak: the four that exist are all dated 2026-11-07.

## New src/jabuka fingerprint

`FINGERPRINT_SH` at HEAD (final code commit 87d01a2; later commits touched no src/):

**`c36c79860a3a2f8d97b0f60a5721adc50e131db0760ac6e6b1f337b34a9e2c58`**

This equals `code.sha256` in the e2e report. The wheelhouse rebuilt for the Pi must reproduce it.

## Task Commits

1. **Task 1 (tracer): journal copy isolated and recorded**: `0ed5f74` (test, RED), `776a726` (feat, GREEN)
2. **Task 2: end_signal + F3/F4 interrupted/journal rules + IN-01**: `bdeb0b6` (test, RED), `87d01a2` (feat, GREEN), `6fef0ea` (fix: header wrap)
3. **Task 3: docs + tee -i**: `2ed6241` (test, RED), `039ca1e` (docs, GREEN)

## TDD Gate Compliance

Every task has a `test(04-08)` RED commit before its GREEN commit. RED was assertion-level each time:
- Task 1: the group test got `journal None, text '1.000 started'`.
- Task 2: the freeze-check fixtures still PASSed (`assert 0 == 1`).
- Task 3: `'end_signal' in SOAK.md` failed.

`gsd check tdd-red-evidence` parses node TAP output only, so it cannot classify a pytest run. The RED evidence is recorded here instead.

## Decisions Made

- I followed the interface contract from the plan as written, including its exact error and FAIL strings.
- The IN-01 suffix names `$path` (the report.json path), as the contract specifies. Moving either that file or its run dir un-masks an older soak.

## Deviations from Plan

**1. [Rule 1 - Bug] The freeze-check header split « soak interrompu » across two lines**
- **Found during:** Task 2 acceptance (`grep -c "soak interrompu"` printed 1; 2 are required)
- **Fix:** rewrapped the header. The line count is unchanged, so `-h` still uses `sed -n '2,36p'`.
- **Commit:** `6fef0ea`

**2. [Environment] The precondition snapshot `var/04-08-soak-before.txt` came out empty**
- **Why:** the rtk hook rewrites `ls`, so the `grep race-36h` in the snapshot command matched nothing.
- **What I did instead:** checked the invariant with `rtk proxy ls var/soak`. The only race-36h dirs are dated 2026-11-07 (before this plan started at 2026-11-08T19:43Z), and every run of this plan went to var/soak-04-08.

**3. [Process] Commits on `main`**
- The executor's generic protected-branch halt was not applied. The orchestrator explicitly required sequential commits on main without switching branches, and that matches the project's `branching_strategy: none` history. Every file was staged by explicit path. Nothing under cad/, stl/ or hardware/ was touched.

**Total deviations:** 1 auto-fixed bug, 2 environment/process notes. **Impact:** none on scope.

## Issues Encountered

None. The full gate passed on its first run; the 04-04 e2e flake did not occur.

## Probes skipped (visible)

- **The edge probe was SKIPPED:** `edge-probe.cjs` is missing.
- **The pattern mapper was SKIPPED:** patterns were taken from 04-07 / 04-REVIEW / 04-VERIFICATION.

## Next Phase Readiness / Human Items

- Rebuild the wheelhouse from HEAD (`bash scripts/build-wheelhouse.sh`) and re-provision the Pi, before 2026-11-10. It must reproduce fingerprint `c36c7986…`.
- Run the Pi soak in tmux at full length, before 2026-11-10. **Do not press Ctrl-C at the end.** Accept the run only if all of these hold:
  - exit 0 and verdict PASS;
  - `end_signal` null;
  - `systemd.journal.complete` true;
  - both journal files non-empty.
- Re-run the laptop `bash scripts/soak.sh --scenario race-36h` in full on the final pre-freeze HEAD, on a clean tree. Every earlier laptop report lacks `end_signal` and is refused by design.
- REL-02 and REL-03 stay not-Complete until the real Pi soak PASSes and the phase is re-verified.

---
*Phase: 04-race-readiness-hardening-commissioning*
*Completed: 2026-11-08*

## Self-Check: PASSED
