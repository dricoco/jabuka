# Jabuka

Offline race navigation for an X35 (Regata Jabuka 2026). A Raspberry Pi 3B reads the boat's
B&G Fastnet bus **strictly receive-only** and a USB GPS, records everything raw-first, decodes it
into one normalized state (SI units, Signal K-style paths, M/T reference kept), and serves a
diagnostics page (later: helm view, laylines, routing) over Wi-Fi.

Phase 1 is the data backbone: ingest, core state store, logs, replay/simulation and the bus
test kit.

## Dev setup

Requirements: `uv` (0.6+), Python 3.14 for the main venv and `/usr/bin/python3.13` (the Pi runs 3.13).

```bash
bash scripts/bootstrap-dev.sh     # creates .venv (3.14) and .venv313 (3.13), installs -e ".[dev]"
```

## Run the whole pipeline locally (three terminals)

```bash
# 1. L0 replay: a recorded Fastnet capture written byte-for-byte into a pseudo-terminal
.venv/bin/jabuka-replay tests/fixtures/fastnet/example2_fastnet_data.txt --link var/fastnet-pty --loop

# 2. Receive-only ingest: raw log first, then framing, pyfastnet decode, UDP deltas to the core
.venv/bin/jabuka-ingest-fastnet --device var/fastnet-pty --data-dir var

# 3. Core: state store, logs, diagnostics page and WebSocket
.venv/bin/jabuka-core --data-dir var --http-port 8080
```

Then open <http://127.0.0.1:8080/>. Every decoded value is listed with its unit, source, M/T
reference and server-computed age. The "Event marker" button writes a line to
`var/logs/events/events-*.jsonl`.

Logs land under `<data-dir>/logs/{raw,bus,derived,events}/`.

## Checks

```bash
bash scripts/check.sh     # ruff lint + format check + full suite on Python 3.14 and 3.13
```

## Layout

- `src/jabuka/common/` clock (injected, the only place allowed to read the wall clock), UDP
  message schema, atomic IO, systemd notify
- `src/jabuka/ingest/` receive-only serial, Fastnet framing/decoding, raw logs, ingest entrypoint
- `src/jabuka/core/` state store, UDP bus listener, derived log, FastAPI web app, core entrypoint
- `src/jabuka/sim/` replay and simulation tools
- `src/jabuka/web/static/` diagnostics page (plain HTML + ES module, no build chain)
- `tests/fixtures/fastnet/` vendored MIT captures from pyfastnet and fastnet2ip (see `SOURCES.md`)
