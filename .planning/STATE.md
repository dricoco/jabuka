---
gsd_state_version: "1.0"
current_phase: 2
current_phase_name: Helm MVP — Laylines, Marks & Map
status: executing
stopped_at: Roadmap and state initialized; ready to plan Phase 1
last_updated: "2026-11-06T03:11:32.094Z"
last_activity: 2026-11-06
last_activity_desc: Phase 2 execution started
state_head: 69c3f736a9aa3ecd604e4b162d27f2deeaff0d46
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 9
  completed_plans: 5
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-11-05)

**Core value:** At the helm, during the race, the screen shows a trustworthy, continuously updated "steer this / tack here" (optimal course to the next mark + laylines) computed from live boat data — even if parts of the data chain fail.
**Current focus:** Phase 2 — Helm MVP — Laylines, Marks & Map

## Current Position

Phase: 2 (Helm MVP — Laylines, Marks & Map) — EXECUTING
Plan: 2 of 5
Status: Ready to execute
Last activity: 2026-11-06 — Phase 2 execution started

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

None yet.

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
