---
phase: 04-race-readiness-hardening-commissioning
verified: 2026-11-07T14:31:12Z
status: gaps_found
score: 15/20 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-01-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-02-SUMMARY.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-PLAN.md", ".planning/phases/04-race-readiness-hardening-commissioning/04-03-SUMMARY.md", "deploy/PI-SETUP.md", "docs/COMMISSIONING-SL.md", "docs/COMMISSIONING.md", "docs/FREEZE.md", "docs/SOAK.md", "docs/SPARE-SD.md", "pyproject.toml", "scripts/bootstrap-dev.sh", "scripts/commissioning-rehearsal.sh", "scripts/freeze-check.sh", "scripts/soak.sh", "src/jabuka/common/atomicio.py", "src/jabuka/core/router_service.py", "src/jabuka/ingest/gpsd_client.py", "src/jabuka/ingest/rawlog.py", "src/jabuka/nav/course.py", "src/jabuka/nav/settings.py", "src/jabuka/route/advice.py", "src/jabuka/sim/synth.py", "src/jabuka/soak/__init__.py", "src/jabuka/soak/faults.py", "src/jabuka/soak/pack.py", "src/jabuka/soak/probes.py", "src/jabuka/soak/report.py", "src/jabuka/soak/scenario.py", "src/jabuka/soak/scenarios/ci.json", "src/jabuka/soak/scenarios/gpsclock-ci.json", "src/jabuka/soak/scenarios/race-36h.json", "src/jabuka/soak/scenarios/tracer.json", "src/jabuka/soak/supervisor.py", "src/jabuka/soak/systemd.py", "src/jabuka/soak/tablet.py", "src/jabuka/tools/rehearsal.py", "src/jabuka/tools/soak.py", "src/jabuka/web/static/i18n.js"]
covered_digest: "v1:sha256:512e1f43b431e67a76c1f97695ce4d9bd975c7b56aa7e865b29ee682306e5033"
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "The 2026-11-11 freeze checker passes only with a clean tree, a green gate, laptop AND Pi race-36h soak reports PASS on code identical to HEAD (04-02 truth 4; ROADMAP SC3 'Features are frozen on 2026-11-11')"
    status: partial
    reason: "A Pi soak run the documented way can never satisfy freeze-check F4. deploy/PI-SETUP.md §3 (and FREEZE.md step 8, which points to it) copies the repo to ~/jabuka with rsync --exclude '.git'. In --systemd system the harness runs from the installed wheel, so repo_root() is None and checkout() falls back to cwd ~/jabuka. rep.git_info() then returns {head: null, dirty: null} because ~/jabuka/.git does not exist. freeze-check.sh treats dirty null as dirty and prints FAIL F4 'fait sur un arbre dirty (git.dirty pas false)'. FREEZE.md steps 5 and 10 require F4 PASS, so the owner cannot complete the documented freeze on 11 Nov without improvising. 04-03 deviation 3 (checkout() fallback) was meant to fix exactly this, but it only works when the Pi copy is a git checkout. Reproduced: an rsync copy of deploy/ + pyproject.toml without .git gives git_info(cwd) = {'head': None, 'dirty': None}."
    artifacts:
      - path: "deploy/PI-SETUP.md"
        issue: "§3 rsync excludes .git, so ~/jabuka on the Pi is not a checkout"
      - path: "docs/SOAK.md"
        issue: "'Soak sur le Pi 3B' step 1 says ~/jabuka must be at the wheel's commit, but gives no way to make it a git checkout"
      - path: "src/jabuka/tools/soak.py"
        issue: "checkout()/git_info yield head/dirty null on the Pi under the documented install, with no warning at run start"
      - path: "scripts/freeze-check.sh"
        issue: "F4 can only FAIL for a Pi report produced per the docs"
    missing:
      - "Make the Pi soak report carry a usable code identity under the documented install. Options: (a) SOAK.md step 1 / FREEZE.md step 2 copy the repo to the Pi WITH .git (for example `rsync -a --exclude '.venv*' --exclude '__pycache__' ./ <user>@jabuka.local:jabuka/`, git installed on the Pi), or (b) better, also addresses review WR-03: record a sha256 manifest of the installed jabuka package in report.json and let F4 compare it to src/jabuka at HEAD instead of git.head/dirty"
      - "Have the harness print a loud warning (or refuse in system scope) when git.head would be null, so the owner learns before a 2-4 h Pi run, not at freeze-check"
      - "A test: a system-scope report produced from a non-git copy of the repo must be accepted by freeze-check F4 (or rejected up front by the harness)"
human_verification:
  - test: "Pi 3B system-scope soak (ROADMAP SC1): on the Pi, `cd ~/jabuka && sudo bash scripts/soak.sh --systemd system --python /opt/jabuka/venv/bin/python --scenario race-36h --speed 20 --logs-fs loop:512M` (docs/SOAK.md 'Soak sur le Pi 3B'), then scp the run dir to the laptop's var/soak/, reboot and check `systemctl cat jabuka-core | grep -c 50-jabuka-soak` = 0"
    expected: "Verdict PASS, tick ratio >= 0.95 (otherwise re-run at --speed 10), core/worker RSS <= 250 MB, no throttled/under-voltage bits, production units active with no soak drop-in after the reboot"
    why_human: "Needs the real Pi 3B hardware and its installed systemd units; the laptop only proves the user-scope backend and renders/verifies the system-scope drop-ins against a fake systemctl"
  - test: "Record the Pi RSS, temperature and throttling in docs/SOAK.md 'Budgets Pi à confirmer' (also closes 03-05 'Pi memory')"
    expected: "Table filled; the numbers fit the 1 GB Pi"
    why_human: "Hardware measurement"
  - test: "5 real power pulls on the Pi, each followed by jabuka-logcheck (PI-SETUP §4 j, 01-UAT #7)"
    expected: "Services back on their own each time, logcheck OK, course/settings intact"
    why_human: "Physical power interruption; the soak only simulates it with kill -9 of every group"
  - test: "Feature freeze on 2026-11-11 per docs/FREEZE.md: lock review and hash written on the `Lock revu : sha256 À REMPLIR` line, tag race-2026, wheelhouse rebuilt from the tag, Pi re-provisioned, `bash scripts/freeze-check.sh` all PASS except F8 WARN and F9 HUMAN (after the F4 gap above is fixed)"
    expected: "freeze-check exit 0; only configuration changes after this point"
    why_human: "Owner decisions (lock review) and a future-dated event; today F4 (no Pi report), F5 (hash not written) and F6 (stale jabuka wheel) FAIL as expected"
  - test: "Clone the spare SD per docs/SPARE-SD.md (dd or rpi-clone) and boot it (ROADMAP SC3)"
    expected: "jabuka-core and jabuka-ingest-fastnet active, jabuka-logcheck OK, fastnet-probe --file exits 0, same code fingerprint as the original card, tablet opens http://10.42.0.1"
    why_human: "Physical SD cards and Pi boot"
  - test: "12 Nov: replay the boat's real capture: `bash scripts/commissioning-rehearsal.sh --steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`"
    expected: "5 PASS lines; every decoded inventory path served by /api/state; logcheck OK"
    why_human: "The real Hercules bus capture only exists on 12 Nov"
  - test: "On-boat commissioning following docs/COMMISSIONING.md §2–§9 on 12–13 Nov (wiring and probe, capture with every B&G page cycled, true/magnetic and COG-vs-HDG checks, tablet setup, Friday pack, course drill under 30 s on the tablet, degraded drills, go/no-go)"
    expected: "The tablet at the helm shows live wind (or MANUEL / GRIB) and laylines to the first mark over the boat Wi-Fi, readable at night (ROADMAP SC4)"
    why_human: "Real boat, instruments, tablet and night conditions"
  - test: "Owner reads docs/COMMISSIONING.md once and shifts the 12 Nov timings to the real boat-access plan; a Slovenian speaker proofreads docs/COMMISSIONING-SL.md"
    expected: "Timings fit; card wording correct (sailing terms flagged in 04-02)"
    why_human: "Owner logistics and native-language review"
---

# Phase 4: Race Readiness — Hardening & Commissioning Verification Report

**Phase Goal:** The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Verified:** 2026-11-07T14:31:12Z (main 424671c; code identical to 0fff60c, later commits are docs/.planning only)
**Status:** gaps_found
**Re-verification:** No, initial verification

All the software the laptop can prove is in place and works. I re-ran on HEAD:
- the CI soak (19 faults, every CONTEXT kind, disk-full included) — PASS;
- the production GPS-clock soak — PASS;
- the full 34-step commissioning rehearsal — 23 PASS, 0 FAIL, 1 SKIP (offline), 10 HUMAN;
- 108 targeted phase-4 tests — all pass.

The orchestrator's race-36h laptop report (0fff60c, clean tree) is genuine. It shows 94 faults, all ok, 18 checks ok, and the leak fit enforced on a 12 sim-h segment (15.18 MB/36 h for a 20 MB budget).

One gap remains, on the freeze path. A Pi soak run exactly as documented records `git.head = null`, so `freeze-check` F4 can never pass and the 11 Nov freeze checklist cannot be completed as written. Everything that needs the Pi, the SD cards or the boat is listed under Human Verification.

## User Flow Coverage (MVP mode)

The ROADMAP `**Goal:**` line is not in user-story form (`user-story.validate` → valid=false), and unlike Phases 1–2 no phase-4 plan carries a restatement. This report uses the following restatement, which passes `user-story.validate` (valid=true): "As a boat owner racing the X35, I want to leave the Pi 3B running about 36 h unattended at night and commission it on the real boat on 12–13 Nov in one session by following a written runbook, so that the helm tablet shows trustworthy live wind and laylines for the whole race even when parts of the data chain fail." Consider writing a user story into ROADMAP.md.

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Prove 36 h of faults on the laptop | One command, real processes, every CONTEXT fault, budgets checked | `jabuka-soak` + race-36h report 20261107T133350Z: PASS, 94 faults (18 kinds), 59.97×, 0 land crossings in 303 routes | ✓ |
| Prove it on the Pi 3B | Same soak against the installed systemd units | `--systemd system` backend, drop-ins verified with systemd-analyze + fake systemctl; SOAK.md 9-step Pi procedure | ? human (hardware) |
| Freeze on 11 Nov | Checklist + checker green | FREEZE.md + freeze-check.sh F1–F9 work on this repo; **F4 cannot pass for a Pi report produced per PI-SETUP §3** | ✗ partial (gap) |
| Spare SD | Clone boots to the same state | SPARE-SD.md (dd / rpi-clone, boot checks, swap at sea, overlay rollback) | ? human |
| Commission on 12–13 Nov in one session | Timed French runbook, rehearsed | COMMISSIONING.md (453 lines, 9 sections, [Rn.x] tags bound to code), full rehearsal PASS on HEAD | ✓ doc / ? human on board |
| Tablet shows wind + laylines at night | LIVE/MANUEL/GRIB + laylines | Rehearsal R8.gribonly / R8.manual / R5.offline PASS; soak counts laylines on beat/run legs | ? human on board |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | 36 h ~60× soak **on the Pi 3B** with the listed faults; services recover, memory in budget, tablet live again | ? HUMAN (laptop equivalent ✓) | Laptop race-36h PASS on 0fff60c: bus 20 / GPS 4 / process 12 / power 8 / watchdog 2 faults, worst recoveries 0.54 / 0.04 / 3.09 / 0.55 / 25.9 s against 10/10/30/60/60. The Pi run is a human item due 2026-11-10 (CONTEXT). |
| SC2 | Runbook exists, dry-run against a replayed capture, covers wiring/swap, probe, inventory with pages cycled, true/mag + COG-vs-HDG, tablet, final GRIB + pack, spare SD, course drill < 30 s | ✓ VERIFIED | docs/COMMISSIONING.md §1–§9 + annexes. I re-ran `python -m jabuka.tools.rehearsal --steps all` on HEAD: R3.replay "42 chemins de l'inventaire servis par /api/state", R7.drill 0.03 s, exit 0. |
| SC3 | Frozen 2026-11-11; cloned spare SD boots to the same state; 12 Nov real capture replays cleanly; config-only changes | ? HUMAN + ✗ partial | FREEZE.md, freeze-check.sh, SPARE-SD.md and `--capture` replay all exist. The events are future-dated (human). The F4 path is broken for the documented Pi install (gap). |
| SC4 | On the boat by 12 Nov, the helm tablet shows live/manual/GRIB wind and laylines at night | ? HUMAN | Software from Phase 2. The rehearsal proves the GRIB → MANUEL → LIVE source switching through the real ingest + core. |
| 01-1 | One command runs the real stack under SimClock ~60×, seeded faults, exit 0/1, report.json + report.md | ✓ VERIFIED | `tools/soak.py` main/build_arg_parser/run_soak; `jabuka-soak` in pyproject and both venvs. Independent CI run: exit 0, 59.34×, report written. |
| 01-2 | After every fault the WS tablet sees wind + position within 10/30/60 s; new route after each restart; no route crosses land | ✓ VERIFIED | tablet.py `ws://…/ws` + `LandMask.validate_polyline`. Independent CI run: all 19 faults ok, 24 routes land-validated. Race-36h: 303 routes, 0 crossings. |
| 01-3 | Course/settings/manual wind survive clean pulls; a corrupt state file never stops the core (main/.bak or default + "illisible" alert) | ✓ VERIFIED | Race-36h persistence ok across 8 pulls (settings.json, course.json ×3, route.json corrupted). tests/nav/test_state_corruption.py passes. |
| 01-4 | RSS ≤ 250 MB, no leak trend, fd/threads stable, log retention, full log partition never stops live data | ✓ VERIFIED | Race-36h: core 77 / worker 148.7 MB, leak 15.18/3.89 MB per 36 h (enforced), fd +1, threads 0, log 44/128 MB. Independent CI run: disk-full ran on a 64M tmpfs, ok. |
| 01-5 | No unexpected traceback; no core error counter rises outside a fault window | ✓ VERIFIED | Race-36h tracebacks 0 (288 expected ENOSPC), error_counters 0. CI run: same. |
| 01-6 | GPS clock path end to end (late GPS time: gate blocked then ok; ±1 h step: holdover, re-anchor, route ok) | ✓ VERIFIED | Independent gpsclock-ci run: gps-loss blocked_seen=True, recovery 2.96 s, route 4.15 s; clock-jump jumps [0, 2], PASS. |
| 01-7 | CI soak in the normal gate on both interpreters; every soak-found defect has a regression test and a fix | ✓ VERIFIED | check.sh runs plain pytest with no marker exclusion. var/gate-0fff60c.log: 1534 passed ×2, `check: ok`. Five finding regression tests pass (state_corruption, follow_helm_faults, clock_step_back, gpsd_client_cancel, rawlog_full_disk). |
| 02-1 | One French timed runbook for 12/13 Nov with the nine CONTEXT sections, referencing UAT/human items | ✓ VERIFIED | 9 numbered sections in order, plan des deux journées, annex B mapping; test_runbook_docs passes. |
| 02-2 | commissioning-rehearsal.sh: PASS/FAIL/HUMAN per step, exit 0 only with no FAIL; `--capture` replays the boat capture | ✓ VERIFIED | Full run on HEAD exit 0 (above). The failure path (random bytes → exit 1) is covered by test_rehearsal, which passed. |
| 02-3 | Runbook cannot drift: exit-code table == EXIT_CODES, commands parse with the real parsers, [Rn.x] tags == STEPS, references exist | ✓ VERIFIED | tests/commissioning/test_runbook_docs.py + test_rehearsal.py pass (108-test targeted run). |
| 02-4 | Freeze = FREEZE.md + freeze-check.sh; passes only with clean tree, gate, laptop **and Pi** race-36h PASS on HEAD code, lock hash, wheelhouse, tag | ✗ PARTIAL | Checker logic correct (test_freeze_check passes). On this repo: F1 PASS, F3 PASS on 0fff60c; F4/F5/F6 FAIL as expected today. But a Pi report made per the docs has head/dirty null → F4 FAIL "arbre dirty" forever (see Gaps). |
| 02-5 | SPARE-SD.md: dd (primary) + rpi-clone, boot checks, card swap at sea, optional overlay with rollback | ✓ VERIFIED | Sections Méthode A/B, Vérification, Échange de carte en mer, overlay annex with `disable_overlayfs`; doc test binds the commands. |
| 03-1 | Pi `--systemd system` runs against the installed units via volatile /run drop-ins, always cleaned up | ? HUMAN (software ✓) | systemd.py render_dropins/cleanup. These tests pass: drop-ins parsed by the real parsers, systemd-analyze verify, kill/power-pull order, cleanup on exception, stale-drop-in refusal. Not runnable without the Pi. Review WR-01/WR-02 cover cleanup robustness. |
| 03-2 | Same backend end to end on the laptop in user scope; systemd (not the harness) restarts the core | ✓ VERIFIED | The user-scope e2e test in tests/soak/test_soak_systemd.py ran (not skipped) and passed in my targeted run. |
| 03-3 | Full race-36h on the laptop PASS, leak fit enforced, findings fixed, budgets in SOAK.md | ✓ VERIFIED | Report 20261107T133350Z: verdict PASS, mode shim, leak_slope ok=True "680 samples over 12.0 sim-h". SOAK.md "Résultats portable" present. |
| 03-4 | On the Pi the report records CPU temperature and throttling | ✓ VERIFIED (code) | probes.pi_probe (vcgencmd measure_temp/get_throttled), pi_summary → temp_c_max/throttled_flags_seen, report.md line; test_vcgencmd_parsing passes. Real values: human. |

**Score:** 15/20 truths verified (0 present-but-behavior-unverified; 1 partial gap; 4 human-only)

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/jabuka/tools/soak.py` | CLI, run orchestration | ✓ VERIFIED | 1281 lines; exports main/build_arg_parser/run_soak; independent runs PASS |
| `src/jabuka/soak/` (supervisor, tablet, probes, faults, pack, report, scenario, systemd) | Harness | ✓ VERIFIED | All wired; 18 fault kinds |
| `src/jabuka/soak/scenarios/{tracer,ci,gpsclock-ci,race-36h}.json` | Schedules | ✓ VERIFIED | race-36h: 94 faults incl. 60 random, quiet tail |
| `scripts/soak.sh` | Full-run wrapper | ✓ VERIFIED | --out confined to var/, --systemd pass-through, root check |
| `tests/soak/test_ci_soak.py` | CI soak in gate | ✓ VERIFIED | Asserts every FAULT_KIND ran or skipped with a host reason |
| `docs/SOAK.md` (≥140 lines) | Procedure + results | ✓ VERIFIED | 367 lines, Pi procedure, budgets table |
| `docs/COMMISSIONING.md` (≥250 lines) | Runbook | ✓ VERIFIED | 453 lines |
| `src/jabuka/tools/rehearsal.py` | STEPS + runner | ✓ VERIFIED | 34 steps; full run PASS on HEAD |
| `scripts/commissioning-rehearsal.sh`, `scripts/freeze-check.sh` | Dry run, freeze checker | ✓ VERIFIED | Both run on this repo |
| `docs/FREEZE.md`, `docs/SPARE-SD.md`, `docs/COMMISSIONING-SL.md` | Freeze, spare SD, skipper card | ✓ VERIFIED | 80 / 154 / 56 lines; PI-SETUP §7 points to all four docs |
| `src/jabuka/soak/systemd.py`, `tests/soak/test_soak_systemd.py` | systemd backend | ✓ VERIFIED | 862 lines; tests pass |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| soak/supervisor.py | deploy/systemd/*.service | Restart/RestartSec/WatchdogSec parsed, drift guard | ✓ WIRED | parse at L73–91; drift test passes |
| soak/faults.py | sim/synth.py | `--control` UDP toggles | ✓ WIRED | `h.control(kind, on)`; synth `--control`/`--clock-udp` passed by tools/soak.py L278–280 |
| soak/tablet.py | core `/ws` + route/landmask | websockets sync client, validate_polyline | ✓ WIRED | tools/soak.py L710, tablet.py L288 |
| tests/soak/test_ci_soak.py | jabuka.tools.soak | subprocess `-m jabuka.tools.soak --scenario ci / gpsclock-ci` | ✓ WIRED | L64 |
| test_runbook_docs.py | tools/probe.py EXIT_CODES | table equality | ✓ WIRED | test passes |
| test_rehearsal.py | COMMISSIONING.md | tags == STEPS both ways | ✓ WIRED | test passes |
| freeze-check.sh | var/soak/*/report.json | verdict/scenario/host.machine/git.head/dirty | ⚠️ PARTIAL | Reads the laptop report correctly (F3 PASS). The Pi report under the documented install has null git fields → F4 unreachable |
| soak/systemd.py | /run/systemd/system/<unit>.d/50-jabuka-soak.conf | volatile drop-in + cleanup | ✓ WIRED (laptop-testable part) | fake-systemctl tests; real run human |
| tools/soak.py | soak/systemd.py | `--systemd user|system` | ✓ WIRED | user scope e2e passes |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| report.json checks | recovery/RSS/leak | tablet WS messages + /proc samples (samples.csv) of the real processes | Yes (values vary per run: 72.8 vs 77 MB core RSS, etc.) | ✓ FLOWING |
| report.json git | head/dirty | /usr/bin/git in checkout() | Yes on laptop; **null on Pi per documented install** | ⚠️ STATIC on Pi (gap) |
| rehearsal R3.replay | inventory paths | jabuka-replay → ingest → core /api/state | Yes (42 paths) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| CI soak on HEAD | `.venv313/bin/python -m jabuka.tools.soak --scenario ci --out <scratch>` | exit 0, PASS, 19 faults ok, skipped [] (disk-full ran), 91.5 s wall | ✓ PASS |
| GPS-clock soak on HEAD | `... --scenario gpsclock-ci` | exit 0, PASS, blocked_seen True, jumps [0, 2] | ✓ PASS |
| Full rehearsal on HEAD | `.venv313/bin/python -m jabuka.tools.rehearsal --steps all --out <scratch>` | 23 PASS, 0 FAIL, 1 SKIP, 10 HUMAN, 201 s, exit 0 | ✓ PASS |
| Phase-4 targeted tests | `pytest tests/soak tests/commissioning <5 finding tests> tests/sim/test_synth_control.py` (CI soak deselected, run separately) | 108 passed, 1 skipped (full rehearsal, env-gated) | ✓ PASS |
| freeze-check on repo | `bash scripts/freeze-check.sh --pre --skip-gate` | F1 PASS, F3 PASS (0fff60c, code identical), F4/F5/F6 FAIL (expected today), F8 WARN 18 | ✓ as expected |
| Pi git identity | `git_info(cwd)` in an rsync copy without .git | `{'head': None, 'dirty': None}` | ✗ FAIL (gap) |
| Race-36h report authenticity | parse var/soak/20261107T133350Z-race-36h/report.json | schema 1, PASS, shim, x86_64, head 0fff60c, dirty False, 129640 sim s, 0 failed faults, all 18 checks ok | ✓ PASS |

### Probe Execution

Step 7c: no `scripts/*/tests/probe-*.sh` exist and the plans declare none. The phase's runnable checks (soak, rehearsal, freeze-check) were run directly above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| REL-02 | 04-01, 04-03 | ~36 h unattended on the Pi 3B, verified by an accelerated fault-injected soak | ? NEEDS HUMAN (laptop ✓) | Harness, CI soak in gate, laptop race-36h PASS; the Pi run is a human item (2026-11-10) |
| REL-03 | 04-02 | On-boat commissioning runbook for 12–13 Nov (wiring, probe, capture, true/mag, tablet, final GRIB, spare SD) | ✓ SATISFIED | COMMISSIONING.md + SPARE-SD.md + rehearsal; on-boat execution human |

No orphaned requirements: REQUIREMENTS.md maps only REL-02 and REL-03 to Phase 4, and both are claimed by plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| docs/FREEZE.md | 64 | `Lock revu : sha256 À REMPLIR` | ℹ️ Info | Intentional owner input on 11 Nov; freeze-check F5 enforces it |
| docs/SOAK.md | ~252 | "Pi 3B (à remplir)" column | ℹ️ Info | Intentional; filled after the Pi soak |
| — | — | TBD/FIXME/XXX/TODO in phase files | none | Scan clean |

Code review 04-REVIEW.md (advisory, not re-litigated here): WR-01 (system-scope cleanup marks done too early), WR-02 (tmpfs default on the Pi; SOAK.md says `--logs-fs loop:512M` but it is not enforced), WR-03 (Pi report certifies the checkout, not the installed wheel; related to the gap above), WR-04 (silent .bak fallback for course.json), WR-05 (recycled router pool not counted as a failure). WR-01/WR-02 affect the Pi soak run the owner will do on 10 Nov and are worth fixing together with the gap.

### Human Verification Required

1. **Pi 3B system-scope soak.** Run the race-36h scenario per SOAK.md "Soak sur le Pi 3B" (pass `--logs-fs loop:512M`). Expect PASS, tick ratio ≥ 0.95, RSS ≤ 250 MB, no throttling. Copy the report back, reboot, check that no `50-jabuka-soak` drop-in remains.
2. **Pi budgets.** Fill in "Budgets Pi à confirmer" in SOAK.md.
3. **5 real power pulls.** Follow PI-SETUP §4 j with logcheck after each pull.
4. **Freeze on 11 Nov.** Follow FREEZE.md. `freeze-check.sh` must end with exit 0, which needs the gap fixed first.
5. **Spare SD.** Clone it and boot-verify it per SPARE-SD.md.
6. **12 Nov capture replay.** Run the rehearsal with `--capture` on the boat's capture.
7. **On-boat commissioning on 12–13 Nov.** Follow COMMISSIONING.md. The helm tablet must show wind and laylines at night.
8. **Runbook and skipper card.** The owner reads the runbook timings; a Slovenian speaker proofreads the card.

(04-01's deferred check "read one CI report.md for plausibility": I read the race-36h and CI reports. The faults are spaced, and recoveries are listed in seconds. They look plausible.)

### Gaps Summary

There is one gap, on the freeze path, and it is cheap to fix.

The Pi soak must produce a report that `freeze-check` F4 accepts, because FREEZE.md steps 5 and 10 require F4 PASS. The documented install copies the repo to the Pi without `.git` (PI-SETUP §3 rsync `--exclude '.git'`; FREEZE.md step 8 reuses it). In `--systemd system` the harness therefore records `git: {head: null, dirty: null}`. F4 then reports FAIL "fait sur un arbre dirty", and no Pi report can ever make it pass. 04-03 tried to address this (deviation 3, `checkout()` falling back to cwd), but the fallback only helps when the copy is a git checkout.

There are two ways to fix it:
- **Minimal:** document copying the repo with `.git` for the Pi soak, and make the harness warn or refuse when the git identity is null.
- **Better, also closes review WR-03:** record a hash of the installed jabuka package in report.json, and have F4 compare it to `src/jabuka` at HEAD.

Everything else on the software side is verified by fresh runs on HEAD. The remaining phase outcomes (the Pi soak, the real power pulls, the freeze, the spare SD boot, and on-board commissioning) are inherently physical or future-dated. They are listed as human verification.

---

_Verified: 2026-11-07T14:31:12Z_
_Verifier: Claude (gsd-verifier)_
