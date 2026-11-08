---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-08T17:46:38Z
status: gaps_found
score: 35/41 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-04-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-05-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-06-SUMMARY.md", "deploy/PI-SETUP.md", "docs/COMMISSIONING-SL.md", "docs/COMMISSIONING.md", "docs/FREEZE.md", "docs/SOAK.md", "docs/SPARE-SD.md", "pyproject.toml", "scripts/commissioning-rehearsal.sh", "scripts/freeze-check.sh", "scripts/soak.sh", "src/jabuka/common/atomicio.py", "src/jabuka/core/router_service.py", "src/jabuka/nav/course.py", "src/jabuka/nav/settings.py", "src/jabuka/soak/faults.py", "src/jabuka/soak/report.py", "src/jabuka/soak/supervisor.py", "src/jabuka/soak/systemd.py", "src/jabuka/tools/rehearsal.py", "src/jabuka/tools/soak.py", "src/jabuka/web/static/i18n.js", "tests/commissioning/test_freeze_check.py", "tests/nav/test_state_corruption.py", "tests/routing/test_supervisor.py", "tests/soak/test_soak_identity.py", "tests/soak/test_soak_systemd.py"]
covered_digest: "v1:sha256:e33378e65c269f156a2c1c89d19f73691011de67bf82a8f50416a0219a98a4a6"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 29/34
  gaps_closed:
    - "02-4 / CR-01 (previous): F4 accepted a shim, --systemd user or code-less aarch64 report. CLOSED. The freeze-check helper now maps an aarch64 report with no valid code.sha256 to no-code and any report whose mode is not systemd or whose code.source is not units to not-units; both FAIL before any PASS branch (scripts/freeze-check.sh L169-175, L190-193). The six negative tests and the positive git-less system-scope test pass. A user-scope run cannot produce source units (compute_code_identity sets it only in system scope)."
    - "Advisory WR-01 (previous): a failed restart was marked done. CLOSED: restarted = rc 0 AND both units ActiveState active (_await_active, up to 20 s); cleaned stays False otherwise, the verdict FAILs via cleanup_fail_reasons, --systemd-cleanup exits 1 via CleanupIncomplete, systemctl runs with start_new_session."
    - "Advisory WR-02 (previous): a signal during the cleanup lost report.json. CLOSED for the cleanup window: the signal is recorded in pending_signal and run_soak returns 128+n after write_report. SOAK.md step 2 now runs the Pi soak inside tmux."
  gaps_remaining:
    - "02-4 (new root cause): freeze-check F3/F4 accept a shortened (--duration) race-36h run as the 36 h soak. Reproduced end to end with the real harness and the real script."
  regressions: []
gaps:
  - truth: "The 2026-11-11 freeze checker passes only with a clean tree, a green gate, laptop AND Pi race-36h soak reports PASS on code identical to HEAD (04-02 truth 4; ROADMAP SC1 + SC3: the evidence is the 36 h soak). Also 04-06 truth 1: F4 PASSes an aarch64 report only when it comes from the documented `sudo bash scripts/soak.sh --systemd system … --scenario race-36h --speed 20 --logs-fs loop:512M` run."
    status: partial
    reason: "The previous root cause (CR-01: source/mode not checked) is closed. A different fail-open remains in the same PASS branch. The helper selects reports by scenario == 'race-36h' and host.machine only, keeps the newest run directory, and never reads sim_s, skipped or the scenario source. `jabuka-soak --duration SIM_S` keeps scenario 'race-36h' and run_faults() lists every fault scheduled after the shortened end as skipped; decide() ignores skipped, so the verdict is PASS. I ran the real harness: `.venv313/bin/python -m jabuka.tools.soak --scenario race-36h --duration 900 --out <scratchpad>` finished in about 20 s wall with verdict PASS, sim_s 1322, 1 fault run, 93 faults skipped, git at HEAD clean. Copied into var/soak of a scratch clone of HEAD, freeze-check printed `[PASS] F3 portable : var/soak/20261108T174419Z-race-36h/report.json PASS sur ee6f42709dc9, code identique à HEAD`. The review's fixture reproduction (Pi system-scope report with sim_s 600, one skipped power pull) gives `[PASS] F4 Pi : … paquet installé = src/jabuka à HEAD` and `freeze-check: ok`. The same applies to the Pi: `sudo … --systemd system … --scenario race-36h --duration 600 --logs-fs loop:512M` produces mode systemd, source units, and F4 PASSes. docs/SOAK.md L46-47 advertises --duration as the quick-test option and says skipped faults are 'jamais comptées comme passées', yet the freeze gate counts the run. Because the newest race-36h report wins, a quick sanity run made after the real soak (laptop: every run lands in var/soak; Pi: after the FREEZE step 8 re-provision) silently replaces the real 36 h evidence with a 20-second one. This is the same fail-open class as the previous CR-01, in a file this round modified, with deterministic evidence."
    artifacts:
      - path: "scripts/freeze-check.sh"
        issue: "Helper L153-176 picks the newest scenario=='race-36h' report per machine and reads only verdict, mode, git and code. No check of sim_s against the scenario's duration_s, of skipped faults 'after the end of the run', or of where the scenario came from (a custom --scenario file named race-36h is also accepted)."
      - path: "src/jabuka/soak/report.py"
        issue: "decide() (L342-355) ignores report['skipped'], so a shortened run is PASS."
      - path: "src/jabuka/tools/soak.py"
        issue: "build_report (L1055-1075) records sim_s but not the requested duration, the scenario's duration_s or the scenario source, so the report does not say it was shortened."
      - path: "tests/commissioning/test_freeze_check.py"
        issue: "No negative case for a shortened race-36h report."
    missing:
      - "In the freeze-check helper: read the scenario's duration_s at HEAD (git show HEAD:src/jabuka/soak/scenarios/race-36h.json) and give a new state 'short' (FAIL for F3 and F4) when sim_s < ~0.99 × duration_s or any skipped entry says 'after the end of the run'. Bash: FAIL '… essai raccourci (sim_s X / Y) : refaire le soak race-36h complet'."
      - "Optionally (stronger): have the harness record duration_s / scenario_duration_s / scenario_source in report.json and give a non-PASS verdict (e.g. SHORT) whenever --duration < scenario duration_s, so the report itself cannot claim PASS."
      - "Tests: (a) Pi system-scope report with sim_s 600 and a skipped 'after the end of the run' fault → F4 FAIL; (b) same for the laptop report → F3 FAIL; (c) the full-duration Frozen reports still PASS (fixture reports must carry a realistic sim_s)."
advisory:
  - finding: "WR-04 (carried): the git-less F4 path fingerprints src/jabuka plus the two jabuka unit files only; post-soak changes to other deploy/** files or pyproject.toml do not invalidate F4"
    category: other
    reason: "Deferred by 04-06 (T-04-06-05) with rationale: F3 git rule, F5, F6 and FREEZE step 8 re-provision cover it. Note: the F3 compensating control is skippable when a laptop report has git.head null (see WR-01 in the body)."
    evidence_status: "none provided"
  - finding: "WR-03 / IN-01 (carried): 'restauré' alerts cannot be cleared until the core restarts; the first write after a .bak restore turns the corrupt main into the .bak"
    category: other
    reason: "Deferred by 04-06 with rationale; race-path UX / low-probability durability. 04-05 truths hold."
    evidence_status: "none provided"
human_verification:
  - test: "Laptop race-36h soak on the final pre-freeze HEAD: `bash scripts/soak.sh --scenario race-36h` on a clean tree, full length (no --duration). Make sure no later shortened race-36h run sits in var/soak (the newest one is the one freeze-check reads)."
    expected: "Verdict PASS, sim_s ≈ 129 600, no 'after the end of the run' skips. freeze-check F3 PASS (today F3 FAILs 'code modifié depuis le soak (0fff60c -> HEAD …)', as expected)."
    why_human: "About 40 min of wall time on the owner's laptop, on the final HEAD"
  - test: "Pi 3B system-scope soak (ROADMAP SC1). Rebuild the wheelhouse from HEAD (`bash scripts/build-wheelhouse.sh`; F6 shows the current one predates phase 4), re-provision the Pi, install tmux while it has internet. Then on the Pi inside `tmux new -s soak`: `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M`. scp only that run dir back, reboot, check `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0 and `systemctl is-active jabuka-core jabuka-ingest-fastnet` = active active."
    expected: "Startup prints `jabuka-soak: code d42dac399a00 … source units` (fingerprint of src/jabuka at HEAD since 256a762) and no WARNING line. Verdict PASS, tick ratio >= 0.95 (else re-run at --speed 10), core/worker RSS <= 250 MB, no throttling/under-voltage, report.json systemd.cleanup.restarted true with both units active. freeze-check F4 PASS 'paquet installé = src/jabuka à HEAD'."
    why_human: "Needs the real Pi 3B with its installed systemd units"
  - test: "Record the Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer' (also closes 03-05 'Pi memory')"
    expected: "Table filled; numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j, 01-UAT #7)"
    expected: "Services come back each time, logcheck OK, course and settings intact (a visible '.bak restauré' alert is acceptable)"
    why_human: "Physical power interruption"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md: lock review and hash, tag race-2026, wheelhouse from the tag, Pi re-provisioned, `bash scripts/freeze-check.sh` all PASS except F8 WARN and F9 HUMAN (after the 02-4 gap is fixed)"
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
**Verified:** 2026-11-08T17:46:38Z (main ee6f427; code identical to 256a762, later commits are .planning only)
**Status:** gaps_found
**Re-verification:** Yes, after gap closure 04-06

## Verdict on the previous gap "02-4" (CR-01)

**The previous gap is CLOSED.** F4 no longer accepts a shim, `--systemd user` or code-less Pi report. I checked the code, not the summary:

- `scripts/freeze-check.sh` L169-175: for `machine == "aarch64"`, `absent` becomes `no-code`. Any state other than `error` becomes `not-units` when `mode != "systemd"` or `code.source != "units"`. Both map to FAIL branches (L190-193), placed right after the verdict check and before the only fingerprint PASS branch (L198).
- A `--systemd user` run cannot produce `source: units`, because `compute_code_identity` sets it only in system scope.
- The permanent tests pass: shim, user scope, children with wrong units, units with the wrong mode, git without code, malformed sha, plus the positive git-less system-scope case (92 passed in my targeted run on Python 3.13).
- The previous advisories WR-01 (a failed restart counted as done) and WR-02 (a signal during cleanup losing the report) are also closed as specified (see the 06-x rows).

**But truth 02-4 is still not achieved, because of a different root cause. The new review CR-01 is confirmed, end to end.** F3 and F4 accept a shortened `--duration` run of `race-36h` as the 36 h soak:

- **Real harness.** I ran `.venv313/bin/python -m jabuka.tools.soak --scenario race-36h --duration 900 --out <scratchpad>`. It finished in about 20 s with `verdict PASS`, `scenario race-36h`, `sim_s 1322`, 1 fault run and 93 faults skipped "after the end of the run". `git.head` was HEAD and the tree was clean.
- **Real script.** I put that report alone in `var/soak/` of a scratch clone of HEAD. `freeze-check --pre --skip-gate` printed `[PASS] F3 portable : var/soak/20261108T174419Z-race-36h/report.json PASS sur ee6f42709dc9, code identique à HEAD`.
- **Review fixture.** The fixture repro (`test_repro.py`: a Pi system-scope report with `sim_s 600` and a skipped power pull) gives `[PASS] F4 Pi : … paquet installé = src/jabuka à HEAD` and `freeze-check: ok`.

Why this blocks the freeze truth (ROADMAP SC1/SC3):
- freeze-check exists to certify that the 36 h soak happened on the frozen code. A 20-second smoke run gets the same green line.
- freeze-check reads the **newest** race-36h report. A quick `--duration` sanity run made after the real soak therefore silently replaces the real evidence. On the laptop every run lands in `var/soak/`; on the Pi, a natural moment for such a run is after the FREEZE step 8 re-provision.
- docs/SOAK.md L46-47 advertises `--duration` as the "essai rapide" option and promises that skipped faults are "jamais comptées comme passées". The freeze gate counts them anyway.
- This is the same fail-open class as the previous CR-01. It sits in a file this round modified (`scripts/freeze-check.sh`) and has deterministic evidence, so the evidence gate keeps it blocking.

It is not a regression: the hole has existed since 04-02, and previous verifications missed it. The fix is small (see Gaps).

## Review findings: independent assessment

| Review ID | Confirmed? | Evidence | Blocks goal / freeze truth? |
| --- | --- | --- | --- |
| CR-01 (shortened `--duration` race-36h passes F3/F4) | **Yes**, end to end | Real harness run (verdict PASS, 1/94 faults) → real freeze-check F3 PASS on a scratch clone; fixture repro F4 PASS | **Yes: gap on 02-4 / 06-1** |
| WR-01 (F3 skips the git rule when a laptop report has `git.head` null) | **Yes** | `test_repro2.py` (2 passed): after a deploy/pyproject change, `[PASS] F3 portable : … paquet installé = src/jabuka à HEAD`. L198 applies the fingerprint-only PASS to F3 too. FREEZE.md L87 says F3 is "la règle git … plus l'empreinte". | No (warning). This is the behaviour 04-04 specified (truth 04-2) and F3 left unchanged in 04-06. It needs `git_info` to fail on the dev laptop, which always has `.git`, and the fingerprint still binds `src/jabuka`. The doc/code mismatch and the weakened WR-04 compensating control are real. Fix: restrict the L198 shortcut to aarch64, about one line plus one test. |
| WR-02 (signal during `shutdown()` / `build_report()` loses report.json) | **Yes** | `Harness.run` L781-787: only `sup.cleanup()` defers signals. A SIGTERM/SIGINT during `shutdown()` (journal dump) or `build_report()` (final logcheck) escapes as SystemExit/KeyboardInterrupt before `write_report` (L1353). | No (warning). Accepted residual T-04-06-04. The failure mode is "re-run the soak", never a false PASS. tmux removes the SIGHUP-on-SSH-drop case. |
| IN-03 (F4 identifies "the Pi" only by aarch64; no `pi` block required) | Yes (code read) | `freeze-check.sh` L161 | No (info). |

## User Flow Coverage (MVP mode)

User story (same restatement as plans 04-04 to 04-06): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Prove 36 h of faults on the laptop | One command, every CONTEXT fault, budgets | Harness green in the gate; CI soak PASS at HEAD (`var/soak/20261108T173414Z-ci`, code d42dac399a00). The full race-36h re-run on HEAD is pending | ✓ code / ? human re-run |
| Prove it on the Pi 3B | Same soak against the installed units, identity recorded, units restored | `--systemd system`, code identity, tmpfs refusal, verified restart, deferred signal, tmux in docs; tests pass | ? human (hardware) |
| Freeze on 11 Nov | Checker green **only** for the real soaks | System-scope rule closed; **a shortened race-36h run still PASSes F3/F4** | ✗ partial (gap) |
| Spare SD | Clone boots to the same state | SPARE-SD.md step 5 quotes FINGERPRINT_SH (test-bound) | ? human |
| Commission on 12–13 Nov | Timed runbook, rehearsed | COMMISSIONING.md + rehearsal (gate green) | ✓ doc / ? human on board |
| Tablet trustworthy at night | Wind + laylines; no silent fallback | 04-05 `.bak` alerts; stale-route withdrawal | ✓ code / ? human on board |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h ~60× soak **on the Pi 3B** with faults; recovery, memory, tablet | ? HUMAN | Pi run due 2026-11-10; harness path hardened further by 04-06 |
| SC2 | Runbook exists, dry-run against replayed capture, all listed topics | ✓ VERIFIED | test_runbook_docs / test_rehearsal green (gate-04-06: 1603 passed ×2, `check: ok`) |
| SC3 | Frozen 2026-11-11; spare SD boots same; 12 Nov capture replays; config-only | ? HUMAN (+ 02-4 gap) | Future-dated events; freeze-gate integrity tracked under 02-4 |
| SC4 | Helm tablet shows live/manual/GRIB wind + laylines at night | ? HUMAN | Phase 2 software, unchanged |
| 01-1 | One command, SimClock ~60×, faults, report.json + report.md | ✓ VERIFIED | Gate; my short race-36h run produced both files |
| 01-2 | Tablet data within budgets; route after restart; no land crossing | ✓ VERIFIED | Regression (gate) |
| 01-3 | State survives pulls; corrupt state never stops the core | ✓ VERIFIED | Regression (gate) |
| 01-4 | RSS/leak/fd/threads/logs within budget | ✓ VERIFIED | Regression (gate) |
| 01-5 | No unexpected traceback / error counter | ✓ VERIFIED | Regression (gate) |
| 01-6 | GPS clock path end to end | ✓ VERIFIED | Regression (gate) |
| 01-7 | CI soak in the gate on both interpreters | ✓ VERIFIED | var/gate-04-06.log; CI soak PASS at 7f71d01 |
| 02-1 | French timed runbook, nine sections | ✓ VERIFIED | Unchanged; doc tests green |
| 02-2 | Rehearsal script PASS/FAIL/HUMAN, `--capture` | ✓ VERIFIED | Unchanged; tests green |
| 02-3 | Runbook bound to code | ✓ VERIFIED | Unchanged; tests green |
| 02-4 | Freeze checker passes **only** with laptop and Pi race-36h PASS on code identical to HEAD | ✗ PARTIAL | Previous root cause closed. New: shortened `--duration` race-36h run PASSes F3 (real run + real script) and F4 (fixture) |
| 02-5 | SPARE-SD.md: dd + rpi-clone, checks, swap, overlay | ✓ VERIFIED | Unchanged |
| 03-1 | Pi `--systemd system` against installed units, cleanup always | ? HUMAN (software ✓) | Cleanup now verified (ActiveState) and retryable; real run human |
| 03-2 | User-scope e2e on the laptop | ✓ VERIFIED | test_soak_systemd.py passed |
| 03-3 | Laptop race-36h PASS, leak fit enforced | ✓ VERIFIED (historic) | Report on 0fff60c; re-run on HEAD is a human item |
| 03-4 | Pi report records temperature/throttling | ✓ VERIFIED (code) | Unchanged |
| 04-1 | Documented Pi run writes `code` (units' venv fingerprint, units) | ✓ VERIFIED | Unchanged since previous verification; tests pass |
| 04-2 | F3/F4 fingerprint rule (+units for system scope) | ✓ VERIFIED (as specified, F4 tightened by 04-06) | freeze-check L128-150; WR-01 residual for F3 (warning) |
| 04-3 | Checkout at HEAD + stale venv → F4 FAIL | ✓ VERIFIED | test passes |
| 04-4 | Identity printed; system scope refuses without fingerprint | ✓ VERIFIED | My short run printed `jabuka-soak: code d42dac399a00 (146 files, …, source children); git ee6f42709dc9` |
| 04-5 | tmpfs refused in system scope; harness oom -900 | ✓ VERIFIED | Regression (tests; 04-06 SUMMARY CLI check) |
| 04-6 | Cleanup order drop-ins → reload → restart → unmount; retryable | ✓ VERIFIED | systemd.py L776-830; tests pass |
| 04-7 | One fingerprint definition; docs quote it; parity tested | ✓ VERIFIED | Harness fingerprint d42dac399a00… = SUMMARY's HEAD value |
| 04-8 | Docs describe the rule; gate + CI soak green | ✓ VERIFIED | gate-04-06 |
| 05-1 | Corrupt course.json + valid .bak → .bak + "restauré" alert | ✓ VERIFIED | Unchanged; tests in gate |
| 05-2 | Same for settings.json / wind_manual.json | ✓ VERIFIED | Unchanged |
| 05-3 | Schema-invalid main falls through to .bak; else default + "illisible" | ✓ VERIFIED | Unchanged |
| 05-4 | Happy path unchanged | ✓ VERIFIED | Unchanged |
| 05-5 | Recycled pool with in-flight cycle → stale, retry, withdrawal | ✓ VERIFIED | Unchanged |
| 05-6 | Gate + CI soak green | ✓ VERIFIED | gate-04-06 |
| 06-1 | F4 PASSes an aarch64 report **only** from the documented `--systemd system … --scenario race-36h` run (mode systemd, source units, package + units = HEAD) | ✗ PARTIAL | Source/mode/code rule ✓ (L169-175, tests). But a `--duration`-shortened system-scope run is not the documented run and still PASSes (same root cause as 02-4) |
| 06-2 | F4 FAILs shim / user-scope / code-less / malformed-sha Pi reports with an actionable message | ✓ VERIFIED | 6 named tests pass; messages name `--systemd system` / "empreinte"; no-code with git at HEAD FAILs (git no longer a fallback) |
| 06-3 | F3 unchanged; laptop report without code judged by the git rule | ✓ VERIFIED (as specified) | test_f3_laptop_report_without_code_keeps_the_git_rule passes. WR-01: head-null + match still bypasses the git rule (pre-existing, warning) |
| 06-4 | WR-01: verified restart; retryable; verdict FAIL; `--systemd-cleanup` exit 1; own session | ✓ VERIFIED | systemd.py L55, L80, L285 `start_new_session=True`, L312 `_await_active`, L788 `cleaned = user or restarted`, L809 restarted = rc 0 and all active, L917 raise; soak.py L1176 `cleanup_fail_reasons`, L1385-1387 exit 1. Named tests pass (fake systemctl, FAKE_ACTIVE) |
| 06-5 | WR-02: signal during cleanup recorded; report written; return 128+n | ✓ VERIFIED (cleanup window) | systemd.py L771-772; soak.py L1353 write_report then L1363-1372. test_run_soak_writes_the_report_before_honouring_a_deferred_signal passes. Residual outside the cleanup: warning |
| 06-6 | aarch64 shim/user run prints WARNING quoting `--systemd system` | ✓ VERIFIED | `identity_messages(..., machine=platform.machine())`; `PI_F4_COMMAND`; named test passes |
| 06-7 | SOAK.md tmux / F4 rule / cleanup outcome; FREEZE.md F4 rule; gate + CI soak green | ✓ VERIFIED | SOAK.md L216, L229-231 (`tmux new -s soak`, `tmux attach -t soak`), L96-98, L272; FREEZE.md L44-49, L87-93; doc test passes; gate-04-06 `check: ok` EXIT=0 |

**Score:** 35/41 truths verified (0 present-but-behavior-unverified; 2 partial with one root cause; 4 human-only)

### Advisory (New Scope, Unevidenced)

| # | Finding | Category | Why Advisory |
|---|---------|----------|--------------|
| 1 | WR-04 (carried): git-less F4 covers src/jabuka + 2 units only | other | Deferred by 04-06 with rationale; the F3 compensating control is weaker than stated (WR-01) |
| 2 | WR-03 / IN-01 (carried): "restauré" badges cannot be cleared; corrupt main becomes .bak on the next write | other | Deferred by 04-06 with rationale; 04-05 truths hold |

The new review's WR-01 and WR-02 are confirmed with evidence, so they are listed as ⚠️ Warnings below rather than as advisories.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `scripts/freeze-check.sh` | no-code / not-units states and FAIL lines; header and `-h 2,27p` | ⚠️ PARTIAL | System-scope rule present and wired; no duration/skipped check (gap) |
| `tests/commissioning/test_freeze_check.py` | CR-01 negative cases, system-scope Frozen default | ✓ VERIFIED | 7 new cases pass; missing a shortened-run case |
| `src/jabuka/soak/systemd.py` | RESTART_VERIFY_S, CleanupIncomplete, pending_signal, _await_active, start_new_session | ✓ VERIFIED | All present and used |
| `src/jabuka/tools/soak.py` | cleanup_fail_reasons, run_soak 128+sig after report, identity WARNING, cleanup exit 1 | ✓ VERIFIED | Wired in Harness.run / run_soak / main |
| `tests/soak/test_soak_systemd.py` | failed-restart, rc, own-session, report-before-signal, CLI, IN-06 | ✓ VERIFIED | Pass |
| `tests/soak/test_soak_identity.py` | aarch64 WARNING; doc binding (tmux, F4) | ✓ VERIFIED | Pass |
| `docs/SOAK.md`, `docs/FREEZE.md` | tmux, F4 rule, cleanup outcome | ✓ VERIFIED | Present; FREEZE.md F3 wording overstates the code (WR-01) |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| freeze-check.sh | var/soak/*/report.json | aarch64: mode + code.source + code.sha256 + code.units → no-code / not-units / match | ✓ WIRED | L169-176 → L190-199 |
| freeze-check.sh | var/soak/*/report.json | scenario duration actually run (sim_s / skipped) | ✗ NOT_WIRED | Never read (gap 02-4) |
| tools/soak.py | soak/systemd.py | Harness.run → sup.cleanup() → cleanup_fail_reasons; run_soak → write_report → pending_signal → 128+n | ✓ WIRED | L784-792, L1353-1372 |
| soak/systemd.py | systemctl | `_await_active` polls `show -p ActiveState`; restarted = rc 0 and all active | ✓ WIRED | L312-320, L809 |
| docs/FREEZE.md | freeze-check.sh | F4 wording bound by test_soak_identity.py | ✓ WIRED | Doc test passes |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| report.json `code` | sha256 / source | `compute_code_identity` (real run: d42dac399a00, 146 files, source children) | Yes | ✓ FLOWING |
| report.json `systemd.cleanup` | restarted / restart_rc / active | `_cleanup_system` → `_await_active` | Yes (fake systemctl tests) | ✓ FLOWING |
| freeze-check F3/F4 | cstate | report `code`, `mode` + git archive HEAD | Yes | ✓ FLOWING (but sim_s ignored) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 04-06 test files | `.venv313/bin/python -m pytest tests/commissioning/test_freeze_check.py tests/soak/test_soak_identity.py tests/soak/test_soak_systemd.py tests/commissioning/test_runbook_docs.py` | 92 passed in 28.7 s | ✓ PASS |
| Full gate (orchestrator log) | `tail var/gate-04-06.log` | 1603 passed, 4 skipped ×2, `check: ok`, EXIT=0 | ✓ PASS |
| CI soak at HEAD | `var/soak/20261108T173414Z-ci/report.json` | PASS, git 7f71d01 clean, code d42dac399a00 | ✓ PASS |
| Code unchanged since 256a762 | `git diff --stat 256a762 HEAD -- src scripts deploy pyproject.toml tests docs` | empty | ✓ PASS |
| freeze-check on the repo | `bash scripts/freeze-check.sh --pre --skip-gate` | F1 PASS; F3 FAIL (laptop soak on 0fff60c); F4 FAIL (no Pi report); F5 FAIL (À REMPLIR); F6 FAIL (stale wheelhouse); F8 WARN 18; F9 HUMAN; rc 1 | ✓ as expected today |
| Shortened race-36h, real harness | `python -m jabuka.tools.soak --scenario race-36h --duration 900 --out <scratchpad>` | ~20 s wall, verdict PASS, sim_s 1322, faults 1, skipped 93 | ✗ (gap evidence) |
| Shortened run through freeze-check | scratch clone of HEAD + that report → `freeze-check --pre --skip-gate` | `[PASS] F3 portable : … PASS sur ee6f42709dc9, code identique à HEAD` | ✗ FAIL (gap confirmed) |
| Review repro CR-01 (F4) | `pytest test_repro.py -s` | `[PASS] F4 Pi : … paquet installé = src/jabuka à HEAD`, `freeze-check: ok` | ✗ FAIL (gap confirmed) |
| Review repro WR-01 (F3 head null) | `pytest test_repro2.py -s` | `[PASS] F3 portable : … paquet installé = src/jabuka à HEAD` after a deploy/pyproject change | ⚠️ warning confirmed |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and the plans declare none. The phase's runnable checks were run directly above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-02 | 04-01, 04-03, 04-04, 04-05, 04-06 | ~36 h unattended on the Pi 3B, verified by an accelerated fault-injected soak | ? NEEDS HUMAN (software ✓; freeze gate partial) | Harness and Pi path ready; the Pi run is human (10 Nov). The freeze gate can certify a shortened run (gap). REQUIREMENTS.md already marks it Complete, which is premature until the Pi soak runs |
| REL-03 | 04-02, 04-04, 04-06 | On-boat commissioning runbook for 12–13 Nov | ✓ SATISFIED (doc) | COMMISSIONING/FREEZE/SOAK/SPARE-SD; on-board execution human |

No orphaned requirements. REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and both are claimed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| scripts/freeze-check.sh | 153-176 | Report selection/judgement ignores sim_s and skipped faults (fail-open PASS for a shortened run) | 🛑 Blocker (gap 02-4) | F3/F4 can certify a ~20 s smoke run as the 36 h soak |
| scripts/freeze-check.sh | 198 | Fingerprint-only PASS also applies to F3 (head null) | ⚠️ Warning (review WR-01) | Contradicts FREEZE.md L87; weakens the WR-04 compensating control |
| src/jabuka/tools/soak.py | 781-787 vs 1353 | Signals during shutdown()/build_report() not deferred | ⚠️ Warning (review WR-02) | Report loss → re-run; never a false PASS |
| src/jabuka/soak/systemd.py / docs/SOAK.md | docstring / step 8 | "second Ctrl-C" wording stale (review IN-01) | ℹ️ Info | Hung cleanup only stoppable with kill -9 (bounded by timeouts) |
| docs/FREEZE.md | "Lock revu" line | `À REMPLIR` | ℹ️ Info | Intentional owner input, enforced by F5 |
| — | — | TBD/FIXME/XXX/TODO/HACK in 04-06 files | none | Scan clean |

### Human Verification Required

1. **Laptop race-36h on the final HEAD, full length.** Run without `--duration`. Leave no newer short race-36h run in `var/soak/` afterwards: until the gap is fixed, freeze-check reads the newest one.
2. **Pi 3B system-scope soak.** Rebuild the wheelhouse first: it must reproduce d42dac399a00… Then re-provision and install tmux. Run inside `tmux new -s soak`. Expect `source units`, no WARNING, verdict PASS and `cleanup.restarted true`. Afterwards reboot and check `is-active`.
3. **Pi budgets.** Fill in SOAK.md "Budgets Pi à confirmer".
4. **5 real power pulls.** Run logcheck after each one.
5. **Freeze on 11 Nov.** Follow FREEZE.md. freeze-check must exit 0, after the 02-4 fix.
6. **Spare SD.** Clone and boot it. The fingerprint must equal the original card's and the Pi report's `code.sha256`.
7. **12 Nov capture replay.** Run the rehearsal with `--capture`.
8. **On-board commissioning on 12–13 Nov.** The helm tablet must show wind and laylines at night.
9. **Runbook timings and SL proofreading.**

### Gaps Summary

**Previous gap 02-4 / CR-01 (F4 accepted shim, `--systemd user` or code-less Pi reports): CLOSED.** It is verified in code, the tests pass, and the repro cases are now permanent FAIL tests. The previous advisories WR-01 (unverified restart) and WR-02 (report lost to a signal during cleanup) are closed as specified as well.

**One gap remains on the same freeze truth (02-4, plus 06-1), with a new root cause.** freeze-check judges a race-36h report by its name, verdict, mode and code only. It never checks that the full scenario actually ran. I proved this end to end: a ~20-second `--scenario race-36h --duration 900` run from the real harness gets verdict PASS (93 of 94 faults "skipped") and turns F3 green on a clone of HEAD. The fixture shows the same for a system-scope Pi report on F4. Because the newest report wins, such a run made after the real soak replaces the evidence for ROADMAP SC1/SC3.

The fix is small:
1. In the helper, compare `sim_s` with `duration_s` of `race-36h.json` at HEAD, and reject any skip "after the end of the run". Map that to a new FAIL state `short` for F3 and F4.
2. Optionally, make the harness itself give a non-PASS verdict when `--duration` is shorter than the scenario.
3. Add two negative tests, and give the Frozen fixture realistic `sim_s` values.

It should land before the 11 Nov freeze. The 10 Nov Pi soak does not depend on it. Two cheap fixes can go in the same change:
- WR-01: restrict the L198 fingerprint-only PASS to aarch64, so F3 always applies the git rule as FREEZE.md says.
- WR-02 (optional): defer signals from `shutdown()` to `write_report`.

**If the owner decides to accept this instead** (the documented commands never pass `--duration`, and report.md shows `sim_s` and the skipped faults), add to this file's frontmatter:

```yaml
overrides:
  - must_have: "The 2026-11-11 freeze checker passes only with a clean tree, a green gate, laptop AND Pi race-36h soak reports PASS on code identical to HEAD"
    reason: "Documented procedures never use --duration; the owner checks sim_s ≈ 129600 and no 'after the end of the run' skips in each report.md before the freeze"
    accepted_by: "<owner>"
    accepted_at: "<ISO timestamp>"
```

---

_Verified: 2026-11-08T17:46:38Z_
_Verifier: Claude (gsd-verifier)_
