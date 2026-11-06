---
phase: 01-foundation-data-backbone-bus-test-kit
plan: 02
subsystem: bus-test-kit
status: complete
tags: [fastnet-probe, bus-health, receive-only, reconnect, heartbeat, replay, fault-injection, L1]
requires:
  - "01-01: serial_ro.open_fastnet, CountingFramer/load_capture, decode_to_values, RotatingAppendLog/iter_log_lines, FastnetIngest, messages, atomicio, PtyFeeder/replay_bytes, CoreContext/create_app"
provides:
  - "jabuka.ingest.bus_health: STATES, classify(), WindowStats, HINT_* strings"
  - "jabuka.ingest.fastnet_records: iter_records(), layout_code(), record_hex()"
  - "fastnet-probe (jabuka.tools.probe: run_probe, main, Inventory, read_icount): live + --file, inventory.json, capture.log, exit codes 0/2/3/4/5/1"
  - "jabuka-ingest-fastnet: DeviceReader reconnect loop + 1 Hz health_message('fastnet') heartbeat; bandg.layoutRecord.0xNN for ref-unknown Heading/TWD/Set"
  - "jabuka.sim.pty_replay: replay_bytes(invert, garbage_rate, silences, rng); jabuka-replay --invert --garbage-rate --seed --silence --unplug-at --replug-after"
  - "jabuka-replay-msgs (jabuka.sim.msg_replay: replay_messages, main): L1 replay of bus logs with t_sim"
  - "tests/bus/: conftest (running_replay, probe_out_dir, terminate) + static receive-only AST guard"
affects: [01-03, 01-04, phase-2, phase-4]
tech-stack:
  added: []
  patterns: [shared verdict rules for probe and heartbeat, reconnect-forever device loop, heartbeat independent of byte arrival, AST guard as security test, duck-typed replay writer for unplug]
key-files:
  created:
    - src/jabuka/ingest/bus_health.py
    - src/jabuka/ingest/fastnet_records.py
    - src/jabuka/tools/probe.py
    - src/jabuka/sim/msg_replay.py
    - tests/bus/conftest.py
    - tests/bus/test_bus_health.py
    - tests/bus/test_records.py
    - tests/bus/test_probe.py
    - tests/bus/test_ingest_resilience.py
    - tests/bus/test_no_write_path.py
    - tests/bus/test_msg_replay.py
  modified:
    - src/jabuka/sim/pty_replay.py
    - src/jabuka/ingest/fastnet_main.py
    - src/jabuka/ingest/serial_ro.py
decisions:
  - "classify() treats a valid ratio below 0.1 as 'no valid frames': random bytes pass both 8-bit checksums about once per 65k bytes (the byte-inverted example2 capture yields exactly 1 frame), so frames_ok == 0 alone misread swapped wires as NOISY"
  - "The ingest attempts the first open before READY=1 (READY still means 'device open' when present) but sends READY even when the device is absent, so systemd Type=notify never times out on a missing adapter"
  - "fastnet-probe enforces a 5 s minimum window only in the CLI for live devices; run_probe() accepts any duration (tests use 2-3 s)"
  - "--file mode uses equivalent wire time (bytes / 2400 B/s) as its window for frames/s"
  - "capture.log is the RotatingAppendLog part file renamed on finish (parts concatenated if an hour boundary rotated it); interrupted probes leave replayable capture-*.log parts"
  - "msg_replay sets t_sim from the bus-log line's t_wall (core receipt time), per plan; an existing t_sim is kept"
metrics:
  duration: "~35 min"
  completed: 2026-11-06
  tasks: 3
  files: 14
plan_head_before: f878a42cbbeb4fb39c6e522af3ee2bf4776fa9aa
actuals:
  tokens: 24700
  tasks: 3
  commits: 7
---

# Phase 1 Plan 02: Bus-Test Kit Summary

`fastnet-probe` gives a wiring verdict (OK / NO BYTES / swap White-Green A/B / NOISY / FEW BYTES) with exit codes, an `inventory.json` (per channel: name, count, last value and display, layouts, layout codes, raw record hex) and a replayable `capture.log`. The ingest now reconnects forever on unplug or absence and sends a 1 Hz bus-health heartbeat even on a silent bus. An AST test guards receive-only. `jabuka-replay-msgs` replays core bus logs at speed into a `--clock sim` core.

## What was built

- **bus_health:** `classify()` with the plan's rule order and hints, plus `WindowStats`. WindowStats keeps the newest snapshot at or before the cutoff as the baseline, restarts the window if time goes backwards, and never reports a negative delta after a counter reset. The probe and the ingest heartbeat share both.
- **fastnet_records:** `iter_records()` walks a Broadcast body using pyfastnet's private `_FORMAT_SIZE_MAP`. A truncated trailing record ends the walk quietly. On all 10 fixtures it matches `decode_frame`: same names, records tile the body exactly, and each record decodes identically. `layout_code()` reads `layoutBits` (byte/mask/shiftRight) or `layoutByte` from the installed fastnet.json templates and returns None otherwise.
- **fastnet-probe:**
  - Live mode: `open_fastnet` (O_RDONLY), then a select/os.read loop for `--seconds`. Raw-first `capture.log` via RotatingAppendLog. TIOCGICOUNT deltas are reported, or null on ENOTTY. EOF or EIO mid-probe is reported.
  - `--file` mode: analyses an existing capture.
  - Inventory: per-channel accumulation, raw records (up to 5 distinct) for 0x49, 0x6D and 0x84 and any TBC/None layout, from_addresses with names, by_command, undecoded commands and decode errors. Written with `atomic_write_json`.
  - Output: a human report (verdict line first, then stats, channel table, from-addresses, and a reminder to cycle every display page) or `--json`. `--help` says to stop jabuka-ingest-fastnet first.
- **pty_replay (additive):** `replay_bytes` gains `invert`, `garbage_rate`, `silences` (pacing shifts after a silence instead of bursting) and `rng`. The CLI gains `--invert`, `--garbage-rate`, `--seed`, `--silence START:DUR` (repeatable), `--unplug-at T` and `--replug-after D`. The unplug flags use a duck-typed writer that drops bytes while unplugged, as a real cable does. The `PtyFeeder` class is unchanged.
- **Ingest:**
  - `DeviceReader` reconnect loop: retries every 1 s, backing off to at most 2 s. EIO/EOF closes the port and marks it missing. The framer buffer is cleared on reconnect so bytes from before the loss are never spliced onto the new stream. `reconnects` and `last_error` are tracked.
  - Heartbeat task (1 Hz): `health_message("fastnet", {device, state, hint, bytes_per_s, frames_per_s, bytes_in, bytes_discarded, frames_ok, decode_errors, unknown_ch≤50, reconnects, last_error})`.
  - Decoding and logging: per-frame decode stays in try/except and raw-first. Routed channels with ref "?" also publish `bandg.layoutRecord.0xNN` with the record hex.
  - Unchanged: CLI flags and log formats.
- **msg_replay:** `replay_messages(paths, *, speed, udp, loop)` returns (sent, skipped). It skips bad lines (no 3 fields, non-float times, `messages.decode` None, re-encode failure) and counts send errors as skips. Gaps that are negative or over 60 s are clamped to 0. The CLI prints `sent N, skipped M`.

## Test results

- `bash scripts/check.sh`: ruff check clean and ruff format clean. **148 passed** on Python 3.14.7 and **148 passed** on Python 3.13.12 (about 44 s each, up from 76 tests). Repeated runs of the resilience and probe tests (3 times) were all green.
- Probe verdicts over a pty: example2 is ok (exit 0, channels include 0x41/0x49/0x51, capture.log reloads byte-identical to the 66425 bytes replayed); inverted is no_frames (exit 3); silent is exit 2; garbage 0.5 is noisy (exit 4). CLI `--file` cases give 0, 3, 4, 2 (empty) and 5 (few bytes). A live silent pty gives exit 2 (the CLI raised the window to 5 s). A missing device gives exit 1.
- `fastnet-probe --file rawfn... --json` exits 0. In its 0x49 entry, `layout_codes_seen` is `["0x66"]` and `raw_records` includes `490600bee8e8`.
- Resilience (subprocess ingest):
  - Unplug: device reported missing within 3 s, process stays alive.
  - Replug: device ok within 3 s with `reconnects >= 1`, and frames resume.
  - Absent device at start: reported missing until the path appears, then ok.
  - Silent bus: 5-8 heartbeats in 6 s, and core diag shows `health.fastnet.alive=true` with `state="silent"`.
- AST guard: no violations in `ingest/` + `tools/`. 12 positive controls and 4 negative controls (including the `ReadOnlySerial(serial.Serial)` base class) confirm the guard flags what it should and nothing else. A `ReadOnlySerial` fd is O_RDONLY, and `os.write` on it gives EBADF.
- L1: 40 deltas were recorded by a live core over about 1.2 s and replayed at speed 20 into a SimClock core. The fastnet paths match, and the sim UTC equals the last recorded t_wall (sim monotonic = recorded span).

## TDD Gate Compliance

- Task 1: RED `4391a78` (collection errors: modules absent; implementation moved aside for the run) → GREEN `63da111`.
- Task 2: RED `995a692` (6 resilience tests failing on the plan-01 ingest; the 19 AST-guard tests already pass, as they should for a guard over code that was already clean) → GREEN `581962a`.
- Task 3: RED `eae0c74` (collection error: msg_replay absent) → GREEN `f4c634e`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The verdict rule misclassified swapped wires as NOISY**
- **Found during:** Task 1, an experiment with the byte-inverted example2 capture
- **Issue:** `frames_ok == 0` is not reliable. Inverted bytes produced 1 coincidental frame (command 0xCD), with valid_ratio 0.007, which classified as "noisy" instead of "no_frames" (exit 4 instead of 3).
- **Fix:** a valid ratio below `NO_FRAMES_MAX_RATIO = 0.1` counts as no valid frames. All 5 plan behaviour cases still hold, and a dedicated test pins the inverted-capture counters.
- **Files:** src/jabuka/ingest/bus_health.py, tests/bus/test_bus_health.py. **Commit:** 63da111

**2. [Rule 1 - Plan expectation corrected] rawfn heading "other layout code"**
- **Issue:** the plan expected `layout_code` on rawfn heading records to return 0x66 "and at least one other code". In fact the non-°M heading records in rawfn are format 0x06 segment-display records (`490600bee8e8`, which shows " OFF"). That format has no layout field, so the second value is None, not a code. This is also why heading shows ref "?" in that capture: it is a display-only "OFF", not an unknown °T byte.
- **Fix:** the test asserts that 0x66 is present, that a None (no-layout) record is present, and that its raw record is `490600bee8e8`. The probe keeps such raw records in the inventory.
- **Files:** tests/bus/test_records.py, tests/bus/test_probe.py. **Commit:** 63da111

**3. [Rule 2 - Missing critical] READY=1 when the device is absent**
- **Issue:** the plan-01 ingest sent READY only after a successful open. With a reconnect-forever loop and a missing adapter, systemd `Type=notify` would time out and restart the service.
- **Fix:** the ingest tries one open first (so READY still implies an open device whenever it exists, which keeps test_sdnotify's ordering), then sends READY regardless and keeps retrying in the background.
- **Files:** src/jabuka/ingest/fastnet_main.py. **Commit:** 581962a

**4. [Rule 1 - Bug, raised by the orchestrator from plan 01-04] Reopening the same tty failed with EINVAL**
- **Issue:** on this laptop (glibc 2.43), after one `open_fastnet()` the pty reports the custom speed literally (ispeed/ospeed = 28800) and has dropped parity. pyserial's next `tcsetattr` is then rejected with EINVAL, so a second `open_fastnet()` on the same tty failed. That breaks an ingest restart or a reconnect to a tty that did not disappear. Reproduced: open 0 ok, opens 1 and 2 `error(22)`.
- **Fix:** before `_reconfigure_port`, `ReadOnlySerial.open()` resets the tty to B38400 with PARENB and PARODD cleared (best effort). Then pyserial applies 28800 8O2 as before. The fd stays O_RDONLY.
- **Test:** `test_open_fastnet_reopens_the_same_tty` (3 consecutive opens on one pty) passes on 3.14 and 3.13.
- **Files:** src/jabuka/ingest/serial_ro.py (plan 01-01's file, touched with orchestrator permission), tests/bus/test_no_write_path.py. **Commit:** 6f5f5af

### Interpretations and additive extensions

- `run_probe` has extra keywords `file_mode` (default: auto-detected from a regular file) and `on_open` (a callback once the port is open and flushed, used by tests to start the replay without racing the open-time input flush). It also adds state `"missing"` (exit 1) for an unopenable device.
- The inventory adds `mode`, `file`, `capture`, `formats_seen`, `si_values`, `paths` and `stats.valid_ratio`/`unknown_ch`. Channel keys are pyfastnet-style uppercase hex (`"0x6D"`).
- `fastnet_records.record_hex()` was added and is shared by the probe and the ingest.
- `FastnetIngest` adds `health()`, `send_heartbeat()`, `channels_seen`, `device_open`, `reconnects` and `last_error`. The per-frame `bus.unknown_ch` is also capped at 50.
- Tests live in the plan's files only. The replay fault-injection unit tests are in tests/bus/test_probe.py, since no dedicated pty_replay test file was listed.

## Notes for later plans

- To find the °T layout byte on 12 Nov: run `fastnet-probe --device /dev/fastnet --seconds 60` while cycling Heading/TWD/Set to True on a B&G display, then read `channels["0x49"].layout_codes_seen` and `raw_records`. Any code other than 0x66 is a °T candidate. A ref "?" on the diagnostics page now comes with `bandg.layoutRecord.0xNN`.
- `jabuka-replay --link X --unplug-at T --replug-after D` reproduces adapter loss for soak tests (Phase 4).

## Human check (end of phase, non-blocking)

- On the Pi with the DTECH plugged in and the ingest stopped: `fastnet-probe --device /dev/fastnet --seconds 10` with no bus connected should give NO BYTES and exit 2. At the boat (12 Nov) it should give OK. Keep inventory.json and capture.log.
- With the ingest running: `stty -F /dev/fastnet` should show 28800 parenb parodd cs8 cstopb. Unplug and replug the DTECH. The diagnostics page should go fastnet missing and then recover, with `NRestarts` unchanged.

## Known Stubs

None.

## Threat Flags

None. All new surface is in the plan's register: the probe opens via open_fastnet (T-02-01), the AST guard covers ingest/ and tools/, reconnect plus per-frame try/except (T-02-02), skip-and-count parsers (T-02-03), and atomic inventory (T-02-05). One limit: `load_capture` (plan 01-01) raises on a non-hex line that is not the last line. The probe CLI catches this and exits 1 with a message rather than crashing.

## Self-Check: PASSED

- Files exist: src/jabuka/ingest/{bus_health,fastnet_records}.py, src/jabuka/tools/probe.py, src/jabuka/sim/msg_replay.py, tests/bus/{conftest,test_bus_health,test_records,test_probe,test_ingest_resilience,test_no_write_path,test_msg_replay}.py
- Commits exist: 4391a78, 63da111, 995a692, 581962a, eae0c74, f4c634e, 6f5f5af
