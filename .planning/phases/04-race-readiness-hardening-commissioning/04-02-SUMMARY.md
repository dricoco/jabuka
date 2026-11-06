---
phase: 04-race-readiness-hardening-commissioning
plan: 02
subsystem: commissioning/runbook-rehearsal-freeze
status: complete
tags: [commissioning, runbook, rehearsal, freeze, spare-sd, slovenian-card, REL-03]

requires:
  - phase: 01
    provides: "fastnet-probe EXIT_CODES/--file/--device, jabuka-replay (pty, --invert, --garbage-rate, --silence), jabuka-logcheck, jabuka-sim pty mode + fake gpsd + --fault bus-silent"
  - phase: 02
    provides: "course API (select/finish/confirm-sides with base_version), settings, manual wind, TABLET-SETUP"
  - phase: 03
    provides: "router on a race pack (route.version, pack.ok), GRIB-only wind source, ON RESTE, racepack-dryrun.sh, WEATHER-PACK Friday checklist, ROUTING operator section"
provides:
  - "docs/COMMISSIONING.md: French timed runbook for Thu 12 / Fri 13 Nov, nine sections, go/no-go + plans B/C, annex A (rehearsal result), annex B (every pending UAT / 03-06 / PI-SETUP item placed)"
  - "src/jabuka/tools/rehearsal.py: STEPS registry (34 steps, [Rn.x] ids), runner, synthetic-boat stack; python -m jabuka.tools.rehearsal"
  - "scripts/commissioning-rehearsal.sh: laptop dry run (quick ~10 s in the gate, all ~200 s)"
  - "scripts/freeze-check.sh: F1-F9 freeze checker (reads 04-01 report.json schema 1: verdict, scenario, host.machine, git.head, git.dirty)"
  - "docs/FREEZE.md (2026-11-11 checklist, config-only rule, emergency fix), docs/SPARE-SD.md (dd / rpi-clone, boot check, swap at sea, overlay try + rollback), docs/COMMISSIONING-SL.md (Slovenian skipper card)"
  - "deploy/PI-SETUP.md §7 points to SOAK, COMMISSIONING, SPARE-SD, FREEZE"
affects: [04-01, 04-03, phase-4-verification]

actuals:
  tokens: 37000
  tasks: 3
  commits: 6
plan_head_before: 76ed3ee40b08ce1909461311241dd856a9ca9171
commits: 6

tech-stack:
  added: []
  patterns:
    - "Runbook <-> code binding: [Rn.x] tags in the doc == rehearsal STEPS ids (both ways); probe exit-code table == EXIT_CODES + EXIT_ERROR; every tool command in a sh block parses with the tool's real argparse parser (builders, or parse_args intercepted inside main() for jabuka-route-bench / jabuka-prep land)"
    - "Rehearsal writes only through jabuka.common.atomicio; subprocess output drained into memory and saved to OUT/logs at the end (jabuka.tools stays clean for the receive-only static guard)"
    - "Static bus-silent windows in sim seconds, placed after §6/§7, one per degraded drill (GRIB-only, then manual wind)"

key-files:
  created:
    - docs/COMMISSIONING.md
    - docs/COMMISSIONING-SL.md
    - docs/FREEZE.md
    - docs/SPARE-SD.md
    - src/jabuka/tools/rehearsal.py
    - scripts/commissioning-rehearsal.sh
    - scripts/freeze-check.sh
    - tests/commissioning/test_rehearsal.py
    - tests/commissioning/test_runbook_docs.py
    - tests/commissioning/test_freeze_check.py
  modified:
    - deploy/PI-SETUP.md

decisions:
  - "The course drill (R7.drill) is select other template -> Finir ici at the last mark -> Finir ici cancelled (idx null) -> Côtés confirmés -> back, each with base_version: /api/course/undo only takes a token from an automatic rounding banner, so it cannot be part of a manual drill"
  - "MANUEL only shows while no live wind exists (LIVE outranks the stored entry), so R8.manual runs in its own bus-silent window (900+200 and 1300+400 sim s)"
  - "Rehearsal output never opened for writing in jabuka.tools: atomicio + in-memory logs (no allowlist change to the receive-only guard)"
  - "freeze-check F3/F4 ignore deploy/*.md when diffing the soak commit against HEAD (a doc fix after the soak does not invalidate it)"

metrics:
  duration: 55 min
  completed: 2026-11-06
---

# Phase 4 Plan 02: Commissioning runbook, rehearsal, freeze and spare SD Summary

One French runbook for 12–13 Nov whose every automatable step is tagged and rehearsed on the
laptop by `bash scripts/commissioning-rehearsal.sh` (replayed capture plus a synthetic boat
through the real ingest and core), tests that bind the runbook to the code, a F1–F9 freeze checker
for 2026-11-11, and the spare-SD and Slovenian skipper documents.

## What was built

- **Rehearsal** (`src/jabuka/tools/rehearsal.py`, `scripts/commissioning-rehearsal.sh`). 34
  registered steps, 22 automatic and 12 HUMAN, in runbook order. The quick run (the gate's dry
  run, ~10 s) covers §2 swap-wires drills on derived capture files, §3 capture, inventory,
  archive, replay through `jabuka-replay` → `jabuka-ingest-fastnet` → `jabuka-core` and logcheck,
  §4 instrument checks, §5 offline helm page, §7 course drill and §9 summary. The full run
  (`--steps all`, ~200 s) adds the live pty probe drills, §1 wheelhouse and soak lookup, §6 route
  adopted on the rehearsal pack, §8 GRIB-only, manual wind, ON RESTE and a kill -9 power pull
  with course/settings/manual-wind snapshot comparison and logcheck. `--capture` replays the
  boat's own capture on 12 Nov.
- **Runbook** (`docs/COMMISSIONING.md`, 450 lines). It has a two-day plan, the nine CONTEXT
  sections with time / action / tag / expected observation, the probe exit-code table, the
  AWA-sign drop-in, the go/no-go table (GO routing, GO laylines, GO GRIB/manual, Plan B
  OpenCPN via the relay, Plan C B&G + paper), annex A (full rehearsal result) and annex B
  (every 01-UAT, 02-UAT, 03-06 human item and PI-SETUP §4 item mapped to a moment on 11–13 Nov).
- **Freeze** (`docs/FREEZE.md`, `scripts/freeze-check.sh`): what is frozen, what configuration
  stays allowed, the 12 ordered steps, the `Lock revu : sha256 À REMPLIR` line, the
  `race-2026.1` emergency path; F1 clean tree, F2 gate, F3/F4 laptop and Pi race-36h soak PASS
  on code identical to HEAD, F5 lock hash, F6 wheelhouse = frozen source, F7 tag at HEAD, F8
  pending UAT WARN, F9 spare SD HUMAN.
- **Spare SD** (`docs/SPARE-SD.md`): dd with lsblk before/after and a bold wrong-device warning,
  cmp check, rpi-clone alternative, boot checks on the clone (services, logcheck, probe on a
  capture, code fingerprint), card swap at sea, optional overlay try with rollback (default OFF:
  it would lose course and settings at every reboot, CRSE-05).
- **Slovenian card** (`docs/COMMISSIONING-SL.md`, 56 lines): URL, big number, badges, ON RESTE,
  night and lock, grey/empty screen, glossary of VIREZ / Virement dans / ON RESTE / Ne pas virer /
  CAP À SUIVRE / Route mise à jour… / LIVE / MANUEL / GRIB / Marque suivante. Marked
  "brouillon, à relire par un locuteur slovène".

## Full rehearsal (`bash scripts/commissioning-rehearsal.sh --steps all`, 2026-11-06 20:15 UTC)

```text
[HUMAN] R1.packing §1 Sac de bord
[PASS] R1.wheelhouse §1 Wheelhouse complète : 19 paquets verrouillés, une roue chacun + jabuka
[HUMAN] R1.soak §1 Endurance race-36h : aucun rapport race-36h dans var/soak : bash scripts/soak.sh (docs/SOAK.md), puis le même essai sur le Pi
[HUMAN] R2.wiring §2 Prise sur le bus
[PASS] R2.silent §2 Bus muet → NO BYTES : attendu NO BYTES (code 2), obtenu code 2 (pty en direct)
[PASS] R2.swap §2 Fils inversés → croiser Blanc/Vert : attendu BYTES BUT NO VALID FRAMES (code 3), obtenu code 3 (pty en direct)
[PASS] R2.noisy §2 Bus bruité → NOISY : attendu NOISY (code 4), obtenu code 4 (pty en direct)
[PASS] R2.ok §2 Bon câblage → OK : attendu OK (code 0), obtenu code 0 (pty en direct) : OK: 102.6 frames/s, 54 channels
[HUMAN] R3.pages §3 Pages B&G pendant la capture
[PASS] R3.capture §3 Capture brute (fastnet-probe) : probe code 0 : OK: 102.6 frames/s, 54 channels ; fichiers ['capture.log', 'inventory.json']
[PASS] R3.inventory §3 Inventaire des canaux : 42 canaux décodés sur 54 vus : 0x0B Rudder Angle, ... 0xEB Speed Over Ground
[PASS] R3.archive §3 Archive de la capture : var/rehearsal/final-all2/archive/capture-20261106T201554Z.tar.gz (sha256 326f78d706fb…)
[PASS] R3.replay §3 Rejeu propre dans la chaîne : 42 chemins de l'inventaire servis par /api/state en 0.6 s
[PASS] R3.logcheck §3 Journaux du rejeu intacts : jabuka-logcheck code 0 : logcheck: OK (1 files, 0 torn tails)
[PASS] R4.variation §4 Cap magnétique + variation = cap vrai : cap bus 111.0°M + variation 4.7° = 115.7°T, nav 115.7°T, bateau 116.0°T (écarts 0.0° / 0.3°)
[PASS] R4.cog_hdg §4 COG contre cap vrai : COG 116.0°T, cap vrai 115.7°T : écart 0.3° (≤ 3°, sans courant)
[PASS] R4.awa_sign §4 Signe de l'AWA : tribord amures (TWA +45) → AWA +33°, TWA nav +45° (convention : + = vent sur tribord)
[PASS] R4.twd §4 TWD calculé contre scripté : TWD calculé 160.6°T contre 161°T scripté : écart 0.4° (≤ 5°) ; moitié instrument SKIP : le bateau de synthèse n'émet pas le canal TWD 0x6D (à comparer à bord, R4.underway)
[HUMAN] R4.dock §4 Contrôles au port / au moteur
[HUMAN] R4.underway §4 Contrôles sous voiles
[PASS] R5.offline §5 Page de barre sans internet : 8 ressources de la page, toutes servies par le Pi (aucun hôte externe)
[HUMAN] R5.setup §5 Réglage de la tablette
[PASS] R6.pack §6 Route adoptée sur le pack : route version 1 adoptée en 0.0 s (état ok, pack uniform ok)
[SKIP] R6.dryrun §6 Répétition du pack réel : hors ligne (--online lance scripts/racepack-dryrun.sh)
[HUMAN] R6.friday §6 Pack final du vendredi
[PASS] R7.drill §7 Changement de parcours : parcours B → Finir ici à Mulo → Finir ici annulé → Côtés confirmés → parcours A en 0.07 s (< 30 s), version 5
[HUMAN] R7.si §7 Parcours d'après les IC
[PASS] R8.gribonly §8 Bus muet → GRIB : bus muet → GRIB (TWD 160.6°T, 12.0 nd, alerte ["VENT GRIB (pas d'instruments)"]) → LIVE au retour du bus
[PASS] R8.manual §8 Vent manuel : GRIB → saisie 150°M 14 nd → MANUEL 154.7°T → effacé → GRIB
[PASS] R8.stay §8 ON RESTE : ON RESTE actif (bord stbd) → ANNULER ON RESTE : inactif
[PASS] R8.powerpull §8 Coupure d'alimentation : kill -9 ingest + cœur, redémarrage en 0.9 s : parcours, réglages et vent manuel identiques, bus de retour, jabuka-logcheck OK
[HUMAN] R8.boat §8 Exercices à bord
[HUMAN] R8.sdswap §8 Échange de carte SD
[PASS] R9.summary §9 Bilan go / no-go : 21 PASS, 0 FAIL, 1 SKIP, 11 HUMAN ; répétition sans échec (les HUMAN se font à bord)
jabuka-rehearsal: 22 PASS, 0 FAIL, 1 SKIP, 11 HUMAN en 202 s -> OK
exit 0
```

(HUMAN lines shortened here; the full expected observations are in the runbook and in
`results.json`.) The quick run in the gate: 16 PASS, 0 FAIL, 4 HUMAN in about 9 s.
`JABUKA_REHEARSAL_FULL=1 pytest tests/commissioning/test_rehearsal.py -k full`: 1 passed in
199.9 s.

## freeze-check on this repo (`bash scripts/freeze-check.sh --pre --skip-gate`, after the last commit)

```text
freeze-check: /home/drico/git/jabuka/.claude/worktrees/agent-a5994c7c46e95a927 @ 90c91c2155a8 (worktree-agent-a5994c7c46e95a927)
[PASS] F1 arbre de travail propre (fichiers suivis)
[SKIP] F2 porte non lancée (--skip-gate) : JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh
[FAIL] F3 pas de rapport race-36h portable (x86_64) dans var/soak : bash scripts/soak.sh (docs/SOAK.md)
[FAIL] F4 pas de rapport race-36h Pi (aarch64) dans var/soak : bash scripts/soak.sh (docs/SOAK.md)
[FAIL] F5 verrou non revu ou modifié : docs/FREEZE.md dit « À REMPLIR », sha256 du verrou d7236cb6dfee6bf0b57e823c96de98b75537d46aa5d17db6a113c100db597d80 (revue 01-UAT #8 / 02-UAT #10, puis écrire ce hash)
[FAIL] F6 roue jabuka différente de src/ : ['jabuka/common/clock.py', 'jabuka/core/course_api.py', 'jabuka/core/nav_api.py', 'jabuka/core/nav_service.py'] ; absents de la roue jabuka : ['jabuka/core/hardening.py', 'jabuka/tools/rehearsal.py', 'jabuka/web/static/lock-early.js', 'jabuka/web/static/route.js'] -> bash scripts/build-wheelhouse.sh depuis le tag
[SKIP] F7 tag race-2026 pas encore attendu (--pre)
[WARN] F8 18 éléments UAT en attente (result: [pending]) : à traiter à bord, docs/COMMISSIONING.md annexe B
[HUMAN] F9 carte SD de secours clonée depuis la version gelée et démarrée : docs/SPARE-SD.md
freeze-check: 4 item(s) FAIL
exit 1
```

The expected FAILs today: F3/F4 (no race-36h soak report yet; 04-01 writes them), F5 (lock
hash is `À REMPLIR` until the owner's review on 11 Nov), F6 (the wheelhouse in this worktree is a
copy of the main checkout's, built before Phase 3/4 code: it is rebuilt from the tag on 11 Nov).

## Gate

`JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh` on the final code (commit `90c91c2`): ruff check and format clean; Python 3.14 **1265 passed, 4 skipped** (423 s); Python 3.13 **1265 passed, 4 skipped** (418 s); `check: ok`, exit 0.

The brief's baseline was 1221 passed, 4 skipped. This plan adds 38 tests in `tests/commissioning/`: 37 run in the gate and 1 is skipped (`test_full_run` needs JABUKA_REHEARSAL_FULL=1). The two wheelhouse tests in `tests/deploy/test_lock.py` also run here instead of skipping, because this worktree holds the copied `deploy/wheelhouse/`. The first gate run on the Task 3 code failed one test: `tests/bus/test_no_write_path.py::test_no_write_constructs_in_ingest_or_tools`, the receive-only guard on `jabuka/tools` (see deviation 3). After the fix, the gate is green.

Long rehearsal: `JABUKA_REHEARSAL_FULL=1 .venv/bin/python -m pytest tests/commissioning/test_rehearsal.py -k full` passed in 199.9 s (Task 2 code). After the Task 3 rework, `bash scripts/commissioning-rehearsal.sh --steps all` was run again: exit 0 in 202 s (the output above).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Plan/API mismatch] R7.drill has no "undo"**
- **Found during:** Task 2
- **Issue:** the plan's drill was select B → finish at Mulo → undo → select A. `POST /api/course/undo`
  takes only the token of an automatic rounding banner (`UndoIn` forbids `base_version`, and a
  manual edit creates no banner), so it cannot be exercised by a manual drill.
- **Fix:** the drill is other template → "Finir ici" at the last mark → "Finir ici" cancelled
  (`idx: null`, the inverse of the finish) → "Côtés confirmés" → original template. Each call
  carries `base_version` and must return 200 with a newer version. Total time is printed and must
  be under 30 s.
- **Files modified:** src/jabuka/tools/rehearsal.py
- **Commit:** 2ef4f7a

**2. [Rule 1 - Bug in the plan's sequencing] Manual wind needs its own bus-silent window**
- **Found during:** Task 2
- **Issue:** with live wind the source stays `LIVE` (it outranks a stored manual entry), so
  "POST manual wind gives MANUEL" only holds while the bus is silent. One window could not serve
  both "GRIB then back to LIVE" and the manual drill.
- **Fix:** two static `--fault bus-silent` windows (900+200 and 1300+400 sim s at speed 10).
  R8.gribonly checks GRIB, then LIVE after window 1. R8.manual checks GRIB → MANUEL → DELETE → GRIB in
  window 2. R8.powerpull waits for window 2 to end, so the bus has to come back.
- **Commit:** 2ef4f7a

**3. [Rule 3 - Blocking] Receive-only static guard flagged the rehearsal's file writes**
- **Found during:** Task 3 (gate)
- **Issue:** `tests/bus/test_no_write_path.py` scans every `jabuka/tools/*.py` for write-mode
  `open()`, `write_text`, `os.open` with non-read-only flags and `os.O_RDWR`. The plan's
  `src/jabuka/tools/rehearsal.py` wrote logs, derived captures, the archive and `results.json`
  directly. It also reset the pty termios (O_RDWR + tcsetattr) before restarting the ingest.
- **Fix:** every output now goes through `jabuka.common.atomicio` (as `tools/probe.py` does).
  Subprocess output is drained into memory and saved to `OUT/logs/` at the end. The archive is
  built in memory (`tarfile.TarFile` + `gzip`). The termios reset is removed, because the ingest
  resets the tty speed itself (`serial_ro._quiesce_and_reset_speed`); the full rehearsal's power
  pull passes without it. The guard's allowlist is unchanged.
- **Files modified:** src/jabuka/tools/rehearsal.py
- **Commit:** 90c91c2

**4. [Rule 1 - Test bug] Doc command scan missed indented code blocks**
- **Found during:** Task 3
- **Issue:** the `sh` blocks inside numbered list items of SPARE-SD.md are indented, and the RED
  test's regex only matched blocks at column 0.
- **Fix:** the regex accepts leading whitespace.
- **Commit:** 90c91c2

### Other choices made without the owner (user AFK, auto-accepted)

- **Quick mode in R3.capture:** `fastnet-probe --file` writes no `capture.log` (only live mode
  does). The rehearsal copies `--capture` as `OUT/probe/capture.log`, so R3.archive packs the same
  two files as on the boat.
- **Extra step R8.sdswap** (HUMAN): plan §8 lists the at-sea card swap among the drills, so it got
  its own tag.
- **R1.soak / R1.wheelhouse not in quick mode:** this keeps the gate hermetic. A failed
  `var/soak` report left on a dev laptop must not fail the gate.
- **freeze-check F3/F4** diff `src deploy pyproject.toml` minus `deploy/*.md`. A doc fix after
  the soak does not void it.
- **jabuka-route-bench and jabuka-prep commands** are parsed by intercepting
  `ArgumentParser.parse_args` inside their `main()`. bench builds its parser in `main()`, and
  `jabuka-prep land` is dispatched to `jabuka.prep.land.main`. It is still the real parser, and
  nothing runs after parsing.
- **deploy/wheelhouse** was copied from the main checkout into this worktree (gitignored, not
  committed), so R1.wheelhouse could run. Its jabuka wheel predates Phase 3/4 code, which is why
  F6 FAILs here.
- **Synthetic-boat scenario:** 1.5 nm NNW of Plić Sestre, TWD 161°, 12 kn, starboard TWA +45
  (true heading 116°), sim start 2026-11-13T18:00Z, speed 10. The rehearsal pack is the 25 m land
  mask plus a uniform wind covering start − 1 day to + 3 days.
- **Timings:** the quick run takes ~9 s (budget 30–45 s) and the full run ~200 s ("about 4 min").
- **Doc tests** used to point at FREEZE.md and SPARE-SD.md through a temporary link allowlist in
  the Task 2 commit. Task 3 removed the allowlist once the files existed.
- **SPARE-SD rpi-clone source:** the maintained fork named is `geerlingguy/rpi-clone`. Check it
  before installing (human item).
- **COMMISSIONING-SL.md** was written by Claude, not a native speaker. Sailing terms such as
  "obrat", "orcaj" and "odpadi" need proofreading.

## Known Stubs

| File | Line | Reason |
|---|---|---|
| docs/FREEZE.md | `Lock revu : sha256 À REMPLIR` | Intentional: the owner writes the reviewed lock hash on 11 Nov (FREEZE step 4); freeze-check F5 FAILs until then and prints the hash to write. |

Not recorded in `.planning/WINDOWS.md`: that file is shared with the parallel 04-01 and review
worktrees, and this plan's brief limits writes to its own files. The orchestrator can add the
entry when it merges.

## Human items (end of phase, non-blocking)

| Item | Due | Source |
|---|---|---|
| Read docs/COMMISSIONING.md once; shift the 12 Nov timings to the real boat-access plan | before 2026-11-12 | 04-02 |
| Proofread docs/COMMISSIONING-SL.md with a Slovenian speaker (sailing terms) | before 2026-11-13 | 04-02 |
| Lock review (01-UAT #8, 02-UAT #10, 03-05 packages), write its sha256 on the `Lock revu` line of docs/FREEZE.md, tag `race-2026`, rebuild the wheelhouse from the tag, re-provision the Pi, `bash scripts/freeze-check.sh` | 2026-11-11 | FREEZE.md |
| Clone the spare SD (dd or rpi-clone; check the rpi-clone fork URL first) and boot-verify it | 2026-11-11 | SPARE-SD.md |
| Optional: try the overlay FS once and roll it back | by 2026-11-09 | SPARE-SD.md annex |
| Re-run `bash scripts/commissioning-rehearsal.sh --steps all` after the freeze (R1.soak should then PASS) and `--online` once with internet (R6.dryrun) | 2026-11-11 | 04-02 |
| Follow docs/COMMISSIONING.md on the boat; run the rehearsal against the boat capture (`--steps R3.capture,R3.inventory,R3.archive,R3.replay,R3.logcheck --capture var/commissioning/capture-12nov/capture.log`) | 2026-11-12 / 13 | 04-02 |
| Ask at registration whether any electronics or data-reception restriction applies (Pitfall 19) | 2026-11-13 | COMMISSIONING §7 |

## Self-Check: PASSED

All 10 created files and the modified `deploy/PI-SETUP.md` exist. The 6 task commits (`04001ef`, `4290aa8`, `94a1339`, `2ef4f7a`, `9ed8631`, `90c91c2`) are in the log from `76ed3ee`. The gate is green on both interpreters, and the full rehearsal and `freeze-check --pre --skip-gate` ran on this repository.
