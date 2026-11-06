---
phase: 01-foundation-data-backbone-bus-test-kit
reviewed: 2026-11-06T01:28:26Z
depth: deep
files_reviewed: 52
files_reviewed_list:
  - src/jabuka/__init__.py
  - src/jabuka/common/__init__.py
  - src/jabuka/common/atomicio.py
  - src/jabuka/common/clock.py
  - src/jabuka/common/conventions.py
  - src/jabuka/common/messages.py
  - src/jabuka/common/sdnotify.py
  - src/jabuka/common/units.py
  - src/jabuka/core/__init__.py
  - src/jabuka/core/bus.py
  - src/jabuka/core/derived_log.py
  - src/jabuka/core/main.py
  - src/jabuka/core/state.py
  - src/jabuka/core/web.py
  - src/jabuka/ingest/__init__.py
  - src/jabuka/ingest/bus_health.py
  - src/jabuka/ingest/fastnet_decode.py
  - src/jabuka/ingest/fastnet_encode.py
  - src/jabuka/ingest/fastnet_framing.py
  - src/jabuka/ingest/fastnet_main.py
  - src/jabuka/ingest/fastnet_records.py
  - src/jabuka/ingest/gpsd_client.py
  - src/jabuka/ingest/nmea.py
  - src/jabuka/ingest/rawlog.py
  - src/jabuka/ingest/serial_ro.py
  - src/jabuka/sim/__init__.py
  - src/jabuka/sim/fake_gpsd.py
  - src/jabuka/sim/msg_replay.py
  - src/jabuka/sim/pty_replay.py
  - src/jabuka/sim/synth.py
  - src/jabuka/tools/__init__.py
  - src/jabuka/tools/logcheck.py
  - src/jabuka/tools/probe.py
  - src/jabuka/web/static/diag.css
  - src/jabuka/web/static/diag.js
  - src/jabuka/web/static/index.html
  - deploy/PI-SETUP.md
  - deploy/chrony-gps.conf
  - deploy/gpsd.default
  - deploy/provision.sh
  - deploy/requirements.in
  - deploy/secrets.env.example
  - deploy/systemd/fastnet2ip.service
  - deploy/systemd/jabuka-core.service
  - deploy/systemd/jabuka-ingest-fastnet.service
  - deploy/systemd/journald-jabuka.conf
  - deploy/systemd/watchdog.conf
  - deploy/udev/99-jabuka.rules
  - scripts/bootstrap-dev.sh
  - scripts/build-wheelhouse.sh
  - scripts/check.sh
  - tests/bus/test_no_write_path.py
findings:
  critical: 1
  warning: 11
  info: 10
  total: 22
by_severity:
  critical: 0
  high: 1
  medium: 11
  low: 10
status: fixed
fixed_at: 2026-11-06
fix_summary:
  fixed: 18          # CR-01, WR-01..WR-11, IN-04, IN-05, IN-06, IN-08, IN-09, IN-10
  skipped: 4         # IN-01, IN-02, IN-03, IN-07 (low, not trivial)
  gate: "bash scripts/check.sh: ok (467 passed on Python 3.14 and 3.13, ruff clean)"
---

# Phase 1: Code Review Report

**Reviewed:** 2026-11-06T01:28:26Z
**Depth:** deep (cross-module: ingest -> UDP -> core -> state/logs/web, deploy units vs code)
**Files Reviewed:** 52
**Status:** issues_found

Severity mapping: BLOCKER = critical/high, WARNING = medium, INFO = low.

## Summary

Scope: `git diff --name-only 3510091..HEAD -- src tests deploy scripts`. All of `src/jabuka/**`, `deploy/**`
and `scripts/**` were read in full. Of the tests, only the receive-only guard
(`tests/bus/test_no_write_path.py`) was reviewed, and only for whether it can be relied on. Claims were checked
by running code against the repo fixtures: decoded units and M/T layouts, log byte rates, and guard coverage.

Overall the code is careful. It handles hostile UDP/gpsd/serial input without crashing (finite-float checks,
bounded lines and datagrams, exceptions contained per chunk). Atomic file writes are correct, the conventions
module is mathematically right (I checked TWA/TWD/u-v sign cases by hand), and the data path from the bus is
O_RDONLY end to end. Debian's gpsd udev rule leaves the FTDI 0403:6001 match disabled and `USBAUTO=false` is
set, so gpsd will not probe the bus. The main problems:

1. **Log retention is not sustainable (high).** At measured rates the logs grow by several GB per day. The disk
   guard then deletes *all* raw and bus history first, because the derived and event logs are never pruned. In
   the end the disk fills and event markers can no longer be written.
2. **The receive-only guarantee is narrower than claimed.** O_RDONLY blocks `write()` but not the
   break/modem-line ioctls that `ReadOnlySerial` inherits. The static guard misses most of the ways a write
   could be written. Plan B (`fastnet2ip`) runs as root with an O_RDWR fd and unpinned dependencies.
3. **Silent wrong or stale values:** the M/T reference is dropped for four more channels that carry a `°M`
   layout. `latest()` lets an instrument "OFF" (`None`) hide a valid value from another source. The
   diagnostics page shows frozen data as "live"/fresh. The GPS clock stops syncing after 2031.

## Fix status

All critical/high and medium findings are fixed; six of the ten low findings were fixed where the
change was small and safe. Gate after the last fix: `bash scripts/check.sh` ok (ruff check + format
clean, 467 tests passed on Python 3.14 and on 3.13, nothing skipped). Gates ran in the main
checkout (no worktree).

| ID | Severity | Status | Commit | What changed |
|----|----------|--------|--------|--------------|
| CR-01 | high | fixed | d24ceab | `jabuka.ingest.retention`: one policy for `logs/` with per-category budgets (raw 50 %, derived 20 %, bus 15 %, gps 10 %, events 5 % of half the filesystem; `--log-budget-gb`), a free-space reserve pruned bus → derived → gps → events → raw, a 36 h raw floor (breached only as a counted last resort). Derived and events are pruned. Core enforces budgets from its tick, ingest enforces the reserve from its flusher. Bus log opt-in (`--bus-log on`, default off). `diag.core.disk` and the Fastnet heartbeat report free space/usage/raw hours/deletions; red banner on the page. |
| WR-01 | medium | fixed | 0759396 | `ReadOnlySerial` refuses send_break, break_condition, rts, dtr, rs485_mode, tcflow (input/output flow control), xonxoff/rtscts enabling. `open()` turns off ECHO/ICANON, IXON/IXOFF and CRTSCTS as its first termios call (a cooked-mode ttyUSB would otherwise echo bus bytes back onto the bus). Core unit gets `PrivateDevices=yes`. (`DevicePolicy=closed` for the ingest was not added: `char-ttyUSB` is only resolvable while usbserial is loaded, so an adapter plugged in after boot would be denied until a restart.) |
| WR-02 | medium | fixed | ecb3670 | Static guard rewritten: line-control names/attributes/strings, line-attribute assignment/setattr/keywords, pyserial imports outside `serial_ro.py`, os aliases, non-literal/RW `os.open` flags, write-mode `open()` outside an allowlist checked against the source, `write_bytes/write_text`, non read-only `ioctl`. All 12 review snippets are regression cases. |
| WR-03 | medium | fixed | 9bbe870 | New `jabuka-fastnet-relay` (O_RDONLY via `open_fastnet` → pty `/run/jabuka-relay/fastnet-ro`; reader writes are drained, discarded, logged). `fastnet2ip.service` runs as `jabuka` without `dialout`, empty capabilities, `BindsTo=` the relay. fastnet2ip 3.3.1 + 10 deps hash-locked in `deploy/fastnet2ip.lock`, installed offline into `/opt/fastnet2ip/venv` with `--require-hashes`; pipx removed. Risk documented in PI-SETUP §5. |
| WR-04 | medium | fixed | d962677 | `open_fastnet(exclusive=True)`; the flock is taken right after `os.open`, before any termios change, so a refused second opener cannot disturb the first reader. `PortBusyError` → probe state `busy` (exit 1, no wiring verdict); ingest heartbeat `device/state: busy`. |
| WR-05 | medium | fixed | 2ce9109 | Client link watchdog: stale after 3 s without a message (all rows stale, sources "no data", badge "no data for Ns"), socket closed after 6 s; stuck CONNECTING abandoned. Logic in `diag_logic.js`, tested through node. |
| WR-06 | medium | fixed | 71947e6 | Heartbeat: `raw_errors`, `send_errors`, `raw_file`. `diag.core`: `derived_errors`, `bus_log_errors`, `events_errors`, `flush_errors`, `handler_errors` (+ disk from CR-01). Red banner while any counter increased in the last 60 s. |
| WR-07 | medium | fixed | 12cdc80 | `MT_CHANNELS` covers 0x49, 0x69, 0x6D, 0x84, 0x9A, 0xA6, 0xD3 with ref-neutral paths and ref M/T/?; any other rad entry with a °M/°T layout gets a ref. 0xE5/0xE9/0xEA keep their channel-defined references (documented). |
| WR-08 | medium | fixed | f038635 | `latest()` skips `None` values; `rows()` still shows them. |
| WR-09 | medium | fixed | 2ba8c23 | `jabuka.__build_year__`; GPS year window = (build year, build year + 50), passed through `make_clock(gps_years=...)`. |
| WR-10 | medium | fixed | 97c9575 | `/etc/ssh/sshd_config.d/00-jabuka.conf` (old `jabuka.conf` removed) with `PasswordAuthentication no` and `KbdInteractiveAuthentication no`; `sshd -t` before reload; `sshd -T` checked and a loud warning if either is not effective. |
| WR-11 | medium | fixed | c2109dd | `flush_once()` never raises (counted in `raw_errors`); `supervise()` exits 1 when any ingest task ends; port range check in `parse_hostport`; `send`/raw-write exceptions all contained. |
| IN-01 | low | skipped | — | PSK via keyfile/`--ask` changes the AP provisioning path; not trivial to do and verify without the Pi. |
| IN-02 | low | skipped | — | Refusing to run over wlan0 and disabling instead of deleting profiles changes provisioning behaviour; needs a Pi to verify. |
| IN-03 | low | skipped | — | Anchor slewing/monotonic clamp changes GpsClock semantics that Phase 2/3 depend on; deserves its own design + tests. |
| IN-04 | low | fixed | af6f578 | `navigation.datetime` is dropped when GpsClock rejected the TPV. |
| IN-05 | low | fixed | 12cdc80 | Untraceable pyfastnet `...Magnetic/...True` paths are published ref-neutral with ref `?` (with WR-07). |
| IN-06 | low | fixed | d224a83 | Millisecond field clamped to 999. |
| IN-07 | low | skipped | — | Probe output-dir handling (`--force`, per-run part matching, separate write-error reporting) is a CLI behaviour change beyond a trivial fix. |
| IN-08 | low | fixed | 71947e6, 7745a10 | Failed event write → 503 `{"ok": false, "error": "log write failed"}` shown in the UI; dev `--http-host` default 127.0.0.1, Pi unit passes 0.0.0.0 explicitly (it relied on the default). |
| IN-09 | low | fixed | 7745a10 | PI-SETUP EINVAL item and ingest unit READY comment corrected; README updated. |
| IN-10 | low | fixed | 8b6111a | `load_json_with_bak` catches `OSError`/`ValueError` per candidate; logcheck reports instead of crashing. |

Notes for the human verify pass:
- The local `deploy/wheelhouse/` (gitignored) holds a stale `jabuka-*.whl`: rebuild it with
  `bash scripts/build-wheelhouse.sh` before provisioning (it now also fetches
  `deploy/wheelhouse/fastnet2ip/`). The dev `.venv` needs a reinstall to get the new
  `jabuka-fastnet-relay` console script (tests use `python -m`).
- On the Pi: check `journalctl -u jabuka-fastnet-relay` while Plan B runs, `sshd -T | grep -i
  authentication`, and the Core `disk` row on the diagnostics page.
- `nmea2000` 2026.11.3 (a Plan B dependency) was released days before it was locked; review it.

## Critical Issues

### CR-01: [BLOCKER / high] Log retention: derived/events never pruned, so the disk guard wipes all raw and bus history, then the disk fills

**Files:** `src/jabuka/core/main.py:71-108`, `src/jabuka/core/derived_log.py:17`, `src/jabuka/ingest/rawlog.py:136-166`, `src/jabuka/ingest/fastnet_main.py:336`
**Issue:** Each `RotatingAppendLog` has its own guard, limited to its own directory and prefixes:
- raw: `("fastnet",)`
- bus: `("bus",)`
- gps: `("gps",)`
- derived: `()`, so never pruned
- events: `()`, so never pruned

I measured the rates by feeding `tests/fixtures/fastnet/ap_backlight_20260514.txt` through `FastnetIngest`
(2433 datagrams for 24.3 s of wire time at full bus load):
- bus log (every accepted datagram, re-serialised): **about 46 KB/s**
- raw log: **about 5.8 KB/s**
- derived log (one full snapshot per second, 41 rows): **about 7-8 KB/s**

That is up to about 4-5 GB/day on a busy bus. The derived log alone is about 0.6-0.7 GB/day. Once free space
drops below 1 GB, each guard deletes its oldest files until 1 GB is free again. The derived log keeps growing,
so the raw and bus guards keep deleting until there is **no raw history left**. The raw log is meant to be the
primary record, written before anything decodes the bytes. After that the disk fills:
- `derived.write` fails every tick (logged only to the volatile journal);
- `record_event` raises, so `/api/event` returns HTTP 500 and the user's event markers are lost.

On a 32 GB card the guard starts eating raw captures within about a week of continuous running. Nothing on the
diagnostics page warns about it.
**Fix:**
- Replace the per-instance guards with one retention policy for the whole data volume. Give each category a
  budget, e.g. raw 50%, derived 20%, bus 10%, gps 10%, events never deleted. Prune in this order: bus, then
  derived, then gps, then raw. Keep a hard floor of the last N days of raw.
- Cut the volume: write the derived log only on change or at 0.2 Hz, or gzip rotated files (hourly derived and
  bus files compress about 10:1). Make the bus log opt-in on the Pi (`--bus-log off`), since it is about 8x
  the raw bytes and the raw log plus deterministic decode can reproduce it.
- Report `disk_free_bytes`, `guard_deleted` and the oldest raw timestamp in `diag.core`, and colour the page
  when the guard is active.

## Warnings

### WR-01: [WARNING / medium] `ReadOnlySerial` still exposes break and modem-line control; O_RDONLY does not block these ioctls

**File:** `src/jabuka/ingest/serial_ro.py:41-82` (docstring lines 1-5; `fastnet_main.py:4` "nothing in this process can write to the bus")
**Issue:** Only `write()` is overridden. `ReadOnlySerial` still inherits from pyserial:
- `send_break()` (`termios.tcsendbreak`);
- the `break_condition` setter, which ends in `_update_break_state` and `ioctl(TIOCSBRK)`;
- the `rts`/`dtr` setters (`TIOCMBIS`/`TIOCMBIC`);
- the `rs485_mode` setter (`TIOCSRS485`).

The Linux tty layer does not check `FMODE_WRITE` on `TIOCSBRK`/`TCSBRK`/`TIOCMSET`/`TIOCMBIS`, so these work on
an O_RDONLY fd. The udev `MODE=0640` only controls whether the device can be opened for writing; it does not
affect these ioctls.

On the DTECH in RS-485 mode with Fastnet on T/R+/T/R- (the wiring PI-SETUP.md tells the user to use), a break
condition holds the line in the spacing state. That actively drives the B&G bus. No code calls these today, so
this is a defence-in-depth gap rather than a live path. But the module promises "kernel-enforced", and this is
the one guarantee the project calls absolute.
**Fix:**
```python
class ReadOnlySerial(serial.Serial):
    def send_break(self, duration: float = 0.25) -> None:
        raise PermissionError("Fastnet port is receive-only")
    def _update_break_state(self) -> None:
        raise PermissionError("Fastnet port is receive-only")
    def _update_rts_state(self) -> None:
        raise PermissionError("Fastnet port is receive-only")
    def _update_dtr_state(self) -> None:
        raise PermissionError("Fastnet port is receive-only")
    @serial.Serial.rs485_mode.setter
    def rs485_mode(self, value) -> None:
        if value is not None:
            raise PermissionError("Fastnet port is receive-only")
        self._rs485_mode = None
```
Add a test asserting each one raises. Also correct the docstrings: O_RDONLY covers data writes only.
Optionally, for cgroup-level open-mode enforcement, add `DevicePolicy=closed` plus
`DeviceAllow=/dev/fastnet r` and `DeviceAllow=char-ttyUSB r` to `jabuka-ingest-fastnet.service`, and
`PrivateDevices=yes` to `jabuka-core.service`, which never needs the tty.

### WR-02: [WARNING / medium] The static receive-only guard misses most write constructs

**File:** `tests/bus/test_no_write_path.py:32-57`
**Issue:** I ran `violations()` on these snippets. **All of them come back clean (not detected):**
- `ser.break_condition = True`
- `ser.rts = True` / `ser.dtr = False`
- `fcntl.ioctl(fd, termios.TIOCSBRK)`
- `termios.tcsendbreak(fd, 0)`
- `from serial import Serial; Serial('/dev/fastnet')`
- `open('/dev/fastnet','wb').write(...)`
- `os.open('/dev/fastnet', 2)` (numeric flags)
- `Path('/dev/fastnet').write_bytes(...)`
- `self.ser.sendBreak()`
- `import os as o; o.write(...)`
- `w = os.write; w(fd, ...)`
- `s.rs485_mode = x`

The test name ("no write path") and the SUMMARY treat it as proof, but it only matches exact spellings.
**Fix:**
- Flag every attribute assignment to `break_condition|rts|dtr|rs485_mode|rtscts|dsrdtr|xonxoff`.
- Flag any reference to `TIOCSBRK|TCSBRK|TCSBRKP|TIOCMSET|TIOCMBIS|TIOCMBIC|TIOCSRS485|tcsendbreak|sendBreak|setRTS|setDTR`.
- Flag any `import serial` / `from serial import` outside `serial_ro.py`.
- Flag `open(...)` and `os.open(...)` whose mode or flags are not literally read-only.
- Resolve `import os as X` aliases.

Pair the test with WR-01's runtime overrides, so the guarantee does not rest on the static scan alone.

### WR-03: [WARNING / medium] Plan B `fastnet2ip` runs as root with an O_RDWR fd on the bus, and its dependencies are unpinned

**Files:** `deploy/systemd/fastnet2ip.service:10-23`, `deploy/provision.sh:245-252`
**Issue:**
- The unit runs as `User=root`, so the 0640 udev mode does not apply, and pyserial opens `/dev/fastnet` O_RDWR.
  pyserial's `open()` also sets DTR and RTS.
- The only assurance is a grep of fastnet2ip 3.3.1's own source.
- `pipx install --global fastnet2ip==3.3.1` pins the top-level version only. Its dependencies (pyfastnet,
  pyserial, ...) resolve from PyPI at whatever versions are current when provisioning runs, with no hashes.
  The grep says nothing about that code, which runs as root with a write-capable fd on the B&G bus.

This is the one real code path that could transmit.
**Fix:** Do not give a third-party root process the bus fd. Reuse the existing pieces in a small
`jabuka-relay`: `open_fastnet()` (O_RDONLY) reads the bus and `PtyFeeder` writes the bytes into a pty with
`link=/run/jabuka/fastnet-ro`. Run fastnet2ip as `User=jabuka` on that pty: anything it writes goes into the pty
and never reaches the wire. Lock fastnet2ip and its dependencies with hashes in the wheelhouse, as is already
done for the app, instead of a live `pipx install`.

### WR-04: [WARNING / medium] No exclusive open: probe and ingest can split the byte stream, and the probe then tells the user to rewire

**Files:** `src/jabuka/ingest/serial_ro.py:85-94`, `src/jabuka/tools/probe.py:11, 269`
**Issue:** `open_fastnet` does not pass `exclusive=True`, and `ReadOnlySerial.open` does not use TIOCEXCL. Two
readers on one tty each get a random share of the bytes, which breaks frames apart. If `fastnet-probe` is run
while `jabuka-ingest-fastnet` is still running (the docstring says "stop the ingest first", but nothing
enforces it), the probe sees many discarded bytes. Its verdict is then `no_frames` ("swap White/Green") or
`noisy`, so a healthy bus produces the instruction to swap wires on the B&G bus. Two ingest instances (manual
run plus the systemd unit) corrupt each other in the same way.
**Fix:** In `open_fastnet`, pass `exclusive=True`. pyserial's `_reconfigure_port`, which
`ReadOnlySerial.open` already calls, then takes `flock(LOCK_EX|LOCK_NB)`, and that works on an O_RDONLY fd.
In the probe, turn the resulting `SerialException(EWOULDBLOCK)` into "port busy: stop jabuka-ingest-fastnet
first", with exit code 1 and no wiring verdict.

### WR-05: [WARNING / medium] The diagnostics page shows frozen values as fresh and "live" when the WebSocket goes quiet

**File:** `src/jabuka/web/static/diag.js:51-55, 180-200`
**Issue:** Ages and staleness are computed only on the server, and the client has no receive timeout. On a
half-open Wi-Fi link (tablet at the edge of AP range, AP restart, core hung but socket open) the browser may not
fire `onclose` for minutes. The last frame stays on screen with `fresh` row colours and the "live" badge. This is
the "silent stale value" failure the project ranks worst, and Phase 2's helm view will likely copy the pattern.
**Fix:**
```js
let lastMsg = 0;
ws.onmessage = (ev) => { lastMsg = performance.now(); /* render */ };
setInterval(() => {
  if (performance.now() - lastMsg > 3000) {
    setConn(false, "no data");
    document.querySelectorAll("#values-body tr").forEach((tr) => (tr.className = "stale"));
    if (ws.readyState === WebSocket.OPEN && performance.now() - lastMsg > 6000) ws.close();
  }
}, 1000);
```

### WR-06: [WARNING / medium] Raw, bus and derived log write failures are invisible on the diagnostics page

**Files:** `src/jabuka/ingest/fastnet_main.py:145-173` (health payload), `src/jabuka/ingest/fastnet_main.py:89-91, 197-206`, `src/jabuka/core/main.py:212-221`, `src/jabuka/core/bus.py:38-41`
**Issue:** `FastnetIngest` counts `raw_errors` and `send_errors`, but `health()` does not report either. A full
disk, an SD card remounted read-only after an fs error, or an oversize datagram dropped in `_emit` all leave
the heartbeat reporting `state: ok`. In the core, derived and bus log failures go only to `log.exception` and
`log.warning`, and the journal is volatile (`journald-jabuka.conf`), so the evidence is lost on the next
reboot. The gpsd client does report `raw_errors`, so the sources behave inconsistently. With raw-first logging
as a stated guarantee, losing the raw log must be visible.
**Fix:** Add `raw_errors`, `send_errors`, `rawlog.current_path.name` and `rawlog.guard_deleted` to the
heartbeat. Add `derived_errors`, `bus_log_errors`, `events_errors` and disk free space to `diag.core`. Show a red
state when any of them increases.

### WR-07: [WARNING / medium] The M/T reference is dropped for 0x69, 0x9A, 0xA6 and 0xD3; their paths assume Magnetic or no reference

**File:** `src/jabuka/ingest/fastnet_decode.py:24-28, 120-124`
**Issue:** I decoded all fixtures and grouped the results by layout. These channels carry a `°M` layout, which
pyfastnet uses for the M/T flag:
- `0x69` Course (HDG+Leeway), published as `bandg.navigation.courseThroughWater`;
- `0x9A` Heading on Next Tack, published as `performance.tackMagnetic`;
- `0xA6` Autopilot Compass Target, published as `steering.autopilot.target.headingMagnetic`;
- `0xD3` Dead Reckoning Course.

Only 0x49, 0x6D and 0x84 go through `ROUTED_CHANNELS`, so these four have no `ref`. Two of them have
"Magnetic" fixed in the path name by pyfastnet. If the instruments are set to True heading (the `°T` code is
still unidentified), these values are labelled Magnetic or carry no reference at all. That is the same
silent-mislabel bug that the module docstring says it removes for heading/TWD/set. Bearing-to-waypoint
(`...bearingTrue`, 0xE5) is likewise assumed True.
**Fix:** For every decoded entry, set `item["ref"] = _ref_for_layout(entry["layout"])` whenever the layout is a
heading layout (`°M`, `°T` or unknown) on a channel whose unit is an angle, not only for the routed three.
Rename the affected pyfastnet paths to ref-neutral ones (strip the `Magnetic`/`True` suffix), as is already done
for the routed channels.

### WR-08: [WARNING / medium] `StateStore.latest()` lets a `None` ("OFF") value hide a valid value from another source

**File:** `src/jabuka/core/state.py:91-110`
**Issue:** Fastnet publishes `value: None` for channels whose instrument shows "OFF". The fixtures contain
`navigation.speedOverGround` (0xEB), `navigation.courseOverGroundTrue` (0xE9), `environment.current.set` and
others. Those entries are stored with a fresh `t_rx`. `latest()` picks the freshest non-stale entry across
sources and ignores the value, so a Fastnet "OFF" received after the gpsd TPV hides gpsd's valid SOG/COG.
`latest()` is the documented arbitration seam for Phase 2 (WIND-04), so this will turn into wrong or missing
inputs there.
**Fix:**
```python
for (p, _src), e in self._entries.items():
    if p != path or e["value"] is None:
        continue
```
Keep the `None` rows in `rows()` for diagnostics.

### WR-09: [WARNING / medium] GpsClock stops working after 2031: the routing gate stays blocked

**File:** `src/jabuka/common/clock.py:196, 220`
**Issue:** `years=(2026, 2031)` is a fixed default, and `make_clock("gps")` uses it. From 1 Jan 2032 every TPV is
rejected:
- `time_valid` never becomes True and routing stays "blocked" on every boot;
- `now_utc()` returns None and events and derived lines carry no UTC.

The diagnostics page would show the cause, but this is a built-in expiry date for an appliance that ships as
a disk image.
**Fix:** Derive the lower bound from a build constant (for example `jabuka.__build_year__`, or the wheel's
mtime). This keeps the GPS week-rollover guard, which rejects dates about 19.6 years in the past. Set the upper
bound to lower+50, or drop it. Pass the bounds through `make_clock`.

### WR-10: [WARNING / medium] The SSH key-only drop-in can be silently overridden, and the result is never verified

**File:** `deploy/provision.sh:276-279`
**Issue:** sshd keeps the **first** value it reads for each keyword, and `Include /etc/ssh/sshd_config.d/*.conf`
loads files in lexical order. `jabuka.conf` sorts after any numbered drop-in. For example, Imager/cloud-init
first-boot setup with password SSH writes `50-cloud-init.conf` containing `PasswordAuthentication yes`. If such
a file exists, password login stays enabled while the script reports success. The provisioning log implies
key-only.
**Fix:** Name the file `/etc/ssh/sshd_config.d/00-jabuka.conf`, then verify the effective value:
```bash
run sshd -t
if [ "$DRY_RUN" -eq 0 ] && ! sshd -T 2>/dev/null | grep -qx 'passwordauthentication no'; then
    warn "PasswordAuthentication is still enabled (another sshd_config.d drop-in wins)"
fi
```

### WR-11: [WARNING / medium] Ingest background tasks can die silently while the watchdog keeps pinging

**Files:** `src/jabuka/ingest/fastnet_main.py:209-213, 238-242, 342-373`
**Issue:**
- `flusher()` calls `rawlog.maybe_flush()` with no `try`. The first `ENOSPC`/`EIO` from `fh.flush()` or
  `os.fsync` ends the task. The exception is never retrieved, and a quiet bus no longer gets flushed or
  fsync'd.
- The watchdog task is independent of the reader, heartbeat and flusher tasks. It only detects a blocked
  event loop, so systemd never restarts a process whose real work has died.
- `on_chunk`/`_emit` and `send_heartbeat` catch only `OSError` from `send`. `parse_hostport` does not
  range-check the port, so `--udp 127.0.0.1:99999` makes `sendto` raise `OverflowError`. That escapes
  `on_chunk`, despite its "never raises" contract, into the `add_reader` callback on every chunk, and kills the
  heartbeat task.

**Fix:**
- Wrap the `flusher` body in `try/except Exception: log.exception(...)`.
- Add a done-callback to each task in `tasks` that sets `done.set_result(1)` when the task ends with an
  exception, so systemd restarts the process.
- Validate `0 < port < 65536` in `parse_hostport`, as `core.main.parse_gpsd` already does.
- In `_emit` and `send_heartbeat`, catch `Exception` (counted) around `self.send`.

## Info

### IN-01: [INFO / low] The Wi-Fi passphrase is passed on nmcli's command line

**File:** `deploy/provision.sh:318, 326, 328`
**Issue:** `show()` masks the PSK in the printed log. But `nmcli ... wifi-sec.psk "$JABUKA_PSK"` exposes it in
`/proc/<pid>/cmdline`, readable by every local user while nmcli runs.
**Fix:** Create the profile without the secret and set it with `nmcli connection modify jabuka-ap
wifi-sec.psk-flags 0` plus `nmcli --ask`, or write the keyfile
`/etc/NetworkManager/system-connections/jabuka-ap.nmconnection` (mode 0600) and run
`nmcli connection reload`.

### IN-02: [INFO / low] Provisioning deletes every other Wi-Fi profile, and this cannot be undone

**File:** `deploy/provision.sh:295-305`
**Issue:** Every 802-11-wireless profile is deleted before the AP comes up, including the Imager home-Wi-Fi
profile. If the operator runs the script over Wi-Fi (the script warns, but only later, at line 331), the session
drops in the middle of the loop and the Pi has neither its client Wi-Fi nor the AP. The Pi also permanently
loses the internet path that `pipx install fastnet2ip` and later re-provisioning need.
**Fix:** Before step b, refuse to run when the SSH client address (`$SSH_CONNECTION`) arrives via wlan0. Set the
other profiles to `connection.autoconnect no` instead of deleting them.

### IN-03: [INFO / low] GpsClock UTC can step backwards on every fix

**File:** `src/jabuka/common/clock.py:248-251`
**Issue:** Every fix that matches the anchor re-anchors to `(fix_time, arrival_mono)`. When gpsd latency grows
from fix k-1 to fix k, `now_utc()` jumps back by `L_k - L_{k-1}`, which can be up to the 0.5 s tolerance. UTC
consumers then see time running backwards: Phase 3 GRIB interpolation, event ordering by `utc`.
**Fix:** Re-anchor only when `|utc - predicted|` exceeds a small threshold (for example 0.2 s), or slew the
anchor (`ref_utc += 0.1 * err`). Keep `now_utc` monotonic with a `max(last_returned, computed)` clamp.

### IN-04: [INFO / low] `navigation.datetime` is published from TPVs that the clock rejected

**File:** `src/jabuka/ingest/gpsd_client.py:120-122`, `src/jabuka/core/main.py:147-158`
**Issue:** A TPV with a rollover date (for example 2006) is rejected by `GpsClock._sane_epoch`, but
`tpv_to_values` still publishes its `time` as a fresh `navigation.datetime`.
**Fix:** Publish `navigation.datetime` only when the clock accepted the fix (have `on_tpv` return a bool and
pass it through), or attach `valid: false`.

### IN-05: [INFO / low] Decode fallback publishes pyfastnet's assumed-Magnetic path when no source entry matches

**File:** `src/jabuka/ingest/fastnet_decode.py:116-124`
**Issue:** When `source.get(path)` is None, `out_path` stays pyfastnet's name, for example
`navigation.headingMagnetic`, and gets no `ref`. That name is exactly what the module exists to avoid. This
cannot happen with today's pyfastnet projection, but nothing guards against it.
**Fix:** Map the known pyfastnet M/T paths (`navigation.heading{Magnetic,True}`,
`environment.wind.direction{Magnetic,True}`, `environment.current.set{Magnetic,True}`) to the ref-neutral path
with `ref="?"`, or drop the value, when `entry is None`.

### IN-06: [INFO / low] NMEA time rounding can produce ".1000" (dev path)

**File:** `src/jabuka/ingest/nmea.py:76-78`
**Issue:** For seconds with 4 or more decimals (for example `59.9996`), `ms = round(0.9996*1000) = 1000` produces
`"...:59.1000Z"`, which `fromisoformat` reads as 59.1 s. The time is then 0.9 s off.
**Fix:** `ms = min(999, int((sec - whole) * 1000))`, or build the datetime with `timedelta(seconds=sec)`.

### IN-07: [INFO / low] A reused probe output directory mixes or overwrites captures; disk errors are reported as "cannot open"

**File:** `src/jabuka/tools/probe.py:241-257, 346-352`
**Issue:** `_finish_capture` concatenates every `capture-*.log` in `out_dir`, including leftovers from an
earlier probe that crashed, and silently replaces an existing `capture.log`. Any exception in `_read_live`,
including `ENOSPC` from `capture.write_chunk`, is reported as `cannot open {device}`, and with no bytes it is
classified `missing`.
**Fix:** Refuse to run if `out_dir` is non-empty, unless `--force` is given. Only collapse parts whose names
match this run's `RotatingAppendLog` boot and hour stems. Report write errors separately from open errors.

### IN-08: [INFO / low] `/api/event` returns HTTP 500 on I/O errors and accepts unauthenticated requests on every interface

**File:** `src/jabuka/core/web.py:85-99`, `src/jabuka/core/main.py:306`
**Issue:**
- `record_event` errors (disk full, see CR-01) are not caught, so the user gets a bare "HTTP 500" and the marker
  is lost.
- `--http-host` defaults to `0.0.0.0`, so the dev laptop also exposes the event endpoint to its LAN.
- On the Pi, any AP client can write events (WPA2 is the only control). That is acceptable but should be
  documented.

**Fix:** Catch `OSError` and return 503 `{"ok": false, "error": "log write failed"}`, and show it in the UI. Make
the dev default `127.0.0.1`; the systemd unit already passes its own host.

### IN-09: [INFO / low] Docs and comments disagree with the code

**Files:** `deploy/PI-SETUP.md:303-306`, `deploy/systemd/jabuka-ingest-fastnet.service:4-5`
**Issue:**
- PI-SETUP still describes the EINVAL reopen restart loop as a deferred item, but `_reset_to_standard_speed`
  (commit 6f5f5af) fixed it.
- The ingest unit says READY=1 is sent "once /dev/fastnet is open", but `fastnet_main.py:363-374` sends READY
  even when the device is missing (correctly, for unattended start).

**Fix:** Update both texts.

### IN-10: [INFO / low] `load_json_with_bak` raises on permission or other OS errors instead of falling back, which also crashes logcheck

**File:** `src/jabuka/common/atomicio.py:46-53`, `src/jabuka/tools/logcheck.py:176-188`
**Issue:** Only `FileNotFoundError`, `JSONDecodeError` and `UnicodeDecodeError` are caught. A main file with
`EACCES`/`EIO`, or a directory with that name, raises out of `load_json_with_bak`. `check_json` catches
`OSError` on its first read and then calls `load_json_with_bak`, which raises the same error uncaught, so
`jabuka-logcheck` crashes instead of reporting.
**Fix:** Catch `OSError` (and `ValueError`) per candidate in `load_json_with_bak`.

## Verified non-issues (checked, no finding)

- **gpsd probing the DTECH:** Debian's gpsd udev rule has the FTDI 0403:6001 match disabled, and `USBAUTO="false"`
  suppresses hotplug adds (RESEARCH line 589). `DEVICES="/dev/gps"` only.
- **Units:** pyfastnet projections are SI. I checked fixed speed `5.5 kn` decodes to `2.829 m/s`, `18°C` to
  `291.15 K`, and heading `296°M` to `5.166 rad`. 0x4F and 0x56 are the m/s channels, matching the synth encoder.
- **Conventions:** TWA/TWD/AWA sign handling, wind FROM vs current TOWARDS, and u/v are correct; `wrap_pi(±pi)`
  returns `pi`.
- **Hostile input:** datagrams are bounded (8192 bytes), NaN/Infinity are rejected, nesting depth is capped, the
  gpsd line splitter is bounded and resyncs, the framer buffer is capped, decode exceptions are contained, and
  every page cell is set with `textContent` (no XSS).
- **Atomic writes:** tmp + fsync, hard-link .bak, rename, dir fsync. Log files are opened with exclusive create
  plus the boot_id in the name, so nothing is overwritten after a clock step.

---

_Reviewed: 2026-11-06T01:28:26Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
