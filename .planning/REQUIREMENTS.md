# Requirements: Jabuka — Live Race Routing & Laylines for an X35

**Defined:** 2026-11-06
**Core Value:** At the helm, during the race, the screen shows a trustworthy, continuously updated "steer this / tack here" (optimal course to the next mark + laylines) computed from live boat data — even if parts of the data chain fail.

## v1 Requirements

Race-ready for Regata Jabuka (start 2026-11-13). Each maps to one roadmap phase.

### Platform & Data Ingest

- [ ] **DATA-01**: Pi 3B runs Raspberry Pi OS Lite 64-bit with a Wi-Fi access point at a fixed IP that the tablet joins (no internet required)
- [ ] **DATA-02**: System reads the B&G Hercules Fastnet bus via the DTECH RS485 adapter strictly receive-only (nothing on the Pi can transmit to the bus), recording raw bytes to disk before decoding
- [ ] **DATA-03**: System decodes available Fastnet channels (AWA/AWS, TWA/TWS/TWD, BSP, heading, depth, set/drift if present) into one normalized state with units, source and age per value
- [ ] **DATA-04**: System reads the VK-162 USB GPS (position, COG, SOG, UTC time) and sets the system clock from GPS; routing is blocked until time is valid
- [ ] **DATA-05**: A `fastnet-probe` tool tells on the boat whether the bus is wired correctly (frames/checksums/channel IDs seen, "swap wires" hint) and captures a channel inventory
- [ ] **DATA-06**: Developer can replay recorded raw Fastnet/GPS captures and run a synthetic boat simulator (with faults) at accelerated speed, feeding the same pipeline as live data
- [ ] **DATA-07**: System logs raw data and 1 Hz derived state continuously for post-race analysis; user can drop an event marker from the UI

### Wind & Polar

- [ ] **WIND-01**: System loads the generic X35 polar (OpenCPN/Expedition/CSV) and gives target BSP, target TWA up/downwind and live % of polar
- [ ] **WIND-02**: User can set a polar efficiency factor (e.g. 92%) applied to targets, laylines and routing
- [ ] **WIND-03**: All directions are converted to TRUE at one boundary with a configurable magnetic variation (~+5°E) and heading offset; true wind is computed from AWA/AWS/BSP/HDG when available and damped
- [ ] **WIND-04**: User can enter TWD/TWS manually (read off B&G displays); a visible badge shows the active wind source (LIVE / MANUAL / GRIB-only)
- [ ] **WIND-05**: System works in GPS + GRIB-only mode when the Fastnet bus provides nothing
- [ ] **WIND-06**: System estimates GRIB bias (direction offset + speed ratio, measured during steady sailing) and applies it to the GRIB with time decay; bias is shown on screen ("+12° ×1.15") and can be disabled
- [ ] **WIND-07**: Within a configurable radius of Jabuka (magnetic island), heading is flagged untrusted (GPS COG used instead) and bias estimation is frozen

### Laylines & Navigation

- [ ] **NAV-01**: System displays live port/starboard laylines to the active mark (~1 Hz), from polar target angles (with efficiency) or, by toggle, from the actually sailed tacking angles
- [ ] **NAV-02**: Helm sees distance/time to the layline, an "overstood" indicator, and the heading on the other tack
- [ ] **NAV-03**: System can apply Hercules measured set/drift to laylines (off by default until compass/log verified on board)

### Course & Marks

- [ ] **CRSE-01**: Race marks (Vodice, Plić Sestre, Jabuka, Blitvenica, Mulo) and Course A / Course B are pre-loaded; user selects a course in one action
- [ ] **CRSE-02**: User can add, move and delete marks by tapping on the tablet map, set the rounding side (port/starboard) and radius, and reorder the course
- [ ] **CRSE-03**: System auto-advances to the next mark after rounding, with a banner and undo; user can also go next/previous manually
- [ ] **CRSE-04**: User can shorten the course / finish at the current or any checkpoint in one action
- [ ] **CRSE-05**: Course and settings persist on the Pi across reboots and power loss

### Weather Data

- [ ] **GRIB-01**: A laptop prep tool downloads ICON-EU (wind) and EWAM (waves) from DWD, crops them to the race area and converts them to a compact race pack; it also imports any GRIB1/GRIB2 file (e.g. organizer forecast)
- [ ] **GRIB-02**: The race pack is validated on load: every mark and the full race window (13 Nov evening → 15 Nov 10:00 local) must be covered, or the user is warned
- [ ] **GRIB-03**: The prep tool imports a Copernicus Mediterranean current file into the race pack

### Routing & Tack Advice

- [ ] **ROUT-01**: System computes an isochrone route from the boat to the remaining marks (multi-leg, honoring rounding sides) using corrected GRIB wind, polar × efficiency and a tack/gybe penalty, avoiding land and hazards (islands, Plić Sestre)
- [ ] **ROUT-02**: Routing reruns automatically every few minutes and on triggers (course change, bias change, off-route, manual wind change) without blocking the live display; last good route is kept with its age
- [ ] **ROUT-03**: Routing reduces boat speed by wave height (EWAM file, else estimated from TWS)
- [ ] **ROUT-04**: Routing uses the current file when present
- [ ] **ROUT-05**: Route changes are damped (hysteresis): a new route replaces the old only if it gains meaningfully, so advice does not flip
- [ ] **ROUT-06**: Helm sees a countdown to the next recommended tack/gybe (from the route; from laylines if no route)
- [ ] **ROUT-07**: Helm can press "Stay on this tack": routing recomputes with the current tack held, showing the earliest next tack and updated countdown
- [ ] **ROUT-08**: Helm sees the cost of not tacking now (minutes lost vs the optimal route)
- [ ] **ROUT-09**: If the advised tack time has passed by 2 minutes without a tack detected, the system recomputes automatically instead of continuing to say "tack"
- [ ] **ROUT-11**: The route never crosses land: every route segment (not just isochrone points) is checked against a land/hazard mask fine enough to keep the narrow channels between islands (Šibenik archipelago, Kornati side) navigable, with a configurable safety margin from shore and shoals; a test suite of known island-crossing cases (e.g. Vodice → open sea between Prvić/Zlarin/Tijat, around Blitvenica and Plić Sestre) proves no route intersects land
- [ ] **ROUT-10**: Route is drawn on the map and gives a target TWA + tack for the current leg, so steering advice stays correct through wind shifts between reruns

### Helm Display

- [ ] **HELM-01**: Tablet browser shows an offline map of the race area (Vodice → Jabuka) with boat, course, marks, laylines and route
- [ ] **HELM-02**: Helm view shows big, readable numbers: primary number by point of sail (target TWA upwind/downwind, course to steer when reaching), deviation, target BSP / % polar, distance/time to mark, tack countdown
- [ ] **HELM-03**: Night mode: true black with red, readable without spoiling night vision
- [ ] **HELM-04**: Screen lock mode prevents accidental touches from spray/rain; screen stays awake for the race
- [ ] **HELM-05**: Diagnostics page shows every value with source and age, plus bus/GPS/routing health

### Reliability

- [ ] **REL-01**: All services auto-start on boot and auto-restart on crash; the system survives power cuts without corrupting data
- [ ] **REL-02**: System runs ~36 h unattended on the Pi 3B (verified by an accelerated soak test with fault injection)
- [ ] **REL-03**: An on-boat commissioning runbook for 12–13 Nov exists (wiring, probe, capture, true/magnetic check, tablet setup, final GRIB download, spare SD card)

## v2 Requirements

Deferred — tracked but not in the Jabuka roadmap.

### Tactics

- **TACT-01**: Layline uncertainty wedge (width from wind variability)
- **TACT-02**: Lift/header bar vs mean wind
- **TACT-03**: GRIB vs measured disagreement alarm / model choice
- **TACT-04**: Distance-aware emphasis on helm display

### Analysis & Platform

- **ANLY-01**: Polar learning from logged race data
- **ANLY-02**: Multi-model / ensemble routing comparison
- **PLAT-01**: Navigator chart-table view with full routing settings
- **PLAT-02**: Native Android APK / PWA over HTTPS

## Out of Scope

| Feature | Reason |
|---------|--------|
| Signal K server | Needs Node ≥22 and RAM; no routing; one more layer to debug blind |
| Writing to the B&G bus / instrument displays | Bus must stay receive-only to never disturb the boat's instruments |
| In-race GRIB downloads | No internet on board |
| Vector nautical charts (S-57/oeSENC) | Too heavy for Pi 3B; OSM/PMTiles basemap + seamarks is enough |
| AIS, start-line tools | Not needed for an offshore night race |
| ALADIN/DHMZ GRIB | Paid product; ICON-EU used instead |
| Curved/time-varying current laylines | Complexity; Adriatic currents weak |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Pending |
| DATA-02 | Phase 1 | Pending |
| DATA-03 | Phase 1 | Pending |
| DATA-04 | Phase 1 | Pending |
| DATA-05 | Phase 1 | Pending |
| DATA-06 | Phase 1 | Pending |
| DATA-07 | Phase 1 | Pending |
| WIND-01 | Phase 2 | Pending |
| WIND-02 | Phase 2 | Pending |
| WIND-03 | Phase 2 | Pending |
| WIND-04 | Phase 2 | Pending |
| WIND-05 | Phase 3 | Pending |
| WIND-06 | Phase 3 | Pending |
| WIND-07 | Phase 2 | Pending |
| NAV-01 | Phase 2 | Pending |
| NAV-02 | Phase 2 | Pending |
| NAV-03 | Phase 2 | Pending |
| CRSE-01 | Phase 2 | Pending |
| CRSE-02 | Phase 2 | Pending |
| CRSE-03 | Phase 2 | Pending |
| CRSE-04 | Phase 2 | Pending |
| CRSE-05 | Phase 2 | Pending |
| GRIB-01 | Phase 3 | Pending |
| GRIB-02 | Phase 3 | Pending |
| GRIB-03 | Phase 3 | Pending |
| ROUT-01 | Phase 3 | Pending |
| ROUT-02 | Phase 3 | Pending |
| ROUT-03 | Phase 3 | Pending |
| ROUT-04 | Phase 3 | Pending |
| ROUT-05 | Phase 3 | Pending |
| ROUT-06 | Phase 3 | Pending |
| ROUT-07 | Phase 3 | Pending |
| ROUT-08 | Phase 3 | Pending |
| ROUT-09 | Phase 3 | Pending |
| ROUT-10 | Phase 3 | Pending |
| ROUT-11 | Phase 3 | Pending |
| HELM-01 | Phase 2 | Pending |
| HELM-02 | Phase 2 | Pending |
| HELM-03 | Phase 2 | Pending |
| HELM-04 | Phase 2 | Pending |
| HELM-05 | Phase 1 | Pending |
| REL-01 | Phase 1 | Pending |
| REL-02 | Phase 4 | Gaps Found |
| REL-03 | Phase 4 | Gaps Found |

**Coverage:**

- v1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0 ✓

---
*Requirements defined: 2026-11-06*
*Last updated: 2026-11-06 after roadmap creation (traceability mapped)*
