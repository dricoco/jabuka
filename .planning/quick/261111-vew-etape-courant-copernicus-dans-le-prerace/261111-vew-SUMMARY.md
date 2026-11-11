---
phase: quick-261111-vew
plan: 01
subsystem: touch (Pi tooling: weather pack preparation)
status: complete
tags: [copernicus, current, prerace, touch-menu, installer]
requires: [deploy/prerace (frozen, model), jabuka-prep current/check, quick 261111-flb touch menu]
provides: [touch/jabuka-current, COURANT button, prerace -> current chaining, copernicusmarine venv install]
affects: [touch/install.sh, touch/uninstall.sh, touch menu MÉTÉO / WI-FI screen, docs/WEATHER-PACK.md]
tech-stack:
  added: [copernicusmarine 2.5.1 (separate venv /opt/copernicusmarine/venv, 64 exact pins)]
  patterns: [prerace-style detached systemd-run unit + EXIT/TERM trap, staging copy + identity-checked swap]
key-files:
  created:
    - touch/jabuka-current
    - touch/copernicusmarine-constraints.txt
    - tests/touch/test_current_script.py
    - tests/touch/test_current_menu.py
  modified:
    - touch/install.sh
    - touch/uninstall.sh
    - touch/README.md
    - touch/jabuka_touch/actions.py
    - touch/jabuka_touch/ui.py
    - touch/jabuka_touch/status.py
    - touch/jabuka_touch/config.py
    - touch/jabuka_touch/selftest.py
    - tests/touch/test_actions.py
    - tests/touch/test_status.py
    - tests/touch/test_ui.py
    - tests/touch/test_install_files.py
    - docs/WEATHER-PACK.md
decisions:
  - "jabuka-current run contract is exactly 0 OK / 2 failure (signals normalised to 2); launch refusals exit 1, usage errors 2"
  - "Live-pack identity (inode, sha256 of *.json sidecars, prerace-last.txt mtime) is recorded BEFORE the rsync to staging and again right after (abort if different); the pre-rsync identity is the one compared just before the swap"
  - "LANCER PRERACE schedules `jabuka-current --after-prerace <wall time before launch>`; the detached unit waits for prerace itself (up to 65 min) and runs only on a fresh prerace result with code 0 or 3"
  - "MÉTÉO detail mention priority: téléchargement en cours > présent (téléchargé DATE) > présent > absent; level unchanged"
metrics:
  duration: ~75 min
  completed: 2026-11-11
estimate:
  tokens: 120000
  tasks: 3
actuals:
  tokens: 26000
  tasks: 3
  commits: 3
plan_head_before: f4e216972540c3dc13aa2571722bc97e31f3e42a
commits: 3
---

# Phase quick-261111-vew Plan 01: Copernicus current step on the Pi Summary

`sudo jabuka-current` (or the confirmed COURANT tap, or automatically after LANCER PRERACE) downloads
the Copernicus Med surface current (uo/vo, race box, race window -6 h / +2 h = 2026-11-13T11:00:00 ->
2026-11-15T11:00:00 UTC) as root with `--credentials-file` (path only, never read), imports it as
`jabuka` into a staging copy of the pack, and swaps it in only when import + check pass, the current
covers the window and the live pack is provably unchanged since staging. Wi-Fi works exactly like
prerace (phone hotspot only without internet, always back to the AP from the trap).

## Tasks

| # | Name | Commit |
|---|------|--------|
| 1 | Tracer: COURANT button -> jabuka-current -> download -> staging import -> swap | 638b1b6 |
| 2 | Harden jabuka-current (Wi-Fi, refusals, --after-prerace, guards, identity, rollback) + installer + WEATHER-PACK note | 97fcb07 |
| 3 | Menu chaining prerace -> current, current info line, MÉTÉO detail, journal of both units, README, full gate | 69efa7c |

## What was built

- **touch/jabuka-current** (0755): `launch` (refuses: already running, prerace running without
  `--after-prerace`, demo drop-in, prep venv / copernicusmarine / credentials missing; bad args exit 2),
  `status` (en cours / en attente de la fin de prerace / last result), `_run` body:
  wait for prerace (optional) -> guard -> preflight -> window via the installed jabuka-prep
  (`python -I`, as jabuka) -> live pack present -> guard -> internet / phone hotspot -> download
  (`timeout 900`, `nice`) -> guard -> identity before rsync -> staging -> identity after rsync ->
  guard -> `jabuka-prep current` + `check` as jabuka -> coverage gate -> guard + identity -> swap with
  rollback -> restart jabuka-core. Result in `/var/lib/jabuka/current-last.txt` (courant / résultat /
  code / fenêtre / fichier / Wi-Fi / notes / coverage courant lines / journal tail on failure).
- **Installer**: installs `/usr/local/sbin/jabuka-current` and copernicusmarine 2.5.1 in
  `/opt/copernicusmarine/venv` (`--only-binary=:all: -c touch/copernicusmarine-constraints.txt`),
  skips when 2.5.1 is already there, non-fatal without internet / on pip failure. Uninstall removes
  the script, keeps the venv.
- **Menu**: COURANT button (x 125-240, confirmed), `current` action, LANCER PRERACE refused while
  jabuka-current is active and chains `jabuka-current --after-prerace <epoch>`, "Courant : ..." info
  line, MÉTÉO detail mention, journal follows both units ("Journal prerace + courant :").

## Verification

- `.venv313/bin/python -m pytest -q tests/touch`: 212 passed.
- `bash scripts/check.sh`: green (2306 passed, 4 skipped on each venv run; `check: ok`), no flaky rerun needed.
- `cd touch && /usr/bin/python3 -m jabuka_touch selftest --out DIR`: « selftest : ok (23 écrans) »;
  prep.png (three-button row) and confirm-current.png inspected: legible.
- Freeze guard: `git diff --name-only 7c61a53 -- src deploy pyproject.toml` and `git status --porcelain`
  on the same paths both empty before every commit.
- `git ls-files -s touch/jabuka-current`: mode 100755.
- Nothing written to the Pi, nothing installed anywhere, no credentials file read (laptop or Pi).

## Deviations from Plan

### Applied advisory (orchestrator extra instruction)

- **pack_identity before AND after the rsync** (Task 2): identity recorded before the staging
  copy and re-checked right after it (abort exit 2 « pack modifié pendant la copie de travail :
  pack inchangé, relancer COURANT »); the pre-rsync identity is used for the pre-swap comparison.
  Test: `test_pack_modified_during_the_staging_copy_aborts` (rsync stub mutates a live sidecar).

### Auto-fixed / minor

1. **[Rule 3 - Blocking] preflight message without "deploy/"**: the existing parametrized install
   test forbids "deploy/" on non-comment lines of touch scripts; the venv-missing message now says
   « provisionner le Pi avec la wheelhouse prep (PI-SETUP §8) ». (97fcb07)
2. **[Rule 2] selftest.py touched (not in the plan's file list)**: its tmp `Paths` now point
   `current_last` / `current_npz` into the selftest dir (otherwise it would read the real
   /var/lib/jabuka paths), a sample "current" entry was added to SAMPLE_EXTRA, and "current" was
   added to the rendered confirmation screens. (69efa7c)
3. When jabuka-current cannot be scheduled after prerace, the menu adds the script's last line
   (e.g. « identifiants Copernicus absents ») after « Courant non programmé (...) : bouton COURANT
   après prerace » so the reason is visible in the two-line action tail.
4. Extra tests beyond the behavior list: signal (SIGTERM) during the download -> exit 2, AP back,
   pack unchanged, « interrompu »; no live pack -> stop before Wi-Fi; incomplete wind (check 3) does
   not block the current (note only).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-vew-01..07, T-vew-SC all mitigated/accepted as planned).

## On-Pi trial steps (for the orchestrator)

Never display, cat, hash or copy `/root/.copernicusmarine/*` at any step.

1. **Install**: copy `touch/` to the Pi (e.g. `rsync -a touch/ drico@192.168.64.169:jabuka/touch/`).
   With internet (dock, or `sudo jabuka-wifi phone` first), run `sudo bash touch/install.sh`.
   Expect « installation de copernicusmarine 2.5.1 … » then « copernicusmarine 2.5.1 installé »
   (pip installs ~64 binary wheels; a few minutes on the Pi 3B). Check:
   `/opt/copernicusmarine/venv/bin/copernicusmarine --version` -> `copernicusmarine, version 2.5.1`;
   `ls -l /usr/local/sbin/jabuka-current` -> `-rwxr-xr-x root`. A second `sudo bash touch/install.sh`
   must print « copernicusmarine 2.5.1 déjà installé ». Back to the AP if switched
   (`sudo jabuka-wifi ap`).
2. **Credentials (once, interactive, by the user)**:
   `sudo /opt/copernicusmarine/venv/bin/copernicusmarine login` (or copy the laptop's credentials
   file into `/root/.copernicusmarine/` with mode 0600 WITHOUT displaying it). Verify only
   existence: `sudo test -f /root/.copernicusmarine/.copernicusmarine-credentials && echo present`.
3. **Real current run**: `sudo sha256sum /var/lib/jabuka/racepack/* > /tmp/pack-before.sha`, then
   `sudo jabuka-current`; follow `journalctl -fu jabuka-current` (watch `free -m` in another SSH).
   Then `sudo jabuka-current status`: `résultat : OK : courant installé, jabuka-core redémarré`,
   `code : 0`, `fenêtre : 2026-11-13T11:00:00 -> 2026-11-15T11:00:00 UTC …`, `fichier : Courant :
   49 échéances …`. `grep -i courant /var/lib/jabuka/racepack/coverage.txt` has no « désactivé » /
   « absent »; `ls /var/lib/jabuka/racepack/current.npz /var/lib/jabuka/racepack.prev` exist;
   `systemctl is-active jabuka-core` -> active; `iw dev wlan0 info` -> type AP (back on the AP).
4. **Menu**: MÉTÉO / WI-FI shows « Courant : OK : courant installé … · code 0 »; COURANT -> OUI
   launches and opens the journal (« Journal prerace + courant : »); the MÉTÉO tile details end with
   « courant : présent (téléchargé <date>) ».
5. **Failure trial**: with the phone sharing OFF (no internet on the Pi), record
   `sudo sha256sum /var/lib/jabuka/racepack/* > /tmp/pack-fail-before.sha`, then COURANT -> OUI.
   Expect result « ÉCHEC : pas d'internet par le partage du téléphone … » (or « aucun profil
   jabuka-phone » if none is saved), `code : 2`, the boat AP comes back, and
   `sudo sha256sum /var/lib/jabuka/racepack/* | diff - /tmp/pack-fail-before.sha` is empty.
6. **Optional chain**: LANCER PRERACE -> OUI: the journal shows prerace, then jabuka-current
   « en attente de la fin de prerace », then the current run (boat Wi-Fi drops twice); `sudo
   jabuka-current status` at the end: OK, code 0.

## Self-Check: PASSED

- FOUND: touch/jabuka-current, touch/copernicusmarine-constraints.txt, tests/touch/test_current_script.py, tests/touch/test_current_menu.py
- FOUND commits: 638b1b6, 97fcb07, 69efa7c
