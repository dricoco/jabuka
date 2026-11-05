# Architecture Research

**Domain:** On-board live sailing race navigation (instrument ingest, laylines, GRIB weather routing) on a Raspberry Pi 3B, with a tablet browser UI
**Researched:** 2026-11-05
**Confidence:** MEDIUM. The component boundaries, data flow and build order are engineering judgement drawn from how Signal K/OpenPlotter, fastnet2ip, OpenCPN weather_routing and libweatherrouting are built. Facts about third-party tools come from their READMEs and PyPI pages; the GSD seam rates those LOW, so check them during install. Router performance numbers on the Pi 3B are estimates and must be benchmarked by day 4.

---

## Standard Architecture

### How existing systems are structured (and what to take from each)

| System | Structure | Take | Leave |
|--------|-----------|------|-------|
| **Signal K / OpenPlotter** | Node.js server acts as the data hub. Providers (NMEA, N2K, plugins) feed one data model of dotted paths in SI units. Web apps (Freeboard-SK) subscribe over WebSocket. | The **path naming + SI units data model** (pyfastnet already emits Signal K paths). Using a hub that clients subscribe to over WebSocket. | The Node server itself. Its RAM/CPU is a burden on a 1 GB Pi 3B. Custom compute would be split between JS plugins and Python/numpy. It is also one more moving part to debug in 7 days. |
| **fastnet2ip / pyfastnet** | Small single-purpose bridge: serial → `FrameBuffer.add_to_buffer()` → decoded frames → UDP broadcast (NMEA 0183 port 2002 / N2K port 2000). Runs as a systemd unit with `BindsTo=` the serial device, `Restart=always`, `MemoryMax=128M`. Has `--file` replay of hex captures and `--live-data` console table. | **Ingest as a tiny, separate, restartable process that publishes over UDP.** Use pyfastnet directly as the decoder library. Keep `fastnet2ip --live-data` as the independent bus-test diagnostic. | Re-encoding to NMEA 0183 and decoding it again internally. That loses resolution and adds a second parser. |
| **OpenCPN weather_routing** | Routing runs on demand inside the GUI process. It builds isochrone polygons and merges them, and checks land with GSHHS crossing tests. | Concept: polar + GRIB + land check. | Polygon-merging isochrones (heavy, fragile). On-demand-only operation. Ignoring measured wind. |
| **libweatherrouting (GPL, pure Python)** | `Routing(router, polar, track, get_wind_at(t,lat,lon)->(twd,tws), start, point_validity, line_validity)`. Each parent tries 72 TWAs at 5°. Pruning keeps the best point per bearing-from-start bin. Single `nextwp`, no leg switching. Optional ThreadPool, which the GIL limits. No numpy. | The API shape: a pluggable wind function, point/line validity callbacks, step-by-step isochrones. Use it as a **reference oracle in tests**. | Using it as the live engine on a Pi 3B. Its per-candidate Python loops (about 26k polar+wind evaluations per step) would take seconds per step. |
| **Expedition / qtVlm / SailGrib (commercial)** | Instruments → damped "true wind" → laylines at instrument rate. Routing runs as a separate computation. Steering targets are expressed as TWA/BSP targets as well as heading. | Laylines from damped wind + polar targets at about 1 Hz. **Route legs carry target TWA, not just heading.** | — |

### System Overview

```
                    ┌──────────────── OFF-BOAT / AT DOCK (laptop) ─────────────────┐
                    │  jabuka-prep: GRIB → wind.npz, coastline → landmask.npy,      │
                    │  tiles → tiles.mbtiles, polar → polar.json  ==> "RACE PACK"   │
                    └──────────────────────────────┬───────────────────────────────┘
                                                   │ scp / USB stick (before start)
═══════════════════════════════════ RASPBERRY PI 3B ════════════════════════════════════
 HARDWARE        ┌─────────────────────┐          ┌─────────────────────┐
                 │ DTECH RS422/485 USB │          │ VK-162 u-blox USB   │
                 │ /dev/jabuka-fastnet │          │ /dev/jabuka-gps     │
                 └──────────┬──────────┘          └──────────┬──────────┘
 INGEST  (systemd template unit jabuka-ingest@{fastnet,gps}; one process per device)
                 ┌──────────▼──────────┐          ┌──────────▼──────────┐
                 │ ingest@fastnet      │          │ ingest@gps          │
                 │ serial→RAW LOG→     │          │ serial→RAW LOG→     │
                 │ pyfastnet decode→   │          │ NMEA parse (RMC/GGA │
                 │ normalize (SK path, │          │ /VTG)→normalize     │
                 │ SI, src, t_mono)    │          │                     │
                 └──────────┬──────────┘          └──────────┬──────────┘
                            │   UDP 127.0.0.1:47100 (JSON delta lines)  │
                            └──────────────────┬────────────────────────┘
 CORE  (systemd unit jabuka-core; one asyncio process)     ▲ also: jabuka-replay / jabuka-sim
                 ┌──────────────────────────────▼──────────────────────────────────┐
                 │ Bus listener → STATE STORE (latest value, t, src, quality/path) │
                 │   ├─ Clock (GPS-disciplined UTC | data-driven SimClock)         │
                 │   ├─ Source arbitration (fastnet > manual > GRIB-only)          │
                 │   ├─ Wind pipeline: mag→true, true-wind calc/check, damping     │
                 │   ├─ Bias estimator (measured − GRIB@boat, steady-sailing only) │
                 │   ├─ Nav: mark bearing/dist, laylines @1 Hz, route-following    │
                 │   ├─ Course/marks/config (atomic JSON persistence)              │
                 │   ├─ Router supervisor (timer + triggers, 1 job in flight)      │
                 │   ├─ Derived 1 Hz log (JSONL) for post-race polar learning      │
                 │   └─ Web: aiohttp — static UI, /tiles, REST /api/*, WS /ws      │
                 └──────────────┬───────────────────────────────▲──────────────────┘
                                │ RouteRequest (snapshot)       │ RouteResult
                 ┌──────────────▼───────────────────────────────┴──────────────────┐
                 │ ROUTER WORKER (child process, ProcessPoolExecutor(1), nice 10)  │
                 │ loads race pack once: wind.npz, landmask.npy, polar             │
                 │ numpy-vectorized isochrones, local planar frame (nm)            │
                 └──────────────────────────────────────────────────────────────────┘
 STORAGE   /var/lib/jabuka: config.json course.json state.json racepacks/ logs/{raw,derived}
═════════════════════════════════════════════════════════════════════════════════════════
                                │ Wi-Fi (Pi as AP), HTTP + WebSocket
                 ┌──────────────▼──────────────┐   ┌─────────────────────────────┐
                 │ Tablet browser: HELM VIEW   │   │ Laptop browser: same UI     │
                 │ map (offline tiles) + big   │   │ (+ optional OpenCPN via     │
                 │ numbers; renders only       │   │  NMEA 0183 TCP out, later)  │
                 └─────────────────────────────┘   └─────────────────────────────┘
```

**Data flows one way.** Hardware → ingest → core → browser. The only flows back are user edits (REST → core) and route results (worker → core). Ingest never depends on core, so core can crash or restart without losing raw recording.

### Component Responsibilities

| Component | Owns | Does NOT do | Typical implementation |
|-----------|------|-------------|------------------------|
| **ingest@fastnet** | Opening the serial port (28800 8O2), reconnecting on unplug, writing raw bytes to the log first, decoding with pyfastnet, normalizing to `{path, value(SI), src, t_mono}`, counting decode/checksum errors | Any maths beyond unit normalization. No state. No UI. | Python + pyserial + pyfastnet, about 200 LOC |
| **ingest@gps** | Same for NMEA 0183 from the u-blox (RMC/GGA/VTG; GSA for fix quality). Publishes `navigation.position`, COG/SOG, and the **UTC time from RMC** | Same | Python + pyserial + pynmea2 (or a hand parser) |
| **core: state store** | Latest value per path with timestamp, source and quality. Staleness flags (for example, wind stale after 5 s). Plain dict, single-threaded asyncio, no locks. | Persistence of high-rate data (that goes to the logs) | dict of dataclasses |
| **core: clock** | One source of "now" in UTC for all domain logic. Live mode: GPS UTC + monotonic offset. Sim mode: driven by message timestamps. | — | ~50 LOC; see Pattern 3 |
| **core: wind pipeline** | Magnetic→true conversion, B&G true wind vs own true-wind calculation from AWA/AWS/BSP (fallback and cross-check), circular damping, maneuver detection | Routing | numpy-free scalar maths |
| **core: bias estimator** | Δdirection (circular) and speed ratio between measured ground wind and GRIB at the boat, averaged over about 10 min while sailing steadily. Includes a confidence value and the observation time. | Applying the bias to the field (the router does that from parameters) | EMA on vector components |
| **core: nav / laylines** | Bearing and distance to the next mark, laylines (both tacks/gybes) at 1 Hz from damped wind + polar targets + current + leeway, route following (XTE, target TWA/heading from the current route leg) | Long-horizon optimization | Scalar maths + shared `polar` module |
| **core: course** | Ordered marks with rounding side, editable, versioned. Persisted atomically. Generates rounding waypoints for the router. | — | JSON file + version counter |
| **core: router supervisor** | When to route (timer + triggers), building the snapshot `RouteRequest`, at most one job running plus one pending, timeouts, recreating a crashed worker, keeping the last good route and its age | The routing maths | `asyncio` + `concurrent.futures.ProcessPoolExecutor(max_workers=1)` |
| **router worker** | `route(RouteRequest) -> RouteResult`, a **pure function**. Wind field = GRIB (u, v interpolated in time and space) × bias decay. Polar lookup, land mask, rounding constraints, multi-leg. | I/O beyond loading the race pack once in its initializer | numpy; see Pattern 5 |
| **web** | Serving the static UI and tiles. WS push of state (1–2 Hz), laylines (1 Hz), route/course (on change). REST for edits and status. | Computation; the browser only renders | aiohttp (single process with core) |
| **browser UI** | Helm view (big numbers), map with boat, route, laylines and marks. Mark entry by tap. Shows data staleness and route age clearly. | Any navigation maths (every client must show the same numbers) | Static HTML/JS + Leaflet (or MapLibre) |
| **jabuka-prep (laptop)** | Building the race pack: crop GRIBs to the race bbox, convert to `wind.npz` (t, lat, lon, u, v); rasterize OSM land polygons + manual hazards (Plić Sestre shoal) into `landmask.npy`; package tiles; normalize the polar; validate. | Running on the boat | Python + eccodes/xarray + shapely/rasterio |
| **jabuka-replay / jabuka-sim** | Replaying raw logs into a pty (byte level) or into the UDP bus (message level). Synthetic boat sailing the polar in GRIB wind with noise, bias and faults, optionally closed-loop on the router's course to steer. | — | Python; see "Replay / Simulator" |

---

## Recommended Project Structure

```
jabuka/
├── jabuka/
│   ├── common/            # shared by every process; no heavy imports
│   │   ├── units.py       # SI <-> kn/deg; angle wrap helpers (wrap360, wrap180)
│   │   ├── geo.py         # local tangent-plane projection (nm), bearing/distance
│   │   ├── messages.py    # bus message schema (path, v, src, t_mono, t_utc?)
│   │   ├── clock.py       # LiveClock (GPS-disciplined) / SimClock
│   │   └── atomicio.py    # atomic JSON write + .bak fallback
│   ├── polar/             # parse OpenCPN/Expedition/CSV; tables; VMG targets; efficiency
│   ├── ingest/            # sources (serial|pty|file), decoders (fastnet, nmea0183), raw recorder, UDP publisher
│   ├── core/              # state store, wind pipeline, bias, nav/laylines, course, router supervisor, persistence
│   ├── web/               # aiohttp app: static, tiles, REST, WebSocket
│   ├── router/            # PURE: windfield.py, landmask.py, rounding.py, engine.py, types.py
│   ├── racepack/          # jabuka-prep CLI (runs on laptop; heavy deps optional on Pi)
│   └── sim/               # replay (pty + UDP), synthetic boat, fault injection
├── ui/                    # static helm/map SPA (vendored Leaflet: no CDN, it's offline)
├── deploy/                # systemd units, udev rules, sudoers snippet, install.sh, bus-test checklist
├── tests/                 # decoder tests (pyfastnet captures), layline analytic tests, router golden tests
└── data/dev-racepack/     # small sample pack for development and CI
```

### Structure Rationale

- **`router/` is pure and has no dependency on `core/`.** It can be built and tested on a laptop from day 1, in parallel with the hardware path. It touches the rest of the system through exactly one boundary: `RouteRequest -> RouteResult`.
- **`polar/` is shared by `core/` (laylines) and `router/`.** Laylines and the route must use the same polar, efficiency factor and target angles. If they don't, the helm sees laylines that contradict the route.
- **`common/` holds angles, units and the clock.** Most bugs in this domain are unit, true/magnetic and wrap-around bugs. One tested module for these, used everywhere.
- **`racepack/` is separate** so heavy GRIB tooling (eccodes) never has to work on the Pi. The Pi only `np.load`s arrays.

---

## Architectural Patterns

### Pattern 1: Single-purpose ingest processes + localhost UDP bus

**What:** One small process per physical device (systemd template `jabuka-ingest@.service`). Each one writes raw bytes to disk *before* decoding, then publishes normalized messages as JSON lines to `127.0.0.1:47100`. The core subscribes. Replay and sim tools publish to the same port.
**When to use:** Always here. It isolates the untested Fastnet path from everything else. A decoder crash on garbage bytes takes down only `ingest@fastnet`, and systemd restarts it in 2 s while GPS, UI and routing keep running.
**Trade-offs:** A few ms of latency and JSON overhead, which is irrelevant at ≤10 Hz. Loopback UDP is effectively lossless at these rates. Either side restarts independently with no connection state.

```python
# ingest message (one UDP datagram, may batch several values)
{"src": "fastnet", "t_mono": 81234.512, "t_utc": null,
 "values": [{"path": "environment.wind.angleApparent", "v": -0.6109},
            {"path": "navigation.speedThroughWater", "v": 3.37}]}
# conventions: SI units (rad, m/s, m); directions are "from", 0..2π;
# relative angles (AWA/TWA) −π..π, NEGATIVE = PORT; true/magnetic explicit in path
```

### Pattern 2: Raw-first recording at the lowest layer

**What:** Every byte read from a serial port is appended to an hourly-rotated text log before any parsing, for example `t_mono t_wall HEXBYTES` per read chunk for Fastnet and `t_mono t_wall $GPRMC,...` for GPS.
**When to use:** From the first minute on the boat (12 Nov). If decoding is wrong on race day (true/magnetic layout, unexpected channel IDs, wrong wiring polarity), the raw capture lets you fix the decoder that night and re-verify by replay.
**Trade-offs:** Disk. Fastnet at 28800 baud 8O2 is at most about 2400 B/s, so hex text is about 18 MB/h worst case, ≤650 MB for 36 h. Gzip the previous hour at nice 19. GPS is about 2 MB/h. This is fine on a 32 GB card.

### Pattern 3: Injected clock (domain time ≠ wall time)

**What:** All time-dependent logic goes through `clock.now_utc()`: GRIB time interpolation, staleness checks, damping time constants, bias decay, router cadence, ETA. Never call `time.time()` or `datetime.now()` in domain code.
**Why critical here:** (1) **The Pi 3B has no RTC.** It boots offline with fake-hwclock time, which can be hours or days off, so GRIB lookups would silently use the wrong forecast hour. (2) Replay at 10–60× must make the core believe time runs at 10–60×.

```python
class LiveClock:
    """UTC = last GPS RMC time + (monotonic now - monotonic at that fix)."""
    def on_gps_time(self, utc: datetime, t_mono: float): self._ref = (utc, t_mono)
    def now_utc(self) -> datetime | None:          # None => UNSYNCED: block routing, warn UI
        if not self._ref: return None
        utc, m = self._ref
        return utc + timedelta(seconds=time.monotonic() - m)

class SimClock:
    """Driven by t_utc carried in replay/sim messages; scheduler sleeps are scaled."""
```

Also set the system clock once from GPS at the first fix (a sudoers-whitelisted `date -s`) so journal and log timestamps make sense. The domain logic does not depend on this.

### Pattern 4: Compute on the server, render on the client

**What:** The core computes every number the helm sees (laylines, target TWA/BSP/heading, DTW/TTW, route) and pushes it over WS. The browser renders and sends edits only.
**Trade-offs:** If the Pi dies, the UI dies. That is acceptable because the B&G displays remain the primary instruments. In exchange, the tablet and laptop always agree, the browser's own clock is irrelevant, and tablet performance does not matter.
**WS payloads:** `state` at 1–2 Hz (compact: about 30 numbers + staleness flags), `laylines` at 1 Hz, `route` / `course` / `racepack` only on change (decimate isochrones before sending), `alerts` on change. The client shows "DATA STALE x s" and "ROUTE AGE n min" prominently.

### Pattern 5: Vectorized isochrone router in a local planar frame

**What:** Reimplement the isochrone method (libweatherrouting / Hagiwara style) in numpy:
- **Frame:** Project everything to a local tangent plane in nautical miles, centered on the race area (about 45 × 45 nm; x = Δlon·60·cos φ0, y = Δlat·60). Error is negligible at this scale. All geometry becomes vector arithmetic, with no trig on lat/lon per candidate.
- **Wind field:** `wind.npz` holds `u[t, y, x]` and `v[t, y, x]` (m/s), already cropped and regridded to the local frame. Bilinear in space and linear in time on **u/v components** (never on direction/speed), vectorized for all parents at once. The bias is applied on top (Pattern 6). Wind is sampled once per parent per step, not per candidate.
- **Expansion:** For N parents × H headings (TWA grid at 5° plus the exact optimal up/down VMG angles from the polar for each parent's TWS, so beats sit on target angles), BSP = polar(TWS, |TWA|) × efficiency × wave factor. Displacement = BSP·dt·unit(heading) + current·dt. Apply a tack/gybe penalty (config, about 20–30 s of distance lost) when the TWA sign flips relative to the parent.
- **Pruning:** Bin by bearing from the leg origin into 1–2° sectors, restricted to ±100° of the origin→waypoint bearing. Keep the farthest-from-origin point per sector. Drop children whose distance to the waypoint exceeds the parent's distance plus a slack. This yields ≤ about 200 parents per step.
- **Land:** `landmask.npy` is a boolean raster at 50–100 m in the same planar frame, built from OSM land polygons plus hand-drawn hazards (Plić Sestre shoal, other shoals). It is dilated by a safety margin (for example 150 m). Check each candidate segment by sampling K points along it (K ≈ segment length / cell size) with one fancy-indexing gather. **No shapely in the hot loop.**
- **Arrival:** A leg ends when any candidate segment passes within the arrival radius of the current rounding waypoint. Backtrack via `parent_idx` arrays.
- **Step schedule:** dt = 3 min for the first 30 min, 6 min up to 3 h, 15 min beyond. Near-term resolution matters for the helm; far-term matters only for ETA.

**Budget (estimate, LOW confidence, benchmark on Pi by day 4):** 200 × 70 = 14k candidates per step, about 30 numpy ops each, plus about 100k mask gathers. That is roughly 10–40 ms per step on a Pi 3B. A full remaining course (about 100 nm, about 100 steps) takes ≈1–5 s, comfortably inside a 5-minute cadence. If it is 10× worse, reduce H (10° grid plus targets) and sectors.

```python
# core of one isochrone step (shape annotations: N parents, H headings)
tws, twd = wind.sample(t, px, py)                         # (N,), (N,)  bias already applied
twa = twa_grid[None, :] * side                            # (N,H) incl. per-parent VMG targets
hdg = twd[:, None] + twa                                  # true heading, rad
bsp = polar.speed(tws[:, None], np.abs(twa)) * eff        # (N,H)
d   = bsp * dt - tack_penalty * (np.sign(twa) != parent_side[:, None]) * bsp
cx  = px[:, None] + d * np.sin(hdg) + cur_x * dt          # child positions (nm)
cy  = py[:, None] + d * np.cos(hdg) + cur_y * dt
ok  = landmask.segments_clear(px, py, cx, cy)             # vectorized raster sampling
# -> flatten, sector-bin by atan2 from origin, keep max range per bin, record parent_idx
```

### Pattern 6: Wind bias = measured − GRIB at boat, blended with time decay

**What:**
1. **Measure (core, about 1 Hz):** Measured *true, ground-referenced* wind. Use B&G TWD/TWS, converted to true north if the instrument layout is magnetic, plus the current vector if it is known. Compare with the GRIB interpolated at (now, boat position).
2. **Gate:** Only accumulate while sailing steadily: |rate of turn| < about 3°/s for > 30 s, BSP > 2 kn, all inputs fresh, not within 60 s of a tack or gybe. Measured TWD swings during maneuvers because of heading/wind-sensor lag and upwash, and would poison the bias.
3. **Estimate:** EMA with τ ≈ 10 min of Δdir (circular difference, wrapped ±180°) and speed **ratio** (clamped 0.5–2.0). The ratio absorbs the masthead (about 17 m) vs GRIB 10 m height difference. Do not also apply a separate height correction. Publish `{d_dir, k_speed, t_obs, pos_obs, n_samples, confidence}`.
4. **Apply (router):** `W(t, x) = rotate(GRIB(t, x), w·d_dir) · (1 + w·(k_speed − 1))`, with `w = exp(−(t − t_obs)/τ_t)`, τ_t default 2 h (configurable; at 6 h the weight is about 5%). An optional spatial term `exp(−dist(x, pos_obs)/τ_d)` can be added later. The race area is small, so start with time decay only.
5. **Manual mode:** A TWD/TWS read off the B&G displays and entered in the UI produces the same observation record with `src=manual`. It is the same code path, which keeps the degraded mode cheap.

Commercial tools document time-shifting GRIBs and model averaging. No primary source confirmed an exact documented "decaying measured-wind blend" in Expedition, so **the decay constant is a tuning parameter (LOW confidence)**. Show GRIB vs measured on the debug page during the first race hours.

### Pattern 7: Route results carry target TWA; the core re-derives heading live

**What:** Each route segment stores `(t, x, y, heading_true, twa, tack, tws, bsp)`. Between reroutes, the core finds the route segment nearest ahead of the boat and displays **target TWA and tack** (primary) and *heading = TWD_now + TWA_target* (secondary), along with XTE.
**Why:** The route is 0–5 min old and was computed from an older position. In a shift, steering the old heading is wrong, while steering the target TWA stays right. This matches how racing navigators brief the helm.

---

## Data Flow

### Update rates and filtering

| Stream | Native rate | Core processing | Pushed to UI |
|--------|-------------|-----------------|--------------|
| Fastnet AWA/AWS/BSP/HDG/TWS/TWD | about 1–4 Hz per channel (bus dependent; verify on boat) | validity + staleness (stale > 5 s), circular EMA | 1–2 Hz |
| GPS position/COG/SOG/UTC | 1 Hz (u-blox default) | clock discipline, COG/SOG EMA τ ≈ 3 s | 1–2 Hz |
| Hercules set/drift | slow, already heavily averaged by B&G | EMA τ ≈ 5 min (layline current) | 1 Hz |
| Laylines + nav to mark | computed at 1 Hz | from damped values | 1 Hz |
| Wind bias | updated at 1 Hz, EMA τ ≈ 10 min | gated by steady sailing | on change (≥ 1°/2%) |
| Route | every 5 min + triggers | worker job ≈ 1–5 s | on completion |

**Damping time constants (defaults, all configurable, time-based alpha `α = 1 − exp(−Δt/τ)`):** heading 1 s, BSP 3 s, TWS 10 s, TWD 20 s (display/laylines), bias 10 min. Damp angles as **vector components** (sin/cos weighted by speed for wind), never as raw degrees. B&G applies its own damping already (set on the instrument), so keep these modest.

### True wind, heading and variation

1. **Prefer B&G's own TWS/TWA/TWD.** Hercules applies its calibration tables (upwash, heel, mast twist). pyfastnet maps TWD (0x6D), Heading (0x49) and Tidal Set (0x84) to `...Magnetic` or `...True` **based on the instrument's display layout**. The bus carries no variation, so the core must know which one it is getting.
2. **Variation:** Use a config value for the race area (about +4.5° to +5° E near Šibenik in 2026; **verify with the NOAA/WMM calculator**). Optionally compute it with WMM at the boat position. Apply it once in the wind pipeline: everything downstream is **true**.
3. **Own true-wind calculation (fallback + cross-check):** `TWS = √(AWS² + BSP² − 2·AWS·BSP·cos AWA)`, `TWA = atan2(AWS·sin AWA, AWS·cos AWA − BSP)`, `TWD = HDG_true + TWA`. Show both on the debug page. A persistent disagreement of more than about 10° means a true/magnetic or calibration issue.
4. **Ground vs water wind:** GRIB wind is ground-referenced. With known current `c`, ground wind = water wind + c (vector). Adriatic currents are usually weak, so this is optional, but put it in the code path so that enabling current changes one input.
5. **Variation is already applied on the true side,** so GRIB (true, "from") and measured wind are compared in the same frame.

### Key data flows

1. **Live instrument flow:** serial → ingest (raw log, decode, normalize) → UDP → core state → wind pipeline → laylines and nav → WS → helm. Latency well under 1 s.
2. **Routing flow:** timer or trigger → supervisor snapshots `{t0 = clock.now_utc(), boat pos, remaining rounding waypoints, bias params, efficiency, toggles}` → worker `route()` → `RouteResult` → core stores it as the current route (and persists it to `state.json`) → WS `route` → route following updates target TWA at 1 Hz.
   - Triggers: course edited, race pack or GRIB changed, manual wind changed, bias moved > 5° or > 15%, boat > 0.5 nm off route, previous job failed. Coalesce: one job running, one pending (latest snapshot wins).
   - Routing is **blocked while the clock is UNSYNCED** or when no race pack is loaded. The UI then says why.
3. **Edit flow:** tap mark on map → `PUT /api/course {base_version, marks[{lat, lon, name, rounding: port|stbd|none}]}` → core validates, writes atomically, bumps the version, broadcasts the course, triggers a reroute.
4. **Degraded-mode arbitration (core, per quantity):** wind: `fastnet (fresh) > manual (age-weighted) > GRIB-only`. Position/COG/SOG: `gps > fastnet GPS channels`. BSP: `fastnet > SOG ± current`. The UI shows the active source per quantity. GPS + GRIB-only still gives routing and GRIB-based laylines.

### Laylines (1 Hz, core)

Inputs: damped true TWD and TWS, polar targets (up/down VMG TWA and BSP at that TWS) × efficiency, leeway (config, upwind only), current (Hercules set/drift, file or none).
- Mode: if |TWD − BRG_to_mark| < target upwind TWA, the boat is **beating**. If it is > the target downwind TWA, it is **running**. Otherwise it is **reaching**: draw the direct course and no laylines.
- For each tack: ground track = water velocity at (TWD ± target TWA, plus leeway) + current. The layline is the line through the mark with the reverse of that ground track.
- Outputs: two layline bearings, distance and time to each layline from the boat, "ON LAYLINE" flag, time to mark on each tack.
- These are mark-anchored *instantaneous* laylines. Route-based laylines (using forecast wind at arrival time) come from the router and are drawn separately. Never mix them silently.

---

## Router design details

| Concern | Decision |
|---------|----------|
| Engine | Own numpy isochrone engine (Pattern 5). libweatherrouting is used as a test oracle only. |
| Process | `ProcessPoolExecutor(max_workers=1, mp_context=forkserver or spawn, initializer=load_racepack)`. The initializer calls `os.nice(10)`. Numpy imports and race-pack loading happen once. On `BrokenProcessPool`, recreate it and keep the last good route with its age. |
| Timeout | Hard 60 s per job. On timeout, kill and recreate the pool and return the best partial (closest to the waypoint), flagged. |
| Multi-leg | Sequential, leg by leg: the arrival point and time of leg k start leg k+1. Route the whole remaining course for ETAs; the UI emphasizes the current leg. |
| Mark rounding sides | `course.rounding_waypoints()` turns each mark into 1–3 waypoints on a small circle (radius about 0.1–0.2 nm) around the mark. The sweep goes from the incoming to the outgoing bearing, in the direction set by the rounding side (port = counter-clockwise). One point per about 90° of sweep. This handles normal turns, hairpins (Jabuka) and wrong-way loops. For island marks (Jabuka, Blitvenica), the land mask prevents cutting through, and the circle radius must clear the coastline (radius = island extent + margin; set per mark). |
| Land | Raster mask from OSM land polygons (osmdata.openstreetmap.de land-polygons, cropped) + manual hazard polygons, dilated by a safety margin. Built on the laptop. On the Pi it is only `np.load`. |
| GRIB out of range | Beyond the last forecast hour, hold the last field (persistence) and flag it. Before the first hour, use the first field. If the boat is outside the grid, fail with a clear message. |
| Optional current/waves | Current: `current.npz` (u, v) with the same sampling code. Waves: a speed factor `f(Hs, TWA)` from `waves.npz`, or `f(TWS)` if there is no file. Both are off by default and are just extra multipliers or vectors in the expansion step. |
| Output size | Send the route polyline (≤ a few hundred points) + ETAs to the UI. Isochrones are decimated to every 3rd one and capped in points, and are sent only if the UI asks. |

---

## Replay / Simulator Architecture

Three injection levels, all feeding the same core:

```
L0 bytes:     raw log ──jabuka-replay --pty──▶ /dev/pts/N ──▶ ingest@fastnet|gps ──▶ UDP ──▶ core
L1 messages:  bus log  ──jabuka-replay --udp──────────────────────────────────────▶ UDP ──▶ core
L2 synthetic: jabuka-sim (polar × racepack wind + bias/noise/shifts/current, faults)  ─▶ UDP ──▶ core
                    ▲                                                                       │
                    └──────── closed loop: follows core's target TWA/heading (autopilot) ◀──┘
```

- **L0** exercises the real serial and decoder code. The ingest opens a pty path given in config instead of `/dev/jabuka-fastnet`. Until there is a capture from this boat, seed it with the **captures shipped in the pyfastnet repo** (`captures/*.txt`, used by `examples/replay_capture.py`). After 12 Nov, replay the boat's own capture. A pty ignores baud and parity, which is fine.
- **L1** gives deterministic core/UI/router tests and quick bug reproduction. The core can optionally log every bus message it receives.
- **L2** is the only way to test routing, bias and laylines end to end before the race, and to run a **36 h soak at 60×** (about 36 min) to catch leaks, log rotation bugs and timer drift. Fault injection: Fastnet silent for 10 min, GPS loss, NaN or garbage values, device unplug (pty closed), true/magnetic flipped, clock jump.
- **Time scaling:** Replay and sim messages carry `t_utc`, and the core runs `SimClock` (Pattern 3). The scheduler's sleeps are divided by the speed factor. At 60×, the 5-min reroute becomes 5 s of real time. If routing takes about 3 s, cap the sim at 20–30× for routing tests.
- **Golden tests:** In a uniform 10 kn northerly with a mark 5 nm directly upwind, the router must produce a two-tack beat whose tack points lie on the analytic laylines from the layline module. This cross-checks polar, laylines and router in one test.

---

## Persistence (power-loss robust)

| Data | Format | Write strategy |
|------|--------|----------------|
| `config.json`, `course.json`, `state.json` (last bias, last good route, manual wind, active race pack) | JSON | **Atomic:** write `*.tmp` → `fsync` → `os.replace` → `fsync(dir)`. Keep the previous file as `.bak`. On load, if parsing fails use `.bak`, and if that fails use defaults, then raise an alert. |
| Raw logs (`logs/raw/YYYYMMDD-HH-{fastnet,gps}.log`) | timestamped text lines | append, flush every 1 s, `fsync` every 10 s, rotate hourly, gzip the old hour. A torn last line is tolerated by the readers. |
| Derived log (`logs/derived/...-1hz.jsonl`) | JSONL, 1 Hz snapshot of all damped and derived values | same as raw. This is the input for post-race polar learning. |
| Race packs | read-only files | written only at the dock |

System level:
- ext4 `noatime`. Swap on zram, not on the SD card. Use a high-endurance SD card.
- **Carry a cloned spare SD card.** This is the cheapest and strongest mitigation.
- Root overlayfs (raspi-config) with `/var/lib/jabuka` on a USB stick is **optional and only after feature freeze**. It complicates debugging, and one community report says it silently didn't apply.
- Stable device names via udev rules (`/dev/jabuka-fastnet`, `/dev/jabuka-gps` from VID:PID or `/dev/serial/by-id`). Never rely on `ttyUSB0`/`ttyACM0` ordering.
- systemd: `Restart=always`, `RestartSec=2`. The core uses `WatchdogSec=30` with an `sd_notify` heartbeat from the event loop, so a hung loop gets restarted. Set `RuntimeWatchdogSec=15` in `system.conf` to arm the BCM2835 hardware watchdog (reboots a hung kernel). Give ingest `OOMScoreAdjust=-700` and the router worker the highest OOM score, so the kernel kills routing first.

---

## Scaling Considerations (resource budget, not users)

| Resource | Budget on Pi 3B (1 GB) | Notes |
|----------|------------------------|-------|
| ingest@fastnet / ingest@gps | ~25–40 MB RSS each, < 5% CPU | pyserial + pyfastnet only. Don't import numpy here. |
| core + web | ~60–100 MB, 5–15% of one core | 1–3 WS clients |
| router worker | ~100–200 MB (numpy + arrays; landmask ≈ 2–9 MB), 100% of one core for 1–5 s every 5 min | `nice 10`; the other 3 cores keep ingest and core responsive |
| Total | < 450 MB | leaves headroom; no desktop, use OS Lite |

### Bottlenecks (in the order they will appear)

1. **Router compute.** Fix by reducing the heading grid, sector count and far-horizon step, or by routing only the current and next leg.
2. **Wi-Fi/WS payload to the tablet.** Send the route only on change, decimate isochrones, and keep `state` compact.
3. **SD write load and wear.** Keep raw logs hourly and compressed, keep the derived log at 1 Hz, and never write JSON per tick.

---

## Anti-Patterns

### Anti-Pattern 1: Running the router (or any heavy compute) in the web/ingest process
**What people do:** Call the router from an aiohttp handler or a thread.
**Why it's wrong:** The GIL plus a slow Pi 3B core freezes WS pushes and laylines for seconds, and a router crash takes down the UI.
**Do this instead:** A separate worker process with one job in flight, a timeout, and recreation on crash (Pattern 5 + supervisor).

### Anti-Pattern 2: Using wall-clock time
**What people do:** `datetime.now()` for GRIB lookups and timers.
**Why it's wrong:** With no RTC and no internet, the boot time is wrong, so the wrong forecast hour gets used without any error. Replay at speed also breaks.
**Do this instead:** An injected Clock (Pattern 3). Block routing until GPS time is valid.

### Anti-Pattern 3: Assuming true/magnetic from the channel name
**What people do:** Treat Fastnet heading and TWD as true.
**Why it's wrong:** pyfastnet picks Magnetic or True from the instrument's layout, and there is no variation on the bus. A 4–5° error goes straight into bias, laylines and route.
**Do this instead:** Normalize explicitly in the wind pipeline. Verify on the boat by comparing against the B&G display and COG. Show both "B&G TW" and "computed TW" on the debug page.

### Anti-Pattern 4: Adopting the full Signal K server stack for a 7-day build
**What people do:** Install OpenPlotter + Signal K + plugins and write routing as a plugin.
**Why it's wrong:** More RAM on a 1 GB Pi, a JS/Python split, and many moving parts to debug blind before a bus that can only be tested on race day.
**Do this instead:** Reuse the Signal K **path names and SI units** (already emitted by pyfastnet). Keep the option to add an SK or NMEA 0183 TCP output later for OpenCPN on a laptop.

### Anti-Pattern 5: Shapely or polygon intersection per candidate segment
**What people do:** `line.intersects(coast)` for each of about 14k candidates per step.
**Why it's wrong:** Far too slow on a Pi 3B, even with prepared geometries.
**Do this instead:** A pre-rasterized, dilated land mask with vectorized segment sampling (Pattern 5).

### Anti-Pattern 6: Estimating bias from instantaneous values, including maneuvers
**Why it's wrong:** TWD swings 10–30° through a tack because of sensor and heading lag, so the bias chases noise and the route jumps on every reroute.
**Do this instead:** Gate on steady sailing, use a long EMA, and require a minimum change before triggering a reroute (Pattern 6).

### Anti-Pattern 7: Logging only decoded values
**Why it's wrong:** If the decoder or mapping is wrong on race day, the evidence is lost.
**Do this instead:** Write raw bytes first (Pattern 2), and keep the 1 Hz derived log separately.

### Anti-Pattern 8: Writing JSON state in place
**Why it's wrong:** A power cut between truncate and write leaves an empty course file mid-race.
**Do this instead:** Atomic replace + `.bak` fallback.

### Anti-Pattern 9: Navigation maths in the browser
**Why it's wrong:** Two clients can disagree, the tablet's clock and CPU become dependencies, and it is harder to test.
**Do this instead:** The server computes everything and the client only renders (Pattern 4).

---

## Integration Points

### External

| Service / Data | Integration pattern | Notes |
|----------------|---------------------|-------|
| B&G Hercules Fastnet | DTECH RS422/485 USB → pyserial 28800 8O2 → `pyfastnet.FrameBuffer.add_to_buffer()` / `get_complete_frames()` → Signal K paths in SI | Requires pyfastnet ≥3.x (3.2.1 seen on PyPI). Independent diagnostic: `fastnet2ip --serial … --live-data`. Wiring: A/B polarity swapped shows up as checksum errors, so display the error counter. |
| VK-162 GPS | `/dev/ttyACM0` (cdc_acm) NMEA 0183 at 1 Hz | RMC gives UTC for the clock. Use GSA/GGA for fix quality. |
| GRIB (ICON-EU/D2, ALADIN, organizer) | Laptop: eccodes/xarray → crop → `wind.npz` (u10, v10, times UTC) | Organizer format unknown, so the prep tool must report its grid, times and coverage. |
| Coastline | OSM land polygons (osmdata.openstreetmap.de) cropped to the race bbox, plus manual hazard polygons → rasterized | Check that shoals and rocks near Plić Sestre and Blitvenica are covered by the manual hazards. |
| Map tiles | Pre-packaged on the laptop (MBTiles or a z/x/y folder; PMTiles if vector) → served by the core | Bulk download from tile.openstreetmap.org is against OSM policy, so the tile source is a STACK decision. |
| Polar | OpenCPN / Expedition / CSV → `polar.json` (TWS × TWA → BSP + VMG targets) | Efficiency factor is user-tunable and shared by laylines and the router. |
| OpenCPN on a laptop (optional, later) | NMEA 0183 over TCP 10110 from the core | Free fallback chart-plotter view; not in the MVP. |

### Internal boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| ingest ↔ core | UDP JSON lines, 127.0.0.1:47100, fire-and-forget | Either side restarts independently. Replay and sim use the same port. |
| core ↔ router worker | `ProcessPoolExecutor` future: pickled `RouteRequest` / `RouteResult` dataclasses | The router is pure, and the same function runs in tests on the laptop. |
| core ↔ browser | WS `/ws` (server push), REST `/api/course`, `/api/wind/manual`, `/api/config`, `/api/status`, `/api/route/trigger`, `/api/racepack` | The course uses `base_version` optimistic concurrency (two tablets). |
| laptop ↔ Pi | race pack directory over scp/USB; `jabuka-prep validate` before departure | The Pi never needs eccodes. |

---

## Suggested Build Order (7 days, race-day bus test must be low-risk)

**Principle:** The hardware path (Fastnet) cannot be tested until 12 Nov, so build its **diagnostic and recording tools first**, and build everything else so it works **without** Fastnet. The router is pure and can be developed in parallel. A helm MVP without routing (laylines + marks + map) must exist early as a fallback.

```
Day:      1      2      3      4      5      6      7   | 12-13 Nov (boat)
Track A: [P1 backbone+bus kit][P2 helm MVP     ][P4 hardening/soak][freeze] | bus test → go
Track B:        [P3a racepack prep][P3b router lib][P3c integrate]         |
                                     ▲ Pi benchmark gate (day 4)
```

### Phase 1: Data backbone and bus-test kit (FIRST, blocks everything)
Pi OS Lite 64-bit, SSH, Wi-Fi AP, udev names. `common/` (units, angles, messages, clock, atomic IO). `ingest@gps` and `ingest@fastnet` with raw recording. L0 replay via pty using pyfastnet's sample captures. L1 UDP replay. Core state store + WS + a **debug page that lists every path with value, source, age and error counters**. systemd units with restart and watchdog.
*Exit:* replaying a pyfastnet capture shows decoded values on the tablet. GPS live on the desk. Unplugging and replugging recovers. That is the race-day bus test kit.
*Avoids:* finding on 12 Nov that nothing can be seen or recorded.

### Phase 2: Helm MVP without routing
`polar/` (load, targets, efficiency). Wind pipeline (variation, true-wind cross-check, damping). Laylines and nav to mark. Course/marks with tap entry and rounding sides (atomic persistence). Offline map and helm view. Manual wind entry and source arbitration (degraded mode). L2 synthetic sim (open loop).
*Exit:* a sim boat sails toward tapped marks, laylines are correct against the analytic test, and the helm view is readable at night.
*Why before routing:* this delivers most of the core value on its own and is the fallback if routing slips.

### Phase 3: Weather routing (Track B starts day 2 in parallel; integrates day 4–5)
3a race-pack prep (GRIB → npz, land mask + hazards, validation). 3b pure numpy router with multi-leg, rounding waypoints and land, golden tests, oracle comparison with libweatherrouting, and a **Pi 3B benchmark by day 4**. 3c supervisor, triggers, bias estimator, route display, route following (target TWA).
*Exit:* closed-loop sim at 20× completes Vodice → Plić Sestre → Jabuka → Blitvenica → Vodice, with no route crossing land and the correct rounding sides.

### Phase 4: Hardening and race readiness
Fault-injection runs. 36 h soak at 60×. Power-pull tests (course and config survive). Memory/OOM settings. Clock-unsynced behavior. On-boat checklist (bytes arriving → error counter ≈ 0 → values match B&G displays → true/magnetic confirmed → raw recording running). Spare SD clone. Load the final race pack with the latest GRIBs. Optional current and waves only if time remains.
*Exit:* feature freeze by day 7. On 12 Nov, only configuration fixes from the bus test (layout true/magnetic, channel mapping), verified by replaying the capture that night.

**Critical path:** P1 → P2 → P4. P3 must not block P2/P4. If the day-4 Pi benchmark fails, fall back to routing only the current leg with coarser settings rather than delaying hardening.

**Research flags:**
- P1: confirm DTECH adapter wiring for Fastnet (RS485 2-wire vs RS422) and which channels the Hercules 2000/390 actually broadcasts (needs a capture from the boat).
- P3: needs deeper research on the organizer GRIB format, the tile source and licensing, and bias decay constants.
- P2/P4: standard patterns.

---

## Sources

- fastnet2ip README (GitHub ghotihook/fastnet2ip): CLI, UDP ports 2002/2000, NMEA sentences, `--file` replay, `--live-data`, systemd unit, no-variation note. https://github.com/ghotihook/fastnet2ip (seam tier LOW; primary project doc)
- pyfastnet on PyPI (3.2.1): `FrameBuffer` API, Signal K path output, 28800 8O2, replay example and captures. https://pypi.org/project/pyfastnet/ (LOW tier; primary project doc)
- pyfastnet channel map: TWD/Heading/Set true/magnetic chosen from layout, channel IDs. https://raw.githubusercontent.com/ghotihook/pyfastnet/main/docs/channel_map.md (LOW tier; primary project doc)
- libweatherrouting README and source (`routers/router.py`, `linearbestisorouter.py`): 72 TWAs at 5°, bearing-bin pruning, pure Python, validity callbacks, single next waypoint. https://github.com/dakk/libweatherrouting (LOW tier; primary source code)
- Raspberry Pi read-only overlay discussions (Core Electronics guide, Blokas forum, Lemmy): https://core-electronics.com.au/guides/raspberry-pi/read-only-raspberry-pi/ , https://community.blokas.io/t/read-only-os-to-prevent-os-corruption-on-sd-card/6199 (LOW)
- Signal K resource usage on small Pis (community forums, no official benchmark): https://answeroverflow.com/m/1261787460527194122 (LOW)
- Expedition GRIB time-shift and model averaging (user forum / Setsail): https://expedition.boardhost.com/viewtopic.php?id=399 , https://setsail.com/expedition-routing-comparing-weather-models/ (LOW; no primary source found for decaying measured-wind blending)
- Engineering judgement (true-wind vector maths, isochrone/Hagiwara pruning, atomic file replacement, systemd watchdog): standard practice, not separately sourced.

---
*Architecture research for: on-board live race routing and laylines (Jabuka, X35, Pi 3B)*
*Researched: 2026-11-05*
