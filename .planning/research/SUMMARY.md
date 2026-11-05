# Project Research Summary

**Project:** Jabuka — Live Race Routing & Laylines for an X35
**Domain:** Offline embedded sailing race navigation (B&G Fastnet ingest, live isochrone GRIB routing, laylines, night helm display) on a Raspberry Pi 3B, served to a tablet browser
**Researched:** 2026-11-05 (synthesized 2026-11-06)
**Confidence:** MEDIUM (stack HIGH, Pi performance and boat-specific bus behaviour unverified)

## Executive Summary

Jabuka is a small version of what Expedition, qtVlm and SailGrib do for racing navigators. It takes damped instrument wind and polar targets and turns them into laylines about once a second. It runs an isochrone router over GRIB wind every few minutes. It shows the helm one number to steer to, mostly a target TWA rather than a heading. Expert systems share three habits. They keep ingest, nav maths and routing as separate concerns. They are open about data quality (staleness, source, polar efficiency). They let the navigator override wind and current when instruments misbehave. Commercial tools leave the GRIB-vs-measured correction manual (scale/rotate plus a linear fade). Doing that automatically, with a visible clamp and a veto, is this project's real differentiator.

Recommended approach: a 64-bit Python 3.13 stack on Raspberry Pi OS Lite (Trixie), with no Signal K server and no JS build chain. A small ingest process owns the RS-485 port, records raw bytes first and decodes with pyfastnet. The VK-162 GPS goes through gpsd and chrony, because the Pi has no RTC and GRIB time lookups depend on the clock. One asyncio core (FastAPI/uvicorn) handles state, laylines, course, router supervision and WebSocket push. A niced worker process runs an in-house numpy-vectorised isochrone router modelled on libweatherrouting, with libweatherrouting kept as a test oracle and emergency fallback. GRIBs are cropped on the laptop into `.npz` cubes. The tablet renders a MapLibre 5 map from a Protomaps PMTiles extract. The server computes everything and the browser only renders.

Main risks, in order:
1. **The Fastnet bus cannot be tested until 12 Nov.** Mitigate with a bus-test kit built first (probe tool, raw capture, channel inventory), replay/simulation for all development, and degraded modes: GPS+GRIB and manual TWD/TWS.
2. **Routing could be too slow or unstable on a Pi 3B.** Mitigate with a Pi benchmark gate by about 9 Nov, hysteresis, and shipping laylines plus the helm view before routing so the core value survives if routing slips.
3. **Silent correctness bugs.** These include magnetic vs true, u/v FROM/TOWARDS, kn vs m/s, a wrong clock giving the wrong GRIB hour, and routes through islands. Mitigate with one conventions module plus golden tests, an injected GPS-disciplined clock, and a raster land mask with rounding waypoints.

The deadline is 2026-11-12 and today is 2026-11-06, so there are about 6 working days. Anything not on the critical path must be cut without hesitation.

## Resolved Conflicts Between Research Files

| Topic | Disagreement | Resolution | Why |
|---|---|---|---|
| OS | STACK: Trixie 64-bit (Bookworm as "Legacy" fallback). ARCH/PITFALLS: "64-bit Lite", no release named | **Raspberry Pi OS Lite 64-bit Trixie**, flashed clean. Bookworm 64-bit only if a package regresses | 64-bit is mandatory (no armv7 wheels for numpy/pygrib/eccodeslib/shapely). Trixie gives Python 3.13 and numpy 2.5, and NetworkManager is the AP tool on both. No research file argued *for* Bookworm. |
| Signal K | No real disagreement: all three reject the server | **No Signal K server.** Use Signal K path names and SI units internally (pyfastnet already emits them) | signalk-server needs Node ≥22 (Trixie ships 20.19), costs RAM on 1 GB, does no routing, and is one more layer to debug blind. |
| Fastnet ingest seam | STACK: fastnet2ip as a service, NMEA0183 over UDP. ARCH/PITFALLS: own ingest process using **pyfastnet directly** | **Own `ingest@fastnet` process with pyfastnet**, raw-bytes-first, publishing JSON deltas on localhost UDP. Keep **fastnet2ip as the diagnostic and Plan B** (stop the ingest, start fastnet2ip, and OpenCPN on a laptop reads UDP :2002) | NMEA re-encoding loses M/T reference flags, precision and channels (Target BSP, raw IDs). Raw capture is needed to fix the decoder on the night of 12 Nov. Only one process can own the serial port, so the two run as alternatives, not together. |
| GPS access | STACK: gpsd + chrony. PITFALLS: "pick one, prefer direct pyserial". ARCH: direct serial + in-app clock | **gpsd (explicit `DEVICES=/dev/gps`, `USBAUTO=false`) + chrony SHM refclock.** The app is a gpsd JSON client. Domain logic still uses an **injected clock** from GPS time and blocks routing while unsynced | chrony fixes system/log time after power cuts, and gpsd handles replug and `gpsfake` replay. The PITFALLS concern (gpsd grabbing the FTDI) is handled by udev by-id names, no autoprobe, and purging ModemManager. |
| Web framework | STACK: FastAPI. ARCH: aiohttp | **FastAPI + uvicorn, single worker** (aiohttp if RAM is tight) | Pydantic models for course/settings save time. Both fit. |
| Map | STACK: MapLibre 5.24 + PMTiles vector. FEATURES/PITFALLS assume raster tiles + CSS filter | **MapLibre GL JS 5.24 (UMD, pinned) + Protomaps PMTiles extract + osmium seamark GeoJSON**. Leaflet + protomaps-leaflet only if the tablet has no WebGL | OSMF policy forbids bulk raster prefetch. Vector styles give a real red-on-black night theme and course-up rotation. v6 needs WebGL2 and the tablet is unknown. |
| GRIB decode location | STACK: pygrib on Pi is fine. PITFALLS/ARCH: laptop only | **Prep on laptop → `.npz`. pygrib also installed on the Pi as a backup** (aarch64 wheel bundles eccodes). The runtime router only `np.load`s | Keeps routing memory small. Still allows re-prepping at the dock without a laptop. |
| Masthead height correction | FEATURES: scale 10 m→masthead before bias. ARCH/PITFALLS: speed *ratio* absorbs it | **No separate height correction.** The bias speed ratio absorbs it | Avoids double-correction. |
| Bias decay shape | FEATURES: linear fade over 3–6 h. ARCH: exp τ≈2 h. PITFALLS: half-life 2–3 h + 10–15 nm distance | **Time-only decay, configurable (default τ≈2–3 h)**. Clamp ±30–40°, ratio 0.6–1.5. Spatial decay deferred | The race area is small. The constant is a tuning parameter (LOW confidence) either way. |
| Read-only root overlay | STACK: enable last step on 12 Nov. ARCH: optional after freeze | **Optional.** Test it once by 9 Nov. If it isn't clean, skip it and rely on atomic writes + a spare cloned SD card | A late, untested FS change is a bigger risk than SD corruption with a spare card on board. |
| Current in laylines | FEATURES: default Ignore. STACK: use Hercules VDR | **Default Ignore**, enable after the on-boat compass/log check | Instrument-derived current needs calibrated heading and log, and Adriatic currents are weak. |

## Key Findings

### Recommended Stack

Python 3.13 venv on Pi OS Lite 64-bit Trixie, with dependencies locked on the laptop via `uv` and a wheelhouse for offline reinstall. Heavy GRIB tooling (cfgrib/xarray/eccodes, copernicusmarine) stays on the laptop. The frontend is vanilla ES modules with vendored MapLibre, glyphs and sprites (labels won't render offline without the glyphs). Details are in STACK.md.

**Core technologies:**
- **Raspberry Pi OS Lite 64-bit (Trixie):** base OS. aarch64 wheels exist; armv7 is a dead end.
- **pyfastnet 3.2.1 (in own ingest) / fastnet2ip 3.3.1 (diagnostic, Plan B):** the only maintained Fastnet decoder (28800 8O2), tested with the DTECH dongle on H2000. The Hercules 390 is unverified.
- **gpsd 3.25 + chrony:** GPS position and the system clock with no RTC or internet.
- **FastAPI 0.162 + uvicorn 0.54:** WS push, REST, static files and tiles in about 60–80 MB.
- **numpy 2.5:** vectorised isochrone router, trilinear GRIB interpolation, polar tables. Expected 2–6 s per route (must benchmark).
- **pygrib 2.1.8:** GRIB1/2 → cropped `.npz` cube (u/v float32, UTC epochs).
- **MapLibre GL JS 5.24.0 + Protomaps PMTiles (go-pmtiles 1.31.2, `pmtiles` py 3.8.1):** legal offline vector basemap of a few MB, with day and night styles.
- **shapely 2.2 (prep only):** rasterise OSM land polygons + hand hazards into `landmask.npy`.
- **libweatherrouting 0.2.3:** test oracle and emergency fallback engine. It has no current and is too slow as the primary engine.

**Weather sources:** **ICON-EU is primary** (covers the whole course, +120 h). **ICON-D2 does not reach Jabuka** (south edge 43.18 N), so use it for the northern part only, if at all. EWAM for waves. Copernicus Med currents are optional. ALADIN-HR GRIB is paid. The organiser's forecast format is unknown.

### Expected Features

**Must have (table stakes, v1 race-ready):**
- Ingest + per-value freshness/source badges (LIVE/MANUAL/GRIB/STALE) + damping (TS-1..3)
- Replay/simulator sharing the log format (TS-4)
- Polar load, target TWA/BSP, polar %, efficiency factor + angle offset (TS-5..8), tack penalty (TS-9)
- Laylines to the active mark with a polar-vs-actual source toggle, time/distance to layline, overstood indicator, manual wind override (TS-10..12, TS-14)
- Manual TWD/TWS entry, GPS-only mode, persistence across restarts (TS-20..22)
- Mark library pre-loaded (Vodice, Plić Sestre, Jabuka, Blitvenica, Mulo), course A/B templates, rounding side + radius, manual next/prev, auto-advance with banner + undo, fast "finish here / shorten course" (TS-23..27)
- Helm view: big numbers, true-black/red night mode, stay-awake, lock mode against wet-screen touches (TS-28..31)
- Raw + 1 Hz logging, event button (TS-32..33)
- Isochrone routing with land avoidance, decaying GRIB bias, route advice from the first leg (TS-15..17, TS-19)
- **User-added helm requirements (all v1):**
  - **Tack/gybe countdown** to the next recommended manoeuvre. It comes from the route's first tack time. Laylines-only fallback: time to layline (TS-12).
  - **"Stay on this tack" button:** freezes the current tack and reroutes with the first leg forced on it. Shows the earliest next tack and an updated countdown.
  - **Cost of not tacking now:** ETA(forced current tack) − ETA(optimal), in minutes. This is research item D-3, promoted from P2 to v1.
  - **Auto-recompute** when the advised tack time passes by 2 min with no tack detected. This is a supervisor trigger. The display then stops saying "TACK" and shows "route updating".

**Should have (differentiators):**
- D-1 automatic GRIB bias, shown as "+12° ×1.15, fading", with a toggle. Headline feature.
- D-4 route hysteresis (re-evaluate the old route under new wind; switch only if it gains more than about 3–5 min). Required for the countdown not to flicker.
- D-6 mode-aware primary number (target TWA upwind/downwind, heading on a reach). D-7 other-tack heading. D-11 health/diagnostics page.
- v1.x if time allows: D-5 layline uncertainty wedge, D-8 lift/header bar, D-9 distance-aware emphasis, TS-13 measured current, wave table, D-2 GRIB disagreement alarm.

**Defer (v2+):** polar learning, multi-model/ensemble, navigator chart-table UI, PWA/APK/HTTPS, curved current laylines, start-line tools, AIS, writing back to the B&G displays (never: the bus stays read-only).

### Architecture Approach

Data flows one way: hardware → per-device ingest processes (raw log first, normalise to SI/Signal K paths, UDP JSON on 127.0.0.1) → one asyncio core (state store with staleness, injected clock, wind pipeline including M/T conversion and own true-wind cross-check, gated bias estimator, 1 Hz laylines and route following, course persistence, router supervisor) → WebSocket → stateless browser. Routing is a **pure function** `route(RouteRequest) -> RouteResult` in a `ProcessPoolExecutor(1)` at nice 10. It has a 60 s timeout and is recreated on crash, and the last good route is kept with its age. Route results carry **target TWA + tack per segment**, so the helm keeps steering the right angle through shifts between reroutes. The same structure carries the tack-advice features. The supervisor runs two snapshots per cycle (optimal, plus first leg forced on the current tack), giving the countdown, the cost of not tacking and the stay-on-tack mode with no new component.

**Major components:**
1. **ingest@fastnet / ingest@gps (or gpsd):** device ownership, raw recording, decoding, normalisation. Receive-only.
2. **core:** state + clock + wind pipeline + bias + laylines/nav + course + router supervisor (triggers: timer, course edit, bias move, off-route, manual wind, **missed tack +2 min**, **stay-on-tack toggled**) + web/WS + 1 Hz derived log.
3. **router worker:** numpy isochrones in a local planar nm frame. u/v interpolation, polar × efficiency × wave factor, current vector, tack penalty, raster land mask with segment sampling, rounding waypoints per side, multi-leg.
4. **jabuka-prep (laptop):** race pack = `wind.npz`, `landmask.npy`, `polar.json`, `race.pmtiles`, seamarks GeoJSON, plus a coverage validation report.
5. **replay/sim:** L0 pty bytes, L1 UDP messages, L2 synthetic boat (closed loop on core's target, fault injection, 36 h soak at 60×), all on `SimClock`.

### Critical Pitfalls

1. **Fastnet wiring/termination/ground wrong on race day; or something transmits on the bus.** Bring a labelled tap harness (White→T/R+, Green→T/R−, Black→GND), add no termination, and use a `fastnet-probe` that reports frames, checksums and channel IDs ("0 valid + bytes = swap wires"). Make the code path receive-only, purge ModemManager, and keep gpsd off the FTDI.
2. **Expected channels absent or magnetic/true mixed.** Design for a minimum of AWA/AWS/BSP + GPS and compute true wind ourselves when HDG exists. Hercules TWD and set/drift are a bonus. Convert everything to TRUE at one boundary, with a visible variation setting (about +5° E) and a heading offset. Do the motoring COG-vs-HDG check on 12 Nov. Cycle the display pages during capture. **Jabuka is a magnetic island**: freeze the bias and flag heading as untrusted within about 3 nm.
3. **Convention/unit/clock bugs that are silent.** GRIB FROM = `atan2(-u,-v)`. Current is TOWARDS. Interpolate u/v. libweatherrouting uses m/s while polars use knots. Keep one conventions module with golden tests from day 1. Use the injected GPS clock, block routing while unsynced, and sanity-check the GPS date.
4. **Routes through islands, marks on land, route flip-flop.** Use a raster land mask (OSM + hand hazards for Plić Sestre and Blitvenica reefs) dilated by about 150 m, segment checks, rounding waypoints on a per-mark radius, and snapping of tapped land marks. Hysteresis + gated bias (τ≈10 min, no manoeuvre samples) keep the countdown and "tack now" advice from flickering. Untrustworthy advice is worse than none.
5. **Optimistic generic X35 polar.** Use an efficiency factor (default 0.90–0.95, up/down split if time allows), observed-tacking-angle laylines as an option, % polar on screen, and a 30–60 s tack penalty. This directly affects the accuracy of "cost of not tacking".

Also critical but routine: undervoltage/SD corruption (quality 5 V 3 A buck converter, atomic writes, spare SD card), Android dropping a no-internet AP (forget other networks, mobile data off, fixed IP), Wake Lock unavailable over HTTP (Chrome insecure-origin flag + OS stay-awake + NoSleep fallback).

## Implications for Roadmap

Coarse granularity, 6 working days, two parallel tracks. The critical path is Phase 1 → 2 → 4. Phase 3 runs alongside from day 2 and **must never block Phase 4**.

### Phase 1: Foundation, Data Backbone and Bus-Test Kit (days 1–2)
**Rationale:** Nothing can be tested on the boat before 12 Nov, so the replay path and the bus diagnostics have to exist first. The OS architecture choice is irreversible.
**Delivers:** flashed Pi (Trixie 64-bit Lite, NM AP at fixed IP, udev by-id names, ModemManager purged, gpsd/chrony); `common/` (units, angles, conventions + golden tests, clock, atomic IO); ingest@fastnet (raw-first, pyfastnet, error counters) + GPS path; `fastnet-probe`; L0/L1 replay using pyfastnet repo captures; core state store with staleness; FastAPI WS + debug page listing every path/value/source/age; systemd units with restart/watchdog; raw + 1 Hz logging.
**Addresses:** TS-1, TS-2, TS-4, TS-32, D-11 (initial).
**Avoids:** Pitfalls 1, 2, 3, 8, 10, 14 (conventions, clock, OS arch, bus safety).

### Phase 2: Helm MVP Without Routing (days 2–4)
**Rationale:** Laylines do not depend on routing and deliver most of the core value. This phase is the fallback if routing slips.
**Delivers:** polar parser/targets/efficiency; wind pipeline (M/T, variation, own TW cross-check, damping, upwash offset, Jabuka heading-trust zone); 1 Hz laylines (polar/actual toggle, time/distance to layline, overstood, other-tack heading); course/marks (library, A/B templates, rounding side + radius, tap entry, next/prev, auto-advance + undo, shorten course), persisted on the Pi; manual wind + source arbitration (LIVE/MANUAL/GPS+GRIB badge); MapLibre map + helm view (day/night, lock mode, mode-aware primary number, layline-based tack countdown as a fallback); L2 synthetic sim.
**Uses:** MapLibre 5.24 + PMTiles, FastAPI WS, numpy polar.
**Addresses:** TS-3, TS-5..8, TS-10..12, TS-14, TS-20..31, TS-33, D-6, D-7.
**Avoids:** Pitfalls 4, 5, 6, 7, 11 (mark side), 17, 18.

### Phase 3: Weather Routing and Tack Advice (Track B: days 2–5, Pi benchmark gate day 4)
**Rationale:** Highest value and highest risk. The router is pure and can be developed on the laptop in parallel, then integrated once the core exists.
**Delivers:** jabuka-prep (GRIB → npz with a coverage assertion for every mark and 13 Nov 19Z → 15 Nov 09Z; land mask + hazards; tiles; polar); numpy isochrone router (multi-leg, rounding waypoints, land segments, tack penalty, horizon hold), golden tests + libweatherrouting oracle; **Pi 3B benchmark gate**; supervisor + triggers; gated GRIB bias with time decay (D-1); route display + target-TWA following; hysteresis (D-4); **tack countdown, stay-on-this-tack (forced first-leg reroute), cost of not tacking (dual routing), auto-recompute 2 min after a missed advised tack**.
**Addresses:** TS-9, TS-15..17, TS-19, D-1, D-3, D-4 + the four user-added helm requirements.
**Avoids:** Pitfalls 9, 11, 12, 13, slow-Pi trap, GRIB-horizon trap.
**Fallback if the benchmark fails:** 10° headings, 30-min steps, next mark plus one only, 10-min cadence. If routing is still too slow, the cost of not tacking is computed only on demand or every other cycle, and the countdown falls back to laylines.

### Phase 4: Hardening and Race Readiness / Commissioning (days 5–6 + 12–13 Nov)
**Rationale:** 36 h unattended at night with a bus that has never been tested. The on-boat runbook is a deliverable in its own right.
**Delivers:** fault-injection runs (Fastnet silent, GPS loss, garbage, clock jump, unplug); 36 h soak at 60×; 5× power-pull test; OOM scores; offline-clock boot test; tablet setup (Wi-Fi isolation, Chrome flag, stay-awake, night brightness); optional overlay FS decision; spare SD clone; GRIB download script tested daily; **commissioning runbook** (probe → wiring swap steps → channel inventory capture with every display page cycled → M/T + COG/HDG check → port/stbd TWD symmetry → engine-start `get_throttled` → Wi-Fi at the helm at night → SI review → course-change drill under 30 s); feature freeze by 11 Nov. On 12 Nov only config fixes, verified by replaying the boat's capture.
**Addresses:** TS-22 verification, D-11, Pitfalls 15, 16, 17, 19.

### Phase Ordering Rationale

- Replay/sim and conventions come first because every other feature is otherwise untestable before 12 Nov, and unit/M-T bugs are silent.
- Helm MVP before routing is a deliberate hedge. Laylines + marks + map deliver "steer this / tack here" even if routing never ships.
- Routing is isolated behind one pure-function boundary so it can run in parallel and degrade (coarser settings, libweatherrouting fallback) without touching anything else.
- The tack-advice features sit in Phase 3 because they are just routing variants (forced first leg) plus supervisor triggers. Their laylines-based fallback countdown sits in Phase 2.
- Hardening is scheduled with dedicated days rather than "if time remains", because 36 h unattended reliability is a stated constraint.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** DTECH 2-wire RS485 wiring/mode switch, and which channels the Hercules 2000/390 actually broadcasts (only answerable on the boat, so plan the capture procedure).
- **Phase 3:** stay-on-tack / cost-of-not-tacking design (constrained routing semantics, minimum forced-leg duration, how to detect "tacked"); bias decay constants; organiser GRIB format; router performance on the Pi 3B (benchmark, not reading).

Phases with standard patterns (skip research-phase):
- **Phase 2:** polar parsing, layline geometry, MapLibre styling and helm UI are well documented in FEATURES/ARCHITECTURE.
- **Phase 4:** systemd/watchdog/atomic IO/tablet setup are covered by PITFALLS checklists.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions checked live against PyPI/npm/Debian. ICON grid extents decoded from real files. Pi routing performance is an estimate only. |
| Features | MEDIUM | Based on vendor manuals (Expedition, SailGrib, Tactics, Navimetrix). Helm layout is opinionated synthesis. |
| Architecture | MEDIUM | Sound engineering judgement and consistent with prior art. Router budget is LOW confidence until benchmarked. |
| Pitfalls | MEDIUM | Primary sources for Fastnet, wheels, NoR and Wake Lock. Termination values, the Jabuka anomaly magnitude and Android behaviour come from community or inference. |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Hercules 390 Fastnet compatibility and channel set:** unknown until 12 Nov. Mitigate with the raw capture + degraded modes, and no feature may hard-depend on TWD or set/drift.
- **Router speed on the Pi 3B:** benchmark by about 9 Nov (day 4). Dual routing for the cost of not tacking doubles the load, so budget for it.
- **"Tacked" detection and the missed-tack rule:** define it (heading/TWA sign change sustained for more than 30 s) and test it in closed-loop sim.
- **Tablet model and WebGL support:** unknown. Check with `chrome://gpu` this week. If needed, the fallback is Leaflet + protomaps-leaflet.
- **Organiser forecast format and Sailing Instructions:** not published. Email the organiser, build a generic GRIB importer, and read the SIs on posting.
- **X35 polar file quality and format:** validate on day 1. Pick a default efficiency factor.
- **Magnetic variation value and Jabuka anomaly extent:** compute variation with WMM. The anomaly radius is a setting.
- **Bias decay constants:** tuning parameters. Expose them and log the GRIB-vs-measured comparison.
- **Overlay FS on Trixie:** community reports only. Test by 9 Nov or skip it.

## Sources

### Primary (HIGH confidence)
- PyPI / npm / sources.debian.org (queried 2026-11-05): versions, aarch64 vs armv7 wheels, Node version on Trixie, signalk-server engines
- opendata.dwd.de ICON-EU / ICON-D2 / EWAM files: grid extents decoded, run horizons
- pyfastnet source and channel map: channel IDs, M/T routing from the display layout
- libweatherrouting source: scalar loops, no current support, validity callbacks
- OSMF tile usage policy: offline prefetch prohibited
- Regata Jabuka NoR / equipment / weather pages: rules, race schedule, forecast page empty

### Secondary (MEDIUM confidence)
- fastnet2ip README: DTECH tested, 28800 8O2, no re-broadcast, replay pacing
- Expedition manual, SailGrib WR help, OpenCPN Tactics, Navimetrix, Freeboard-SK, Raymarine docs: layline models, bias fade, efficiency factors, auto-advance
- MapLibre v6 migration guide: WebGL2/ESM requirement
- DTECH manual, gpsd udev rules, ModemManager bug reports, Wake Lock spec + NoSleep, Android no-internet AP reports
- NIPP registry (ALADIN GRIB paid), ECMWF bora poster, RRS 41 / Case 120

### Tertiary (LOW confidence)
- Oppedijk Fastnet page (termination values), overlay-FS-on-Trixie community reports, Jabuka magnetic anomaly (qualitative), router performance estimates, bias decay constants

---
*Research completed: 2026-11-06*
*Ready for roadmap: yes*
