# Walking Skeleton — Jabuka (Live Race Routing & Laylines for an X35)

**Phase:** 1
**Generated:** 2026-11-06

## Capability Proven End-to-End

A recorded B&G Fastnet capture, replayed byte-for-byte into a pseudo-terminal, is read by the receive-only ingest process. The ingest writes the raw bytes to disk, then frames and decodes them, and sends normalized deltas to the core. The core shows every decoded value in a browser, with unit, source, M/T reference and age. Pressing the "Event marker" button on that page writes a marker into the on-disk event log.

This is delivered by Plan 01-01, task 1 (tracer) plus task 2 (event marker write path). It is proven by `tests/test_tracer_e2e.py`, which runs the same three commands a developer types: `jabuka-replay`, `jabuka-ingest-fastnet` and `jabuka-core`.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Target OS | Raspberry Pi OS Lite **64-bit Trixie** (Debian 13, Python 3.13), flashed clean | Only aarch64 has PyPI wheels for the later numpy/pygrib stack. Trixie ships Python 3.13, gpsd 3.25, chrony 4.6 and NetworkManager (RESEARCH §Standard Stack). |
| Language / runtime | Python, `requires-python >=3.13`, ruff `target-version = "py313"`. Developed on 3.14.7, and the suite also runs under `/usr/bin/python3.13` | The Pi runs 3.13, and code that only works on 3.14 (lazy annotations, `except A, B:`) must fail on the laptop first. |
| Package / env tooling | `uv` 0.6.6 (`uv venv`, `uv pip install -e ".[dev]"`, `uv pip compile`), hatchling build backend, `pip download` for the aarch64 wheelhouse | Locked by CONTEXT. uv 0.6.6 has no `uv pip download`, so pip does that one step. |
| Process model | Three processes. `jabuka-ingest-fastnet` owns the serial device. `jabuka-core` holds state, logs and web, on one asyncio loop with a single uvicorn worker. gpsd + chrony are OS services. Dev tools (`jabuka-replay`, `jabuka-replay-msgs`, `jabuka-sim`, `jabuka-fake-gpsd`, `fastnet-probe`, `jabuka-logcheck`) feed the same entry points | A crash in one process does not take down the others. Only one process may own the RS-485 port. |
| Bus safety | The serial port is opened **`O_RDONLY`** by `ReadOnlySerial` (a pyserial subclass), so any write fails with `EBADF`. udev sets `MODE="0640"` and an AST test bans write paths | The bus must never be disturbed, and this is enforced by the kernel rather than by discipline. |
| Decoding | pyfastnet 3.2.1 `decode_frame` (rich) + `project()`. Our `CountingFramer` mirrors pyfastnet's framing for error counters, and an equivalence test on 10 vendored captures proves they match | No hand-rolled channel tables. The M/T layout is kept as `ref ∈ {M,T,?}`. |
| IPC | JSON datagrams on UDP `127.0.0.1:47100`, schema `v=1`, max 8192 B (`jabuka.common.messages`). Every message carries `t_mono`/`t_wall` and, for replay and sim, `t_sim` | It is simple and loss-tolerant, and replay (L1) and the simulator (L2) inject at the same seam as live ingest. |
| Internal units / naming | SI units (rad, m/s, m, K) and Signal K-style paths. Paths for directions that may be magnetic or true don't name M/T (`navigation.heading`, `environment.wind.direction`, `environment.current.set`); a separate `ref` field carries it | Mixing up true and magnetic is the classic silent bug. Conversion to TRUE happens at one boundary, in Phase 2 (WIND-03). |
| Time | An **injected `Clock`** (`SystemClock`, `SimClock`, `GpsClock`) used by all core and common logic. `routing_time_gate: blocked|ok` comes from GPS sync. `time.time()`/`datetime.now()` are banned outside `common/clock.py` (enforced by a test) | The Pi has no RTC and no internet. Accelerated replay needs sim time. |
| Data layer | No database. The state is an in-memory `StateStore` (latest value per path, with server-side age). Logs are append-only rotating line logs (`raw`, `bus`, `gps`, `derived` JSONL at 1 Hz, `events` JSONL), flushed every 1 s, fsync'd every 10 s (events immediately), rotated hourly or at 32 MB, with a free-space guard. Config and state files use atomic write + `.bak` (`jabuka.common.atomicio`) | Survives power cuts. Line logs tolerate a torn last line (`iter_log_lines`). |
| Web | FastAPI 0.162 + plain uvicorn 0.54 + websockets 17.4. Endpoints: `GET /api/state`, `WS /ws` (1 Hz `{"type":"diag"}`, bounded per-client queues that drop the oldest message), `POST /api/event`, and static files mounted last. The frontend is plain HTML + ES module, with no build chain and no external assets | Locked by CONTEXT. Works offline on any tablet browser. |
| Auth | No app login. The perimeter is the WPA2-PSK AP. The only write endpoint (`/api/event`) is validated and rate-limited to 1/s. UDP binds to localhost only | ASVS L1, single-boat appliance. |
| Deployment | `deploy/provision.sh` (idempotent, run as root over Ethernet) sets up the NetworkManager AP `jabuka` at **10.42.0.1/24** (`ipv4.method shared`), udev `/dev/fastnet` and `/dev/gps`, gpsd `USBAUTO=false`, chrony SHM 0 with `makestep 1 -1`, purges ModemManager/brltty, and installs the venv from a hash-locked aarch64 wheelhouse. systemd units use `Type=notify`, `Restart=always`, `StartLimitIntervalSec=0`, `WatchdogSec=30`, plus the hardware watchdog. Dev runs locally with three commands (README) | Works offline and recovers on its own after a power pull. |
| Directory layout | `src/jabuka/{common,ingest,core,sim,tools}/`, `src/jabuka/web/static/`, `deploy/` (repo root, not Python), `scripts/` (bootstrap, check, wheelhouse), `tests/` (root = plan 01; `tests/bus`, `tests/gps`, `tests/sim`, `tests/common`, `tests/deploy` = wave-2 plans; vendored fixtures in `tests/fixtures/`) | src layout from CONTEXT. `deploy/` sits at repo root because it holds shell/systemd/udev files (RESEARCH §Recommended Project Structure). |

## Stack Touched in Phase 1

- [x] Project scaffold: `pyproject.toml` (hatchling, ruff py313, pytest `asyncio_mode=auto`, `--import-mode=importlib`), `scripts/bootstrap-dev.sh`, `scripts/check.sh` (ruff plus the suite on 3.14 and 3.13). Plan 01-01 T1.
- [x] Routing: `GET /`, `GET /api/state` and `WS /ws` serve live decoded state. Plan 01-01 T1.
- [x] Data layer: one real read (`StateStore.snapshot()` drives `/api/state` and `/ws`) and one real write (raw-first Fastnet log in T1; derived, bus and events logs in T2).
- [x] UI: the "Event marker" button posts to `POST /api/event`, which appends a fsync'd line to `events-*.jsonl` and shows an acknowledgement. Plan 01-01 T2.
- [x] Deployment: a documented local full-stack run (README, three commands, proven by `tests/test_tracer_e2e.py::test_full_stack_subprocesses`), plus Pi provisioning scripts and systemd units (Plan 01-04). Flashing the Pi itself is an end-of-phase human-verify step.

## Out of Scope (Deferred to Later Slices)

- Polar, efficiency factor, conversion to TRUE (variation/heading offset applied to live data), own true-wind computation and damping. Phase 2. The conventions module and its golden tests exist from Phase 1 (Plan 01-03).
- Laylines, marks, course, offline map (MapLibre/PMTiles), helm view, night mode, lock mode. Phase 2.
- GRIB race pack, routing, tack advice, and the routing-health row on the diagnostics page. Phase 3 (CONTEXT deferred).
- Read-only root overlay FS. Phase 4 decision (CONTEXT deferred).
- 36 h soak, power-pull campaign on hardware, on-boat commissioning runbook. Phase 4 (REL-02, REL-03). Phase 1 only provides `deploy/PI-SETUP.md` and the laptop-side recovery tests.
- Closed-loop steering in the synthetic boat. Phase 2.
- App-level authentication, HTTPS, PWA. v2 (PLAT-02).

## Subsequent Slice Plan

Each later phase adds vertical slices on top of this skeleton and keeps its architectural decisions: processes, UDP schema, SI + Signal K paths with `ref`, injected Clock, log formats, FastAPI/WS, `deploy/` + systemd.

- Phase 2: the helmsman sees polar targets and live laylines to the active mark, over an offline map, on a night-readable helm view, using live or manual wind. It reads `StateStore`, `/ws`, `SimClock` and the L2 synthetic boat, extended to closed loop.
- Phase 3: the helm gets a continuously re-run isochrone route with tack advice. It consumes `routing_time_gate`, `GpsClock` and state snapshots, and adds the routing-health row to the diagnostics page.
- Phase 4: the system runs about 36 h unattended (soak with fault injection via `jabuka-sim`/`jabuka-replay` faults), and the owner commissions it on board with the runbook, using `fastnet-probe`, `jabuka-logcheck` and `deploy/PI-SETUP.md`.
