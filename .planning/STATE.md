---
gsd_state_version: "1.0"
current_phase: 4
current_phase_name: race-readiness-hardening-commissioning
status: executing
stopped_at: Completed 04-15-PLAN.md
last_updated: "2026-11-09T16:51:12.971Z"
last_activity: 2026-11-09
last_activity_desc: 04-15 executed (CR-01 _carry_suppress, WR-01 = R10, IN-01 docstrings)
state_head: 0d73d554c99b3af77f2270c67897a6a9c06e1fff
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 30
  completed_plans: 30
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-11-05)

**Core value:** At the helm, during the race, the screen shows a trustworthy, continuously updated "steer this / tack here" (optimal course to the next mark + laylines) computed from live boat data — even if parts of the data chain fail.
**Current focus:** Phase 4 — race-readiness-hardening-commissioning

## Current Position

Phase: 4 (race-readiness-hardening-commissioning) — EXECUTING
Plan: 15 of 15
Status: Gap closure 8 complete — 04-15 done (CR-01 of review ccbbdc2: an edit that keeps the active leg keeps the Annuler suppression via _carry_suppress; WR-01 accepted as R10; IN-01 docstrings); full gate green; phase re-verification, freeze, wheelhouse rebuild/Pi re-provision and human UAT pending
Last activity: 2026-11-09 — 04-15 executed (CR-01: 16 stuck Annuler-then-edit cases now advance once; residuals R1-R10 recorded; gate green 1915 passed on 3.14 and 3.13; src/jabuka fingerprint 8b0a3bc4…19c8, 147 files)

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
| Phase 04 P09 | 30 min | 2 tasks | 4 files |
| Phase 04 P10 | 31 min | 3 tasks | 12 files |
| Phase 04 P11 | 46min | 3 tasks | 14 files |
| Phase 04 P12 | 33min | 3 tasks | 18 files |
| Phase 04 P13 | 31min | 3 tasks | 8 files |
| Phase 04 P14 | 31min | 3 tasks | 5 files |
| Phase 04 P15 | 27min | 2 tasks | 2 files |

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
- [Phase 04]: 04-09: a zone exit advances the course only past the mark (incoming leg; hairpin: _beyond latch since entering + past along the outgoing leg); CR-02 sets the latch, the 2 nm gate resets it
- [Phase 04]: 04-09: helm polar adopts the router VMG-linear rule on segments with both knots >= 120 deg; X35 run target 180 deg from 14 kn on helm and router; 9/11/13 kn tail residual deferred
- [Phase 04]: 04-10: in jabuka-core and jabuka-ingest-fastnet every fsync and atomic-write tail runs on one FIFO thread (jabuka-durable); atomic_write_json callers unchanged; tests/tools stay synchronous
- [Phase 04]: 04-10: background atomic write = synchronous .NAME.<n>.tmp write (disk-full/read-only errors still 503 on the caller), then fsync -> .bak -> rename -> dir fsync queued; an API 200 may precede the fsync during an SD stall (accepted; drain 20 s at exit)
- [Phase 04]: 04-10: routing worker raises its oom_score_adj to max(500, inherited) in _pool_init; Plan B units StartLimitIntervalSec=0
- [Phase 04]: 04-11: helm takeovers in primaryView priority order navFailed > PAS DE GPS > VENT PÉRIMÉ > VIREZ/EMPANNEZ cue > route > Phase 2; no core change for stale manual wind (UI-only)
- [Phase 04]: 04-11: noPosition keys on a boat block carrying lat/lon keys with null values (core shape); a frozen cue loses its red box on link loss
- [Phase 4]: 04-12: the padlock unlocks only on lifting the primary pointer after a 2-4 s press (inclusive); a press past 4 s is void, so a resting water drop never unlocks
- [Phase 4]: 04-12: night text tiers floored at rgb(110, 0, 0) (TEXT_FLOOR); --line and the map dim freely
- [Phase 4]: 04-12: primary label at --f-label (= --f-word) in var(--fg), single-id rule so 04-11 alert/cue colours win; landscape fallback not needed
- [Phase 4]: 04-12: Diag night variant before first paint via classic diag-theme.js; final src/jabuka fingerprint c1bab550…
- [Phase 4]: [04-13] CR-01: normal-mark zone exit = _beyond latch, or dot_in > 0, or dot_out > 0 after coming within radius + MARK_TOL_NM (0.1 nm); hairpin rule unchanged; residuals R2-R7 fall back to Carte → « Suiv. »
- [Phase 4]: [04-13] WR-01: rounding state machine keyed by _fsm_geometry (leg + previous/active/next positions); A<->B switch changing neighbours restarts it on purpose; relay RestartMode=direct (WR-06); new src/jabuka fingerprint c6fb70b0… (147 files), wheelhouse rebuild + Pi re-provision required
- [Phase 4]: 04-14 CR-01: rounding evidence keyed by _fsm_geometry (idx, mark, radius, previous pos, active pos); side/next-mark edits (_fsm_outgoing) restart only the 10 s debounce
- [Phase 4]: 04-14 WR-01: after Annuler in the zone of a normal mark, the zone exit stands in for _near (exit must be past the mark along either leg); _beyond only at hairpins / no outgoing leg
- [Phase 4]: 04-14 WR-02 accepted as false-advance residual R9 (banner + Annuler); IN-02 fixed; IN-01 advisory; new src/jabuka fingerprint f4a6fa25...9cc8 (147 files) -> wheelhouse rebuild + Pi re-provision
- [Phase 4]: 04-15 CR-01: _carry_suppress in _commit keeps the Annuler suppression through an edit that keeps the active leg (same index + mark, not the finish, no banner, not finished); Suiv./Préc., other leg, index shift (R6), select() to another mark, Finir ici on the active leg still clear it
- [Phase 4]: 04-15 WR-01 accepted as false-advance residual R10 (Annuler in a normal mark's zone, then an inside-of-the-turn exit advances); 04-14 D3 holds only for outside-of-the-turn retreats; new src/jabuka fingerprint 8b0a3bc4...19c8 (147 files) -> wheelhouse rebuild + Pi re-provision

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

Last session: 2026-11-09T16:51:12.905Z
Stopped at: Completed 04-15-PLAN.md
Resume file: None
