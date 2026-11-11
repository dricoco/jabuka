---
phase: quick-261111-flb
verified: 2026-11-11T11:31:09Z
status: human_needed
score: 11/11 must-haves verified
covered_files:
  - .planning/quick/261111-flb-menu-tactile-jabuka-touch-pour-l-ecran-m/261111-flb-PLAN.md
  - .planning/quick/261111-flb-menu-tactile-jabuka-touch-pour-l-ecran-m/261111-flb-SUMMARY.md
  - scripts/check.sh
  - tests/touch/conftest.py
  - tests/touch/test_actions.py
  - tests/touch/test_demo.py
  - tests/touch/test_fb.py
  - tests/touch/test_install_files.py
  - tests/touch/test_isolation.py
  - tests/touch/test_render_selftest.py
  - tests/touch/test_status.py
  - tests/touch/test_touchin.py
  - tests/touch/test_tracer.py
  - tests/touch/test_ui.py
  - touch/README.md
  - touch/install.sh
  - touch/jabuka-touch
  - touch/jabuka-touch.example.json
  - touch/jabuka-touch.service
  - touch/jabuka_touch/__init__.py
  - touch/jabuka_touch/__main__.py
  - touch/jabuka_touch/actions.py
  - touch/jabuka_touch/app.py
  - touch/jabuka_touch/calibrate.py
  - touch/jabuka_touch/config.py
  - touch/jabuka_touch/console.py
  - touch/jabuka_touch/demo.py
  - touch/jabuka_touch/demo_wind.py
  - touch/jabuka_touch/fb.py
  - touch/jabuka_touch/render.py
  - touch/jabuka_touch/selftest.py
  - touch/jabuka_touch/status.py
  - touch/jabuka_touch/touchin.py
  - touch/jabuka_touch/ui.py
  - touch/uninstall.sh
covered_digest: "v1:sha256:9813ab010ee80d3a49557b96a2053e54a5f262bdacee4050cd54806e05e281c3"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "On the Pi, run `cd touch && python3 -m jabuka_touch selftest --out /tmp/touch-png` with the Pi's system python (3.13, Pillow 11.1, numpy 2.2), then `sudo bash touch/install.sh`"
    expected: "« selftest : ok (22 écrans) »; jabuka-touch active; journal shows « écran : /dev/fbN 480x320 » and « toucher : /dev/input/eventN ouvert »; `sudo jabuka-touch status` prints 10 lines"
    why_human: "Only the laptop's Pillow 12.2 / numpy 2.5 were exercised; real fbtft and ADS7846 nodes exist only on the Pi"
  - test: "Look at the MHS35: home tiles, details, MÉTÉO / WI-FI, SYSTÈME; tap each corner and button; NUIT/JOUR"
    expected: "Tiles coloured and refreshed about once a second; taps land under the finger (otherwise `sudo jabuka-touch calibrate`); text readable in day and night palettes"
    why_human: "Visual legibility and the real panel calibration (rotate=90, swap) cannot be checked off-device"
  - test: "SYSTÈME -> REDÉMARRER SERVICES: let one confirmation auto-cancel after 8 s, then OUI"
    expected: "Confirmation disappears after 8 s without action; on OUI, jabuka-core and jabuka-ingest-fastnet restart, header shows the busy title"
    why_human: "Real systemd restart and on-screen timing"
  - test: "DÉMO -> LANCER LA DÉMO -> OUI with the operator `--awa-sign -1` override.conf in place; check `ls /run/systemd/system/*/zz-jabuka-touch-demo.conf`, `systemctl cat jabuka-ingest-fastnet | tail -5`, `/proc/<MainPID>/cmdline` of jabuka-core, `sha256sum /var/lib/jabuka/racepack/*` before/after, and the tablet at http://10.42.0.1"
    expected: "Two zz- drop-ins, --awa-sign -1 kept, core cmdline carries /var/lib/jabuka-demo and --clock sim, magenta DÉMO banner, simulated boat on the tablet, race pack hashes unchanged"
    why_human: "Drop-in merge order, ProtectSystem=strict + ReadWritePaths, runuser + venv demo_wind, systemd-run sim and pty ownership were proven only against fakes"
  - test: "MODE COURSE -> OUI; then start a demo again and reboot the Pi during it; finally `sudo jabuka-touch course` from SSH during a demo"
    expected: "Drop-ins, /var/lib/jabuka-demo and /run/jabuka-demo gone, core cmdline back to /var/lib/jabuka --clock gps; after the reboot the Pi is in race mode on the menu; the CLI ends the demo too"
    why_human: "Volatility of /run across a real reboot and real unit restarts"
  - test: "SYSTÈME -> TERMINAL -> OUI, log in with a USB keyboard, run `sudo jabuka-touch`; reboot and check `systemctl is-active jabuka-touch getty@tty1`; check `systemctl show jabuka-touch -p RestartMode`; kill -9 the menu once"
    expected: "getty login appears and the menu stops; `sudo jabuka-touch` brings the menu back; after boot jabuka-touch active / getty@tty1 inactive; RestartMode=direct; the menu returns after ~3 s without the getty"
    why_human: "Conflicts= resolution in the boot transaction and RestartMode/OnFailure semantics depend on the Pi's systemd"
  - test: "Optional: `sudo bash touch/uninstall.sh`, then reinstall"
    expected: "getty login back on tty1, /etc/jabuka-touch.json kept"
    why_human: "Real root install/uninstall (only DESTDIR dry runs are tested)"
---

# Quick 261111-flb: menu tactile jabuka-touch Verification Report

**Goal:** a touchscreen menu, jabuka-touch, for the Pi's MHS35 screen. It covers status at a glance, prerace + Wi-Fi, a demo/race mode through runtime systemd drop-ins (which never write to /var/lib/jabuka and always revert on reboot), and terminal/reboot/poweroff with confirmation. All code lives under touch/ + tests/touch/; the freeze means nothing under src/, deploy/ or pyproject.toml has changed since 7c61a53. It runs on the system python with apt Pillow/numpy, in an isolated unit, with install/uninstall, a French README and tests.
**Verified:** 2026-11-11T11:31:09Z
**Status:** human_needed (all automated checks pass; the real-screen/real-systemd trial on the Pi remains)
**Re-verification:** No (initial verification)

## Goal Achievement

### Observable Truths

| # | Truth (PLAN must_haves) | Status | Evidence |
|---|---|---|---|
| 1 | install.sh is idempotent and installs to /opt/jabuka-touch, the unit, the wrapper and the config only when absent, then reload/enable/restart. It never touches the boot partition, /opt/jabuka or the core units. uninstall.sh returns to race mode first, removes the menu and gives tty1 back | VERIFIED | `touch/install.sh` and `touch/uninstall.sh` were read. Tests: `test_install_dry_run_idempotent_and_uninstall` (DESTDIR, fake systemctl, edited config kept), `test_uninstall_runs_race_mode_first_when_a_demo_runs`, `test_uninstall_stops_when_race_mode_fails`, `test_install_refuses_without_pillow`, `test_scripts_syntax_and_no_boot_partition[*]` |
| 2 | System /usr/bin/python3 only. Nothing imports jabuka except demo_wind.py, which runs under the venv python as jabuka | VERIFIED | Unit `ExecStart=/usr/bin/python3 -s -m jabuka_touch run`. Grep finds the only `jabuka` import at `demo_wind.py:25`. The AST checks `test_no_jabuka_import_no_shell` and `test_checker_catches_violations` pass. `wind_argv` = `runuser -u jabuka -- /opt/jabuka/venv/bin/python -I …/demo_wind.py` (asserted in `test_start_demo_sequence`) |
| 3 | Framebuffer found by name fb_ili9486; sysfs geometry; native LE RGB565; render on view change only; changed row band only; KD_GRAPHICS while running, KD_TEXT restored on exit, SIGTERM, crash and ExecStopPost | VERIFIED | `test_fb.py` (find_fb_by_name, read_geometry, rgb565_values, partial_band_writes, band_write_offset_only, stride_padding_preserved, only_16_bpp). `app.step` renders only when `view != last_view`. `app.run` restores the console in a `finally` and the SIGTERM handler sets the stop flag. `test_app_crash_restores_console`. The unit has `ExecStopPost=… restore-console` |
| 4 | Ten coloured tiles about every 1 s with French text, read-only from /api/state and /api/nav (1 s timeout) plus short-timeout system commands on a background thread. A silent core gives red « cœur muet » | VERIFIED | `status.py` (`make_fetch` timeout 1.0, daemon collector thread). Tests: `test_collector_healthy_ten_items`, `test_collector_never_raises`, `test_core_down_five_red` and the per-tile level tests. The selftest PNGs `home.png` and `home-core-down.png` were inspected: ten tiles, five red « cœur muet » |
| 5 | Each of the nine risky actions shows an OUI/NON confirmation that cancels itself after 8 s. A 0.6 s tap guard applies. Every button is ≥ 80 px. No OUI lies under the centre of a button that opens a confirmation | VERIFIED | The `RISKY` set in ui.py has all nine ids. Tests: `test_confirmation_times_out`, `test_tap_guard_after_screen_change`, `test_buttons_big_and_inside` (all screens, demo on/off), `test_oui_never_under_a_confirmation_opening_button`. Visual check: OUI band y 150–240 (right half), and the openers on system/prep/home/demo sit outside it |
| 6 | Actions run as argv only from a whitelist, with timeouts, single-flight on a worker. The unit has no Requires/BindsTo/PartOf on the core, and sets Nice=10, MemoryMax, Restart=on-failure and Conflicts=getty@tty1 | VERIFIED | `actions.check_argv` (basename in ALLOWED plus system dirs), `Runner.run` (DEVNULL stdin, fixed env, no shell, never raises). Tests: `test_runner_refuses_non_whitelisted`, `test_runner_never_raises`, `test_worker_single_flight`, `test_unit_is_isolated_from_navigation`. The unit file was read |
| 7 | MÉTÉO / WI-FI: prerace (refused during a demo), live journal and last result, plus `jabuka-wifi ap/phone/status` | VERIFIED | Tests: `test_prerace_and_wifi_argv`, `test_prerace_refused_during_demo`, `test_wifi_phone_failure_lines`, `test_prep_journal_details_navigation_and_extra`, `test_successful_prerace_opens_the_journal`, `test_extra_queries_only_while_requested`. The `prep.png`, `journal.png` and `prep-wifi-fail.png` renders were inspected |
| 8 | DÉMO uses volatile `zz-jabuka-touch-demo.conf` drop-ins in /run that swap only the demo flags of the effective ExecStart. Data goes to /var/lib/jabuka-demo, and the sim runs in the transient jabuka-demo-sim unit. /var/lib/jabuka is only read. A DÉMO banner shows. MODE COURSE (or a reboot) restores race mode | VERIFIED (with fakes) | `demo.py` was read in full. Tests: `test_demo_argv_and_dropin_text`, `test_start_demo_sequence` (ordered calls; race-data tree hash unchanged), `test_demo_pack_copies_map_only_and_never_writes_race`, `test_operator_override_before_ours_keeps_awa_sign`, `test_stop_removes_only_ours_and_is_idempotent`, `test_wipe_guards`. The only writes in the package go to the demo root, the run dir, /run drop-ins and /etc/jabuka-touch.json, and `safe_wipe` refuses the race data dir. A fresh demo data dir falls back to Course A (`nav/course.py`), so course.json is not needed. Behaviour on a real systemd is a human item |
| 9 | A demo is never half-applied. The effective ExecStart is re-parsed after daemon-reload before any restart, and the main-process cmdline is checked after the restart. Any mismatch rolls back with « ÉCHEC démo ». When a unit is still inactive after 30 s, the screen gives the reboot hint | VERIFIED | Tests: `test_operator_dropin_after_ours_rolls_back_before_restart` (no systemd-run; the only restart is the rollback's; operator drop-in kept), `test_stale_main_process_rolls_back`, `test_failing_step_rolls_back`, `test_rollback_failure_shows_reboot_hint`, `test_stop_not_active_after_30s_says_reboot`, `test_demo_screen_reboot_hint_after_failed_race_mode`. `demo-reboot-hint.png` was inspected |
| 10 | TERMINAL sets KD_TEXT, then `systemctl --no-block start getty@tty1.service`. The wrapper provides `sudo jabuka-touch` / `course` / `calibrate`. Reboot and poweroff use systemctl | VERIFIED | `test_terminal_restores_text_console_first`, `test_system_action_argv`, `test_wrapper_usage`, `test_solve_calibration_recovers_default`, `test_save_calibration_keeps_other_keys`, `test_run_calibration_with_fake_display_and_reader`. The wrapper `touch/jabuka-touch` was read |
| 11 | The gate covers touch, the system-python selftest renders, the freeze diff is empty, and nothing is written to the Pi | VERIFIED | Commands run by the verifier: `.venv313/bin/pytest -q -rs tests/touch` gave 130 passed, 0 skipped. `/usr/bin/python3 -m jabuka_touch selftest --out <scratch>` gave « selftest : ok (22 écrans) », exit 0. `git diff --name-only 7c61a53 -- src deploy pyproject.toml` is empty (0 lines), and `git status --porcelain` on those paths plus touch, tests/touch and scripts is empty. `ruff check` / `format --check` are clean on touch and tests/touch. `scripts/check.sh` has ruff on `src tests touch`. The full gate was not re-run, as instructed |

**Score:** 11/11 truths verified (0 present but behaviour-unverified)

### Required Artifacts

| Artifact | Status | Details |
|---|---|---|
| touch/jabuka_touch/fb.py | VERIFIED | Contains fb_ili9486; pwrite band writes; tested |
| touch/jabuka_touch/touchin.py | VERIFIED | `=qqHHi`, median tap, debounce, calibration; tested |
| touch/jabuka_touch/console.py | VERIFIED | 0x4B3A KDSETMODE with an injectable ioctl; tested |
| touch/jabuka_touch/ui.py | VERIFIED | Pillow-free state machine with confirm, guard and view_key |
| touch/jabuka_touch/render.py | VERIFIED | DejaVu fonts; 22 real PNGs rendered and inspected |
| touch/jabuka_touch/actions.py | VERIFIED | Whitelist, Runner, Worker, getty@tty1.service |
| touch/jabuka_touch/status.py | VERIFIED | get_throttled and the other parsers, ten-item Collector |
| touch/jabuka_touch/demo.py | VERIFIED | zz-jabuka-touch-demo.conf, verification, rollback |
| touch/jabuka_touch/demo_wind.py | VERIFIED | write_wind; `test_demo_wind_script_writes_the_wind` runs it against real jabuka |
| touch/jabuka-touch.service | VERIFIED | Conflicts=getty@tty1.service, isolated |
| touch/install.sh | VERIFIED | /opt/jabuka-touch, DESTDIR/SYSTEMCTL/TOUCH_PYTHON overrides |
| touch/README.md | VERIFIED | French, contains `sudo jabuka-touch`, demo/soak/uninstall sections |
| scripts/check.sh | VERIFIED | ruff lines cover `touch` |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| app.py main loop | framebuffer | renderer → `fb.show` → `os.pwrite` of the changed band | WIRED (`test_tracer_restart_through_raw_events`, selftest tracer writes fb.raw) |
| TouchReader | `ui.on_tap` | `App.step`: `for tap in self.touch.poll(...)`, then `ui.on_tap` | WIRED |
| Confirmation OUI | `Worker.submit` → `Runner.run` | UI `submit=worker.submit`; registry from `build_registry` plus `demo_actions` | WIRED (tracer: FakeRunner.calls == [restart argv]) |
| Collector | /api/state and /api/nav | `status.make_fetch(cfg.core_url)` 1 s | WIRED |
| start_demo | /run/.../zz-jabuka-touch-demo.conf | `dropin_text` with `ReadWritePaths=-/var/lib/jabuka-demo`, daemon-reload, re-parse, restart, cmdline check | WIRED (`__main__.make_registry` passes `owner=demo.chown_jabuka`) |
| jabuka-touch.service | getty@tty1.service | `Conflicts=` plus TERMINAL `--no-block start` | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|---|---|---|---|---|
| home tiles | Snapshot.items | Collector: urllib on core API plus whitelisted system commands, /sys temp, statvfs | Yes (fake fetch in tests; real URL `http://127.0.0.1`) | FLOWING |
| demo banner / prerace refusal | demo flag | `Paths.demo_flag` = the core drop-in path written by start_demo | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Touch test suite | `.venv313/bin/pytest -q -rs tests/touch` | 130 passed in 1.55 s, no skips | PASS |
| Rendering + tracer under system python | `cd touch && /usr/bin/python3 -m jabuka_touch selftest --out <scratch>/st` | « selftest : ok (22 écrans) », rc 0, 22 PNG + calibration.png | PASS |
| Freeze guard | `git diff --name-only 7c61a53 -- src deploy pyproject.toml` | 0 lines | PASS |
| Lint | `.venv/bin/ruff check touch tests/touch` and `format --check` | clean / 27 files formatted | PASS |

### Probe Execution

No probes are declared for this quick task. Step 7c does not apply.

### Requirements Coverage

| Requirement | Source | Status | Evidence |
|---|---|---|---|
| HELM-05 | PLAN frontmatter | SATISFIED (code) | On-board status/diagnosis UI without a laptop (truths 4, 7) |
| REL-03 | PLAN frontmatter | SATISFIED (code) | Isolated unit; never takes navigation down; reboot returns to race mode (truths 6, 8, 9) |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| (none) | – | No TBD/FIXME/XXX/TODO/HACK in touch/ or tests/touch/; no shell=, os.system or os.popen | – | – |
| scripts/check.sh | 6-7 | Modified outside touch/ + tests/touch/ | Info | The plan sanctions it (files_modified) and it is outside the frozen set (src, deploy, pyproject). The only change is ruff covering `touch` |
| touch/jabuka_touch/demo.py | 502-504 | A pre-restart verification failure still runs the full `stop_demo`, which restarts jabuka-core and the ingest although they never left race mode | Info | Causes a brief, unnecessary navigation blip on a failed demo start (at the dock). Not a must-have violation; it could be narrowed later |

### Human Verification Required

See `human_verification` in the frontmatter (seven items, mapped from the SUMMARY's on-Pi trial steps). The main ones:

1. **Real screen and touch:** selftest on the Pi's python, install, then check tile legibility, tap accuracy and calibration.
2. **Real DÉMO on systemd:** drop-in merge with the operator override.conf, ProtectSystem/ReadWritePaths, runuser + demo_wind, sim pty ownership, race-pack hashes unchanged, and the tablet showing the boat.
3. **MODE COURSE / reboot during a demo:** comes back in race mode.
4. **TERMINAL / boot / crash:** the Conflicts= winner at boot, RestartMode=direct accepted, and recovery after a kill.

### Gaps Summary

There are no gaps. Every must-have is backed by passing tests or by command output the verifier ran (130 touch tests, system-python selftest rendering 22 screens, empty freeze diff, clean ruff). The remaining items need the real Pi hardware and systemd, as expected for this task.

---

_Verified: 2026-11-11T11:31:09Z_
_Verifier: Claude (gsd-verifier)_

## Essai sur le Pi réel (orchestrateur, 2026-11-11, écran MHS35)

Appuis injectés dans /dev/input/event0 (coordonnées passées par la calibration inverse), écran capturé depuis /dev/fb1.

- Selftest sur le Pi : « selftest : ok (22 écrans) » ; aucun service réel redémarré (FakeRunner, NRestarts=0).
- install.sh : jabuka-touch active, getty@tty1 inactive, RestartMode=direct accepté, journal « écran : /dev/fb1 480x320 », « toucher : /dev/input/event0 ouvert ».
- Accueil : 10 voyants lisibles et justes (bus muet, vent aucun, GPS, météo ICON-EU 09/18Z, Wi-Fi AP, alim, temp., disque, services).
- Confirmation : annulation automatique à 8 s constatée (deux essais trop lents annulés, aucune action lancée).
- Démo : demo_start ok ; drop-ins zz-jabuka-touch-demo.conf dans /run ; cmdline cœur = /var/lib/jabuka-demo/data --clock sim --gpsd 127.0.0.1:2948, ingest sur /run/jabuka-demo/fastnet-pty ; bandeau magenta DÉMO ; accueil tout vert (bus ok, vent LIVE 12 kn, route v1, GPS 3D) ; sha256 du racepack inchangé.
- MODE COURSE depuis l'écran : drop-ins, /var/lib/jabuka-demo et /run/jabuka-demo supprimés ; cœur revenu sur /var/lib/jabuka --clock gps ; racepack inchangé.
- Redémarrage pendant une démo : retour en mode course, menu affiché (jabuka-touch active / getty@tty1 inactive). Reste /var/lib/jabuka-demo sur disque (inutilisé, effacé au prochain lancement de démo).
- kill -9 du menu : relancé (nouveau PID, NRestarts=1), getty non démarré.
- Non testé : vrai doigt sur la dalle (précision de calibration), bouton TERMINAL + clavier USB, LANCER PRERACE, bascule Wi-Fi téléphone, épuisement de StartLimit (6 kills), désinstallation.
