---
phase: 04-race-readiness-hardening-commissioning
plan: 06
subsystem: soak / freeze gate
tags: [freeze-check, soak, systemd, signals, tmux, docs]
status: complete
gap_closure: true

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: "04-04 code identity (code block, fingerprint), 04-03 systemd soak backend, 04-02 freeze-check"
provides:
  - "freeze-check F4 counts only a --systemd system Pi report (mode systemd, code.source units) with a code block matching HEAD"
  - "System-scope soak cleanup verifies both production units are active after the restart (retryable, verdict FAIL, --systemd-cleanup exit 1)"
  - "Signals during cleanup recorded in SystemdBackend.pending_signal; run_soak writes the report, then returns 128 + signal"
  - "aarch64 WARNING at start for shim / --systemd user runs"
  - "docs/SOAK.md (tmux, F4 rule, cleanup outcome) and docs/FREEZE.md (F4 rule) bound by tests"
affects: [freeze 2026-11-11, Pi soak 2026-11-10, docs/SOAK.md, docs/FREEZE.md]

plan_head_before: cef36083eeea5dd7ebeffa9dce31256febb2ab3e
actuals:
  tokens: 7400
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "freeze-check helper: machine-specific state mapping (aarch64 no-code / not-units) ahead of PASS branches"
    - "verify-after-restart: ActiveState poll with a monotonic deadline; cleaned only when verified"
    - "deferred signal recorded, honoured by the caller after its durable write"

key-files:
  created: []
  modified:
    - scripts/freeze-check.sh
    - tests/commissioning/test_freeze_check.py
    - src/jabuka/soak/systemd.py
    - src/jabuka/tools/soak.py
    - tests/soak/test_soak_systemd.py
    - tests/soak/test_soak_identity.py
    - docs/SOAK.md
    - docs/FREEZE.md

key-decisions:
  - "F4 not-units overrides differ/units-*/match: a run that never exercised the installed units is irrelevant to F4 whatever its fingerprint"
  - "F3 unchanged: a laptop report without a code block is still judged by the git rule (laptop always has .git)"
  - "cleanup() marks done only for user scope or restarted True (rc 0 AND both units ActiveState active); otherwise atexit / --systemd-cleanup redo it"
  - "A signal during cleanup is never re-raised inside cleanup(); run_soak returns 128 + signal after write_report"

requirements-completed: [REL-02, REL-03]

coverage:
  - id: D1
    description: "freeze-check F4 FAILs shim, --systemd user, children-with-wrong-units, units-with-wrong-mode, code-less and malformed-sha aarch64 reports; still PASSes the documented git-less system-scope report; F3 unchanged"
    requirement: REL-02
    verification:
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_pi_shim_report_is_not_a_system_soak"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_pi_user_scope_report_is_not_a_system_soak"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_pi_children_report_with_wrong_units_is_not_a_system_soak"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_pi_units_report_with_a_wrong_mode_is_not_a_system_soak"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_pi_report_with_git_but_without_code_fails"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_pi_report_with_a_malformed_sha_fails"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_non_git_pi_copy_accepted_when_the_installed_code_matches"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f3_laptop_report_without_code_keeps_the_git_rule"
        status: pass
    human_judgment: false
  - id: D2
    description: "WR-01: failed or unverified restart keeps the system cleanup retryable, FAILs the verdict, --systemd-cleanup exits 1; systemctl in its own session"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_failed_restart_keeps_the_system_cleanup_retryable"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_restart_rc_failure_is_not_a_restart"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_cleanup_fail_reasons"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_systemd_cleanup_cli_exits_1_when_the_units_stay_down"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_systemctl_children_get_their_own_session"
        status: pass
    human_judgment: false
  - id: D3
    description: "WR-02: signal during cleanup recorded; report.json written before exit 128 + signal; aarch64 WARNING for non system-scope runs"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_signal_during_system_cleanup_is_deferred_until_the_units_restart"
        status: pass
      - kind: integration
        ref: "tests/soak/test_soak_systemd.py#test_run_soak_writes_the_report_before_honouring_a_deferred_signal"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_identity_messages_warn_when_a_pi_run_is_not_system_scope"
        status: pass
    human_judgment: false
  - id: D4
    description: "docs/SOAK.md (tmux, F4 rule, step 8 code 1, cleanup outcome) and docs/FREEZE.md (step 2, per-item F3/F4 rule) bound by tests"
    requirement: REL-03
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_docs_describe_the_f4_system_scope_rule_and_tmux"
        status: pass
      - kind: unit
        ref: "tests/commissioning/test_runbook_docs.py#test_freeze_doc"
        status: pass
    human_judgment: false
  - id: D5
    description: "The real Pi soak inside tmux on the re-provisioned Pi gives F4 PASS ('paquet installé = src/jabuka à HEAD')"
    requirement: REL-02
    verification: []
    human_judgment: true
    rationale: "Needs the physical Pi 3B, a wheelhouse rebuilt from the merged HEAD and a 2-4 h run (owner, 2026-11-10)"

duration: 32min
completed: 2026-11-08
---

# Phase 04 Plan 06: F4 system-scope rule and soak cleanup hardening Summary

**freeze-check F4 n'accepte plus que le rapport `--systemd system` du Pi (mode systemd, code.source units, empreinte et unités = HEAD) ; le nettoyage du soak vérifie que jabuka-core et jabuka-ingest-fastnet sont actives après la relance, et un signal reçu pendant le nettoyage ne fait plus perdre report.json. Le soak du Pi se lance dans tmux.**

## Performance

- **Duration:** ~32 min (dont ~21 min de porte complète)
- **Started:** 2026-11-08T17:00:34Z
- **Completed:** 2026-11-08T17:32:07Z
- **Tasks:** 3 (6 commits TDD : 3 RED + 3 GREEN)
- **Files modified:** 8

## Accomplishments

- **CR-01 / gap 02-4 fermé.** The helper maps an aarch64 report with no valid `code.sha256` to `no-code`. A report whose mode is not `systemd` or whose `code.source` is not `units` becomes `not-units`. Both FAIL right after the verdict branch, before any PASS branch. F3 is unchanged.
- **WR-01 fermé.** `_await_active` polls `ActiveState` for up to `RESTART_VERIFY_S` (20 s). `restarted` is now true only when rc is 0 and both units are active, and the report gains `restart_rc` and `active`. When `restarted` is false, the cleanup is not marked done, so atexit or `--systemd-cleanup` runs it again; `cleanup_fail_reasons` FAILs the verdict; `CleanupIncomplete` makes `--systemd-cleanup` exit 1. systemctl now runs with `start_new_session=True`.
- **WR-02 fermé.** A signal received during cleanup goes into `pending_signal` and is never re-raised inside `cleanup()`. `run_soak` writes the report first, then returns 128 + signal. The prints after the report are protected against a dead pipe.
- A shim or `--systemd user` run on aarch64 prints a `WARNING` at start that quotes the `--systemd system` command.
- docs/SOAK.md and docs/FREEZE.md are updated (tmux, the F4 rule, cleanup outcome, `--systemd-cleanup` code 1), and a test binds them.
- IN-06: `test_systemd_cleanup_alone_removes_stale_dropins` no longer touches the real `/proc/mounts` or umount.

## Task Commits

1. **Task 1 (tracer): F4 counts only a `--systemd system` Pi report**
   - `df439c1` test(04-06) RED
   - `b4c45ea` feat(04-06) GREEN
2. **Task 2: verified restart, deferred signal, aarch64 WARNING**
   - `4cb43af` test(04-06) RED
   - `45d1faa` feat(04-06) GREEN
3. **Task 3: docs SOAK/FREEZE (tmux, F4 rule)**
   - `8df5d63` test(04-06) RED
   - `256a762` docs(04-06) GREEN

The RED evidence was verified for each task with `gsd-tools check tdd-red-evidence` (`RED_EVIDENCE_OK`). The target tests were `test_f4_pi_shim_report_is_not_a_system_soak`, `test_systemctl_children_get_their_own_session` and `test_docs_describe_the_f4_system_scope_rule_and_tmux`.

## Evidence

**F4 lines printed by the new freeze-check cases** (temporary repo):

```
shim:   [FAIL] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json n'est pas un soak --systemd system (mode shim, source children) : F4 ne compte que le soak des unités installées : sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M (docs/SOAK.md)
user:   [FAIL] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json n'est pas un soak --systemd system (mode systemd, source children) : F4 ne compte que le soak des unités installées : sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M (docs/SOAK.md)
nocode: [FAIL] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json sans empreinte du code (pas de code.sha256) : refaire le soak du Pi avec le banc actuel : sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M (docs/SOAK.md)
system: [PASS] F4 Pi : var/soak/20261110T070000Z-race-36h-pi/report.json PASS, paquet installé = src/jabuka à HEAD (empreinte 580dda975ae1, 3 fichiers)
```

**`bash scripts/freeze-check.sh -h` header (F3/F4 part):**

```
  F3  laptop race-36h soak report (host.machine x86_64): verdict PASS, git.dirty false, and no
      change under src/, deploy/ (except *.md) or pyproject.toml between git.head and HEAD.
      A report with a `code` block (empreinte du paquet exécuté, docs/SOAK.md) must also have
      code.sha256 = the fingerprint of src/jabuka at HEAD and, for the Pi (source "units"),
      code.units = deploy/systemd at HEAD; then git.head may be null (Pi copy without .git)
  F4  Pi race-36h soak report (aarch64; copy the Pi's var/soak/<run>/ back into var/soak/). It
      must come from `sudo bash scripts/soak.sh --systemd system …` (mode systemd, code.source
      units) and carry the code block: code.sha256 = the fingerprint of src/jabuka at HEAD and
      code.units = deploy/systemd at HEAD; git.head may then be null (Pi copy without .git).
      When git.head is present the F3 git rules apply on top; git alone never suffices for F4
```

The full header runs from F1 to F9 plus the "Reads soak reports" sentence, which now lists `mode`. `-h` prints no `set ` line; the range is now `2,27p`.

**freeze-check on this repo** (`--pre --skip-gate`, exit 1, which is expected):

```
[FAIL] F1 fichiers modifiés : .planning/STATE.md   (orchestrator edit, not this plan)
[SKIP] F2 porte non lancée (--skip-gate)
[FAIL] F3 portable : code modifié depuis le soak (0fff60c12c24 -> HEAD : …) : refaire bash scripts/soak.sh
[FAIL] F4 pas de rapport race-36h Pi (aarch64) dans var/soak
[FAIL] F5 verrou non revu (À REMPLIR)
[FAIL] F6 roue jabuka différente de src/ -> bash scripts/build-wheelhouse.sh depuis le tag
[SKIP] F7 tag race-2026 pas encore attendu (--pre)
[WARN] F8 18 éléments UAT en attente
[HUMAN] F9 carte SD de secours
```

**Soaks:**
- tracer (`.venv313 -m jabuka.tools.soak --scenario tracer`): verdict PASS, exit 0.
- `bash scripts/soak.sh --scenario ci`: verdict PASS, exit 0.
- `--systemd system --scenario race-36h` without `--logs-fs` still exits 2 with the `loop:` hint.

**Full gate** (`JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh`, `var/gate-04-06.log`):

```
All checks passed!
1603 passed, 4 skipped in 625.37s (0:10:25)
1603 passed, 4 skipped in 624.32s (0:10:24)
check: ok
EXIT=0
```

**Fingerprint of src/jabuka at the final code commit `256a762`** (146 files; `git archive HEAD` and the working tree give the same value). The wheelhouse rebuilt for the Pi must reproduce it:

```
d42dac399a00d9de6f807f6454122bf775aa08011ea5e941ac337797b783b9df
```

## Files Created/Modified

- `scripts/freeze-check.sh`: `no-code` and `not-units` states (aarch64 only), the two FAIL lines, the F4 header and `-h 2,27p`.
- `tests/commissioning/test_freeze_check.py`: the Frozen fixture's Pi report is now a system-scope report with a code block; 7 new cases.
- `src/jabuka/soak/systemd.py`: `RESTART_VERIFY_S`, `CleanupIncomplete`, `pending_signal`, `_await_active`, `start_new_session`, `restart_rc`/`active`, and `cleanup_system` raising.
- `src/jabuka/tools/soak.py`: `cleanup_fail_reasons`, `PI_F4_COMMAND`, `identity_messages(machine=)`, `run_soak` returning 128 + signal after the report, and `--systemd-cleanup` exiting 1.
- `tests/soak/test_soak_systemd.py`: `FAKE_ACTIVE`; 6 new tests; the signal test updated; IN-06.
- `tests/soak/test_soak_identity.py`: the aarch64 WARNING test and the doc test.
- `docs/SOAK.md`: tmux at step 2, the F4 rule at step 1, code 1 at step 8, and the cleanup bullet.
- `docs/FREEZE.md`: step 2 (exact command, tmux, F4 rule) and the per-item rule under "Empreinte du code".

## Decisions Made

- **F3 unchanged.** A laptop report without a code block is still judged by the git rule. `test_f3_laptop_report_without_code_keeps_the_git_rule` documents this.
- **`not-units` takes precedence** over `differ`, `units-*` and `match`. `error` is kept as is, and `no-code` comes first.
- **`identity_messages` delegates to `_identity_lines`.** When `machine` is omitted, the output is unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ruff E501 on the FAKE line edited in the RED commit**
- **Found during:** Task 2 (GREEN)
- **Issue:** The `ActiveState` line of the fake systemctl went over 100 columns.
- **Fix:** Wrapped the line (pure formatting, no behaviour change). It is part of the GREEN commit `45d1faa`.
- **Files modified:** tests/soak/test_soak_systemd.py

**2. [Process] Commits on `main`**
- The orchestrator asked for a sequential executor on `main` without switching branches. `git.base-branch --is-protected main` returns true, but the project commits directly to `main` (branching_strategy none, plans 04-01..05). The commits were staged by explicit path only. Nothing under cad/, stl/ or hardware/ was touched, and `.planning/STATE.md` was not modified by the code commits.

---

**Total deviations:** 1 auto-fixed (formatting) + 1 process note. **Impact:** none on scope.

## TDD Gate Compliance

RED → GREEN for all 3 tasks: `test(04-06)` comes before `feat(04-06)` / `docs(04-06)`. No REFACTOR was needed. Task 3's GREEN commit is `docs(...)` because the change is documentation only.

## Issues Encountered

None. The `test_user_scope_tracer_end_to_end` flake noted in 04-04 did not appear.

## User Setup Required

These human items come after the merge:
- Install tmux on the Pi while it still has internet: `sudo apt install -y tmux`.
- Rebuild the wheelhouse from HEAD (`bash scripts/build-wheelhouse.sh`). It must reproduce the fingerprint `d42dac399a00…`.
- Re-provision the Pi.
- Run the Pi soak inside tmux on 2026-11-10: `sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`.
- Re-run the laptop race-36h soak (F3) on the final HEAD before the freeze.

## Next Phase Readiness

The freeze gate now counts only the documented Pi soak. The Pi soak can no longer hide a failed restart, and it can no longer lose its report to a late signal. Phase 04 is ready for re-verification.

## Self-Check: PASSED

- The 8 modified files exist.
- Commits df439c1, b4c45ea, 4cb43af, 45d1faa, 8df5d63 and 256a762 are present in `git log`.
- The acceptance criteria for tasks 1–3 were re-run and all PASS:
  - grep counts 4, 1, 3, 3, 1, 1, 2, 1;
  - the diff contains no `-assert` line;
  - the import check passes.
