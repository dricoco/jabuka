---
phase: quick-261109-vdo
plan: 01
subsystem: deploy
status: complete
tags: [deploy, weather, raspberry-pi, wheelhouse, offline, wifi]
requires: [deploy/jabuka-wifi (aa61b90), jabuka-prep CLI (Phase 3)]
provides: [/opt/jabuka-prep/venv (provision step g2), /usr/local/sbin/prerace, deploy/prep.lock]
affects: [scripts/build-wheelhouse.sh, deploy/provision.sh, deploy/PI-SETUP.md, docs/WEATHER-PACK.md]
tech-stack:
  added: []
  patterns: [hash-locked side venv (Plan B pattern), transient systemd unit with EXIT/TERM trap, staging + rename swap]
key-files:
  created: [deploy/prep.in, deploy/prep.lock, deploy/prerace, tests/deploy/test_prerace.py]
  modified: [scripts/build-wheelhouse.sh, deploy/provision.sh, tests/deploy/test_lock.py, tests/deploy/test_provisioning_files.py, deploy/PI-SETUP.md, docs/WEATHER-PACK.md]
decisions:
  - "Pi weather prep lives in its own hash-locked venv /opt/jabuka-prep/venv (two pip --require-hashes installs + jabuka wheel --no-deps); the app venv is never named"
  - "sudo prerace runs as transient unit jabuka-prerace (RuntimeMaxSec=3600), builds in racepack.new, installs on 0/3 by rename swap, always returns to the AP via the EXIT/TERM trap"
  - "Docs and prerace always pass --cache /var/lib/jabuka/cache/prep (default cache path is cwd-relative and unwritable for jabuka)"
metrics:
  duration: ~25 min
  completed: 2026-11-09
actuals:
  tokens: 16700
  tasks: 3
  commits: 3
plan_head_before: aa61b907903720df5b130284ccb7263e5d889c42
---

# Phase quick-261109-vdo Plan 01: Weather prep on the Pi as an emergency fallback (sudo prerace) Summary

The Pi now gets an offline, hash-locked `/opt/jabuka-prep/venv` (pygrib, shapely, netCDF4) from `deploy/wheelhouse/prep`. One root command, `sudo prerace`, uses the phone hotspot only when there is no internet. It builds wind, waves and a check into a staging copy, swaps it in, restarts jabuka-core and always returns to the boat AP. The app venv, `src/` and the existing locks are untouched.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 16649a6 | feat(deploy): venv météo de secours /opt/jabuka-prep sur le Pi (prep.lock, wheelhouse/prep) |
| 2 | f1f06e1 | feat(deploy): sudo prerace prépare la météo sur le Pi (partage téléphone, pack en staging, retour AP) |
| 3 | 7ba5b52 | docs: météo sur le Pi en secours, sudo prerace (PI-SETUP §8, WEATHER-PACK) |

## Generated prep.lock package set

`certifi, cftime, netcdf4, numpy, packaging, pygrib, pyproj, shapely` (8 packages). This is **identical to the planning-time trial**.

- numpy 2.5.4 is the only package shared with `requirements.lock`. Its version and hashes are identical (asserted by `test_prep_lock_shares_packages_identically_with_the_app_lock`).
- Lock header: `uv pip compile deploy/prep.in -c deploy/requirements.lock --python-platform aarch64-unknown-linux-gnu --python-version 3.13 --generate-hashes -o deploy/prep.lock`.

## build-wheelhouse output (run WITHOUT --relock)

```
build-wheelhouse: locking deploy/prep.in -> deploy/prep.lock (aarch64, cp313, hashes)
Resolved 8 packages in 248ms
...
build-wheelhouse: deploy/wheelhouse: 19 locked packages, 20 wheels
build-wheelhouse: deploy/wheelhouse/fastnet2ip: 11 locked packages, 11 wheels
e9b54de7...  certifi-2026.10.23-py3-none-any.whl
2d1e68e1...  cftime-1.6.6.1-cp311-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl
544316a1...  netcdf4-1.7.5.1.post1-cp311-abi3-manylinux_2_28_aarch64.whl
1c2e71b0...  numpy-2.5.4-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl
d7193f7c...  packaging-26.3-py3-none-any.whl
f16d805a...  pygrib-2.1.8-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.whl
8e01abce...  pyproj-3.8.0-cp313-cp313-manylinux_2_28_aarch64.whl
4ed79beb...  shapely-2.2.0-cp313-cp313-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl
build-wheelhouse: deploy/wheelhouse/prep: 8 locked packages, 8 wheels
build-wheelhouse: simulating the offline --require-hashes install of deploy/requirements.lock
build-wheelhouse: simulating the offline --require-hashes install of deploy/fastnet2ip.lock
build-wheelhouse: simulating the offline --require-hashes install of deploy/prep.lock
build-wheelhouse: simulating the prep venv (app lock + prep lock) offline --require-hashes install
build-wheelhouse: ok
```

`deploy/requirements.lock` and `deploy/fastnet2ip.lock` were checked before and after the run with sha256sum and `git diff --exit-code`, and are byte-identical. The gitignored jabuka wheel was rebuilt from unchanged src, as expected.

## Provision dry-run, step g2

```
== g2. emergency weather prep venv /opt/jabuka-prep/venv (separate from the app venv)
+ install -m 0644 /home/drico/git/jabuka/deploy/prep.lock /opt/jabuka/prep.lock
+ python3 -m venv /opt/jabuka-prep/venv
+ /opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse --require-hashes -r /opt/jabuka/requirements.lock
+ /opt/jabuka-prep/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse/prep --require-hashes -r /opt/jabuka/prep.lock
+ /opt/jabuka-prep/venv/bin/pip install --no-index --no-deps --force-reinstall /opt/jabuka/wheelhouse/jabuka-0.1.0-py3-none-any.whl
+ ln -sfn /opt/jabuka-prep/venv/bin/jabuka-prep /usr/local/bin/jabuka-prep-pi
+ install -m 0755 /home/drico/git/jabuka/deploy/prerace /usr/local/sbin/prerace

== h. systemd units and drop-ins
```

The last `+ ` line of the dry-run is still `+ nmcli connection up jabuka-ap`.

## Tests

- `tests/deploy/test_prerace.py`: 20 passed. These cover the 12 planned behaviours, plus bash syntax, the executable bit, no PSK handling, unknown argument, a missing organiser file, an organiser `_run`, and status while a run is active. The tests were written first and were RED (19 failed) before the script existed.
- `tests/deploy/test_lock.py`: 4 new prep tests (prep.in = pyproject `prep` extra minus osmium; lock hashed/pinned/constrained/Pi/exact set; shared packages identical; prep wheelhouse).
- `tests/deploy/test_provisioning_files.py`: g2 tokens, ordering (prep pip and prerace between fastnet2ip and the systemd enable, AP still last), `test_prep_venv_is_hash_locked_and_separate`, `test_prep_step_warns_when_wheelhouse_prep_absent`.
- Final gate: `.venv313/bin/pytest -q tests/deploy tests/commissioning` gave **164 passed, 1 skipped**. `tests/deploy` alone: 97 passed. `ruff check tests/deploy` is clean, `ruff format --check` is clean, and `bash -n` passes on provision.sh, prerace and build-wheelhouse.sh.
- `git diff --quiet aa61b90 -- src deploy/systemd deploy/requirements.lock deploy/fastnet2ip.lock docs/SOAK.md cad stl hardware` passes, so these paths are unchanged.

## Deviations from Plan

Minor, no rule-4 items:

1. **build-wheelhouse `--help` range.** It is now `sed -n '2,15p'`, so it prints the whole header including the last "system python3's pip" line, which the old `2,12p` already cut off.
2. **`deploy/prep.in` header.** It is 4 comment lines instead of 3, to fit the required content.
3. **[Rule 2] prerace `systemctl restart jabuka-core` failure.** A failure is recorded as a note (`ÉCHEC du redémarrage de jabuka-core : sudo systemctl restart jabuka-core`) instead of aborting under `set -e`. `INSTALLED=1` is set right after the `mv` swap rather than after the chown. This way the result file never claims "old pack kept" when the swap already happened.
4. **prerace help without root.** `prerace -h/--help` works without root (harmless). Every real subcommand still requires root.
5. **Extra tests.** Added tests beyond the plan: no PSK handling, unknown argument, an organiser `_run`, and status while a run is active.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model. All `mitigate` items are implemented:
- jabuka-prep runs via `runuser -u jabuka -- nice -n 10`.
- SWITCHED is set before the switch, and the EXIT plus TERM/INT/HUP trap returns to the AP. RuntimeMaxSec=3600.
- The pack is built in staging and installed by rename swap with exactly one `.prev`. Derived paths use `${DATA:?}`.
- prerace never handles the PSK (a test asserts this).
- The unit name is fixed and a second launch is refused while one is active. The cache is purged after an install.

## Notes for the orchestrator

- (a) Copy `deploy/wheelhouse/` **including `prep/`** (8 wheels) to the Pi, then re-run `sudo deploy/provision.sh` so step g2 creates `/opt/jabuka-prep/venv` and installs `/usr/local/sbin/prerace`.
- (b) This change touches `deploy/` non-.md files (provision.sh, prerace, prep.in, prep.lock) and `scripts/build-wheelhouse.sh`. The freeze-check F3 git rule will flag a laptop soak report older than these commits.
- (c) At the dock, re-check the Pi 3's memory and runtime of a real `sudo prerace`. ICON-EU decoding on a Cortex-A53 over a phone link may approach the RuntimeMaxSec=3600 safety cap. If a SIGTERM hits, the trap still restores the AP and keeps the old pack.

## Self-Check: PASSED

- Files exist: deploy/prep.in, deploy/prep.lock, deploy/prerace (100755), tests/deploy/test_prerace.py, and deploy/wheelhouse/prep/ (8 wheels, gitignored).
- Commits exist: 16649a6, f1f06e1, 7ba5b52 (`git rev-list --count aa61b90..HEAD` = 3).
