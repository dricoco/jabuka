---
phase: quick-261111-flb
plan: 01
subsystem: ui
tags: [touchscreen, framebuffer, fbtft, ads7846, systemd, drop-in, demo, pillow]
requires:
  - phase: 04
    provides: jabuka-core /api/state and /api/nav, prerace, jabuka-wifi, jabuka-sim, soak drop-in precedent
provides:
  - jabuka-touch French touchscreen menu for the MHS35 (touch/ package, unit, wrapper, install/uninstall)
  - ten health tiles with details; MÉTÉO / WI-FI screen (prerace + journal, Wi-Fi switch)
  - DÉMO / MODE COURSE through verified volatile zz- drop-ins with rollback
  - touch calibration (sudo jabuka-touch calibrate)
affects: [deploy, commissioning, PI-SETUP]
actuals:
  tokens: 54000
  tasks: 3
  commits: 3
plan_head_before: 7c61a539099d9128276cd99ce93259e8b12f11ce
tech-stack:
  added: [system python3 + Pillow + numpy (apt) for the menu only; nothing added to the venvs or pyproject]
  patterns:
    - "Pillow-free modules + one render module, rendering tested via a system-python selftest subprocess"
    - "Volatile drop-ins built from the effective ExecStart, re-verified after daemon-reload and on /proc/<pid>/cmdline, rollback on mismatch"
key-files:
  created:
    - touch/jabuka_touch/{__init__,__main__,config,fb,touchin,console,ui,render,actions,status,calibrate,demo,demo_wind,app,selftest}.py
    - touch/jabuka-touch.service
    - touch/jabuka-touch
    - touch/jabuka-touch.example.json
    - touch/install.sh
    - touch/uninstall.sh
    - touch/README.md
    - tests/touch/{conftest,test_fb,test_touchin,test_ui,test_actions,test_status,test_demo,test_tracer,test_render_selftest,test_install_files,test_isolation}.py
  modified:
    - scripts/check.sh
key-decisions:
  - "jabuka-touch runs with the system python and never imports jabuka (except demo_wind.py, run by the venv python as jabuka via runuser -I)"
  - "Demo drop-ins named zz-jabuka-touch-demo.conf in /run; effective ExecStart re-parsed before any restart and main-process argv checked after, rollback otherwise"
  - "OUI/NON band at y 150-240 (OUI on the right half): no confirmation-opening button centre falls inside OUI on any screen (tested)"
requirements-completed: [HELM-05, REL-03]
duration: 50min
completed: 2026-11-11
status: complete
---

# Quick 261111-flb: menu tactile jabuka-touch Summary

**French touchscreen menu for the MHS35 (fb_ili9486 RGB565 band writes, ADS7846 raw evdev with median taps): ten live health tiles, prerace/journal/Wi-Fi, demo via verified volatile systemd drop-ins with rollback, confirmed system actions, calibration, isolated unit + idempotent installer.**

## Performance

- Duration: about 50 min (2026-11-11 10:37Z to 11:27Z, including the full gate on both venvs)
- Tasks: 3/3, 3 commits
- Files: 34 created, 1 modified (scripts/check.sh)

## Accomplishments

- **Task 1 (tracer)**: `touch/jabuka_touch` package. It finds the framebuffer by name in /proc/fb, reads its geometry from sysfs, writes RGB565 with `os.pwrite` of the changed row band only, and keeps stride padding. Touch input parses 24-byte input_events and takes the median sample with debounce and the default goodtft calibration plus swap. tty1 switches KD_GRAPHICS/KD_TEXT. The UI state machine has an 8 s confirmation timeout and a 0.6 s tap guard. The command runner uses a whitelist, argv lists only, no shell, and never raises. A single-flight worker runs actions. The tracer SYSTÈME -> REDÉMARRER SERVICES -> OUI runs `systemctl restart jabuka-ingest-fastnet.service jabuka-core.service` from raw events. `scripts/check.sh` ruff now covers `touch`.
- **Task 2**: ten tiles BUS, GPS, VENT, MÉTÉO, ROUTE, WI-FI, ALIM, TEMP., DISQUE, SERVICES. The data comes from the core API (1 s timeout; a silent core turns five tiles red « cœur muet ») and from system commands (2 s timeout each, every 5 s). Extra queries run only while a screen asks for them. The details screen is in. The MÉTÉO / WI-FI screen runs prerace (refused during a demo), opens the journal after a successful launch, shows the result (`prerace status`), and switches Wi-Fi. A failed phone switch shows the code, the last output line and the profile hint. Calibration uses three crosses and saves the result while keeping the other config keys.
- **Task 3**: `start_demo` / `stop_demo`, the DÉMO screen with a REDÉMARRER LE PI shortcut after a not-active failure, `race-mode` CLI, `demo_wind.py`, and the packaging: unit, wrapper, example config, install.sh, uninstall.sh and README.

## Task Commits

1. Task 1, tracer: `c79e6dd` feat(touch): menu tactile jabuka-touch, traceur écran + toucher + redémarrage des services
2. Task 2: `bd662c9` feat(touch): état d'un coup d'œil (10 voyants), écran météo et Wi-Fi (prerace, journal, bascule), calibration
3. Task 3: `6909e2f` feat(touch): démo et mode course par drop-ins volatils vérifiés, paquet d'installation, README

## Verification

- `tests/touch`: 130 tests pass on .venv and .venv313. `test_render_selftest` is NOT skipped on this laptop, because /usr/bin/python3 has Pillow 12.2.
- `cd touch && /usr/bin/python3 -m jabuka_touch selftest --out DIR` prints « selftest : ok (22 écrans) » and writes 22 screen PNGs plus calibration.png and home-core-down.png.
- Full gate: ruff check/format are clean on `src tests touch`. .venv313 passed 2224 with 4 skipped. On .venv (3.14), 2223 passed and 1 failed: the Playwright test `tests/ui/test_start_ui.py::test_start_zone_and_times_on_the_map` timed out a 15 s nav predicate. It passed when re-run alone, and it does not touch any changed code (src/ is unchanged). It is a timing flake, not the known i18n flaky test.
- Freeze guard: `git diff --name-only 7c61a53 -- src deploy pyproject.toml` and `git status --porcelain -- src deploy pyproject.toml` are both empty.
- Nothing was written to the Pi and nothing was installed anywhere.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Multiple ExecStart= lines in the ported soak parser**
- **Found during:** Task 3 (test_effective_execstart_refuses)
- **Issue:** The soak's `unit_execstart` replaces the list on each non-empty `ExecStart=`. Two ExecStart lines without a reset therefore went undetected, although systemd appends them.
- **Fix:** The port in `touch/jabuka_touch/demo.py` appends (`cur = [*cur, v]`), so two effective lines raise. src/jabuka/soak/systemd.py is unchanged because of the freeze, and its behaviour is fine for real units.
- **Commit:** 6909e2f

**2. [Rule 1 - Bug] `:g` number formatting truncated the epochs passed to demo_wind**
- **Found during:** Task 3 (test_start_demo_sequence)
- **Issue:** `f"{x:g}"` keeps 6 significant digits, so 1794592800 became 1.79459e+09 and the wind start was about 47 min off.
- **Fix:** Numbers are now formatted with `.15g`.
- **Commit:** 6909e2f

**3. [Rule 2] The prep screen had no room for the phone-switch failure lines**
- **Issue:** The planned 120-202 / 202-320 layout left too little room for the code, the last output line and the profile hint.
- **Fix:** The info band now runs 36-152 with wrapped 14 px text, and the buttons are 152-236 / 236-320 (84 px each, centres still outside OUI). The DÉMO screen lines also wrap.
- **Commit:** bd662c9, 6909e2f

**4. [Rule 2] Copying geofields into the demo pack**
- **Fix:** geofields.npz/json (map-derived distance-by-water fields) are copied when present, alongside the seven planned files. No weather file is ever copied.
- **Commit:** 6909e2f

**5. Minor additions**
- `install.sh` also installs README.md to /opt/jabuka-touch, which the unit's Documentation= points to.
- `config.write_json` is shared by `save` and the calibration.
- The wrapper's `--help` works without root.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-flb-01..09 mitigations implemented and tested).

## On-Pi trial steps (for the orchestrator)

1. **Copy and selftest (no install yet)**: rsync `touch/` to the Pi repo copy. Then run `sudo apt install python3-pil python3-numpy fonts-dejavu-core` if they are missing, and `cd touch && python3 -m jabuka_touch selftest --out /tmp/touch-png`. The expected output is « selftest : ok (22 écrans) ». Copy the PNGs back if you want to eyeball them.
2. **Install**: `sudo bash touch/install.sh`. Check `systemctl status jabuka-touch` (active) and `journalctl -u jabuka-touch -n 30`, which should show « écran : /dev/fbN 480x320 » and « toucher : /dev/input/eventN ouvert ». `sudo jabuka-touch status` should print 10 lines.
3. **Look at the screen**:
   - The header shows « JABUKA · COURSE » and the local HH:MM.
   - The ten tiles are coloured and update about every second. Tap the tiles to open the details, then RETOUR.
   - Check that the taps land where the finger touches. If they don't, run `sudo jabuka-touch calibrate` and confirm that /etc/jabuka-touch.json has new values.
4. **System**: SYSTÈME -> REDÉMARRER SERVICES -> confirmation screen (let it auto-cancel after 8 s once) -> OUI. Then check `systemctl status jabuka-core jabuka-ingest-fastnet` (just restarted) and the header « … Redémarrage des services ». NUIT/JOUR switches the palette.
5. **MÉTÉO / WI-FI**:
   - The info lines show the prerace result and the Wi-Fi mode with the client count.
   - JOURNAL shows `journalctl -u jabuka-prerace` and RÉSULTAT shows `prerace status`.
   - Optionally run LANCER PRERACE (the boat Wi-Fi drops for 10 to 30 min) and watch the journal screen open.
6. **Demo start**:
   - DÉMO -> LANCER LA DÉMO -> OUI. The progress lines should end on « Démo lancée … » and the header should turn into the magenta « DÉMO — bateau simulé » banner.
   - Then check `ls /run/systemd/system/*/zz-jabuka-touch-demo.conf` (two files) and `systemctl cat jabuka-ingest-fastnet | tail -5`. Any operator `--awa-sign -1` must still be there.
   - Check `systemctl status jabuka-demo-sim`, and `cat /proc/$(systemctl show -p MainPID --value jabuka-core)/cmdline | tr '\0' ' '`, which must show /var/lib/jabuka-demo and --clock sim.
   - The tablet at http://10.42.0.1 should show the simulated boat beating toward Plić Sestre.
   - `sha256sum /var/lib/jabuka/racepack/*` must be unchanged from before the demo.
7. **Demo stop**:
   - MODE COURSE -> OUI. The screen should show « Mode course : capteurs réels… », the banner disappears, and both drop-ins plus /var/lib/jabuka-demo and /run/jabuka-demo are gone.
   - The core cmdline is back to /var/lib/jabuka --clock gps.
   - Run the demo again and reboot during it: the Pi must come back in race mode on the menu.
   - From SSH, `sudo jabuka-touch course` must also end a demo.
8. **Terminal**: SYSTÈME -> TERMINAL -> OUI. The getty login appears on tty1 and the menu unit is inactive. Log in with a USB keyboard and run `sudo jabuka-touch`: the menu comes back and the tty1 session closes.
9. **Boot behaviour to verify (Conflicts / RestartMode)**:
   - After `sudo systemctl reboot` the MENU must appear, not the getty login. getty@tty1 (getty.target) and jabuka-touch (multi-user) are in the same boot transaction. Per systemd.unit(5), when neither is required, the conflicting unit (jabuka-touch) is started and getty@tty1 is dropped. Confirm with `systemctl is-active jabuka-touch getty@tty1`, which should give `active` / `inactive`.
   - Check that `systemctl show jabuka-touch -p RestartMode` gives `direct` (systemd >= 254 on Trixie). If that systemd rejects the key, `journalctl -b -u jabuka-touch` shows « Unknown key name 'RestartMode' ». The unit still works, but OnFailure would then fire on every crash.
   - Crash test: run `sudo kill -9 $(systemctl show -p MainPID --value jabuka-touch)` 1 or 2 times. The menu must come back after about 3 s with the getty NOT started. Six fast kills inside 120 s should then exhaust the start limit, and getty@tty1 (login) should appear (OnFailure).
   - Fallback if getty wins at boot: run `sudo systemctl disable getty@tty1.service`. The TERMINAL button still starts it explicitly. Note this in PI-SETUP.
10. **Uninstall check (optional)**: `sudo bash touch/uninstall.sh` should bring the getty login back on tty1 and keep /etc/jabuka-touch.json. Reinstall with `sudo bash touch/install.sh`.

## Self-Check: PASSED

- All created files exist under touch/ and tests/touch/.
- Commits c79e6dd, bd662c9 and 6909e2f are present on main. A measured `git rev-list --count 7c61a53..HEAD` gives 3.
