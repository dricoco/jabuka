---
phase: 04-race-readiness-hardening-commissioning
plan: 07
subsystem: soak-harness / freeze-gate
status: complete
tags: [freeze-check, soak, signals, gap-closure, REL-02, REL-03]
requires:
  - 04-06 (F4 system-scope rule, pending_signal cleanup deferral)
provides:
  - freeze-check F3/F4 count only a full-length race-36h run of the scenario at HEAD (fail closed)
  - F3 always requires git.head (fingerprint-only PASS limited to aarch64)
  - end-of-run signal hold (report written first, then 128 + signal)
  - report.json keys duration_s, scenario_duration_s, scenario_source, scenario_sha256
affects:
  - docs/SOAK.md, docs/FREEZE.md (owner procedures 10-11 Nov)
tech-stack:
  added: []
  patterns:
    - "Fail-closed checker states (not-scenario, short) placed before every PASS branch"
    - "SignalHold: hold SIGINT/SIGTERM/SIGHUP over a critical section, act after the evidence is written"
key-files:
  created: []
  modified:
    - src/jabuka/soak/scenario.py
    - src/jabuka/tools/soak.py
    - src/jabuka/soak/systemd.py
    - src/jabuka/soak/report.py
    - scripts/freeze-check.sh
    - tests/commissioning/test_freeze_check.py
    - tests/soak/test_soak_identity.py
    - tests/soak/test_soak_systemd.py
    - docs/SOAK.md
    - docs/FREEZE.md
key-decisions:
  - "04-07: freeze-check F3/F4 count a race-36h report only when scenario_sha256 and seed equal race-36h.json at HEAD, duration_s >= its duration_s, sim_s >= 0.99x, and no fault skipped 'after the end of the run'; missing fields or an unreadable HEAD scenario FAIL (fail closed)"
  - "04-07: F3 always needs git.head and the git rule; the fingerprint-only PASS stays F4 (aarch64) only"
  - "04-07: SIGINT/SIGTERM/SIGHUP are held from the end of the main run until report.json is written and handed back; run_soak then exits 128 + signal. A signal during the main run still aborts it."
  - "04-07: the harness verdict of a shortened run is unchanged (PASS/FAIL describes what ran); it is announced by a start WARNING and an 'Essai raccourci' report.md line, and freeze-check is the gate"
requirements-completed: []
duration: 35 min
completed: 2026-11-08
plan_head_before: c02c43a87618aceba57afffee679eac6c80682da
actuals:
  tokens: 8000
  tasks: 3
  commits: 6
coverage:
  - deliverable: "F3/F4 accept only a full-length race-36h run of the scenario at HEAD (CR-01, gap 02-4)"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/commissioning/test_freeze_check.py (9 new cases + unchanged positive cases)"
        status: pass
      - kind: command
        ref: "real `--scenario race-36h --duration 900` run judged on a clone of HEAD -> var/soak-04-07/freeze.txt [FAIL] F3 essai raccourci"
        status: pass
  - deliverable: "F3 requires git.head (WR-01)"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/commissioning/test_freeze_check.py#test_f3_laptop_report_without_git_head_fails_even_with_a_matching_fingerprint"
        status: pass
  - deliverable: "End-of-run signal hold, report written before 128 + signal (WR-02, IN-01)"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/soak/test_soak_systemd.py#test_signal_hold_records_and_restores, #test_signal_at_the_end_of_the_run_is_held_until_the_report_is_written, #test_run_soak_honours_a_signal_held_at_the_end_of_the_run"
        status: pass
  - deliverable: "Report records what ran; shortened run WARNING and 'Essai raccourci'"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/soak/test_soak_identity.py#test_report_records_the_run_length_and_the_scenario, #test_freeze_check_matches_the_harness_skip_reason, #test_shortened_run_is_announced_at_start, #test_report_md_marks_a_shortened_run"
        status: pass
  - deliverable: "SOAK.md / FREEZE.md describe the full-length rule, var/soak-essais, F3 git.head, end-of-run hold and kill -9"
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/soak/test_soak_identity.py#test_docs_describe_the_full_length_rule_and_the_f3_git_rule + tests/commissioning (unchanged)"
        status: pass
  - deliverable: "Genuine full-length laptop and Pi soak on the merged HEAD PASS F3/F4"
    human_judgment: true
    rationale: "Needs the real 36 h laptop run and the 2-4 h Pi soak (human items, 10-11 Nov); the Pi soak has not run"
---

# Phase 4 Plan 07: Freeze-check counts only a full-length race-36h soak Summary

**freeze-check F3/F4 now accept a race-36h report only when its recorded scenario_sha256, seed, duration_s, sim_s and skips prove a full-length run of race-36h.json at HEAD. F3 always needs git.head. The harness holds SIGINT/SIGTERM/SIGHUP from the end of the main run until report.json is written.**

## Performance

- Start: 2026-11-08T18:24Z, end: 2026-11-08T19:05Z (about 35 min, including a 10.5 min gate per interpreter)
- Tasks: 3 (TDD: RED then GREEN commit per task)
- Files: 10 modified

## Accomplishments

- **CR-01 / gap 02-4 closed.**
  - `load_scenario` hashes the raw file bytes into `Scenario.sha256`.
  - `build_report` writes `scenario_source`, `scenario_sha256`, `duration_s` and `scenario_duration_s` (schema stays 1).
  - The freeze-check helper adds `head_scenario()` (git show of race-36h.json at HEAD) and `run_state()`, which give the states `not-scenario` and `short`. Both FAIL before any PASS branch.
  - An unreadable race-36h.json at HEAD is an error (fail closed).
- **WR-01 closed.** The fingerprint-only PASS now requires `machine = aarch64`. An x86_64 report with git.head null FAILs « git.head inconnu ».
- **WR-02 / IN-01 closed.**
  - `systemd.SignalHold` (start/release, context manager). `_deferred_signals` is rebuilt on it.
  - `Harness.end_signals` starts after the main run.
  - `run_soak` releases the hold after `write_report` and `_give_back`, then returns 128 + the held signal (falling back to `sup.pending_signal`).
  - The stale "second Ctrl-C" wording is gone.
- **Shortened runs** print `jabuka-soak: WARNING: shortened run …` at start. report.md says **Essai raccourci**.
- **Docs.**
  - SOAK.md covers: the --duration paragraph, the report.json keys, the cleanup bullet (« fin du soak »), the Pi step 1 full-length note, and the step 8 `kill -9` escape.
  - FREEZE.md covers: steps 1–2 « complet (sans `--duration`) », the F3 git.head rule, and the F3/F4 full-length rule.

## Evidence

**Fixture lines from the new freeze-check cases:**
```
shortened Pi:     [FAIL] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json essai raccourci (duration_s 600.0 / 129600, sim_s 600.0, 1 panne(s) après la fin) : F3/F4 ne comptent que le soak race-36h complet : le refaire sans --duration (docs/SOAK.md) ; lancer les essais rapides avec --out var/soak-essais pour ne pas masquer le vrai soak
foreign scenario: [FAIL] F3 portable : var/soak/20261110T060000Z-race-36h-laptop/report.json ne prouve pas le scénario race-36h de HEAD (scenario_sha256 000000000000 / race-36h.json à HEAD 8f17312324e8) : refaire le soak avec le banc actuel et --scenario race-36h (scénario packagé, sans fichier perso ni --seed) (docs/SOAK.md)
newest quick run: [FAIL] F4 Pi : var/soak/20261111T000000Z-race-36h-quick/report.json essai raccourci (duration_s 900.0 / 129600, sim_s 900.0, 0 panne(s) après la fin) : … --out var/soak-essais …
F3 head-null:     [FAIL] F3 portable : var/soak/20261110T060000Z-race-36h-laptop/report.json git.head inconnu (rapport sans git) : F3 exige la règle git, l'empreinte seule ne suffit pas : refaire bash scripts/soak.sh --scenario race-36h depuis le checkout
```

**Real shortened run (`--scenario race-36h --duration 900 --out var/soak-04-07`, verdict PASS), judged on a clone of HEAD (var/soak-04-07/freeze.txt):**
```
[FAIL] F3 portable : var/soak/20261108T183445Z-race-36h/report.json essai raccourci (duration_s 900.0 / 129600, sim_s 1329.6, 93 panne(s) après la fin) : F3/F4 ne comptent que le soak race-36h complet : le refaire sans --duration (docs/SOAK.md) ; lancer les essais rapides avec --out var/soak-essais pour ne pas masquer le vrai soak
```
report.json: duration_s 900.0, scenario_duration_s 129600.0, scenario_source scenarios/race-36h.json, scenario_sha256 dca4d6aecc19e0aa10f0e9ad42a521f3a88e8be419bbd63cabaf97370c60a172. Before this plan, the same run gave `[PASS] F3`.

**`bash scripts/freeze-check.sh -h`** prints the F1–F9 header, now with:
- an F3 paragraph that ends "the fingerprint alone never suffices for F3 (git.head inconnu)";
- a new "F3+F4 only a full-length run of the race-36h scenario at HEAD counts: scenario_sha256 = …, duration_s >= …, sim_s >= 0.99 x …, no fault skipped "after the end of the run" … quick runs go to --out var/soak-essais";
- the reads list extended with seed, sim_s, duration_s, scenario_sha256 and skipped[].reason.

No line starts with `set `.

**freeze-check on this repo (`--pre --skip-gate`, exit 1, expected FAILs):**
```
[PASS] F1 arbre de travail propre (fichiers suivis)
[SKIP] F2 porte non lancée (--skip-gate) : …
[FAIL] F3 portable : var/soak/20261107T133350Z-race-36h/report.json ne prouve pas le scénario race-36h de HEAD (scenario_sha256 absent / race-36h.json à HEAD dca4d6aecc19) : refaire le soak …
[FAIL] F4 pas de rapport race-36h Pi (aarch64) dans var/soak : bash scripts/soak.sh (docs/SOAK.md)
[FAIL] F5 verrou non revu ou modifié : docs/FREEZE.md dit « À REMPLIR » …
[FAIL] F6 roue jabuka différente de src/ : … -> bash scripts/build-wheelhouse.sh depuis le tag
[SKIP] F7 tag race-2026 pas encore attendu (--pre)
[WARN] F8 18 éléments UAT en attente …
[HUMAN] F9 carte SD de secours …
```

**Soaks:**
- tracer `--out var/soak`: verdict PASS (exit 0).
- tracer `--duration 600 --out var/soak-04-07`: verdict PASS. stderr has `jabuka-soak: WARNING: shortened run (--duration 600 < scenario 1200 sim s): faults after the end are SKIPPED and freeze-check F3/F4 will not count this report (essai raccourci); run quick tests with --out var/soak-essais (docs/SOAK.md)`, and report.md has `- **Essai raccourci** : 600 s simulées demandées sur 1200 s du scénario ; …`.
- `bash scripts/soak.sh --scenario ci`: verdict PASS (exit 0).

**Gate** (var/gate-04-07.log): `1620 passed, 4 skipped` on Python 3.14 and on 3.13, ruff clean. The log ends with `check: ok` / `EXIT=0`.

**New src/jabuka fingerprint** (FINGERPRINT_SH at ee8d5e2, 146 files): `f7ddf18106457b465fc2e42efa18184a5fae2a1c89dd67d8990b5f4f4a5b0b4f`. The wheelhouse rebuilt for the Pi must reproduce it.

## Task Commits

1. Task 1 (tracer): RED `d79c1da`, GREEN `a2ba600`. The tracer was then verified end to end with the real `--duration 900` run.
2. Task 2: RED `554c457`, GREEN `0c44c59`.
3. Task 3: RED `896d868`, GREEN `ee8d5e2`.

## Requirements

`requirements-completed: []`. This plan addresses REL-02 and REL-03 but does not complete them. REQUIREMENTS.md is untouched, and REL-02 stays not-Complete until the real Pi soak PASSes and the phase is re-verified.

## Deviations from Plan

**1. [Rule 1 - Bug] Kept the report.json table row on a single line in docs/SOAK.md**
- Found during: Task 3, reviewing the doc diff.
- Issue: the first edit wrapped the new key list across lines inside a Markdown table row, which breaks the table.
- Fix: the row was rejoined onto one line before the commit (ee8d5e2).

**2. [Process] Order of the Task 1 end-to-end proof**
- The proof ran after the GREEN commit, so the shallow clone of HEAD carries the new code. This makes no difference to the result.

**3. [Process] RED evidence**
- `gsd check tdd-red-evidence` parses TAP (node) output only, so it was not usable with pytest.
- RED was checked by hand instead. Each target test failed on its behavioural assertion: freeze-check printed PASS where FAIL was expected, or SystemExit 129 came from an unheld SIGHUP. Tests for an API that did not exist yet failed with AttributeError (`SignalHold`, `end_signals`, `run_length_messages`, `SKIP_AFTER_END`, `Scenario.sha256`).

**4. [Detail] freeze-check helper normalises whitespace in the record detail field**
- The helper now collapses all whitespace in the record's detail field, so tabs or newlines cannot break the tab-separated record. Every bash message is unchanged.

**Total deviations:** 1 auto-fixed (Rule 1), 3 process notes. **Impact:** none on scope.

## Issues Encountered

None. The known `test_user_scope_tracer_end_to_end` flake did not occur. The CI soak ran after the gate so the two would not compete for CPU.

## Human Items (after merge)

- Rebuild the wheelhouse from the merged HEAD (it must give fingerprint f7ddf1810645…) and re-provision the Pi. Then run the full Pi soak in tmux with no `--duration` (2026-11-10). F4 must PASS.
- Re-run the laptop `bash scripts/soak.sh --scenario race-36h` in full on the final pre-freeze HEAD. Quick runs go to `--out var/soak-essais`. F3 must PASS.
- Mark REL-02 Complete only after the Pi soak PASSes and the phase is re-verified.

## Next Phase Readiness

All seven plans of phase 04 now have summaries. Next: re-verify phase 04 (`/gsd-verify-work 04`).

## Self-Check: PASSED

- Commits d79c1da, a2ba600, 554c457, 0c44c59, 896d868 and ee8d5e2 exist (`git log c02c43a..HEAD`).
- All 10 modified files are present. var/soak-04-07/freeze.txt and var/gate-04-07.log exist.
- No race-36h run dir was created under var/soak/ by this plan.
