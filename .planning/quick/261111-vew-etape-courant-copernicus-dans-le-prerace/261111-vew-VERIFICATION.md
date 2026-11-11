---
phase: quick-261111-vew
verified: 2026-11-11T23:55:00Z
status: human_needed
score: 8/8 must-haves verified (truth 8 scoped: freeze guard + ruff + tests/touch on both venvs; full scripts/check.sh not re-run, by orchestrator instruction)
covered_files:
  - .planning/quick/261111-vew-etape-courant-copernicus-dans-le-prerace/261111-vew-PLAN.md
  - .planning/quick/261111-vew-etape-courant-copernicus-dans-le-prerace/261111-vew-SUMMARY.md
  - docs/WEATHER-PACK.md
  - tests/touch/test_actions.py
  - tests/touch/test_current_menu.py
  - tests/touch/test_current_script.py
  - tests/touch/test_install_files.py
  - tests/touch/test_status.py
  - tests/touch/test_ui.py
  - touch/README.md
  - touch/copernicusmarine-constraints.txt
  - touch/install.sh
  - touch/jabuka-current
  - touch/jabuka_touch/actions.py
  - touch/jabuka_touch/config.py
  - touch/jabuka_touch/selftest.py
  - touch/jabuka_touch/status.py
  - touch/jabuka_touch/ui.py
  - touch/uninstall.sh
covered_digest: "v1:sha256:b67a3c68d94310ded6c9b3f7dde43e81d33aac1dfd1553eae40762a9dc280cac"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "On the Pi with internet: sudo bash touch/install.sh, then /opt/copernicusmarine/venv/bin/copernicusmarine --version; re-run install.sh"
    expected: "copernicusmarine, version 2.5.1 installed from binary wheels only (no compile); /usr/local/sbin/jabuka-current is 0755; the second run prints « copernicusmarine 2.5.1 déjà installé »; /opt/jabuka/venv and /opt/jabuka-prep/venv untouched"
    why_human: "Tests stub python -m venv and pip; real aarch64 wheel availability for the 64 pins and the Pi's pip behaviour can only be observed on the Pi"
  - test: "On the Pi after a one-time copernicusmarine login: record sha256sum of /var/lib/jabuka/racepack/*, run sudo jabuka-current, follow journalctl -fu jabuka-current, then sudo jabuka-current status"
    expected: "code 0, window 2026-11-13T11:00:00 -> 2026-11-15T11:00:00 UTC, « Courant : N échéances … », current.npz in the pack, coverage.txt has no « courant désactivé » / « Courant absent », racepack.prev present, jabuka-core active, Wi-Fi back on the AP; credentials file never displayed"
    why_human: "The real Copernicus server, the real credentials and the real NetCDF are stubbed in every test"
  - test: "Failure trial on the Pi: phone sharing OFF (no internet), COURANT -> OUI from the touch menu"
    expected: "ÉCHEC result with code 2, boat AP back, pack sha256sum unchanged"
    why_human: "Real nmcli/jabuka-wifi switching and systemd-run detachment are stubbed in tests"
  - test: "Touch menu on the 3.5-inch screen with real (long) prerace and current results already recorded: tap LANCER PRERACE -> OUI, and also try it with the credentials file absent"
    expected: "Prerace starts, the journal opens, jabuka-current shows « en attente de la fin de prerace » then runs. With credentials absent, the user can still find out that the current was NOT scheduled"
    why_human: "Measured with the real render fonts: with realistic result strings the 116 px info band holds 6 lines but the content is ~11 wrapped lines, so the action tail (« Courant non programmé (...) : bouton COURANT après prerace » + reason) is clipped on the prep screen, and tick() jumps to JOURNAL where a refused launch leaves no log line. The tests use short sample strings and do not see this"
---

# Quick task 261111-vew: Copernicus current step on the Pi — Verification Report

**Goal:** add a Copernicus current step to the Pi. This covers the `touch/jabuka-current` script, its install into a separate venv, a COURANT button in the menu, chaining after LANCER PRERACE, and a status display. It must never touch the frozen paths, must leave the pack untouched on any failure, must always put the Wi-Fi back on the AP, and must never read or print the credentials. The concurrency guards are: pack identity checked before and after the staging copy and before the swap, a prerace/demo guard at each check point, and a rollback if the swap fails.
**Verified:** 2026-11-11T23:55:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (PLAN must_haves) | Status | Evidence |
|---|---|---|---|
| 1 | `sudo jabuka-current` launches a detached unit (systemd-run --unit=jabuka-current --collect, RuntimeMaxSec=5400). It refuses with exit 1 when current or prerace is active, during a demo drop-in, or when the CM / prep / creds file is missing. `status` reports the last result, a running run, or a wait for prerace | ✓ VERIFIED | `touch/jabuka-current` launch() L104-136, status() L139-152, demo_active L77-83, preflight L86-101. Tests: test_launch_detaches_as_a_transient_unit, test_launch_refuses_* (8 cases), test_bad_arguments_exit_2[4], test_status_* (3), all pass |
| 2 | Downloads uo/vo of the dataset over bbox 14.75..16.55 / 42.55..44.25 for the jabuka-prep window -6 h/+2 h = 2026-11-13T11:00:00 -> 2026-11-15T11:00:00 UTC, as root with --credentials-file. The creds content is never read or printed | ✓ VERIFIED | L357-365 exact argv; race_window() L277-288 runs the real `DEFAULT_WINDOW_LOCAL`/`window_from_local` via `python -I` as jabuka. I checked it myself: start_utc 1794589200 - 21600 = 2026-11-13T11:00:00. test_happy_path_with_internet parses the exact argv (the real window code runs through the python wrapper → sys.executable). test_never_handles_secrets_beyond_the_path: CREDS appears only in the default/`[ -f ]`/`--credentials-file`. test_secret_never_leaks checks stdout, stderr, result, log and calls |
| 3 | Without internet it switches to the phone hotspot only when the jabuka-phone profile exists, and always switches back with `_switch ap` from the EXIT/TERM trap | ✓ VERIFIED (behavioral) | L326-350 (SWITCHED=1 before the switch); cleanup L246-264; traps L313-314. Tests: test_no_internet_switches_to_the_phone_and_back (last wifi call `_switch ap`, after the restart), test_no_internet_and_no_phone_profile, test_phone_without_internet_returns_to_the_ap, test_failure_on_signal_exits_2_and_returns_to_the_ap (real SIGTERM → trap → AP) |
| 4 | Import runs as jabuka into staging (current then check). The swap happens only on 0/3 + current.npz + clean coverage + no prerace/demo + unchanged identity. Every failure leaves the pack byte-identical, exits 2 and writes current-last.txt. If `mv STAGE PACK` fails, the pack is rolled back | ✓ VERIFIED (behavioral) | prep() L268-273 `runuser -u jabuka`; L389-411 code + coverage gate; pack_identity L187-195 (inode, sha256 of *.json, prerace-last mtime) taken before and after the rsync (L375-385) and re-checked before the swap (L416); rollback L420-427; cleanup normalises to 0/2. Tests: test_copernicus_failure_keeps_the_pack_and_the_wifi, test_import_or_coverage_failure_keeps_the_pack[4], test_a_prerace_that_ran_during_the_run_is_never_overwritten, test_pack_modified_during_the_staging_copy_aborts, test_swap_failure_puts_the_old_pack_back (byte-compare `_tree`) |
| 5 | Refuses to start, and never switches to the phone, while prerace is active at the check points (body start, before internet, after download, after staging, before swap) | ✓ VERIFIED | guard() L180-183 is called at "début" L319, "avant internet" L328, "après le téléchargement" L370, "après la copie de travail" L387, "avant l'installation" L415. Tests: test_body_refuses_while_prerace_runs, test_prerace_at_the_wifi_check_point_prevents_the_switch (no `_switch phone`), test_prerace_appearing_before_the_swap_aborts, test_demo_appearing_before_the_swap_aborts. The after-download and after-staging calls use the same tested function and are confirmed by reading the code |
| 6 | Menu: LANCER PRERACE launches prerace, then `jabuka-current --after-prerace <epoch>`, which continues only on a fresh 0/3. COURANT is confirmed and >= 80 px, with its centre outside OUI. Both are refused during a demo; PRERACE is refused while the current runs. Info line, MÉTÉO detail, and JOURNAL showing both units | ✓ VERIFIED | actions.py prerace() (CURRENT_UNIT check, since=int(wall()) before launch, second argv), current(); ui.py RISKY/CONFIRM_TEXTS/three-button row x 0-125/125-240/240-480, prep_lines current line; status.py _current_step, pack_current, journal `-u jabuka-current.service`; script wait_for_prerace L199-219. Tests: test_current_menu.py (26 cases incl. geometry, chaining argv, refusals, collector, prep lines, journal) and test_after_prerace_* (6). Selftest prep.png shows the 3-button row, which I inspected and found legible |
| 7 | install.sh installs jabuka-current 0755 and copernicusmarine 2.5.1 in /opt/copernicusmarine/venv (pinned, binary only). It skips the venv when already installed, prints a French message without internet or on a pip failure and continues, and never touches the race venvs | ✓ VERIFIED | install.sh L79-111 (`install_copernicusmarine \|\| true`, before daemon-reload); constraints file contains 64 `name==version` pins incl. copernicusmarine==2.5.1. No `/opt/jabuka/` or `jabuka-prep` on non-comment lines. Tests: test_install_current_and_copernicusmarine_venv (argv, 0755, byte-identical, second run skips, uninstall keeps venv, no opt/jabuka*), test_install_without_internet_still_installs_the_menu, test_install_pip_failure_is_not_fatal, test_constraints_pin_everything |
| 8 | Gate green and nothing changed under src/, deploy/ or pyproject.toml since 7c61a53 | ✓ VERIFIED (scoped) | `git diff --name-only 7c61a53 -- src deploy pyproject.toml` empty; `git status --porcelain` on the same paths empty. I ran `ruff check` + `ruff format --check` on touch and tests/touch (clean), and tests/touch on both .venv (3.14) and .venv313 (212 passed each). The full `scripts/check.sh` was not re-run (orchestrator instruction); SUMMARY claims it green |

**Score:** 8/8 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `touch/jabuka-current` | launch/status/_run, contains dataset id | ✓ VERIFIED | 447 lines, mode 100755 in git, dataset id on L37 |
| `touch/copernicusmarine-constraints.txt` | exact pins incl. copernicusmarine==2.5.1 | ✓ VERIFIED | 64 pins + header; test_constraints_pin_everything |
| `touch/install.sh` | jabuka-current + separate venv | ✓ VERIFIED | `/opt/copernicusmarine/venv`, non-fatal step |
| `touch/jabuka_touch/actions.py` | whitelisted jabuka-current, current action, `--after-prerace` | ✓ VERIFIED | ALLOWED + CURRENT + chaining |
| `touch/jabuka_touch/ui.py` | COURANT button, confirm text, current line | ✓ VERIFIED | |
| `touch/jabuka_touch/status.py` | current-last parsing, MÉTÉO mention, journal of both units | ✓ VERIFIED | contains `jabuka-current.service` via CURRENT_UNIT |
| `tests/touch/test_current_script.py` | stubbed-PATH tests | ✓ VERIFIED | 48 tests, real window code exercised |
| `tests/touch/test_current_menu.py` | menu tests | ✓ VERIFIED | 26 tests |
| `docs/WEATHER-PACK.md` | Pi note | ✓ VERIFIED | "On the Pi: `sudo jabuka-current`" subsection |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| ui.py COURANT | actions.current → /usr/local/sbin/jabuka-current | confirm → submit("current") → runner.run([CURRENT], 30) | ✓ WIRED (test_courant_then_oui_submits_current, test_current_action_argv) |
| actions.prerace | `jabuka-current --after-prerace <since>` | second argv after successful prerace | ✓ WIRED (test_prerace_chains_the_current_step) |
| jabuka-current _run | jabuka-prep current/check | `runuser -u jabuka -- nice -n 10 "$PREP" ... --out "$STAGE"` | ✓ WIRED |
| cleanup trap | jabuka-wifi `_switch ap` | `trap cleanup EXIT` + `trap 'exit 143' TERM INT HUP` | ✓ WIRED (signal test) |
| status.Collector | current-last.txt / current.npz | Paths.current_last / current_npz in `_current_step` from `_system` | ✓ WIRED (selftest also redirects these paths) |
| install.sh | pip install -c copernicusmarine-constraints.txt | `install_copernicusmarine` before daemon-reload | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|---|---|---|---|---|
| prep "Courant : …" line | extra["current"] | Collector._current_step → current-last.txt written by the script's write_result | Yes (same "courant :/résultat :/code :" keys, parse_current_last) | ✓ FLOWING |
| MÉTÉO detail mention | pack_current(item, self._current) | current_npz existence + parsed last result | Yes | ✓ FLOWING |
| Copernicus window | START/END | real jabuka.route.racepack via installed prep venv python | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Touch suite (3.13) | `.venv313/bin/pytest -q tests/touch` | 212 passed | ✓ PASS |
| Touch suite (3.14) | `.venv/bin/python -m pytest -q tests/touch` | 212 passed | ✓ PASS |
| Lint/format of touched trees | `.venv/bin/ruff check tests/touch touch && ruff format --check` | clean | ✓ PASS |
| Render selftest | `cd touch && /usr/bin/python3 -m jabuka_touch selftest --out <scratch>` | « selftest : ok (23 écrans) »; prep.png and confirm-current.png inspected | ✓ PASS |
| Freeze guard | `git diff --name-only 7c61a53 -- src deploy pyproject.toml` / `git status --porcelain` same paths | both empty | ✓ PASS |
| Window value | real `window_from_local(*DEFAULT_WINDOW_LOCAL)` − 21600 s | 2026-11-13T11:00:00 | ✓ PASS |
| Executable bit | `git ls-files -s touch/jabuka-current` | 100755 | ✓ PASS |

### Probe Execution

Not applicable (no probe scripts declared for this quick task).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| GRIB-03 | 261111-vew-PLAN | Prep tool imports a Copernicus Med current file into the race pack | ✓ SATISFIED (Pi-side path added) | jabuka-current drives the existing `jabuka-prep current` into staging + swap |
| ROUT-04 | 261111-vew-PLAN | Routing uses the current file when present | ✓ SATISFIED (supporting) | current.npz installed into the live pack + jabuka-core restart; router side unchanged (frozen src) |

### Test Quality Audit

| Test File | Active | Skipped | Circular | Assertion Level | Verdict |
|---|---|---|---|---|---|
| tests/touch/test_current_script.py | 48 | 0 | No (fake copernicusmarine/prep; real window code) | Behavioral (argv, call order, byte-level pack trees, result text) | OK |
| tests/touch/test_current_menu.py | 26 | 0 | No | Value/behavioral (exact argv lists, lines) | OK |
| tests/touch/test_install_files.py | 13 | 0 | No | Behavioral (DESTDIR install, logs, modes) | OK |

Disabled tests: 0. Circular patterns: 0. Insufficient assertions: 0.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| (all modified files) | — | TBD/FIXME/XXX/TODO/HACK | — | none found |
| touch/jabuka_touch/ui.py / render.py | prep_lines | Info band clipping | ⚠️ Warning | With real result strings (prerace + courant results each wrap to 2 lines), the 6-line band is full before the action tail, so « Courant non programmé (...) » is not visible on the prep screen. Not a must-have failure: the "Courant : …" status line is still shown. Listed as a human check |
| touch/jabuka-current | 420-427 | Signal between `mv PACK PREV` and `mv STAGE PACK` | ℹ️ Info | If SIGTERM (RuntimeMaxSec / stop) lands in the millisecond window between the two renames, the trap exits with INSTALLED=0 and removes the staging dir. The live pack is then left only as racepack.prev, which needs a manual `mv`. Frozen prerace has the same pattern. The probability is very low |

### Human Verification Required

1. **Pi install**: `sudo bash touch/install.sh` with internet. Expected: copernicusmarine 2.5.1 in /opt/copernicusmarine/venv from binary wheels, the second run prints « déjà installé », and the race venvs are untouched.
2. **Real current run**: after a one-time login, `sudo jabuka-current` and then `status`. Expected: code 0, the correct window, current.npz present, clean coverage, racepack.prev present, jabuka-core active, the AP back. Never display the credentials file.
3. **Failure trial**: COURANT -> OUI with no internet. Expected: code 2, the AP back, and the pack sha256 unchanged.
4. **Menu visibility of a not-scheduled current**: on the real screen, with long recorded results, LANCER PRERACE -> OUI, including with the credentials absent. Confirm the user can tell the current was not scheduled. Measured: the info band holds 6 lines and the realistic content is about 11, so the « Courant non programmé » tail is clipped.

### Gaps Summary

No blocking gaps. All 8 must-have truths are met in code and backed by passing behavioral tests. These cover the exact Copernicus argv, the real window code, the credentials never being read, Wi-Fi always back through the trap (including on a real SIGTERM), byte-identical packs on every failure path, a prerace that ran in the middle being detected and not overwritten, the swap rollback, the menu chaining and its refusals, and the installer degrading gracefully. The freeze guard is empty. The status is human_needed for two reasons: the real Pi behaviours (aarch64 wheels, the Copernicus server and credentials, nmcli Wi-Fi switching) are stubbed throughout, and one UX warning was measured: the "Courant non programmé" note is clipped on the prep screen.

---

_Verified: 2026-11-11T23:55:00Z_
_Verifier: Claude (gsd-verifier)_

## Essai sur le Pi réel (orchestrateur, 2026-11-11 ~23:40 CET)

- install.sh avec internet (Ethernet) : copernicusmarine 2.5.1 installé dans /opt/copernicusmarine/venv (roues binaires, pas de compilation) ; /usr/local/sbin/jabuka-current 0755 ; menu redémarré actif. Identifiants : présence vérifiée par `test -f` seulement.
- Vrai `sudo jabuka-current` : code 0 « OK : courant installé, jabuka-core redémarré » ; fenêtre 2026-11-13T11:00 -> 2026-11-15T11:00 UTC ; 49 échéances, grille 41x44 ; aucune ligne courant dans coverage.txt ; racepack.prev présent ; jabuka-core actif ; Wi-Fi resté sur jabuka-ap (internet par Ethernet) ; 23,9 s CPU ; mémoire disponible 601 Mo.
- Échec provoqué (binaire copernicusmarine renommé temporairement) : refus immédiat « copernicusmarine absent … », pack identique octet pour octet (sha256 -c), jabuka-core actif, Wi-Fi sur l'AP ; binaire remis (version 2.5.1).
- Menu : écran MÉTÉO / WI-FI montre « Courant : OK : courant installé … code 0 » et le bouton COURANT ; voyant MÉTÉO ICON-EU 11/12Z.
- Non testé sur le Pi : échec réseau réel avec bascule téléphone, enchaînement LANCER PRERACE -> courant, note « courant non programmé » tronquée (avertissement du vérificateur, à revoir après la course).
