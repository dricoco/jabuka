---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-08T20:32:10Z
status: human_needed
score: 51/55 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-07-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-08-SUMMARY.md", "deploy/PI-SETUP.md", "docs/COMMISSIONING-SL.md", "docs/COMMISSIONING.md", "docs/FREEZE.md", "docs/SOAK.md", "docs/SPARE-SD.md", "pyproject.toml", "scripts/commissioning-rehearsal.sh", "scripts/freeze-check.sh", "scripts/soak.sh", "src/jabuka/common/atomicio.py", "src/jabuka/core/router_service.py", "src/jabuka/nav/course.py", "src/jabuka/nav/settings.py", "src/jabuka/soak/faults.py", "src/jabuka/soak/probes.py", "src/jabuka/soak/report.py", "src/jabuka/soak/scenario.py", "src/jabuka/soak/supervisor.py", "src/jabuka/soak/systemd.py", "src/jabuka/tools/rehearsal.py", "src/jabuka/tools/soak.py", "src/jabuka/web/static/i18n.js", "tests/commissioning/test_freeze_check.py", "tests/nav/test_state_corruption.py", "tests/routing/test_supervisor.py", "tests/soak/test_soak_identity.py", "tests/soak/test_soak_systemd.py"]
covered_digest: "v1:sha256:92cf7b3402b8ec3e93df6a9fa3e277a030ed099c618a7e214ae0ffa96d98268e"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 43/48
  gaps_closed:
    - "07-5 / review CR-01 (previous BLOCKER): a held end-of-run Ctrl-C/SIGHUP killed journalctl, which truncated the journal and gave a false PASS. CLOSED. dump_journal (systemd.py L752-826) runs journalctl with start_new_session=True and timeout JOURNAL_TIMEOUT_S=300. A non-zero rc (including a negative rc when killed by a signal), a timeout (partial stdout kept), an OSError, or in system scope a unit with zero entries sets SystemdBackend.journal.complete=false. journal_problem() (soak.py L1209-1219) then makes the tracebacks check ok False ('journal dump incomplete (…)'), so the verdict is FAIL. report.json records end_signal, and freeze-check end_state() refuses non-null/absent end_signal ('soak interrompu') and systemd.journal.complete != true ('copie du journal des unités incomplète') before every PASS branch. Independent repro: the same harness as last round (real dump_journal + real SignalHold, driver run under setsid, fake journalctl printing 'started', sleeping 3 s, then a Traceback, os.killpg(SIGINT) at 1 s). Before the fix: held 2, journal '1.000 started', 0 blocks. Now: held 2, journal {complete: true, entries core 4 / ingest 1}, the traceback is in the copy, 1 block, journal_problem None. A system-scope empty copy gives complete false ('no journal entry for jabuka-core.service; …'), and journal_problem is non-None."
  gaps_remaining: []
  regressions: []
advisory:
  - finding: "Review WR-01 (dbcd536): a `--systemd user` race-36h soak whose user-journal copy comes back empty (rc 0, zero entries) is recorded complete:true, journal_problem() is None, the tracebacks check is ok, and F3 (x86_64 accepts any mode) could PASS without unit-output evidence"
    category: other
    reason: "Reproduced independently: fake journalctl rc 0 with no output, SystemdBackend('user') core+ingest → {complete: true, error: null, entries {core: 0, ingest: 0}}, journal_problem None. Not a blocker. (1) It is off-procedure: the documented F3 run is `bash scripts/soak.sh` (shim, FREEZE.md checklist step 1). SOAK.md uses `--systemd user` only for the tracer/ci scenarios. The shim backend does not depend on the journal. (2) F4 (the Pi evidence for SC1) uses system scope, where the zero-entry rule applies and FAILs (also reproduced). (3) The trigger needs a host whose user journal is unreadable or volatile-empty. On this laptop, the real user-scope e2e reads entries. (4) The 04-08 test-tier prohibition explicitly scopes the empty-unit rule to system scope. To close it, apply the zero-entry rule in both scopes, or have freeze-check refuse any systemd-mode report with entries[role] == 0. Recommended before the freeze, but it does not gate the phase."
    evidence_status: "deterministic repro of the code path; no in-procedure trigger"
  - finding: "Review IN-01 (dbcd536): journal entries lost inside journald (Pi Storage=volatile RuntimeMaxUse=32M vacuum, rate limiting, backward clock step vs --since @t0-1) still read as a complete copy, because PID 1's final Stopped lines keep entries >= 1"
    category: other
    reason: "Accepted and noted in 04-08-PLAN 'Deferred findings'. The unit-journal volume is tens of lines and the Pi run is about 1.8 h at --speed 20. The owner still checks that both proc/*-journal.log files are non-empty. Cross-checking InvocationIDs or using a cursor would close it."
    evidence_status: "reviewer repro with a fake journalctl; low probability"
  - finding: "Review IN-03 (dbcd536): a signal arriving after run_soak reads end_signal and before the hold is released exits 128+n with end_signal null in report.json"
    category: other
    reason: "The evidence is complete (the journal copy has already finished), so this is not a false PASS of the evidence. The SOAK.md step 6 acceptance (exit code 0 AND end_signal null) still rejects that run when the owner follows it. The window is milliseconds."
    evidence_status: "code read (soak.py L1413-1423)"
  - finding: "Review IN-02 / IN-04 (dbcd536): the cleanup's nested hold announces 'report.json' where none will be written; the group-SIGINT test is timed by a 0.5 s sleep and could become vacuous on a loaded box"
    category: other
    reason: "Wording/UX and test robustness only. My independent repro (SIGINT at 1 s, fake sleeps 3 s, behaviour confirmed) covers IN-04 for this verification."
    evidence_status: "code read; independent repro passes"
  - finding: "Carried (deferred with rationale): WR-04 git-less F4 fingerprint scope; WR-03/IN-01 04-05-era '.bak restauré' alert; laptop userns parent 30 s wait (old IN-03); run ordering by dir name"
    category: other
    reason: "Unchanged, deferred by 04-06/04-07/04-08 with rationale; all fail closed or never certify a false PASS."
    evidence_status: "none provided"
human_verification:
  - test: "Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length (no --duration), never Ctrl-C at the end. Quick runs go to `--out var/soak-essais`."
    expected: "Verdict PASS, exit 0, report.json end_signal null, duration_s 129600, sim_s >= 129600, scenario_sha256 = sha256 of race-36h.json at HEAD, no 'after the end of the run' skips. freeze-check F3 PASS. Today F3 FAILs by design: every existing laptop report (20261107*) predates end_signal/scenario_sha256."
    why_human: "About 40 min of wall time on the owner's laptop, on the final HEAD"
  - test: "Pi 3B system-scope soak (ROADMAP SC1). Rebuild the wheelhouse from the final HEAD (`bash scripts/build-wheelhouse.sh`; F6 FAILs today) and re-provision the Pi. The installed fingerprint must equal c36c79860a3a2f8d97b0f60a5721adc50e131db0760ac6e6b1f337b34a9e2c58, if src/jabuka has not changed since. Then, inside `tmux new -s soak`: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`. Do not press Ctrl-C at the end; wait for `jabuka-soak: verdict`. scp only that run dir back, reboot, check `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0 and both units active."
    expected: "No WARNING line at startup. Exit code 0, verdict PASS, end_signal null, systemd.journal.complete true with entries core > 0 and ingest > 0, proc/core-journal.log and proc/ingest-journal.log non-empty, tick ratio >= 0.95, core/worker RSS <= 250 MB, no throttling/under-voltage, cleanup.restarted true. freeze-check F4 PASS 'paquet installé = src/jabuka à HEAD'. This run also confirms on real Pi journald that the new zero-entry rule does not false-FAIL (T-04-08-04 residual)."
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
  - test: "Owner reads docs/COMMISSIONING.md, docs/SOAK.md (Pi section steps 6 and 8, rewritten by 04-08) and docs/FREEZE.md once, and adjusts the 12 Nov timings; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md and the SL 'obnovljen iz varnostne kopije' strings"
    expected: "Timings fit; French operator wording clear; SL wording correct"
    why_human: "Owner logistics and native-language review (04-08 D3 human_judgment)"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-08T20:32:10Z (main dbcd536; last code commit 87d01a2, docs 039ca1e, later commits .planning only)
**Status:** human_needed
**Re-verification:** Yes, after gap closure 04-08

## Verdict on gap 07-5 (review CR-01): CLOSED

**Gap 07-5 is closed.** I checked it with my own runs against the real code, not from the SUMMARY.

The fix has three layers. All three are present, wired and exercised.

| Layer | Code | Evidence |
| --- | --- | --- |
| 1. The journal copy survives a group signal | `dump_journal` runs journalctl with `start_new_session=True` and `timeout=JOURNAL_TIMEOUT_S` (300 s) (systemd.py L774-776). `unmount()` (L960) and `pi_probe` vcgencmd (probes.py L103-105) also run in their own session. | **My repro**, same harness as last round: real `dump_journal` + real `SignalHold`, driver under `setsid`, fake journalctl printing "started", sleeping 3 s, then a Traceback, `os.killpg(SIGINT)` at 1 s → held 2, `journal = {complete: true, entries {core: 4, ingest: 1}}`, `RuntimeError: boom` in the copy, **1 traceback block**. Last round the same scenario gave `'1.000 started\n'` and 0 blocks. |
| 2. A failed copy is never silent | rc ≠ 0, timeout (partial stdout kept), OSError, or a system-scope unit with 0 entries sets `journal.complete = false` with the reason. `journal_problem()` (soak.py L1209-1219) then gives `tracebacks` ok False with "journal dump incomplete (…)", so the verdict is FAIL. | My repro: an empty system-scope copy gives `complete false`, "no journal entry for jabuka-core.service; no journal entry for jabuka-ingest-fastnet.service", and `journal_problem` is non-None. The named tests pass on 3.13 and 3.14: rc 1, rc -9, timeout, missing binary, empty unit, harness timeout → verdict FAIL. |
| 3. An interrupted soak never certifies the freeze | `report["end_signal"]` is the end-hold signal, else the cleanup's `pending_signal` (soak.py L1413-1416). freeze-check `end_state()` gives `interrupted` (non-null or absent) or `journal` (systemd mode and `complete` not true). It runs after not-scenario/short and before every PASS branch. | My e2e: the real 04-08 harness report copied into a fresh clone of HEAD, reshaped to full length → `[PASS] F3 … PASS sur 87d01a21daa3`. With `end_signal 2` → `[FAIL] F3 … soak interrompu (signal 2 …)`. With the key deleted → `[FAIL] F3 … soak interrompu (end_signal absent : banc antérieur au plan 04-08)`. |

docs/SOAK.md no longer says that a Ctrl-C during the journal copy is harmless. It now says:
- the journal copy runs in its "propre session";
- such a run is a "soak interrompu", which F3/F4 refuse;
- a failed copy gives "journal dump incomplete";
- step 6 accepts a run only with exit 0, PASS, non-empty journal files, `end_signal` null and `journal.complete` true;
- step 8: do not press Ctrl-C at the end; kill -9 only after ~15 min.

## Review WR-01 (dbcd536), weighed independently: advisory, not blocking

**Reproduced:** a `SystemdBackend("user")` with a journalctl that exits 0 and prints nothing gives `{complete: true, error: null, entries {core: 0, ingest: 0}}`, and `journal_problem` is None. In user scope, a race-36h soak could therefore PASS the tracebacks check with no unit-output evidence, and F3 (x86_64, any mode) would count it.

**Why it does not block the phase goal or the freeze truth:**

- **Off-procedure.**
  - The documented F3 run is `bash scripts/soak.sh` (shim). See FREEZE.md checklist step 1 and the SOAK.md Pi section.
  - SOAK.md shows `--systemd user` only with the `tracer` and `ci` scenarios, never with race-36h.
  - The shim pipes process output itself and never depends on the journal (`journal_problem` returns None for it by design).
- **The Pi evidence is protected.** F4 accepts only `mode systemd` with `code.source units`, which is system scope. There the zero-entry rule FAILs an empty copy (my repro above).
- **Host-dependent trigger.** It needs a user journal that is unreadable or volatile-empty. On this laptop (systemd 260), the real `test_user_scope_tracer_end_to_end` reads entries and passes.
- **Accepted scope.** The 04-08 test-tier prohibition explicitly limits the empty-unit rule to system scope.

**Recommended (cheap, before the freeze):** apply the zero-entry rule in both scopes, or make freeze-check refuse a systemd-mode report with any `entries[role] == 0`. It is recorded under `advisory`.

## User Flow Coverage (MVP mode)

User story (same restatement as plans 04-04 to 04-08): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Prove 36 h of faults on the laptop | One command, every CONTEXT fault, budgets | Harness green in gate-04-08; CI soak PASS (`var/soak-04-08/20261108T201811Z-ci`, end_signal null, code c36c79860a3a). Full race-36h re-run on HEAD pending | ✓ code / ? human re-run |
| Prove it on the Pi 3B | Same soak against the installed units, identity recorded, units restored, verdict trustworthy | `--systemd system`, identity, verified restart, end-of-run hold. **The journal copy is isolated and accounted for, and an interrupted run is recorded and refused** | ✓ code / ? human (hardware) |
| Freeze on 11 Nov | Checker green **only** for real, full-length, uninterrupted soaks with a complete journal | Full-length rule, F3 git rule and the 04-08 `end_state` rule, all reproduced | ✓ checker / ? human event |
| Spare SD | Clone boots to the same state | SPARE-SD.md step 5 FINGERPRINT_SH | ? human |
| Commission on 12–13 Nov | Timed runbook, rehearsed | COMMISSIONING.md + rehearsal (gate green) | ✓ doc / ? human on board |
| Tablet trustworthy at night | Wind + laylines; no silent fallback | 04-05 `.bak` alerts; stale-route withdrawal | ✓ code / ? human on board |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h ~60× soak **on the Pi 3B** with faults; recovery, memory, tablet | ? HUMAN | Pi run due 2026-11-10. Verdict integrity gap closed (07-5) |
| SC2 | Runbook exists, dry-run against replayed capture, all listed topics | ✓ VERIFIED | Doc/rehearsal tests in gate-04-08 (1633 passed ×2, `check: ok`, EXIT=0) |
| SC3 | Frozen 2026-11-11; spare SD boots same; 12 Nov capture replays; config-only | ? HUMAN | Future-dated events; the freeze gate now counts only full-length, uninterrupted runs |
| SC4 | Helm tablet shows live/manual/GRIB wind + laylines at night | ? HUMAN | Phase 2 software, unchanged (race path untouched by 04-08: empty diff on nav/core/web) |
| 01-1..01-7 | Soak harness, budgets, state survival, leak/fd, tracebacks, GPS clock, CI soak in gate | ✓ VERIFIED | Regression: gate-04-08 green; CI soak PASS. 01-5 now also holds in system scope (journal integrity, 07-5) |
| 02-1..02-5 | French timed runbook, rehearsal, binding, freeze checker full-length rule, SPARE-SD | ✓ VERIFIED | Unchanged; tests green; 02-4 extended by end_state (my e2e) |
| 03-1 | Pi `--systemd system` against installed units, cleanup always | ? HUMAN (software ✓) | Real run human |
| 03-2..03-4 | User-scope e2e; laptop race-36h historic PASS; Pi temp/throttling recorded | ✓ VERIFIED | e2e passes with the two appended asserts (journal complete, end_signal null) |
| 04-1..04-8 | Code identity, F3/F4 fingerprint rule, stale venv FAIL, identity print, tmpfs refused, cleanup order, one fingerprint definition, docs + gate | ✓ VERIFIED | Regression; fingerprint at HEAD recomputed by me with the FREEZE.md command = c36c79860a3a2f8d…, equal to the e2e report's code.sha256 |
| 05-1..05-6 | `.bak` restore + alerts, schema fall-through, happy path, stale recycled pool, gate | ✓ VERIFIED | Unchanged; gate |
| 06-1..06-7 | F4 only from the documented system-scope run; shim/user/code-less FAIL; verified restart; deferred cleanup signals; aarch64 WARNING; docs | ✓ VERIFIED | Unchanged; tests pass |
| 07-1..07-4, 07-6, 07-7 | Full-length rule, real shortened run FAILs, new report keys, head-null FAIL, docs, gate | ✓ VERIFIED | Unchanged; regression tests pass; 07-6's SOAK.md overpromise corrected by 04-08 |
| 07-5 | WR-02: signals held from end of main run until report written; window covers shutdown **and the journal dump**; never acted on | ✓ VERIFIED (was FAILED) | Behaviour-dependent: `test_group_sigint_during_the_journal_copy_keeps_the_whole_journal` passes (3.13 + 3.14), plus my independent repro (SIGINT at 1 s, 1 block kept). An interrupted run is recorded (end_signal) and refused by F3/F4 |
| 08-1 | Group SIGINT/SIGHUP during dump_journal no longer reaches journalctl; copy complete (1 block) | ✓ VERIFIED | Named test + my repro |
| 08-2 | Every failed journal copy recorded (rc, rc<0, 300 s timeout, OSError, system-scope empty unit); tracebacks check FAIL "journal dump incomplete (", verdict FAIL; complete copy unchanged | ✓ VERIFIED | `test_a_failed_journal_copy_is_recorded_never_silent`, `test_incomplete_journal_copy_fails_the_tracebacks_check_and_the_verdict`, `test_complete_journal_copy_keeps_the_tracebacks_check` pass; my empty-system repro |
| 08-3 | umount and vcgencmd in their own session | ✓ VERIFIED | systemd.py L960, probes.py L103-105; `test_end_of_run_children_get_their_own_session` passes. Remaining group-sharing children (git_info, locate_package, mkfs/mount at setup) are not end-of-run evidence producers, or they fail closed (git null → F3 FAIL) |
| 08-4 | report.json end_signal; report.md "Soak interrompu"; F3/F4 FAIL interrupted/absent and incomplete journal, before every PASS; a genuine full report still PASSes F3 | ✓ VERIFIED | freeze-check L203-217, L250-252, L272-275; 4 named freeze tests + 2 harness tests pass; my e2e on a clone of HEAD: PASS / FAIL signal 2 / FAIL absent |
| 08-5 | IN-01 un-mask suffix; IN-02 held-signal stderr line via os.write; soak.sh `tee -i` | ✓ VERIFIED | freeze-check L270/L272; `HELD_SIGNAL_MESSAGE` + `contextlib.suppress(OSError)`; soak.sh L78; `test_a_held_signal_is_announced_once_and_never_raises`, `test_short_or_foreign_run_fail_says_how_to_unmask_an_older_full_soak` pass |
| 08-6 | SOAK.md drops the false promise and states own session / soak interrompu / journal dump incomplete / ~15 min / no Ctrl-C; FREEZE.md F3/F4 rule; bound by test | ✓ VERIFIED (content) | Docs diff read in full; `test_docs_describe_the_interrupted_soak_and_the_journal_copy` passes. The owner should still read the French wording (human item 9) |
| 08-7 | Both venvs green; CI soak PASS; gate `check: ok` / EXIT=0; REQUIREMENTS.md and race path unchanged; no race-36h dir added under var/soak | ✓ VERIFIED | My run: 104 passed (3.13, three test files), 10 targeted passed (3.14). var/gate-04-08.log (21:18, after the last code/doc commit): 1633 passed, 4 skipped ×2, `check: ok`, `EXIT=0`. CI report PASS. Empty diff on REQUIREMENTS.md and nav/core/web. var/soak race-36h dirs: only the four 20261107 ones. 0 removed `assert` lines in tests |

**Score:** 51/55 truths verified. 0 failed. 4 human-only (SC1, SC3, SC4, 03-1). 0 present-but-behaviour-unverified.

### Prohibitions (04-08, test tier)

| Prohibition | Enforcement evidence | Status |
| --- | --- | --- |
| MUST NOT let a soak report PASS when the units' journal copy was truncated by a signal, failed, timed out, or (system scope) came back empty | 3 named tests pass + my repro (signal and empty system scope) | ✓ enforced (user-scope empty is out of its stated scope: WR-01 advisory) |
| MUST NOT let F3/F4 PASS an interrupted (end_signal non-null/absent) report, or a systemd report with an incomplete journal copy | 3 named freeze tests pass + my real-report e2e (signal 2 and absent → FAIL) | ✓ enforced |
| MUST NOT reject a genuine uninterrupted full-length soak | test_frozen_repo_passes + 04-06/04-07 positive cases pass; user-scope e2e asserts journal complete and end_signal null; my real full-shape report → `[PASS] F3` | ✓ enforced (Pi journald behaviour is confirmed by the human Pi soak) |

The 04-07 prohibitions still hold (regression tests pass).

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/jabuka/soak/systemd.py` | JOURNAL_TIMEOUT_S; dump_journal own session + `journal` record; unmount own session; SignalHold(announce_fd) | ✓ VERIFIED | Diff read; wired into info() → report.json `systemd.journal` |
| `src/jabuka/soak/probes.py` | vcgencmd own session | ✓ VERIFIED | L103-105 |
| `src/jabuka/tools/soak.py` | journal_problem; tracebacks FAIL; end_signal in build_report and run_soak | ✓ VERIFIED | L961-976, L1129-1132, L1209-1219, L1413-1416 |
| `src/jabuka/soak/report.py` | docstring keys; "Soak interrompu" | ✓ VERIFIED | int-not-bool guard; test passes |
| `scripts/freeze-check.sh` | end_state; interrupted/journal FAILs; IN-01 suffix; header/-h | ✓ VERIFIED | `-h` range 2-36 |
| `scripts/soak.sh` | `tee -i` | ✓ VERIFIED | L78; RC still `${PIPESTATUS[0]}` |
| `tests/soak/test_soak_systemd.py`, `tests/commissioning/test_freeze_check.py`, `tests/soak/test_soak_identity.py` | New cases | ✓ VERIFIED | All pass, both interpreters |
| `docs/SOAK.md`, `docs/FREEZE.md` | Corrected promise, rules, ~15 min, no Ctrl-C | ✓ VERIFIED | Diff read |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| systemd.dump_journal | tools/soak compute_checks | SystemdBackend.journal → journal_problem → tracebacks ok False → finalize FAIL | ✓ WIRED | Harness timeout test → verdict FAIL |
| tools/soak run_soak | freeze-check.sh | report["end_signal"] → end_state → interrupted FAIL | ✓ WIRED | My e2e |
| SystemdBackend.info | report.json systemd.journal | build_report copies info() when a scope is set | ✓ WIRED | freeze-check `journal` state reads it |
| SignalHold | journalctl child | the held signal must not reach the evidence child | ✓ WIRED (was NOT_WIRED) | start_new_session=True; repro keeps the full copy |
| docs | freeze-check / soak.sh | wording bound by test | ✓ WIRED | Doc test passes |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| tracebacks check (system scope) | proc/*-journal.log + journal.complete | journalctl stdout in its own session; failures recorded | Yes; an incomplete copy now FAILs instead of reading as clean | ✓ FLOWING (was HOLLOW) |
| report.json end_signal | end_signals.signal / pending_signal | real SignalHold | Yes (null in real runs; 2 when held, per tests) | ✓ FLOWING |
| freeze-check F3/F4 | state interrupted / journal | report keys | Yes | ✓ FLOWING |
| tracebacks check (user scope, empty journal) | entries 0, complete true | — | Accepted as clean (WR-01) | ⚠️ advisory, off-procedure |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 04-08 + regression test files (3.13) | `pytest tests/soak/test_soak_systemd.py tests/commissioning/test_freeze_check.py tests/soak/test_soak_identity.py` | 104 passed in 36 s | ✓ PASS |
| Targeted 04-08 tests (3.14) | `.venv/bin/python -m pytest … -k "group_sigint or failed_journal or own_session or …"` | 10 passed | ✓ PASS |
| CR-01 repro, no signal | real dump_journal, setsid driver, fake journalctl | complete, core 4 / ingest 1, 1 block | ✓ PASS |
| CR-01 repro, group SIGINT at 1 s | same + `os.killpg(SIGINT)` | held 2, complete, 1 block (was 0) | ✓ PASS (gap closed) |
| System scope empty copy | fake rc 0, no output | complete false, "no journal entry for …", journal_problem set | ✓ PASS |
| User scope empty copy (WR-01) | same, user scope | complete true, journal_problem None | ⚠️ advisory |
| Real report e2e on a clone of HEAD | `freeze-check --repo <clone> --pre --skip-gate` | full shape `[PASS] F3`; end_signal 2 `[FAIL] … soak interrompu`; key deleted `[FAIL] … end_signal absent` | ✓ PASS |
| Fingerprint at HEAD | FREEZE.md FINGERPRINT_SH on src/jabuka | c36c79860a3a2f8d97b0f60a5721adc50e131db0760ac6e6b1f337b34a9e2c58 (= SUMMARY, = e2e report) | ✓ PASS |
| Full gate | `var/gate-04-08.log` | 1633 passed, 4 skipped ×2, `check: ok`, `EXIT=0` | ✓ PASS |
| Debt markers in the 04-08 diff | grep TBD/FIXME/XXX/TODO/HACK on added lines | none | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist, and the plans declare none. I ran the phase's runnable checks directly (above).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-02 | 04-01, 04-03..04-08 | ~36 h unattended on the Pi 3B, verified by an accelerated fault-injected soak | ✓ SATISFIED (software) / ? NEEDS HUMAN | The soak verdict and freeze gate are now sound: journal integrity, interrupted runs refused, full-length rule. The real Pi soak (10 Nov) is human. REQUIREMENTS.md is correctly still unchecked ("Gaps Found"). The orchestrator should set it to "Pending human" or similar after this verification |
| REL-03 | 04-02, 04-04, 04-06..04-08 | On-boat commissioning runbook for 12–13 Nov | ✓ SATISFIED (doc) / ? human on board | COMMISSIONING/FREEZE/SOAK/SPARE-SD; SOAK.md Pi steps 6/8 updated |

No orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and both are claimed by plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| src/jabuka/soak/systemd.py | 815-821 | Zero-entry rule limited to system scope (WR-01) | 📋 Advisory | Off-procedure user-scope race-36h only |
| src/jabuka/tools/soak.py | 1413-1423 | end_signal read before the hold is released (IN-03) | ℹ️ Info | Evidence complete; exit-code acceptance still rejects the run |
| src/jabuka/soak/systemd.py | 62-65, 854 | Nested cleanup hold reuses the end-of-soak announcement (IN-02) | ℹ️ Info | Wording |
| tests/soak/test_soak_systemd.py | `_GROUP_SIGINT_DRIVER` | Sleep-timed signal (IN-04) | ℹ️ Info | Could become vacuous under load; my repro covers it today |
| docs/FREEZE.md | "Lock revu" line | `À REMPLIR` | ℹ️ Info | Intentional owner input, enforced by F5 |

### Human Verification Required

1. **Laptop race-36h on the final HEAD, full length, no Ctrl-C at the end.** Every existing laptop report lacks `end_signal` and is refused by design.
2. **Pi 3B system-scope soak.**
   - Before: rebuild the wheelhouse (fingerprint c36c7986…), re-provision, run inside tmux.
   - During: no Ctrl-C at the end.
   - Accept only exit 0 + PASS + end_signal null + journal.complete true with entries > 0. This also confirms Pi journald under the new rules.
3. **Pi budgets.** Fill in SOAK.md "Budgets Pi à confirmer".
4. **5 real power pulls.** Run logcheck after each one.
5. **Freeze on 11 Nov.** freeze-check must exit 0.
6. **Spare SD.** Clone it and boot it; the fingerprint must match.
7. **12 Nov capture replay.**
8. **On-board commissioning on 12–13 Nov.**
9. **Proofreading.** Runbook timings; owner read of SOAK/FREEZE French wording; SL proofreading.

### Gaps Summary

**Gap 07-5 (review CR-01) is closed. I verified it with my own runs.**
- The repro that truncated the journal last round now keeps the whole copy (1 traceback block).
- Every failed copy is recorded and FAILs the verdict.
- An end-of-run signal is recorded as `end_signal` and refused by F3/F4.
- A genuine full-length report still PASSes F3.

**No automated must-have fails.**

**Review WR-01** (empty user-scope journal counted complete) is reproduced. It is advisory, not blocking:
- the documented F3 path is the shim;
- F4 is system scope, where empty copies FAIL;
- the trigger depends on the host's journald.

A one-line fix (zero-entry rule in both scopes) is recommended before the freeze.

**What remains is human-only:** the Pi and laptop soaks on the final HEAD, power pulls, freeze, spare SD, capture replay, on-board commissioning, and proofreading.

---

_Verified: 2026-11-08T20:32:10Z_
_Verifier: Claude (gsd-verifier)_
