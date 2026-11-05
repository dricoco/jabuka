# Pitfalls Research

**Domain:** On-board live sailing routing and laylines. Raspberry Pi 3B reads B&G Hercules 2000/390 over Fastnet (DTECH USB RS422/485) plus a VK-162 USB GPS, runs offline GRIB routing, and serves a web app to an Android tablet. Used in a ~36 h night offshore race in the November Adriatic (Regata Jabuka, 13–15 Nov 2026).
**Researched:** 2026-11-05
**Confidence:** MEDIUM overall. The research seam rates web-sourced findings LOW by default. Findings backed by primary sources (fastnet2ip/pyfastnet READMEs, PyPI file listings, the organizer's Notice of Race, World Sailing case book) are raised to MEDIUM. Findings from domain reasoning only are marked as such.

> **Why this matters for this project:** the boat and its Fastnet bus can only be touched on 12–13 Nov. Every pitfall that shows up only on real hardware has to be caught by **(a)** replay or simulation before then, or **(b)** a written on-boat commissioning checklist that takes under 2 hours. Otherwise it is a race-day failure. The roadmap should treat "on-boat commissioning runbook" as a deliverable, not an afterthought.

### Phase vocabulary used below

The roadmapper can rename these, but the mapping should hold.
- **P-FOUND:** Pi OS image, service skeleton, internal data model (units/conventions), replay/simulator
- **P-INGEST:** Fastnet + GPS ingestion, staleness, logging
- **P-NAV:** sailing math (true wind, heading/variation, polars, targets, laylines)
- **P-GRIB:** GRIB acquisition, pre-processing, wind model, live-wind bias correction
- **P-ROUTE:** isochrone routing, land avoidance, marks/rounding, stability
- **P-UI:** web app, helm view, map, tablet setup
- **P-HARDEN:** 36 h robustness (power, SD, time, autostart, watchdog)
- **P-COMMISSION:** on-boat validation runbook for 12–13 Nov, plus the pre-race checklist (GRIB download, SIs, marks)

---

## Critical Pitfalls

### Pitfall 1: Fastnet wiring wrong on race day (polarity, wrong terminals, termination, missing ground)

**What goes wrong:**
The decoder reports nothing, or a stream of checksum and parity errors. Typical causes:
- Data+ and Data- swapped.
- Wires put on the DTECH's RS422 RXD± terminals instead of the RS485 T/R± pair.
- A third terminator added mid-bus.
- No common ground, so the common-mode voltage floats out of range.

There is no second chance to debug at home.

**Why it happens:**
- **Naming:** "A/B" means opposite things to different vendors. The DTECH manual labels T/R+ as RS485 "A+" and T/R- as "B-". B&G uses wire colours, not A/B: White = Network Data +, Green = Network Data -, Red = 12 V, Black = 0 V, plus a screen.
- **Termination:** the bus is already terminated at both ends. Community docs say 100 Ω each end, about 50 Ω measured between White and Green. Adding the adapter's or a HAT's 120 Ω terminator at a tap point changes the load. fastnet2ip's README recommends 120 Ω, but in the context of a HAT that *is* an end node.
- **Ground:** the Pi may be powered from a separate USB bank or converter, so its 0 V can float relative to the instrument 0 V.

**How to avoid:**
- Prepare a **tap harness at home**: screw terminals or WAGO connectors, short labelled pigtails (WHITE→T/R+, GREEN→T/R-, BLACK→GND), ferrules, and a multimeter in the bag.
- **No added termination** by default. Add one only if the error rate is high and the tap is at a bus end.
- **Connect 0 V (Black) to the adapter GND.**
- Write a `fastnet-probe` script that runs before anything else. It opens the port at 28800 8O2, counts bytes/s, parity errors, header and full-frame checksum passes and fails, and the distinct channel IDs seen. It prints a verdict such as "swap wires" or "OK, N frames/s".
  - **Rule:** zero valid checksums plus a steady byte stream means swap polarity first.
  - Inverted RS485 data gives garbage, not damage, so swapping is safe.
- Check the port settings explicitly: `stty -F /dev/ttyUSB0` must show `parenb parodd cstopb cs8 28800`. FTDI (the DTECH chip) supports the non-standard 28800 baud. fastnet2ip reports the DTECH "works out of the box".

**Warning signs:**
- Bytes arrive but there are 0 % valid frames: polarity.
- No bytes at all: wrong terminal pair, or adapter in RS422 mode.
- Intermittent bursts of checksum errors that correlate with the engine or alternator: missing ground or noise.

**Phase to address:** P-INGEST (probe tool plus checksum stats), P-COMMISSION (harness and wiring card).
**Confidence:** MEDIUM. Serial parameters and wire colours come from pyfastnet/fastnet2ip and the Oppedijk Fastnet page. Termination values are from a 2015 community page with internal inconsistencies.

---

### Pitfall 2: Something transmits onto the Fastnet bus (gpsd hotplug, ModemManager, own code)

**What goes wrong:**
A process opens the RS485 adapter and **writes** bytes onto the instrument bus. Possible culprits:
- gpsd probing for a GPS.
- ModemManager sending AT commands.
- A `serial.write` in your own code.
- A HAT whose TX line idles low.

Effects range from B&G displays alarming or freezing to corrupted data for the whole boat, including the crew's own instruments.

**Why it happens:**
- **gpsd:** upstream gpsd udev rules match the FTDI 0403:6001 VID/PID (the DTECH chip) and hot-plug it into gpsd. Debian disables that specific rule "as it matches too many other devices", but derivative images and manual installs may not.
- **ModemManager:** it probes `ttyACM`/`ttyUSB` devices by default.
- **HATs:** fastnet2ip documents that instruments alarm on every reboot when an auto-direction RS485 HAT sees the Pi TX pin low.

**How to avoid:**
- Treat the bus as **receive-only by design**: no write path in the ingest code. The DTECH in 2-wire RS485 mode only drives the line while the host transmits.
- `apt purge modemmanager`, or mask it.
- If gpsd is used, run it only for the GPS (`/dev/serial/by-id/...u-blox...`) with `USBAUTO="false"`. Also check `/lib/udev/rules.d/*gpsd*` for an FTDI match.
- Use `/dev/serial/by-id/` paths for both devices, never `ttyUSB0`/`ttyACM0`.

**Warning signs:**
- B&G displays show "Fastnet error"-type alarms, or values blank out when the Pi boots.
- `lsof /dev/ttyUSB0` shows more than one process.

**Phase to address:** P-FOUND (OS image hardening), P-INGEST.
**Confidence:** MEDIUM. gpsd's FTDI rule is from rule files in OpenEmbedded and Debian. The HAT alarm behaviour is documented in fastnet2ip.

---

### Pitfall 3: Expected channels simply are not on this boat's bus (TWD, set/drift, heading, position)

**What goes wrong:**
The design assumes the Hercules provides TWD, set/drift and heading. On the day, some never appear.

**Why it happens:**
- **Hardware-dependent channels:**
  - Heading (0x49) needs a compass such as a Halcyon on the system.
  - TWD (0x6D) needs heading.
  - Tidal set/drift (0x84/0x83) needs heading, boatspeed **and** a GPS feeding position/COG/SOG into the B&G. The VK-162 on the Pi does not feed the B&G.
- **Display-driven channels:** pyfastnet notes that some installations broadcast certain values (heel, trim, air temperature, pressure) only as 7-segment display text, which decodes to `None`. Which channels appear can depend on what the displays are set to show (domain inference, LOW).
- **Reference ambiguity:** heading, TWD and set are "routed" to Magnetic or True from a display indicator, so the reference can change if the crew changes a setting.

**How to avoid:**
- Design for **minimum viable inputs**: AWA, AWS, BSP (from the bus) plus GPS. Compute TWA/TWS/TWD yourself from these when heading exists, and from COG/SOG when heading does not (degraded).
- Treat Hercules TWD and set/drift as optional bonuses.
- On race day, cycle every display page (TWD, tide, heading) while recording a raw capture, so the replay library contains this boat's real channel set.
- Keep a per-channel "last seen" table visible in a diagnostics page.

**Warning signs:**
- The diagnostics table lacks 0x49/0x6D/0x84 after 60 s.
- TWD appears only while a particular display page is shown.

**Phase to address:** P-INGEST (channel inventory and capture tool), P-NAV (own true-wind computation), P-COMMISSION.
**Confidence:** MEDIUM for channel IDs and M/T routing (pyfastnet channel map). LOW for "display-driven broadcasting" (inference from pyfastnet notes; verify on board).

---

### Pitfall 4: Magnetic vs true heading (and therefore TWD) silently mixed

**What goes wrong:**
- Laylines and routes are rotated by about 5°, the Adriatic variation (about +4.5 to +5° E around Šibenik in 2026; compute it, don't hard-code it).
- If the sign is wrong, they are rotated by about 10°.
- TWD from the bus may be magnetic while GRIB wind is true. The "bias correction" then learns a fake 5° shift and applies it to the whole forecast.

**Why it happens:**
- Fastnet carries **no variation or deviation**. fastnet2ip and pyfastnet both state that they cannot convert M↔T and only label what the instrument says.
- The NMEA output of fastnet2ip emits HDM or HDT, and MWD, depending on the instrument setting. Downstream code often assumes "heading = true".

**How to avoid:**
- Use **one internal convention: everything TRUE, degrees, wind = FROM, current = TOWARDS**.
- Convert at the ingest boundary using a WMM2025 model computed offline (e.g. `pygeomag`/`wmm2020`-class lib, or a precomputed constant per leg).
- **True = Magnetic + East variation.**
- Store the reference flag with every heading and TWD sample.
- Add a manual **heading offset** (deviation and compass alignment) setting.
- **Calibrate heading on 12–13 Nov:** motor in flat water on four headings and compare (HDG + var) with GPS COG at slack current.

**Warning signs:**
- Persistent COG − (HDG + var) offset of more than 3° while motoring with no current.
- Computed TWD differs from GRIB by a near-constant 5° in a steady gradient wind.

**Phase to address:** P-FOUND (conventions doc and unit tests), P-NAV, P-COMMISSION (heading check).
**Confidence:** MEDIUM. The no-variation-on-bus point is from primary READMEs. The variation value is approximate (domain knowledge), so compute it with WMM.

---

### Pitfall 5: Jabuka is a magnetic island; the compass lies near the key mark

**What goes wrong:**
Jabuka's rock contains magnetite and is known for deflecting ship compasses. Near the island, the fluxgate heading is wrong. TWD (heading + TWA) is then wrong too, so the bias correction and the laylines **at the most important rounding of the race** are wrong.

**Why it happens:** The B&G heading sensor cannot tell a local anomaly from a real heading change.

**How to avoid:**
- Inside a configurable radius of Jabuka (start with about 3 nm), automatically **freeze the live-wind bias**: hold the last good TWD and stop learning.
- Compute laylines from GPS COG and the measured tacking angle rather than from heading.
- Show a "MAG ANOMALY: heading unreliable" badge.
- The same mechanism doubles as a general "heading untrusted" degraded mode.

**Warning signs:** Computed TWD drifts steadily as the distance to Jabuka shrinks. HDG vs COG divergence grows without a corresponding current.

**Phase to address:** P-NAV (heading-trust flag), P-UI (badge).
**Confidence:** LOW-MEDIUM. The anomaly is well documented qualitatively, but its magnitude and extent are unknown. Cheap to mitigate, so do it.

---

### Pitfall 6: Uncalibrated true wind (upwash, mast twist, heel) makes TWD jump on every tack

**What goes wrong:**
- Measured TWD differs by 5–15° between port and starboard tacks.
- The bias corrector treats each tack as a wind shift, so the router "re-plans" after every tack and recommends tacking back.
- Laylines swing as the boat tacks.

**Why it happens:**
- Masthead AWA is distorted by sail upwash. H2000 true-wind correction tables are often never calibrated.
- Generic upwash corrections differ by boat.
- Leeway is ignored. TWA is relative to heading while the boat tracks along heading + leeway.

**How to avoid:**
- Compute true wind yourself from AWA, AWS, BSP and HDG, with:
  - a **user-tunable upwash correction** (a simple symmetric AWA offset upwind, e.g. 0–4°)
  - an optional leeway term.
- Use the B&G TWD only for comparison.
- Filter TWD with a **tack-aware filter**: a long time constant, a reset or blend window of about 60–90 s after a manoeuvre (detected from a heading change of more than 50°), and exclusion of samples while BSP is still recovering.
- Show port-tack and starboard-tack mean TWD side by side so the navigator can trim the correction at sea. Add a one-tap "these two should match" auto-calibration that sets the offset to half the difference.

**Warning signs:** In replay or on the water, TWD step changes coincide with tacks. The difference between port and starboard tack averages stays above 4°.

**Phase to address:** P-NAV (true-wind computation, filter, calibration UI), P-COMMISSION (first-tacks check before the start; there is a 4 h start window).
**Confidence:** MEDIUM (standard performance-instrument knowledge; no primary source fetched).

---

### Pitfall 7: Generic X35 polar gives optimistic targets and laylines

**What goes wrong:**
- The router assumes theoretical speeds (ORC-style polar, flat water, full crew, perfect trim).
- At night, in a bora or jugo chop, real BSP is 5–15 % lower and the real tacking angle is wider.
- Laylines are too tight and the boat understands the mark. Routes prefer upwind options too much, and ETAs are hours optimistic over a 100 nm course.

**Why it happens:** Polars are rarely corrected for sea state, sail inventory (reefed, small jib at night) or helming quality. PROJECT.md already flags this.

**How to avoid:**
- Add a **global efficiency factor** (default 0.90–0.95).
- Add **separate upwind and downwind factors**.
- Add a **wave/TWS-based reduction**.
- Add a **tacking/gybe penalty in seconds**.
- Allow laylines based on the "observed tacking angle": the boat's own COG on each tack, measured over the last minutes. Offer this as an alternative to polar target TWA.
- Log BSP vs polar continuously and show "% of polar". Let the navigator adjust the factor at sea.

**Warning signs:** "% polar" sits steadily below 90 %. The boat repeatedly needs extra tacks to fetch marks the laylines said were fetchable.

**Phase to address:** P-NAV (factors, observed-angle laylines), P-ROUTE (manoeuvre penalty).
**Confidence:** MEDIUM (widely reported by routing practitioners; consistent with PROJECT.md).

---

### Pitfall 8: Direction-convention and unit bugs (FROM vs TOWARDS, u/v sign, knots vs m/s, AWA ±180 vs 0–360)

**What goes wrong:**
- Wind is used 180° off: a run looks like a beat.
- Current is applied backwards.
- Wind speeds are off by about 1.94× (m/s vs kn), so the polar is read at the wrong TWS.
- Port and starboard laylines are swapped.

**Why it happens:**
- GRIB `10u`/`10v` give the wind's direction of **motion**, so the FROM direction is `atan2(-u, -v)`.
- Copernicus `uo`/`vo` and NMEA VDR/set give current **TOWARDS**.
- MWD and wind GRIB conventions give wind **FROM**.
- Units differ:
  - pyfastnet emits Signal K units (radians, m/s).
  - NMEA 0183 uses degrees and knots.
  - libweatherrouting's `get_wind_at()` returns TWS in **m/s**.
  - Polar files are in **knots**.
- AWA arrives as ±180 from some sources and 0–360 from others.

**How to avoid:**
- Keep a single conventions module and doc (P-FOUND) with golden unit tests. Examples:
  - u = +5, v = 0 → wind FROM 270° (west).
  - Current set 090° at 1 kn moves the boat east.
  - Boat heading 000 with AWA +45 (starboard) → wind from 045 apparent.
- Run one **end-to-end sanity scenario** in the simulator: a known northerly wind of 15 kn, the boat beating north, starboard tack; assert TWA, TWD, laylines and the router's first leg.
- Interpolate **u/v components**, never direction angles (359°/1° wrap).

**Warning signs:** The router recommends motoring straight upwind. Laylines are drawn downwind of the mark. Displayed TWS is roughly double or half the B&G display.

**Phase to address:** P-FOUND (conventions plus tests), P-GRIB, P-NAV.
**Confidence:** HIGH for the conventions themselves (standard meteorological and NMEA definitions). MEDIUM for the libweatherrouting units (README).

---

### Pitfall 9: GRIB coverage, resolution and time-horizon surprises for THIS course

**What goes wrong:**
- **ICON-D2 domain:** the regular grid's southern edge is around 43.18° N (MEDIUM, from memory of the DWD grid; verify by loading the file). **Jabuka (43.09° N, 15.46° E) is outside or at the edge**, inside the lateral relaxation zone. The router gets `None` or garbage wind for the southern leg.
- **ICON-D2 horizon:** about 48 h. A run downloaded on 13 Nov morning may end before the 15 Nov 10:00 local time limit.
- **ICON-EU** (about 6.5 km) and **GFS** (0.25°, about 25 km) cannot resolve island channel acceleration, wind shadows behind Kornati/Žirje or bora jets. Bora gusts are underestimated by coarse models: an ECMWF evaluation found only 2 km ALADIN caught the gusts.
- **ALADIN/DHMZ GRIB** is listed as a **fee-based product** in the Croatian registry (GIF images are free). It may simply not be obtainable in time.
- **Organizer forecast page** still contains placeholder text (checked 2026-11-05). Expect images or links, not GRIB.

**Why it happens:** Model domains, horizons and access terms are checked only when the first download fails.

**How to avoid:**
- **Multi-source wind model:** for each point and time, use the finest model that covers it with a valid time. Use ICON-D2 where it covers, away from its boundary, and blend to ICON-EU near the edges and south of about 43.4° N.
- Assert coverage **for every mark and the rhumb lines between them** at load time, and for the full window 13 Nov 19:00 UTC → 15 Nov 09:00 UTC (+ margin). Show a red "NO WIND DATA" for any gap.
- Download the **latest possible runs** in Vodice on 13 Nov afternoon:
  - ICON-D2 12 UTC run is typically available about 1.5–2 h after run time.
  - ICON-EU 12 UTC run covers well beyond the limit.
- Also keep a GFS or ECMWF-open backup.
- Prepare the download script now and run it daily to test it.
- Email the organizer (jk_tijat_vodice@yahoo.com) about the forecast format. Do not build an importer for an unknown format.

**Warning signs:** The wind function returns `None` south of 43.2° N in tests. GRIB last valid time is earlier than 15 Nov 09 UTC. The route crosses a 2 km-wide channel and shows the same wind as open sea.

**Phase to address:** P-GRIB (coverage assertions, blending, download script), P-COMMISSION (final download checklist).
**Confidence:**
- MEDIUM: the ALADIN fee status (NIPP registry), the bora underestimation (ECMWF poster) and the organizer page state (fetched).
- MEDIUM-LOW: the exact ICON-D2 southern bound. **Verify on day 1 by loading an ICON-D2 file**.

---

### Pitfall 10: GRIB decoding on the Pi (eccodes wheels, 32-bit vs 64-bit, memory)

**What goes wrong:**
- `pip install eccodes cfgrib` fails or compiles for hours on the Pi.
- Or decoding a full ICON-D2 domain (about 1215×746 points × u,v × 48 steps, roughly 350 MB as float32) runs the 1 GB Pi 3B into swap or the OOM killer mid-race.

**Why it happens:**
- `eccodes` ≥ 2.43 on Linux depends on `eccodeslib`.
- `eccodeslib` 2.50.0.33 (Oct 2026) ships **manylinux_2_28 x86_64 and aarch64 wheels only. No armv7l/armhf.**
- piwheels supports only 32-bit Raspberry Pi OS.
- **Recommendation: avoid needing either on the Pi.**

**How to avoid:**
- **Pre-process GRIB on the laptop** (where eccodes, cfgrib and xarray just work):
  1. Crop to the race box (about 42.8–44.0° N, 14.9–16.2° E).
  2. Convert to a compact `.npz` (u10, v10, optional gust and wave fields, on a regular grid, times in UTC epoch).
  3. Copy it to the Pi.
- The Pi needs only numpy. If on-Pi decoding is ever wanted, use **64-bit Raspberry Pi OS (arm64)** so the `eccodeslib` aarch64 wheels apply, or `apt install python3-eccodes`.
- Pick the OS architecture on day 1. Changing it later means reinstalling everything.

**Warning signs:** pip starts building from source on the Pi. RSS of the routing process exceeds 300 MB. `dmesg` shows the OOM killer.

**Phase to address:** P-FOUND (OS image: 64-bit Lite), P-GRIB (laptop pre-processor, `.npz` format).
**Confidence:** HIGH for the wheel availability (PyPI file listings fetched). MEDIUM for the memory estimate (arithmetic).

---

### Pitfall 11: Marks on land, island roundings and coastline detail

**What goes wrong:**
- **Islands as marks:** Jabuka, Blitvenica and Mulo are islands or islets. A mark tapped on the island is **on land**, so the router's `point_validity` rejects it and routing fails or loops.
- **Coastline detail:** low-resolution coastlines (GSHHG crude/low) miss islets and shoals. Plić Sestre is a "plić" (shoal). The route cuts across rocks between Kornati and Žirje.
- **Segment checks:** checking only isochrone points, not the segments between them, lets routes "jump" over narrow islands.

**Why it happens:** Routing libraries treat marks as points. Coastline checks are optional callbacks (`point_validity`/`line_validity` in libweatherrouting) that the developer must implement.

**How to avoid:**
- Model each mark as **(position, rounding side, safety radius)**.
- The router targets a **rounding waypoint** offset seaward on the correct side (or a gate). Snap any mark tapped on land to the nearest sea point at the safety radius, and warn.
- Use **full-resolution coastline polygons clipped to the race area** (OSM land polygons or GSHHG "f"). Buffer them by a safety margin (e.g. 0.2 nm), simplify, and index them with an STRtree (shapely).
- Implement **segment** intersection, not only point-in-polygon.
- Pre-compute a land raster (e.g. 100 m) for fast point lookups on the Pi.
- Add known hazards (Plić Sestre shoal, Blitvenica reefs) as polygons.

**Warning signs:** Route lines cross land on the map overlay. The route to a mark tapped on Jabuka never converges. Routing is fast in open sea but takes minutes near the archipelago, which indicates unindexed polygons.

**Phase to address:** P-ROUTE (mark model, land checks), P-UI (mark entry with side and snapping).
**Confidence:** HIGH for the libweatherrouting validity callbacks (README). The "plić" = shoal meaning is Croatian vocabulary. The geometry advice is standard.

---

### Pitfall 12: Route flipping between successive re-runs

**What goes wrong:**
- Re-running every few minutes from a slightly different position and wind, the optimum alternates, e.g. "north of Žirje" one run and "south of Žirje" the next, or "tack now" then "hold".
- The helmsman loses trust in the screen, which defeats the core value.

**Why it happens:** Isochrone routing has near-ties between topologically different routes. Discretisation (heading step, time step, pruning sectors) and the live bias correction add noise.

**How to avoid:**
- Apply **hysteresis**: replace the displayed route only if the new ETA beats the *currently displayed route re-evaluated under the same new wind* by more than X minutes (e.g. 3 % of remaining time or 5 min).
- Always re-evaluate the previous route as a candidate.
- Smooth the inputs: bias correction with a time constant of 10 min or more.
- Keep discretisation constant between runs.
- Show "route changed" explicitly, with the reason, rather than silently.

**Warning signs:** In replay, the first-leg heading changes by more than 30° between consecutive runs while the conditions are steady.

**Phase to address:** P-ROUTE (stability logic), tested in replay under P-FOUND's simulator.
**Confidence:** MEDIUM (well-known practitioner complaint about live routers; domain reasoning).

---

### Pitfall 13: Live-wind bias correction that poisons the forecast

**What goes wrong:**
- **Local leakage:** a gust, lull, island wind shadow or acceleration zone, or a mid-tack sample, is learned as "the GRIB is 40 % too weak" and applied to the whole course for hours.
- **Reference mismatch:** in current, water-referenced true wind (measured) is compared with ground-referenced GRIB wind.
- **Height mismatch:** masthead height (about 16–17 m) is compared with a 10 m GRIB.

**Why it happens:** Naive implementations take bias = measured − forecast with a single sample and apply it uniformly.

**How to avoid:**
- Compute the bias from **filtered** (10–15 min) ground-referenced TWD/TWS: correct for current when it is known, else accept the error.
- Store direction as an additive offset and speed as a **ratio**, both clamped (e.g. ±30°, 0.6–1.5×).
- Decay the bias in **time and distance**, e.g. half-life about 2–3 h and about 10–15 nm.
- Exclude samples during manoeuvres and near the Jabuka anomaly.
- Show the bias numerically ("GRIB +12°, ×1.15") so the navigator can veto it, with a toggle to disable it.

**Warning signs:** Bias swings by more than 10° or more than 20 % over 15 min in replay. Route ETA jumps after every tack.

**Phase to address:** P-GRIB (bias model), P-NAV (filtered inputs).
**Confidence:** MEDIUM (domain reasoning; consistent with how commercial routers expose a "wind offset").

---

### Pitfall 14: Pi has no RTC; system clock wrong at boot means wrong GRIB time slice

**What goes wrong:**
- Offline, the Pi boots with fake-hwclock's last saved time, which can be hours or days old. Routing picks the wrong forecast hour.
- Logs get wrong timestamps.
- If chrony or timesyncd later steps the clock by hours, timers and staleness checks misbehave (negative ages, frozen loops).

**Why it happens:**
- No internet means no NTP.
- chrony by default only steps at startup (`makestep 1 3`).
- The app reads `time.time()` naively.
- Separately, cheap u-blox 6/7/8 USB GPS units have reported **correct time but wrong date** (GPS week-rollover compensation). u-blox 7 FW 7.x defaults are fine until 2030, but clones vary.

**How to avoid:**
- Derive **race time from GPS RMC/ZDA (UTC)** inside the app, with a sanity check: year 2026 and date within ±2 days of the GRIB reference time.
- Use the monotonic clock for staleness and intervals.
- Optionally run chrony with gpsd SHM and `makestep 1 -1`.
- Display UTC and local time (CET = UTC+1 in November; the race start 20:00 local is 19:00 UTC).
- Store everything in UTC.

**Warning signs:** The UI shows forecast valid time ≠ current UTC hour. The date shows 2006 or 2046. Log timestamps go backwards.

**Phase to address:** P-HARDEN (time source), P-GRIB (UTC everywhere), P-INGEST (GPS date sanity).
**Confidence:** HIGH for no RTC and UTC GRIB. MEDIUM for the u-blox rollover reports (OpenPlotter forum, u-blox app notes).

---

### Pitfall 15: Power events on a 12 V boat lead to undervoltage, USB resets and SD-card corruption

**What goes wrong:**
- Engine cranking dips 12 V to about 9–10 V. A cheap buck converter or a long micro-USB cable leaves the Pi 3B below 4.63 V. It throttles, the USB devices (GPS, FTDI) reset and re-enumerate, and open serial handles die silently.
- Hard power-off (crew kills the instrument breaker at night to save battery, or the house bank drops) corrupts the ext4 root on the SD card, and the Pi does not boot on the second night.

**Why it happens:**
- The Pi 3B wants 5.1 V at 2.5 A over micro-USB, where the thin cable's voltage drop is real.
- SD cards are not power-loss safe.

**How to avoid:**
- Use a quality 12→5 V converter (≥ 3 A, wide input range 8–30 V) and a short, thick cable, or feed the 5 V GPIO pins.
- Check `vcgencmd get_throttled` on the boat; it must be `0x0` while the engine starts.
- Make the root filesystem **read-only (raspi-config OverlayFS)**. Put logs on tmpfs plus a small separate writable partition with periodic `fsync`, or on a USB stick.
- **Carry a second, identically imaged SD card** and a printed "swap card" instruction.
- Serial readers must **detect EOF and errors, then reopen by `/dev/serial/by-id`** in a retry loop.

**Warning signs:** "Undervoltage detected" in `dmesg`. `get_throttled` is non-zero. GPS or Fastnet data stops after the engine starts. The rainbow square or lightning-bolt icon appears.

**Phase to address:** P-HARDEN (read-only FS, reconnect loops), P-COMMISSION (engine-start test, spare SD).
**Confidence:** MEDIUM (vendor and community sources plus standard Pi knowledge).

---

### Pitfall 16: Android tablet drops off the Pi's Wi-Fi or routes around it ("no internet")

**What goes wrong:**
- Android detects that the Pi AP has no internet. It then:
  - silently prefers mobile data (if there is a SIM), so requests to 10.x/192.168.x fail;
  - prompts "Stay connected?", which nobody answers at night;
  - or auto-switches to a known network that has internet, such as a crew phone hotspot.
- The helm screen freezes on stale data.

**Why it happens:** Android connectivity validation. Reported repeatedly for Pi, ESP32 and LibreELEC access points. The only reliable workaround found is to disable mobile data and answer "stay connected".

**How to avoid:**
- Tablet setup checklist:
  - Forget all other Wi-Fi networks.
  - Disable mobile data, "switch to mobile data automatically" and adaptive Wi-Fi.
  - Tick "stay connected" once, at the dock.
  - Use a **fixed IP URL** (no `.local`/mDNS, no DNS).
- On the Pi, run the AP with NetworkManager (Bookworm/Trixie default; old hostapd tutorials are stale) and turn off Wi-Fi power save (`iw wlan0 set power_save off`).
- Optionally run a local DNS that answers connectivity-check hostnames (some apps/OSes accept a 204 from a local server). Treat this as a nice-to-have, untested.

**Warning signs:** A Wi-Fi icon with "!" on the tablet. The page loads at the dock (where a phone has internet) but not offshore.

**Phase to address:** P-UI (tablet setup doc), P-HARDEN (AP config), P-COMMISSION (test with phones' mobile data off, as at sea).
**Confidence:** MEDIUM (multiple independent forum reports, no official Android doc).

---

### Pitfall 17: Plain-HTTP origin cannot use Screen Wake Lock, so the tablet sleeps mid-race

**What goes wrong:**
- The screen turns off after 30 s to 2 min. The helmsman, wearing gloves and wet, has to unlock it every time, or ignores it.
- `navigator.wakeLock` is undefined.

**Why it happens:**
- The Screen Wake Lock API is **secure-context only** (HTTPS or localhost).
- `http://10.42.0.1` is neither. Service workers (PWA install, offline cache) are secure-context only too.

**How to avoid:**
- Use several layers:
  1. In Chrome Android, set `chrome://flags/#unsafely-treat-insecure-origin-as-secure` = `http://<pi-ip>:<port>` (supported on Android per community docs). This makes Wake Lock available.
  2. Fallback: a NoSleep.js-style looping muted video started on the first tap.
  3. OS level: maximum screen timeout, plus Developer options "Stay awake while charging" (the tablet should be on cockpit power for 36 h anyway).
- Do **not** depend on service workers. The Pi serves everything.
- Verify on **the actual tablet** this week.

**Warning signs:** `window.isSecureContext === false` in the console. The screen dims during bench tests.

**Phase to address:** P-UI.
**Confidence:** MEDIUM. The secure-context requirement is spec-level (HIGH). The Android flag behaviour comes from community docs (MEDIUM). Test it.

---

### Pitfall 18: State lives in the browser, so reloads lose marks and route

**What goes wrong:**
- Android kills the background tab, Chrome reloads after a sleep, or a second device (a laptop) connects.
- Marks entered on the tablet are gone, or the devices show different courses.

**How to avoid:**
- **The Pi is the single source of truth** for marks, course, settings and offsets, persisted to the writable partition atomically (write temp file, `fsync`, rename).
- The browser is a stateless view with WebSocket auto-reconnect and backoff.
- Show data age on every number.

**Warning signs:** Marks disappear after the tablet sleeps in bench tests.

**Phase to address:** P-UI, P-HARDEN.
**Confidence:** HIGH (standard web-app behaviour on Android).

---

### Pitfall 19: Rules exposure (RRS 41 and the Sailing Instructions)

**What goes wrong:**
- A protest or an RC question about outside help.
- The SIs (not yet published) add electronics or communication restrictions, or change the course.

**What the research shows:**
- **Governing rules:** the NoR applies RRS 2025–2028, OSR Cat 3 (without liferaft) and ORC rules. **IRPCAS replaces RRS Part 2 from sunset to sunrise.**
- **Organizer equipment:** the organizer may install **GPS trackers or video cameras**.
- **No RRS 41 changes** are in the NoR, and the equipment list has no electronics restrictions.
- **Sailing Instructions:** to be posted on regata-jabuka.com and racingrulesofsailing.org (event 16094; that site returned 403 to automated fetch).
- **Own computation:** computing with your own instruments and software on board is **not** "help from an outside source".
- **Pre-race data:** RRS 41 applies "while racing", so GRIBs downloaded before the start are not outside help received while racing.
- **Freely available information:** under RRS 41(c) and Case 120, freely available info is allowed anyway. Software used to read it is not the issue; paid, non-public data is.
- **Low residual risk:** the main risk is an SI clause, e.g. no data reception during the race. The system is offline by design, which helps.

**How to avoid:**
- **Read the SIs the moment they are posted.** Ask at registration (13 Nov 12:00–18:00) whether there are any restrictions on electronic navigation aids or data reception.
- Keep the Pi **fully offline**: no phone tethering for "just one GRIB update" during the race.
- Use only free, public GRIB sources.
- Plan for **course changes and shortened courses**: "each checkpoint may serve as an auxiliary finish". The UI needs a fast "finish at this mark / reorder course" action.

**Warning signs:** The SIs mention "electronic devices", "data reception" or "routing".

**Phase to address:** P-COMMISSION (SI review, course-change drill), P-UI (course editing).
**Confidence:** MEDIUM. The NoR was fetched (primary). RRS 41 and Case 120 interpretations come from the World Sailing case book via racingrulesofsailing.org and PredictWind summaries. The SIs are unread (gap).

---

## Moderate Pitfalls (summarised)

| Pitfall | What goes wrong | Prevention | Phase |
|---|---|---|---|
| **fastnet2ip goes silent on stale sources** | The README: "no dedup or periodic re-broadcast, so output stops when a source goes quiet". The UI keeps showing the last value as if live. | Per-field `last_update` and a max-age (e.g. 5 s for wind/BSP, 3 s for GPS). Show a grey or STALE overlay and drop to the degraded mode automatically. | P-INGEST, P-UI |
| **Replay is not wire-accurate** | fastnet2ip `--file` replay paces at about 5120 B/s with no timestamps. Timing-dependent bugs (filters, staleness) don't reproduce. | Record your own captures **with timestamps** (raw bytes + monotonic time) on race day. Build the simulator on a timestamped format from day 1. | P-FOUND, P-INGEST |
| **No real capture until race day** | The decoder is only tested against other people's captures (pyfastnet `captures/` in the repo, not the pip package). | Clone the pyfastnet repo for its captures. Build a synthetic Fastnet frame generator (header/body checksums per the Oppedijk spec) for unit tests. | P-FOUND |
| **Using fastnet2ip's UDP NMEA as the integration seam** | Loses precision and reference flags. Adds the broadcast address (255.255.255.255), a port and a process that can die. NMEA heading may be HDM or HDT. | Prefer importing **pyfastnet directly** (no deps, Python ≥3.7) in your own ingest process. Keep fastnet2ip as a fallback CLI for diagnostics. | P-INGEST |
| **pyfastnet threading/queue semantics** | `frame_queue` drops new frames when full. `add_to_buffer`/`get_complete_frames` must be called from one thread. | Single reader thread that drains every loop. Count dropped frames. | P-INGEST |
| **gpsd vs direct serial for the VK-162** | gpsd grabs `ttyACM0` and the app's direct open gets nothing (or the reverse). | Pick one. Recommendation: read NMEA directly with pyserial from `/dev/serial/by-id/usb-u-blox_...`, no gpsd. If gpsd is used for chrony, the app must be a gpsd client. | P-INGEST |
| **VK-162 cold start / no fix below deck** | 1–several minutes to fix, longer inside the cabin. The u-blox 7 default is 1 Hz and GPS-only. | Mount it with sky view (cockpit, under a deck window). Show fix quality, satellites and HDOP. Don't start routing until a 3D fix. Optional: UBX to enable GLONASS / 5 Hz (stay at 1–2 Hz on a Pi 3B). | P-INGEST, P-COMMISSION |
| **Isochrone compute too slow on Pi 3B** | Pure-Python routing over about 40–60 nm legs with 5° heading steps and 10 min steps can take minutes. Re-run "every few minutes" overlaps itself and starves the web server. | Benchmark **on the Pi** in week 1. Vectorise with numpy. Prune isochrones by sector. Use coarse-then-fine steps (5 min near, 20–30 min far). Run in a separate process at `nice` priority with a hard time budget. Always serve the last good route. | P-ROUTE |
| **Routing past the GRIB horizon or domain** | libweatherrouting's wind function returns `None` outside the time or space range, and the routing stalls or ends silently. | Explicit "forecast ends at T" handling: hold the last field or persist the measured wind beyond the horizon, with a visible warning. | P-ROUTE, P-GRIB |
| **No tack/gybe penalty** | Optimal routes zig-zag at every time step upwind. | Manoeuvre penalty (e.g. 30–60 s at X35 size, more in a heavy sea) plus a minimum leg duration. | P-ROUTE |
| **Wind interpolation near land** | Coastal model cells have land roughness, so the wind interpolated near islands is too low. | Use the land-sea mask if available. Prefer sea-cell values. Otherwise accept and rely on the live bias. | P-GRIB |
| **Current file is NetCDF, not GRIB; currents are tiny** | Copernicus MEDSEA currents come as NetCDF, need an account, and are usually 0.1–0.5 kn in the Adriatic (larger in strong bora/jugo). | Defer current to optional. If used, convert on the laptop to the same `.npz` format. Set is TOWARDS. | P-GRIB (optional) |
| **Wind at 10 m vs masthead** | Measured TWS is about 5–10 % above GRIB 10 m wind. | Absorbed by the speed-ratio bias. Document it rather than double-correcting. | P-GRIB |
| **Wet-screen ghost touches** | Spray or rain on a capacitive screen pans the map, moves marks or opens dialogs during the race. | **Helm view has a lock mode.** Editing marks needs an explicit unlock and confirm. Keep big hit targets. Add an undo for the last mark edit. | P-UI |
| **Night vision / sunlight** | A white OSM map at night destroys night vision. Grey-on-white numbers are unreadable in sun. | Night theme: black background, red/amber numbers, dark-styled or CSS-inverted tiles, auto by sun altitude plus a manual toggle. Day theme: maximum contrast, huge numbers. | P-UI |
| **Offline map tiles too heavy / wrong zoom** | The tile set for the area at z15+ is GBs. Missing zooms show blank grey. | Pre-render an MBTiles for the race box at z8–z14 (z15–16 only around marks/harbour). Serve it from the Pi. Test fully offline. | P-UI |
| **Pi 3B Wi-Fi range / antenna** | Onboard 2.4 GHz chip antenna in a box at the nav station, through a bulkhead, and the cockpit has crew bodies in the path. | Place the Pi or a USB Wi-Fi dongle near the companionway. Test the signal at the helm with the boat closed up at night. | P-COMMISSION |
| **Thermal** | Low risk in November. A sealed box plus a routing CPU at 100 % can still throttle. | Monitor `vcgencmd measure_temp`. Use a vented case. | P-HARDEN |

## Minor Pitfalls

- **Pi built-in UART first-open stuck at 9600** (fastnet2ip note). Not relevant with the USB DTECH, but relevant if anyone swaps to a HAT.
- **Time zone in the UI:** CEST ended on 25 Oct, so the race is in CET (UTC+1). Never display GRIB times without a zone.
- **PyPI immutability:** pin exact versions of fastnet2ip and pyfastnet. Vendor the wheels onto the Pi image; no internet at the marina may also mean no `pip install` on the 12th.
- **Two clients (tablet + laptop) editing marks at once:** last-write-wins with a version number. Show "updated by other device".
- **Logging fills the disk over 36 h at 20 Hz per channel:** downsample to 1–2 Hz for the persistent log, use a rotating ring buffer, and keep a raw capture only on demand.

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|---|---|---|---|
| Hard-code variation +5° E | No WMM dependency | Wrong elsewhere and in later years | Acceptable for Jabuka **if** it is a visible setting, not a magic number |
| Use fastnet2ip UDP NMEA instead of pyfastnet in-process | Zero decoder code | Loses M/T flags and precision, adds a process | Acceptable as a fallback path only |
| Pre-process GRIB on the laptop only (no on-Pi GRIB) | Avoids eccodes on the Pi entirely | Can't load a new GRIB on board without a laptop | **Recommended for v1.** The laptop comes to the boat anyway. |
| Single global polar efficiency factor | 5 min to implement | Upwind and downwind errors differ | MVP only; add up/down split if time allows |
| No HTTPS | Simplicity | Wake lock and service workers unavailable without the Chrome flag | Acceptable with the flag plus the OS "stay awake" setting |
| Skip current entirely | Saves a day | Small ETA and layline errors (Adriatic currents are weak) | Acceptable for Jabuka |
| Write config with plain `open().write()` | Simple | Corrupt JSON after a power cut means no marks on reboot | **Never.** Atomic write is 5 lines. |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| DTECH RS422/485 | Wiring to RXD± (422 receive) | 2-wire RS485 on **T/R+ / T/R-**, plus GND. Adapter set to RS485 mode. |
| Fastnet serial | Default pyserial settings (8N1) | `baudrate=28800, bytesize=8, parity=ODD, stopbits=2` |
| pyfastnet | Assuming radians and m/s are degrees and knots | Convert at the boundary. Keep the M/T routed path name. |
| VK-162 | Opening `ttyACM0` while gpsd or ModemManager owns it | Purge ModemManager, avoid or disable gpsd hotplug, use the by-id path. |
| GRIB (ICON) | Direction from u/v as `atan2(u,v)` | FROM = `atan2(-u,-v)`. Interpolate u/v. |
| GRIB time | Treating valid time as local | Everything in UTC, displayed in CET |
| libweatherrouting | Knots into `get_wind_at` | TWS is in **m/s** per the README. Polar in knots. Unit-test both. |
| libweatherrouting | No `point_validity`/`line_validity` | Implement both against a buffered, indexed coastline. |
| Android Chrome | Using `.local` hostname | Fixed IP (e.g. `http://10.42.0.1:8080`), bookmarked to the home screen |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|---|---|---|---|
| Full-domain GRIB in RAM | Swap, OOM | Crop to the race box on the laptop; float32; `.npz` | Full ICON-D2 or ICON-EU on 1 GB RAM |
| Unindexed coastline polygons | Routing minutes long near the archipelago | Buffered, simplified polygons plus STRtree or raster lookup | Thousands of Kornati islets × thousands of isochrone segments |
| Routing in the web-server process | UI freezes during routing | Separate process, nice, time budget | Every re-route on a Pi 3B |
| 20 Hz WebSocket push of every field | Tablet battery drain, Pi CPU | Push the UI state at 1–2 Hz, coalesced | Always on a Pi 3B |
| Leaflet with many SVG layers at night | Tablet lag when panning | Few layers; canvas renderer for isochrones | Drawing full isochrone sets |

## Security Mistakes

| Mistake | Risk | Prevention |
|---|---|---|
| Open Wi-Fi AP | Any device in the marina (or a nearby boat) can edit your marks | WPA2 PSK. Optionally an edit PIN for mark changes. |
| Default `pi`/password or SSH open on the AP | Remote tampering (low likelihood) | Key-only SSH. Disable password auth. |
| Any write path to the Fastnet port | Corrupting the boat's instruments | Receive-only code path. Purge ModemManager. No gpsd on the FTDI device. |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---|---|---|
| Showing route heading without data age or quality | The helm steers to stale or garbage advice | Every number has an age/quality indicator. The whole panel greys out on stale data. |
| Silent fallback between data modes | The helmsman doesn't know the advice is GRIB-only | A big mode badge: **LIVE / GPS+GRIB / MANUAL WIND** |
| Map-first layout | Numbers too small to read in a seaway | Numbers first (heading to steer, Δ, TWA target, layline distance/time). The map is secondary. |
| Laylines as thin lines | Invisible in sun or at night | Thick colour-coded port/starboard lines plus "layline in 0.8 nm / 6 min" text |
| Flashing route changes | Distraction at night; IRPCAS lookout duty at night | Gentle "ROUTE UPDATED" with the reason. No flashing, no sound. |

## "Looks Done But Isn't" Checklist

- [ ] **Fastnet ingest:** works on a pyfastnet capture, but was never run with this boat's channel set. Verify the channel inventory on 12 Nov and record a timestamped capture.
- [ ] **True wind:** right on one tack in the simulator. Verify port vs starboard TWD symmetry with an upwash offset.
- [ ] **Heading:** right in the simulator (true). Verify the M/T flag handling and variation sign with a real HDM capture.
- [ ] **GRIB:** loads one file. Verify coverage of **every mark** (Jabuka!) and of time to 15 Nov 09 UTC.
- [ ] **Routing:** finds a route in open sea. Verify a route **around Jabuka with the rounding side**, past Žirje/Kornati, with no land crossing.
- [ ] **Routing on the Pi:** fast on the laptop. Verify runtime on the Pi 3B for the full course.
- [ ] **Autostart:** works after `reboot`. Verify after **pulling the power** 5 times, and after unplugging and replugging the GPS and adapter while running.
- [ ] **Tablet:** works at the desk with home Wi-Fi. Verify with mobile data off, no other networks, screen-timeout behaviour, at night brightness, with a wet screen.
- [ ] **Time:** correct with internet. Verify with Wi-Fi uplink off and fake-hwclock 3 days stale.
- [ ] **Degraded modes:** exist in code. Verify by physically unplugging the RS485 adapter during a replay run, then entering manual TWD/TWS.
- [ ] **Course change:** marks can be added. Verify you can shorten the course to finish at Blitvenica/Mulo in under 30 s.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---|---|---|
| Fastnet doesn't decode on race day | LOW (if planned) | Swap White/Green → check GND → remove termination → check RS485 mode. If still dead, use **GPS+GRIB + manual TWD/TWS** mode (read from the B&G display). |
| SD card corrupted | LOW (with spare) | Swap in the spare pre-imaged card. Marks/config are re-entered from the printed course card. |
| GRIB missing coverage or horizon | MEDIUM | Fall back to the ICON-EU/GFS backup file. Persist measured wind beyond the horizon. |
| Router flipping or slow | LOW | Freeze the route (button), use laylines-only mode, and increase hysteresis or step size from the settings page. |
| Tablet won't stay connected | LOW | Laptop as the backup display. Phone as a third display (same URL). |
| TWD jumps per tack | LOW | Adjust the upwash offset with the port/stbd TWD comparison. Disable bias correction. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---|---|---|
| 1 Wiring/polarity/termination | P-INGEST, P-COMMISSION | `fastnet-probe` verdict OK with more than 95 % valid checksums on the boat |
| 2 Transmitting on the bus | P-FOUND, P-INGEST | No write calls in ingest. ModemManager absent. `lsof` shows a single reader. |
| 3 Missing channels | P-INGEST, P-NAV | Channel inventory captured. Own true-wind path works with HDG absent (simulated). |
| 4 Magnetic vs true | P-FOUND, P-NAV, P-COMMISSION | Unit tests. Motoring HDG+var vs COG check below 3°. |
| 5 Jabuka anomaly | P-NAV, P-UI | Bias frozen inside the radius in replay. Badge shown. |
| 6 Upwash / TWD per tack | P-NAV | Replay with a synthetic tack-dependent AWA error; filter plus offset removes the jump. |
| 7 Optimistic polar | P-NAV, P-ROUTE | Efficiency factor and observed-angle laylines exist. "% polar" displayed. |
| 8 Conventions/units | P-FOUND | Golden tests pass (u/v, set, AWA sign, kn/m/s). |
| 9 GRIB coverage/horizon | P-GRIB, P-COMMISSION | Load-time assertion report for marks and time window |
| 10 eccodes on Pi / memory | P-FOUND, P-GRIB | Pi needs only numpy. Cropped `.npz` below 50 MB. |
| 11 Marks on land / coastline | P-ROUTE, P-UI | Route around Jabuka/Blitvenica valid with the side respected. No land crossings in tests. |
| 12 Route flipping | P-ROUTE | Replay: first-leg heading stable within 10° in steady conditions |
| 13 Bias poisoning | P-GRIB | Bias clamped, decays, shown, toggleable |
| 14 Time without RTC | P-HARDEN | Boot offline with a stale clock; UTC from GPS within 1 s; correct GRIB slice |
| 15 Power/SD | P-HARDEN, P-COMMISSION | Read-only root. 5× pull-the-plug test. `get_throttled` = 0 during engine start. Spare SD. |
| 16 Android Wi-Fi | P-UI, P-COMMISSION | Tablet stays connected for 2 h offline with mobile data off |
| 17 Wake lock over HTTP | P-UI | Screen stays on for 30 min unattended on the actual tablet |
| 18 State in browser | P-UI, P-HARDEN | Kill Chrome, reopen: marks and route intact |
| 19 Rules/SIs | P-COMMISSION | SIs read; RC answered; course-change drill under 30 s |

## Sources

- fastnet2ip README (libraries.io mirror, v3.3.1, Sep 2026): https://libraries.io/pypi/fastnet2ip (serial 28800 8O2, DTECH tested, no variation on the bus, no re-broadcast, replay pacing, HAT alarm note). MEDIUM (primary project doc).
- pyfastnet README and channel map: https://github.com/ghotihook/pyfastnet, https://github.com/ghotihook/pyfastnet/blob/main/docs/channel_map.md (channel IDs, M/T routing, 7-segment-only channels, queue semantics). MEDIUM (primary).
- fastnet2ip issues: https://github.com/ghotihook/fastnet2ip/issues (only one closed issue, about heel/trim). MEDIUM.
- B&G Fastnet bus info (Oppedijk, 2015, community reverse-engineering): https://oppedijk.azurewebsites.net/bandg/fastnet (wire colours, termination, frame/checksum). LOW-MEDIUM.
- Yacht Devices Fastnet article (Apr 2024): https://yachtd.com/news/b_and_g_fastnet.html (28800 for H2000/H3000, 11000 for Network instruments). MEDIUM.
- DTECH USB RS422/485 manual (manuals.plus): https://manuals.plus/asin/B0195ZD3P4 , https://manuals.plus/asin/B076WVFXN8 (FTDI chip, T/R+ = A+, T/R- = B-, common ground). MEDIUM.
- gpsd udev rules (FTDI match, disabled in Debian): https://sources.debian.org/src/gpsd/3.16-1~bpo8+1/gpsd.rules.in/ , https://github.com/koenkooi/meta-oe/blob/74c00dc15be76b40d1056ecc7f46acfb6e8f3cc5/meta-oe/recipes-navigation/gpsd/gpsd/60-gpsd.rules. MEDIUM.
- ModemManager vs USB GPS: https://bugzilla.redhat.com/show_bug.cgi?id=1023234 , https://bugs.gentoo.org/658836. MEDIUM.
- u-blox week-rollover notes: https://content.u-blox.com/sites/default/files/u-blox-GPS-WeekNumberRolloverWorkaround_IN_%28UBX-19039990%29.pdf , https://forum.openmarine.net/printthread.php?tid=3572. MEDIUM.
- eccodes / eccodeslib on PyPI (no armv7l wheels; aarch64 manylinux_2_28): https://pypi.org/project/eccodes/ , https://pypi.org/project/eccodeslib/#files. HIGH (fetched file listings).
- piwheels (32-bit only): https://piwheels.org/. MEDIUM.
- libweatherrouting README (`get_wind_at` m/s, `point_validity`/`line_validity`, `None` out of range): https://github.com/dakk/libweatherrouting. MEDIUM.
- Wake Lock secure context: https://www.w3.org/TR/2017/CR-wake-lock-20171214 , https://vaadin.com/docs/latest/flow/browser-apis/wake-lock-api , https://github.com/richtr/NoSleep.js , https://github.com/SEPIA-Framework/sepia-docs/wiki/Set-up-web-browser-to-treat-your-local-IP-as-secure-origin. MEDIUM.
- Android "no internet" Wi-Fi behaviour: https://forum.gl-inet.com/t/how-to-access-local-devices-when-no-internet-is-available/64078 , https://forum.libreelec.tv/thread/13638-wireless-access-point-android/ , https://forum.remotexy.com/viewtopic.php?id=912. MEDIUM (multiple independent reports).
- Pi undervoltage / SD / overlay: https://hackaday.com/2022/03/09/raspberry-pi-and-the-story-of-sd-card-corruption , https://d-central.tech/asic-troubleshooting/piaxe-12v-dc-undervoltage-rpi/. LOW-MEDIUM.
- Regata Jabuka NoR and equipment pages (fetched 2026-11-05): https://www.regata-jabuka.com/index.php/en/notice-of-race , https://www.regata-jabuka.com/index.php/en/equipement , https://www.regata-jabuka.com/index.php/en/weather-forecast (placeholder). HIGH for content as published.
- RRS 41 / Case 120: https://www.racingrulesofsailing.org/cases/120 , https://help.predictwind.com/en/articles/2884600-is-it-legal-to-use-predictwind-whilst-racing , https://www.racingrulesofsailing.org/posts/1840-rrs-41-c-allow-cloud-based-routing. MEDIUM.
- DHMZ ALADIN GRIB fee status: https://registri.nipp.hr/api/izvori/91/pdf/ , https://registri.nipp.hr/tcpdf/print/izvor_javno.php?id=91. MEDIUM.
- Bora forecast underestimation: https://www.ecmwf.int/sites/default/files/elibrary/2015/13440-recent-extreme-bora-wind-cases-croatia-ecmwf-forecast-evaluation-poster.pdf. MEDIUM.
- Jabuka magnetic island: https://www.amusingplanet.com/2015/07/jabuka-magnetic-island.html , https://en.wikipedia.org/wiki/Jabuka_(island) (43.0917 N, 15.4603 E). LOW-MEDIUM (qualitative only).
- Domain knowledge (not fetched, flagged in text): ICON-D2 grid bounds and horizon, Adriatic variation value, upwash/tack calibration practice, isochrone stability practice.

---
*Pitfalls research for: on-board offline sailing race routing and laylines (B&G Fastnet + Pi 3B + Android web UI)*
*Researched: 2026-11-05*
