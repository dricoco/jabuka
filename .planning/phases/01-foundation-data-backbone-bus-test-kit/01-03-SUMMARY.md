---
phase: 01-foundation-data-backbone-bus-test-kit
plan: 03
subsystem: gps-clock-conventions-sim
status: complete
tags: [gpsd, gps-clock, time-gate, conventions, golden-tests, nmea, fake-gpsd, synthetic-boat, fault-injection, fastnet-encoder]
requires:
  - "01-01: Clock protocol/SimClock, messages, RotatingAppendLog, StateStore, CoreContext/create_app, decode_to_values, CountingFramer, PtyFeeder"
provides:
  - "jabuka.ingest.gpsd_client (GpsdClient, run_gpsd_client, parse_line, tpv_to_values, sky_to_values, tpv_epoch, MAX_LINE)"
  - "jabuka.ingest.nmea (parse_sentence, NmeaToGpsd)"
  - "jabuka.sim.fake_gpsd (FakeGpsd, load_script, load_nmea, jabuka-fake-gpsd CLI)"
  - "jabuka.common.clock.GpsClock + make_clock('gps') + routing_time_gate"
  - "jabuka.common.units, jabuka.common.conventions (pinned by golden tests)"
  - "jabuka.ingest.fastnet_encode (rec01, rec08, frame)"
  - "jabuka.sim.synth (SynthConfig, SynthBoat, run_synth, jabuka-sim CLI with 4 fault kinds)"
  - "jabuka-core flags: --clock {system,sim,gps}, --gpsd HOST:PORT|none; core.main.build_context(args)"
affects: [01-04, phase-2, phase-3, phase-4]
tech-stack:
  added: []
  patterns: [raw-first gps log, bounded line splitter with resync, GPS time discipline with candidate timeline and holdover, single conventions boundary module, literal golden tests, embedded fake gpsd for sim, wait-for-reader before writing a pty]
key-files:
  created:
    - src/jabuka/ingest/gpsd_client.py
    - src/jabuka/ingest/nmea.py
    - src/jabuka/sim/fake_gpsd.py
    - src/jabuka/common/units.py
    - src/jabuka/common/conventions.py
    - src/jabuka/ingest/fastnet_encode.py
    - src/jabuka/sim/synth.py
    - tests/fixtures/gps/tpv_sky.jsonl
    - tests/fixtures/gps/sample.nmea
    - tests/gps/conftest.py
    - tests/gps/test_gpsd_client.py
    - tests/gps/test_nmea.py
    - tests/gps/test_gps_e2e.py
    - tests/gps/test_gps_clock.py
    - tests/common/test_units.py
    - tests/common/test_conventions.py
    - tests/sim/test_fastnet_encode.py
    - tests/sim/test_synth_e2e.py
  modified:
    - src/jabuka/common/clock.py
    - src/jabuka/core/main.py
decisions:
  - "gpsd lines are split by a bounded LineSplitter over reader.read() instead of StreamReader.readline: on an overrun readline clears its buffer and the tail of the overlong line comes back as a second garbage line, so the resync point is lost and the line is double counted"
  - "GpsClock.on_tpv returns True for every sane fix (mode >= 2, time, year 2026-2031), consistent or not; consistency only drives the sync count and re-anchoring"
  - "GpsClock holdover_s = time since the anchor was last refreshed (grows during GPS loss and during an unproven jump candidate); last_fix_age_s = time since any sane fix"
  - "A jump is counted once per departure from the anchor timeline; the old anchor is held until the candidate timeline has required_fixes consecutive consistent fixes"
  - "true_wind_from_apparent / apparent_from_true return NamedTuples (TrueWind twa/tws/twd, ApparentWind awa/aws); apparent_from_true(twd, tws, bsp, hdg)"
  - "Synth waits for a gpsd watcher (--wait-gpsd) and, in pty mode, for another process to open the pty slave (--wait-reader, /proc scan + 0.5 s) because the ingest flushes input on open"
  - "NMEA: RMC A gives mode 3 when the last GGA had a fix, else 2; RMC magvar is not carried into TPV (gpsd semantics West-positive; not needed by the dev path)"
  - "rec01/rec08 raise ValueError for out-of-range values instead of clamping silently"
metrics:
  duration: "~19 min"
  completed: 2026-11-06
  tasks: 3
  files: 20
plan_head_before: f878a42cbbeb4fb39c6e522af3ee2bf4776fa9aa
actuals:
  tokens: 32600
  tasks: 3
  commits: 5
---

# Phase 1 Plan 03: GPS, Clock, Conventions and Synthetic Boat Summary

jabuka-core now reads gpsd over its JSON protocol. Every raw line lands in `logs/gps` before it is parsed, and the client reconnects with a 1 to 5 s backoff. Position, COG, SOG, UTC and satellite health show on the diagnostics page with `src gpsd`, an age, and a `health.gps` block. With `--clock gps` a GpsClock blocks the routing time gate until 3 sane, consistent fixes have arrived (mode >= 2, year 2026-2031, within 0.5 s). After that it holds over through GPS loss and counts time jumps instead of applying them. The units and conventions modules are pinned by literal golden tests. `jabuka-sim` drives a synthetic boat with four fault kinds through the same pipeline, either as UDP deltas or as encoded Fastnet bytes read by the real ingest.

## What was built

- **gpsd client** (`ingest/gpsd_client.py`):
  - `GpsdClient.run()` / `run_gpsd_client()` send WATCH, then for each line: raw log first, then `parse_line`, then `on_object(obj, t_rx)`.
  - `parse_line` rejects invalid JSON or UTF-8, NaN/Infinity, non-objects, a missing or non-string `class`, and lines over 8192 bytes. Rejections are counted in `rejected_lines`.
  - `tpv_to_values`: always emits `gps.mode`. With mode >= 2 it adds `navigation.position` {latitude, longitude} (deg, range-checked), `courseOverGroundTrue` (rad, ref T), `speedOverGround` (m/s), `navigation.datetime` and `gps.eph`.
  - `sky_to_values` uses uSat/nSat, falling back to counting `satellites[].used`.
  - Health dict: connected, device, mode, sats_used, sats_visible, hdop, tpv_rx, sky_rx, rejected_lines, reconnects, last_error, handler_errors, raw_errors, server. Handler or raw-log failures are counted and never raised.
- **NMEA** (`ingest/nmea.py`): `parse_sentence` checks the XOR checksum, accepts any talker and only ASCII. `NmeaToGpsd` turns GGA into SKY, RMC A into a TPV (time from ddmmyy + hhmmss.ss, kn converted to m/s), and RMC V into a mode 1 TPV with no time.
- **Fake gpsd** (`sim/fake_gpsd.py`, `jabuka-fake-gpsd`):
  - Protocol: VERSION on connect; on ?WATCH it sends DEVICES (/dev/gps, u-blox) and WATCH.
  - Methods: `push`, `push_raw`, `pause`/`resume`, and `play(speed, loop, retime)`, paced by TPV time deltas.
  - Inspection helpers: `wait_watching` and `sent_lines`.
  - CLI: `--script` takes JSONL or a jabuka gps raw log (torn last line tolerated), or `--nmea`; also `--speed`, `--loop`, `--retime`. Default port is 2948.
- **Core** (`core/main.py`):
  - New flags `--gpsd HOST:PORT|none` and `--clock {system,sim,gps}`.
  - `CoreContext.create(..., gpsd=)` adds the rotating `gps` log (guard prefix `gps`, flushed by the tick) and a `jabuka-gpsd` lifespan task.
  - A TPV goes to `clock.on_tpv` (GpsClock) or `observe_utc` (SimClock, sane fixes only) BEFORE `t_rx` is stamped.
  - `build_context(args)` is shared by `serve()` and the tests.
- **GpsClock** (`common/clock.py`): implements the interface contract. Status keys: kind, time_valid, routing_time_gate, utc, synced, consistent_fixes, holdover_s, jumps, last_fix_age_s, system_clock (synced/unsynced/unknown, tolerance 1 s), system_offset_s, plus required_fixes, fixes_accepted, fixes_rejected and system_utc. It is still the only module in common/ and core/ that reads the wall clock (`test_no_wallclock` stays green).
- **Units and conventions** (`common/units.py`, `common/conventions.py`):
  - Units: KN_IN_MS = 1852/3600; wrap_2pi gives [0, 2π) with a guard for the 2π rounding edge; wrap_pi gives (-π, π].
  - Directions: mag_to_true and true_to_mag with East-positive variation, apply_heading_offset, and gpsd_magvar_to_east (West-positive input).
  - u/v: wind FROM uses atan2(-u, -v); current TOWARDS uses atan2(u, v).
  - True and apparent wind are computed as boat-frame vectors, with signed angles where negative = port.
- **Encoder** (`ingest/fastnet_encode.py`): rec01, rec08 and frame, as in the RESEARCH code example, with range checks.
- **Synthetic boat** (`sim/synth.py`, `jabuka-sim`):
  - Wind and boat model: TWD + shift, TWS + gust·sin(2πt/120). Heading is fixed, or set to TWD − TWA. A placeholder BSP curve is 0 at TWA 0, monotone in TWS and capped at 8.5 kn. AWA/AWS come from `apparent_from_true`, position from dead reckoning.
  - udp mode: SI deltas plus a heartbeat carrying t_sim (state ok/silent).
  - pty mode: Broadcast frames (0x41, 0x51, 0x4F, 0x59, 0x56 and 0x49 magnetic with layout 0x66) are written to a PtyFeeder.
  - An embedded FakeGpsd sends TPV and SKY at 1 Hz.
  - Faults use `KIND@START+DUR`: bus-silent, gps-loss, garbage (4 hostile datagrams, or 64 random bytes in pty mode) and clock-jump (`--jump-s`).
  - The CLI prints the gpsd port and pty/link at start, and a fault timeline at the end.

## Test results

- `bash scripts/check.sh`: ruff check and ruff format are clean. **166 passed** on Python 3.14.7 and **166 passed** on Python 3.13 (about 24 s each). Plan 01-01 had 76 tests; this plan adds 90.
- `tests/gps` and `tests/sim` were run 3 more times on 3.14: green every time (68 passed each).
- GPS e2e: FakeGpsd plays `tpv_sky.jsonl` (retimed) into a core started from real flags. The test checks rows with `src gpsd`, `health.gps` {connected, mode 3, sats_used 8, hdop 0.9, device /dev/gps}, and that VERSION and TPV lines appear verbatim in `logs/gps/gps-*.log`. After a gpsd stop, connected goes false within 3 s; after a restart on the same port it reconnects within 6 s.
- Clock e2e with `--clock gps`: blocked after a no-fix TPV and 2 fixes, ok after the 3rd, `system_clock` synced.
- udp synth e2e (speed 20, 70 sim-s, all four faults), checked against the derived log:
  - wind: fresh at 2-9, stale at 21-24, fresh at 29-50
  - gpsd position: fresh at 2-29, stale at 35-39, fresh again at 42-49
  - `udp_rejected` stays 0 until 44 and is above 0 at 47-54
  - every `age_s` is >= 0
  - the jump shows up as UTC +3600, and the clock is back on its original timeline at 66-70
  - fewer than 200 lines, and no ERROR log from jabuka loggers
- pty synth e2e: the decoded AWA is within 1° and BSP within 0.05 kn of the last simulated values, and the heading has ref "M".

## TDD Gate Compliance

- Task 1: RED `9c305d0` (conftest import error: `build_context`, `gpsd_client`, `nmea` and `fake_gpsd` did not exist), then GREEN `b9310ce`.
- Task 2: RED `7e7c993` (collection errors: `GpsClock`, `units` and `conventions` missing), then GREEN `61036a8`.
- Task 3 (not TDD): `142f6f2`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug avoided] gpsd line limit: a bounded splitter instead of `StreamReader.readline(limit)`**
- **Found during:** Task 1 design. In CPython's `readline`, a `LimitOverrunError` clears the buffer, so the rest of the overlong line arrives later as a separate "line". That loses the resync point and counts one hostile line twice.
- **Fix:** `LineSplitter` feeds on `reader.read(4096)`. It caps memory at MAX_LINE, drops the overlong line once (its first 8192 bytes go to the raw log), and resyncs at the next newline.
- **Files:** src/jabuka/ingest/gpsd_client.py. **Commit:** b9310ce

**2. [Rule 1 - Test bug] Encoder round-trip test with leading junk**
- **Issue:** two junk bytes in front of the frame made the framer read 0xFF as a body length and wait for 261 bytes. This is by design (RESEARCH Pitfall 4).
- **Fix:** the test feeds `frame + frame` with no junk. Resync on corrupt input is covered by `test_checksums`.
- **Files:** tests/sim/test_fastnet_encode.py. **Commit:** 142f6f2

**3. [Rule 3 - Blocking] Synth must not write into a pty before the reader opens it**
- **Issue:** the 01-01 note says `ReadOnlySerial.open()` flushes pending input.
- **Fix:** added `SynthConfig.wait_reader_s` / `--wait-reader`, which polls /proc until another process holds the slave and then waits 0.5 s. Also added `wait_gpsd_s` / `--wait-gpsd`, so a core whose gpsd client is still in backoff doesn't miss the first sim seconds at speed 20. Both default to 0.
- **Files:** src/jabuka/sim/synth.py. **Commit:** 142f6f2

### Interpretations and additive extensions (no contract renamed or removed)

- `rec01` and `rec08` raise ValueError when a value is out of range. The plan said both "clamp" and "raise"; raising is the safer of the two.
- Additions beyond the interfaces block:
  - fake gpsd: `FakeGpsd.push_raw`, `wait_watching`, `sent_lines`, `play(wait_client=)`, `load_script`, `load_nmea`, `--host`
  - gpsd client: `GpsdClient` class (backing `run_gpsd_client`), `tpv_epoch`, a `mono=` kwarg and backoff kwargs
  - synth: `SynthConfig.start_utc` (`--start-utc`) and `gpsd_host`; `run_synth(on_ready=)`
  - core: `core.main.parse_gpsd`, `build_context`, `CoreContext.on_gps_object`/`on_gps_health`
  - units/conventions: `units.TWO_PI`; `conventions.TrueWind`/`ApparentWind`
- COG values carry `ref: "T"`.
- `--gpsd` defaults to `None` (parsed from "none"). Help text names the Pi value `127.0.0.1:2947` that plan 01-04's unit passes.

## Contract for 01-04 (phase-level cross-check)

`.venv/bin/jabuka-core --help` lists `--clock {system,sim,gps}` and `--gpsd HOST:PORT|none`. The 01-04 unit can run `jabuka-core --http-port 80 --data-dir /var/lib/jabuka --clock gps --gpsd 127.0.0.1:2947` as specified.

## Human check (end of phase, non-blocking; from Task 2)

Run these on the Pi after 01-04 provisioning, with the VK-162 plugged in and no internet:
1. `gpspipe -w -n 5` shows TPV mode 3.
2. `chronyc sources` shows `#* GPS`.
3. Power-cycle with a stale fake-hwclock: after the fix, `date -u` is correct to within 1 s.
4. The diagnostics page shows routing_time_gate blocked at boot, then ok with system_clock synced.

On the laptop: run `jabuka-core --clock sim --gpsd 127.0.0.1:2948` next to `jabuka-sim --speed 20 --wait-gpsd 10 --fault bus-silent@60+30 --fault gps-loss@120+30`, and watch the rows on http://127.0.0.1:8080/ go stale and recover.

## Known Stubs

None. `synthetic_bsp` is the placeholder curve the plan asked for (CONTEXT: the real X35 polar is Phase 2 WIND-01). It only feeds the developer simulator, not live data.

## Threat Flags

None. The gpsd TCP client (T-03-02), raw gps log (T-03-03), GpsClock (T-03-01) and fake gpsd/sim (T-03-04: port 2948, 127.0.0.1 by default, dev-only) are all in the plan's threat register with their mitigations implemented and tested.

## Self-Check: PASSED

- Files exist: every path under key-files.created and key-files.modified.
- Commits exist: 9c305d0, b9310ce, 7e7c993, 61036a8, 142f6f2.
