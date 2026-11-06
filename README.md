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

## Tester en local (démo en une commande)

```bash
bash scripts/demo.sh              # ou : .venv/bin/python -m jabuka.tools.demo
```

Puis ouvrir <http://127.0.0.1:8080/> dans le navigateur. La démo lance tout sur ce portable :
jabuka-core (horloge simulée), un X35 de synthèse qui remonte au près vers Plić Sestre en
suivant la route calculée (vent de 12 nds du 161°, qui tourne lentement), et l'ingest Fastnet.
On voit la route et les lay-lines sur la carte, le compte à rebours de virement, ON RESTE, et
Réglages > Langue FR / EN / SL. Ctrl-C arrête tout.

- `--speed 1` pour le temps réel (défaut ×2), `--port 8081` si 8080 est pris.
- `--lan` pour l'ouvrir depuis un téléphone ou une tablette sur le même Wi-Fi : les adresses
  sont affichées au démarrage.
- La carte réelle vient de `var/racepack/` si elle est là, sinon la carte de test de Šibenik.
  Les données de la démo vont dans `var/demo/`, effacé à chaque lancement.

## Run the whole pipeline locally (three terminals)

```bash
# 1. L0 replay: a recorded Fastnet capture written byte-for-byte into a pseudo-terminal
.venv/bin/jabuka-replay tests/fixtures/fastnet/example2_fastnet_data.txt --link var/fastnet-pty --loop

# 2. Receive-only ingest: raw log first, then framing, pyfastnet decode, UDP deltas to the core
.venv/bin/jabuka-ingest-fastnet --device var/fastnet-pty --data-dir var

# 3. Core: state store, logs, diagnostics page and WebSocket
.venv/bin/jabuka-core --data-dir var --http-port 8080
```

Then open <http://127.0.0.1:8080/> (the core binds 127.0.0.1 by default; pass
`--http-host 0.0.0.0` to reach it from another device). Every decoded value is listed with its unit, source, M/T
reference and server-computed age. The "Event marker" button writes a line to
`var/logs/events/events-*.jsonl`.

Logs land under `<data-dir>/logs/{raw,derived,events,gps}/` (and `bus/` with
`jabuka-core --bus-log on`). One retention policy prunes them (see deploy/PI-SETUP.md,
"Disk filling up").

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
