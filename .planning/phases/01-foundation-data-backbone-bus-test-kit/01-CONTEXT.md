# Phase 1: Foundation, Data Backbone & Bus-Test Kit - Context

**Gathered:** 2026-11-06
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted — user is AFK and explicitly asked to "continue without me". All decisions below are Claude's recommended answers, grounded in `.planning/research/SUMMARY.md`. Revisit if the user objects.

<domain>
## Phase Boundary

Pi boots headless into a receive-only data backbone that records then decodes Fastnet + GPS, normalizes into one state store with units/source/age, logs raw + 1 Hz, and exposes a diagnostics web page over the Pi's Wi-Fi AP. Every later feature can be developed and tested on the dev laptop against replayed captures or a synthetic simulator. A `fastnet-probe` tool diagnoses the bus on the boat in minutes.

Not in this phase: polar, laylines, map, helm view, routing, GRIB (Phases 2–3).

</domain>

<decisions>
## Implementation Decisions

### Repo layout & tooling
- Single Python package `jabuka/` (src layout: `src/jabuka/`), Python ≥3.13 target (Pi Trixie), developed on the laptop (Python 3.14 locally is fine; keep code 3.13-compatible), managed with `uv`, tests with `pytest`, lint with `ruff`.
- Subpackages: `common/` (units, angles, conventions, clock, atomic IO), `ingest/` (fastnet, gps), `core/` (state store, wind source arbitration stub, logging, web), `sim/` (replay + synthetic boat), `tools/` (fastnet-probe), `deploy/` (Pi provisioning, systemd units, udev rules).
- Frontend: plain static HTML/ES modules served by FastAPI, no JS build chain.

### Ingest architecture
- Own `ingest-fastnet` process using **pyfastnet** directly (not fastnet2ip NMEA), owning `/dev/fastnet` (udev by-id symlink to the DTECH FTDI), serial 28800 8O2, **opened read-only in code — no write path anywhere**. Raw bytes appended to a rotating raw file *before* decoding.
- Decoded channels normalized to SI + Signal K-style paths, preserving the M/T reference flag per value; published as JSON deltas on localhost UDP to the core.
- GPS via **gpsd** (`DEVICES=/dev/gps`, `USBAUTO=false`) + **chrony** SHM refclock; core is a gpsd JSON client. Fallback for dev: direct NMEA file replay.
- fastnet2ip kept installed as a diagnostic / Plan B (OpenCPN on UDP :2002); never runs concurrently with ingest-fastnet (systemd `Conflicts=`).
- pyfastnet API may differ from research notes — planner/executor must verify against the installed package and the repo's sample captures before coding against it.

### Core, clock & state
- One asyncio core process (FastAPI + uvicorn single worker): state store keyed by path → {value, unit, source, timestamp, ref(M/T)}; staleness computed from injected clock.
- **Injected clock** abstraction (`SystemClock`, `GpsClock`, `SimClock`) used by all domain logic; a "time valid" flag (GPS-synced) gates routing (exposed as `routing_time_gate: blocked|ok` on diagnostics).
- Conventions module with golden tests from day 1: angles (deg/rad, wrap), true/magnetic with variation + heading offset, wind FROM vs current TOWARDS, u/v ↔ dir/speed, kn ↔ m/s.

### Replay / simulation
- L0: byte-level replay of raw Fastnet captures into a pty (so ingest code path is identical); captures sourced from the pyfastnet/fastnet2ip repos' sample data.
- L1: message-level replay of logged JSON deltas / NMEA GPS at accelerated speed (SimClock).
- L2 synthetic boat: generates AWA/AWS/BSP/HDG/GPS from a scripted wind + simple boat model, with fault injection (bus silent, GPS loss, garbage bytes, clock jump). Closed-loop steering comes in Phase 2.

### Diagnostics page (HELM-05 initial)
- Plain table: every path, value, unit, source, age (color by staleness), M/T flag; bus health (bytes/s, valid frames, checksum errors, unknown channel IDs), GPS health (fix, sats, time sync), clock state, routing time gate. Live via WebSocket. Event-marker button writes to the log (DATA-07).

### fastnet-probe
- CLI: opens port read-only, reports bytes/s, valid frames, checksum failures, channel IDs seen with last values; heuristic hint "bytes but 0 valid frames → swap A/B (white/green) or check parity"; writes a channel inventory JSON + raw capture file. Works against the pty replay for testing.

### Pi provisioning & reliability (REL-01)
- `deploy/` contains: provisioning script for Raspberry Pi OS Lite 64-bit Trixie (apt packages, purge ModemManager, udev rules for /dev/fastnet and /dev/gps, NetworkManager hotspot at fixed IP 10.42.0.1 SSID "jabuka", gpsd/chrony config, venv + wheelhouse install), systemd units (`jabuka-ingest-fastnet`, `jabuka-core`, restart=always, WatchdogSec where feasible), atomic file writes (tmp + fsync + rename) for state/config, journald volatile or size-limited.
- Physical flashing / on-Pi validation is a **human step** (user is AFK and has the hardware) — plans must make it a scripted, documented step and keep all automated verification runnable on the laptop. Pi-on-hardware checks become human verification items, not blockers for proceeding.

### Logging (DATA-07)
- Raw Fastnet bytes + GPS NMEA (via gpsd raw or separate) rotating files; 1 Hz derived state as JSON Lines, rotated hourly, fsync'd periodically; event markers as JSONL records.

### Claude's Discretion
- Exact module names, UDP port numbers, file rotation sizes, WebSocket message schema, CSS of the diagnostics page.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Greenfield repo — no code yet. External: pyfastnet (decoder + sample captures), fastnet2ip (diagnostic, replay tools `record_fn.py`, `playback_fn.py`), gpsd/gpsfake.

### Established Patterns
- None yet; this phase establishes them (src layout, uv, pytest golden tests, injected clock, SI internal units).

### Integration Points
- Phase 2 consumes the state store + WebSocket + SimClock + L2 sim; Phase 3 consumes the clock gate and state; Phase 4 consumes deploy/ + fault injection.

</code_context>

<specifics>
## Specific Ideas

- Hardware: Pi 3B, DTECH USB RS422/485 (FTDI 0403:6001), VK-162 u-blox USB GPS (ttyACM), B&G Hercules 2000/390 Fastnet (White=Data+, Green=Data−, Black=GND; no termination, listen-only).
- Magnetic variation default ~+5°E (verify with WMM for Šibenik 2026), configurable.
- User communicates in French; code/docs in English, UI strings may be French later (Phase 2).

</specifics>

<deferred>
## Deferred Ideas

- Read-only root overlay FS — Phase 4 decision.
- Routing-health row on diagnostics — filled in Phase 3.

</deferred>
