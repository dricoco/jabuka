---
phase: 01-foundation-data-backbone-bus-test-kit
plan: 01
subsystem: data-backbone
status: complete
tags: [walking-skeleton, fastnet, pyfastnet, receive-only, fastapi, websocket, logging, systemd, sd_notify]
requires: []
provides:
  - "pyproject.toml with pinned deps and all 8 console scripts (wave-2 plans never edit it)"
  - "jabuka.common.{clock,messages,atomicio,sdnotify} contracts (UDP schema v1, injected Clock)"
  - "jabuka.ingest.{serial_ro,fastnet_framing,fastnet_decode,rawlog,fastnet_main} (jabuka-ingest-fastnet)"
  - "jabuka.core.{state,bus,derived_log,web,main} (jabuka-core) + diagnostics page with event marker"
  - "jabuka.sim.pty_replay (PtyFeeder, replay_bytes, jabuka-replay)"
  - "tests/fixtures/fastnet (10 MIT captures pinned to SHAs) + tests/conftest.py fixtures"
affects: [01-02, 01-03, 01-04, phase-2, phase-3, phase-4]
tech-stack:
  added: [pyfastnet 3.2.1, pyserial 3.5, fastapi 0.162.0, uvicorn 0.54.0, websockets 17.4, pytest 9.2.0, pytest-asyncio 1.4.1.post1, httpx 0.28.1, ruff 0.17.4, hatchling]
  patterns: [raw-first logging, kernel-enforced O_RDONLY serial, counting framer proven equivalent to pyfastnet, ref-neutral M/T paths with ref field, injected Clock (SimClock/SystemClock), bounded drop-oldest WS fan-out, exclusive-create rotating logs, atomic write + .bak, standalone sd_notify]
key-files:
  created:
    - pyproject.toml
    - scripts/bootstrap-dev.sh
    - scripts/check.sh
    - src/jabuka/common/clock.py
    - src/jabuka/common/messages.py
    - src/jabuka/common/atomicio.py
    - src/jabuka/common/sdnotify.py
    - src/jabuka/ingest/serial_ro.py
    - src/jabuka/ingest/fastnet_framing.py
    - src/jabuka/ingest/fastnet_decode.py
    - src/jabuka/ingest/rawlog.py
    - src/jabuka/ingest/fastnet_main.py
    - src/jabuka/core/state.py
    - src/jabuka/core/bus.py
    - src/jabuka/core/derived_log.py
    - src/jabuka/core/web.py
    - src/jabuka/core/main.py
    - src/jabuka/sim/pty_replay.py
    - src/jabuka/web/static/index.html
    - src/jabuka/web/static/diag.js
    - src/jabuka/web/static/diag.css
    - tests/conftest.py
    - tests/fixtures/fastnet/SOURCES.md
    - tests/test_tracer_e2e.py
    - tests/test_framing_equivalence.py
  modified: []
decisions:
  - "CountingFramer equivalence is measured by feeding captures line-by-line and draining after each chunk, because FrameBuffer trims to 8192 bytes on add and its queue holds 1000 frames"
  - "decode_to_values maps projected paths back to rich entries by projecting each entry alone; routed channels 0x49/0x6D/0x84 get ref-neutral paths and ref from layout (M/T/?)"
  - "jabuka-core runs a uvicorn.Server subclass (CoreServer) with loop signal handlers, because stock uvicorn 0.54 re-raises SIGTERM after shutdown and the process would exit -15 rather than 0"
  - "Core logs (bus, derived, events) run on the injected clock, so sim replays rotate on sim time; disk guard prefixes are fastnet (raw) and bus (bus), with none for derived and events"
  - "The tick loop's first target is computed in startup(), so a sim advance right after startup never skips the first second"
metrics:
  duration: "~40 min"
  completed: 2026-11-06
  tasks: 3
  files: 41
plan_head_before: 3510091894eba383e9361a07b122838f26b4424b
actuals:
  tokens: 35900
  tasks: 3
  commits: 5
---

# Phase 1 Plan 01: Walking Skeleton Summary

A recorded B&G Fastnet capture is replayed byte-for-byte into a pty and read by the receive-only (O_RDONLY) ingest. The ingest writes the raw log first, then frames the bytes with a counting framer proven equivalent to pyfastnet, decodes them with pyfastnet while keeping M/T as `ref`, and sends UDP schema-v1 deltas. The core keeps them in a StateStore on an injected clock and serves them over `/api/state`, `/ws` and a diagnostics page. From that page an event marker lands in an fsync'd JSONL file. Rotating raw, bus, derived (1 Hz) and event logs, atomic files and systemd notify/watchdog are included. The suite passes on Python 3.14 and 3.13.

## What was built

- **Scaffold:** hatchling `pyproject.toml` with exact pins and all 8 console scripts declared, so 01-02, 01-03 and 01-04 never touch it. Ruff targets py313. pytest uses `asyncio_mode=auto` and `--import-mode=importlib`, plus a filterwarnings entry for the starlette httpx deprecation (category and message read from the installed `starlette/testclient.py`). `scripts/bootstrap-dev.sh` is idempotent and worktree-safe (it checks that `jabuka.__file__` is inside this checkout). `scripts/check.sh` runs ruff lint, ruff format check, and pytest on `.venv` (3.14) and `.venv313` (3.13).
- **Fixtures:** 8 pyfastnet captures (pinned to `59bc23be…`) and 2 fastnet2ip captures (pinned to `9e6ac449…`), plus both MIT licences. `SOURCES.md` records the repo, SHA, original path, file bytes and sha256 for each, and notes that big.txt is byte-identical in both repos.
- **Ingest:** `ReadOnlySerial`/`open_fastnet` open 28800 8O2 O_RDONLY. `CountingFramer` with `FramerStats`, `load_capture` (hex-per-line or Jabuka raw log, torn last line tolerated) and `chunks_from_capture`. `decode_to_values` keeps ref M/T/?, ch and disp, applies `awa_sign`, and collects unknown_ch. `RotatingAppendLog`: hourly or 32 MB rotation, flush every 1 s and fsync every 10 s on the injected mono clock, exclusive create, and a disk guard. `iter_log_lines` skips a torn last line. `FastnetIngest.on_chunk`: raw first, then framer, then decode, then a UDP delta with a bus block. It never raises.
- **Core:** `StateStore` keyed by (path, src), with longest-prefix staleness, merged health and `latest()` arbitration. The UDP `BusProtocol` keeps `udp_rx`/`udp_rejected` counters and writes the bus log. The 1 Hz tick writes the derived JSONL and then publishes the diag message to the `Hub` (bounded queue of 4 per client, drops the oldest). `POST /api/event` takes a pydantic label (max 200), strips control characters, is rate-limited to 1/s (429) and writes fsync'd JSONL with `state_ref`. Static files are mounted last.
- **Page:** plain HTML + ES module, dark high-contrast. It has a values table with fresh/aging/stale classes and SI→display formatting (deg, kn, m, °C, deg+decimal minutes), generic per-source health tables, a large routing-gate badge, core counters, a connection indicator with 1→5 s backoff, and the event panel (`event-label`, `event-btn`, `event-ack`).
- **Replay:** `PtyFeeder` (EAGAIN-safe write, close = unplug, reopen = replug with an atomic symlink re-point) and `replay_bytes` paced at 2400 B/s × speed. `jabuka-replay CAPTURE [--speed] [--link] [--loop]`.
- **Reliability:** `atomicio` (tmp + fsync + rename + dir fsync, `.bak`) and `sdnotify` (filesystem and `@abstract` sockets, `WATCHDOG_USEC/2`, respects `WATCHDOG_PID`). Both entrypoints send READY=1, ping WATCHDOG=1 from the loop, and on SIGTERM/SIGINT send STOPPING=1, close (fsync) every log and exit 0.

## Test results

- `bash scripts/check.sh`: ruff check clean, ruff format clean. **76 passed** on Python 3.14.7 and **76 passed** on Python 3.13.12 (about 8.6 s each). Three repeated 3.14 runs were also all green.
- Tracer: `test_in_process_core` covers pty, subprocess ingest, UDP, TestClient core, `/api/state`, `/ws` and the raw log, which is byte-identical to the replayed bytes. `test_full_stack_subprocesses` runs `jabuka-replay --link --loop`, `jabuka-ingest-fastnet` and `jabuka-core`, then queries over real HTTP.
- Framing equivalence: 10/10 captures match FrameBuffer(project=True) with golden counts 937, 2018, 2630, 2801, 164, 422, 161, 189, 2433 and 3392.
- rawfn capture: heading arrives with ref `M` and with ref `?`, never `T`.

## TDD Gate Compliance (tasks 2 and 3)

- Task 2: RED `e60a2b3`, where 15 of 19 tests failed for missing behaviour (4 already passed on Task 1's naming and torn-line basics), then GREEN `c95a7b4`.
- Task 3: RED `1f0575f` (atomicio/sdnotify modules missing, decoder exception not contained; the datagram validation tests already passed because Task 1's `messages.decode` covered them), then GREEN `9d4f1fa`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The tick loop skipped the first second under SimClock**
- **Found during:** Task 2 (`test_derived_log_1hz_under_simclock` produced 9 lines, not 10)
- **Issue:** the loop computed its first target only when the task first ran, which could be after the clock had already advanced
- **Fix:** `startup()` computes `floor(now)+1` synchronously and passes it to `_tick_loop`
- **Files:** src/jabuka/core/main.py. **Commit:** c95a7b4

**2. [Rule 1 - Bug] uvicorn re-raises SIGTERM after a graceful shutdown (exit -15, not 0)**
- **Found during:** Task 3 design (read `uvicorn/server.py` `capture_signals`)
- **Fix:** `CoreServer(uvicorn.Server)` overrides `capture_signals` with `loop.add_signal_handler`. The handler sends STOPPING=1 and sets should_exit. The exit code is 0 after a signal or a started server, and 1 when startup failed.
- **Files:** src/jabuka/core/main.py. **Commit:** 9d4f1fa

**3. [Rule 2 - Missing critical] Raw-log flush when the bus goes quiet, and non-fatal raw write errors**
- **Issue:** the flush/fsync cadence is applied on write, so a silent bus would leave the last bytes buffered. A disk error in `write_chunk` would also have killed the read path.
- **Fix:** the ingest runs a 1 s `maybe_flush` task, and the core tick calls `maybe_flush` on every log. `on_chunk` counts `raw_errors` instead of raising.
- **Files:** src/jabuka/ingest/fastnet_main.py, src/jabuka/core/main.py. **Commits:** c95a7b4, 9d4f1fa

**4. [Rule 1 - Test bug] Race in the ingest lifecycle test**
- **Issue:** `ReadOnlySerial.open()` flushes the tty input queue, so the frame written before the ingest opened the pty was discarded
- **Fix:** the frame is written after READY=1. The in-process tracer likewise waits until the ingest holds the pty fd (via /proc), plus 0.5 s.
- **Files:** tests/test_sdnotify.py, tests/test_tracer_e2e.py. **Commit:** 9d4f1fa

### Interpretations and additive extensions (no contract renamed or removed)

- Equivalence test: FrameBuffer is fed capture line by line and drained after every chunk. One `add_to_buffer` of a whole capture would trim it to 8192 bytes, and the queue holds at most 1000 frames. Dispatch mirrors `decode_and_queue_frame` exactly, including `decode_light_frame` for 0xC9 and dropping empty projections.
- Added beyond the interfaces block: a `"type"` key in delta and health messages; `stale_after_s` per diag row (drives the page's "aging" colour); `system_utc` and `sim_mono` in clock status; `chunks_from_capture`; `FastnetIngest.raw_errors`/`send_errors`/`messages_sent`; `RotatingAppendLog.rotations`/`lines_written`; `CoreContext.record_event`, `close_logs`, `CoreContext.create(...)`; conftest fixtures `wait_until` and `process_has_open`.

## Notes for wave-2 plans

- `ReadOnlySerial.open()` flushes pending input (pyserial `_reset_input_buffer`). Bytes written into a `PtyFeeder` before the reader opens are lost. Wait for READY=1 (NOTIFY_SOCKET) or for the fd to be open before replaying.
- `jabuka-ingest-fastnet` currently exits with code 3 on device EOF/EIO and code 2 if the device can't be opened. Plan 01-02 adds the reconnect loop.
- `jabuka-core --clock` accepts `system|sim`. Plan 01-03 adds `gps` and `--gpsd`.
- tests/conftest.py exposes `fixtures_dir`, `capture_bytes`, `free_udp_port`, `free_tcp_port`, `tmp_data_dir`, `sim_clock`, `wait_until` and `process_has_open`.

## Human check (end of phase, non-blocking)

Run the three README commands and open http://127.0.0.1:8080/. Stop `jabuka-replay` and check that the rows turn stale. Press "Event marker" with a label, then confirm the acknowledgement and a new line in `var/logs/events/events-*.jsonl`. Parity (PARENB) can only be checked on the real FTDI with `stty -F /dev/fastnet`.

## Known Stubs

None. Every page element is wired to live data.

## Threat Flags

None. All new surface (UDP listener on 127.0.0.1, `/api/event`, `/ws`, log files) is in the plan's threat register, with its mitigations implemented and tested (T-01-01 to T-01-08).

## Self-Check: PASSED

- Files exist: pyproject.toml, src/jabuka/{common,ingest,core,sim}/*.py, src/jabuka/web/static/{index.html,diag.js,diag.css}, tests/fixtures/fastnet (10 .txt + SOURCES.md + 2 LICENSE)
- Commits exist: e0e4c3c, e60a2b3, c95a7b4, 1f0575f, 9d4f1fa
