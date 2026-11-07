---
gsd_state_version: "1.0"
current_phase: 4
current_phase_name: Race Readiness — Hardening & Commissioning
status: executing
stopped_at: 04-01 soak harness, quick-002 and quick-003 merged after the PC crash; next 04-03 Pi soak
last_updated: "2026-11-07T09:25:49.444Z"
last_activity: 2026-11-07
last_activity_desc: Resumed after crash; merged 04-01, quick-002, quick-003; master gate green (1464 passed x2)
state_head: 5d02b525023214387220b0064a9a7e1fd7ad3458
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 18
  completed_plans: 17
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-11-05)

**Core value:** At the helm, during the race, the screen shows a trustworthy, continuously updated "steer this / tack here" (optimal course to the next mark + laylines) computed from live boat data — even if parts of the data chain fail.
**Current focus:** Phase 2 — Helm MVP — Laylines, Marks & Map

## Current Position

Phase: 4 (Race Readiness — Hardening & Commissioning) — EXECUTING
Plan: 04-01 and 04-02 complete; 04-03 (Pi soak) next
Status: Phases 1–3 executed; quick 001–003 done; master gate green 2026-11-07
Last activity: 2026-11-07 — Completed quick task 261107-1ow: heavy-weather polar reduction; master gate 1512 passed ×2

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

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Critical path is 1 → 2 → 4. Phase 3 (routing) runs in parallel from 2026-11-07 and never blocks Phase 4. The Phase 2 helm MVP (laylines, no routing) is the race fallback.
- [Roadmap]: Tack countdown starts in Phase 2 from the laylines (HELM-02/NAV-02). Phase 3 (ROUT-06) adds the route-driven version.
- [Research]: Pi OS Lite 64-bit Trixie, Python 3.13. No Signal K server. Own ingest process with pyfastnet (raw bytes first), fastnet2ip as diagnostic/Plan B. gpsd + chrony for GPS and clock.
- [Research]: FastAPI/uvicorn core + WebSocket. MapLibre 5.24 + PMTiles offline map. GRIBs prepped on the laptop into `.npz`. In-house numpy isochrone router, libweatherrouting as oracle/fallback.

### Pending Todos

- [docs, minor] Fiche réglages débutant et calibration instruments (.planning/todos/pending/2026-11-06-fiche-reglages-debutant-et-calibration-instruments.md)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 261107-1ow | Heavy-weather polar reduction (18→25 kn, 5 %, Réglages) | 2026-11-07 | 995eb1c | [261107-1ow-heavy-weather-polar-reduction](./quick/261107-1ow-heavy-weather-polar-reduction/) |
| 2 | Night map: land/islands visible (toRed applied twice; coastline added) | 2026-11-07 | 5d02b52 | — |

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

Last session: 2026-11-06
Stopped at: Roadmap and state initialized; ready to plan Phase 1
Resume file: None
