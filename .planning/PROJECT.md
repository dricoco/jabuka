# Jabuka — Live Race Routing & Laylines for an X35

## What This Is

An open-source, fully offline sailing race-navigation stack: a Raspberry Pi 3B on board reads the boat's B&G Hercules instruments (Fastnet bus via RS422/485) and a USB GPS, continuously recomputes the optimal route to the next mark using GRIB weather corrected by live measured wind, the boat's polars, and optionally current and waves — and serves a web app over Wi-Fi so the helmsman can read the target heading/course and live laylines on a tablet (Android browser) or laptop, on top of a map. Think "SailGrib/Expedition-style live routing", built by and for the owner, first used at Regata Jabuka 2026 on an X35.

## Core Value

At the helm, during the race, the screen shows a trustworthy, continuously updated "steer this / tack here" (optimal course to the next mark + laylines) computed from live boat data — even if parts of the data chain fail.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Pi reads B&G Hercules 2000/390 Fastnet bus (DTECH USB RS422/485 adapter) — via fastnet2ip or equivalent — giving AWA/AWS, TWA/TWS/TWD, boatspeed (STW), heading, depth, and Hercules set/drift if available
- [ ] Pi reads USB GPS (VK-162, u-blox NMEA) for position, COG, SOG
- [ ] Live data replay/simulator so everything can be developed and tested without the boat (bus is untested until race day)
- [ ] Degraded modes: GPS + GRIB only if Fastnet fails; manual entry of TWD/TWS (read off B&G displays) to correct the GRIB
- [ ] Load polar for X35 (generic polar, common formats: OpenCPN/Expedition/CSV) and compute target speeds/VMG/target TWA
- [ ] Import GRIB1/GRIB2 files offline (ICON-EU, ICON-D2, ALADIN/DHMZ Croatia, organizer-provided forecast) — loaded before departure
- [ ] Correct GRIB wind with live measured wind (bias at boat position, decaying with time horizon)
- [ ] Isochrone weather routing to the next mark(s), re-run automatically every few minutes from the current boat position
- [ ] Optional current: from a file (e.g. Copernicus Adriatic) for routing, and Hercules measured set/drift for short-term laylines
- [ ] Optional waves: speed reduction on polar in heavy seas — from wave-height file if available, else from TWS
- [ ] Live laylines to the next mark (both tacks/gybes), using polar target angles, current, and measured conditions
- [ ] Web app served by the Pi over the boat's Wi-Fi, usable in a tablet browser (Android) and laptop
- [ ] Offline map of the race area (Vodice / Šibenik archipelago to Jabuka) with boat, route, laylines, marks
- [ ] Marks entered by tapping on the tablet map (with which side to leave them), ordered into a course; editable during the race
- [ ] Helm view: big, night-readable numbers (course to steer / target heading, deviation, target TWA/BSP, distance/time to mark, layline indication) with map behind
- [ ] Helm view shows time (countdown) to the next recommended tack/gybe
- [ ] "Stay on this tack" override: a helm button freezes the current tack; routing recomputes from it (earliest next tack point, countdown updated)
- [ ] Show the cost of not tacking now (minutes lost vs optimal route)
- [ ] Auto-recompute if the advised tack time has passed and the boat hasn't tacked (after 2 minutes), instead of continuing to say "tack"
- [ ] Runs headless and robust on Pi 3B for ~36 h (auto-start on boot, survives restarts, no internet)

### Out of Scope

- Native Android APK — web app is faster to deliver in 8 days; possible later (WebView/PWA wrapper)
- In-race GRIB downloads — no internet on board; all weather loaded before the start
- Separate navigator/chart-table view with full routing settings — v1 targets the helm; may come later
- AIS, start-line/race-start tools, writing performance data back to B&G displays — not needed for Jabuka
- Vector charts (S-57/oeSENC) — too heavy for Pi 3B; raster/OSM-style tiles only
- Polar learning from logged data — later, after the race (but log data now)

## Context

- **Event:** 23rd Regata Jabuka, Vodice (Croatia). Start Fri 13 Nov 2026 20:00–24:00 (night start), time limit Sun 15 Nov 10:00. Course A: Vodice → Plić Sestre → Jabuka → Blitvenica → Vodice; Course B: … → Jabuka → Mulo → Vodice. Course may be changed by the committee. Offshore, OSR Cat 3, IRPCAS at night. November Adriatic: bora/jugo possible → significant seas.
- **Timeline:** today is 2026-11-05 → ~8 days to race. Boat (and its bus) only accessible on 12–13 Nov — no prior hardware-in-the-loop testing with the Hercules.
- **Boat:** X35 with B&G Hercules 2000/390 (Fastnet bus). Generic X35 polar available.
- **Hardware:** Raspberry Pi 3B (in hand, OS to install), DTECH USB RS422/RS485 adapter, VK-162 USB GPS, possibly an Android tablet over Wi-Fi.
- **Prior art considered:** OpenCPN + Weather Routing / Tactics (routing is on-demand only, ignores measured wind), Signal K + Freeboard-SK (laylines but no routing), GWeatherRouting / libweatherrouting (Python GPL routing lib with pluggable wind function — candidate engine), XyGrib (GRIB viewer only), fastnet2ip (Python 3.11+, Fastnet → NMEA0183/2000 over UDP, tested with DTECH dongle; serial 28800 8O2).
- **Organizer weather:** https://www.regata-jabuka.com/index.php/en/weather-forecast — format unknown yet (page empty at time of writing).
- **Polar caveat:** theoretical polars tend to give optimistic laylines; allow a user-tunable offset/efficiency factor.
- User communicates in French.

## Constraints

- **Timeline**: Must be race-ready by 2026-11-12 — hard deadline; scope must be ruthlessly prioritized behind the core value
- **Hardware**: Raspberry Pi 3B (1 GB RAM, ARMv8, slow) — routing and serving must fit; no heavy desktop GUI
- **Connectivity**: No internet during the race — everything (GRIB, map tiles, polar) pre-loaded
- **Testing**: Real Fastnet bus untested until 12–13 Nov — needs recorded/simulated data and a quick on-boat validation procedure
- **Reliability**: ~36 h unattended at sea, power cycles, night use — must auto-recover
- **Licensing**: Open source; reuse GPL components (fastnet2ip, libweatherrouting) is acceptable

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Web app served by Pi instead of native Android app | 8-day deadline; works on any tablet/laptop with no install | — Pending |
| Fully offline operation, GRIBs loaded pre-start | No internet on board | — Pending |
| Full GRIB routing in scope for Jabuka (not just laylines) | User priority | — Pending |
| Marks entered by tapping on the map | User preference; course may change | — Pending |
| Helm-first UI (big numbers + map) | Helmsman is the primary user | — Pending |
| Degraded modes: GPS+GRIB, manual wind entry | Fastnet bus untested before race day | — Pending |
| Route must never cross land (segment-level checks, narrow inter-island channels kept open, shore margin) | Race passes between islands of the Šibenik archipelago; user explicitly insisted | — Pending |
| Current & waves optional (file and/or measured) | Data availability uncertain | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-11-05 after initialization*
