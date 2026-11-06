# Phase 3: Weather Routing & Tack Advice - Research

**Researched:** 2026-11-06
**Domain:** Offline GRIB race pack (DWD ICON-EU/EWAM, Copernicus currents, generic GRIB), raster land mask from OSM, numpy isochrone router with land avoidance, GRIB bias correction, tack advice (countdown / stay-on-tack / cost of not tacking), router supervision on a Raspberry Pi 3B
**Confidence:** HIGH for data sources, land mask and router feasibility (all prototyped and measured this session). MEDIUM for Pi 3B timings (extrapolated from the laptop). LOW for the tuning constants (bias decay, wave factor).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Race pack prep (laptop: `jabuka-prep`)
- Downloads **ICON-EU** (DWD opendata, regular lat/lon, 10 m U/V; latest run covering 13 Nov 18Z → 15 Nov 10Z local) and **EWAM** waves (significant wave height + mean direction) from opendata.dwd.de; imports any GRIB1/GRIB2 file (organizer forecast) with pygrib; imports Copernicus Med currents NetCDF (user downloads with their free account / `copernicusmarine` CLI — tool accepts a file path; credentials never stored in repo).
- Crops to race bbox ≈ 15.0–16.3E, 42.8–44.0N; writes `wind.npz` (u, v float32 [t, lat, lon], UTC epoch seconds, model/run metadata), `waves.npz`, `current.npz` into a gitignored race-pack dir, plus `landmask.npz` and a coverage report.
- **Coverage validation (GRIB-02)**: every mark and every hour 13 Nov 18:00 → 15 Nov 10:00 local (UTC+1) must be inside the data; otherwise loud warning in the prep output and on the Pi Diag/helm.
- DWD keeps only ~24 h of runs → the prep tool must be re-run Friday before the start; document in runbook.
- Organizer forecast format still unknown → generic GRIB importer + clear error for other formats.

#### Land mask & never-cross-land (ROUT-01, ROUT-11)
- Source: OSM land polygons (osmdata.openstreetmap.de land-polygons-split-4326, cropped) + hand hazard polygons (Plić Sestre shoal, reefs near Blitvenica/Jabuka, any other charted dangers found via OSM seamark hazards/rocks).
- Rasterized on the laptop to a boolean grid at ≈ 25–50 m resolution in a local equirectangular frame — fine enough that the **narrow inter-island channels of the Šibenik archipelago stay open** (e.g. Prvić–Tijat, Zlarin channel); then dilated by a configurable **shore margin (default 100 m; hazards 200 m)**. Narrowest critical channel width must be measured and the margin validated so no required channel closes.
- **Segment-level check**: every isochrone expansion segment is sampled at ≤ half-cell spacing (or Bresenham/DDA over the raster) — not just endpoints. A segment touching land is rejected.
- **Test suite of island-crossing cases** with known geometry: Vodice → open sea (must exit via a real channel), straight line through Prvić/Zlarin/Tijat must be rejected, rounding Blitvenica and Jabuka by the correct side, passing Plić Sestre. Every computed route polyline is re-validated against the mask (assertion in tests; runtime sanity check flags and discards an invalid route).
- Marks placed on land (islands as marks) → rounding waypoints on a circle of per-mark radius at sea (from Phase 2 course model).

#### Router
- Own numpy-vectorised isochrone engine (port of libweatherrouting's approach; libweatherrouting only as test oracle/fallback). Local planar frame in nm; headings every 5° (degraded: 10°); time step 10–15 min near the boat growing to 30–60 min far out; pruning by bearing sectors from start; tack/gybe penalty (default 45 s, configurable) on heading side change; u/v trilinear interpolation (space + time); polar × efficiency (Phase 2 settings) × wave factor; current vector added to velocity.
- Wave factor: speed multiplier f(Hs, TWA sector) from a small table (default ~ -5 %/m of Hs upwind, less downwind, cap -30 %), else f(TWS) when no wave file. Tunable; LOW-confidence numbers documented.
- Multi-leg sequential: arrival of leg k starts leg k+1; whole remaining course for ETA; UI emphasises current leg.
- Pure function `route(RouteRequest) -> RouteResult` in a `ProcessPoolExecutor(max_workers=1)` worker at nice 10, 60 s timeout, recreated on crash; last good route kept with age. Routing blocked until the GPS clock gate is ok (Phase 1).
- **Pi 3B benchmark gate (2026-11-09)**: a benchmark script with a realistic remaining-course scenario; if optimal + forced-tack routes don't fit the cadence, apply documented degraded settings in order: 10° headings → 30-min steps → route next mark + one only → cadence 10 min → cost-of-not-tacking every other cycle.

#### Wind correction (WIND-05, WIND-06)
- Wind source now: LIVE > MANUAL > GRIB-only (GPS + GRIB) — badge shows GRIB when the bus is silent.
- Bias estimator: measured (damped, steady-sailing gate: no tack in last 3 min, all inputs fresh, BSP > 2 kn) minus GRIB at boat position/time, averaged ~10 min, as direction offset + speed ratio; clamps ±35°, ratio 0.6–1.5; applied to the GRIB with exponential time decay τ default 2.5 h (configurable); shown on helm ("+12° ×1.15, fading"); toggle off; **frozen inside the Jabuka magnetic zone** (Phase 2 flag). Manual wind uses the same path.

#### Supervisor, triggers, hysteresis (ROUT-02, ROUT-05, ROUT-09)
- Triggers: timer (default 5 min), course change, bias change beyond threshold, manual wind change, off-route (> 0.5 nm or > 20° heading divergence sustained 2 min), stay-on-tack toggled, **missed advised tack + 2 min**.
- Hysteresis: a new route replaces the current one only if it improves ETA by > max(3 min, 1 %) or the current route became invalid/outdated (> 20 min old) — except forced triggers (course change, stay-on-tack, missed tack) which replace immediately.

#### Tack advice (ROUT-06..ROUT-10)
- Route segments carry target TWA + tack; the helm keeps steering the target TWA between reruns (heading = TWD + target TWA).
- **Countdown** to next recommended tack/gybe = time until the route's first side change (fallback: Phase 2 layline countdown when no valid route).
- **"On reste" (Stay on this tack)** button: rerun with first leg forced on current tack for a minimum duration (default: until the next route-suggested tack point is ≥ 5 min later than optimal) → earliest next tack + updated countdown; persists until the next tack is detected or the user cancels.
- **Cost of not tacking now** = ETA(forced current tack) − ETA(optimal), minutes; computed every cycle as the second (forced) routing (or every other cycle when degraded).
- **Tack detection**: TWA sign change sustained > 30 s (with COG fallback inside the Jabuka zone).
- **Auto-recompute**: if now > advised tack time + 2 min and no tack detected → trigger reroute, display stops saying "VIRE" and shows "Route mise à jour…".

#### Display
- Route polyline + next tack point on the map; helm adds countdown "Virement dans 08:30", cost "Ne pas virer : +4 min", "On reste" button (big, lock-mode aware), route age, routing health on Diag.

### Claude's Discretion
- Module layout (suggested `src/jabuka/route/`: `racepack.py`, `landmask.py`, `isochrone.py`, `supervisor.py`, `bias.py`; prep under `src/jabuka/prep/`), exact constants within the stated ranges, data formats.

### Deferred Ideas (OUT OF SCOPE)
- Multi-model/ensemble comparison, GRIB disagreement alarm (v2).
- Spatial decay of bias (time-only in v1).
- Polar learning from logs (v2).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRIB-01 | Laptop prep tool downloads ICON-EU + EWAM, crops, converts to a compact race pack; imports any GRIB1/GRIB2 | §Data Sources (exact URL patterns, run selection, sizes, decode/crop recipe with margin), Pattern 1 (prep pipeline), Pattern 2 (generic GRIB importer, GRIB1 verified via eccodes-built fixture) |
| GRIB-02 | Race pack validated on load: every mark + full window covered, else warn | Pattern 3 (coverage rules: time window 13 Nov 17:00Z → 15 Nov 09:00Z, max time gap, marks inside grid with interpolation margin, NaN check) |
| GRIB-03 | Prep imports a Copernicus Med current file | §Data Sources (dataset id, variables `uo`/`vo`, grid, subset command), Pattern 1 |
| WIND-05 | GPS + GRIB-only mode when the bus provides nothing | Pattern 10 (source arbitration LIVE > MANUAL > GRIB, COG for heading, SOG for BSP, badge) |
| WIND-06 | GRIB bias (dir offset + speed ratio) estimated in steady sailing, applied with time decay, shown, can be disabled | Pattern 8 (gating, circular EMA, ratio of means, clamps, u/v rotation formula, decay, freeze in Jabuka zone, manual path) |
| ROUT-01 | Isochrone route boat → remaining marks, rounding sides, corrected wind, polar × eff, tack penalty, land/hazards | Patterns 4–6, prototype + benchmark (§Benchmark), geodesic-ranked pruning (the key robustness finding) |
| ROUT-02 | Auto rerun every few minutes + triggers, non-blocking, last good route + age | Pattern 9 (supervisor: ProcessPoolExecutor, forkserver, kill on timeout incl. 3.13 fallback, coalescing), tick-latency test |
| ROUT-03 | Speed reduced by wave height (EWAM else from TWS) | Pattern 4 wave factor table + Hs(TWS) fallback [ASSUMED constants], EWAM masked-cell fill |
| ROUT-04 | Uses current when present | Pattern 4 (current added to displacement; water-referenced wind for the polar) |
| ROUT-05 | Hysteresis | Pattern 9 (re-evaluated old-route ETA vs new ETA, max(3 min, 1 %), forced triggers bypass) |
| ROUT-06 | Countdown to next tack/gybe from route (laylines fallback) | Pattern 11 (first side change; countdown measured from the boat's projection on the route) |
| ROUT-07 | "Stay on this tack" | Pattern 7 (forced first leg until advised tack + 5 min; release when the held tack hits the land mask) — prototyped |
| ROUT-08 | Cost of not tacking now | Pattern 7 (forced current-leg routing, cost = arrival delta, clamp ≥ 0) — prototyped |
| ROUT-09 | Recompute 2 min after a missed advised tack | Pattern 11 (tack detector on AWA sign, countdown < −120 s and no tack → forced trigger) |
| ROUT-10 | Route on the map + target TWA/tack per current leg | Pattern 11 (route following: target TWA from the nearest route segment ahead; heading = TWD − TWA with the project sign convention) |
| ROUT-11 | Never crosses land; segment-level checks; channels open; island-crossing test suite | §Land Mask (measured channel widths, margins), Pattern 5 (coarse/fine segment sampling), §Verification Map (test cases with coordinates) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

`.claude/CLAUDE.md` directives that bind this phase:
- **Stack:** Raspberry Pi OS Lite 64-bit Trixie, Python 3.13 venv on the Pi; numpy 2.5.x; pygrib for GRIB1/2; prep (GRIB, land mask) on the laptop into `.npz`; the router only `np.load`s on the Pi. **No cfgrib/xarray at runtime on the Pi.** No shapely in the routing hot loop. **No pure-Python per-point routing loops on the Pi.**
- **Own numpy isochrone router** (libweatherrouting algorithm); libweatherrouting 0.2.3 is the oracle and emergency fallback (GPL-3 is acceptable).
- `copernicusmarine`, `netCDF4`, `eccodes`/`cfgrib`/`xarray` are **laptop-only**.
- Use the injected clock everywhere; routing is blocked while the clock is unsynced.
- Workflow: changes go through GSD commands (`/gsd-execute-phase` for planned work).
- Conventions section is empty (no extra coding rules beyond Phase 1 patterns): SI units internally, Signal K paths, M/T reference per value, test-first (RED then GREEN), fixtures under `tests/fixtures`, `scripts/check.sh` = ruff + pytest on 3.14 and 3.13.

## Summary

Everything this phase needs exists and was exercised end to end this session. DWD opendata serves ICON-EU 10 m wind and EWAM waves as bz2 GRIB2 files with predictable names. pygrib 2.1.8 (wheels for cp313/cp314 on x86_64 and aarch64) decodes and crops them. A full 49-hour ICON-EU pull (98 files, 111 MB) took 12.8 s, decode plus crop took 23 s, and the result is a 221 KB `wind.npz`. The Copernicus Med currents dataset was confirmed through the `copernicusmarine` catalogue, but downloading needs an account, so this report only documents it. The osmdata.openstreetmap.de land-polygon server could not be reached from this machine. Instead, OSM coastline ways fetched through Overpass (4.9 MB) were turned into land polygons with shapely in 0.5 s, with zero unclassified faces. A vectorised numpy scanline rasteriser built 25 m and 50 m masks in under 0.5 s, and they match shapely at every cell centre tested.

**The channel question has a hard number.** Every route out of Vodice must pass a bottleneck with **516–530 m clearance on each side**. This is the Prvić–Tijat passage (≈1.03–1.07 km wide, 43.7229 N 15.7828 E). All other connections the course needs have ≥ 914 m clearance. With the default 100 m shore margin, 200 m hazard margin and a 25 m raster, every mark stays reachable. That holds even with all 710 OSM rock nodes added as hazards. Gaps narrower than about 2 × margin + 2 cells close: Prvić–Lupac 255 m, Tijat–Kamenica 260 m and Obonjan–Sestrica Vela 288 m all close at the defaults. That is intended, since those are night-time hazards.

**The router prototype answered the performance question, and it also exposed a real design flaw in the planned pruning.** On the i7-7700K laptop, a whole Course A/B route (87–91 nm, 14–33 h ETA) takes a median of **0.29 s and at most 0.47 s** with 5° headings and a 25–50 m mask. The forced current-leg routing adds 0.02–0.12 s. Extrapolated to a Pi 3B (×15 typical, ×25 pessimistic), one cycle (optimal plus forced) is **≈ 6–15 s, far inside the 5-min cadence and the 60 s timeout**. However, the planned pruning rule ("farthest from the leg origin per bearing sector", as in Hagiwara and libweatherrouting) **failed or gave erratic ETAs in 1–3 of 8 archipelago scenarios**. The isochrone front gets trapped in pockets behind islands, and long time steps cannot thread the channels. Two fixes made every scenario succeed with consistent ETAs. First, rank each sector by **geodesic (around-land) distance to the leg target**, using a per-mark distance field computed once in prep. Second, **force the fine time step whenever the leading part of the front is within 1 nm of land**.

**Primary recommendation:** Build the pure core first (race-pack prep, land mask, numpy isochrone engine with geodesic sector ranking, bias maths and the benchmark script) and test it on the laptop against committed fixtures. Only then integrate with the Phase 2 core (supervisor, route following, tack advice, UI).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| GRIB/EWAM download, decode, crop, generic GRIB import, Copernicus import | Laptop prep CLI (`jabuka-prep`) | Pi (pygrib wheel, emergency re-prep) | Heavy deps and network live on the laptop; the Pi only reads `.npz` |
| Land polygons → raster mask, hazards, geodesic fields | Laptop prep CLI | — | shapely/Overpass are prep-only; the runtime gets O(1) raster lookups |
| Race pack load + coverage validation (GRIB-02) | Core (API/backend) | Router worker (re-validates its copy) | Warnings must reach Diag/helm even if routing is off |
| GRIB-only wind (WIND-05), source arbitration | Core (wind pipeline, Phase 2 module) | — | Same arbitration seam as LIVE/MANUAL |
| Bias estimation (gated EMA) | Core (1 Hz tick) | — | Needs live instruments, tack state, Jabuka flag |
| Bias application to the wind field | Router worker | Core (helm GRIB-only wind) | Pure function of bias params + time |
| Isochrone routing (optimal + forced) | Router worker process (nice 10) | — | CPU-heavy; must never block the asyncio loop |
| Supervisor (triggers, coalescing, timeout, hysteresis) | Core | — | Owns state, clock and WS |
| Route following (target TWA, countdown, cost, missed tack) | Core (1 Hz) | — | Live wind and position; the server computes and the browser renders |
| Route/tack-point drawing, countdown, "On reste" button | Browser (render only) | Core (REST/WS) | Phase 1/2 rule: no navigation maths in the browser |
| Pi benchmark | Human-run CLI on the Pi | Laptop smoke test | The real hardware is only reachable by the owner |

## Standard Stack

### Core (Pi runtime)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.5.4 (released 2026-10-10; cp313 + cp314 aarch64 wheels) | Router, wind/wave/current interpolation, mask lookups, bias apply | [VERIFIED: PyPI JSON this session] Only numeric dependency needed at runtime. Must be added to `[project].dependencies` **and** `deploy/requirements.in` and re-locked (see Pitfall 12) |

### Prep / laptop (new optional extra, e.g. `[prep]`)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pygrib | 2.1.8 (cp310–cp314 wheels, x86_64 + aarch64, eccodes bundled) | Decode ICON-EU/EWAM GRIB2 (CCSDS packing) and any GRIB1/2 | [VERIFIED: PyPI file list + decoded real files this session] Always in prep |
| shapely | 2.2.0 | Coastline polygonize/classify, buffers (margins), hazard discs | [VERIFIED: used this session] Prep only |
| netCDF4 | 1.7.5.1.post1 | Read the Copernicus NetCDF (`uo`, `vo`) | [VERIFIED: PyPI JSON] Prep only. xarray is also fine on the laptop |

### Dev / test only (extend the `[dev]` extra)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| weatherrouting (libweatherrouting) | 0.2.3 (GPL-3, depends on latlon3 1.0.4) | Oracle in tests (open-water legs) | [VERIFIED: installed + run this session] Test-only import, `pytest.importorskip` |
| eccodes | 2.50.0 (+ eccodeslib 2.50.0.33) | Build a GRIB1 test fixture (`codes_grib_new_from_samples("regular_ll_sfc_grib1")`) | [VERIFIED: built a GRIB1 file and read it back with pygrib this session] Dev-only, optional (skip the test if absent) |

### User-run tool (not a project dependency)
| Tool | Version | Purpose |
|------|---------|---------|
| copernicusmarine CLI | 2.5.1 (2026-11-03) | User downloads the current NetCDF with their own account. The prep tool only takes a file path [VERIFIED: `copernicusmarine describe` ran without credentials; `subset --dry-run` prompts for credentials] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| OSM land-polygons-split-4326 (osmdata) | **Overpass coastline ways + own polygonize** (verified) | osmdata.openstreetmap.de refused connections from this machine (ECONNREFUSED/no route on 2026-11-06), and the zip is several hundred MB [ASSUMED size]. Overpass gave 4.9 MB of coastline for the bbox, and the polygonize/orientation classification produced 446 land faces with 0 unclassified. **Support both:** Overpass is the default; `--land-polygons <shp/zip>` is optional if osmdata comes back (needs a shapefile reader such as `pyshp`, only then) |
| Sector pruning by distance from origin (planned) | **Geodesic distance-to-target ranking per sector** | Measured: origin ranking failed or diverged in 1–3/8 archipelago scenarios; geodesic ranking had 0/8 failures, at about 1.5× the routing time of origin ranking (still ≤ 0.47 s for the whole course on the laptop). Fields cost ~2 s each on the laptop (200 m grid), so precompute them in prep |
| scipy for distance fields | numpy 8-neighbour relaxation | scipy is not in the Pi stack. The numpy relaxation converges in 200–600 iterations, which is fine at prep time |
| `matplotlib.path`/GDAL rasterisation | numpy even-odd scanline fill (prototype below) | No GDAL/sudo; 0.2–0.5 s for 5.6–22.4 Mcells; 100 % agreement with shapely at cell centres |

**Installation (laptop dev venvs):**
```bash
uv pip install --python .venv/bin/python numpy==2.5.4 pygrib==2.1.8 shapely==2.2.0 netCDF4==1.7.5.1.post1 weatherrouting==0.2.3
# Pi runtime: only numpy, through deploy/requirements.in + scripts/build-wheelhouse.sh --relock
```

**Version verification:** numpy 2.5.4 (2026-10-10), shapely 2.2.0 (2026-10-07), pygrib 2.1.8 (2025-10-26), netCDF4 1.7.5.1.post1 (2026-10-23), weatherrouting 0.2.3 (2025-05-08), copernicusmarine 2.5.1 (2026-11-03). Source: PyPI JSON API queried this session.

## Package Legitimacy Audit

`gsd-tools query package-legitimacy check --ecosystem pypi` returned **SUS** for every package, citing `unknown-downloads` and `no-repository` (the seam has no PyPI download/repo signal), plus `too-new` for numpy and shapely because their latest releases are under 30 days old. Cross-checked against the PyPI JSON:

| Package | Registry | Age (first upload) | Downloads | Source Repo (PyPI project_urls) | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| numpy | PyPI | 2006 | n/a (seam) | github.com/numpy/numpy | SUS (seam artefact) | Approved: pin + hash in lock |
| pygrib | PyPI | 2014 | n/a | github.com/jswhit/pygrib | SUS (seam artefact) | Approved (prep extra) |
| shapely | PyPI | 2007 | n/a | github.com/shapely/shapely | SUS (seam artefact) | Approved (prep extra) |
| netCDF4 | PyPI | 2006 | n/a | github.com/Unidata/netcdf4-python | SUS (seam artefact) | Approved (prep extra) |
| weatherrouting | PyPI | 2021 | n/a | none listed on PyPI (STACK.md: github.com/dakk/libweatherrouting) | SUS | `weatherrouting` [WARNING: flagged as suspicious — verify before using.] Dev-only oracle |
| latlon3 | PyPI | 2019 | n/a | github.com/search5/latlon | SUS | `latlon3` [WARNING: flagged as suspicious — verify before using.] Transitive dev-only dependency of weatherrouting |
| eccodes | PyPI | — | n/a | ECMWF | not run through the seam | Optional dev-only fixture builder |
| copernicusmarine | PyPI | 2024 | n/a | none listed | SUS | Not a dependency (user tool, documented only) |

**Packages removed due to [SLOP]:** none.
**Packages flagged [SUS]:** all of them, as a seam artefact. Policy, carried over from Phase 1 and Phase 2 (02-CONTEXT addendum): "no blocking per-install checkpoint (unattended run); pins + hashes in the lock, one end-of-phase human lock review item". The planner should add **one end-of-phase human-verify item** covering the numpy lock entry and the dev/prep pins, with weatherrouting/latlon3 called out explicitly.

## Data Sources (verified this session)

### ICON-EU 10 m wind (GRIB-01)
- **URL pattern** [VERIFIED: opendata.dwd.de directory listings + 98 files downloaded]:
  `https://opendata.dwd.de/weather/nwp/icon-eu/grib/{HH}/{u_10m|v_10m}/icon-eu_europe_regular-lat-lon_single-level_{YYYYMMDDHH}_{FFF}_{U_10M|V_10M}.grib2.bz2`
- **Runs:** 00/06/12/18 run to +120 h (hourly to +78, then 3-hourly: 93 files). 03/09/15/21 run to +51 h, hourly (52 files). Each `{HH}/` directory holds **only the latest run of that hour**, so about 24 h of runs are online. **Files appear progressively between run + 2 h 40 and run + 3 h 32** (00Z run: 02:40:34 → 03:32:25). A run is usable only when its last needed step exists.
- **Size:** about 1.1–1.2 MB per file. bz2 barely helps because the payload is CCSDS-packed. 49 h × U+V = 98 files = 111 MB, downloaded in 12.8 s with 6 parallel curls.
- **Grid** (decoded with pygrib): `gridType regular_ll`, Ni 1377 × Nj 657, 0.0625°, lat 29.5→70.5 **ascending rows**, lon −23.5→62.5 (`longitudeOfFirstGridPointInDegrees` 336.5), `packingType grid_ccsds`, shortNames `10u`/`10v`, `typeOfLevel heightAboveGround`, level 10. **`forecastTime` is in minutes (1440 = +24 h)**, so always use `g.validDate`.
- **Crop:** `g.data(lat1, lat2, lon1, lon2)` returns 2-D arrays for lat/lon grids. Asking for exactly 15.0–16.3E gave lon 15.0…16.25: **the bbox edge 16.3E was not covered**. Crop with a **0.25° margin** (gives 28 × 29 cells).
- **Run choice for Friday 13 Nov** (race window = 13 Nov 17:00Z → 15 Nov 09:00Z, since 18:00–10:00 local is UTC+1 in November): 12Z run (complete about 15:35 UTC = 16:35 local) needs +5…+45, all hourly. The 15Z run (+51 max) also covers it but completes about 18:30 UTC, which is too close to a 20:00 local start. Selection algorithm: newest run whose `run + max_step ≥ window_end` **and** whose needed steps all exist in the listing. Fall back to the previous run.
- **Optional:** `fr_land` (time-invariant land fraction, `.../{HH}/fr_land/icon-eu_europe_regular-lat-lon_time-invariant_{run}_FR_LAND.grib2.bz2`) exists [VERIFIED: listing], as do `vmax_10m` (gusts) and `pmsl`. These are not needed for v1.

### EWAM waves (ROUT-03)
- **URL pattern** [VERIFIED: listings + decoded]: `https://opendata.dwd.de/weather/maritime/wave_models/ewam/grib/{00|12}/{swh|mwd}/EWAM_{SWH|MWD}_{YYYYMMDDHH}_{FFF}.grib2.bz2`. Other variables in the run directory: `dd_10m mdts mdww mpts mpww mwd ppts ppww shts shww sp_10m swh tm10`.
- **Runs:** 00 and 12, hourly +0…+78. **Two runs are kept** per directory. Published run + 3 h 16 → + 3 h 52. SWH is about 95 KB per file and MWD about 225 KB.
- **Grid:** regular_ll 526 × 721, **dlon 0.1° × dlat 0.05°, lat 66→30 (descending rows)**, lon −10.5→42. `bitmapPresent 1`: **land/near-coast points are masked** (69 of 312 cells in the race bbox). `swh` in m; `mwd` "Degree true". Crop also needs the margin (the lon 15.0 edge was dropped because of float rounding).

### Copernicus Med currents (GRIB-03), documented only (needs an account)
- Product `MEDSEA_ANALYSISFORECAST_PHY_006_013`, dataset **`cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m`** (version 202511), "Sea Surface Horizontal Velocity (2D) - Hourly Mean". Variables **`uo`** (eastward_sea_water_velocity, m s-1) and **`vo`** (northward), coordinates `latitude` 30.1875…45.979 (step 1/24°), `longitude` −17.29…36.29, `time` hourly. On 2026-11-05 the forecast reached about 9 days ahead [VERIFIED: `copernicusmarine describe --dataset-id …` this session]. There is no depth coordinate in the describe output (2D dataset).
- User command (documented in the runbook; credentials come from the CLI prompt or `copernicusmarine login`, never the repo):
  ```bash
  copernicusmarine subset --dataset-id cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m \
    --variable uo --variable vo \
    --minimum-longitude 14.75 --maximum-longitude 16.55 --minimum-latitude 42.55 --maximum-latitude 44.25 \
    --start-datetime 2026-11-13T12:00:00 --end-datetime 2026-11-15T12:00:00 \
    --output-filename current_med.nc
  jabuka-prep current current_med.nc   # → racepack/current.npz
  ```
  Option names were verified with `copernicusmarine subset --help`. A dry run needs credentials, so the exact output layout is [ASSUMED]: `uo(time, latitude, longitude)` with NaN or `_FillValue` on land. The importer must treat masked current as **0** (unknown means no current), not fill it from the nearest neighbour.

### Organiser / generic GRIB (GRIB-01)
- pygrib reads GRIB1 and GRIB2 [VERIFIED: GRIB1 built with eccodes from the `regular_ll_sfc_grib1` sample and read back by pygrib, `edition 1`, rows N→S]. `data(lat1..)` returns **2-D only for unprojected lat/lon grids, else 1-D** [VERIFIED: pygrib docstring]. `latlons()` handles lambert, rotated_ll, mercator, gaussian and so on.
- GRIB1 shortNames depend on the parameter table. The same `indicatorOfParameter 33` decoded as `rsn` with the ECMWF sample table. Match wind fields on several keys: shortName ∈ {`10u`,`u`,`UGRD`} / {`10v`,`v`,`VGRD`} at `heightAboveGround` level 10, or paramId 165/166, or speed/direction pairs (`10si`/`10wdir`, `ws`/`wdir`). Always print what was found, and fail with a clear message ("aucun champ de vent 10 m trouvé ; champs présents : …").

## Land Mask (ROUT-01, ROUT-11): measured

**Source used:** Overpass `way["natural"="coastline"](42.7,14.9,44.1,16.4); out geom;` gave a 4.9 MB JSON with 934 ways and 74,955 nodes (OSM base 2026-11-06T02:01Z) [VERIFIED]. `linemerge` produced 490 closed rings and 6 open chains (the mainland). These were clipped to the work frame, noded with the frame boundary and `polygonize`d into 451 faces. Each face was classified with the OSM rule "land on the left of the coastline direction": orient the face CCW and look for a coastline segment in the same direction. Result: **446 land faces, 0 unclassified, 2,972 km² land, 0.5 s** [VERIFIED]. Sanity points all correct: Vodice start, Plić Sestre and open sea are sea; Prvić, Zlarin, Tijat, Jabuka and Šibenik town are land.

**Rasterisation** (local equirectangular frame lat0 43.4, lon0 15.65, metres; cell-centre semantics) [VERIFIED]:

| Cell | Grid | Raster time | Packed+compressed npz | Agreement with shapely (20k random cell centres) |
|------|------|-------------|---------------|------|
| 50 m | 2667 × 2100 = 5.6 Mcells | 0.2 s | 27 KB | 100.000 % |
| 25 m | 5334 × 4199 = 22.4 Mcells (22 MB as bool in RAM) | 0.4–0.5 s | 65 KB | 100.000 % |

Margin buffer: `land.buffer(100 m)` takes 2.7 s (shapely, prep only).

**Channel bottlenecks.** Max-min clearance over all water paths, computed on a 25 m margin-0 mask with a distance transform (scipy, research only), cross-checked with exact shapely buffer bisection [VERIFIED]:

| Required connection | Best-path min clearance (land only) | With all OSM rocks as 50 m discs | Pinch location |
|---|---|---|---|
| Vodice → Plić Sestre (either side) | **516 m** (exact shapely: 530 m) | 516 m | 43.7229 N 15.7828 E: **Prvić–Tijat passage** |
| Plić Sestre → open sea SW | 1137 m | 492 m* | — |
| Plić Sestre → Jabuka rounding | 1043 m | 492 m* | — |
| Plić Sestre → Mulo | 914 m | 492 m* | — |
| Blitvenica / Mulo → Vodice | 516 m | 516 m | Prvić–Tijat |

\*With every submerged rock as a hazard, the widest path detours. Min clearance stays ≥ 492 m.

**Named gaps near the course** (exact polygon distance) [VERIFIED]: Prvić–Lupac 255 m; Kamenica–Tijat 260 m; Obonjan–Sestrica Vela 288 m; Logorun–Tijat 412 m; Obonjan–Zmajan 419 m; Galijola–Prvić 549 m; **Prvić–mainland (Vodice side) 824 m**; **Prvić–Tijat 1065 m**; Zlarin–mainland 1247 m; Lupac–Zlarin 1450 m.

**Rule (derived):** a gap of width g stays open when `g > 2·margin + 2·cell` (plus hazard discs inside it). Defaults of 100 m margin, 200 m hazard margin and a 25 m cell keep every required connection open with ≥ 300 m to spare. Raising the shore margin to ~400 m would still keep the course feasible but closes Prvić–mainland. **Recommended defaults: cell 25 m, shore margin 100 m, hazard margin 200 m.** The effective guaranteed clearance is margin − 0.71·cell ≈ 82 m.

**Connectivity checks (4-connected flood from Vodice) on the real masks** [VERIFIED]: Plić Sestre, open sea, Jabuka and Mulo rounding points were reachable with (a) land + 100 m, (b) land + 100 m + awash/covers rocks + 200 m + submerged rocks + 100 m, and (c) land + 200 m + awash rocks + 400 m + submerged rocks + 200 m. Full routes under (b) and (c) were valid for all 6 wind/course scenarios.

**Hazards found in OSM within the bbox** [VERIFIED: Overpass]: 710 `seamark:type=rock` nodes (663 `submerged`, 26 `awash`, 24 `covers`, 2 untagged), 20 `beacon_isolated_danger`, 3 `buoy_isolated_danger`, 12 cardinals, 8 wrecks, 10 obstruction ways, 4 `natural=reef`, 2 `natural=shoal`, 261+84 `natural=bare_rock`.
- **Plić Sestre:** beacon node 498394251 (43.684627, 15.811626) "Plicina Sestre, in Zlarinski Kanal.", plus submerged rock node 8883790953 (43.684411, 15.811043). The nearest islets are Sestrica Vela (0.85 nm) and Obonjan (1.16 nm). Hazard = 50 m disc around both nodes + 200 m hazard margin. That stays inside the 0.3 nm (556 m) rounding radius.
- **Blitvenica:** no rocks within 1.29 nm. The nearest are submerged rocks/bare rock E at 43.6329 N 15.6024 E. The islet itself is in the coastline.
- **Jabuka:** only the islet's own `bare_rock` way (in the coastline). No other hazard within 1.5 nm in OSM (absence ≠ proof; check the chart).
- **Vodice start area:** isolated-danger beacon 43.75485 N 15.779379 E and submerged rocks 43.744 N 15.783 E, 0.3–0.4 nm from the placeholder start. These matter for the start/finish geometry.
- **Recommended hazard set (default):** all awash/covers rocks, isolated-danger beacons/buoys, `natural=reef|shoal`, and the hand polygons (Plić Sestre) as hazards with the 200 m hazard margin. **Submerged rocks without depth: 50 m discs, no extra margin, behind a prep flag (default on).** Measured: they do not close any required connection. Rock depth is unknown in OSM [ASSUMED: safe to treat as hazards for a 2.1 m draft at night].

## Architecture Patterns

### System Architecture Diagram

```
 LAPTOP (internet)                                                   PI 3B (offline)
 ───────────────────────────────────────────────                     ─────────────────────────────────────────────────────────
 jabuka-prep wind  ──► list DWD dirs → pick newest complete run ──┐
   (ICON-EU u/v)      download bz2 → pygrib decode → crop+margin  │
 jabuka-prep waves ──► EWAM swh(+mwd) → fill masked → crop        ├─► racepack/ (gitignored, scp)
 jabuka-prep grib  ──► any GRIB1/2 → detect wind keys → regrid    │     manifest.json (frame, sha256, coverage)
 jabuka-prep current► Copernicus .nc (user-downloaded) → u/v      │     wind.npz waves.npz current.npz
 jabuka-prep land  ──► Overpass coastline → polygonize/classify   │     landmask.npz (mask + raw, packbits)
                       + hazards → buffer → rasterise → geofields ┘     geofields.npz   coverage.txt
                                                                             │ np.load (allow_pickle=False)
                                                                             ▼
   Fastnet/GPS ─► core state ─► wind pipeline (LIVE>MANUAL>GRIB) ─► bias estimator (gated EMA, 1 Hz)
                                     │                                   │ {d_dir,k,t_obs,valid}
                                     ▼                                   ▼
                        laylines (Phase 2) ◄──────────── supervisor (1 Hz trigger check; timer 5 min,
                                                          course/bias/manual/off-route/stay-on-tack/missed-tack)
                                                                │ RouteRequest snapshot (t0 from GPS clock,
                                                                │  pos, tack0, waypoints, bias, settings level)
                                                                ▼
                                          ProcessPoolExecutor(1, forkserver) worker, nice 10
                                          ├─ optimal: whole remaining course (multi-leg isochrones)
                                          └─ forced: current leg, hold tack0 until advised tack + 5 min
                                                                │ RouteResult (≤300 pts, tack points, leg ETAs)
                                                                ▼
                        validate polyline vs mask → hysteresis (re-evaluated old ETA vs new) → current route
                                                                │
                        route following @1 Hz: projection on route → target TWA/tack, countdown,
                        cost (forced − optimal), missed-tack check (tack detector on AWA sign)
                                                                │ WS "route" (on change) + "nav" (1 Hz)
                                                                ▼
                        Browser: route polyline + tack point, "Virement dans 08:30", "Ne pas virer : +4 min",
                                 "On reste", route age, bias "+12° ×1.15", GRIB badge, Diag routing health
```

### Recommended Project Structure
```
src/jabuka/route/                 # PURE (no I/O except np.load in racepack, no clock reads) → add to no-wallclock scan
├── frame.py        # local equirectangular frame (lat0, lon0 from the pack), vectorised ll↔xy, wrap helpers
├── racepack.py     # load + validate pack (shapes, finite, monotonic t, frame, sha256), coverage report (GRIB-02)
├── fields.py       # WindField (u/v trilinear, bias apply), ScalarField (Hs), CurrentField; scalar .at() for the core
├── polar_grid.py   # dense regular TWS×TWA table from the Phase 2 Polar (×eff), VMG targets per TWS
├── landmask.py     # LandMask (fine + coarse "near" grid, segments_clear, in_zone), GeoField lookup
├── rounding.py     # rounding waypoint sweep per mark (side, radius), skip already-passed wps
├── isochrone.py    # route(request) -> result; multi-leg; forced tack; arrival by direct shot
├── evaluate.py     # re-evaluate an existing route under new wind (hysteresis), first side change
├── types.py        # RouteRequest / RouteResult / RouterSettings dataclasses (picklable, plain types)
└── bench.py        # jabuka-route-bench (Pi gate script; also laptop smoke test)
src/jabuka/core/router_service.py  # supervisor, worker pool, triggers, hysteresis, route following, tack advice
src/jabuka/core/bias.py            # bias estimator (or src/jabuka/nav/bias.py next to Phase 2 wind.py)
src/jabuka/nav/tacks.py            # Phase 2 owns it (sailed angles); Phase 3 adds/uses the tack detector
src/jabuka/prep/                   # laptop CLI: wind.py, waves.py, grib_generic.py, current.py, land.py, cli.py
tests/route/ tests/prep/ tests/fixtures/route/   # mask fixture (65 KB), GRIB template (≈200 B), ATTRIBUTION
```

### Pattern 1: Prep pipeline (GRIB-01/03)
- **Run discovery:** fetch the directory HTML, regex the file names, group by run, check the steps needed for the window, choose the newest complete run. Unit-test the selection on saved listing fixtures (no network in tests).
- **Download:** `urllib.request` with a 60 s timeout, ≤ 6 parallel requests (ThreadPoolExecutor), retries, skip existing files, verify `.bz2` integrity by decompressing. The cache directory lives outside git.
- **Decode:** `bz2.decompress` → temp file → `pygrib.open` (pygrib needs a path). For each message: `g.data(lat1=42.55, lat2=44.25, lon1=14.75, lon2=16.55)`. Normalise to **ascending lat** (flip if `lats[0,0] > lats[-1,0]`). Valid time = `calendar.timegm(g.validDate.timetuple())`. Masked → NaN.
- **Write:** `np.savez_compressed(wind.npz, u, v (float32 [T,NY,NX] m/s), t (int64 epoch s), lat, lon (float64 ascending), model, run)`. Strings are stored as numpy unicode arrays, which load with the default `allow_pickle=False`.
- **Waves:** `swh` (m) and optional `mwd` (deg FROM, true). Fill masked cells by **nearest valid cell** (iterative 4-neighbour dilation of valid values, in numpy). This is conservative inside sheltered channels.
- **Current:** `uo`/`vo` in m/s, TOWARDS (same convention as `current_towards_uv`). Masked → 0.
- **Manifest:** `manifest.json` (frame lat0/lon0, bbox, per-file sha256, model/run/source, created) and `coverage.txt` (Pattern 3). Write everything with Phase 1 `atomicio`.

### Pattern 2: Generic GRIB import (organiser forecast)
Iterate over all messages. Group candidate wind fields by validDate. Regular lat/lon grids use `data(lat1..)`. Other grids use `latlons()` + values, crop by bbox, then **regrid onto a regular 0.025° grid** by inverse-distance over the 4 nearest source points (brute force with numpy on the cropped points; a few thousand points at most). Speed/direction pairs convert with `uv_from_wind_from` semantics (FROM). Reject the file with a clear French error if there is no 10 m wind, no overlap with the bbox, or an unknown grid type.

### Pattern 3: Coverage validation (GRIB-02)
Run on the laptop at prep and again in the core on pack load. Each failed rule yields an alert (Diag + helm banner "MÉTÉO INCOMPLÈTE : …"):
1. `t[0] ≤ window_start (13 Nov 17:00Z)` and `t[-1] ≥ window_end (15 Nov 09:00Z)`. The window is configurable in local time (Europe/Zagreb, UTC+1 in Nov), converted once.
2. `max(diff(t)) ≤ 3600 s` inside the window (warn on 3-hourly data).
3. Every mark of courses A and B plus the current course, and the rhumb lines between them sampled every 1 nm, lies inside `[lat[1], lat[-2]] × [lon[1], lon[-2]]` (interpolation margin) and has finite u/v for all window times.
4. Waves/current: same rules, but a failure only disables that factor (ROUT-03/04 fall back), warning-level.
5. Beyond the last forecast time the router **holds the last field** and flags `horizon_hold=True` in the result.

### Pattern 4: Isochrone engine (ROUT-01/03/04): what the prototype validated
- **Frame:** the local equirectangular frame comes from the race pack (lat0 43.4, lon0 15.65). x = Δlon·60·cos(lat0) nm, y = Δlat·60 nm. Scale error at the bbox edges is about ±1 % in x (cos 42.8° vs 43.4°) and 0.4 % at Jabuka, which is acceptable. Mask and router share the frame, so land checks are exact in that frame.
- **Wind:** the step time t is the same for all parents, so blend the two bracketing time slices **once per step** (two tiny 28 × 29 grids), then do bilinear in space for all parents. Sample per parent, not per candidate. FROM direction = `atan2(-u, -v)`, matching `conventions.py:55`.
- **Polar:** resample the Phase 2 `Polar` once into a dense regular table (TWS 0–40 kn step 1 × TWA 0–180° step 1). Lookup is pure index arithmetic, bilinear. VMG up/down targets per integer TWS come from the same table. **Do not extend the last given TWA flat to 180°.** The prototype bug did that and moved the downwind target to 180°. Use 0.9 × last speed at 180° or stop at the last angle.
- **Headings:** |TWA| ∈ {30…180 step 5} ∪ {VMG up, VMG down per parent}, both signs ((31 + 2) × 2 = 66 per parent). **Heading = TWD − TWA** (project convention, see Pitfall 1). Tack = sign(TWA): +1 starboard, −1 port.
- **Speed:** `bsp = polar(tws_water, |twa|) × eff × wave_factor(Hs, |twa|)`. Wave factor (LOW confidence, configurable): `1 − k·Hs` with k = 0.05/m for |TWA| < 60°, 0.03/m for 60–120°, 0.015/m for > 120°, floor 0.70. No wave file: Hs from TWS ≈ 0.7 × WMO Beaufort "probable wave height" (5 kn → 0.1 m, 10 → 0.4, 15 → 0.8, 20 → 1.4, 25 → 2.0, 30 → 2.8 m) [ASSUMED].
- **Current:** displacement = bsp·dt·u(hdg) + c·dt. The wind fed to the polar is **water-referenced**: `(u_wind − u_cur, v_wind − v_cur)` before computing TWD/TWS. This is one subtraction and only applies when a current field is present.
- **Tack/gybe penalty:** if the child tack ≠ parent tack (and the parent tack ≠ 0), sail `dt − penalty` (45 s default) at the new heading.
- **Arrival (exact):** at each step, for every parent compute the direct shot to the leg target (heading = bearing, TWA, polar speed, + penalty if the tack changes). If `need ≤ dt` and the segment is clear, arrive at `t + need`, take the minimum over parents, and stop the leg. Note that lwr stops "near" the target (gap up to ~1 nm, ETA quantised to the step).
- **Pruning (CHANGED from the plan, measured):** sectors of 1.5° by bearing from the leg origin. **Within a sector keep the candidate with the smallest geodesic distance to the leg target**, using a per-target distance field. Land-check only the best 4 candidates per sector (`lazy_k=4`) and keep the first valid one. If all 4 are blocked, the sector is dropped this step. Checking every candidate (`lazy_k=0`) was 5–10× slower and *less* robust.
- **Time step:** 10 min for the first hour, 15 min to 3 h, 30 min beyond. **Use 10 min whenever the leg target or origin is < 3 nm away, or any of the 20 % front points closest to the target lies within 1 nm of land** (coarse "zone" raster). Without the land-proximity rule, Blitvenica → Vodice failed (30-min segments cannot thread 1 km channels).
- **Multi-leg:** sequential. The arrival position, time and tack of leg k start leg k+1. `legs[k].eta` gives per-mark ETAs.
- **Output:** path points `(t, x, y, twa, tack, bsp, twd, tws)`, decimated for WS to ≤ 300 points. Tack points (first and later side changes), leg ETAs, `horizon_hold`, `force_released_at`, settings level, compute ms, steps.

### Pattern 5: Land checks (ROUT-11)
- `landmask.npz`: `mask` (dilated: land + 100 m ∪ hazards + 200 m) and `raw` (undilated land), each `np.packbits(axis=1)`, plus `shape, x0, y0, cell, lat0, lon0, margin_m, hazard_margin_m, source`. Unpack once in the worker (22 MB bool at 25 m).
- **Coarse "near" grid:** blocks of 8 × 8 fine cells (200 m at 25 m) marked if any land is in the block or its 8 neighbours. A segment sampled at the block spacing whose samples all fall in non-near blocks is clear: any land along it would be ≤ half a spacing from a sample, which is inside the dilated neighbourhood. Only "near" segments are sampled at **half a fine cell**. Measured: 30–45 % of segments needed the fine pass on this course, and land sampling is about 40 % of routing time (cProfile).
- **Start inside the margin** (boat in Vodice marina or close to shore): snap the start to the nearest clear cell (ring search ≤ 1 nm), check that exit segment against `raw` only, prepend it, and flag `start_in_margin`. Do the same for a target inside the mask, and validate rounding waypoints when the course loads (push them radially outward until clear, with a warning).
- **Final validation:** check every polyline segment against the dilated mask. On failure, discard the route, keep the last good one, and raise a "route invalide" alert. Tests assert this.

### Pattern 6: Rounding waypoints (from the Phase 2 Mark model: `radius_nm`, `side`)
For mark M with previous P (previous mark, or the start for leg 1) and next N: b_in = bearing(P→M), b_out = bearing(M→N). Port rounding: the boat passes on the right, starting at angle a1 = b_in + 90° and sweeping CCW (decreasing bearing-from-mark) to a2 = b_out + 90°. Starboard rounding: a1 = b_in − 90°, sweeping CW to a2 = b_out − 90°. Use one waypoint per ≤ 90° of sweep. Checked: Course A starboard Plić Sestre (161° in, 203° out) gives a 42° sweep starting at 071° from the mark (boat passes east of the beacon). The Jabuka hairpin (203° in, 009° out) gives a 166° sweep with 3 waypoints. Use the **previous mark**, not the boat, for b_in, so the waypoints do not move between reruns. Drop waypoints already passed (boat inside the zone and past them in sweep order).

### Pattern 7: Stay-on-this-tack and cost of not tacking (ROUT-07/08), prototyped
- Optimal route (whole course) from the request gives `t_tack` = time of its first side change relative to `tack0` (the boat's detected current tack, passed in the request).
- **Forced route:** the **current leg only** (default `cost_horizon="leg"`). The same request, plus `force_tack_until = max(t0, t_tack) + 5 min`. Before that time only headings (and direct shots) on `tack0` are generated. **If every same-tack expansion is blocked by the mask, release the constraint at that time** and set `force_released_at`. The helm then sees "virement imposé (terre) dans mm:ss".
- **Earliest next tack** = first side change of the forced route. **Cost** = forced leg arrival − optimal leg arrival (`opt.legs[0].eta`, no extra run). Display `max(0, round(cost))`. Measured discretisation noise was −0.2…+0.2 min, so show "< 1 min" for |cost| < 1.
- Measured (laptop): open-water beat, starboard tack advised now: hold +5 min costs 1.7 min, hold +60 min costs 3.8 min. Port tack with advised tack at +75 min: hold to +30 min past advised costs 10.2 min, +60 min costs 24.3 min. Vodice start on port: the held tack hits Tijat/Srima at +10 min, so the constraint is released and the cost is 0.
- "On reste" active: every cycle the *forced* route is the displayed route and the countdown shows its earliest next tack. The mode clears on a detected tack or cancel. Cycle cost: forced current-leg routing measured at 18–121 ms on the laptop.

### Pattern 8: GRIB bias (WIND-06)
Runs in the core at 1 Hz. All angles in rad, speeds in m/s.
1. **Gate (all must hold):** source LIVE (instrument true wind fresh), AWA/AWS/BSP/heading/GPS fresh (existing stale thresholds), BSP > 2 kn, no tack/gybe detected in the last 180 s, |turn rate| < 3°/s over 30 s (from the damped COG), TWS_meas and TWS_grib > 4 kn, the GRIB covers (now, boat position), **not inside the Jabuka zone** (freeze), bias enabled.
2. **Measured ground wind:** B&G true wind is water-referenced. If a current field exists: `W_ground = W_water + C(boat, now)` as u/v air-motion vectors. Otherwise accept the error (weak Adriatic currents).
3. **Accumulate** with a time-based EMA, τ = 600 s, α = 1 − exp(−Δt_gated/τ), where Δt counts only gated seconds (the EMA holds when the gate closes):
   - direction: `S = EMA(sin δ)`, `Cc = EMA(cos δ)` with δ = wrap_pi(TWD_meas − TWD_grib). Then `d_dir = atan2(S, Cc)`.
   - speed: `M = EMA(TWS_meas)`, `G = EMA(TWS_grib)`, then `k = M / G` (a ratio of means, robust when the GRIB is light).
   - `n_gated_s += Δt`. The bias is **valid after ≥ 300 gated seconds**.
4. **Clamp:** d_dir ∈ [−35°, +35°], k ∈ [0.6, 1.5]. Flag `clamped`. `t_obs` = time of the latest gated sample (UTC epoch from the GPS clock).
5. **Apply** (router per step, core for GRIB-only helm wind): `w = exp(−max(0, t − t_obs)/τ_decay)` with τ_decay = 2.5 h (9000 s). Rotate the GRIB air-motion vector **clockwise by w·d_dir** (TWD increases): `u' = u·cos φ + v·sin φ`, `v' = −u·sin φ + v·cos φ`, φ = w·d_dir. Then scale by `1 + w·(k − 1)`. Check: wind from 000° (u=0, v=−1) rotated φ=90° gives u'=−1, v'=0, which is wind from 090° ✓.
6. **Display:** effective now values `w·d_dir` and `1 + w(k − 1)` → "+12° ×1.15", plus "s'estompe" when not updating and "gelé (Jabuka)" inside the zone.
7. **Reroute trigger:** |Δ(w·d_dir)| > 5° or |Δ k_eff| > 0.10 since the last route request.
8. **Manual wind:** a user TWD/TWS entry (converted to TRUE) becomes one observation `δ = TWD_man − TWD_grib(boat, t_set)`, `k = TWS_man / TWS_grib`, `t_obs = t_set`, with the same clamps (no EMA).
9. **Toggle off:** the router receives `bias=None` and the helm shows "biais désactivé".

### Pattern 9: Supervisor, worker, hysteresis (ROUT-02/05)
- **Pool:** `ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("forkserver"), initializer=_init_worker, initargs=(racepack_dir,))`. `_init_worker` calls `os.nice(10)` and loads the pack once into module globals. Explicit forkserver: Python 3.14 already defaults to it, but **3.13 (the Pi) defaults to `fork`** [VERIFIED: `multiprocessing.get_start_method()` on both]. fork from a threaded asyncio process is unsafe, and tests run on both versions.
- **Timeout/crash:** `await asyncio.wait_for(asyncio.wrap_future(fut), 60)`. On timeout, kill: `ProcessPoolExecutor.kill_workers()` exists **only on 3.14**. On 3.13 iterate the private `pool._processes.values()` and `p.kill()` [VERIFIED: source inspection on both], then `shutdown(wait=False, cancel_futures=True)` and recreate. On `BrokenProcessPool`, recreate the same way. Keep the last good route; `route_age` grows.
- **Coalescing:** at most one job running and one pending (latest snapshot wins). Triggers are evaluated in the 1 Hz tick. Routing is blocked while `clock.status()["routing_time_gate"] != "ok"` [VERIFIED: `src/jabuka/common/clock.py:124` and `:317`, both `"routing_time_gate": "ok" if valid else "blocked",`] or when no valid race pack is loaded. The UI says why.
- **One job = one snapshot → two routings** (optimal whole course + forced current leg), returned together for consistency. The degraded level decides whether the forced routing runs this cycle.
- **Hysteresis:** on a non-forced trigger, compute `eta_old_now` = arrival of the current route **re-evaluated from the boat's projection under the new request's wind** (`evaluate.py`: sail the remaining old polyline segments at polar speed; if a segment's TWA becomes < 30° or crosses the mask, the old route is invalid). Replace when `eta_old_now − eta_new > max(180 s, 0.01 × (eta_new − now))`, or when the old route is invalid, older than 20 min, or the trigger is forced (course change, stay-on-tack toggle, missed tack, race-pack change). If re-evaluation is not implemented in time, fall back to `eta_old_now = now + (ETA_old − t_route_at_projection)`. This ignores wind changes, so mark it in the result.
- **Persistence:** store the current route in core state (atomic JSON) so a core restart keeps "last good route + age".

### Pattern 10: GPS + GRIB-only mode (WIND-05)
Extend Phase 2 arbitration: LIVE > MANUAL > **GRIB** > none. In GRIB mode: TWD/TWS = WindField.at(now, boat) with bias decay applied; heading := GPS COG; BSP := SOG; badge "GRIB"; laylines and the router keep working; the bias estimator does not update (no measurement). The core needs a scalar `WindField.at()`. Importing numpy in the core is acceptable [ASSUMED: +10–20 MB RSS, ~1 s import on the Pi].

### Pattern 11: Route following, countdown, missed tack (ROUT-06/09/10)
- At 1 Hz: project the boat onto the current route polyline (nearest segment ahead of the last projection, so it never jumps backwards) to get `t_route_here`. **Target TWA/tack** = that segment's TWA. Primary heading = TWD_now − TWA_target (project convention). XTE and off-route checks: > 0.5 nm, or > 20° between COG and the route segment course, sustained 120 s → trigger.
- **Countdown** = `t_tack_route − t_route_here` (route time, so it is robust to being early or late). No valid route → Phase 2 layline countdown.
- **Tack detector** (in `nav/tacks.py`): input is the sign of the 10 s-damped **AWA**. AWA comes from the masthead vane and is independent of the compass, so it works inside the Jabuka zone. TWA computed from AWA/AWS/BSP does not use heading either (`conventions.py` computes `twa` before `twd`). Confirm a new side when |angle| ∈ [15°, 165°] on the opposite sign continuously for 30 s, which avoids flicker head-to-wind and dead downwind. With no AWA (GRIB-only), use `wrap_pi(TWD_grib − COG)` with SOG > 1.5 kn. Emit `{t_tack, new_side}`.
- **Missed tack:** `countdown < −120 s` and no tack detected since `t_tack − 60 s` → forced reroute trigger. The helm replaces "VIREZ" with "Route mise à jour…" until the new route arrives.

### Anti-Patterns to Avoid
- **Heading = TWD + TWA** (ARCHITECTURE.md:195 snippet). This gives mirrored tack labels under the project convention. Use `TWD − TWA`.
- **Pruning by "farthest from origin" alone in the archipelago** (measured failures).
- **Long fixed time steps near land** (cannot thread 1 km channels).
- **Shapely in the runtime loop**, and **`np.load(..., allow_pickle=True)`** on race-pack files (arbitrary code execution from a crafted file).
- **Computing GRIB valid time from `forecastTime` as hours.** ICON-EU encodes it in minutes. Use `validDate`.
- **Cropping exactly at the bbox:** edge cells drop because of float rounding. Use a 0.25° margin.
- **Filling masked current with nearest values** (invents currents in channels). Use 0. For waves, nearest-fill is conservative and fine.
- **Running two routings as two separate jobs with two snapshots.** The cost becomes inconsistent.

## Benchmark & Pi Extrapolation (ROUT gate, SC5)

Laptop: Intel i7-7700K (max 4.5 GHz), Python 3.14.7, numpy 2.5.4. Prototype at `scratchpad/scripts/iso_proto.py` (not in the repo). Scenarios: Course A (Vodice→Plić Sestre→Jabuka→Blitvenica→Vodice) and B (→Mulo) from Vodice, under uniform SW 12 kn, NE 18 kn (bora) and real ICON-EU 2026-11-05 18Z (mean 5 kn, max 22 kn) at two start times. Median of 2–3 runs [VERIFIED]:

| Settings (geodesic ranking, lazy_k 4) | Mask | Whole-course route median / max | Fails (8 scenarios) |
|---|---|---|---|
| L0: 5° + VMG targets, 10/15/30-min schedule | 50 m | 289 / 419 ms | 0 |
| L0 | 25 m | 364 / 470 ms | 0 |
| L1: 10° headings | 50 m / 25 m | 213 / 304 ms; 301 / 376 ms | 0 |
| L1 + 15/30-min steps, 2° sectors | 50 m / 25 m | 166 / 244 ms; 252 / 342 ms | 0 |
| (planned design) origin ranking, L0 | 50 m | 189 / 396 ms | 1–3, plus erratic ETAs (41.4 h vs 29.8 h for the same case) |
| Forced current leg (stay-on-tack) | 50 m | 18–121 ms | — |
| Geodesic field per target, 200 m centre-sampled | — | ≈ 2.1 s each (prep) | — |
| Geodesic field, 400 m any-land | — | ≈ 0.18 s each | — |
| libweatherrouting 0.2.3, one 20 nm open-water leg | — | 4.7–8.5 s | — |

Accuracy: open-water legs agree with analytic VMG within 0.5 % (3.92 h vs 3.90 h beat; 2.60/2.60 reach; 3.15/3.15 run). They agree with lwr once its arrival gap is accounted for (lwr 2.50 h + 0.78 nm gap ≈ 2.60 h). Geodesic ranking costs up to ~3 % ETA vs the best origin-ranked runs with 400 m any-land fields (17.37 h vs 17.17 h; 26.43 h vs 25.71 h), and ≤ 0.3 % with 200 m centre-sampled fields (17.18 h; 25.75 h). Keeping the farthest-from-origin point per sector as well ("dual") recovers most of the 400 m loss for about 1.5× time. **Use 200 m centre-sampled fields (prep), no dual.** Worker RSS: 43 MB after loading (50 m), 74 MB after routing.

**Pi 3B extrapolation** [ASSUMED factor: ×15 typical, ×25 pessimistic for memory-bound gathers on a 512 KB-L2 Cortex-A53 at 1.2 GHz plus possible thermal or undervoltage throttling]:

| Level | Cycle = optimal course + forced leg (laptop max) | Pi ×15 | Pi ×25 | Fits 300 s cadence / 60 s timeout? |
|---|---|---|---|---|
| L0 (25 m, 5°, full schedule) | ≈ 0.47 + 0.12 = 0.6 s | ≈ 9 s | ≈ 15 s | Yes (≥ 20× margin) |
| L1 (10°) | ≈ 0.5 s | ≈ 7 s | ≈ 12 s | Yes |
| L2 (L1 + 15/30-min steps) | ≈ 0.4 s | ≈ 6 s | ≈ 10 s | Yes |

Geodesic fields on the Pi: precompute them in prep (laptop) for the library marks. For marks created or moved on the Pi, compute a 400 m field in the worker (≈ 3–5 s on the Pi [ASSUMED ×15–25]) and cache it by mark id and position.

**Gate recommendation for 2026-11-09:** run `jabuka-route-bench` on the Pi with the real race pack (or the committed fixture pack). It reports p50/p95/max cycle time per level (L0…L4 per the CONTEXT ladder) and the core 1 Hz tick jitter while routing. **Pass at the first level whose p95 cycle ≤ 30 s and tick jitter ≤ 200 ms.** Expected: L0 passes. Degrade ladder (CONTEXT order) as concrete settings: L1 `hdg_step_deg=10`; L2 `dt_schedule=((3600,900),(inf,1800))`, `sector_deg=2`; L3 `max_marks_ahead=2`; L4 `cadence_s=600`; L5 `forced_every_n_cycles=2`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GRIB decoding (CCSDS, GRIB1 tables, grids) | A GRIB parser | pygrib 2.1.8 (bundled eccodes) | CCSDS packing, bitmaps, parameter tables, grid geometry |
| Polygon buffering / coastline polygonize | Own offsetting/ring assembly | shapely 2.2 (`linemerge`, `polygonize`, `buffer`, `orient`) | Robust topology; 0.5 s for the whole area |
| Current download/auth | HTTP calls to the Copernicus API | `copernicusmarine subset` run by the user | Auth, catalogue versions, dataset parts |
| Process timeouts | Threads + flags | `ProcessPoolExecutor` + kill helper (3.14 `kill_workers`, 3.13 `_processes`) | A thread cannot be killed; the GIL would block the asyncio loop |
| Oracle routing | A second isochrone implementation for tests | libweatherrouting 0.2.3 (open-water legs) + analytic VMG | Independent implementation |
| Wind/current sign conventions | New inline maths | `jabuka.common.conventions` (+ vectorised twins golden-tested against it) | Single tested boundary (Phase 1) |

**Key insight:** what you do have to build (vectorised isochrones, raster sampling, geodesic ranking) is small. The traps are in the data edges: crop margins, minute-based forecast times, masked cells, row order, sign conventions. Every one of them showed up in this session's prototypes.

## Common Pitfalls

### Pitfall 1: Heading/TWA sign
**What goes wrong:** the route's tacks are mirrored (port ↔ starboard). "On reste" then holds the wrong tack and the countdown is wrong.
**Why:** the project convention is `twd = hdg + twa` with TWA "negative = port" [VERIFIED: `src/jabuka/common/conventions.py:82` `return TrueWind(twa=twa, tws=tws, twd=wrap_2pi(hdg + twa))`; `:8` "TWA/AWA are signed, negative = port"]. So **hdg = twd − twa**. The ARCHITECTURE Pattern 5 snippet has `hdg = twd[:, None] + twa` (ARCHITECTURE.md:195).
**How to avoid:** a golden test asserting that the vectorised router helper agrees with `conventions.true_wind_from_apparent`/`apparent_from_true` on both tacks.

### Pitfall 2: Isochrone front trapped behind islands
**What goes wrong:** "max steps" / "no valid expansion", or wildly different ETAs between reruns, on legs entering or leaving the archipelago.
**Why:** the farthest-from-origin point in a bearing sector may sit in a dead-end bay. Long steps cannot bend through channels.
**How to avoid:** geodesic ranking, the land-proximity fine-step rule, and a regression test with the 8 scenarios above.
**Warning signs:** `steps` near `max_steps`; ETA jumps > 10 % between consecutive identical requests.

### Pitfall 3: Crop exactly at the bbox
Edge columns disappear (ICON-EU lost 16.3E; EWAM lost 15.0E to float rounding). Crop with ±0.25° and assert the mark coverage.

### Pitfall 4: ICON-EU forecastTime unit
`forecastTime` 1440 means minutes (+24 h). When a GRIB fixture was edited, setting `forecastTime=6` produced a valid time of 18:06. Always use `g.validDate` and assert hourly spacing.

### Pitfall 5: Partial DWD run
Files of the newest run appear over ~50 min. Picking a run by its directory alone yields missing hours. Select only runs whose needed steps all exist.

### Pitfall 6: EWAM row order and land bitmap
EWAM rows are N→S and ICON-EU rows are S→N. Masked land cells appear as masked arrays. Normalise to ascending latitude and fill explicitly.

### Pitfall 7: Boat or target inside the dilated mask
At the dock or close to shore, every segment from the start is "on land", so routing fails at the marina. Snap to the nearest clear cell (Pattern 5), and validate rounding waypoints when the course loads.

### Pitfall 8: Forced route impossible because of land
Holding the current tack into a shore makes the forced routing fail. Release the constraint at the first fully blocked step and report "virement imposé".

### Pitfall 9: Negative or noisy "cost of not tacking"
Discretisation makes the forced route occasionally a few seconds better (measured −0.2 min). Clamp at 0 and display "< 1 min".

### Pitfall 10: Bias learned from manoeuvres / Jabuka / calm
TWD swings through tacks, the compass is wrong near Jabuka, and direction is undefined in calm. Use the gate in Pattern 8 (180 s after a tack, TWS > 4 kn, zone freeze, ≥ 300 gated s before valid).

### Pitfall 11: fork start method on the Pi
Python 3.13 defaults to `fork`; the laptop's 3.14 defaults to `forkserver`. Tests pass on 3.14 while forking a threaded asyncio process on the Pi. Pass `mp_context` explicitly.

### Pitfall 12: Pi dependency lock
`tests/deploy/test_lock.py` asserts that `deploy/requirements.in` equals the `[project].dependencies` pins, and that the lock contains exactly `EXPECTED_LOCKED` [VERIFIED: tests/deploy/test_lock.py:11-29, which lists `"annotated-doc"`, `"annotated-types"`, `"anyio"`, `"click"`, `"fastapi"`, `"h11"`, `"idna"`, `"opentelemetry-api"`, `"pydantic"`, `"pydantic-core"`, `"pyfastnet"`, `"pyserial"`, `"starlette"`, `"typing-extensions"`, `"typing-inspection"`, `"uvicorn"`, `"websockets"`]. Adding `numpy==2.5.4` means changing pyproject, requirements.in, re-locking (`bash scripts/build-wheelhouse.sh --relock`) and adding `"numpy"` to `EXPECTED_LOCKED`. **Phase 2 (parallel) may also add runtime deps such as `pmtiles`.** One plan must own this edit to avoid conflicting relocks.

### Pitfall 13: Wall-clock creep
The no-wallclock test only scans `core/` and `common/` [VERIFIED: tests/test_no_wallclock.py:43 `files = sorted((PKG / "core").glob("*.py")) + sorted((PKG / "common").glob("*.py"))`; banned calls at :12 are `("time", "time"), ("time", "monotonic"), ("datetime", "now"), ("datetime", "utcnow")`]. Add `route/` (and `nav/`) to the scan. The router gets `t0` in the request, and `time.perf_counter` (not banned) is used only for timing diagnostics.

### Pitfall 14: GRIB1 parameter tables
The same parameter number maps to different shortNames depending on centre/table (`rsn` vs `u`). Match on several keys and print what was found.

## Code Examples

### Vectorised scanline rasterisation (no GDAL), verified 100 % against shapely
```python
# Source: scratchpad prototype rasterize_proto.py (executed this session)
def rasterize(geom, x0, y0, cell, nx, ny):
    """Cell (r, c) centre = (x0+(c+.5)cell, y0+(r+.5)cell); True where the centre is inside."""
    rings = []
    for poly in getattr(geom, "geoms", [geom]):
        rings.append(np.asarray(poly.exterior.coords))
        rings.extend(np.asarray(r.coords) for r in poly.interiors)
    a = np.concatenate([r[:-1] for r in rings]); b = np.concatenate([r[1:] for r in rings])
    ya, yb = (a[:, 1] - y0) / cell - 0.5, (b[:, 1] - y0) / cell - 0.5
    r0 = np.clip(np.ceil(np.minimum(ya, yb)).astype(np.int64), 0, ny)
    r1 = np.clip(np.ceil(np.maximum(ya, yb)).astype(np.int64), 0, ny)   # half-open rows
    n = np.maximum(r1 - r0, 0)
    idx = np.repeat(np.arange(len(a)), n)
    rows = np.repeat(r0, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    t = (rows - ya[idx]) / (yb[idx] - ya[idx])
    xc = (a[idx, 0] + t * (b[idx, 0] - a[idx, 0]) - x0) / cell - 0.5
    cols = np.clip(np.ceil(xc).astype(np.int64), 0, nx)
    tog = np.zeros((ny, nx + 1), dtype=np.int32)
    np.add.at(tog, (rows, cols), 1)
    return (np.cumsum(tog, axis=1)[:, :nx] & 1).astype(bool)   # even-odd fill
```

### Coastline ways → land polygons (OSM "land on the left")
```python
# Source: scratchpad prototype landmask_proto.py (446 land faces, 0 unclassified)
merged = linemerge(lines)                                   # coastline LineStrings, local metric frame
merged = list(getattr(merged, "geoms", [merged]))
parts = []
for ls in merged:                                           # clip every chain/ring to the work frame
    g = frame.intersection(ls)
    parts.extend(getattr(g, "geoms", [g]) if not g.is_empty else [])
coast_dir = set()                                           # directed segments, coords rounded to mm
for ls in parts:
    c = np.round(np.asarray(ls.coords), 3)
    coast_dir |= {(tuple(c[i]), tuple(c[i + 1])) for i in range(len(c) - 1)}
land = []
for f in polygonize(unary_union(parts + [frame.exterior])):
    f = shapely.geometry.polygon.orient(f, 1.0)             # exterior CCW, holes CW: face on the LEFT
    verdict = None
    for ring in [f.exterior, *f.interiors]:
        c = np.round(np.asarray(ring.coords), 3)
        for i in range(len(c) - 1):
            a, b = tuple(c[i]), tuple(c[i + 1])
            if (a, b) in coast_dir: verdict = True; break   # same direction as the coastline -> land
            if (b, a) in coast_dir: verdict = False; break  # reversed -> water
        if verdict is not None: break
    if verdict: land.append(f)
land = unary_union(land)
```

### Segment check: coarse pass then fine pass (half a cell)
```python
# Source: scratchpad prototype iso_proto.py LandMask.segments_clear
def _sample(grid, cell, x0, y0, ax, ay, bx, by, spacing):
    L = np.hypot(bx - ax, by - ay)
    k = np.maximum(np.ceil(L / spacing).astype(np.int64), 1)
    fr = np.minimum(np.arange(k.max() + 1)[None, :] / k[:, None], 1.0)   # pad with the endpoint
    xs = ax[:, None] + fr * (bx - ax)[:, None]; ys = ay[:, None] + fr * (by - ay)[:, None]
    c = ((xs - x0) / cell).astype(np.int64); r = ((ys - y0) / cell).astype(np.int64)
    out = (r < 0) | (r >= grid.shape[0]) | (c < 0) | (c >= grid.shape[1])
    return (out | grid[np.clip(r, 0, grid.shape[0] - 1), np.clip(c, 0, grid.shape[1] - 1)]).any(axis=1)

def segments_clear(self, ax, ay, bx, by):
    ok = np.ones(len(ax), bool)
    near = _sample(self.near, self.bcell, self.x0, self.y0, ax, ay, bx, by, self.bcell)
    idx = np.nonzero(near)[0]
    if len(idx):
        ok[idx] = ~_sample(self.m, self.cell, self.x0, self.y0, ax[idx], ay[idx], bx[idx], by[idx], self.cell * 0.5)
    return ok
```

### Geodesic distance field (numpy, prep) used for sector ranking
```python
# Source: scratchpad prototype iso_proto.py GeoField (200 m centre-sampled grid: ~2 s on the laptop)
blocked = fine_mask[B // 2::B, B // 2::B]          # centre-sampled: a channel >= 2 cells wide stays open
d = np.full((ny + 2, nx + 2), np.inf); d[tr + 1, tc + 1] = 0.0
steps = [(-1,0,h),(1,0,h),(0,-1,h),(0,1,h),(-1,-1,h*1.4142),(-1,1,h*1.4142),(1,-1,h*1.4142),(1,1,h*1.4142)]
while True:
    cur = d[1:-1, 1:-1]; best = cur.copy()
    for dr, dc, w in steps:
        np.minimum(best, d[1+dr:ny+1+dr, 1+dc:nx+1+dc] + w, out=best)
    best = np.where(~blocked, best, np.inf); best[tr, tc] = 0.0
    if np.array_equal(best, cur): break
    d[1:-1, 1:-1] = best
# ranking key in a sector: geo(x, y) = max(field[cell(x, y)], euclid(x, y, target)); smaller wins
```

### One expansion step (shapes: n parents × H headings)
```python
# Source: scratchpad prototype iso_proto.py route() (conventions: hdg = twd - twa, tack = sign(twa))
twd, tws = wind.sample(t, px, py)                              # per parent, bias applied
up, down = polar.targets(tws)
twa_abs = np.concatenate([np.broadcast_to(base, (n, len(base))), up[:, None], down[:, None]], axis=1)
twa = np.concatenate([twa_abs, -twa_abs], axis=1)              # deg
tack = np.where(twa > 0, 1, -1).astype(np.int8)
if force_until is not None and t < force_until:                # stay-on-this-tack
    keep = tack[0] == tack0; twa, tack = twa[:, keep], tack[:, keep]
bsp = polar.speed(tws[:, None], np.abs(twa)) * eff * wave_factor
hdg = twd[:, None] - np.radians(twa)
flip = (tack != ptack[:, None]) & (ptack[:, None] != 0)
d = bsp * np.maximum(dt - flip * penalty_s, 0.0) / 3600.0
cx = px[:, None] + d * np.sin(hdg) + cu[:, None] * dt / 3600
cy = py[:, None] + d * np.cos(hdg) + cv[:, None] * dt / 3600
# flatten → sector = floor(bearing_from_origin / 1.5°) → sort by (sector, geo) → land-check top 4 → keep first valid
```

### Killing a stuck worker on 3.13 and 3.14
```python
def _kill_pool(pool) -> None:
    kill = getattr(pool, "kill_workers", None)          # Python >= 3.14
    if kill is not None:
        kill()
    else:                                               # Python 3.13 (Pi): private but stable attribute
        for p in list(getattr(pool, "_processes", {}).values()):
            p.kill()
    pool.shutdown(wait=False, cancel_futures=True)
```

### Bias application to u/v (air motion), clockwise rotation of the FROM direction
```python
w = math.exp(-max(0.0, t - t_obs) / tau_decay)
phi = w * d_dir
u2 = (u * math.cos(phi) + v * math.sin(phi)) * (1.0 + w * (k - 1.0))
v2 = (-u * math.sin(phi) + v * math.cos(phi)) * (1.0 + w * (k - 1.0))
```

### Tiny GRIB fixtures generated in tests (no large binaries in git)
```python
# Verified this session: edit a committed ~200-byte GRIB2 template with pygrib.
g = pygrib.open(TEMPLATE).message(1)
g["Ni"], g["Nj"] = 23, 21
g["latitudeOfFirstGridPointInDegrees"], g["longitudeOfFirstGridPointInDegrees"] = 42.75, 14.875
g["latitudeOfLastGridPointInDegrees"], g["longitudeOfLastGridPointInDegrees"] = 44.0, 16.25
g["packingType"] = "grid_simple"; g.values = np.full((21, 23), 3.5)
g["forecastTime"] = 360            # MINUTES in the ICON-EU template (6 h)
path.write_bytes(g.tostring())
# GRIB1 fixture: eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib1") (dev extra), read back by pygrib.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pure-Python per-point isochrones (lwr) | numpy vectorised step | — | 4.7–8.5 s vs ~40 ms for a 20 nm leg on the laptop |
| `ProcessPoolExecutor` private `_processes` to kill | `kill_workers()` / `terminate_workers()` | Python 3.14 | The Pi (3.13) still needs the fallback |
| Default `fork` start method | `forkserver` default on Linux | Python 3.14 | Pass `mp_context` explicitly for both |
| OSM land-polygons bulk download | Overpass coastline for a small bbox + polygonize | (this project) | 4.9 MB instead of a large zip; works when osmdata is down |

**Deprecated/outdated:** ARCHITECTURE.md Pattern 5's "keep the farthest-from-origin point per sector" for an archipelago course (replaced by geodesic ranking), and its `hdg = twd + twa` line (sign).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pi 3B is ×15 (typical) to ×25 (pessimistic) slower than the i7-7700K for this numpy workload | Benchmark | If worse than ×50, L0 exceeds 30 s per cycle. The degrade ladder covers it; the 2026-11-09 Pi run decides |
| A2 | Wave factor constants (5/3/1.5 %/m, floor 0.7) and Hs(TWS) ≈ 0.7 × WMO probable height | Pattern 4 | ETA bias in waves. Tunable settings; LOW confidence |
| A3 | Bias τ_EMA 10 min, τ_decay 2.5 h, gate thresholds (4 kn, 3°/s, 300 s) | Pattern 8 | Bias too jumpy or too sluggish. Shown on screen, can be disabled |
| A4 | Copernicus subset NetCDF layout `uo(time, latitude, longitude)` with NaN/_FillValue on land | Data Sources | Importer tweak. Test with the user's real file before the race |
| A5 | OSM submerged rocks with unknown depth are all hazards for a ~2.1 m draft | Land Mask | Over-conservative routes near rocks. Measured: no channel closes |
| A6 | land-polygons-split-4326.zip is several hundred MB (osmdata unreachable this session) | Alternatives | Irrelevant if Overpass is the default |
| A7 | Importing numpy in the core costs ~1 s and +10–20 MB RSS on the Pi | Pattern 10 | Slightly slower core start. Alternatively a pure-Python scalar `at()` |
| A8 | Organiser forecast will be a regular GRIB1/2 with 10 m wind | Pattern 2 | Clear error message; fall back to ICON-EU |

## Open Questions (RESOLVED)

Resolution (2026-11-07, plans 03-01..03-06): bias estimator lives in route/bias.py (03-04), wired into the wind pipeline in 03-05; rounding sides and start/finish come from the Phase 2 course model (confirm at SI briefing — human item); cost horizon = current leg (cost_horizon="leg"), whole course only if the Pi bench shows headroom; polar = Phase 2 placeholder ORC X-35 polar until the owner provides the real one (human item).

1. **Where does the bias estimator live relative to the Phase 2 wind pipeline?** We know Phase 2 owns `nav/wind.py` (VectorEma, arbitration) and `nav/tacks.py`. It is unclear whether Phase 2 exposes a tack-event stream and a "steady" signal. Recommendation: Phase 3 adds `bias.py` beside the Phase 2 wind module and consumes the tack detector. If Phase 2 has not shipped the detector, Phase 3 implements it in `nav/tacks.py` (Pattern 11).
2. **Rounding sides and the start/finish line** are not in the NoR (Phase 2 research). Phase 3 consumes whatever the Phase 2 course model holds. Rounding radii must clear the mask (validated on load).
3. **Cost horizon:** current leg (default, cheap) vs whole course. Recommendation: `cost_horizon="leg"`. Switch to "course" only if the Pi bench shows ample margin.
4. **Real X35 polar** is still a placeholder. All ETA numbers scale with it. The router takes the Phase 2 Polar object.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14 / 3.13 dev venvs | tests | ✓ (`.venv`, `.venv313`) | 3.14.7 / 3.13 | — |
| numpy in project venvs | router | ✗ (not yet installed) | — | Install via pyproject (plan task) |
| opendata.dwd.de (ICON-EU, EWAM) | prep | ✓ | — | Organiser/OpenSkiron GRIB via the generic importer |
| overpass-api.de | land mask prep | ✓ (needs a User-Agent; plain curl got 406) | 0.7.62.11 | Cached JSON in the race-pack source dir |
| osmdata.openstreetmap.de | land-polygons (CONTEXT source) | ✗ (connection refused 2026-11-06) | — | Overpass (verified) |
| Copernicus Marine | current file | catalogue ✓, download needs the user's account | toolbox 2.5.1 | Route without current (ROUT-04 optional) |
| Raspberry Pi 3B | benchmark gate | ✗ from here | — | Human-run `jabuka-route-bench` on 2026-11-09 |
| scipy | — | not needed (research analysis only) | — | — |

**Missing with no fallback:** none blocking. The Pi benchmark is a human checkpoint.

## Verification Map (ROADMAP Phase 3 success criteria → tests)

`workflow.nyquist_validation` is `false`, so this is a plain mapping. Framework: pytest 9.2.0 via `scripts/check.sh` on 3.14 and 3.13. Quick run: `.venv/bin/python -m pytest tests/route tests/prep -q`.

| SC | Behaviour | Automated on the laptop | Human / Pi |
|----|-----------|-----------------|------------|
| 1 | Prep: run selection, download, decode/crop, npz schema | Unit tests on saved DWD listing HTML fixtures (run choice incl. partial run); decode/crop on generated GRIB2 fixtures (template ≈ 200 B) incl. row flip, margin, minute-based forecastTime; GRIB1 via eccodes fixture (skip if absent); generic importer error messages; Copernicus importer on a tiny NetCDF written in the test (netCDF4) | Real `jabuka-prep wind/waves` run on the laptop (network), and the Friday 13 Nov final run (runbook) |
| 1 | Coverage warnings (GRIB-02) | Truncated packs (missing hours, 3-hourly gap, mark outside the grid, NaN) → expected alerts | — |
| 1 | GPS + GRIB-only mode | Sim with the Fastnet bus silent → wind source "GRIB", laylines/route still produced | Visual badge check on the tablet |
| 2 | Route never crosses land; channels open | Committed fixture `landmask_race_25m.npz` (~65 KB, ODbL attribution). (a) segments (43.75, 15.78) → (43.705, 15.80) through Prvić, (43.69, 15.815) → (43.69, 15.87) through Zlarin, and (43.735, 15.75) → (43.705, 15.78) through Tijat are rejected, while the control (43.60, 15.60) → (43.55, 15.65) is clear [VERIFIED on the 25 m / 100 m mask this session; all endpoints in water]; (b) known sea/land points; (c) flood/route Vodice → open sea succeeds and passes the Prvić–Tijat gate (43.7229, 15.7828) ± 0.5 nm or the Prvić–mainland gate; (d) routes for courses A/B under SW12/NE18/real-wind fixtures: every polyline segment valid, no point within the Plić Sestre hazard disc, Blitvenica/Jabuka passed on the configured side (signed winding of the route around the mark); (e) invalid route injected → discarded + alert | Visual check of the route on the map |
| 2 | Optimality sanity | Uniform-wind beat vs analytic VMG (≤ 1 %); open-water legs vs libweatherrouting (`importorskip`; tolerance: lwr ETA + gap/speed within max(3 %, 5 min)); golden test: tack points on the Phase 2 analytic laylines (± one step) | — |
| 2 | Waves/current effects | Uniform Hs field slows the upwind ETA by the configured factor; a uniform current shifts the arrival as expected; water-referenced wind | — |
| 2 | Target TWA stays right through shifts | Route-following test: rotate TWD 15° after routing → target TWA unchanged, heading = TWD − TWA | — |
| 3 | Rerun timer/triggers, non-blocking | Supervisor tests with SimClock + fake executor (trigger matrix, coalescing, timeout → kill + recreate on both Python versions, crash → BrokenProcessPool → recreate); **tick-latency test**: 1 Hz core tick jitter < 200 ms while a real worker routes the full fixture course | Pi: tick jitter measured by the bench |
| 3 | Hysteresis | Identical rerun → route kept; ETA gain 2 min → kept; gain 6 min → replaced; forced trigger → replaced | — |
| 3 | Bias shown / fades / off / frozen | Estimator unit tests: gate (tack < 180 s, BSP, staleness, calm, Jabuka), circular mean across ±180°, clamps, decay formula, u/v rotation sign, manual path | Visual on the helm |
| 4 | Countdown, cost, "On reste", missed tack | Unit tests on synthetic routes (first side change, projection-based countdown); forced routing (hold, release at land, clamp); closed-loop sim (Phase 2 L2 boat) that ignores the advised tack → reroute triggered at +120 s and the helm message changes | Tablet UI check (button size, lock mode) |
| 5 | Pi fits cadence | `jabuka-route-bench --quick` smoke test on the laptop (runs, prints levels) | **Human: run on the Pi by 2026-11-09**, record p50/p95/max per level + tick jitter; set the configured level |

Wave 0 gaps: `tests/route/`, `tests/prep/`, `tests/fixtures/route/` (mask fixture + GRIB template + DWD listing HTML + ATTRIBUTION). numpy/pygrib/shapely/netCDF4/weatherrouting are not yet in the dev venvs.

## Security Domain

`security_enforcement: true`, ASVS L1.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (LAN appliance, Phase 1 model) | — |
| V3 Session Management | no | — |
| V4 Access Control | partial | Stay-on-tack/bias toggles are helm actions on the boat LAN (same trust model as Phase 2 course edits) |
| V5 Input Validation | yes | pydantic models for new REST bodies (stay-on-tack, bias toggle, settings); prep CLI validates file types and sizes; race-pack loader validates shapes/dtypes/finite/frame; `np.load(..., allow_pickle=False)` always |
| V6 Cryptography | no (sha256 integrity only) | `hashlib.sha256` of pack files in the manifest |
| V12 Files/Resources | yes | Race-pack paths confined to `--racepack` dir (no traversal); organiser GRIB size cap (e.g. 200 MB); temp files via `tempfile` |
| V14 Configuration | yes | Copernicus credentials never in the repo (user CLI prompt / its own config); `.gitignore` the race pack |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious `.npz` with pickled objects | Tampering / EoP | `allow_pickle=False` (default), test it |
| Crafted GRIB/NetCDF exhausting memory | DoS | Size cap, crop early, run prep on the laptop only |
| Router job never ends (bad pack, pathological wind) | DoS | `max_steps`, 60 s timeout + kill, last good route kept |
| Path traversal in a race-pack import endpoint | Tampering | Resolve and check against the pack root, no user-supplied paths on the Pi API |
| Credential leakage (Copernicus) | Information disclosure | Not stored by jabuka; runbook uses `copernicusmarine login` on the laptop |

## Sources

### Primary (HIGH: tool-verified this session)
- opendata.dwd.de directory listings + 98 ICON-EU files and EWAM SWH/MWD files downloaded and decoded with pygrib 2.1.8 (grid keys, row order, packing, forecastTime unit, availability times).
- `copernicusmarine describe --dataset-id cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m --return-fields all` (2.5.1) and `subset --help`.
- Overpass API (`overpass-api.de`) coastline and hazard queries, OSM base 2026-11-06T02:01Z.
- libweatherrouting 0.2.3 installed source (`routing.py`, `routers/router.py`, `routers/linearbestisorouter.py`, `polar.py`, `grib.py`) and runs.
- PyPI JSON API: versions, wheels (pygrib cp313/cp314 aarch64), first-upload dates, project URLs.
- Python 3.13/3.14 `multiprocessing.get_start_method()` and `ProcessPoolExecutor` source inspection (`kill_workers` only on 3.14).
- Repo files read this session: `src/jabuka/common/conventions.py`, `src/jabuka/common/clock.py`, `src/jabuka/common/units.py`, `tests/test_no_wallclock.py`, `tests/deploy/test_lock.py`, `pyproject.toml`, `deploy/requirements.in`, `.gitignore`.

### Secondary (MEDIUM)
- pygrib docstrings (`data()` subset semantics, `latlons()` supported grids).
- `.planning/research/{STACK,ARCHITECTURE,PITFALLS,SUMMARY}.md`, `.planning/phases/02-*/02-CONTEXT.md`, `02-RESEARCH.md` (marks, polar, course model).

### Tertiary (LOW)
- [Land polygons (osmdata)](https://osmdata.openstreetmap.de/data/land-polygons.html): page unreachable from here; size not confirmed.
- [cyclobs land-polygons-split README](https://cyclobs.ifremer.fr/static/sarwing_datarmor/xsardata/land-polygons-split-4326/README.txt): feature counts only (via web search).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH. Versions and wheels checked; every library exercised.
- Data sources: HIGH for DWD (downloaded and decoded) and Overpass. MEDIUM for Copernicus (catalogue only).
- Land mask and channels: HIGH. Measured with two independent methods (raster distance transform and exact shapely bisection).
- Router architecture: HIGH for feasibility and the pruning finding (8-scenario matrix). MEDIUM for Pi timings (extrapolated).
- Bias, wave and tack constants: LOW (tuning parameters, documented as such).

**Research date:** 2026-11-06
**Valid until:** 2026-11-13 (race-week data sources: re-check DWD run timing on Friday)
