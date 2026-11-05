# Stack Research

**Domain:** Offline embedded sailing race-navigation (live isochrone routing + laylines) on Raspberry Pi 3B, B&G Fastnet ingestion, web UI for an Android tablet
**Researched:** 2026-11-05
**Confidence:** MEDIUM-HIGH overall. Versions were checked live against PyPI, npm, Debian and GitHub on 2026-11-05. Model grid extents were checked by downloading DWD GRIB files and decoding their grid section. The routing performance numbers are estimates and must be benchmarked on day 1.

> **Bottom line:** Use Python 3.13 on Raspberry Pi OS Lite 64-bit (Trixie). Run **fastnet2ip** as its own systemd service and have it broadcast NMEA0183 over UDP. Add **gpsd + chrony** for GPS and the system clock. The app is one **asyncio Python hub** (FastAPI/uvicorn: WebSocket, REST and static files) plus a **numpy-vectorised isochrone router**, written in-house and modelled on libweatherrouting's algorithm, running in a separate niced process. Read GRIBs with **pygrib** and convert them once into a compact `.npz` cube. The frontend is vanilla JS with **MapLibre GL JS 5.x** on a **Protomaps PMTiles** extract, with seamarks extracted from OSM as GeoJSON. No Signal K, no xarray/cfgrib on the Pi, no build toolchain.

---

## Recommended Stack

### Core Technologies

| Technology | Version (verified 2026-11-05) | Purpose | Why Recommended | Confidence |
|---|---|---|---|---|
| **Raspberry Pi OS Lite 64-bit (Trixie / Debian 13)** | Released 2025-10-02. Ships Python 3.13.5, gpsd 3.25, NetworkManager | Base OS on Pi 3B | Trixie has been the current Raspberry Pi OS for over a year and runs on the Pi 3 ("perfectly usable on Pi 3", per Raspberry Pi). **64-bit is required in practice.** PyPI publishes numpy, scipy, shapely, pygrib, eccodeslib and pydantic-core wheels for **aarch64 only, not armv7**, so 32-bit would mean compiling numpy from source or depending on lagging piwheels. Do not upgrade Bookworm in place; flash a clean image. | HIGH |
| **Python** | 3.13 (system) in a venv | Hub, router, GRIB prep | fastnet2ip needs ≥3.11. Under 3.13 you get the latest numpy 2.5.x (numpy ≥2.5 dropped 3.11, so Bookworm would pin you to numpy 2.4.6). | HIGH |
| **fastnet2ip** (+ **pyfastnet**) | 3.3.1 (2026-09-13) / 3.2.1, MIT | Fastnet RS-485 (28800 8O2) to NMEA0183 on UDP :2002 | This is the only maintained open-source Fastnet decoder: 225 commits, last released Sep 2026. It has been tested with the **DTECH USB RS422/485 dongle**. It emits VHW, MWV (apparent and true), MWD (TWD), HDM/HDT, DBT, VTG, VPW, **VDR (set/drift)**, GLL and XDR raw channels. It has a `--file` replay mode, and the repo ships real bus captures. Install it with `pipx install --global`. **Caveat:** it was tested on **H2000/Hydra** buses ("Normal CPU (Wind Board in H2000)" in the captures). There are no captures from a **Hercules 390**, so treat the 390 as plausible but unverified. | HIGH for the tool, MEDIUM for your specific bus |
| **gpsd + chrony** | gpsd 3.25 (Trixie), chrony (Trixie) | VK-162 u-blox (`/dev/ttyACM0`) position and **system clock** | **The clock is the deciding reason.** The Pi has no RTC and there is no internet on board, so after a power cut the clock would be wrong and every GRIB time lookup would be wrong with it. gpsd plus a chrony SHM refclock sets the time from NMEA (±100 ms, plenty). gpsd also handles USB re-plug and exposes clean JSON on :2947. The app talks to gpsd over an asyncio socket with `?WATCH={"enable":true,"json":true}` (~30 lines). | HIGH |
| **FastAPI + uvicorn[standard]** | fastapi 0.162.0, uvicorn 0.54.0 | HTTP API, WebSocket push, static files, tile endpoint | Gives you WebSocket, REST, static files and Pydantic validation in one well-known stack, and every component has aarch64 wheels. Starlette's `FileResponse` supports HTTP Range. Memory is roughly 60–80 MB RSS, which fits in 1 GB. This is the stack an AI-assisted 7-day build is least likely to fumble. | HIGH |
| **numpy** | 2.5.4 (cp313 aarch64 wheel) | Vectorised isochrone router, GRIB interpolation, polar tables, laylines | Vectorising is what makes routing a ~150 nm course in 15-min steps run in seconds rather than minutes on a Cortex-A53 (see the routing section). | HIGH |
| **Own numpy isochrone router** (port of libweatherrouting's `LinearBestIsoRouter`) | n/a (in-house, about 400–600 LOC) | Routing to the next marks | libweatherrouting 0.2.3 is pure-Python scalar loops (72 headings × up to 360 points per step, `latlon3` geodesy per point). It has **no current support** (literally `# TODO: add current factor`) and no wave reduction. Porting the same algorithm to arrays keeps the reuse benefit (GPL is fine) and adds current vectors, a wave factor, tack penalty and a raster land mask. | MEDIUM-HIGH |
| **pygrib** | 2.1.8 (aarch64 wheels for cp311–cp313, eccodes bundled) | Read GRIB1 + GRIB2 | One `pip install` with no system eccodes and no index files. `grbs.select(shortName='10u')` plus `.data(lat1,lat2,lon1,lon2)` crops directly. It handles GRIB1 (some organiser/openskiron files) and GRIB2 (DWD, Météo-France). | HIGH |
| **MapLibre GL JS** | **5.24.0** (pin the last 5.x; 6.16.0 is latest) | Offline map rendering on the tablet | Renders vector tiles, so a tiny PMTiles extract replaces thousands of raster PNGs. It supports **night/red styling by swapping the style** and native rotation (course-up). v5 keeps a **UMD single-file bundle and a WebGL1 fallback**. v6 is ESM-only and **requires WebGL2** (it throws `GPUInitializationError`), which matters because the tablet is unknown. | HIGH |
| **Protomaps basemap (PMTiles)** + go-pmtiles CLI | go-pmtiles 1.31.2, @protomaps/basemaps 5.7.2 | Legal offline OSM basemap for the race area | `pmtiles extract <daily build> race.pmtiles --bbox=15.0,42.8,16.3,44.0 --maxzoom=15` gives a file of a few MB. Licensing is clean (ODbL produced work). By contrast, the **OSMF tile policy explicitly forbids** "download area for offline use" from tile.openstreetmap.org, which rules out the usual Leaflet raster approach. | HIGH |

### Supporting Libraries

| Library | Version | Purpose | When to Use | Confidence |
|---|---|---|---|---|
| `pmtiles` (Python) | 3.8.1 | Read tiles out of `race.pmtiles` on the Pi and serve `/tiles/{z}/{x}/{y}.mvt` (set `Content-Encoding: gzip`) | Always. It avoids relying on HTTP Range from the browser's pmtiles protocol, so MapLibre sees a plain XYZ source. | MEDIUM |
| `pynmea2` | 1.19.0 (stable; last release 2023) | Parse NMEA0183 from fastnet2ip UDP and from replay files | Always. Alternatively hand-parse the ~10 sentences. Either way, **validate checksums and timestamp each value**, because fastnet2ip does no re-broadcast and quiet sources simply stop. | MEDIUM |
| `shapely` | 2.2.0 (aarch64 wheels) | Build the land mask from OSM land polygons with vectorised `contains_xy` | Prep step only (laptop or Pi, once). At runtime the router uses a **pre-rasterised boolean numpy mask** (~50–100 m cells, a few MB) for O(1) point and segment checks. | HIGH |
| `weatherrouting` (libweatherrouting) | 0.2.3 (2025-05; last commit 2026-07), GPL-3 | **Reference oracle** in tests: same polar, same wind function, compare the ETA and path of the numpy router | Dev laptop / CI only. Also a fallback engine if the numpy port slips (with coarse settings `subdiv=3`, 1 h steps). | HIGH |
| `copernicusmarine` | 2.5.1 (2026-11-03) | Download Med currents `cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m` and Med waves (MEDSEA_ANALYSISFORECAST_WAV_006_017) as NetCDF | **Laptop only**, before departure. Needs a free Copernicus Marine account. Convert to the same `.npz` cube format as the wind. | MEDIUM |
| `netCDF4` | 1.7.5.1 (abi3 aarch64 wheel) | Read Copernicus NetCDF if conversion must happen on the Pi | Only if no laptop is available at the dock. | MEDIUM |
| `eccodes` + `eccodeslib` + `cfgrib` + `xarray` | 2.50.0 / 2.50.0.33 / 0.9.15.1 / 2026.9.0 | Inspect odd GRIBs (e.g. the organiser's file) on the laptop | **Laptop only.** They work on aarch64 (`eccodeslib` now ships manylinux_2_28 aarch64 wheels), but the import cost (pandas + xarray) and `.idx` side files are wrong for a 1 GB Pi with a read-only root. | HIGH |
| `osmium-tool` (apt) | Debian package | Extract `seamark:*` nodes and ways from Geofabrik `croatia-latest.osm.pbf` into a GeoJSON overlay (lights, buoys, dangers) | Prep step on the laptop: `osmium tags-filter croatia-latest.osm.pbf nwr/seamark:type -o seamarks.osm.pbf`, then `osmium export` to GeoJSON, clipped to the bbox. | MEDIUM |
| `ecmwf-opendata` | 0.3.35 | Optional second wind model (ECMWF IFS/AIFS open data, GRIB2) for comparison | Laptop, if time allows. Never the critical path. | LOW-MEDIUM |

### Development Tools

| Tool | Version | Purpose | Notes |
|---|---|---|---|
| `uv` | 0.13.7 | Fast venv and dependency management (aarch64 binary available) | Use `uv pip compile` to make a lock file on the laptop and `uv pip sync` on the Pi, which avoids slow pip resolution on the Pi 3B. Keep a **wheelhouse** (`uv pip download`) on the laptop so you can reinstall the Pi with no internet at the marina. |
| `pytest` | 9.2.0 | Router/polar/GRIB/layline unit tests plus replay integration tests | Golden tests: route Vodice to Jabuka under a constant-wind field and check against analytical VMG and libweatherrouting. |
| `ruff` | 0.17.4 | Lint/format | Zero config. |
| fastnet2ip `--file` + repo `tools/playback_fn.py` | 3.3.1 | Replay real Fastnet captures into the full pipeline | Repo captures live in `tests/data/` and the pyfastnet `captures/` directory (not in the pip package), so clone the repos. `--file` paces at about 5 KB/s, not wire speed. Use `playback_fn.py` for realistic timing. |
| `gpsfake` (gpsd-clients) | 3.25 | Replay NMEA GPS logs through gpsd | Pairs with a small NMEA UDP sender to simulate a whole race leg on the laptop. |
| Chrome remote debugging (`chrome://inspect`) | n/a | Debug the web app on the Android tablet over USB | Essential for WebGL/WebSocket issues on the real tablet. |

---

## Installation

```bash
# --- On the Pi (Raspberry Pi OS Lite 64-bit Trixie), with internet at the dock ---
sudo apt update
sudo apt install -y gpsd gpsd-clients chrony pipx python3-venv osmium-tool
sudo pipx install --global fastnet2ip          # 3.3.1; pipx >= 1.5 required (Trixie has 1.7)

# App venv
python3 -m venv /opt/jabuka/venv
/opt/jabuka/venv/bin/pip install \
  "numpy==2.5.*" "pygrib==2.1.8" "fastapi==0.162.*" "uvicorn[standard]==0.54.*" \
  "pynmea2==1.19.0" "pmtiles==3.8.1" "shapely==2.2.*"

# --- On the dev laptop (x86_64) additionally ---
pip install weatherrouting==0.2.3 copernicusmarine==2.5.1 cfgrib eccodes xarray netCDF4 pytest ruff
# go-pmtiles v1.31.2 binary from github.com/protomaps/go-pmtiles/releases
pmtiles extract https://build.protomaps.com/<YYYYMMDD>.pmtiles race.pmtiles \
  --bbox=15.0,42.8,16.3,44.0 --maxzoom=15

# --- Frontend (vendored, no build step) ---
# Download maplibre-gl@5.24.0 dist/maplibre-gl.js + .css into static/vendor/
# Generate the basemap style JSON once with @protomaps/basemaps 5.7.2 (node, laptop), save as static/style-day.json + style-night.json
# Copy fonts (glyph PBFs) + sprites from github.com/protomaps/basemaps-assets into static/ — MapLibre will NOT render labels offline without them
```

---

## Answers to the Specific Questions

### 1. Fastnet ingestion: fastnet2ip
- **Maturity:** Active, single maintainer. fastnet2ip 3.3.1 and pyfastnet 3.2.1 were both released 2026-09-13. The repo has a conformance test suite (`conformance/vectors.json`) and 9,648 real captured frames. It is MIT-licensed.
- **Tested hardware:** Raspberry Pi 4/5/Zero 2W, Mac, **DTECH USB RS422/RS485**, Waveshare RS485 CAN HAT. The Pi 3B is not listed, but nothing in the tool is Pi-model-specific. The load is about 2.4 KB/s of serial data.
- **Instruments:** The captures and naming are **H2000/Hydra**. The channel map includes everything needed: Boatspeed 0x41, Heading 0x49, TWS 0x55/0x56, TWA 0x59, **TWD 0x6D**, **Tidal Drift 0x83 / Set 0x84**, Target Boatspeed 0x7D and "Heading on Next Tack" 0x9A. A "Hercules 2000" is H2000-family, so expect it to work. A **Hercules 390** (older generation, same Fastnet physical layer) is **unverified**, so expect possible `bandg.unknown.0x..` channels. Mitigation: record raw bus bytes on 12 Nov with `record_fn.py` before anything else.
- **Wiring:** Fastnet White = Data+, Green = Data−, two-wire. No termination advice is given, so connect listen-only.
- **Decision:** Run it as a **separate systemd service** with `--output nmea0183 --serial /dev/fastnet --host <AP broadcast> --udp-port 2002`. This gives you crash isolation, a single NMEA ingestion path for live, replay and simulator, and a **free backup feed**: OpenCPN (Tactics/Weather Routing) on a laptop, or any Android NMEA app, can read UDP :2002 off the boat Wi-Fi if the custom app fails. Use `--ignore-gps` if the Hercules relays the same GPS. Do not also import pyfastnet in the hub, because only one process can own the serial port.

### 2. Data hub: Signal K vs custom asyncio hub; gpsd vs pyserial
- **Signal K: not worth its weight here.** signalk-server 2.36.0 requires **Node ≥22 (24 recommended)**, but Trixie ships Node 20.19, so you would need NodeSource. Node 24 has no 32-bit ARM support. On a 1 GB Pi 3B it competes with the router for RAM and CPU, and it adds a plugin/JS layer that a 7-day project cannot afford to debug. Its main attractions (Freeboard-SK laylines, a data browser) do not do routing, which is the core value. **Borrow its vocabulary instead.** pyfastnet already uses Signal K paths and SI units, so use the same key names and units in the hub's state store. That leaves a Signal K bridge possible later. (Confidence: HIGH)
- **Custom hub:** a single Python asyncio process. It runs a UDP NMEA listener (`asyncio.DatagramProtocol`), a gpsd JSON client, a timestamped latest-value store with per-source staleness, a 1 Hz layline/target computation, WebSocket fan-out, REST for marks/course/settings/GRIB selection, and a 1 Hz CSV/NDJSON logger to `/data`.
- **gpsd vs pyserial: use gpsd**, for the clock discipline (chrony), hot-plug recovery and `gpsfake` replay (see above). Pin device names with udev rules (`/dev/gps`, `/dev/fastnet` via `/dev/serial/by-id`), because the DTECH (ttyUSB) and the VK-162 (ttyACM) can enumerate in any order. Configure `/etc/default/gpsd` with `DEVICES="/dev/gps" GPSD_OPTIONS="-n"` and disable USBAUTO probing of `/dev/fastnet`, **otherwise gpsd may grab and reconfigure the RS-485 port**. (Confidence: HIGH)

### 3. Routing engine
- **libweatherrouting 0.2.3:** GPL-3. Its only dependency is `latlon3`. It has a clean pluggable `get_wind_at(t, lat, lon) -> (twd_deg, tws_ms)`, `point_validity` and `line_validity`, plus `Polar` (whitespace TWA\TWS matrix) and GeoJSON output. It is pure-Python scalar loops: 72 headings × up to 360 isochrone points per step (`subdiv=1°`), each doing polar lookup, destination point, distance and loxodrome. It has **no current and no waves**. A 2026-07 PR sped up `get_speed` with bisect, but the structure remains O(points × headings) in the interpreter.
- **Performance estimate (MEDIUM, must benchmark):** a ~150 nm course at 15-min steps is about 80–100 steps × ~10–25k expansions. Pure Python at roughly 20–40 µs per expansion on a Cortex-A53 gives **minutes per full route**. numpy vectorisation (one array op per step over all expansions, ~25k elements) brings this to roughly **20–60 ms per step, i.e. 2–6 s per route**. That is compatible with "re-run every few minutes", and leaves headroom for 5° headings and two to three marks ahead.
- **Decision:** Write a numpy isochrone router that copies libweatherrouting's algorithm: expand all headings, prune by bearing-from-start sectors keeping the best progress to the mark, then backtrack. Extend it with:
  1. the current vector added to the boat velocity;
  2. a wave factor applied to polar speed;
  3. a tack/gybe time penalty;
  4. the raster land mask, used for point and segment checks;
  5. the live-wind-corrected wind function.

  Keep libweatherrouting as the test oracle and as an emergency fallback.
- **Others considered:** OpenCPN weather_routing_pi (C++, desktop GUI plugin, on-demand only, ignores measured wind; read it as an algorithm reference only). VISIR-2 (research code, heavy, aimed at motor/sail ship routing with xarray/numba; overkill). qtVlm and Expedition are not open source.

### 4. GRIB reading on the Pi
- **Use pygrib 2.1.8.** Its aarch64 wheels bundle eccodes and cover GRIB1 and GRIB2.
- **Pipeline:** a `prep_weather` CLI that runs on the laptop or the Pi. It reads the GRIB(s), extracts 10u/10v (also gust `vmax_10m` and `pmsl` for display), crops to the race bbox, and writes `wind_<model>_<run>.npz`. That file holds `lat[]`, `lon[]`, `valid_time[]` (UTC epoch) and `u[t,y,x]`, `v[t,y,x]` as float32, a few hundred KB. At runtime the router does `np.load` (mmap) plus its own trilinear interpolation (time × lat × lon, about 30 lines of numpy). It never imports pygrib, so startup is fast and memory stays small.
- **Not on the Pi:** cfgrib/xarray, because of import weight, `DatasetBuildError` on heterogeneous GRIBs, and `.idx` files written next to the GRIB (which fails on a read-only FS). They are fine on the laptop for inspection. On Debian you could also use `apt install python3-eccodes`/`libeccodes-tools`, but this is unnecessary.

### 5. Offline weather sources for the Adriatic (verified where noted)

| Source | Coverage of race area | Resolution / horizon | Access | Verdict | Confidence |
|---|---|---|---|---|---|
| **ICON-EU (DWD opendata)** | **Yes.** Grid 29.5–70.5 N, −23.5–62.5 E (decoded from a live file) | 0.0625° (~7 km). 00/06/12/18 UTC runs to **+120 h** (hourly to +78, then 3-hourly). 03/09/15/21 runs to +51 h | `opendata.dwd.de/weather/nwp/icon-eu/grib/<run>/u_10m/`, one bz2 GRIB2 per variable per step, **only about 24 h of runs kept**. Script the download of `u_10m`, `v_10m`, `vmax_10m`, `pmsl`. | **Primary model.** Covers the whole 38 h race from the Friday 06Z run. | HIGH |
| **ICON-D2 (DWD)** | **Partial: Jabuka is OUTSIDE.** The regular grid is 43.18–58.08 N, −3.94–20.34 E (decoded). Jabuka (43.10 N) is about 8 km south of the edge. Vodice, Plić Sestre and Blitvenica are inside, at the domain's southern boundary zone. | 0.02° (~2.2 km), every run to **+48 h** | Same opendata server | Secondary, for the **northern part only**. Blend or switch to ICON-EU south of about 43.3 N. Boundary-zone values are lower quality. | HIGH (extent), MEDIUM (usefulness) |
| **AROME 0.025° (Météo-France, grid EURW1S40)** | Nominally **yes**: 37.5–55.4 N, 12 W–**16 E**. But the race area sits right on the **east boundary**, in the LAM relaxation zone. | ~2.5 km, ~42–51 h | data.gouv.fr / meteo.data.gouv.fr, Etalab licence, GRIB2 | Curiosity only. Do not trust it at the domain edge. | MEDIUM (extent from catalogue), LOW (usefulness) |
| **DHMZ ALADIN-HR (Croatia)** | Yes, the best local model (8 km / 2 km) | — | GRIB is a **paid product** per the Croatian NIPP registry. Only GIF charts are free (prognoza.hr). | Not available as GRIB. Use the charts for human sanity checks. Ask DHMZ or the organiser if time allows. | MEDIUM |
| **OpenSkiron / OpenWRF / OpenGribs (XyGrib server)** | Mediterranean domains include the Adriatic | WRF 4 km (2-day) / 12 km (5-day), ICON-EU re-cuts | Free download from openskiron.org; XyGrib GUI on the laptop | Good **second opinion** GRIB1/2 via laptop GUI; pygrib reads it. | MEDIUM |
| **Organiser forecast** | Unknown | Unknown | regata-jabuka.com page empty at time of writing | Build the importer generically (any GRIB1/2 with 10u/10v or wind speed/direction). | — |
| **DWD EWAM (waves)** | **Yes.** 30–66 N, −10.5–42 E (decoded) | 0.1° × 0.05°, to +78 h; `swh`, `mwd`, `tm10` and wind-sea/swell split | `opendata.dwd.de/weather/maritime/wave_models/ewam/grib/` | **Primary wave source**: same server, same GRIB2 pipeline, no account. | HIGH |
| **Copernicus Med currents** | Yes | 0.042° (~4.2 km), hourly 2D surface currents (`cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m`), ~10-day forecast | Free account + `copernicusmarine subset` → NetCDF (laptop) | Optional current layer. Adriatic currents are mostly weak (<0.5 kn) offshore, so this is a low-priority phase. | MEDIUM |
| **Copernicus Med waves** | Yes | ~4.2 km hourly | Same toolbox | Use only if EWAM fails. | MEDIUM |
| **Saildocs** | Global models | Coarse | E-mail request, pre-departure | Not needed when shore internet is available. | LOW |

Time base: the race runs Fri 13 Nov 19:00 UTC (20:00 CET) to Sun 15 Nov 09:00 UTC. **Store everything in UTC.** The Pi's clock comes from GPS via chrony.

### 6. Web app: backend + offline map
- **Backend:** FastAPI + uvicorn, a single worker. It serves one WebSocket (`/ws`), with state pushed at 1 Hz and route/laylines pushed on change. REST covers marks/course/settings/polar/weather selection. It also serves static files (vendored JS/CSS/fonts) and the tile endpoint that reads `race.pmtiles`. aiohttp 3.14.5 would also work and is lighter, but FastAPI's Pydantic models for marks/course/settings save time. (Confidence: HIGH)
- **Frontend:** **vanilla JS ES modules with no bundler, no npm build and no framework.** That leaves one less toolchain to break the week before the race. It has a helm view (CSS grid, very large numerals) over a MapLibre map. There are two vendored styles, day and **night (dark red-on-black)**, switched via `map.setStyle`. Use the Fullscreen API.
- **Map library: MapLibre GL JS 5.24.0** over Leaflet 1.9.4. Leaflet 1.9.4 is stable but has no native rotation and no vector night styling. More decisively, Leaflet needs raster tiles, and there is no legal, low-effort way to bulk-get OSM raster tiles (the OSMF policy forbids offline prefetch). Leaflet 2.0 is still beta (2.0.0-beta.1, 2026-11-02). Use Leaflet + `protomaps-leaflet` 5.1.0 only if the tablet has no WebGL at all, since it renders the same PMTiles on canvas, more slowly. (Confidence: HIGH)
- **Tiles:** a Protomaps extract with bbox 15.0,42.8 → 16.3,44.0 and maxzoom 15, a few MB, served as XYZ MVT by the Pi. Make **seamarks** a GeoJSON overlay (circle/symbol layer, coloured by `seamark:type`, labelled with light characteristics) built with osmium from Geofabrik Croatia. That is legal, tiny and styleable for night. Use the **coastline/land mask for routing** from osmdata.openstreetmap.de `land-polygons-split-4326`, clipped to the bbox and rasterised to `landmask.npy`. Do not bulk-download OpenSeaMap raster tiles; there is no clear offline-use policy and the vector route is better anyway. (Confidence: MEDIUM-HIGH)
- **Tablet caveat (HIGH):** `http://10.42.0.1` is **not a secure context**. The Screen Wake Lock API and service workers/PWA are unavailable. Options: set the tablet's screen timeout to "never" or use a NoSleep-style video trick. Alternatively, in Chrome set `chrome://flags/#unsafely-treat-insecure-origin-as-secure` = `http://10.42.0.1:8000`. Put the tablet in airplane mode with Wi-Fi on, and bookmark the IP rather than an mDNS name.

### 7. Polar formats and parsing
Write one tolerant parser (numpy, about 80 LOC) that normalises everything to `twa[]` (deg) × `tws[]` (kn) → `bsp[twa, tws]`, adds a 0 row and column, and exposes an efficiency factor:
- **OpenCPN / qtVlm `.pol`/`.csv`/`.txt`:** first row `TWA\TWS` (or `twa/tws`) followed by TWS columns; first column TWA. The separator is tab, `;`, `,` or spaces, so auto-detect it. An optional first line may name the boat. This is also what libweatherrouting reads.
- **Expedition:** each line is `TWS  TWA1 BSP1  TWA2 BSP2 …` (tab or space); `!` lines are comments. Detect it by the odd column count and a first column that increases slowly. Resample onto the common TWA grid.
- **ORC-derived CSV:** usually semicolon `TWA\TWS;6;8;10;12;14;16;20` plus separate beat/run angle and VMG rows. Map the "Beat angle"/"Run angle" rows into target-TWA tables.
- **Interpolation:** bilinear via `np.searchsorted` (vectorised for the router). Compute VMG-optimal up/down TWA per TWS once, then cache it. (Confidence: MEDIUM. Formats come from the OpenCPN manuals and community descriptions. Validate against the actual X35 file on day 1.)

### 8. Pi deployment
- **OS:** Raspberry Pi OS **Lite 64-bit (Trixie)**, flashed with Raspberry Pi Imager (pre-set hostname, user, SSH key). Headless: set `gpu_mem=16` and disable Bluetooth (`dtoverlay=disable-bt`). That frees RAM and the UART, and Bluetooth is unused. (Confidence: HIGH)
- **Wi-Fi AP: NetworkManager**, which is the default since Bookworm. Do **not** use hostapd/dnsmasq/dhcpcd recipes; they conflict with NM. Commands:
  ```bash
  nmcli con add type wifi ifname wlan0 con-name boat-ap autoconnect yes ssid JABUKA \
    802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    ipv4.method shared ipv4.addresses 10.42.0.1/24 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk '<pass>' 802-11-wireless-security.pmf 1
  ```
  `pmf 1` (disabled) is a known Trixie workaround for clients failing to join. The **Pi 3B radio is 2.4 GHz only**. The same radio cannot be AP and client at once, so download GRIBs over Ethernet or a phone USB tether at the dock, or switch NM profiles. (Confidence: MEDIUM-HIGH)
- **systemd units:**
  - `fastnet2ip.service`, `gpsd`, `chrony`: `Restart=always`.
  - `jabuka-hub.service`: `Restart=always`, `RestartSec=2`, `WatchdogSec=30` with a sd_notify heartbeat.
  - `jabuka-router.service` (or a child process): `Nice=10`, `CPUQuota=250%` so the UI never starves.
  - Hardware watchdog: `RuntimeWatchdogSec=15` in `/etc/systemd/system.conf`.
  - `journald`: `Storage=volatile` with `RuntimeMaxUse=30M`.
- **Power-cut robustness:**
  - Enable the root **overlay FS** via `sudo raspi-config nonint enable_overlayfs` as the **last step on 12 Nov**, after all config is final. Reported working on Trixie; MEDIUM confidence, so test it on 6–7 Nov, not on race day.
  - Keep a **separate writable `/data`**, either a USB stick or an ext4 partition created before first-boot auto-expand, mounted `noatime`. It holds weather npz, the course/marks JSON (atomic write: tmp + `os.replace`) and logs.
  - Use a high-endurance SD card plus a cloned spare card in the nav station.
  - Undervoltage on 12 V boat power is a classic Pi killer, so use a quality 5 V 3 A buck converter. (Confidence: MEDIUM)

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|---|---|---|
| Own numpy router (libweatherrouting algorithm) | libweatherrouting as-is | If the numpy port isn't passing tests by about 9 Nov. Then run lwr with `subdiv=3–5`, 30–60 min steps, no current, accept a slower refresh (every 10–15 min) and do current corrections only in the laylines. |
| fastnet2ip (separate service, NMEA UDP) | pyfastnet imported in the hub (Signal K paths, SI units) | If NMEA conversion turns out lossy for a needed channel (e.g. Target BSP 0x7D, Heading on Next Tack 0x9A are not in the NMEA list). Then own the serial port in a small dedicated pyfastnet reader process that publishes JSON on UDP. |
| gpsd + chrony | pyserial-asyncio reading `/dev/ttyACM0` | Never for the clock. Acceptable only if gpsd misbehaves with the VK-162, in which case set time manually via `timedatectl` and accept that risk. |
| FastAPI | aiohttp 3.14.5 | If RAM is tight (saves about 20–30 MB) or if you prefer one dependency for server and client. |
| MapLibre GL 5.24 | MapLibre GL 6.16 | If the tablet is confirmed WebGL2-capable (any Android 8+ Chrome is) and you want ESM. |
| MapLibre GL | Leaflet 1.9.4 + protomaps-leaflet 5.1.0 | If the tablet's WebGL is broken. It renders the same PMTiles on canvas, more slowly. |
| Protomaps PMTiles | Raster MBTiles (OSM + OpenSeaMap) made with MOBAC | Only with a raster source that explicitly permits offline prefetch. Otherwise it violates the OSMF tile policy. |
| ICON-EU primary | ICON-D2 primary | ICON-D2 does not reach Jabuka (south edge 43.18 N) and stops at +48 h. Use it only as a northern-leg overlay. |
| Trixie 64-bit | Bookworm 64-bit ("Legacy") | If a needed package regresses on Trixie. Python 3.11 still satisfies fastnet2ip, but caps numpy at 2.4.x and scipy at 1.17.x. |
| Pi-served web app | OpenCPN on a laptop reading UDP :2002 | **Plan B at sea**: no extra work beyond fastnet2ip broadcasting to the AP subnet. |

## What NOT to Use

| Avoid | Why | Use Instead |
|---|---|---|
| Signal K server on the Pi 3B | Node ≥22 is not in Trixie apt (20.19). It costs RAM and CPU against the router, gives no routing, and adds a JS plugin layer to debug in 7 days. | Python hub using Signal K path names and SI units |
| 32-bit Raspberry Pi OS (armhf) | No PyPI armv7 wheels for numpy/scipy/shapely/pygrib/eccodeslib. Node 24 does not support armv7. | 64-bit Lite |
| cfgrib + xarray at runtime on the Pi | Import cost, hypercube errors on mixed GRIBs, `.idx` writes onto a read-only FS | pygrib → `.npz` cube; cfgrib only on the laptop |
| tile.openstreetmap.org bulk download / "download area" | Explicitly prohibited by the OSMF tile usage policy | Protomaps `pmtiles extract` |
| Pure-Python per-point routing loops on the Pi | Minutes per route on a Cortex-A53, so the live re-routing goal fails | numpy-vectorised expansions |
| hostapd + dnsmasq + dhcpcd AP recipes | Conflict with NetworkManager on Bookworm/Trixie | `nmcli` AP profile with `ipv4.method shared` |
| A JS build chain (Vite/React) for v1 | One more toolchain to break, and npm/node on the Pi or laptop on race week | Vanilla ES modules + vendored MapLibre UMD |
| MapLibre GL JS v6 without checking the tablet | Requires WebGL2 and is ESM-only | Pin 5.24.0 |
| Relying on the Pi clock without GPS discipline | No RTC and no internet, so wrong GRIB time indexing after any power cut | gpsd + chrony SHM refclock, with a UI warning if not synced |
| gpsd USBAUTO on all USB serial devices | gpsd may probe and reconfigure the RS-485 adapter | Explicit `DEVICES=/dev/gps`, udev by-id symlinks |

## Stack Patterns by Variant

**If the Fastnet bus does not decode on 12 Nov (Hercules 390 incompatibility or wiring):**
- Run GPS + GRIB only. Enter TWD/TWS manually in the UI from the B&G displays.
- The hub must treat every source as optional, with staleness timestamps on each value.

**If the routing benchmark on the Pi exceeds ~30 s per route:**
- Coarsen to 10° headings, 30-min steps, `subdiv` 2°, and route only to the next mark plus one.
- Re-run on a timer of about 10 min, or on mark change, or on wind-bias change above a threshold.

**If no laptop is available at the marina:**
- Run `prep_weather` on the Pi itself (pygrib is installed). Convert Copernicus NetCDF with netCDF4, or skip current.

**If the tablet browser lacks WebGL:**
- Fall back to Leaflet 1.9.4 + protomaps-leaflet on the same tiles. The helm numbers view works without any map.

## Version Compatibility

| Package A | Compatible With | Notes |
|---|---|---|
| numpy 2.5.x | Python ≥3.12 | On Bookworm (3.11) the max is numpy 2.4.6 and scipy 1.17.1. That is one reason for Trixie. |
| fastnet2ip 3.3.1 | Python ≥3.11, pipx ≥1.5 | 3.3.1 fixed an ImportError with nmea2000 2026.8.1 on fresh installs, so do not pin older versions. |
| pygrib 2.1.8 | cp310–cp313 manylinux2014 aarch64 | Bundles eccodes. GRIB1 + GRIB2. |
| eccodeslib 2.50.0.33 | manylinux_2_28 aarch64 (glibc ≥2.28; Trixie has 2.41) | Only needed if using `eccodes`/cfgrib. |
| signalk-server 2.36.0 | Node ≥22 | Trixie has Node 20.19, so NodeSource would be needed (reason to skip). |
| maplibre-gl 5.24.0 | WebGL1 or WebGL2, UMD bundle | v6.x requires WebGL2 and is ESM-only. |
| Protomaps basemaps 5.7.2 style | maplibre-gl 4/5 | Needs local glyphs/sprites from `protomaps/basemaps-assets` for offline use. |
| pmtiles (py) 3.8.1 | PMTiles v3 archives from go-pmtiles 1.31.2 | Tiles are gzip MVT, so send `Content-Encoding: gzip`. |
| shapely 2.2.0 | Python ≥3.11, aarch64 wheels | Vectorised `contains_xy` for land-mask rasterisation. |

## Sources

- github.com/ghotihook/fastnet2ip README (fetched): sentences, PGNs, flags, tested hardware, replay caveats. MEDIUM-HIGH (official repo)
- github.com/ghotihook/pyfastnet source tarball (inspected): `fastnet.json` channel map (TWD 0x6D, Set/Drift 0x83/0x84), captures README (H2000/Hydra). HIGH (primary source)
- github.com/dakk/libweatherrouting master tarball (inspected): `router.py` scalar loops, "TODO: add current factor", `install_requires=["latlon3"]`, last commit 2026-07-06. HIGH (primary source)
- PyPI JSON API (queried 2026-11-05): all Python versions and aarch64/armv7 wheel availability listed above. HIGH
- npm registry (queried): signalk-server 2.36.0 `engines.node >=22`, maplibre-gl 6.16.0 / 5.24.0, leaflet 1.9.4 / 2.0.0-beta.1, @protomaps/basemaps 5.7.2, protomaps-leaflet 5.1.0. HIGH
- sources.debian.org API: Trixie python3.13 3.13.5, gpsd 3.25, nodejs 20.19.2. HIGH
- opendata.dwd.de: ICON-EU, ICON-D2 and EWAM GRIB2 files downloaded and grid section decoded (extents above). Run horizons from directory listings. HIGH
- https://www.raspberrypi.com/news/trixie-the-new-version-of-raspberry-pi-os/: Trixie release 2025-10-02, usable on Pi 3, clean flash advised. MEDIUM-HIGH
- https://demo.signalk.org/documentation/Installation/Raspberry_Pi.html: Node 22+/24, 64-bit only for Node 24. MEDIUM
- https://maplibre.org/maplibre-gl-js/docs/guides/v5-to-v6-migration-guide/ and v6.0.0 release notes: WebGL2 required, ESM only. MEDIUM-HIGH
- https://operations.osmfoundation.org/policies/tiles/: offline prefetch prohibited. HIGH
- https://docs.protomaps.com/basemaps/downloads and https://docs.protomaps.com/guide/getting-started: extract/maxzoom, ODbL attribution, build retention. MEDIUM-HIGH
- https://data.marine.copernicus.eu/product/MEDSEA_ANALYSISFORECAST_PHY_006_013: 0.042° hourly 2D currents dataset ID. MEDIUM
- https://www.data.gouv.fr/datasets/paquets-arome-resolution-0-025deg: AROME EURW1S40 grid 37.5–55.4 N, 12 W–16 E. MEDIUM
- https://registri.nipp.hr/tcpdf/print/izvor_javno.php?id=91: DHMZ ALADIN GRIB is a fee-based product. MEDIUM
- https://opengribs.org/en/gribs, windy.app OpenSkiron article: OpenWRF 4/12 km, ICON-EU re-cuts. LOW-MEDIUM
- https://signag.github.io/raspi-cam-srv/4.6/bp_Hotspot_Trixie and Adafruit AP guide: NM hotspot on Trixie, PMF workaround. MEDIUM
- tinypilotkvm.com FAQ and openenergymonitor forum: `raspi-config nonint enable_overlayfs`, works on Trixie per community reports. LOW-MEDIUM
- https://opencpn-manuals.github.io/main/weather_routing/polar_file_conversion.html: polar file variants (.csv/.pol/.txt, separators). MEDIUM
- https://starlette.dev/responses/: FileResponse Range support. MEDIUM-HIGH

---
*Stack research for: offline live sailing race routing + laylines on Raspberry Pi 3B (Regata Jabuka 2026)*
*Researched: 2026-11-05*
