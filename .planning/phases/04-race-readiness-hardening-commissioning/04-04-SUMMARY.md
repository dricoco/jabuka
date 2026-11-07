---
phase: 04-race-readiness-hardening-commissioning
plan: 04
subsystem: testing
tags: [soak, freeze-check, sha256, systemd, fingerprint, gap-closure]

requires:
  - phase: 04-race-readiness-hardening-commissioning
    provides: "jabuka-soak harness (04-01), freeze-check.sh F1-F9 (04-02), --systemd system backend (04-03)"
provides:
  - "report.json `code` block: sha256 fingerprint of the jabuka package that actually ran (FINGERPRINT_SH), file count, package dir, source units|children, installed unit hashes in system scope"
  - "freeze-check F3/F4 code rule: a git-less Pi report passes only when code.sha256 = git archive HEAD src/jabuka and code.units = deploy/systemd at HEAD"
  - "Run-start identity gate: system scope refuses (exit 2) without a fingerprint; shim/user print a WARNING block when neither code nor git exists"
  - "System scope refuses a tmpfs log fs (exit 2, before the root check); root harness oom_score_adj -900"
  - "SystemdBackend.cleanup: restart before unmount, marked done only at the end, retried after interruption, SIGINT/SIGTERM/SIGHUP deferred"
  - "Docs SOAK/FREEZE/SPARE-SD quote FINGERPRINT_SH verbatim (test-bound); PI-SETUP §3 explains the copy without .git"
affects: [freeze 2026-11-11, Pi soak 2026-11-10, spare SD clone]

actuals:
  tokens: 17800
  tasks: 3
  commits: 6
plan_head_before: cf03fe84205a1880a3aa7a32fd69e92b36ec0142

tech-stack:
  added: []
  patterns:
    - "One shell pipeline (FINGERPRINT_SH) is the fingerprint definition; Python and the freeze-check helper re-implement it and are parity-tested"
    - "System scope locates the package statically from the installed ExecStart binary (venv glob), never executes an interpreter as root"
    - "Cleanup idempotent only on completion, signals deferred through a main-thread context manager"

key-files:
  created:
    - tests/soak/test_soak_identity.py
  modified:
    - src/jabuka/soak/report.py
    - src/jabuka/tools/soak.py
    - src/jabuka/soak/systemd.py
    - scripts/freeze-check.sh
    - tests/commissioning/test_freeze_check.py
    - tests/soak/test_soak_systemd.py
    - docs/SOAK.md
    - docs/FREEZE.md
    - docs/SPARE-SD.md
    - deploy/PI-SETUP.md

key-decisions:
  - "Gap fix option (b): the report fingerprints the installed package; PI-SETUP §3 keeps rsync --exclude '.git'"
  - "freeze-check keeps the git rules byte-for-byte; the code rule is added on top and PASSes alone only when git.head is null and the code (and units for source units) equal HEAD"
  - "A freeze-check helper crash becomes an error record (|| fallback), so F3/F4 FAIL with a reason instead of aborting under set -e"
  - "report.json also carries code_error (additive) so report.md can say why no fingerprint was recorded"
  - "cleanup_report.restarted is the restart's return-code result (true on rc 0), removed drop-ins accumulate across retried cleanups"

patterns-established:
  - "Fingerprint parity tests: Python vs shell pipeline vs git archive vs docs"
  - "Fake-systemctl tests never call the real umount (sd.unmount monkeypatched, review IN-06)"

requirements-completed: [REL-02, REL-03]

coverage:
  - id: D1
    description: "Soak report records the code identity of the package that ran (system scope: the installed units' venv + unit file hashes)"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_fingerprint_matches_the_shell_pipeline"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_compute_code_identity_system_scope_uses_the_units_venv"
        status: pass
      - kind: integration
        ref: ".venv313/bin/python -m jabuka.tools.soak --scenario tracer --out var/soak (code.sha256 == FINGERPRINT_SH in src/jabuka)"
        status: pass
    human_judgment: false
  - id: D2
    description: "freeze-check F4 accepts a non-git Pi report only when the installed package and units equal HEAD; rejects byte change, stale venv (WR-03), unit drift"
    requirement: REL-02
    verification:
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_non_git_pi_copy_accepted_when_the_installed_code_matches"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_non_git_checkout_at_head_with_a_stale_venv_is_rejected"
        status: pass
      - kind: integration
        ref: "tests/commissioning/test_freeze_check.py#test_f4_non_git_pi_copy_rejected_when_a_unit_differs"
        status: pass
    human_judgment: false
  - id: D3
    description: "Harness refuses system-scope runs without a code identity or with a tmpfs log fs (WR-02); root harness oom_score_adj -900"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_run_soak_refuses_system_scope_without_a_code_identity"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_cli_system_scope_refuses_tmpfs_before_the_root_check"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_protect_from_oom"
        status: pass
    human_judgment: false
  - id: D4
    description: "System-scope cleanup restarts before unmounting, is retried after interruption, defers SIGHUP (WR-01)"
    requirement: REL-02
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_system_cleanup_restarts_the_units_before_unmounting"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_interrupted_system_cleanup_is_retried"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_systemd.py#test_signal_during_system_cleanup_is_deferred_until_the_units_restart"
        status: pass
    human_judgment: false
  - id: D5
    description: "SOAK/FREEZE/SPARE-SD/PI-SETUP describe the fingerprint rule and quote FINGERPRINT_SH verbatim"
    requirement: REL-03
    verification:
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_docs_quote_the_fingerprint_command"
        status: pass
      - kind: unit
        ref: "tests/soak/test_soak_identity.py#test_pi_soak_procedure_describes_the_code_identity"
        status: pass
    human_judgment: false
  - id: D6
    description: "Real Pi soak under the documented install produces a report that F4 PASSes"
    requirement: REL-02
    verification: []
    human_judgment: true
    rationale: "Needs the Pi 3B with /opt/jabuka/venv re-provisioned from a wheelhouse built after this plan (owner, 2026-11-10)"

duration: 60min
completed: 2026-11-08
status: complete
---

# Phase 4 Plan 04: Soak code identity and safe Pi soak Summary

**The soak report now carries a sha256 fingerprint of the jabuka package that actually ran (plus the installed unit hashes on the Pi). freeze-check F3/F4 accept a git-less Pi report only when that identity equals src/jabuka and deploy/systemd at HEAD. The Pi harness refuses unidentifiable or RAM-logged runs, and its cleanup can no longer leave the production units stopped.**

## Performance

- **Duration:** about 60 min (including about 35 min of soak and gate runs)
- **Started:** 2026-11-07T22:10Z
- **Completed:** 2026-11-07T23:10Z
- **Tasks:** 3 (all TDD: RED commit then GREEN commit)
- **Files modified:** 11 (1 created)

## Accomplishments

- **One fingerprint definition.** `jabuka.soak.report.FINGERPRINT_SH` is:
  `find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum`.
  Tests prove that `package_fingerprint` (Python) and the freeze-check helper (on `git archive HEAD src/jabuka`) give the same hex, and that the three French docs quote the pipeline verbatim.
- **Every report has a `code` block.**
  - System scope: the fingerprint is taken from the installed units' own venv, found statically from their ExecStart binary. The block also holds the sha256 of each installed unit file (via `FragmentPath`).
  - Shim and user scope: the fingerprint is taken from the package the children's interpreter imports (`python -I`).
  - `report.md` has a "- Code :" line.
- **freeze-check F3/F4 code rule.** F3/F4 now:
  - PASS a git-less Pi report when its code matches HEAD;
  - FAIL on a fingerprint difference, a unit drift or a missing unit;
  - keep every existing git rule when git.head exists (WR-03: a checkout at HEAD with a stale venv FAILs);
  - still FAIL a git-less report that has no code block.
  If the helper crashes, F3/F4 print a FAIL line instead of aborting the script.
- **Run-start gate.** The harness prints `jabuka-soak: code <12 hex> …; git …` when a run starts.
  - System scope without a fingerprint: exit 2, before any unit is touched (only `systemctl cat`/`show` run), and the run dir is removed.
  - Other modes with neither a fingerprint nor a git head: a WARNING block that names F3/F4.
- **WR-02.**
  - `--systemd system` refuses a tmpfs log fs with exit 2 and a `loop:SIZE` hint. This covers an explicit tmpfs, the race-36h default (tmpfs:256M) and `auto` with disk-full. The check runs before the root check.
  - `mount_logs_tmpfs` refuses tmpfs as well (defense in depth).
  - The root harness sets its `oom_score_adj` to -900, reported as `systemd.harness_oom_score_adj`.
- **WR-01.** Cleanup order is now: drop-ins removed → daemon-reload → restart → unmount.
  - It is marked done only at the end, so the next call (atexit or `--systemd-cleanup`) redoes an interrupted cleanup.
  - SIGINT, SIGTERM and SIGHUP are deferred and re-raised once the units are back.

## Results requested by the plan

- **Fingerprint of src/jabuka at the final commit (77810da):** `9424f6af7c38ad0a544ac3343c4730325f168504d8c478b1d5a6ec5055676360` (146 files). I checked it three ways:
  - `git archive HEAD src/jabuka` → `fingerprint_entries`;
  - the CI soak report;
  - the tracer report.
- **Tracer report:**
  - `var/soak/20261107T230745Z-tracer/report.json` (worktree var/, re-run on the final source): `code.sha256` = `9424f6af7c38…6360`, `source` = `children`, verdict PASS; report.md has "- Code : empreinte 9424f6af7c38 (146 fichiers, …, source children)".
  - The Task 1 tracer, `var/soak/20261107T222350Z-tracer` on commit 1cf2c67, gave `533714e06293…`, which equalled FINGERPRINT_SH on the source at that time.
- **freeze-check on this repo** (`bash scripts/freeze-check.sh --pre --skip-gate`, exit 1, 9 lines):
  ```
  [PASS] F1 arbre de travail propre (fichiers suivis)
  [SKIP] F2 porte non lancée (--skip-gate) : JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh
  [FAIL] F3 pas de rapport race-36h portable (x86_64) dans var/soak : bash scripts/soak.sh (docs/SOAK.md)
  [FAIL] F4 pas de rapport race-36h Pi (aarch64) dans var/soak : bash scripts/soak.sh (docs/SOAK.md)
  [FAIL] F5 verrou non revu ou modifié : docs/FREEZE.md dit « À REMPLIR », sha256 du verrou d7236cb6…7d80 (…)
  [FAIL] F6 deploy/wheelhouse absent : bash scripts/build-wheelhouse.sh
  [SKIP] F7 tag race-2026 pas encore attendu (--pre)
  [WARN] F8 18 éléments UAT en attente (result: [pending]) : à traiter à bord, docs/COMMISSIONING.md annexe B
  [HUMAN] F9 carte SD de secours clonée depuis la version gelée et démarrée : docs/SPARE-SD.md
  ```
  These FAILs are expected today. This worktree's var/soak has no race-36h report, the lock hash has not been written, and there is no wheelhouse.
- **CI soak:** `bash scripts/soak.sh --scenario ci` gave verdict PASS (exit 0), 19 faults and nothing skipped (`var/soak/20261107T223046Z-ci`). Its `code.sha256` is `9424f6af7c38…`.
- **Gate:** `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh` passed: ruff clean; 1565 passed and 6 skipped on Python 3.14 and the same on 3.13; `check: ok`, exit 0 (log `var/gate-04-04-run2.log`). The first attempt failed on a flaky test; see Issues Encountered.

## Task Commits

1. **Task 1 (tracer): code identity + F3/F4 fingerprint rule**: `1cf2c67` (test, RED), `3c16d4d` (feat, GREEN)
2. **Task 2: run-start gate, tmpfs refusal, OOM protection, safe cleanup**: `f23072b` (test, RED), `e0953a0` (feat, GREEN)
3. **Task 3: docs bound to the fingerprint**: `f3f4ef5` (test, RED), `77810da` (docs, GREEN)

**Plan metadata:** the SUMMARY commit that follows these.

## TDD Gate Compliance

Every task has a `test(04-04)` commit before its implementation commit. Each RED run failed on the target tests only, and for the planned reason:
- Task 1: 20 failures, the missing report API (for example `AttributeError: … package_fingerprint`).
- Task 2: 10 failures:
  - the cleanup order was `['daemon-reload', 'umount', 'restart']`;
  - `cleaned` was True after the interruption;
  - the sudo hint appeared instead of the `loop:` hint;
  - `identity_messages` was missing.
- Task 3: 2 failures, because FINGERPRINT_SH was absent from SPARE-SD.md and `code.sha256` was absent from SOAK.md.

I did not record the plan-level `tdd-red-evidence` file because this plan is `type: execute`, not `tdd`.

## Files Created/Modified

- `src/jabuka/soak/report.py`: FINGERPRINT_ALGO/FINGERPRINT_SH, fingerprint_entries, package_fingerprint, locate_package, venv_package, code_identity, CodeIdentityError, the report.md Code line, and the docstring keys.
- `src/jabuka/tools/soak.py`: Harness.compute_code_identity, _unit_file_sha256, the code/code_error/git/oom_adj fields, identity_messages, system_logs_fs_error, the run_soak refusal, the reordered main() checks, the tmpfs refusal in mount_logs_tmpfs, and protect_from_oom in prepare_system.
- `src/jabuka/soak/systemd.py`: DEFERRED_SIGNALS, `_deferred_signals`, cleanup split into `_cleanup_user`/`_cleanup_system` in the new order, `protect_from_oom`, and the docstring.
- `scripts/freeze-check.sh`: the code-state helper (git archive fingerprint and unit hashes), the code rule ahead of the unchanged git chain, the `|| printf` error record, and the header and `-h` range.
- `tests/soak/test_soak_identity.py` (new): parity, locate/venv, compute_code_identity, identity_messages, the run_soak refusal, and the doc binding.
- `tests/commissioning/test_freeze_check.py`: the Frozen fixture gains the unit files, pi_copy/unit_hashes/pi_report, and 7 new cases (`*non_git*`, WR-03, unit drift, git rules kept, malformed block).
- `tests/soak/test_soak_systemd.py`: cleanup order, interrupted retry, deferred SIGHUP, protect_from_oom, and the tmpfs refusal (function and CLI).
- `docs/SOAK.md`, `docs/FREEZE.md`, `docs/SPARE-SD.md`, `deploy/PI-SETUP.md`: the new rule, described per the plan.

## Decisions Made

- I kept the `- Code :` line wording and the freeze-check messages exactly as the plan's interfaces specify ("paquet installé = src/jabuka à HEAD", "code soaké (empreinte …) différent de src/jabuka à HEAD (…)", "unités installées différentes de deploy/systemd à HEAD").
- In system scope, compute_code_identity also catches ValueError and SetupError from `_installed_argv`, so it never raises. Run_soak then refuses with the reason.
- The fingerprint skips `.pyc` files and files under a `__pycache__` directory, which is exactly `find`'s `-path '*/__pycache__/*'`. A regular file literally named `__pycache__` would be kept, as find keeps it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `freeze-check.sh -h` printed `set -euo pipefail`**
- **Found during:** Task 1.
- **Issue:** The old range `sed -n '2,21p'` already included the `set` line. The acceptance criterion requires that no line starts with "set ".
- **Fix:** The range is now `2,23p`, which matches the new 22-line header.
- **Commit:** `3c16d4d`.

**2. [Rule 2 - Missing critical] Additive `code_error` report key**
- **Found during:** Task 1.
- **Issue:** The plan's report.md line "aucune empreinte (<reason>)" needs the reason, but report["code"] is None in that case.
- **Fix:** report.json gained a `code_error` key. The change is additive and the schema stays 1.
- **Commit:** `3c16d4d`.

**3. [Rule 3 - Blocking] Frozen.report() helper accepts new top-level dict keys**
- **Found during:** Task 1.
- **Issue:** `{**rep[k], **v}` raised KeyError for the new `code` key.
- **Fix:** It now uses `rep.get(k) or {}`. No existing assertion changed.
- **Commit:** `1cf2c67`.

---

**Total deviations:** 3 auto-fixed (1 bug, 1 missing critical, 1 blocking).
**Impact on plan:** All three are small and needed for the acceptance criteria; nothing outside the plan's scope changed.

## Issues Encountered

- **The worktree had no venvs.** I ran `scripts/bootstrap-dev.sh` (worktree-safe) to create `.venv` and `.venv313` before any test.
- **The first full-gate run failed one test.** `tests/soak/test_soak_systemd.py::test_user_scope_tracer_end_to_end` failed with "fault f01 kill-core … the tablet never lost the core (fault not effective?)". systemd had killed and restarted the core (NRestarts 1, a 2 s gap), but the tablet client missed the gap. The laptop was loaded at the time, and the sibling 04-05 gate was probably running too.
  - This plan does not touch that code path: the user-scope backend, the faults and the tablet are unchanged.
  - The test passed alone on a re-run (21.97 s).
  - A second full gate run was all green on both interpreters.
  - It is noted as a possible flake under load; no fix was attempted (out of scope).
- **Two stale-looking rules in the review were left alone because they are outside this plan:** IN-06 for the *existing* `test_systemd_cleanup_alone_removes_stale_dropins`, and the existing user-scope atexit. The plan said the existing tests stay unchanged. The new tests follow IN-06.

## Known Stubs

None.

## User Setup Required

None. The owner's human items remain those the plan lists (below).

## Next Phase Readiness

- **Before the freeze (2026-11-11):**
  - Re-run the laptop `bash scripts/soak.sh --scenario race-36h` on the merged HEAD. 04-04 and 04-05 change `src/`, so F3 needs a new report, and that report will also carry `code`.
  - Rebuild the wheelhouse, re-provision the Pi, run the Pi soak per docs/SOAK.md (with `--logs-fs loop:512M`), then copy the run dir back; F4 must then PASS on the fingerprint.

## Self-Check: PASSED

- All created and modified files exist: tests/soak/test_soak_identity.py, src/jabuka/soak/report.py, src/jabuka/tools/soak.py, src/jabuka/soak/systemd.py, scripts/freeze-check.sh, the docs.
- Commits 1cf2c67, 3c16d4d, f23072b, e0953a0, f3f4ef5, 77810da are present on worktree-agent-ac582267de982144a, and `git rev-list --count cf03fe84..HEAD` is 6.
- I re-ran each task's acceptance criteria: the import checks, the `non_git` test on both venvs, the `-h` header, the CLI exit codes, the doc greps, the CI soak PASS and the gate `check: ok`.

---
*Phase: 04-race-readiness-hardening-commissioning*
*Completed: 2026-11-08*
