# Phase 1: Foundation, Data Backbone & Bus-Test Kit - Research

**Researched:** 2026-11-06
**Domain:** Embedded Linux data acquisition (RS-485 Fastnet + gpsd GPS) on Raspberry Pi OS Trixie, asyncio Python services, FastAPI diagnostics, systemd reliability
**Confidence:** HIGH for the decoder API, serial/pty behaviour and Python stack (all exercised in this session). MEDIUM for Pi provisioning and gpsd/chrony (official docs, not run on a Pi). LOW for B&G-bus-specific behaviour (sign of AWA, True-layout byte), which can only be checked on the boat.

<user_constraints>
## User Constraints (from CONTEXT.md)

> Mode: Smart discuss auto-accepted. The user is AFK and explicitly asked to "continue without me". All decisions below are Claude's recommended answers, grounded in `.planning/research/SUMMARY.md`. Revisit if the user objects.

### Locked Decisions

#### Repo layout & tooling
- Single Python package `jabuka/` (src layout: `src/jabuka/`), Python ≥3.13 target (Pi Trixie), developed on the laptop (Python 3.14 locally is fine; keep code 3.13-compatible), managed with `uv`, tests with `pytest`, lint with `ruff`.
- Subpackages: `common/` (units, angles, conventions, clock, atomic IO), `ingest/` (fastnet, gps), `core/` (state store, wind source arbitration stub, logging, web), `sim/` (replay + synthetic boat), `tools/` (fastnet-probe), `deploy/` (Pi provisioning, systemd units, udev rules).
- Frontend: plain static HTML/ES modules served by FastAPI, no JS build chain.

#### Ingest architecture
- Own `ingest-fastnet` process using **pyfastnet** directly (not fastnet2ip NMEA), owning `/dev/fastnet` (udev by-id symlink to the DTECH FTDI), serial 28800 8O2, **opened read-only in code — no write path anywhere**. Raw bytes appended to a rotating raw file *before* decoding.
- Decoded channels normalized to SI + Signal K-style paths, preserving the M/T reference flag per value; published as JSON deltas on localhost UDP to the core.
- GPS via **gpsd** (`DEVICES=/dev/gps`, `USBAUTO=false`) + **chrony** SHM refclock; core is a gpsd JSON client. Fallback for dev: direct NMEA file replay.
- fastnet2ip kept installed as a diagnostic / Plan B (OpenCPN on UDP :2002); never runs concurrently with ingest-fastnet (systemd `Conflicts=`).
- pyfastnet API may differ from research notes — planner/executor must verify against the installed package and the repo's sample captures before coding against it.

#### Core, clock & state
- One asyncio core process (FastAPI + uvicorn single worker): state store keyed by path → {value, unit, source, timestamp, ref(M/T)}; staleness computed from injected clock.
- **Injected clock** abstraction (`SystemClock`, `GpsClock`, `SimClock`) used by all domain logic; a "time valid" flag (GPS-synced) gates routing (exposed as `routing_time_gate: blocked|ok` on diagnostics).
- Conventions module with golden tests from day 1: angles (deg/rad, wrap), true/magnetic with variation + heading offset, wind FROM vs current TOWARDS, u/v ↔ dir/speed, kn ↔ m/s.

#### Replay / simulation
- L0: byte-level replay of raw Fastnet captures into a pty (so ingest code path is identical); captures sourced from the pyfastnet/fastnet2ip repos' sample data.
- L1: message-level replay of logged JSON deltas / NMEA GPS at accelerated speed (SimClock).
- L2 synthetic boat: generates AWA/AWS/BSP/HDG/GPS from a scripted wind + simple boat model, with fault injection (bus silent, GPS loss, garbage bytes, clock jump). Closed-loop steering comes in Phase 2.

#### Diagnostics page (HELM-05 initial)
- Plain table: every path, value, unit, source, age (color by staleness), M/T flag; bus health (bytes/s, valid frames, checksum errors, unknown channel IDs), GPS health (fix, sats, time sync), clock state, routing time gate. Live via WebSocket. Event-marker button writes to the log (DATA-07).

#### fastnet-probe
- CLI: opens port read-only, reports bytes/s, valid frames, checksum failures, channel IDs seen with last values; heuristic hint "bytes but 0 valid frames → swap A/B (white/green) or check parity"; writes a channel inventory JSON + raw capture file. Works against the pty replay for testing.

#### Pi provisioning & reliability (REL-01)
- `deploy/` contains: provisioning script for Raspberry Pi OS Lite 64-bit Trixie (apt packages, purge ModemManager, udev rules for /dev/fastnet and /dev/gps, NetworkManager hotspot at fixed IP 10.42.0.1 SSID "jabuka", gpsd/chrony config, venv + wheelhouse install), systemd units (`jabuka-ingest-fastnet`, `jabuka-core`, restart=always, WatchdogSec where feasible), atomic file writes (tmp + fsync + rename) for state/config, journald volatile or size-limited.
- Physical flashing / on-Pi validation is a **human step** (user is AFK and has the hardware) — plans must make it a scripted, documented step and keep all automated verification runnable on the laptop. Pi-on-hardware checks become human verification items, not blockers for proceeding.

#### Logging (DATA-07)
- Raw Fastnet bytes + GPS NMEA (via gpsd raw or separate) rotating files; 1 Hz derived state as JSON Lines, rotated hourly, fsync'd periodically; event markers as JSONL records.

### Claude's Discretion
- Exact module names, UDP port numbers, file rotation sizes, WebSocket message schema, CSS of the diagnostics page.

### Deferred Ideas (OUT OF SCOPE)
- Read-only root overlay FS — Phase 4 decision.
- Routing-health row on diagnostics — filled in Phase 3.

### Specific Ideas (from CONTEXT.md)
- Hardware: Pi 3B, DTECH USB RS422/485 (FTDI 0403:6001), VK-162 u-blox USB GPS (ttyACM), B&G Hercules 2000/390 Fastnet (White=Data+, Green=Data−, Black=GND; no termination, listen-only).
- Magnetic variation default ~+5°E (verify with WMM for Šibenik 2026), configurable.
- User communicates in French; code/docs in English, UI strings may be French later (Phase 2).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Pi 3B runs Raspberry Pi OS Lite 64-bit with a Wi-Fi AP at a fixed IP that the tablet joins (no internet) | §Deploy: `nmcli` AP profile (`ipv4.method shared` + `ipv4.addresses 10.42.0.1/24`, `pmf disable`, `powersave 2`); cloud-init/Imager first boot; Ethernet during provisioning. Human-verify on Pi. |
| DATA-02 | Read Fastnet strictly receive-only; raw bytes on disk before decoding | §Pattern 1 `ReadOnlySerial` (fd opened `O_RDONLY`, write → `EBADF`, tested on a pty); udev `MODE="0640"`; raw-first writer in the read callback; static "no write path" test. |
| DATA-03 | Decode Fastnet channels into one normalized state with units, source, age | §pyfastnet API: `decode_frame` + `project` (SI + Signal K paths), `unit_for`; M/T from the rich decode's `layout`; state store with injected clock. All 10 sample captures decode (counts below). |
| DATA-04 | Read VK-162 GPS (position, COG, SOG, UTC) and set system clock from GPS; routing blocked until time valid | §gpsd JSON client (`?WATCH`, TPV/SKY fields verified), chrony `refclock SHM 0`, `makestep 1 -1`; `GpsClock` validity rule; `routing_time_gate`. |
| DATA-05 | `fastnet-probe`: frames/checksums/channel IDs, swap-wires hint, channel inventory | §Pattern 2 `CountingFramer` (pyfastnet's `FrameBuffer` exposes no error counters); verdict heuristics; optional `TIOCGICOUNT` parity counters; tested via pty with inverted bytes (0 frames). |
| DATA-06 | Replay raw Fastnet/GPS captures and run a synthetic boat with faults at accelerated speed through the same pipeline | §Pattern 6: L0 pty (verified: 21147/21147 bytes, 937 frames through pyserial on a pty), L1 UDP, L2 sim with a **verified** minimal Fastnet frame encoder (round-trips through pyfastnet). |
| DATA-07 | Continuous raw + 1 Hz derived logging; event marker from UI | §Pattern 7 rotating append-only writers (flush 1 s, fsync 10 s, hourly rotate), JSONL events via `POST /api/event`. |
| HELM-05 | Diagnostics page with every value, source and age, plus bus/GPS/routing health | §Pattern 5 FastAPI WS hub with bounded per-client queues (verified with TestClient and real uvicorn+websockets); server-computed ages. |
| REL-01 | Auto-start on boot, auto-restart on crash, survive power cuts without corruption | §Deploy: systemd `Restart=always`, `StartLimitIntervalSec=0`, `Type=notify` + `WatchdogSec` via a 10-line `sd_notify`; atomic write + `.bak`; journald volatile; `RuntimeWatchdogSec`. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

Extracted from `/home/drico/git/jabuka/.claude/CLAUDE.md` (its stack section is a copy of research/STACK.md):

- **Hardware:** Raspberry Pi 3B (1 GB RAM). No heavy desktop GUI. Ingest must not import numpy.
- **Connectivity:** no internet during the race. Everything pre-loaded, including a wheelhouse for offline reinstall.
- **Testing:** the real Fastnet bus can't be reached until 12–13 Nov, so everything must be testable on recorded/simulated data.
- **Reliability:** about 36 h unattended, power cycles, auto-recover.
- **Licensing:** open source. MIT pyfastnet captures can be vendored with attribution.
- **Do not use:** Signal K server; 32-bit OS; hostapd/dnsmasq/dhcpcd AP recipes (use `nmcli` with `ipv4.method shared`); a JS build chain; gpsd USBAUTO on all USB serial devices; relying on the Pi clock without GPS discipline; `.local`/mDNS URLs for the tablet (use a fixed IP).
- **GSD workflow:** repo edits happen through GSD commands (`/gsd-execute-phase` for this phase).
- **Conventions:** not yet established. This phase sets them (src layout, uv, pytest golden tests, injected clock, SI internal units).

## Summary

The pyfastnet 3.2.1 API was installed and exercised under both Python 3.13.12 and 3.14.7 on this laptop. Its public surface is `FrameBuffer`, `decode_frame`, `decode_ascii_frame`, `decode_light_frame`, `project`, `unit_for`, `channel_map` and `set_log_level`. `FrameBuffer(project=True)` queues `{"to_address", "from_address", "command", "values": {signalk_path: SI_value}}`. All 8 pyfastnet captures and 2 extra fastnet2ip captures decode cleanly, giving 937–3507 frames each. There are three things pyfastnet does **not** do that this phase needs:

1. **No error counters.** `FrameBuffer` silently drops one byte per checksum failure. The probe and the ingest's bus-health figures therefore need a small counting framer of their own, about 30 lines, that mirrors pyfastnet's algorithm. It hands valid frames to pyfastnet's `decode_frame`/`project`.
2. **Projected output loses the M/T layout.** The projection routes heading, TWD and tidal set to `...Magnetic` whenever the layout byte is anything other than `°T`, and **the `°T` byte value is unknown upstream**. If the Hercules is set to show True, pyfastnet will still emit `navigation.headingMagnetic` carrying a True value. The ingest has to read the rich decode (`project=False`) and keep `layout` so that the ref is explicitly `M`, `T` or `?`.
3. **No encoder.** A minimal frame encoder (format `0x01` scaled int16 and format `0x08` layout+9-bit) was written and round-tripped through `decode_frame`/`project` in this session. That makes an L2 simulator that drives the real byte path feasible.

Receive-only is enforceable in the kernel rather than only by discipline. A 20-line `pyserial.Serial` subclass opens the tty `O_RDONLY`. Any `os.write` then fails with `EBADF`, termios 28800 8O2 configuration still works, and the fd plugs into `asyncio`'s `loop.add_reader`. This was verified on a pty, including EOF when the "device" disappears, which is how unplug gets simulated. Linux ptys silently clear `PARENB`, so parity can only be verified on the real FTDI, as a human step. GPS goes through gpsd 3.25 (Trixie). The gpsd JSON fields were verified from the official protocol doc. chrony's Trixie config already includes `confdir /etc/chrony/conf.d` and uses `makestep 1 3`, which provisioning must change to `makestep 1 -1`. The FastAPI 0.162 + uvicorn 0.54 + websockets 17.4 stack ran a WebSocket broadcast on 3.13 and 3.14 with no `uvicorn[standard]` extras (about 49 MB RSS on x86_64). Its cp313 aarch64 wheelhouse is 17 wheels, 3.7 MB.

**Primary recommendation:** Build three processes: `jabuka-ingest-fastnet` (ReadOnlySerial → raw log → CountingFramer → pyfastnet rich decode → normalized UDP deltas), `jabuka-core` (UDP listener + gpsd client → state store with injected clock → 1 Hz logger → FastAPI WS diagnostics), and replay/sim tools that feed either the pty (L0) or the UDP port (L1/L2). Vendor the 10 sample captures as test fixtures, pinned to commit SHAs. Make every Pi-side item a scripted `deploy/` step with a human-verify checklist.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fastnet byte capture (read-only), raw log, framing, decode, normalize | Ingest process (`jabuka-ingest-fastnet`) | — | Owns the device. Crash isolation from core. Raw-first lives at the lowest layer. |
| GPS acquisition, device hotplug, system clock discipline | OS services (gpsd + chrony) | Core (gpsd JSON client) | gpsd/chrony handle the device and clock. The core only consumes TPV/SKY. |
| Domain time ("now", time-valid flag, routing gate) | Core (`common/clock.py`) | — | One injected clock for all logic. The system clock is only cross-checked. |
| State store (latest value per path, source, ref, age) | Core | — | Single-threaded asyncio dict, no locks. |
| 1 Hz derived log, event markers | Core (logger task) | — | It has the full state snapshot. |
| Diagnostics page (rendering) | Browser (static HTML/ES module) | Core (computes ages and health, pushes over WS) | Server computes, client renders, so the browser clock is irrelevant. |
| Bus diagnosis on boat | CLI tool (`fastnet-probe`) | — | Runs with the ingest service stopped. Same framer code. |
| Replay / simulation | Dev tools (`jabuka-replay`, `jabuka-sim`) | pty (L0) / UDP (L1, L2) | Feeds the same entry points as live data. |
| AP, device naming, service supervision | OS config (`deploy/`: NetworkManager, udev, systemd, journald) | — | Declarative files plus a provisioning script. |

## Standard Stack

### Core (runtime on the Pi)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pyfastnet (import name `fastnet_decoder`) | 3.2.1 (2026-09-13), MIT, zero deps, `requires-python >=3.7` | Fastnet decode + Signal K projection | The only maintained decoder. Ran on 3.13.12 and 3.14.7 here. Channel map lives in data (`fastnet.json`). [VERIFIED: installed + read `fastnet_decoder/__init__.py`, `frame_buffer.py`, `interpreter.py`] |
| pyserial | 3.5 (2020-11-23) | termios config incl. non-standard 28800 baud (`BOTHER` via `TCSETS2`) | Battle-tested custom-baud path. Subclassed for `O_RDONLY`. Imported and used under 3.13 and 3.14 in this session (the absence of `requires_python` metadata says nothing either way; the run shows it works). [VERIFIED: local run] |
| fastapi | 0.162.0 (2026-10-23), `requires-python >=3.10` | REST + WS + static files | Locked by CONTEXT. Pulls starlette 1.10.0, pydantic 2.14.3, pydantic-core 2.50.4 (cp313 aarch64 wheel exists). [VERIFIED: PyPI JSON + aarch64 wheel download] |
| uvicorn | 0.54.0 (2026-09-25) — **plain, not `[standard]`** | ASGI server, single worker | `[standard]` adds watchfiles/uvloop/httptools, which aren't needed on a Pi. Plain uvicorn + `websockets` served WS in this session. [VERIFIED: local run] |
| websockets | 17.4 (2026-10-30) | WS protocol implementation for uvicorn | Without it (or wsproto), plain uvicorn can't serve `/ws`. cp313 aarch64 wheel exists. [VERIFIED: local run + wheel download] |
| gpsd (apt) | 3.25-5+deb13u2 (Trixie) | GPS device daemon, JSON on 127.0.0.1:2947, SHM for chrony | Locked by CONTEXT. [VERIFIED: sources.debian.org] |
| chrony (apt) | 4.6.1-3+deb13u2 (Trixie) | System clock from gpsd SHM 0 | Locked by CONTEXT. [VERIFIED: sources.debian.org] |
| NetworkManager (Pi OS default) | Trixie | Wi-Fi AP via `nmcli` | Pi OS default since Bookworm. [CITED: raspi-cam-srv Trixie hotspot doc] |

### Supporting / dev (laptop only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.2.0 (2026-10-27) | Tests | Always |
| pytest-asyncio | 1.4.1.post1 | Async tests (gpsd client, UDP, framer streaming) | Async unit tests. Set `asyncio_mode = "auto"`. |
| httpx | 0.28.1 | Needed by `fastapi.testclient.TestClient` | Starlette 1.10 prefers `httpx2` but still accepts `httpx` with a `StarletteDeprecationWarning` (read in `starlette/testclient.py` lines 26–41). Add a filterwarnings entry. |
| ruff | 0.17.4 (2026-11-05) | Lint/format, `target-version = "py313"` | Always. Catches 3.14-only syntax. |
| fastnet2ip | 3.3.1 | Plan B / cross-check decoder on the Pi (`pipx install --global`) | Diagnostic only, never concurrent with ingest |
| gpsd-clients (`gpsfake`, `cgps`, `gpspipe`) | apt | Optional end-to-end GPS replay through a real gpsd | **Not installed on the laptop.** Needs `sudo apt install gpsd gpsd-clients` (3.27.5 on forky). Tests must use a fake gpsd server instead. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ReadOnlySerial` (pyserial subclass) | Pure `os.open(O_RDONLY)` + `termios` + own `TCSETS2` ioctl | No pyserial dependency, but you re-implement the BOTHER custom-baud code. Not worth it. |
| asyncio `loop.add_reader(fd)` | Blocking read thread + `call_soon_threadsafe` | Threads add the pyfastnet "single thread" caveat and shutdown complexity. `add_reader` was verified on a pty. |
| gpsd JSON client in core | Direct pyserial NMEA reader (`ingest@gps`) | Loses chrony clock discipline and gpsd hotplug. Locked out by CONTEXT. Keep the NMEA parser only for dev replay. |
| httpx for TestClient | `httpx2` (github.com/pydantic/httpx2) | Starlette's preferred future dependency. It's new (2026-10-21), so stick with httpx 0.28.1 for now. |
| Port 8080 | Port 80 via `AmbientCapabilities=CAP_NET_BIND_SERVICE` | Port 80 gives a simpler tablet bookmark (`http://10.42.0.1/`). Either works (discretion). |

**Installation (laptop dev):**
```bash
uv venv -p 3.14 .venv            # or -p 3.13 (/usr/bin/python3.13 exists)
uv pip install -e ".[dev]"       # pyproject: deps = pyfastnet==3.2.1 pyserial==3.5 fastapi==0.162.0 uvicorn==0.54.0 websockets==17.4
                                 # dev = pytest==9.2.0 pytest-asyncio==1.4.1.post1 httpx==0.28.1 ruff==0.17.4
```

**Pi lock + offline wheelhouse (verified in this session; `uv pip download` does NOT exist in uv, so use pip for the download step):**
```bash
uv pip compile requirements.in --python-platform aarch64-unknown-linux-gnu --python-version 3.13 --generate-hashes -o deploy/requirements.lock
python3 -m pip download --only-binary=:all: --no-deps --implementation cp --python-version 3.13 \
  --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64 \
  -r deploy/requirements.lock -d deploy/wheelhouse
# On the Pi:
python3 -m venv /opt/jabuka/venv
/opt/jabuka/venv/bin/pip install --no-index --find-links /opt/jabuka/wheelhouse --require-hashes -r /opt/jabuka/requirements.lock
/opt/jabuka/venv/bin/pip install --no-index --no-deps /opt/jabuka/wheelhouse/jabuka-*.whl
```
The resolved lock is 17 packages: annotated-doc, annotated-types, anyio, click, fastapi, h11, idna, opentelemetry-api, pydantic, pydantic-core, pyfastnet, pyserial, starlette, typing-extensions, typing-inspection, uvicorn, websockets. Only pydantic-core and websockets are binary (cp313 manylinux aarch64). Total 3.7 MB. [VERIFIED: ran both commands]

**Note:** the laptop has **uv 0.6.6**, not 0.13 as the project research assumed. `uv venv`, `uv pip install/compile/sync` all exist in 0.6.6. Avoid features that need newer uv. [VERIFIED: `uv --version`]

## Package Legitimacy Audit

`gsd-tools query package-legitimacy check --ecosystem pypi` was run on all packages. Every PyPI package came back `SUS`, with reason `unknown-downloads` (the seam gets no PyPI download stats, `weeklyDownloads: null` for all of them). `fastapi`, `pytest`, `ruff`, `pytest-asyncio` and `websockets` also got `too-new`, because their latest release is days old. None has a postinstall hook (PyPI has none), and all have their canonical source repo.

| Package | Registry | Latest release | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|----------------|-----------|-------------|---------|-------------|
| pyfastnet | PyPI | 3.2.1, 2026-09-13 | n/a (seam) | github.com/ghotihook/pyfastnet | SUS (unknown-downloads) | Approved: source read in full this session. Pin 3.2.1 + hash. |
| fastnet2ip | PyPI | 3.3.1, 2026-09-13 | n/a | github.com/ghotihook/fastnet2ip | SUS (unknown-downloads) | Approved (Plan B tool). Pin 3.3.1. |
| pyserial | PyPI | 3.5, 2020-11-23 | n/a | github.com/pyserial/pyserial | SUS (unknown-downloads) | Approved. Pin + hash. |
| fastapi | PyPI | 0.162.0, 2026-10-23 | n/a | github.com/fastapi/fastapi | SUS (too-new, unknown-downloads) | Approved. Pin + hash (14 days old). |
| uvicorn | PyPI | 0.54.0, 2026-09-25 | n/a | github.com/Kludex/uvicorn | SUS (unknown-downloads) | Approved. Pin + hash. |
| websockets | PyPI | 17.4, 2026-10-30 | n/a | github.com/python-websockets/websockets | SUS (too-new, unknown-downloads) | Approved. Pin + hash, or 17.3 if you want an older build. |
| pytest | PyPI | 9.2.0, 2026-10-27 | n/a | github.com/pytest-dev/pytest | SUS (too-new, unknown-downloads) | Approved (dev only) |
| pytest-asyncio | PyPI | 1.4.1.post1, 2026-11-01 | n/a | github.com/pytest-dev/pytest-asyncio | SUS (too-new, unknown-downloads) | Approved (dev only) |
| ruff | PyPI | 0.17.4, 2026-11-05 | n/a | astral (docs.astral.sh/ruff) | SUS (too-new, unknown-downloads) | Approved (dev only). 0.17.3 if you want an older build. |
| httpx | PyPI | 0.28.1, 2024-12-06 | n/a | github.com/encode/httpx | SUS (unknown-downloads) | Approved (dev only) |
| httpx2 | PyPI | 2026-10-21 | n/a | github.com/pydantic/httpx2 | SUS (too-new, unknown-downloads) | **Not recommended now.** Referenced by starlette's own testclient. Revisit later. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** all of the above, for a structural seam limitation (no PyPI download data), not a content signal. These are the canonical, widely used projects named in the project's locked stack. Recommended handling, since the user is AFK: **one** `checkpoint:human-verify` covering the hash-pinned `deploy/requirements.lock` (the user eyeballs names and versions), rather than a checkpoint per package. All runtime installs go through `--require-hashes`.

## Architecture Patterns

### System Architecture Diagram

```
 LIVE (Pi)                                              DEV (laptop)
 ─────────                                              ────────────
 B&G Fastnet ──RS485──▶ DTECH FTDI ──▶ /dev/fastnet     raw capture (.txt hex | timestamped .log)
                                         │                    │  jabuka-replay --pty  (L0, paced)
                                         │◀───────────────────┘  [pty slave path given to ingest]
                          ┌──────────────▼───────────────┐
                          │ jabuka-ingest-fastnet        │   fastnet-probe (same ReadOnlySerial +
                          │ ReadOnlySerial (O_RDONLY)    │   CountingFramer; run with ingest stopped)
                          │  └▶ RAW LOG (append, first)  │      └▶ verdict + inventory.json + capture
                          │  └▶ CountingFramer (+stats)  │
                          │  └▶ pyfastnet decode_frame   │
                          │  └▶ normalize: SK path, SI,  │
                          │     ref M/T/?, src, t_mono   │
                          └──────────────┬───────────────┘
                                         │ UDP JSON datagrams → 127.0.0.1:47100
   jabuka-replay --udp (L1) ─────────────┤        ▲
   jabuka-sim (L2 synthetic + faults) ───┘        │ (L2 can also emit encoded Fastnet bytes into a pty → L0 path)
                                                  │
 VK-162 ─USB─▶ /dev/gps ─▶ gpsd (-n) ──SHM0──▶ chrony ─▶ system clock
                              │ JSON TPV/SKY on 127.0.0.1:2947
                          ┌───▼──────────────────────────────────────────────┐
                          │ jabuka-core (asyncio, uvicorn 1 worker)          │
                          │  UDP listener ─┐                                 │
                          │  gpsd client ──┼─▶ normalize ─▶ STATE STORE      │
                          │  (raw gps log) │    {path: value, unit, src,     │
                          │                │     ref, t_mono, t_utc}         │
                          │  Clock (GpsClock|SimClock) ─▶ time_valid,        │
                          │     routing_time_gate                            │
                          │  1 Hz tick ─▶ derived JSONL log ─▶ WS hub ──────────▶ browser /ws
                          │  POST /api/event ─▶ events JSONL                 │      (diagnostics table)
                          │  sd_notify WATCHDOG=1 every WATCHDOG_USEC/2      │
                          └──────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
pyproject.toml                  # requires-python=">=3.13"; ruff target py313; pytest asyncio_mode=auto
src/jabuka/
├── common/
│   ├── units.py                # kn↔m/s, deg↔rad, wrap_2pi, wrap_pi (signed, −π..π)
│   ├── conventions.py          # mag→true (var E positive), heading offset, wind FROM, current TOWARDS, u/v↔dir/speed
│   ├── clock.py                # Clock protocol; SystemClock, GpsClock, SimClock
│   ├── atomicio.py             # atomic_write_bytes/json + load_with_bak
│   ├── messages.py             # Delta dataclass + JSON (de)serialization, schema version
│   └── sdnotify.py             # 10-line NOTIFY_SOCKET client
├── ingest/
│   ├── serial_ro.py            # ReadOnlySerial
│   ├── fastnet_framing.py      # CountingFramer + FramerStats (shared with probe)
│   ├── fastnet_decode.py       # rich decode → Delta list (path, value, ref, channel_id, from_addr)
│   ├── fastnet_encode.py       # minimal encoder (sim + tests); round-trip tested
│   ├── rawlog.py               # RotatingAppendLog (raw, derived, events)
│   ├── fastnet_main.py         # entrypoint: jabuka-ingest-fastnet
│   ├── gpsd_client.py          # asyncio gpsd JSON client → Delta + clock fixes
│   └── nmea.py                 # RMC/GGA parser for dev NMEA replay only
├── core/
│   ├── state.py                # StateStore (+staleness thresholds per path)
│   ├── bus.py                  # asyncio UDP DatagramProtocol
│   ├── derived_log.py          # 1 Hz snapshot writer
│   ├── health.py               # bus/gps/clock health aggregation
│   ├── web.py                  # FastAPI app: /ws, /api/state, /api/event, static
│   └── main.py                 # entrypoint: jabuka-core
├── sim/
│   ├── replay.py               # L0 pty (+timing), L1 UDP; --speed
│   ├── synth.py                # L2 boat + scripted wind + faults
│   └── fake_gpsd.py            # asyncio TCP server speaking gpsd JSON (tests + dev)
├── tools/
│   └── probe.py                # fastnet-probe
└── web/static/                 # index.html, diag.js (ES module), diag.css
deploy/
├── provision.sh                # idempotent; run as root on the Pi
├── udev/99-jabuka.rules
├── gpsd.default                # → /etc/default/gpsd
├── chrony-gps.conf             # → /etc/chrony/conf.d/gps.conf
├── systemd/{jabuka-ingest-fastnet,jabuka-core}.service, watchdog.conf, journald.conf
├── requirements.in / requirements.lock / wheelhouse/ (gitignored or LFS)
└── PI-SETUP.md                 # human runbook: flash, first boot, verify checklist
tests/
├── fixtures/fastnet/           # vendored captures + LICENSE-pyfastnet + SOURCES.md (commit SHAs)
├── fixtures/gps/               # synthetic gpsd JSON + NMEA lines
└── test_*.py
```

### Pattern 1: Kernel-enforced receive-only serial (`ReadOnlySerial`)
**What:** Subclass pyserial and open the tty `O_RDONLY | O_NOCTTY | O_NONBLOCK`. pyserial's own `open()` hard-codes `os.O_RDWR` (`serial/serialposix.py` line 322: `self.fd = os.open(self.portstr, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)`). termios and the BOTHER custom-baud ioctl both work on a read-only fd.
**When:** Both the ingest and `fastnet-probe`.
**Verified on a pty in this session:** `O_ACCMODE == 0`; `os.write(fd)` → `EBADF`; 28800 + `PARODD` + `CSTOPB` + `CS8` are applied; **`PARENB` reads back False on a pty** (Linux ptys don't honour parity). A unit test asserting `PARENB` therefore has to be skipped on ptys and checked on the Pi with `stty -F /dev/fastnet` (expect `parenb parodd cs8 cstopb` and `speed 28800`).
```python
# Source: verified in this session (scratchpad ro_serial.py) against pyserial 3.5 serialposix.open()
import fcntl, os, serial
from serial.serialutil import SerialException

class ReadOnlySerial(serial.Serial):
    """Fd opened O_RDONLY: the kernel rejects any write (EBADF). Never call send_break()."""
    def open(self):
        if self._port is None:
            raise SerialException("Port must be configured before it can be used.")
        if self.is_open:
            raise SerialException("Port is already open.")
        try:
            self.fd = os.open(self.portstr, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as msg:
            self.fd = None
            raise SerialException(msg.errno, f"could not open port {self._port}: {msg}")
        self.pipe_abort_read_r, self.pipe_abort_read_w = os.pipe()
        self.pipe_abort_write_r, self.pipe_abort_write_w = os.pipe()
        fcntl.fcntl(self.pipe_abort_read_r, fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.fcntl(self.pipe_abort_write_r, fcntl.F_SETFL, os.O_NONBLOCK)
        try:
            self._reconfigure_port(force_update=True)   # termios + BOTHER 28800
            self._reset_input_buffer()
        except BaseException:
            os.close(self.fd); self.fd = None
            raise
        self.is_open = True

    def write(self, data):  # belt and braces; the fd can't write anyway
        raise PermissionError("Fastnet port is receive-only")

def open_fastnet(path: str) -> ReadOnlySerial:
    return ReadOnlySerial(path, baudrate=28800, bytesize=serial.EIGHTBITS,
                          parity=serial.PARITY_ODD, stopbits=serial.STOPBITS_TWO, timeout=0)
```
Note: this skips pyserial's DTR/RTS update on open. That's fine because the DTECH auto-direction RS-485 only drives the line when TX data is present. fastnet2ip's README says USB RS-485 adapters like the DTECH are not affected by the PL011 "first-open 9600 baud" bug, so the `_force_baudrate` dance in `fastnet2ip/core/input.py` is **not** needed for the DTECH. It's harmless if added. [VERIFIED: fastnet2ip README lines 247–248, docs/uart_first_open_baud_fix.md line 26–27]

**Asyncio read loop (verified on a pty, 21147/21147 bytes, 937 frames):**
```python
loop.add_reader(fd, on_readable)       # fd = ser.fileno()
def on_readable():
    try:
        b = os.read(fd, 4096)
    except BlockingIOError:
        return
    except OSError as e:                # EIO on USB unplug
        loop.remove_reader(fd); reconnect_soon(e); return
    if not b:                           # EOF (pty master closed = simulated unplug)
        loop.remove_reader(fd); reconnect_soon(None); return
    rawlog.write_chunk(b)               # RAW FIRST
    for frame in framer.feed(b): handle(frame)
```
Reconnect loop: close, sleep 1–2 s, retry `open_fastnet("/dev/fastnet")`. Expect `FileNotFoundError`/`SerialException` while unplugged. Never exit the process because the device is absent. Report `device: missing` in health instead.

### Pattern 2: Counting framer (probe + bus health), pyfastnet for decoding
**Why:** `FrameBuffer.get_complete_frames()` discards a byte on header or body checksum failure and only logs it at DEBUG (`frame_buffer.py` lines 63–73), with no counters. It also offers no per-frame `from_address`/command stats.
**Algorithm (must match pyfastnet, from `docs/porting.md` §2):** frame = `[to, from, body_size, command, header_cks, body…, body_cks]`, length `5 + body_size + 1`. Checksum = `(-sum(bytes)) & 0xFF` (`fastnet_decoder/utils.py`). **Wait for the full length before checking either checksum.** On failure, drop 1 byte. Keep at most 8192 bytes. Commands (verbatim from `fastnet.json` `lookups.commands`): `{'0x01': 'Broadcast', '0x0C': 'Keep Alive', '0x03': 'LatLon', '0xC9': 'Light Intensity'}`. `ignoredCommands`: `['Keep Alive']`.
```python
from collections import Counter
from dataclasses import dataclass, field
BROADCAST, LATLON, LIGHT, KEEP_ALIVE = 0x01, 0x03, 0xC9, 0x0C
MAX_BUF = 8192

def _cks(b) -> int:
    return (-sum(b)) & 0xFF

@dataclass
class FramerStats:
    bytes_in: int = 0
    bytes_discarded: int = 0          # resync drops = "checksum failures" proxy
    frames_ok: int = 0
    by_command: Counter = field(default_factory=Counter)

class CountingFramer:
    def __init__(self):
        self.buf = bytearray(); self.stats = FramerStats()
    def feed(self, data: bytes) -> list[bytes]:
        s = self.stats; s.bytes_in += len(data); self.buf += data
        if len(self.buf) > MAX_BUF:
            drop = len(self.buf) - MAX_BUF; s.bytes_discarded += drop; del self.buf[:drop]
        out = []
        while len(self.buf) >= 6:
            n = 5 + self.buf[2] + 1
            if len(self.buf) < n:
                break
            if _cks(self.buf[0:4]) != self.buf[4] or _cks(self.buf[5:n - 1]) != self.buf[n - 1]:
                del self.buf[0]; s.bytes_discarded += 1; continue
            frame = bytes(self.buf[:n]); del self.buf[:n]
            s.frames_ok += 1; s.by_command[frame[3]] += 1
            if frame[3] != KEEP_ALIVE:
                out.append(frame)
        return out
```
Dispatch: `BROADCAST` → `fastnet_decoder.decode_frame(frame)`; `LATLON` → `decode_ascii_frame(frame)`; `LIGHT` → ignore (backlight); anything else → count as "undecoded command" (pilot traffic). A decode result containing `"error"` counts as a decode error.
**Equivalence test (required):** for every fixture capture, `[project(d) for d in CountingFramer path]` must equal what `FrameBuffer(project=True)` queues. Golden queue counts (computed this session, 3.13.12, pyfastnet 3.2.1):

| Capture | Bytes | `FrameBuffer(project=True)` frames | `project=False` frames |
|---|---:|---:|---:|
| big.txt | 21147 | 937 | 937 |
| big_with_ap_actions.txt | 48040 | 2018 | 2018 |
| example1_fastnet_data.txt | 62751 | 2630 | 2630 |
| example2_fastnet_data.txt | 66425 | 2801 | 2801 |
| heel-port.txt | 3737 | 164 | 164 |
| heel-stb.txt | 9570 | 422 | 422 |
| trim-neg.txt | 3613 | 161 | 161 |
| trim-pos.txt | 4227 | 189 | 189 |
| ap_backlight_20260514.txt (fastnet2ip) | 58240 | 2433 | 2439 |
| rawfn-20260502-011827.txt (fastnet2ip) | 85487 | 3392 | 3507 |

**Robustness verified:** byte-inverted capture → 0 frames. 2 MB of `os.urandom` → 0 queued frames. A garbage prefix stalls the framer until enough bytes arrive (the "claimed long body" rule), then all following frames are recovered (10/10).

### Pattern 3: pyfastnet decode → normalized deltas, keeping the M/T reference
**Rich decode shape** (verbatim from a `project=False` run on example2):
```
{"command": "Broadcast", "keys": ["to_address","from_address","command","values"],
 "Heading": {"channel_id": "0x49", "value": 41.0, "display_text": "41°M", "layout": "°M"}}
{"Apparent Wind Angle": {"channel_id": "0x51", "value": 17.0, "display_text": "17-", "layout": "[data]-"}}
{"LatLon": {"channel_id": "0x47", "value": null, "display_text": "3352.080S15114.010E", "layout": null}}
```
**Projection** (`project(decoded_frame)`) gives `{signalk_path: SI_value}`. Angles are radians, speeds m/s, depth m, temperature K, and `navigation.position` = `{"latitude": deg, "longitude": deg}`. Unmapped channels appear as `bandg.unknown.0xNN`. `None` means present on the bus but display-only (format 0x06). [VERIFIED: `interpreter.py` lines 942–1060]
**M/T routing rule (verbatim, `interpreter.py` lines 1032–1036):**
```python
layout = entry.get("layout")
if layout == "°T":
    route = signalk_info["routes"]["°T"]
else:
    route = signalk_info["routes"]["°M"]  # default when layout is None/unrecognised
```
`segmentA` only knows `'0x66': '°M'`. There is **no `°T` code** (design doc note 13: "the `°T` byte *value* — no True bearing appears in any capture"). In the fastnet2ip `rawfn-20260502` capture, Heading arrives 229× with `°M` and **114× with layout `None`**.
**Rule for the ingest:** for routed channels 0x49 (Heading), 0x6D (TWD) and 0x84 (Tidal Set), set `ref = "M"` if layout == `"°M"`, `"T"` if `"°T"`, else `"?"`. Publish a **ref-neutral path** (`navigation.heading`, `environment.wind.direction`, `environment.current.set`) plus `ref`. Also keep `channel_id`, `from_address`, raw `layout`, and a `bandg.layoutByte` for unknown layouts (via the raw frame), so the °T byte can be identified on 12 Nov. The core displays M/T/? and never assumes True. Conversion to TRUE belongs to Phase 2 (WIND-03), but the conventions module and its tests start now.
**Channel IDs relevant to DATA-03** (verbatim from `docs/channel_map.md`): `0x41 Boatspeed (Knots) navigation.speedThroughWater m/s`; `0x49 Heading navigation.heading{Magnetic,True} rad routed(M/T)`; `0x4F Apparent Wind Speed (m/s) environment.wind.speedApparent`; `0x51 Apparent Wind Angle environment.wind.angleApparent rad`; `0x56 True Wind Speed (m/s) environment.wind.speedTrue`; `0x59 True Wind Angle environment.wind.angleTrueWater rad`; `0x6D True Wind Direction environment.wind.direction{Magnetic,True} routed(M/T)`; `0x83 Tidal Drift environment.current.drift m/s`; `0x84 Tidal Set environment.current.set{Magnetic,True} routed(M/T)`; `0xC1/0xC2/0xC3 Depth environment.depth.belowTransducer m (depth fallback)`; `0xE9 Course Over Ground (True) navigation.courseOverGroundTrue`; `0xEB Speed Over Ground navigation.speedOverGround`.
**Sign:** AWA/TWA come out signed (`'-[data]'` → −1 via `layoutSign`). Samples in example2 range from −47° to +42°. Signal K's convention is negative = port, but **pyfastnet doesn't document which B&G glyph means port**, so treat the sign as `[ASSUMED]` and verify on the boat (see Open Questions).
**Logger noise:** pyfastnet attaches a `StreamHandler` at INFO on import (`logger.py`) and warns on buffer trim and queue full. When using `decode_frame` directly, call `set_log_level("WARNING")` and rely on our own counters.

### Pattern 4: Normalized delta message (UDP JSON, discretion)
One datagram per decoded frame (well under 1 KB). Bind `127.0.0.1:47100` only.
```json
{"v": 1, "src": "fastnet", "t_mono": 81234.512, "t_wall": 1762470000.123,
 "values": [
   {"path": "environment.wind.angleApparent", "value": -0.6109, "unit": "rad"},
   {"path": "navigation.heading", "value": 5.0091, "unit": "rad", "ref": "M", "ch": "0x49"}
 ],
 "bus": {"bytes_in": 123456, "bytes_discarded": 12, "frames_ok": 4980}}
```
- `t_mono` is the receiver's `time.monotonic()`. Replay/sim add `"t_sim"` (UTC epoch) so `SimClock` can follow message time.
- Also send a 1 Hz `{"src":"fastnet","health":{...}}` heartbeat **even when no bytes arrive**. That's how the core tells "ingest alive, bus silent" apart from "ingest dead".
- State store entry: `{value, unit, src, ref, t_mono_rx, t_utc}`. Age is computed from the clock's monotonic now. Staleness defaults: wind/BSP/HDG 5 s, GPS 3 s, depth 10 s, set/drift 60 s (configurable).

### Pattern 5: FastAPI WS hub with bounded per-client queues (verified)
```python
# Source: verified in this session with TestClient (3.13 + 3.14) and real uvicorn 0.54 + websockets 17.4
class Hub:
    def __init__(self): self.clients: set[asyncio.Queue[str]] = set()
    def publish(self, msg: str) -> None:
        for q in list(self.clients):
            if q.full():
                try: q.get_nowait()          # drop oldest: a slow tablet never blocks the core
                except asyncio.QueueEmpty: pass
            q.put_nowait(msg)

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=4); hub.clients.add(q)
    try:
        while True:
            await websocket.send_text(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(q)

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")   # mount LAST
```
Serialize **once** per tick, then fan out the same string. Push `{"type":"diag", ...}` at 1 Hz. Use a FastAPI `lifespan` context to start and stop the UDP listener, gpsd client, 1 Hz tick and sd_notify tasks. Run `uvicorn.Server(Config(app, host="0.0.0.0", port=..., workers=1, log_level="warning", ws="websockets"))` from `main.py`, so the same process owns the asyncio loop and the watchdog task. Measured RSS was about 49 MB on x86_64 for a minimal app (the Pi will differ).

### Pattern 6: Replay & simulation levels
- **L0 (bytes → pty):** `pty.openpty()`, `tty.setraw(master)`, give `os.ttyname(slave)` to the ingest via `--device`. Write chunks to the master, paced either at wire rate (28800 / 12 bits per byte = **2400 B/s**, the same formula as fastnet2ip `playback_fn.py`: `1 + bytesize + parity + stopbits`) × `--speed`, or by recorded `t_mono` deltas for timestamped captures. Closing the master gives the reader EOF (simulated unplug, verified). Faults: `--silence 60s`, `--garbage-rate`, `--invert` (byte-inverted gives 0 valid frames, i.e. the "swap wires" case).
- **Capture formats to accept:** (a) pyfastnet/fastnet2ip **hex-per-line, no timestamps** (`captures/README.md`: "Each line is one burst of bytes … lower-case hex with no separators"); (b) Jabuka raw log `"<t_mono> <t_wall> <hex>\n"`. Lines are not frame-aligned, so always feed through the framer.
- **L1 (deltas → UDP):** replay the core's received-delta log or a derived log at `--speed N`. Messages carry `t_sim` and the core runs `SimClock` (selected by `--clock sim`).
- **L2 (synthetic boat):** scripted TWD/TWS (+ shifts and gusts), boat on a constant heading or a scripted heading list, BSP from a placeholder polar function (the real polar is Phase 2). Compute AWA/AWS from TW + BSP vectors (conventions module), and GPS from dead reckoning. Two outputs: UDP deltas (default), or **encoded Fastnet bytes into the L0 pty**, which exercises the real ingest. Faults: bus silent, GPS loss, garbage bytes, clock jump (SimClock step), device unplug.
- **Minimal encoder (verified round-trip):** format `0x01` = signed int16 big-endian, with the divisor code in the top two bits of the format byte (`divisorByTopTwoBits: {0:1, 1:10, 2:100, 3:1000}`). Format `0x08` = byte0 `(layout<<1)|bit8`, byte1 = low 8 bits, with layout `0x66` = `°M`. Frame = `[0xFF, 0x05, len(body), 0x01, cks(hdr4)] + body + [cks(body)]`. `rec01(0x41, 4.77, 2) + rec01(0x51, -35, 0) + rec01(0x4F, 6.3, 1) + rec08(0x49, 287, 0x66) + rec01(0x59, 42, 0)` decoded to `{'navigation.speedThroughWater': 2.45389788, 'environment.wind.angleApparent': -0.6108652381980153, 'environment.wind.speedApparent': 6.3, 'navigation.headingMagnetic': 5.009094953223726, 'environment.wind.angleTrueWater': 0.7330382858376184}`.

### Pattern 7: Raw-first rotating logs, atomic state files
- `RotatingAppendLog(dir, prefix)`: open in append mode, `write()` per chunk, `flush()` every 1 s, `os.fsync()` every 10 s, rotate on UTC-hour change **or** size > 32 MB. File name `{prefix}-{YYYYmmddTHH}Z-{boot8}-{seq}.log`, where `boot8` is the first 8 characters of `/proc/sys/kernel/random/boot_id`. That avoids collisions when the system clock is wrong before GPS sync and then steps. Each line carries `t_mono` + `t_wall`. Readers tolerate a torn last line.
- Raw Fastnet line: `f"{t_mono:.3f} {t_wall:.3f} {chunk.hex()}\n"` (about 2× the bytes; worst case ~17 MB/h at 2400 B/s, ~620 MB per 36 h). Derived: one JSON line per second with the full state snapshot plus health. Events: `{"t_mono","t_wall","t_gps","label","state_ref"}`, fsync'd **immediately**.
- GPS raw: log every gpsd JSON line verbatim (`TPV`/`SKY`/`DEVICES`) with a receive timestamp. That is replayable through the same `gpsd_client.parse_line`.
- Disk guard: when free space < 1 GB, delete the oldest raw files first.
- **Atomic JSON** (config/state):
```python
def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    if path.exists():                       # keep previous version as .bak (atomic via hard link)
        bak_tmp = path.with_name(f".{path.name}.bak.tmp")
        bak_tmp.unlink(missing_ok=True); os.link(path, bak_tmp); os.replace(bak_tmp, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(dfd)
    finally: os.close(dfd)

def load_json_with_bak(path: Path, default):
    for p in (path, path.with_suffix(path.suffix + ".bak")):
        try: return json.loads(p.read_text())
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError): continue
    return default
```

### Pattern 8: Clock & time-valid gate
- `GpsClock.on_tpv(tpv, t_mono)`: accept only `mode >= 2` with `"time"` present. Parse with `datetime.fromisoformat()`, which accepts `Z` on 3.11+. Sanity: year in [2026, 2031] (guards against u-blox week rollover). Consistency: `|Δgps − Δmono| < 0.5 s` versus the previous accepted fix. **Synced after 3 consecutive consistent fixes.** `now_utc() = ref_utc + (monotonic() − ref_mono)`, and it holds over when GPS is lost (report `holdover_s`).
- `time_valid = synced` (holdover is allowed). `routing_time_gate = "ok" if time_valid else "blocked"`.
- System clock check (diagnostic only): `abs(time.time() − gps_now) < 1.0` → `system_clock: synced`, else `unsynced`. chrony will step it (`makestep 1 -1`). Domain code never reads `time.time()` / `datetime.now()`.
- `SimClock`: driven by `t_sim` in messages and by `advance()` in tests. Sleeps go through `clock.sleep()`, scaled by speed.

### Pattern 9: gpsd JSON client (asyncio)
```python
reader, writer = await asyncio.open_connection("127.0.0.1", 2947)
writer.write(b'?WATCH={"enable":true,"json":true};\n'); await writer.drain()
async for line in reader:          # readline-based; gpsd sends one JSON object per line
    rawlog.write_line(line)        # raw-first
    msg = json.loads(line)
    match msg.get("class"):
        case "TPV": ...            # mode, time, lat, lon, track (deg true), speed (m/s), eph, ept
        case "SKY": ...            # uSat / nSat / hdop, satellites[].used
        case "VERSION" | "DEVICES" | "WATCH": ...
```
Reconnect with backoff (1 → 5 s) if gpsd restarts. Field semantics from the official doc: TPV `mode` 0=unknown, 1=no fix, 2=2D, 3=3D; `time` is ISO8601 UTC and "may be absent if the mode is not 2D or 3D", or "present, but invalid, if there is no fix"; `track` = "Course over ground, degrees from true north"; `speed` = m/s; `magvar` positive **West** (careful: the opposite sign to our East-positive variation). SKY `uSat`, `nSat`, `hdop`, `satellites[].used`. VERSION is sent on connect, DEVICES in the WATCH response. [CITED: gpsd.gitlab.io/gpsd/gpsd_json.html]
Normalize: `navigation.position {latitude, longitude}` (deg), `navigation.courseOverGroundTrue` (rad), `navigation.speedOverGround` (m/s), `navigation.datetime`, plus `gps.mode`, `gps.satellites`, `gps.hdop`.

### Pattern 10: systemd watchdog without libsystemd
```python
# Source: protocol per sd_notify(3) "Standalone Implementations" (freedesktop.org)
import os, socket
def sd_notify(state: str) -> bool:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False                       # not under systemd (laptop/tests): no-op
    if addr[0] == "@":
        addr = "\0" + addr[1:]             # Linux abstract namespace
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
        s.connect(addr); s.sendall(state.encode())
    return True
# Startup done:  sd_notify("READY=1")
# Asyncio task:  interval = int(os.environ.get("WATCHDOG_USEC", "0")) / 2e6; loop: sd_notify("WATCHDOG=1"); await asyncio.sleep(interval)
# Shutdown:      sd_notify("STOPPING=1")
```
The watchdog ping runs **inside the event loop**, so a blocked loop stops the pings and systemd restarts the service. Pinging every `WATCHDOG_USEC/2` is the conventional rate `[ASSUMED: sd_watchdog_enabled(3) guidance, not fetched]`. Use 10 s pings with `WatchdogSec=30` either way.

### Anti-Patterns to Avoid
- **Using `FrameBuffer(project=True)` output as-is for heading/TWD/set:** the M/T information is lost and silently defaults to Magnetic.
- **`BindsTo=dev-fastnet.device`** (as in fastnet2ip's unit): the service would not start without the adapter, and health could not report "device missing". Use the in-process reconnect loop instead.
- **Ages computed in the browser:** use server-side ages from the injected clock.
- **`time.time()` in domain code:** inject the clock everywhere, and add a ruff/grep test that bans it under `core/` and `common/` except in `clock.py`.
- **`uvicorn[standard]` on the Pi:** watchfiles/uvloop/httptools are unnecessary and add RAM.
- **Asserting parity on a pty in tests:** ptys clear `PARENB`. Test parity on the Pi.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fastnet channel decoding, scaling, units, SK paths | Own decoder tables | pyfastnet `decode_frame` + `project` + `unit_for` | About 100 channels with format templates and depth fallback, all data-driven and tested upstream |
| Framing *algorithm* | A "smarter" framer | A copy of porting.md §2 exactly (counting only) | The vectors depend on the exact resync and wait-for-length behaviour. Prove equivalence by test. |
| Custom baud 28800 on Linux | Own `TCSETS2` ioctl | pyserial `_reconfigure_port` (via subclass) | BOTHER path already proven |
| GPS device handling + system clock | Own NMEA reader + `date -s` via sudo | gpsd `-n` + chrony SHM 0 | Hotplug, clock slewing/stepping, `gpsfake` |
| Wi-Fi AP + DHCP | hostapd + dnsmasq configs | `nmcli` `ipv4.method shared` | NM starts its own DHCP/DNS forwarder (`nm-settings-nmcli`: "NetworkManager starts a DHCP server and DNS forwarder") |
| Service supervision/restart | Own watchdog daemon | systemd `Restart=always` + `WatchdogSec` + `RuntimeWatchdogSec` | Standard, survives core hangs and kernel hangs |
| WS protocol | Raw socket handling | Starlette WebSocket + websockets lib | |

**Key insight:** the only custom bus code worth writing is *observability*: the counting framer, the M/T ref capture and the probe verdicts. Everything that interprets bytes goes through pyfastnet, so a fix on 12 Nov (e.g. adding the `°T` segment code) is a one-line `fastnet.json` change upstream, or a local override.

## Deploy / Provisioning Facts

### First boot (human, documented in `deploy/PI-SETUP.md`)
- Flash **Raspberry Pi OS Lite 64-bit (Trixie)** with Raspberry Pi Imager 2.x. Trixie uses **cloud-init**: Imager writes `user-data`, `network-config` and `meta-data` to the FAT boot partition (editable without root). Set hostname `jabuka`, user, SSH public key, **Wi-Fi country HR**, timezone. [CITED: raspberrypi.com/news/cloud-init-on-raspberry-pi-os/]
- **Provision over Ethernet** (the Pi 3B has an RJ45 port). The Pi 3B has one radio, so bringing up the AP drops any Wi-Fi-client SSH session (stated in the raspi-cam-srv Trixie hotspot doc). Install everything first, then switch wlan0 to AP mode. Delete or disable any Imager-created Wi-Fi client profile, so the AP is the only autoconnect wlan0 profile.

### `deploy/provision.sh` (idempotent, run as root) — required steps
```bash
apt-get update && apt-get install -y gpsd gpsd-clients chrony python3-venv pipx dnsmasq-base jq
apt-get purge -y modemmanager brltty || true      # probes/grabs USB serial devices
# gpsd: explicit device, no USB autoprobe, keep device open (-n) for chrony
install -m644 deploy/gpsd.default /etc/default/gpsd
install -m644 deploy/udev/99-jabuka.rules /etc/udev/rules.d/ && udevadm control --reload && udevadm trigger
install -m644 deploy/chrony-gps.conf /etc/chrony/conf.d/gps.conf
sed -i 's/^makestep 1 3$/makestep 1 -1/' /etc/chrony/chrony.conf
systemctl enable --now chrony gpsd
# AP (fixed IP, WPA2-PSK, PMF off for brcmfmac/Android compatibility, no power save)
nmcli con add type wifi ifname wlan0 con-name jabuka-ap autoconnect yes ssid jabuka \
  802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
  802-11-wireless.powersave 2 \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$JABUKA_PSK" wifi-sec.proto rsn \
  wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.pmf disable \
  connection.autoconnect-priority 100
# app user, venv from wheelhouse, units, journald, hardware watchdog
useradd --system --home /var/lib/jabuka --groups dialout jabuka || true
# ... venv install (see Standard Stack), install units, systemctl daemon-reload, enable --now
```
Verified facts behind these lines:
- Trixie `/etc/default/gpsd` ships `DEVICES=""`, `GPSD_OPTIONS=""`, `USBAUTO="true"`. **Set** `DEVICES="/dev/gps"`, `GPSD_OPTIONS="-n"`, `USBAUTO="false"`. [VERIFIED: sources.debian.org gpsd 3.25-5+deb13u2 debian/gpsd.default]
- Debian's gpsd udev rules **disable** the FTDI 0403:6001 match (`# !!! rule disabled in Debian as it matches too many other devices` / `# ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", …`) but **enable** u-blox 7: `ATTRS{idVendor}=="1546", ATTRS{idProduct}=="01a7", SYMLINK+="gps%n", @UDEVCOMMAND@`. With `USBAUTO="false"` the hotplug add is suppressed. [VERIFIED: gpsd.rules.in lines 32–34, 51–52]
- gpsd unit: `After=chronyd.service`, `EnvironmentFile=-/etc/default/gpsd`, `ExecStart=@SBINDIR@/gpsd $GPSD_OPTIONS $OPTIONS $DEVICES`. [VERIFIED: systemd/gpsd.service.in]
- Trixie `chrony.conf` active lines include `pool 2.debian.pool.ntp.org iburst`, `rtcsync`, `makestep 1 3`, `confdir /etc/chrony/conf.d`. [VERIFIED: chrony 4.6.1-3+deb13u2 debian/chrony.conf lines 5, 35, 39, 47]. chrony `makestep`: "A negative value disables the limit." [CITED: chrony-project.org chrony.conf doc]
- `nmcli` properties `802-11-wireless.powersave` ("disable" (2)), `802-11-wireless-security.pmf` ("disable" (1)), `802-11-wireless-security.proto` ("rsn"), and `ipv4.method shared` ("If you do not specify an IP address … assigns 10.42.x.1/24 … starts a DHCP server and DNS forwarder"). [VERIFIED: local `man nm-settings-nmcli`, NM 1.56.1; Trixie ships an older 1.5x with the same long-standing properties `[ASSUMED]`]

### `deploy/chrony-gps.conf`
```
# gpsd NMEA time via SHM 0 (gpsd runs as root first → segment 0 is usable). No PPS on the VK-162.
refclock SHM 0 refid GPS precision 1e-1 offset 0.2 delay 0.2
```
The gpsd HOWTO's example `offset 0.9999` is explicitly "a placeholder … not a number to be used in production". NMEA-only time has roughly 100 ms-class wobble, which is fine for the ±1 s requirement. Tune `offset` on the Pi with `chronyc sourcestats` if desired. gpsd must run `-n` "so the clock will be updated even when no clients are active", and chronyd should start before gpsd. [CITED: gpsd.gitlab.io/gpsd/gpsd-time-service-howto.html]

### `deploy/udev/99-jabuka.rules`
```
# DTECH RS485 (FTDI FT232R). Group read-only: the jabuka user cannot open it for writing even by mistake.
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="fastnet", GROUP="dialout", MODE="0640", ENV{ID_MM_DEVICE_IGNORE}="1", TAG+="systemd"
# VK-162 (u-blox 7)
SUBSYSTEM=="tty", ATTRS{idVendor}=="1546", ATTRS{idProduct}=="01a7", SYMLINK+="gps", ENV{ID_MM_DEVICE_IGNORE}="1", TAG+="systemd"
```
If more than one FT232 might be attached, add `ATTRS{serial}=="<DTECH serial>"` (read it with `udevadm info -a -n /dev/ttyUSB0` on the Pi, a human step). The VID:PID pairs come from CONTEXT and the gpsd rules. Confirm with `lsusb` on the Pi.

### systemd units
```ini
# jabuka-ingest-fastnet.service
[Unit]
Description=Jabuka Fastnet ingest (receive-only)
Conflicts=fastnet2ip.service
StartLimitIntervalSec=0
[Service]
Type=notify
User=jabuka
Group=jabuka
SupplementaryGroups=dialout
ExecStart=/opt/jabuka/venv/bin/jabuka-ingest-fastnet --device /dev/fastnet
Restart=always
RestartSec=2
WatchdogSec=30
StateDirectory=jabuka
OOMScoreAdjust=-700
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/jabuka
[Install]
WantedBy=multi-user.target

# jabuka-core.service
[Unit]
Description=Jabuka core (state, logging, diagnostics web)
Wants=gpsd.service
After=network.target gpsd.service
StartLimitIntervalSec=0
[Service]
Type=notify
User=jabuka
ExecStart=/opt/jabuka/venv/bin/jabuka-core --http-port 80
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
RestartSec=2
WatchdogSec=30
StateDirectory=jabuka
OOMScoreAdjust=-500
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/jabuka
[Install]
WantedBy=multi-user.target
```
- `/etc/systemd/journald.conf.d/jabuka.conf`: `[Journal]` `Storage=volatile`, `RuntimeMaxUse=32M`. App logs live in `/var/lib/jabuka/logs`.
- `/etc/systemd/system.conf.d/watchdog.conf`: `[Manager]` `RuntimeWatchdogSec=15` (arms the BCM2835 hardware watchdog; its maximum timeout is around 15 s `[ASSUMED]`, so check that `dmesg | grep -i watchdog` shows it active on the Pi).
- Keep `fake-hwclock` (Pi OS default). It restores the last saved time at boot, so log times are roughly monotonic before GPS.

## Common Pitfalls

### Pitfall 1: Heading/TWD/Set labelled Magnetic when the instrument is set to True
**What goes wrong:** the projection defaults any non-`°T` layout to `...Magnetic`, and the `°T` code is unknown. **How to avoid:** use the rich decode and keep `ref ∈ {M,T,?}` plus the raw layout byte (Pattern 3). **Warning signs:** the diagnostics page shows `ref=?` on 0x49/0x6D/0x84, or a layout byte that isn't `0x66`.

### Pitfall 2: Probe can't tell "wrong wiring" from "silent bus"
**Cause:** `FrameBuffer` doesn't count failures. **How to avoid:** `CountingFramer` stats plus these verdicts, all computed over a ≥5 s window:
- `bytes_in == 0` → "NO BYTES: wires on T/R+ T/R− (not RXD±)? adapter in RS485 mode? instruments powered?"
- `bytes_in ≥ 2000 and frames_ok == 0` → "BYTES BUT NO VALID FRAMES: swap White/Green (A/B); confirm 28800 8O2"
- `valid_ratio = 1 − bytes_discarded/bytes_in < 0.9` → "NOISY: connect Black→GND; remove any added termination"
- else "OK: N frames/s, K channels"

Random noise produces 0 queued frames (verified on 2 MB), so `frames_ok == 0` is a strong signal.
**Optional extra signal:** `TIOCGICOUNT` (`0x545D`) parity/frame-error counters on the FTDI. It returns `ENOTTY` on a pty (verified), so it must degrade gracefully. Whether ftdi_sio populates parity counts is `[ASSUMED]`.

### Pitfall 3: pty tests give false confidence about serial settings
ptys ignore parity (`PARENB` reads back False) and don't enforce baud. Everything about the physical layer (`stty -F /dev/fastnet` showing `speed 28800 … parenb parodd cs8 cstopb`) is a **Pi human-verify item**.

### Pitfall 4: Framer stall at end of a replay file
A corrupt byte claiming a long body makes the framer wait for more bytes (by design, verified). In live use more bytes always arrive. In tests, feed the whole capture before asserting counts and don't expect trailing partial frames.

### Pitfall 5: gpsd grabs or probes the wrong device / ModemManager / brltty
Set `USBAUTO="false"` and an explicit `DEVICES="/dev/gps"`, purge modemmanager and brltty, and add `ID_MM_DEVICE_IGNORE`. **Verify on the Pi:** `sudo lsof /dev/ttyUSB*` shows only `jabuka-ingest-fastnet`, and `ls -l /dev/fastnet` shows `crw-r----- root dialout`.

### Pitfall 6: Time-valid too eager (no-fix TPV carrying a bogus time)
TPV `time` may be "present, but invalid, if there is no fix". Require `mode ≥ 2`, the year window, and 3 consistent fixes. Also note gpsd `magvar` is **positive West**, the opposite of our East-positive convention. If it's ever used, convert explicitly with a golden test.

### Pitfall 7: Restart storms and the start-rate limit
The default `StartLimitBurst`/`IntervalSec` can stop restarts permanently after a crash loop (e.g. the adapter is unplugged and the code exits). Use `StartLimitIntervalSec=0` **and** don't exit on a missing device.

### Pitfall 8: Python 3.14-only code that breaks on the Pi's 3.13
Python 3.14 evaluates annotations lazily (PEP 649), so forward references that work on 3.14 fail on 3.13. Also avoid unparenthesized `except A, B:` (3.14 syntax), t-strings and `annotationlib`. **How to avoid:** `requires-python = ">=3.13"`, ruff `target-version = "py313"`, `from __future__ import annotations` in modules with forward references, and **run the suite under `/usr/bin/python3.13`** (available on the laptop) as well as 3.14.

### Pitfall 9: AP drops SSH / home Wi-Fi profile competes with AP
Provision over Ethernet, and remove client Wi-Fi profiles from NM before enabling the AP.

### Pitfall 10: pyfastnet log spam into journald
The module installs a stderr handler at INFO and warns on buffer trims. Call `set_log_level("WARNING")` at ingest start and count events ourselves.

## Code Examples

The tested snippets are in Patterns 1, 2, 5, 7, 9 and 10 above. The minimal encoder used for L2 and tests (verified round-trip):
```python
# Source: verified in this session (scratchpad encode_rt.py) against pyfastnet 3.2.1 decode_frame/project
import struct
def cks(b: bytes) -> int: return (-sum(b)) & 0xFF
def rec01(ch: int, value: float, decimals: int) -> bytes:        # signed int16 BE, divisor 10**decimals
    return bytes([ch, (decimals << 6) | 0x01]) + struct.pack(">h", round(value * 10**decimals))
def rec08(ch: int, value_int: int, layout_code: int) -> bytes:    # 9-bit unsigned + 7-bit layout (0x66=°M)
    return bytes([ch, 0x08, ((layout_code & 0x7F) << 1) | ((value_int >> 8) & 1), value_int & 0xFF])
def frame(body: bytes, to=0xFF, frm=0x05, cmd=0x01) -> bytes:
    hdr = bytes([to, frm, len(body), cmd]); return hdr + bytes([cks(hdr)]) + body + bytes([cks(body)])
```

**Vendored fixtures** (MIT; copy `LICENSE` as `tests/fixtures/fastnet/LICENSE-pyfastnet`, and record the SHAs in `SOURCES.md`):
- pyfastnet @ `59bc23be0dbd797ce12d5dc5e0389583dd52f92b`: `https://raw.githubusercontent.com/ghotihook/pyfastnet/59bc23be0dbd797ce12d5dc5e0389583dd52f92b/captures/{big.txt,big_with_ap_actions.txt,example1_fastnet_data.txt,example2_fastnet_data.txt,heel-port.txt,heel-stb.txt,trim-neg.txt,trim-pos.txt}` (445 KB total)
- fastnet2ip @ `9e6ac4495ec6e1482e4094e093de2e18f009b216` (3.3.1, MIT): `tests/data/rawfn-20260502-011827.txt` (has layout-`None` Heading frames, so it's the M/T `?` test case) and `tests/data/ap_backlight_20260514.txt`. Its `tests/data/big.txt` is byte-identical to pyfastnet's (verified with `cmp`).
- No GPS captures exist. Build synthetic gpsd JSON fixtures (TPV/SKY/VERSION/DEVICES lines following the documented fields) and an NMEA RMC/GGA sample with valid checksums.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pyfastnet v2: rich `{name: {value, display_text, layout}}` | v3: `FrameBuffer(project=True)` queues `{signalk_path: SI}` by default; `project=False` gives the rich decode | 3.0.0 (2026-07-22) | Use `project=False` + `project()` to get both |
| Raspberry Pi OS `firstrun.sh` customisation | cloud-init `user-data`/`network-config` on the boot partition | Trixie images + Imager 2.0 | Headless setup files differ from older tutorials |
| hostapd/dnsmasq AP | NetworkManager `nmcli` AP, `ipv4.method shared` | Bookworm onward | |
| `starlette.testclient` on httpx | prefers `httpx2`, httpx deprecated with a warning | Starlette 1.x (2026) | Add a pytest filterwarnings entry |

**Deprecated/outdated:** fastnet2ip's `--file` replay (paces at about 5 KB/s, no timestamps). Use our timestamped raw log plus pty replay instead.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Negative AWA/TWA from pyfastnet = port (Signal K convention); B&G `-`/`=` prefix glyph means port | Pattern 3 | True wind/laylines mirrored. Verify on the boat by comparing the display and a tack (Phase 4 runbook). Phase 2 must not hard-code it without a config flip. |
| A2 | VK-162 enumerates as u-blox 7 `1546:01a7`; DTECH as FTDI `0403:6001` | udev rules | Symlinks not created. Fix with `lsusb` on the Pi (5 min). |
| A3 | `offset 0.2` is a reasonable chrony SHM 0 offset for a USB u-blox 7 | chrony conf | Clock off by a few hundred ms (requirement ±1 s, so low risk) |
| A4 | BCM2835 hardware watchdog max ≈15 s, so `RuntimeWatchdogSec=15` is accepted | systemd | systemd logs a warning and clamps. Low risk. |
| A5 | PMF must be disabled for some clients on brcmfmac AP | nmcli | Some tablets can't join. Toggle `pmf` (human check with the real tablet). |
| A6 | Pi OS keeps Wi-Fi rfkill-blocked until a Wi-Fi country is set | First boot | AP doesn't come up. Imager sets the country; `raspi-config nonint do_wifi_country HR` as a backup. |
| A7 | Trixie's NetworkManager supports the same `nmcli` properties as the laptop's 1.56.1 | nmcli | Command error at provisioning (visible immediately) |
| A8 | Pinging `WATCHDOG=1` at `WATCHDOG_USEC/2` is the documented recommendation | Pattern 10 | None in practice (10 s ping vs 30 s timeout) |
| A9 | ftdi_sio fills `TIOCGICOUNT` parity/frame counters | Pitfall 2 | Optional probe signal missing. The verdict still works from the framer stats. |
| A10 | brltty might grab FTDI devices if present | provision.sh | Harmless purge |
| A11 | DTECH auto-direction RS-485 never drives the bus without TX data, so skipping DTR/RTS setup is safe | Pattern 1 | Very low. The fd can't write anyway, but this is the reason the bus stays quiet. |

## Open Questions

1. **AWA sign convention on this Hercules.** Known: values are signed via `layoutSign` (`-[data]`/`=[data]`/`L[data]`/`H[data]` → −1). Unclear: whether negative means port. Recommendation: the Phase 1 diagnostics show the raw `display_text` glyph next to the value, plus a config `awa_sign: +1|-1` (default +1, SK convention). The commissioning runbook checks it.
2. **`°T` layout byte value.** Unknown upstream. Recommendation: log any unknown layout byte with its channel in the inventory. The probe inventory JSON includes `layouts_seen` per channel, so the boat capture on 12 Nov answers it.
3. **Whether the core should log every received delta (L1 source).** Recommendation: yes, a `bus-*.log` of received datagrams (cheap, ~1–5 KB/s). It makes L1 replay of a real session trivial.
4. **gpsfake on the laptop.** gpsd isn't installed (`sudo` needed). Recommendation: tests use `sim/fake_gpsd.py`. gpsfake is an optional human-run integration step.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14 | dev/tests | ✓ | 3.14.7 | — |
| Python 3.13 | Pi-parity test run | ✓ | 3.13.12 (`/usr/bin/python3.13`) | — |
| uv | env/lock | ✓ | **0.6.6** (not 0.13) | — |
| pip (download wheelhouse) | Pi offline install | ✓ | 26.0.1 | — |
| git, ssh, scp, rsync, sshpass, jq, socat, stty | provisioning/dev | ✓ | — | — |
| gpsd / gpsfake / gpspipe (laptop) | optional GPS replay | ✗ | apt candidate 3.27.5 | `sim/fake_gpsd.py` (tests). Human may `sudo apt install gpsd-clients`. |
| chrony (laptop) | not needed | ✗ | — | — |
| rpi-imager | flashing | ✗ | — | Human installs Imager, or `xz -dc image | dd` (dd and xz available) |
| Raspberry Pi 3B + DTECH + VK-162 | on-hardware verification | human | — | All automated checks run on the laptop |
| Network access to PyPI / GitHub / Debian | lock, wheelhouse, fixture fetch | ✓ (worked this session) | — | — |

**Missing dependencies with no fallback:** none for automated work. Pi hardware steps are human-verify items (per CONTEXT).
**Missing with fallback:** gpsd tools (fake gpsd server), rpi-imager (dd).

## Test Strategy (laptop-verifiable, per success criterion)

`workflow.nyquist_validation` is `false` in config, so there's no formal Validation Architecture section. This maps the phase success criteria to automated checks as the orchestrator requested.

| Success criterion | Automated (laptop, `pytest`, < 30 s total target) | Human-verify on Pi |
|---|---|---|
| SC1 AP + diagnostics page lists every value with unit/source/age + health | `TestClient`: `GET /` returns the page. L1 fixture deltas → `/ws` message contains every expected path with `unit`, `src`, `age_s`, `ref`, and the `bus`/`gps`/`clock` health blocks. The staleness colour class flips after `SimClock.advance(6)`. | Join SSID `jabuka`, open `http://10.42.0.1/` with mobile data off |
| SC2 probe reports frames/checksums/IDs, swap hint, inventory; no transmit; raw-first | Probe against pty replay of `example2` → verdict OK, channels include 0x41/0x49/0x51. Against the byte-**inverted** capture → "swap" verdict. Against silence → "no bytes". Inventory JSON schema check. `ReadOnlySerial` fd `O_ACCMODE==O_RDONLY` and `os.write` → `EBADF`. Static test: no `.write(`/`O_RDWR`/`O_WRONLY`/`send_break` in `ingest/` + `tools/`. Raw-first: inject a decoder exception and assert the chunk is already in the raw log. CountingFramer ≡ FrameBuffer on all 10 fixtures (golden counts table). | `stty -F /dev/fastnet`; `lsof` single reader; `ls -l /dev/fastnet` 0640; probe on the real bus (12 Nov) |
| SC3 clock from GPS, unsynced until valid, gate blocked | `GpsClock` unit tests: mode<2 ignored, bad year rejected, 3-fix sync, holdover. Fake gpsd server → core shows `time_valid=false`/`routing_time_gate=blocked`, then `ok` after 3 TPVs. `magvar` sign golden test. | `chronyc sources` shows `#* GPS`; boot with no internet and a stale fake-hwclock |
| SC4 replay + sim with faults at accelerated speed through the same pipeline | End-to-end: pty replay (speed 20×) → real ingest main (subprocess) → UDP → core (in-process) → state contains decoded paths. L2 sim encoded-bytes mode round-trips. Faults: silence → wind paths stale and bus health "silent"; garbage → `bytes_discarded` rises with no crash; GPS loss → gps stale + holdover; clock jump → no negative ages. | — |
| SC5 logs + event marker; recovery after kill / power pull without corruption | `POST /api/event` → line in the events JSONL (fsync'd). Derived log has about 1 line/s under SimClock. Rotation on hour change and size. Torn-line tolerant reader. `atomic_write` crash simulation (truncated main file → loads `.bak`). `sd_notify` sends READY/WATCHDOG to a test `AF_UNIX` datagram socket via a `NOTIFY_SOCKET` env (both `/path` and `@abstract`). `systemd-analyze verify deploy/systemd/*.service` (runs on the laptop if systemd is present). | `kill -9` each service and see it return in ≤ 2 s; 5× power pull; unplug/replug DTECH and GPS while running |

**Commands:** quick `uv run pytest -q -x`; full `uv run pytest -q && /usr/bin/python3.13 -m pytest -q` (or a second `.venv313`); lint `uv run ruff check . && uv run ruff format --check .`.

**Wave 0 gaps (greenfield):** `pyproject.toml` (pytest `asyncio_mode="auto"`, `filterwarnings` for the starlette httpx deprecation, ruff py313), `tests/conftest.py` (pty fixture, SimClock fixture, fake gpsd fixture, free-UDP-port fixture), vendored fixtures + `SOURCES.md`.

## Security Domain

`security_enforcement` is enabled, ASVS level 1.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | WPA2-PSK on the AP is the perimeter. No app login in v1. SSH key-only (`PasswordAuthentication no`). |
| V3 Session Management | no | No sessions |
| V4 Access Control | partial | Diagnostics are read-only. The only write endpoint, `POST /api/event`, appends a log line. The UDP bus binds `127.0.0.1` only. |
| V5 Input Validation | yes | Pydantic model for `/api/event` (label ≤ 200 chars, strip control chars). UDP datagrams: size cap (8 KB), `json.loads` in try, schema version check, numeric finite check (`math.isfinite`), drop silently with a counter. gpsd lines: same. |
| V6 Cryptography | no | No crypto in scope (WPA2 by NM) |
| V7 Error/Logging | yes | No secrets in logs. The PSK lives in an env/file outside git (`deploy/secrets.env`, gitignored). |
| V12 Files | yes | Log paths are built from fixed prefixes (no user input in file names). Atomic writes. |
| V14 Configuration | yes | systemd hardening (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths`), non-root `jabuka` user, device mode 0640 |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Any process transmits onto the Fastnet bus | Tampering (boat safety) | `O_RDONLY` fd + udev 0640 + no write code (static test) + ModemManager/brltty purge + gpsd `USBAUTO=false` + `Conflicts=fastnet2ip` |
| Nearby device joins the AP and spams events / WS | DoS / Tampering | WPA2-PSK, bounded WS queues, event endpoint rate limit (e.g. 1/s) |
| Malformed UDP/JSON crashes the core | DoS | try/except per datagram, counters, `Restart=always` |
| Log disk exhaustion over 36 h | DoS | Size-capped rotation + free-space guard |

## Sources

### Primary (HIGH confidence)
- pyfastnet 3.2.1 installed from PyPI plus repo @ 59bc23b. Read: `fastnet_decoder/__init__.py`, `frame_buffer.py`, `interpreter.py` (lines 1–64, 760–1152), `logger.py`, `utils.py`, `data/fastnet.json` lookups/formatTemplates/scaling, `docs/protocol.md`, `docs/porting.md` §2–3, `docs/signalk-design.md`, `docs/channel_map.md`, `captures/README.md`, `examples/replay_capture.py`. Decoded all captures.
- fastnet2ip repo @ 9e6ac44 (3.3.1): `core/input.py`, `tools/record_fn.py`, `tools/playback_fn.py`, `fastnet2ip.service`, `pyproject.toml`, README, `docs/uart_first_open_baud_fix.md`.
- pyserial 3.5 `serial/serialposix.py` (open() lines 311–364).
- Local experiments (this session): pty replay, O_RDONLY behaviour, asyncio `add_reader`, inverted/random byte framing, encoder round-trip, FastAPI WS (TestClient and real uvicorn+websockets), RSS, uv lock + aarch64 wheelhouse download, TIOCGICOUNT on pty.
- sources.debian.org: gpsd 3.25-5+deb13u2 (`debian/gpsd.default`, `gpsd.rules.in`, `systemd/gpsd.service.in`), chrony 4.6.1-3+deb13u2 `debian/chrony.conf`.
- PyPI JSON API: versions, release dates, requires_python, aarch64 cp313 wheels.
- `man nm-settings-nmcli` (NM 1.56.1, local).

### Secondary (MEDIUM confidence)
- https://gpsd.gitlab.io/gpsd/gpsd_json.html: WATCH, TPV, SKY, VERSION, DEVICES fields
- https://gpsd.gitlab.io/gpsd/gpsd-time-service-howto.html: SHM refclock lines, `-n`, start order, placeholder offset warning
- https://chrony-project.org/doc/4.6/chrony.conf.html: makestep negative limit, refclock options
- https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html: NOTIFY_SOCKET, abstract `@`, READY/WATCHDOG/STOPPING, standalone reimplementation endorsed
- https://signag.github.io/raspi-cam-srv/4.6/bp_Hotspot_Trixie: nmcli AP on Trixie, SSH drop on activation
- https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/: Trixie cloud-init first boot

### Tertiary (LOW confidence)
- https://lists.freedesktop.org/archives/networkmanager/2022-December/000013.html and https://community.volumio.com/t/volumio-will-not-connect-to-ubuntus-default-hotspot/67508: the PMF-disable workaround for AP clients
- https://www.hackster.io/news/raspberry-pi-aims-for-more-flexible-os-configuration-with-a-move-to-cloud-init-4394fd2c5adc: cloud-init coverage

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH. Installed and run on 3.13 and 3.14. Lock and aarch64 wheelhouse produced.
- pyfastnet API / framing / M/T behaviour: HIGH. Source read and all captures decoded.
- Serial receive-only + pty replay: HIGH for pty behaviour. MEDIUM for FTDI specifics (parity, TIOCGICOUNT), which are human-verify items.
- gpsd/chrony/NM/systemd deploy: MEDIUM. Official docs and Debian sources, not run on a Pi.
- Bus-specific semantics (AWA sign, °T code, Hercules 390 channels): LOW, until the boat capture on 12 Nov.

**Research date:** 2026-11-06
**Valid until:** 2026-11-13 (race). Package pins stay valid. Re-check only if the Pi OS image changes.
