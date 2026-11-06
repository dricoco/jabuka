# Roadmap: Jabuka — Live Race Routing & Laylines for an X35

## Overview

Six working days (Fri 2026-11-06 → Wed 2026-11-11) and then the boat on Thu 12 Nov. The race starts Fri 13 Nov at 20:00. The plan builds a receive-only data backbone first, and with it the bus-test kit and the replay/simulator that every later feature is tested against, because the B&G bus can't be reached before 12 Nov. On top of that comes a helm MVP: polar targets, live laylines, marks and course, an offline map and a night helm view. This is the guaranteed "steer this / tack here" fallback. In parallel from day 2, a separate track builds the weather race pack and the isochrone router with tack advice. A Pi 3B benchmark on 9 Nov is its go/no-go gate. The last phase hardens whatever has landed by the feature freeze (36 h soak with fault injection) and delivers the on-boat commissioning runbook used on 12–13 Nov.

**Critical path:** Phase 1 → Phase 2 → Phase 4. Phase 3 runs alongside Phase 2 (Track B) and **must never block Phase 4**. If it is not ready by the 2026-11-11 feature freeze, the boat races on Phase 2 laylines.

## Timeline

| Date | Day | Milestone |
|------|-----|-----------|
| Fri 2026-11-06 | 1 | Phase 1 starts (Pi flashed, ingest, probe, replay) |
| Sat 2026-11-07 | 2 | Phase 1 target. Phase 2 starts. Phase 3 (Track B, laptop) starts |
| Mon 2026-11-09 | 4 | Phase 2 target. **Pi 3B router benchmark gate** (Phase 3 go/degrade/drop) |
| Tue 2026-11-10 | 5 | Phase 3 target. Phase 4 starts (soak, fault injection, runbook) |
| Wed 2026-11-11 | 6 | **Feature freeze.** Spare SD card cloned |
| Thu 2026-11-12 | 7 | **Race-ready.** On-boat commissioning (bus wiring, capture, checks). Config-only fixes |
| Fri 2026-11-13 | 8 | Final GRIB download + race-pack check. Start 20:00–24:00 |

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation, Data Backbone & Bus-Test Kit** - Headless Pi with receive-only Fastnet + GPS ingest, probe tool, replay/simulator, logging and diagnostics page (target 2026-11-07)
- [ ] **Phase 2: Helm MVP — Laylines, Marks & Map** - Night-readable tablet helm view on an offline map with polar targets, live laylines, course/marks and manual-wind fallback, with no routing needed (target 2026-11-09)
- [ ] **Phase 3: Weather Routing & Tack Advice** - GRIB race pack, live-corrected isochrone routing, tack countdown, stay-on-tack, cost of not tacking, Pi-benchmark gated (Track B, target 2026-11-10)
- [ ] **Phase 4: Race Readiness — Hardening & Commissioning** - 36 h fault-injected soak, feature freeze and on-boat commissioning runbook (freeze 2026-11-11, race-ready 2026-11-12)

## Phase Details

### Phase 1: Foundation, Data Backbone & Bus-Test Kit

**Goal**: The Pi boots headless into a receive-only data backbone that records and decodes Fastnet and GPS data. Every later feature can be built and tested against replayed or simulated data before the boat is reachable, and the bus can be diagnosed on the boat in minutes.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Target date**: Start 2026-11-06 → done 2026-11-07
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, HELM-05, REL-01
**Success Criteria** (what must be TRUE):

  1. A laptop or tablet joins the Pi's Wi-Fi access point at its fixed IP with no internet and opens a diagnostics page. The page lists every decoded value (AWA/AWS, TWA/TWS/TWD, BSP, heading, depth, set/drift when present, position, COG, SOG, UTC) with units, source and age, plus bus and GPS health.
  2. Run against a replayed capture or the real bus, `fastnet-probe` reports the frames, checksum results and channel IDs it sees. It gives a "swap wires" hint when bytes arrive but no valid frame decodes, and it saves a channel inventory file. No process on the Pi can transmit to the bus, and raw bytes are on disk before decoding.
  3. With the VK-162 plugged in and no internet, the system clock is set from GPS time. The diagnostics page shows the clock as unsynced until GPS time is valid, and the routing time gate reports "blocked" until then.
  4. A developer can replay a recorded raw Fastnet/GPS capture, or run the synthetic boat simulator with injected faults (bus silent, GPS loss, garbage bytes), at accelerated speed. The values flow through the same pipeline and appear on the diagnostics page exactly as live data would.
  5. Raw data and 1 Hz derived state are logged continuously, and an event marker dropped from the UI shows up in the log. After a killed process or a pulled power plug, all services come back on their own and logs and state files are not corrupted.

**Plans:** 4/4 plans executed (wave 1: 01; wave 2: 02 ‖ 03 ‖ 04)

Plans:

- [x] 01-01-PLAN.md — Walking skeleton: replayed Fastnet bytes → receive-only ingest (raw-first) → UDP → core state → diagnostics page; 1 Hz/raw/event logs + event marker; atomic IO, sd_notify
- [x] 01-02-PLAN.md — Bus-test kit: `fastnet-probe` (verdicts, inventory, capture), pty fault injection, self-healing ingest + 1 Hz bus heartbeat, static receive-only guard, L1 message replay
- [x] 01-03-PLAN.md — GPS & time: gpsd client + fake gpsd/NMEA, GpsClock + routing time gate, conventions golden tests, L2 synthetic boat with faults (UDP + real-ingest pty)
- [x] 01-04-PLAN.md — Pi appliance: provision.sh (AP 10.42.0.1, udev, gpsd/chrony), hardened systemd units + watchdog, hash-locked aarch64 wheelhouse, `jabuka-logcheck` + crash-recovery tests, PI-SETUP.md runbook

**UI hint**: yes
**Notes**: The UI here is a plain diagnostics page, so a full UI-design pass is optional. It gains a routing-health row once Phase 3 lands. Research flag: which channels the DTECH 2-wire wiring and the Hercules 2000/390 actually expose can only be known on the boat, so plan the capture procedure now. Conventions module (true/magnetic, u/v FROM/TOWARDS, kn vs m/s) and golden tests start here.

### Phase 2: Helm MVP — Laylines, Marks & Map

**Goal**: The helmsman can race to the next mark on laylines alone. A night-readable tablet helm view over an offline map shows polar targets, live laylines and the course, using live instrument wind or manually entered wind. This is the guaranteed fallback if routing never ships.
**Mode:** mvp
**Depends on**: Phase 1
**Target date**: Start 2026-11-07 → done 2026-11-09
**Requirements**: WIND-01, WIND-02, WIND-03, WIND-04, WIND-07, NAV-01, NAV-02, NAV-03, CRSE-01, CRSE-02, CRSE-03, CRSE-04, CRSE-05, HELM-01, HELM-02, HELM-03, HELM-04
**Success Criteria** (what must be TRUE):

  1. In the tablet browser, fully offline, the helm view shows the race-area map (Vodice → Jabuka) with the boat, marks and course behind big numbers. The primary number depends on point of sail: target TWA upwind and downwind, course to steer on a reach. Also shown: deviation, target BSP and % polar (X35 polar × user efficiency factor), distance/time to mark, and a time-to-tack countdown taken from the laylines.
  2. Live port and starboard laylines to the active mark update about once per second, with distance/time to the layline, an "overstood" indicator and the heading on the other tack. The user can switch layline angles between polar targets and actually sailed tacking angles, and can enable Hercules set/drift (off by default).
  3. The user can select Course A or Course B in one action. Marks can be added, moved and deleted by tapping the map, each with a rounding side and radius, and the course can be reordered. The active mark auto-advances after rounding (banner + undo), can be stepped next/previous by hand, and the course can be shortened or finished at any checkpoint in one action. Course and settings survive a Pi reboot or power cut.
  4. Every direction is handled as TRUE, with a configurable variation (~+5°E) and heading offset. True wind is computed and damped from AWA/AWS/BSP/HDG when available. When the bus provides nothing, the user types in TWD/TWS read off the B&G displays and the laylines keep working, with a badge showing the active source (LIVE / MANUAL). Within the configured Jabuka radius, heading is flagged untrusted and GPS COG is used instead.
  5. At night the helm view runs in true-black/red mode without spoiling night vision, a lock mode ignores spray and rain touches, and the tablet screen stays awake for the whole race.

**Plans:** 5 plans (wave 1: 01; wave 2: 02 ‖ 03 ‖ 04 ‖ 05)

Plans:

- [ ] 02-01-PLAN.md — Helm tracer + every shared seam: live wind → polar targets → laylines → nav WS message → Barre numbers; course A/B + settings REST with atomic persistence; PMTiles tile server + race-pack router; vendored MapLibre 5.24.0/glyphs/sprites + day/night styles + map.js; app shell (diag moved to /diag.html); Pi lock + pyproject declarations; Playwright harness
- [ ] 02-02-PLAN.md — Laptop race-pack prep: `jabuka-prep-map` (Protomaps extract, seamarks + coastline from Geofabrik, fallback chain, manifest, `--check`), `jabuka-prep-polar` (grid/Expedition/ORC CSV/JSON → polar.json), docs/RACE-PACK.md
- [ ] 02-03-PLAN.md — Wind & laylines complete: manual TWD/TWS (°M/°T) + LIVE > MANUEL > NONE, TRUE boundary + vector damping + Hercules cross-check, Jabuka zone → COG, sailed tacking angles, set/drift opt-in, actual-track countdown, efficiency up/down, Réglages manual-wind form
- [ ] 02-04-PLAN.md — Course & marks complete: tap/drag/sheet editing with land warning, reorder/delete/side/radius, "Finir ici", 409 concurrency, kill-safe persistence, auto-advance FSM + banner/Annuler, closed-loop `jabuka-sim --follow`
- [ ] 02-05-PLAN.md — Helm view complete: red-on-black night mode end to end, full map overlays (course, marks + radii, laylines, boat, seamarks), course-up/north-up, big numbers ≥ 20% vh with PERTE DONNÉES, lock mode, Wake Lock/NoSleep, docs/TABLET-SETUP.md
**UI hint**: yes
**Notes**: Includes the PMTiles basemap + seamark extract (prep step) needed for the offline map, and the L2 closed-loop simulator extension so the boat can be steered to its targets. The Jabuka untrusted-heading flag from WIND-07 is also used by the Phase 3 bias estimator, which freezes inside the zone. Tablet WebGL support must be checked early (fallback: Leaflet + protomaps-leaflet).

### Phase 3: Weather Routing & Tack Advice

**Goal**: The helm gets an optimal route to the remaining marks that keeps updating, built from GRIB wind corrected by live measurements, with clear and stable tack advice: a countdown, "stay on this tack", and the cost of not tacking. It is built in parallel and gated by a Pi 3B benchmark, so it can never put the Phase 2 layline fallback at risk.
**Mode:** mvp
**Depends on**: Phase 1 (router and prep tool start on the laptop on 2026-11-07, in parallel with Phase 2); Phase 2 for helm view and map integration
**Target date**: Start 2026-11-07 → Pi benchmark gate 2026-11-09 → done 2026-11-10
**Requirements**: GRIB-01, GRIB-02, GRIB-03, WIND-05, WIND-06, ROUT-01, ROUT-02, ROUT-03, ROUT-04, ROUT-05, ROUT-06, ROUT-07, ROUT-08, ROUT-09, ROUT-10, ROUT-11
**Success Criteria** (what must be TRUE):

  1. On the laptop, the prep tool downloads ICON-EU wind and EWAM waves, imports a Copernicus current file and any GRIB1/GRIB2 (such as the organiser's forecast), and writes a cropped race pack. On the Pi, loading the pack warns if any mark or any hour from 13 Nov evening to 15 Nov 10:00 local is missing. With the Fastnet bus silent, the system runs in GPS + GRIB-only mode and the wind-source badge shows GRIB-only.
  2. The map shows an isochrone route from the boat through the remaining marks. It honours rounding sides and never crosses land, islands or the Plić Sestre hazard: every segment is checked against the land mask, the narrow channels between the Šibenik islands stay usable with a configurable shore margin, and an island-crossing test suite passes. It slows the boat for wave height (EWAM, else from TWS) and uses current when the file is present. The helm view gives a target TWA and tack for the current leg that stays correct through wind shifts between reruns.
  3. The route reruns on its own every few minutes and on triggers (course change, bias change, manual wind change, off-route) without freezing the live display. The last good route is shown with its age, and a new route replaces it only when it gains meaningfully, so the advice does not flip. The GRIB bias is shown on screen ("+12° ×1.15"), fades with time, can be switched off and stays frozen inside the Jabuka zone.
  4. The helm sees a countdown to the next recommended tack or gybe from the route (from the laylines when there is no route) and the cost in minutes of not tacking now. Pressing "Stay on this tack" shows the earliest next tack and an updated countdown. If the advised tack time passes by 2 minutes with no tack detected, the display stops saying "tack" and the route recomputes.
  5. On the Pi 3B (benchmarked by 2026-11-09), the optimal route and the forced-current-tack route both finish within the rerun cadence, using either full settings or the documented degraded settings. Laylines and the helm view keep updating at about 1 Hz while routing runs.

**Plans**: TBD
**UI hint**: yes
**Notes**: Plan GRIB pack + GPS+GRIB mode + bias first, because they don't depend on the router passing its benchmark. If the 2026-11-09 benchmark fails, degrade in this order: 10° headings and 30-min steps, then next mark +1 only, then a 10-min cadence. After that, compute the cost of not tacking only on demand and let the countdown fall back to laylines. libweatherrouting is the test oracle and the emergency engine. Research flags: forced-tack semantics and "tacked" detection (sustained TWA sign change >30 s), bias decay constants, organiser GRIB format.

### Phase 4: Race Readiness — Hardening & Commissioning

**Goal**: The system runs about 36 h unattended at night on the Pi 3B, and on 12–13 Nov the owner can commission it on the real boat in one session by following a written runbook.
**Mode:** mvp
**Depends on**: Phase 2 (Phase 3 is hardened only if it lands by the 2026-11-11 feature freeze; it never blocks this phase)
**Target date**: Start 2026-11-10 → feature freeze 2026-11-11 → race-ready on board 2026-11-12
**Requirements**: REL-02, REL-03
**Success Criteria** (what must be TRUE):

  1. An accelerated 36 h soak (~60×) on the Pi 3B completes with injected faults: Fastnet silent, GPS loss, garbage bytes, clock jump, USB unplug, repeated power pulls. Services recover on their own every time, memory stays within budget, and the tablet shows live data again after each fault.
  2. A written commissioning runbook for 12–13 Nov exists and has been dry-run against a replayed capture. It covers tap-harness wiring and the swap-wires steps, `fastnet-probe`, a channel-inventory capture with every B&G display page cycled, the true/magnetic and COG-vs-HDG checks, tablet Wi-Fi/stay-awake/night-brightness setup, the final GRIB download and race-pack check, the spare SD card, and a course-change drill under 30 s.
  3. Features are frozen on 2026-11-11 and a cloned spare SD card boots to the same working state. On 12 Nov the boat's real capture replays cleanly through the pipeline, and only configuration changes are made.
  4. On the boat by 2026-11-12, the tablet at the helm shows live wind (or manual or GRIB-only wind) and laylines to the first mark over the boat Wi-Fi, readable at night.

**Plans**: TBD
**Notes**: The read-only overlay FS is optional: test it once by 2026-11-09, otherwise skip it and rely on atomic writes + the spare SD card. Re-verifies REL-01 (Phase 1) and CRSE-05 (Phase 2) under power-pull faults.

## Progress

**Execution Order:**
Critical path 1 → 2 → 4. Phase 3 runs in parallel with Phase 2 from 2026-11-07 (Track B) and does not block Phase 4.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation, Data Backbone & Bus-Test Kit | 4/4 | In Progress|  |
| 2. Helm MVP — Laylines, Marks & Map | 0/5 | Planned | - |
| 3. Weather Routing & Tack Advice | 0/TBD | Not started | - |
| 4. Race Readiness — Hardening & Commissioning | 0/TBD | Not started | - |

---
*Roadmap created: 2026-11-06*
