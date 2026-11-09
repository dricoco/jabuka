---
gsd_state_version: "1.0"
current_phase: 04
current_phase_name: Race Readiness — Hardening & Commissioning
status: executing
stopped_at: Completed 04-08-PLAN.md
last_updated: "2026-11-09T09:14:26.190Z"
last_activity: 2026-11-08
last_activity_desc: Phase 04 execution started
state_head: b9499c93cc98d5d2fb081062d32f03cde5fac807
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 23
  completed_plans: 23
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-11-05)

**Core value:** At the helm, during the race, the screen shows a trustworthy, continuously updated "steer this / tack here" (optimal course to the next mark + laylines) computed from live boat data — even if parts of the data chain fail.
**Current focus:** Phase 04 — Race Readiness — Hardening & Commissioning

## Current Position

Phase: 04 (Race Readiness — Hardening & Commissioning) — EXECUTING
Plan: 8 of 8
Status: All 8 plans executed — awaiting phase 04 re-verification (gap 07-5 closed by 04-08)
Last activity: 2026-11-08 — 04-08 executed (journal copy isolated, end_signal, F3/F4 interrupted/journal rules)

Progress: [░░░░░░░░░░] 0%

**Key dates:** Phase 3 Pi benchmark gate 2026-11-09 · feature freeze 2026-11-11 · race-ready on board 2026-11-12 · start 2026-11-13 20:00

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: -
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 04 P06 | 32 min | 3 tasks | 8 files |
| Phase 04 P07 | 35 min | 3 tasks | 10 files |
| Phase 04 P08 | 37 min | 3 tasks | 11 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Critical path is 1 → 2 → 4. Phase 3 (routing) runs in parallel from 2026-11-07 and never blocks Phase 4. The Phase 2 helm MVP (laylines, no routing) is the race fallback.
- [Roadmap]: Tack countdown starts in Phase 2 from the laylines (HELM-02/NAV-02). Phase 3 (ROUT-06) adds the route-driven version.
- [Research]: Pi OS Lite 64-bit Trixie, Python 3.13. No Signal K server. Own ingest process with pyfastnet (raw bytes first), fastnet2ip as diagnostic/Plan B. gpsd + chrony for GPS and clock.
- [Research]: FastAPI/uvicorn core + WebSocket. MapLibre 5.24 + PMTiles offline map. GRIBs prepped on the laptop into `.npz`. In-house numpy isochrone router, libweatherrouting as oracle/fallback.
- [Phase 04]: 04-06: freeze-check F4 counts only a --systemd system Pi report (mode systemd, code.source units) with code block = HEAD; F3 keeps the git rule
- [Phase 04]: 04-06: soak cleanup done only when both units ActiveState active after restart (else retryable, verdict FAIL, --systemd-cleanup exit 1); signal during cleanup honoured after report.json (128+signal)
- [Phase 04]: 04-07: freeze-check F3/F4 count only a full-length race-36h run at HEAD (scenario_sha256, seed, duration_s, sim_s>=0.99x, no late skip; fail closed); F3 always needs git.head
- [Phase 04]: 04-07: SIGINT/SIGTERM/SIGHUP held from end of main run until report.json written; run_soak then exits 128+signal
- [Phase 04]: 04-08: end-of-run journalctl/umount/vcgencmd in own session; incomplete journal copy FAILs tracebacks+verdict; report.json end_signal; F3/F4 refuse interrupted soak or incomplete journal (fail closed)

### Pending Todos

- [docs, minor] Fiche réglages débutant et calibration instruments (.planning/todos/pending/2026-11-06-fiche-reglages-debutant-et-calibration-instruments.md)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 261107-1ow | Heavy-weather polar reduction (18→25 kn, 5 %, Réglages) | 2026-11-07 | 995eb1c | [261107-1ow-heavy-weather-polar-reduction](./quick/261107-1ow-heavy-weather-polar-reduction/) |
| 2 | Night map: land/islands visible (toRed applied twice; coastline added) | 2026-11-07 | 5d02b52 | — |
| 3 | Map: boat hull icon on top + live heading ray | 2026-11-07 | 2ea6847 | — |
| 261107-i6x | Guide d'installation FR du Pi 3B (docs/INSTALL-PI.md) + lien README | 2026-11-07 | 24c87d0 | [261107-i6x-guide-d-installation-fr-raspberry-pi-3b-](./quick/261107-i6x-guide-d-installation-fr-raspberry-pi-3b-/) |
| 5 | STL support tablette X35 (v5) + boîte tablette dans stl/ | 2026-11-07 | b831ec3 | — |
| 6 | Sources FreeCAD support + boîte tablette dans cad/ | 2026-11-07 | d8a1c1d | — |
| 7 | Jeu queue d'aronde support X35 0.6 -> 0.8 mm/flanc | 2026-11-07 | cf2be60 | — |
| 8 | Support X35 : écrous M6 captifs au lieu d'inserts | 2026-11-07 | fdb0bb9 | — |
| 9 | Boîte tablette : écrous M3/M4 captifs au lieu d'inserts | 2026-11-07 | 53fe65f | — |
| 10 | Support X35 : centre tablette abaissé à 730 mm | 2026-11-07 | 4aff9d3 | — |
| 11 | Support X35 : renfort jonction tower/column | 2026-11-07 | d07497e | — |
| 12 | BOM PDF support tablette + boîte | 2026-11-08 | ec562fc | — |
| 13 | Berceau : écrou M6 sous le pivot, pied du pivot renforcé | 2026-11-09 | b9499c9 | — |

### Blockers/Concerns

- [Phase 1]: Hercules 2000/390 Fastnet channel set and DTECH wiring stay unverified until 2026-11-12. No feature may hard-depend on TWD or set/drift.
- [Phase 2]: Tablet model and WebGL support unknown. Check `chrome://gpu` early. Fallback is Leaflet + protomaps-leaflet.
- [Phase 3]: Router speed on the Pi 3B is unknown, and dual routing (cost of not tacking) doubles the load. Go/degrade decision at the 2026-11-09 benchmark.
- [Phase 3]: Organiser forecast format not published yet. Need a generic GRIB1/GRIB2 importer. Email the organiser.
- [Phase 3]: "Tacked" detection and forced-tack routing semantics still need defining (proposal: sustained TWA sign change >30 s).

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-11-08T20:21:13.556Z
Stopped at: Completed 04-08-PLAN.md
Resume file: None
