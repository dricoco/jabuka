---
phase: 01-foundation-data-backbone-bus-test-kit
verified: 2026-11-06T02:45:00Z
status: human_needed
score: 30/34 must-haves verified (4 hardware-only, routed to human verification)
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-01-PLAN.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-01-SUMMARY.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-02-PLAN.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-02-SUMMARY.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-03-PLAN.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-03-SUMMARY.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-04-PLAN.md", ".planning/phases/01-foundation-data-backbone-bus-test-kit/01-04-SUMMARY.md", "deploy/PI-SETUP.md", "deploy/chrony-gps.conf", "deploy/gpsd.default", "deploy/provision.sh", "deploy/requirements.in", "deploy/requirements.lock", "deploy/secrets.env.example", "deploy/systemd/fastnet2ip.service", "deploy/systemd/jabuka-core.service", "deploy/systemd/jabuka-ingest-fastnet.service", "deploy/systemd/journald-jabuka.conf", "deploy/systemd/watchdog.conf", "deploy/udev/99-jabuka.rules", "pyproject.toml", "scripts/bootstrap-dev.sh", "scripts/build-wheelhouse.sh", "scripts/check.sh", "src/jabuka/__init__.py", "src/jabuka/common/__init__.py", "src/jabuka/common/atomicio.py", "src/jabuka/common/clock.py", "src/jabuka/common/conventions.py", "src/jabuka/common/messages.py", "src/jabuka/common/sdnotify.py", "src/jabuka/common/units.py", "src/jabuka/core/__init__.py", "src/jabuka/core/bus.py", "src/jabuka/core/derived_log.py", "src/jabuka/core/main.py", "src/jabuka/core/state.py", "src/jabuka/core/web.py", "src/jabuka/ingest/__init__.py", "src/jabuka/ingest/bus_health.py", "src/jabuka/ingest/fastnet_decode.py", "src/jabuka/ingest/fastnet_encode.py", "src/jabuka/ingest/fastnet_framing.py", "src/jabuka/ingest/fastnet_main.py", "src/jabuka/ingest/fastnet_records.py", "src/jabuka/ingest/gpsd_client.py", "src/jabuka/ingest/nmea.py", "src/jabuka/ingest/rawlog.py", "src/jabuka/ingest/serial_ro.py", "src/jabuka/sim/__init__.py", "src/jabuka/sim/fake_gpsd.py", "src/jabuka/sim/msg_replay.py", "src/jabuka/sim/pty_replay.py", "src/jabuka/sim/synth.py", "src/jabuka/tools/__init__.py", "src/jabuka/tools/logcheck.py", "src/jabuka/tools/probe.py", "src/jabuka/web/static/diag.css", "src/jabuka/web/static/diag.js", "src/jabuka/web/static/index.html"]
covered_digest: "v1:sha256:f843e354f92ec0972e36e0735faf480e4b36e33fb2b2aae188e0827e44a63cdb"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Flash Pi OS Lite 64-bit Trixie and run `sudo deploy/provision.sh --psk-file deploy/secrets.env` over Ethernet (PI-SETUP.md sections 1-3). First run `bash scripts/build-wheelhouse.sh` on the laptop: deploy/wheelhouse is absent in the main checkout."
    expected: "Script exits 0; `systemctl is-enabled jabuka-ingest-fastnet jabuka-core` prints enabled twice; after `sudo reboot` with no keyboard/monitor both services are active (headless boot)."
    why_human: "Needs the Pi 3B hardware and an SD card (DATA-01, REL-01)."
  - test: "Tablet with mobile data off joins SSID `jabuka` (WPA2) and opens http://10.42.0.1/ (PI-SETUP 4g)."
    expected: "Diagnostics page loads with no internet; values table, health (fastnet, gps) and routing gate badge render and update about once per second."
    why_human: "Real Wi-Fi AP and tablet browser (ROADMAP SC1, DATA-01)."
  - test: "In a browser against a local replay (README three commands) or the Pi: watch the values table, stop the replay, press 'Event marker' with a label."
    expected: "Rows show unit, src, ref, age; rows turn stale after the replay stops; acknowledgement 'Marker #n logged at ...' appears; a new line lands in logs/events/events-*.jsonl."
    why_human: "Client-side JS rendering (diag.js) has no automated browser test; the API it calls is tested (planner-deferred human-check, 01-01 Task 2)."
  - test: "With the DTECH plugged in and the ingest running: `stty -F /dev/fastnet`; `ls -l /dev/fastnet`; `sudo lsof /dev/ttyUSB*`; `lsusb` (PI-SETUP 4b-4d)."
    expected: "speed 28800, parenb parodd cs8 cstopb; target crw-r----- root dialout; only jabuka-ingest-fastnet holds the port; 0403:6001 and 1546:01a7 present."
    why_human: "Parity cannot be tested on a pty; udev and real FTDI only exist on the Pi (DATA-02)."
  - test: "With the ingest stopped and the bus not connected: `fastnet-probe --device /dev/fastnet --seconds 10` (PI-SETUP 4l). On 12 Nov at the boat, repeat with the bus connected and keep inventory.json and capture.log."
    expected: "NO BYTES verdict, exit 2. At the boat: OK verdict, exit 0, channel inventory written."
    why_human: "Real RS-485 adapter and B&G bus (DATA-05, ROADMAP SC2)."
  - test: "VK-162 plugged in, no internet: `gpspipe -w -n 5`, `chronyc sources`, power-cycle with a stale fake-hwclock, then `date -u`; watch the diagnostics clock block (PI-SETUP 4e-4f)."
    expected: "TPV mode 3; `#* GPS`; system clock correct within 1 s after the fix; page shows routing_time_gate blocked at boot, then ok with system_clock synced."
    why_human: "Real GPS fix, chrony SHM refclock and clock stepping only happen on hardware (DATA-04, ROADMAP SC3)."
  - test: "`sudo kill -9` each service's MainPID; unplug/replug the DTECH and GPS; 5 power pulls followed by `sudo -u jabuka /opt/jabuka/venv/bin/jabuka-logcheck /var/lib/jabuka/logs`; `dmesg | grep -i watchdog` (PI-SETUP 4h-4k)."
    expected: "Services back within about 5 s (NRestarts increments for kill, unchanged for unplug); page shows missing then recovered; logcheck exits 0 after every power pull; hardware watchdog armed."
    why_human: "systemd supervision, USB hot-plug and real power loss on the SD card (REL-01, ROADMAP SC5)."
  - test: "Review deploy/requirements.lock package names before copying the wheelhouse to the Pi (PI-SETUP 4m, T-04-SC)."
    expected: "Exactly the 17 expected canonical projects: annotated-doc, annotated-types, anyio, click, fastapi, h11, idna, opentelemetry-api, pydantic, pydantic-core, pyfastnet, pyserial, starlette, typing-extensions, typing-inspection, uvicorn, websockets."
    why_human: "Supply-chain judgement (planner-deferred human-check, 01-04 Task 2)."
---

# Phase 1: Foundation, Data Backbone & Bus-Test Kit Verification Report

**Phase Goal:** The Pi boots headless into a receive-only data backbone that records and decodes Fastnet and GPS data. Every later feature can be built and tested against replayed or simulated data before the boat is reachable, and the bus can be diagnosed on the boat in minutes.
**Verified:** 2026-11-06T02:45:00Z
**Status:** human_needed
**Re-verification:** No, initial verification

All software that can be checked on the laptop is present, wired and tested. Hardware-only checks are listed under Human Verification.

## User Flow Coverage (MVP mode)

The ROADMAP `**Goal:**` line is not in user-story form. The plans restate it, and that version passes `user-story.validate` (valid=true): "As a the X35's owner-navigator ..., I want to have the Pi boot headless into a receive-only data backbone ..., so that every later feature can be built and tested before the boat is reachable and the bus can be diagnosed on board in minutes."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Pi boots headless | Services enabled at boot, supervised, AP up | Units (Type=notify, Restart=always, WatchdogSec=30, WantedBy=multi-user.target); `provision.sh` enables both and brings up the AP; `systemd-analyze verify` clean (tests/deploy/test_units.py) | Software verified; hardware boot is a human check |
| Receive-only backbone records raw bytes | Raw bytes on disk before decoding; nothing can write to the bus | `FastnetIngest.on_chunk` calls `rawlog.write_chunk(b)` before `framer.feed`; `ReadOnlySerial` opens `O_RDONLY`; AST guard; udev MODE 0640 | VERIFIED |
| Decodes Fastnet and GPS | Normalized values with unit, src, age | `decode_to_values` produces AWA/AWS, TWA/TWS/TWD, BSP, heading (ref M/?), depth, set/drift, position, COG, SOG across the 10 fixtures; gpsd TPV/SKY go to `src gpsd` | VERIFIED |
| [outcome] Built and tested before the boat is reachable | L0 byte replay, L1 message replay, L2 synthetic boat with faults, all through the same pipeline | `jabuka-replay` (faults), `jabuka-replay-msgs`, `jabuka-sim` (udp and pty modes, 4 fault kinds); test_synth_e2e, test_msg_replay | VERIFIED |
| [outcome] Bus diagnosed on board in minutes | One-command verdict plus hint, channel inventory | `fastnet-probe` exits 0/2/3/4/5/1 with wiring hints; inventory.json + capture.log | VERIFIED on laptop; on-boat run is a human check |

## Goal Achievement

### Observable Truths: ROADMAP Success Criteria (the contract)

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | Tablet joins the Pi AP at a fixed IP with no internet and opens a diagnostics page that lists every decoded value (AWA/AWS, TWA/TWS/TWD, BSP, heading, depth, set/drift, position, COG, SOG, UTC) with units, source and age, plus bus and GPS health | ✓ VERIFIED (software) + ? hardware | The decoder emits every listed quantity across the fixtures (enumerated: angleApparent, speedApparent, angleTrueWater, speedTrue, wind.direction, speedThroughWater, heading, depth.belowTransducer, current.set, current.drift, position, COG, SOG). gpsd adds navigation.datetime (UTC). `StateStore.rows()` gives unit, src, ref, age_s and stale. The diag message carries `health.fastnet` (1 Hz heartbeat) and `health.gps`. diag.js renders all of it. AP at 10.42.0.1/24 is in the provision.sh dry run. AP join and browser rendering are human checks. |
| SC2 | `fastnet-probe` reports frames, checksums and channel IDs, gives a swap-wires hint, saves an inventory; no process on the Pi can transmit; raw bytes on disk before decoding | ✓ VERIFIED | Spot-checked: `--file example2` exits 0 with "OK: 105.1 frames/s, 54 channels"; a byte-inverted capture exits 3 with "BYTES BUT NO VALID FRAMES: swap White/Green (A/B)"; a missing device exits 1. inventory.json has 0x49 with layouts_seen and raw_records. Receive-only is enforced in three layers: O_RDONLY fd (test_open_fastnet_on_a_pty_is_read_only), the AST guard over ingest/ and tools/ (test_no_write_constructs_in_ingest_or_tools), and udev MODE 0640. Raw first: `on_chunk` writes the raw log before the framer (test_decoder_exception_keeps_raw_first, tracer raw-log byte equality). |
| SC3 | With the VK-162 and no internet the system clock is set from GPS; diagnostics show unsynced until GPS time is valid; routing time gate "blocked" until then | ✓ VERIFIED (software) + ? hardware | `GpsClock`: 3 consistent fixes, mode >= 2, year 2026-2031, holdover, jump handling; `status()` gives time_valid false, routing_time_gate "blocked" and system_clock "unknown" until synced. Unit `--clock gps --gpsd 127.0.0.1:2947` parses with the real CLI (test_units no longer skips). chrony SHM 0 plus `makestep 1 -1` are in deploy. Tests: test_core_gps_clock_gate, test_holdover_after_gps_loss, test_time_jump_counted_held_then_reanchored. Setting the real system clock is a human check. |
| SC4 | Replay a recorded capture, or run the synthetic boat with faults (bus silent, GPS loss, garbage), at accelerated speed through the same pipeline, appearing on diagnostics exactly as live | ✓ VERIFIED | test_udp_mode_with_faults (speed 20, 70 sim-s, 4 faults): wind stale during bus-silent, gpsd position stale during gps-loss, udp_rejected > 0 after garbage, every age_s >= 0 through the clock jump, `health.fastnet.state == "silent"`. test_pty_mode_through_real_ingest: encoded frames through the real ingest decode within 1 deg and 0.05 kn. test_replay_bus_log_into_sim_core covers L1, and the tracer tests cover L0. |
| SC5 | Raw and 1 Hz derived state logged continuously; UI event marker lands in the log; after a killed process or a pulled power plug all services come back and logs/state are not corrupted | ✓ VERIFIED (software) + ? hardware | The tick writes the derived JSONL before publishing (test_derived_log_1hz_under_simclock). POST /api/event writes fsync'd JSONL (test_event_201_and_stored, test_event_fsynced_immediately); the page button POSTs to it. test_kill9_ingest_and_core_mid_stream: 3 SIGKILL cycles, logcheck ok, no file shrank or was replaced, values back within 10 s. test_atomic_json_survives_random_sigkill: 20 kills. Units: Restart=always, StartLimitIntervalSec=0. Real power pulls and systemd restarts are human checks. |

### Observable Truths: PLAN must_haves (merged)

| Plan | Truth (abridged) | Status | Evidence |
| --- | --- | --- | --- |
| 01-01 | Replay to pty to ingest to core puts AWA, BSP and heading (ref M) on /api/state, /ws and / with unit, src, ref, age_s | ✓ VERIFIED | test_in_process_core, test_full_stack_subprocesses (pass on 3.14 and 3.13) |
| 01-01 | Device fd is O_RDONLY: os.write gives EBADF, .write raises PermissionError | ✓ VERIFIED | serial_ro.py; tests/test_serial_ro.py, test_open_fastnet_on_a_pty_is_read_only |
| 01-01 | Every byte goes to the raw log before the framer | ✓ VERIFIED | fastnet_main.py `on_chunk`; tracer raw-log equality |
| 01-01 | Framing is equivalent to pyfastnet on 10 captures with golden counts | ✓ VERIFIED | tests/test_framing_equivalence.py (10 parametrized cases) |
| 01-01 | 0x49, 0x6D and 0x84 carry ref M/T/?; rawfn gives M and ?, never True | ✓ VERIFIED | Enumeration: heading M=197 and ?=10; current.set M=79 and ?=22; no T |
| 01-01 | Derived JSONL at 1 Hz; event button writes an fsync'd line plus an ack | ✓ VERIFIED (API) | test_logging, test_event_marker; the browser-side ack is a human check |
| 01-01 | SystemClock gives time_valid false and the gate blocked | ✓ VERIFIED | clock.py SystemClock; tracer asserts routing_time_gate == "blocked" |
| 01-01 | Torn tail tolerated, .bak fallback, READY/WATCHDOG, SIGTERM exits 0 | ✓ VERIFIED | test_atomicio, test_sdnotify, test_logging |
| 01-02 | Probe on an example2 pty replay: ok, channels 0x41/0x49/0x51, inventory + capture, exit 0 | ✓ VERIFIED | test_probe_live_example2_ok; CLI spot-check exit 0 |
| 01-02 | Swap-wires exit 3, NO BYTES exit 2, NOISY exit 4 | ✓ VERIFIED | test_probe_live_inverted_says_swap_wires, _silent, _garbage_is_noisy; spot-check inverted exit 3 |
| 01-02 | Inventory lists channels with layouts_seen and raw records for 0x49/0x6D/0x84 | ✓ VERIFIED | Spot-check: 0x49 layouts_seen ['°M'], raw_records present |
| 01-02 | Ingest never exits on device loss; reports missing; reopens | ✓ VERIFIED | test_unplug_and_replug_reconnects_without_exiting, test_absent_device_at_start_does_not_exit |
| 01-02 | 1 Hz heartbeat when silent; page shows alive with state silent | ✓ VERIFIED | test_silent_bus_heartbeats_at_1hz_and_core_shows_silent |
| 01-02 | AST scan: no serial write path in ingest/ or tools/ | ✓ VERIFIED | test_no_write_path.py (12 positive and 4 negative controls) |
| 01-02 | Bus log replays via UDP at --speed into a --clock sim core | ✓ VERIFIED | test_replay_bus_log_into_sim_core |
| 01-03 | gpsd TPV/SKY give position, COG, SOG, datetime and gps.* with src gpsd, plus a gps health block | ✓ VERIFIED | test_gps_e2e; `CoreContext.on_gps_object` / `on_gps_health` wired in `startup()` |
| 01-03 | --clock gps is blocked until 3 consistent fixes, then ok; holdover on loss | ✓ VERIFIED | test_gps_clock.py incl. test_core_gps_clock_gate |
| 01-03 | Jumps counted; no negative ages; no-fix or rollover TPVs never sync | ✓ VERIFIED | test_time_jump_counted_held_then_reanchored; age clamped >= 0 in StateStore |
| 01-03 | Raw gpsd line logged before parsing | ✓ VERIFIED | test_client_raw_first_and_rejects_hostile_lines |
| 01-03 | Conventions pinned by golden tests | ✓ VERIFIED | tests/common/test_conventions.py, test_units.py |
| 01-03 | jabuka-sim with 4 fault kinds at speed through the same pipeline | ✓ VERIFIED | test_udp_mode_with_faults |
| 01-03 | pty mode: synth frames through the real ingest match the simulated values | ✓ VERIFIED | test_pty_mode_through_real_ingest |
| 01-04 | provision.sh on a fresh Pi leaves WPA2 AP `jabuka` at 10.42.0.1/24 that a tablet joins | ? UNCERTAIN (hardware) | Dry run exits 0 and shows the exact nmcli properties; real AP join is a human check |
| 01-04 | Both services enabled, Restart=always, StartLimitIntervalSec=0, notify + WatchdogSec=30, unprivileged, ProtectSystem=strict; hardware watchdog armed | ✓ VERIFIED (config) | Unit files read; test_units.py; systemd-analyze verify clean; RuntimeWatchdogSec=15 drop-in. Arming on the Pi is a human check. |
| 01-04 | udev /dev/fastnet MODE 0640 with MM ignore; gpsd pinned with USBAUTO=false; ModemManager and brltty purged | ? UNCERTAIN (hardware runtime) | Rule, gpsd.default and purge step present and token-tested; real udev/gpsd behaviour is a human check |
| 01-04 | chrony steps the clock from GPS SHM 0 | ? UNCERTAIN (hardware) | chrony-gps.conf plus the `makestep 1 -1` sed in provision.sh; real clock stepping is a human check |
| 01-04 | fastnet2ip Plan B never concurrent (Conflicts both ways), not enabled | ✓ VERIFIED | Conflicts= in both units; fastnet2ip.service has no [Install]; dry-run test asserts it is never enabled |
| 01-04 | Repeated kill -9 leaves logs valid, nothing truncated or overwritten, atomic JSON complete | ✓ VERIFIED | test_kill9_ingest_and_core_mid_stream, test_atomic_json_survives_random_sigkill |
| 01-04 | Runtime hash-locked for aarch64/cp313; wheelhouse buildable for offline reinstall | ✓ VERIFIED (lock) | requirements.lock: 17 packages, 324 sha256 hashes; test_lock passes. The wheelhouse itself is absent in the main checkout (gitignored), so its check SKIPPED here; see Warnings. |

**Score:** 30/34 truths verified (5 ROADMAP SCs, each verified in software, plus 25/29 plan truths). The 4 unverified items are hardware-runtime truths: 01-04 AP join, udev/gpsd runtime, chrony stepping, and ROADMAP SC1/3/5 hardware halves, all routed to Human Verification. No truth FAILED. behavior_unverified: 0. Every behavior-dependent truth (reconnect, heartbeat, clock gate/holdover/jump, crash recovery, fault staleness) is exercised by a passing named test.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `pyproject.toml` | Pins + 8 console scripts | ✓ VERIFIED | All 8 CLIs run `--help` successfully |
| `src/jabuka/ingest/serial_ro.py` | ReadOnlySerial, open_fastnet | ✓ VERIFIED | O_RDONLY; reopen fix (6f5f5af) tested |
| `src/jabuka/ingest/fastnet_{framing,decode,records,main}.py`, `rawlog.py`, `bus_health.py` | Ingest pipeline | ✓ VERIFIED | Substantive; wired in `jabuka-ingest-fastnet` |
| `src/jabuka/core/{state,bus,web,main,derived_log}.py` | Core + diag API | ✓ VERIFIED | UDP to StateStore to diag to /api/state, /ws, page |
| `src/jabuka/web/static/{index.html,diag.js,diag.css}` | Diagnostics page + event marker | ✓ VERIFIED | WebSocket /ws, POST /api/event, ids event-btn/event-label/event-ack |
| `src/jabuka/common/{clock,messages,atomicio,sdnotify,units,conventions}.py` | Contracts | ✓ VERIFIED | GpsClock + make_clock("gps") |
| `src/jabuka/ingest/{gpsd_client,nmea}.py`, `sim/fake_gpsd.py` | GPS path | ✓ VERIFIED | Wired from `CoreContext.startup` |
| `src/jabuka/tools/probe.py` | fastnet-probe | ✓ VERIFIED | Spot-checked exit codes 0/3/1 |
| `src/jabuka/sim/{pty_replay,msg_replay,synth}.py`, `ingest/fastnet_encode.py` | L0/L1/L2 replay + sim | ✓ VERIFIED | Fault flags listed in `--help` |
| `src/jabuka/tools/logcheck.py` | jabuka-logcheck | ✓ VERIFIED | Used in the crash-recovery test |
| `deploy/provision.sh`, `deploy/systemd/*`, `deploy/udev/99-jabuka.rules`, `deploy/gpsd.default`, `deploy/chrony-gps.conf` | Appliance provisioning | ✓ VERIFIED (static) | Dry run exits 0 without root; runtime on the Pi is a human check |
| `deploy/requirements.lock` | Hash lock | ✓ VERIFIED | 324 hashes, 17 packages |
| `deploy/wheelhouse/` | Offline wheels | ⚠️ ABSENT in main checkout | Gitignored build output; rebuild before the Pi install |
| `deploy/PI-SETUP.md` | Runbook (≥120 lines) | ✓ VERIFIED | 328 lines, items a-m |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| fastnet_main.py | rawlog.py | `write_chunk(b)` before `framer.feed(b)` | ✓ WIRED |
| fastnet_main.py | core/bus.py | `delta_message` + `health_message` over UDP 127.0.0.1:47100 | ✓ WIRED |
| core/bus.py | core/state.py | `on_message` to `update_values` / `update_health` | ✓ WIRED |
| diag.js | core/web.py | `new WebSocket(.../ws)` + `fetch("/api/event")` | ✓ WIRED |
| tools/probe.py | serial_ro.py / bus_health.py | `open_fastnet`, `classify(` | ✓ WIRED |
| core/main.py | gpsd_client.py / clock.py | `run_gpsd_client` task; `on_tpv` before t_rx | ✓ WIRED |
| sim/synth.py | conventions.py / fake_gpsd.py | `apparent_from_true`, embedded `FakeGpsd` | ✓ WIRED |
| sim/msg_replay.py | core/bus.py | UDP datagrams with t_sim | ✓ WIRED |
| provision.sh | systemd units / requirements.lock | `systemctl enable jabuka-ingest-fastnet.service jabuka-core.service`; `--require-hashes` | ✓ WIRED |
| jabuka-core.service | core CLI | `--clock gps --gpsd 127.0.0.1:2947` parsed by the real parser | ✓ WIRED (01-03 skip gone) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| diag page values table | `msg.values` | /ws diag, built from StateStore filled by UDP deltas from the ingest (pyfastnet decode of real bytes) and from gpsd | Yes (tracer and synth pty tests decode real frames) | ✓ FLOWING |
| diag health | `msg.health` | ingest 1 Hz heartbeat, gpsd client health | Yes | ✓ FLOWING |
| clock badge | `msg.clock.routing_time_gate` | `clock.status()` (GpsClock on the Pi) | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full gate | `bash scripts/check.sh` | ruff clean, 68 files formatted; 295 passed + 1 skipped on 3.14 and on 3.13; `check: ok` | ✓ PASS |
| Probe OK verdict | `fastnet-probe --file example2 --out ...` | "VERDICT: OK — 105.1 frames/s, 54 channels", rc 0 | ✓ PASS |
| Probe swap-wires | `fastnet-probe --file <inverted example2>` | "swap White/Green (A/B)", rc 3 | ✓ PASS |
| Probe missing device | `fastnet-probe --device <nonexistent>` | rc 1 | ✓ PASS |
| Provision dry run | `bash deploy/provision.sh --dry-run --psk-file deploy/secrets.env.example` | rc 0; PSK masked `***`; AP 10.42.0.1/24; enable both units | ✓ PASS |
| Unit/CLI contract | `pytest tests/deploy/test_units.py tests/deploy/test_lock.py -rs` | 17 passed, 1 skipped (wheelhouse absent only) | ✓ PASS |
| CLI help contracts | `jabuka-core/-sim/-replay/-replay-msgs/-logcheck --help` | `--clock {system,sim,gps}`, `--gpsd`; 4 fault kinds; fault flags; `--speed`/`--udp` | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes are declared or present. Step 7c: N/A. `fastnet-probe` is a product CLI and was spot-checked above.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| DATA-01 | 01-04 | Pi OS Lite 64-bit, Wi-Fi AP at fixed IP, no internet | ? NEEDS HUMAN | provision.sh AP section + dry run; real flash/AP join pending |
| DATA-02 | 01-01, 01-02, 01-04 | Receive-only via DTECH, raw bytes to disk before decoding | ✓ SATISFIED (software) | O_RDONLY, AST guard, udev 0640, raw-first; FTDI parity on hardware pending |
| DATA-03 | 01-01 | Decode channels into normalized state with units, source, age | ✓ SATISFIED | decode enumeration; StateStore rows |
| DATA-04 | 01-03, 01-04 | VK-162 GPS, clock from GPS, routing blocked until valid | ✓ SATISFIED (software) | gpsd client, GpsClock gate; chrony on hardware pending |
| DATA-05 | 01-02 | fastnet-probe verdict, swap-wires hint, inventory | ✓ SATISFIED | probe tests + spot-checks; on-boat run pending |
| DATA-06 | 01-01, 01-02, 01-03 | Replay and synthetic sim with faults at speed through the same pipeline | ✓ SATISFIED | L0/L1/L2 tests |
| DATA-07 | 01-01 | Raw + 1 Hz derived logging; event marker from UI | ✓ SATISFIED | test_logging, test_event_marker; browser click is a human check |
| HELM-05 | 01-01, 01-02, 01-03 | Diagnostics: every value with source and age, bus/GPS/routing health | ✓ SATISFIED | diag message + page; routing health is the time gate now (a routing row is Phase 3 per ROADMAP note) |
| REL-01 | 01-01, 01-04 | Auto-start, auto-restart, survive power cuts | ✓ SATISFIED (software) | units, sd_notify, crash-recovery tests; power pulls on the Pi pending |

All 9 phase requirement IDs are claimed by at least one plan. REQUIREMENTS.md maps no other ID to Phase 1, so there are no ORPHANED requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| (all phase files) | — | TBD/FIXME/XXX | none found | — |
| src/jabuka/sim/synth.py | 4, 102 | "placeholder BSP curve" | ℹ️ Info | Intended: dev simulator only; the real polar is Phase 2 WIND-01 |
| various | — | bare `pass` in except blocks | ℹ️ Info | Cleanup/teardown paths only, not stubs |

### Warnings / Info (non-blocking)

- ⚠️ **Wheelhouse absent in the main checkout.** `deploy/wheelhouse/` is gitignored and was built in the executor's worktree. tests/deploy/test_lock.py skips its wheelhouse checks here. Run `bash scripts/build-wheelhouse.sh` (needs PyPI) before the Pi install; PI-SETUP section 0 already lists this. A real provision.sh run exits 3 without it.
- ℹ️ **MVP goal format.** ROADMAP Phase 1 has `Mode: mvp`, but its `**Goal:**` line is not a user story. The plans carry a valid restatement, which this report used. Consider updating ROADMAP.md.
- ℹ️ **fastnet2ip Plan B** runs as root and opens the port read/write. "No process on the Pi can transmit" holds for the enabled stack. The Plan B is manual-only, has no [Install] section and Conflicts= with the ingest both ways (accepted risk T-04-02).
- ℹ️ Before GPS sync the clock status shows `system_clock: "unknown"` and `time_valid: false` rather than the literal word "unsynced". The gate badge reads "routing: blocked". This meets SC3's intent.

### Human Verification Required

1. **Flash and provision the Pi** (PI-SETUP 1-3, after building the wheelhouse). Expected: both units enabled, and both services active after a headless reboot.
2. **Tablet joins the AP** and opens http://10.42.0.1/. Expected: the diagnostics page renders live values and health with no internet.
3. **Browser page behaviour** (local replay or the Pi). Expected: rows show unit, src, ref and age; they go stale when the feed stops; the event marker ack appears and the marker lands in events-*.jsonl.
4. **Device checks**: `stty -F /dev/fastnet`, `ls -l`, `lsof`, `lsusb`. Expected: 28800 parenb parodd cs8 cstopb; 0640 root:dialout; only the ingest holds the port; IDs 0403:6001 and 1546:01a7.
5. **Probe on hardware**: NO BYTES (exit 2) with no bus; OK at the boat on 12 Nov.
6. **GPS time**: gpspipe mode 3, `chronyc sources` shows `#* GPS`, `date -u` correct within 1 s after a reboot with no internet, and the gate goes from blocked to ok.
7. **REL-01 on hardware**: kill -9 recovery, unplug/replug, 5 power pulls with jabuka-logcheck exiting 0 each time, watchdog armed.
8. **Review the package lock** (17 expected names).

### Gaps Summary

No gaps. Every must-have that can be checked off the hardware is present, substantive, wired and exercised by a passing test on Python 3.14 and 3.13. Phase completion now waits only on the hardware checks above (Pi flash and provisioning, AP/tablet, real FTDI parity, GPS-disciplined system clock, power pulls) and on rebuilding the gitignored wheelhouse before the Pi install.

---

_Verified: 2026-11-06T02:45:00Z_
_Verifier: Claude (gsd-verifier)_
