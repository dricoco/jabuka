---
phase: 01-foundation-data-backbone-bus-test-kit
plan: 04
subsystem: pi-appliance
status: complete
tags: [raspberry-pi, provisioning, systemd, watchdog, networkmanager, gpsd, chrony, udev, wheelhouse, hash-lock, crash-recovery, logcheck]
requires: ["01-01"]
provides:
  - "deploy/provision.sh: idempotent root provisioning with --dry-run / --psk-file / --wheelhouse / --skip-ap"
  - "deploy/systemd/{jabuka-ingest-fastnet,jabuka-core,fastnet2ip}.service + watchdog.conf + journald-jabuka.conf"
  - "deploy/udev/99-jabuka.rules, deploy/gpsd.default, deploy/chrony-gps.conf, deploy/secrets.env.example"
  - "deploy/requirements.in + hash-locked deploy/requirements.lock (aarch64, cp313, 17 packages)"
  - "scripts/build-wheelhouse.sh [--relock] -> deploy/wheelhouse (gitignored), with an offline install simulation"
  - "jabuka.tools.logcheck: check_dir(path) -> Report, main(argv) (console script jabuka-logcheck)"
  - "deploy/PI-SETUP.md: flash / provision / verify checklist a-m / Plan B / troubleshooting"
affects: [01-02, 01-03, phase-4]
tech-stack:
  added: []
  patterns: [run()-wrapped mutations with dry-run printing, secret masking in command echo, parse-not-source secrets file, NetworkManager shared-mode AP, unit tests that parse ExecStart with the real argparse parsers, systemd-analyze verify on rewritten copies, offline pip --dry-run --platform install simulation]
key-files:
  created:
    - deploy/systemd/jabuka-ingest-fastnet.service
    - deploy/systemd/jabuka-core.service
    - deploy/systemd/fastnet2ip.service
    - deploy/systemd/watchdog.conf
    - deploy/systemd/journald-jabuka.conf
    - deploy/provision.sh
    - deploy/udev/99-jabuka.rules
    - deploy/gpsd.default
    - deploy/chrony-gps.conf
    - deploy/secrets.env.example
    - deploy/requirements.in
    - deploy/requirements.lock
    - deploy/PI-SETUP.md
    - scripts/build-wheelhouse.sh
    - src/jabuka/tools/logcheck.py
    - tests/deploy/conftest.py
    - tests/deploy/test_units.py
    - tests/deploy/test_provisioning_files.py
    - tests/deploy/test_lock.py
    - tests/deploy/test_logcheck.py
    - tests/deploy/test_crash_recovery.py
  modified: []
decisions:
  - "fastnet2ip.service has no [Install] section, so `systemctl enable` cannot put the Plan B into boot even by mistake; it is started by hand only (Conflicts= both ways)"
  - "provision.sh validates the PSK only when the AP is configured (--skip-ap needs none), refuses the example PSK on a real run, parses (never sources) the secrets file, and masks the PSK as *** in every echoed command"
  - "provision.sh skips apt-get when every apt package is already installed, so a re-run (wheelhouse upgrade) works fully offline; the wheelhouse is swapped in atomically (copy to .new, then rename) and the jabuka wheel is installed --force-reinstall so a same-version rebuild still upgrades"
  - "jabuka-logcheck exits 2 when DIR is not a directory (in addition to the 0 ok / 1 corrupt contract), and requires complete lines to be strict UTF-8"
  - "The crash-recovery test resets the pty's termios to 38400 between kill and restart, because a pty silently drops PARENB and glibc >= 2.42 then rejects pyserial's tcsetattr on a pty already at 28800 (see Deferred Issues)"
metrics:
  duration: "~19 min"
  completed: 2026-11-06
  tasks: 3
  files: 21
plan_head_before: f878a42cbbeb4fb39c6e522af3ee2bf4776fa9aa
actuals:
  tokens: 29000
  tasks: 3
  commits: 4
---

# Phase 1 Plan 04: Pi Appliance Summary

One root script (`deploy/provision.sh`, idempotent, with a `--dry-run`) turns a fresh Pi OS Lite 64-bit Trixie into the Jabuka appliance. It sets up a NetworkManager WPA2 AP at 10.42.0.1/24, a read-only `/dev/fastnet` (0640 root:dialout) and `/dev/gps`, and gpsd (USBAUTO off) feeding chrony from SHM 0 with `makestep 1 -1`. Two hardened `Type=notify` services run with a 30 s watchdog, restart forever and run unprivileged, and the hardware watchdog is armed. The runtime is hash-locked for aarch64/cp313 and installs from an offline wheelhouse. `jabuka-logcheck` and a laptop kill -9 test show that crashes leave only torn tails.

## What was built

- **Units.** The ingest and core units share StartLimitIntervalSec=0, Type=notify, Restart=always, RestartSec=2, WatchdogSec=30, User/Group jabuka, StateDirectory, NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp, ReadWritePaths=/var/lib/jabuka and PYTHONUNBUFFERED. The ingest adds SupplementaryGroups=dialout, OOMScoreAdjust=-700 and Conflicts=fastnet2ip.service, and is not bound to the device. The core adds Wants/After gpsd (plus chrony), port 80 via the ambient and bounding CAP_NET_BIND_SERVICE, and OOMScoreAdjust=-500. The fastnet2ip Plan B unit is root, Restart=on-failure, `--host 10.42.0.255 --udp-port 2002`, with no [Install] section and a header explaining when to use it. Drop-ins: RuntimeWatchdogSec=15, and a volatile journal capped at 32M.
- **provision.sh.** Steps a-k in the planned order, every mutation through `run()`. It requires root without `--dry-run` (exit 1) and a PSK of 8-63 characters (exit 2). apt install, then a tolerated purge of modemmanager/brltty. gpsd default and udev rules, then reload and trigger. chrony conf.d plus the sed (and an append fallback), then chrony, then gpsd. User jabuka (system, user-group, dialout, nologin). The wheelhouse is swapped atomically into /opt/jabuka, then a venv is created and `pip --no-index --find-links --require-hashes -r requirements.lock`, then the jabuka wheel `--no-deps --force-reinstall`. pipx fastnet2ip==3.3.1 is a warning when offline, and its unit is installed but not enabled. Then units, drop-ins, daemon-reload, `systemctl enable jabuka-ingest-fastnet.service jabuka-core.service`, a journald restart and a service restart. Next, sshd key-only, written only if a non-empty `/home/*/.ssh/authorized_keys` exists. Then the AP: Wi-Fi country, delete the other Wi-Fi profiles, add or modify jabuka-ap with the exact RESEARCH properties, and bring it up last with a warning. There is no hostapd/dnsmasq/dhcpcd config anywhere.
- **Lock/wheelhouse.** `deploy/requirements.in` matches the pyproject pins. The `uv pip compile` lock has 17 packages and 324 sha256 hashes. `build-wheelhouse.sh` downloads the aarch64 wheels with the system pip (`--require-hashes`) and builds the jabuka wheel with `uv build`. It checks for exactly one wheel per pin at the locked version, with no extras, and prints each sha256. Finally it **simulates the Pi's offline install**: `pip install --dry-run --no-index --require-hashes --platform manylinux*_aarch64 --python-version 3.13 --target tmp`, which resolves all 17 packages.
- **jabuka-logcheck.** Covers raw (`fastnet*`/`capture*`: two floats and non-empty even-length hex), line-json (`bus*`/`gps*`: two floats and JSON), `*.jsonl`, and `*.json` via `load_json_with_bak` (source main/bak). Torn tails are reported, not failed. Empty lines and bad UTF-8 are errors. `.bak` files and `.NAME.tmp` leftovers are not checked on their own. Output is a text or `--json` report.
- **PI-SETUP.md** (328 lines): sections 0-7 as planned, including verify items a-m, the Plan B flow and troubleshooting. Troubleshooting has an extra entry for an ingest stuck in a restart loop on `Invalid argument`.

## Test results

- `bash scripts/check.sh`: ruff check and format are clean. **133 passed, 1 skipped** on Python 3.14.7, and **133 passed, 1 skipped** on 3.13.12 (about 18 s each).
- The skip is `test_core_execstart_parses_with_the_real_cli`: "01-03 not merged yet; phase-level check covers it". The argv shape is still asserted before the skip. Run `.venv/bin/python -m pytest tests/deploy/test_units.py -q -rs` after the wave-2 merge, and the skip must disappear.
- `systemd-analyze verify --man=no` runs on rewritten copies of the 3 units and is clean. A detector test proves that it flags a misspelled directive.
- Crash recovery runs 3 cycles of SIGKILL on ingest and core mid-stream (about 9 s). It was green 3 times in a row on each Python. After each kill `check_dir` is ok, a restart serves `environment.wind.angleApparent` within 10 s, the new raw file has the same boot8 and seq+1, and no earlier file shrank or changed inode. A final `python -m jabuka.tools.logcheck` exits 0, with raw files >= ingest starts (4).
- Atomic JSON torture: 20 random SIGKILLs. The main file always loads complete, holding the last or the in-flight counter, and `.bak` is complete.
- Acceptance greps pass: StartLimitIntervalSec, Conflicts, USBAUTO, makestep, `--hash` (324), pyfastnet==3.2.1, 10.42.0.1, `stty -F /dev/fastnet` and `chronyc sources`. `jabuka-logcheck --help` exits 0.

## TDD Gate Compliance (Task 3)

- RED `aa57548`: `tests/deploy/test_logcheck.py` failed at collection with `ModuleNotFoundError: jabuka.tools.logcheck`.
- GREEN `1ac8ba1`: logcheck implemented, 19/19 tests pass. One test-fixture bug was fixed in GREEN: `state/` must exist before `atomic_write_json`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The provision.sh dry run ran before the lock existed**
- **Found during:** Task 1 (the Task 1 tests run before Task 2 creates `deploy/requirements.lock` and the wheelhouse)
- **Fix:** a missing lock or wheelhouse is a warning under `--dry-run` and a clear fatal error (exit 3) on a real run
- **Files:** deploy/provision.sh. **Commit:** 74dad0b

**2. [Rule 1 - Bug, test-only] The restarted ingest could not reopen the same pty (EINVAL)**
- **Found during:** Task 3 (`test_kill9_ingest_and_core_mid_stream`). The restarted ingest exited 2 with `cannot open ...: (22, 'Invalid argument')`.
- **Root cause (reproduced in isolation):** on this laptop (glibc 2.43) Python exposes `termios.B28800`, so pyserial takes the plain `tcsetattr` path. A pty silently drops PARENB. Once the pty is at 28800, glibc rejects a `tcsetattr` that asks for PARENB with EINVAL. A fresh pty works, and so does any request without PARENB. A real UART keeps PARENB.
- **Fix (within this plan's files):** the test resets the pty termios to 38400 between kill and restart, which is the state a new pty would have. The reason is documented in the test.
- **Files:** tests/deploy/test_crash_recovery.py. **Commit:** 1ac8ba1

**3. [Rule 2 - Missing critical] Added safety to provision.sh beyond the plan**
- It refuses the example PSK on a real run, checks the PSK is printable ASCII, parses the secrets file instead of sourcing it, and accepts a quoted PSK.
- The apt step is skipped when everything is already installed, for offline re-runs.
- The wheelhouse is swapped in atomically, and the jabuka wheel is installed with `--force-reinstall`.
- The services are restarted after `enable`, so a re-provision runs the new code.
- PI-SETUP.md is copied to /opt/jabuka, which the units' `Documentation=` points to.
- **Commit:** 74dad0b

**4. [Rule 2] build-wheelhouse.sh simulates the offline Pi install**
- An extra final step, `pip install --dry-run --no-index --require-hashes` for aarch64/cp313, so a wheelhouse the Pi could not install fails on the laptop. **Commit:** 96c54a2

## Deferred Issues

- **serial_ro hardening (outside this plan's files, owned by 01-01; recommended for the orchestrator or a follow-up).** `ReadOnlySerial.open()` could first put the tty back to a standard speed (CBAUD/CIBAUD cleared, B38400) before `_reconfigure_port`. That makes a re-open of a tty left at 28800 independent of glibc's speed API. On the Pi (Trixie glibc 2.41, no `termios.B28800`) pyserial uses the BOTHER/TCSETS2 path and a real FTDI keeps PARENB, so the bug is **not expected** there. PI-SETUP item h (the ingest's NRestarts must stay at 1 after kill -9) and the troubleshooting entry catch it on hardware if it does happen. The same applies to `fastnet-probe` (01-02) opening a tty the ingest has configured, and to any 01-02/01-03 test that re-opens the same pty after a reader was killed.

## Known Stubs

None. The dry-run line `nmcli connection delete <every 802-11-wireless profile except jabuka-ap>` is deliberate: the dry run does not query the laptop's NetworkManager.

## Threat Flags

None. All surface is in the plan's register: T-04-01..07 and T-04-SC are mitigated as planned, and T-04-02 and T-04-08 are accepted. SSH hardening (T-04-04) applies only when an authorized key exists.

## Human check (end of phase, non-blocking)

1. Flash and provision per deploy/PI-SETUP.md sections 1-3 (DATA-01).
2. PI-SETUP section 4 items a-l on the real Pi 3B with the DTECH and VK-162:
   - parity and permissions: c, b, d (DATA-02)
   - chrony clock: e, f (DATA-04)
   - tablet AP: g (DATA-01)
   - REL-01: h, i, j, k
   - probe NO BYTES: l
3. Item m: review the 17 package names in deploy/requirements.lock (T-04-SC).

## Self-Check: PASSED

- Files exist: all 21 key files listed above, and deploy/wheelhouse holds 18 wheels (gitignored).
- Commits exist: 74dad0b, 96c54a2, aa57548, 1ac8ba1.
