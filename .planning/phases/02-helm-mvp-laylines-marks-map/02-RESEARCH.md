# Phase 2: Helm MVP — Laylines, Marks & Map - Research

**Researched:** 2026-11-06
**Domain:** Sailing nav maths (true wind, polar targets, laylines, mark rounding) in the Python core + offline vector map and night helm UI (vanilla JS, MapLibre 5, PMTiles) on an Android tablet over plain HTTP
**Confidence:** MEDIUM-HIGH (map/tiles/wake-lock pipeline verified end-to-end on the laptop; mark positions verified from OSM; X35 polar from an ORC certificate; Sailing Instructions and tablet hardware unverified)

<user_constraints>
## User Constraints (from CONTEXT.md)

> CONTEXT.md mode: "Smart discuss auto-accepted — user is AFK and explicitly asked to 'continue without me'." Revisit if the user objects.

### Locked Decisions

#### UI language & layout
- UI strings in **French** (user is French); code/identifiers in English.
- Single-page app, vanilla ES modules, no build chain, served from `src/jabuka/web/static/` by the existing core. Pages/tabs: **Barre** (helm, default), **Carte** (map + course editing), **Réglages** (settings), **Diag** (existing diagnostics).
- Helm view: map full-screen behind a top/bottom band of big numbers. Primary number by point of sail (D-6): |TWA| < ~70° → target TWA (upwind), |TWA| > ~110° → target TWA (downwind), else course to steer (CTS) to mark. Secondary: deviation (actual − target, colored), BSP vs target BSP and % polar, DTW/TTW to active mark, time/distance to layline ("Virement dans 12 min"), other-tack heading (D-7), wind source badge (LIVE / MANUEL / GRIB / PÉRIMÉ).
- Minimum font: primary number ≥ 20% of viewport height; all touch targets ≥ 48 px; lock mode = full-screen transparent overlay, unlock by long-press (≥ 2 s) on a padlock.

#### Night mode & screen awake
- Two themes: day and night (true black #000 background, red #ff2a00-ish foreground, dimmed map with dark/red MapLibre style). Toggle button on helm view; persist in localStorage (per-viewer convenience).
- Screen awake: try Screen Wake Lock API; fallback NoSleep-style muted looping video; plus document the Android settings (stay awake while charging, Chrome flag `unsafely-treat-insecure-origin-as-secure` for http://10.42.0.1:8080) in a TABLET-SETUP doc. Human-verify on the real tablet.

#### Map (offline)
- **MapLibre GL JS 5.24.0** (UMD build, vendored into static/vendor — pin exact version) + **Protomaps PMTiles** basemap extract for bbox ≈ 15.0,42.8,16.3,44.0 maxzoom ~14, served by the core as plain XYZ `/tiles/{z}/{x}/{y}.mvt` via the `pmtiles` Python reader (avoid browser Range requests). Glyphs + sprites vendored. Seamark overlay = OSM `seamark:*` GeoJSON extracted with osmium from Geofabrik Croatia (prep tool on laptop).
- Fallback if tablet lacks WebGL: Leaflet + protomaps-leaflet (document only; implement only if time allows).
- Prep tool (`jabuka-prep-map`, laptop) builds `race.pmtiles` + `seamarks.geojson` into a race-pack dir; binary outputs are NOT committed to git (gitignored), the build is reproducible by script. If downloading the Protomaps daily build fails, fall back to a smaller extract / raster-free style with coastline from OSM land polygons.
- Course-up / north-up toggle; boat centered option.

#### Polar
- Polar file formats: OpenCPN/Expedition tab-separated (TWA rows × TWS cols) and CSV; bilinear interpolation; derive upwind/downwind target TWA & BSP per TWS (max VMG). Store as JSON in race pack.
- **No X35 polar file is in the repo yet** — user said they have a "polaire générique X35" but it was not provided. Executor must ship a clearly labelled **placeholder X35 polar** (from public sources if a credible one is found, else a conservative synthetic 35-ft cruiser-racer polar) and a loader so the user can drop the real file in. Flag as human-verify: "load your real X35 polar".
- Efficiency factor (default 0.92) applied to target BSP and routing; separate upwind/downwind factors optional.

#### Wind pipeline
- Everything TRUE at one boundary: variation default +4.7°E (verify WMM 2026 Šibenik; configurable), heading offset (configurable), AWA sign config from Phase 1 (`awa_sign`).
- True wind computed from AWA/AWS/BSP/HDG (no leeway, no upwash in v1; leeway fixed configurable default 0°); cross-check against Hercules TWA/TWS/TWD when present; damping via circular EMA on vectors (τ ≈ 10 s for helm, ≈ 60 s for laylines TWD).
- Wind source arbitration: LIVE (instruments fresh) > MANUAL (user-entered TWD/TWS, sticky until cleared) > none; GRIB source arrives in Phase 3. Badge always visible. Stale threshold ~5 s.
- Jabuka magnetic zone (WIND-07): configurable center (Jabuka island) + radius default 3 nm; inside → heading untrusted, use GPS COG for laylines/true wind heading, flag on helm.

#### Laylines
- Computed in the core at ~1 Hz: from the active mark, two lines at TWD ± target TWA (upwind or downwind as appropriate for the leg), with current offset when NAV-03 enabled (Hercules set/drift; off by default). Source toggle: polar target angles (×efficiency) vs actually sailed tacking angles (median of last tack(s) per side; fallback to polar if none).
- Outputs: layline geometry (GeoJSON) for the map, distance & time to layline on current tack, overstood flag, other-tack heading, time-to-tack countdown (= time to reach layline at current VMC/SOG).
- Reach legs (mark not upwind/downwind): no laylines; show CTS.

#### Course & marks
- Mark library pre-loaded with the race marks: Vodice start/finish, Plić Sestre, Jabuka, Blitvenica, Mulo — coordinates to be researched precisely (OSM/charts) and stored in a JSON; islands are marks with a **rounding radius** (default: island → 0.5 nm offset from coast; Plić Sestre shoal → 0.3 nm) and side.
- Course A = Vodice → Plić Sestre → Jabuka → Blitvenica → Vodice; Course B = … → Jabuka → Mulo → Vodice. Rounding sides per NoR/SIs unknown → default sides configurable, user must confirm against SIs (human item).
- Map editing (Carte tab): tap to add mark, drag to move, tap mark → sheet with side (bâbord/tribord), radius, delete, reorder (up/down). One-tap course A/B select, next/prev, "Finir ici" (shorten course).
- Auto-advance: arrival circle (radius) entered then left OR bearing passes beam of mark → advance after 10 s, banner with "Annuler" for 60 s.
- Persistence: course + settings stored on the Pi via Phase 1 atomic IO (JSON), loaded at core start; REST endpoints for edits; WebSocket pushes changes to all clients.

#### Simulation
- Extend L2 synthetic boat to closed loop: steers to the core's target TWA / CTS, tacks at laylines, to exercise laylines, auto-advance and countdown in automated tests.

### Claude's Discretion
- Exact REST/WS schema, CSS details, damping constants within stated ranges, module layout under `src/jabuka/nav/` (suggested: `polar.py`, `wind.py`, `laylines.py`, `course.py`, `marks.json`).

### Deferred Ideas (OUT OF SCOPE)
- Layline uncertainty wedge, lift/header bar (v2 TACT-01/02).
- Leaflet fallback implementation (only if tablet lacks WebGL).
- Upwash/heel-based TWA correction.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------|------------------|
| WIND-01 | Load the generic X35 polar (OpenCPN/Expedition/CSV); target BSP, target TWA up/down, live % polar | §"X35 polar" (ORC X-35 One Design table, Expedition-format file, per-TWS-curve interpolation); Pattern 3 |
| WIND-02 | Polar efficiency factor applied to targets, laylines, routing | Pattern 3 (efficiency scales BSP only; target angles unchanged under a uniform factor); Pitfall 9 |
| WIND-03 | All directions TRUE at one boundary (variation ~+5°E, heading offset); own true wind from AWA/AWS/BSP/HDG, damped | WMM value 4.72°E; Pattern 2 (wind pipeline, vector EMA); existing `conventions.true_wind_from_apparent` |
| WIND-04 | Manual TWD/TWS entry; badge LIVE / MANUAL | Pattern 2 (source arbitration); Pitfall 6 (manual TWD M/T) |
| WIND-07 | Jabuka radius → heading untrusted, COG used | Pattern 2 (zone, center 43.09153 N 15.46054 E) |
| NAV-01 | Live port/stbd laylines ~1 Hz, polar or sailed angles | Pattern 4 (decomposition math, verified prototype); Pattern 5 (sailed tacking angles) |
| NAV-02 | Distance/time to layline, overstood, other-tack heading | Pattern 4 (a/b decomposition; actual-track ray intersection) |
| NAV-03 | Hercules set/drift applied to laylines (off by default) | Pattern 4 (ground vector = water vector + current); paths `environment.current.set` (ref) / `environment.current.drift` |
| CRSE-01 | Race marks + Course A/B pre-loaded, one-action select | §"Race marks" (OSM-verified coordinates, radii, distances) |
| CRSE-02 | Add/move/delete marks by tapping, side + radius, reorder | Pattern 8 (Carte tab, land check with `queryRenderedFeatures` on the `earth` layer) |
| CRSE-03 | Auto-advance after rounding + banner/undo; manual next/prev | Pattern 6 (rounding state machine) |
| CRSE-04 | Shorten / finish at any checkpoint in one action | Pattern 6 ("Finir ici" truncation) |
| CRSE-05 | Course + settings persist across reboot/power loss | Pattern 7 (atomic JSON in `--data-dir`, active index persisted) |
| HELM-01 | Offline map (Vodice → Jabuka) with boat, course, marks, laylines | §"Offline map pipeline" (verified PMTiles extract + tile endpoint + style render) |
| HELM-02 | Big numbers by point of sail, deviation, target BSP/% polar, DTW/TTW, tack countdown | Pattern 9 (helm view), Pattern 4 outputs |
| HELM-03 | Night mode true black/red | Pattern 10 (generated red flavor style, verified render) |
| HELM-04 | Lock mode; screen stays awake | Pattern 11 (overlay + long-press), Pattern 12 (Wake Lock + flag, verified; NoSleep fallback) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

Directives from `/home/drico/git/jabuka/.claude/CLAUDE.md` (embedded STACK.md) that bind this phase:

- **No JS build chain** (no Vite/React/npm build) — "Vanilla ES modules + vendored MapLibre UMD". Node may be used **once on the laptop** to generate style JSON; nothing node-related runs on the Pi.
- **MapLibre GL JS pinned to 5.24.0** (v6 requires WebGL2 + ESM). Glyphs/sprites must be vendored ("MapLibre will NOT render labels offline without them").
- **No Signal K server**; use Signal K path names + SI units internally.
- **FastAPI + uvicorn single worker**; Pi deps come from the hash-locked aarch64 wheelhouse (`deploy/requirements.in` must equal `pyproject` deps; `tests/deploy/test_lock.py` enforces it).
- **No bulk download from tile.openstreetmap.org** (OSMF policy) — use the Protomaps extract.
- **Injected clock everywhere** (no wall-clock calls in domain code; a test bans them).
- `ruff` + `pytest` on Python 3.13 **and** 3.14 via `scripts/check.sh`.
- GSD workflow: edits go through GSD commands (executor concern, not research).

## Summary

Everything this phase needs is either already in the Phase 1 code (true-wind maths, conventions, state store, atomic JSON, WS hub, injected clock, L2 synthetic boat) or was verified end-to-end on this laptop during research. A Protomaps extract of the race box (`15.0,42.8,16.3,44.0`, maxzoom 14) is **12 MB** and takes ~12 s with go-pmtiles 1.31.2. A FastAPI endpoint serving tiles out of it with the `pmtiles` Python reader and `Content-Encoding: gzip` rendered without errors in MapLibre 5.24.0 (headless Chromium 148, WebGL through SwiftShader). Both a day style and a generated red-only night style worked, from `@protomaps/basemaps` 5.7.2 with vendored Noto Sans glyphs (Croatian "ć" renders from the `256-511` range). Two traps came up and were fixed in the prototype. First, MapLibre rejects relative sprite and tile URLs, so the client must absolutize them. Second, `pmtiles.Reader.get()` re-parses the root directory on every call (3.2 ms/tile on x86, so roughly 30 ms on a Pi 3B, holding the GIL). An index built once at startup cuts that to 3.4 µs.

Race marks come from OSM. Plić Sestre is the isolated-danger beacon "Plicina Sestre, in Zlarinski Kanal" (43.684627 N, 15.811626 E; nearest land 0.72 nm, so a 0.3 nm radius is safe). Jabuka is an unlit islet of 271 × 128 m (centroid 43.09153 N, 15.46054 E). Blitvenica light is at 43.625032 N, 15.574467 E and Hrid Mulo light at 43.514478 N, 15.918543 E. The NoR confirms both courses and that "each check point can also be an auxiliary finish". It gives **no rounding sides, start line or coordinates**, and the SIs are not yet readable, so the sides stay a human item. An ORC **X-35 One Design** certificate (data.orc.org, 2019 VPP) gives a complete, credible generic polar: beat/run angles, beat/run VMG and speeds at 52–150° for 6–20 kn TWS. Ship it as the placeholder polar in Expedition format.

Wake Lock over plain HTTP was verified on desktop Chromium. Without the flag, `isSecureContext=false` and there is no `navigator.wakeLock`. With `--unsafely-treat-insecure-origin-as-secure=<origin>`, both become true. On Android the same switch sits in `chrome://flags`. **On the Pi the origin is `http://10.42.0.1` (port 80, from the systemd unit), not `:8080` as CONTEXT says.** Headless UI testing is available without sudo: pip `playwright==1.64.1` drives the system `/usr/bin/chromium` (148) with `executable_path`, so `playwright install` is not needed. Pure JS logic can follow the existing `tests/test_diag_logic.py` pattern (node evaluated from pytest).

**Primary recommendation:** Build pure nav modules (`jabuka/nav/{polar,wind,laylines,course,geo}.py`, scalar Python, no numpy) driven by the core's existing 1 Hz tick. Publish a compact `nav` WS message and persist course and settings with `atomic_write_json`. Serve tiles from an in-memory PMTiles index. Vendor MapLibre, NoSleep, glyphs, sprites and two generated style JSONs into `web/static/` with a reproducible laptop script.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| True wind, damping, source arbitration, Jabuka zone | API / Backend (core 1 Hz tick) | — | Every client must show identical numbers; uses injected clock |
| Polar load, targets, % polar | API / Backend (`nav/polar.py`) | Prep (laptop converts formats → JSON) | Shared later with the Phase 3 router |
| Laylines, distance/time to layline, overstood, other-tack heading | API / Backend (`nav/laylines.py`) | Browser (draws GeoJSON) | Server computes, browser renders only |
| Course/marks, auto-advance, shorten | API / Backend (`nav/course.py` + REST) | Browser (editing UI, land check on tap) | Single source of truth, persisted on Pi |
| Persistence of course/settings/active mark | Database / Storage (atomic JSON in `/var/lib/jabuka`) | — | Power-cut safe via Phase 1 `atomicio` |
| Vector tiles | API / Backend (tile endpoint from PMTiles index) | CDN/Static (vendored glyphs/sprites/styles) | Avoid browser Range requests; offline |
| Basemap + seamark build | Prep tool (laptop) | — | Needs internet + go-pmtiles + pyosmium; never on boat |
| Map rendering, day/night style, course-up, lock overlay, wake lock | Browser / Client | — | Pure presentation; per-viewer prefs in localStorage |
| Closed-loop sim | Dev tool (`jabuka.sim`) | — | Test harness only |

## Standard Stack

### Core (runtime on the Pi)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi / uvicorn / websockets | 0.162.0 / 0.54.0 / 17.4 (already pinned) | REST + WS + static | Existing Phase 1 stack [VERIFIED: pyproject.toml read this session] |
| pydantic (transitive, already locked) | 2.14.3 | Validate course/settings/manual-wind bodies | Already in wheelhouse [VERIFIED: deploy/wheelhouse listing] |
| `pmtiles` (Python) | 3.8.1 (2026-09-16, pure-python `py3-none-any`, **no dependencies**, BSD-3) | Read `race.pmtiles` tiles server-side | Official Protomaps reader; tested this session [VERIFIED: PyPI JSON + local run] `pmtiles` [WARNING: flagged as suspicious — verify before using.] (legitimacy seam: SUS "unknown-downloads"; repo github.com/protomaps/pmtiles) |
| Python stdlib `math` | — | All nav maths (scalar) | 1 Hz × a few dozen ops; numpy not needed in Phase 2 (keeps the Pi lock unchanged except pmtiles) |

### Vendored browser assets (committed under `src/jabuka/web/static/vendor/`)
| Asset | Version / integrity | Purpose |
|-------|---------|---------|
| maplibre-gl `dist/maplibre-gl.js` + `.css` | 5.24.0, npm `sha512-ALyFxgtd5R+65UqZ/++lOqwWcC0SNho9c27fYSyLmG7AfnAul2o46F05aDJGPbFU57wos9dgcIySHs0Xe6ia3A==`; file sha256 `45a9b07a…ee5cb` (js), `ab1e70d5…a732` (css); BSD-3 | Map renderer, UMD, WebGL2→WebGL1 fallback [VERIFIED: `getContext('webgl2', attributes) \|\| this._canvas.getContext('webgl', attributes)` in maplibre-gl-dev.js] |
| nosleep.js `dist/NoSleep.min.js` | 0.12.0, `sha512-9d1HbpKLh3sdWlhXMhU6MMH+wQzKkrgfRkYV0EBdvt99YJfj0ilCJrWRDYG2130Tm4GXbEoTCx5b34JSaP+HhA==`, sha256 `887b763e…731c`, MIT | Wake fallback (looping inline video) |
| protomaps basemaps-assets fonts | `Noto Sans Regular`, `Noto Sans Medium`, `Noto Sans Italic` (ranges `0-255`, `256-511` minimum; add `512-767`, `8192-8447`), OFL | Labels offline [VERIFIED: fonts used by generated style] |
| protomaps basemaps-assets sprites | `sprites/v4/{light,dark}{,@2x}.{json,png}` | Icons (day); night strips icons |
| Generated `style-day.json` / `style-night.json` | from `@protomaps/basemaps` 5.7.2 (build-time only, laptop), BSD-3 | Basemap layers (71 layers, source-layers earth/landcover/landuse/roads/water/buildings/boundaries/pois/places) [VERIFIED: generator run] |

### Laptop-only (prep + dev)
| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| go-pmtiles CLI | 1.31.2 (`go-pmtiles_1.31.2_Linux_x86_64.tar.gz`, sha256 of tarball `3ed7dbf4…312f`) | `pmtiles extract` from daily build | Single static binary; or `go install github.com/protomaps/go-pmtiles@v1.31.2` (go 1.24.4 present) |
| `osmium` (pyosmium) | 4.3.2 (cp313/cp314 manylinux x86_64 wheels; BSD-2; dep `requests`) | Seamark extraction (replaces apt `osmium-tool`, which needs sudo) | [WARNING: flagged as suspicious — verify before using.] (seam: SUS "too-new, unknown-downloads"; official osmcode.org project) |
| node (system) | v24.21.0 | One-off style generation (`.mjs` importing `@protomaps/basemaps/dist/esm/index.js`) | The package's own `generate_style` bin is `./src/cli.ts`; do not rely on it |
| `playwright` (Python, dev/test only) | 1.64.1 | Headless UI smoke tests driving `/usr/bin/chromium` 148 | [WARNING: flagged as suspicious — verify before using.] (seam: SUS "too-new, no-repository" — Microsoft's official package) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Server-side pmtiles reader | Browser `pmtiles` JS protocol + HTTP Range | Locked decision against; also needs extra JS lib |
| pyosmium | apt `osmium-tool` | Needs sudo; same result |
| Scalar Python nav | numpy | numpy not in Pi lock yet; unnecessary at 1 Hz |
| Own wake-lock wrapper + NoSleep | NoSleep alone | NoSleep does not fall back to video when the native request is *rejected* (see Pitfall 12) |

**Installation (Pi runtime):** add `pmtiles==3.8.1` to `pyproject.toml` dependencies **and** `deploy/requirements.in`, add `"pmtiles"` to `EXPECTED_LOCKED` in `tests/deploy/test_lock.py`, then `bash scripts/build-wheelhouse.sh --relock`.
**Laptop extras:** new optional extras, e.g. `prep = ["osmium==4.3.2"]`, `uitest = ["playwright==1.64.1"]`. Do **not** put them in `dev` if `check.sh` must stay green on machines without chromium; tests must `importorskip`.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| pmtiles 3.8.1 | PyPI | latest 2026-09-16 (project multi-year) | unknown (seam) | github.com/protomaps/pmtiles | [SUS] unknown-downloads | Flagged — planner adds checkpoint:human-verify before install |
| osmium 4.3.2 | PyPI | latest 2026-10-18 | unknown | osmcode.org/pyosmium | [SUS] too-new, unknown-downloads | Flagged — laptop-only; checkpoint before install |
| playwright 1.64.1 | PyPI | latest 2026-10-22 | unknown | none in metadata (Microsoft) | [SUS] too-new, no-repository | Flagged — dev-only; checkpoint before install |
| maplibre-gl 5.24.0 | npm (vendored file) | package years old; latest tag 6.16.0 is recent | 9.68 M/wk | github.com/maplibre/maplibre-gl-js | [SUS] too-new (latest publish) | Flagged — vendor by pinned version + integrity hash; no postinstall |
| @protomaps/basemaps 5.7.2 | npm (build-time) | 2026-03 | 713 k/wk | github.com/protomaps/basemaps | [OK] | Approved; no postinstall |
| nosleep.js 0.12.0 | npm (vendored file) | 2022 | 530 k/wk | github.com/richtr/NoSleep.js | [OK] | Approved; no postinstall |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** pmtiles (PyPI), osmium (PyPI), playwright (PyPI), maplibre-gl (npm). All four are the official upstream packages. The SUS signals come from missing download stats and recent releases, not from typosquat indicators. The planner still inserts `checkpoint:human-verify` before each install, as the protocol requires.
`npm view <pkg> scripts.postinstall` was empty for all three npm packages.

## Race Marks (CRSE-01) — verified data for `marks.json`

| Mark | Position (WGS84) | Source | Object & extent | Recommended rounding radius (from position) | Light |
|------|------------------|--------|-----------------|---------------------------------------------|-------|
| **Vodice (start/finish area)** | **43.7500 N, 15.7800 E** (placeholder) | Computed: ≥ 570 m from every OSM coastline vertex, in the channel between Vodice harbour (entrance beacons 43.75551/15.77625, 43.75613/15.77796) and Prvić [VERIFIED: Overpass coastline + seamark query] | Start/finish *line* not published | 0.15 nm arrival radius (finish); **replace with SI line** | Harbour lights Fl 5s (OSM) |
| **Plić Sestre** | **43.684627 N, 15.811626 E** | OSM node 498394251 `seamark:name`="Plicina Sestre, in Zlarinski Kanal.", `beacon_isolated_danger`, Fl(2)W 10s, range 4, ref E 3230; submerged rock node 8883790953 at 43.684411/15.811043 [VERIFIED: Overpass] | Isolated-danger beacon on a shoal; nearest coastline 0.72 nm (bearing 235°) | **0.3 nm** (fits: land ≥ 0.72 nm) | Fl(2) W 10 s |
| **Jabuka** | **43.09153 N, 15.46054 E** (coastline centroid; OSM place node 43.0917177/15.4601321) | OSM way 10520887 `place=islet`, `natural=coastline` [VERIFIED: Overpass geometry] | 271 m E-W × 128 m N-S, max 0.085 nm from centroid; peak 97 m | **0.6 nm** (0.085 + 0.5 offset) | **None found in OSM** within 43.08–43.10 N / 15.44–15.48 E (absence ≠ proof; check the chart) |
| **Blitvenica** | **43.62508 N, 15.57476 E** (centroid); light node 1377046673 at 43.625032/15.574467 | OSM way 8838344 + `light_major` "Otocic Blitvenica" E 3226, Fl(2)W 30s, 24 M [VERIFIED: Overpass] | 185 × 137 m, max 0.065 nm | **0.55 nm** | Fl(2) W 30 s, 24 M |
| **Mulo** | **43.5146 N, 15.91857 E** (centroid); light node 498383293 at 43.514478/15.918543 | OSM way 6186065 + `landmark` "Hrid Mulo" E 3286, Fl W 5s, 21 M [VERIFIED: Overpass] | 78 × 73 m, max 0.026 nm | **0.5 nm** | Fl W 5 s, 21 M |
| Jabuka magnetic zone center | 43.09153 N, 15.46054 E, radius 3 nm (setting) | as above | — | — | — |

Rhumb distances [VERIFIED: computed this session]: A = Vodice→Plić Sestre 4.2 nm (161°) → Jabuka 38.8 nm (203°) → Blitvenica 32.4 nm (009°) → Vodice 11.6 nm (050°) = **87.0 nm**. B = … Jabuka → Mulo 32.3 nm (038°) → Vodice 15.4 nm (337°) = **90.6 nm**. This is consistent with the "about 110 nautical miles" sailed distance on regata-jabuka.com.

**Rounding sides:** NoR text (fetched) — "**Course A**: Vodice – Plić Sestre - Island of Jabuka - Island of Blitvenica - Vodice", "**Course B**: Vodice – Plić Sestre - Island of Jabuka - Island of Mulo - Vodice", "Each check point can also be an auxiliary finish.", "The Organizing Authority reserves the right to change the course". No sides, no start line, no coordinates [CITED: regata-jabuka.com/index.php/en/notice-of-race]. SIs: racingrulesofsailing.org event 16094 returned 403. Default sides by loop geometry: Course A's loop runs clockwise (signed area < 0), so the marks fall naturally to **starboard**. Course B's loop runs counter-clockwise, so they fall naturally to **port** [ASSUMED: geometry heuristic only]. Ship these as defaults with a loud "côtés à confirmer (IC)" warning, and make it a human checkpoint.

**Rhumb lines cross land.** For example, Vodice→Plić Sestre crosses Prvić. Phase 2 has no land mask, so CTS and laylines are geometric. The map makes this visible. Do not claim more.

## X35 Polar (WIND-01) — placeholder source

**Source:** ORC "X-35 ONE DESIGN" certificate, Class X-35 OD, designer Jeppesen, builder X-Yachts, VPP 2019 1.01, "2019 (Test)", "Invalid for Racing" (that only matters for scoring), © Offshore Racing Congress 2019. URL: `https://data.orc.org/public/od/2019/x35.od.pdf` [VERIFIED: downloaded + pdftotext this session]. Redistribution licence not stated [ASSUMED: committing derived numbers with attribution is acceptable; user to confirm].

Verbatim certificate values (knots; TWS columns 6, 8, 10, 12, 14, 16, 20 kt):
```
Beat Angles  42.1° 40.8° 39.0° 37.7° 37.7° 37.2° 38.0°
Beat VMG      3.70  4.47  4.96  5.14  5.21  5.29  5.32
52°           5.60  6.59  7.05  7.19  7.26  7.30  7.40
60°           5.90  6.81  7.21  7.38  7.46  7.49  7.64
75°           6.15  6.95  7.35  7.62  7.79  7.88  8.00
90°           6.10  6.95  7.36  7.69  8.01  8.28  8.53
110°          5.95  7.01  7.53  7.96  8.25  8.50  8.91
120°          5.78  6.90  7.45  7.93  8.44  8.86  9.45
135°          5.21  6.39  7.14  7.59  8.08  8.60  9.97
150°          4.40  5.50  6.47  7.14  7.56  8.01  9.03
Run VMG       3.81  4.76  5.61  6.32  6.94  7.39  8.24
Gybe Angles  142.4° 148.3° 151.4° 158.9° 180.0° 180.0° 180.0°
```
Derived **Expedition-format** placeholder (`TWS  TWA BSP  TWA BSP …`; beat BSP = VMG/cos(beat), run BSP = VMG/−cos(gybe)) [VERIFIED: computed this session]:
```
6   42.1 4.99  52 5.60  60 5.90  75 6.15  90 6.10  110 5.95  120 5.78  135 5.21  142.4 4.81  150 4.40
8   40.8 5.90  52 6.59  60 6.81  75 6.95  90 6.95  110 7.01  120 6.90  135 6.39  148.3 5.59  150 5.50
10  39.0 6.38  52 7.05  60 7.21  75 7.35  90 7.36  110 7.53  120 7.45  135 7.14  150 6.47  151.4 6.39
12  37.7 6.50  52 7.19  60 7.38  75 7.62  90 7.69  110 7.96  120 7.93  135 7.59  150 7.14  158.9 6.77
14  37.7 6.58  52 7.26  60 7.46  75 7.79  90 8.01  110 8.25  120 8.44  135 8.08  150 7.56  180 6.94
16  37.2 6.64  52 7.30  60 7.49  75 7.88  90 8.28  110 8.50  120 8.86  135 8.60  150 8.01  180 7.39
20  38.0 6.75  52 7.40  60 7.64  75 8.00  90 8.53  110 8.91  120 9.45  135 9.97  150 9.03  180 8.24
```
Caveats: this is a VPP with a symmetric spinnaker, a measured 2006 boat and full crew. Night, sea state and a short-handed crew make it optimistic, which is why the 0.92 efficiency default exists. ORC beat angles of 37–42° are VPP angles, and the TWA the instruments read upwind is typically wider [ASSUMED]. The "sailed tacking angles" toggle covers this.

## Architecture Patterns

### System Architecture Diagram

```
 Fastnet ingest (UDP deltas)      gpsd TPV/SKY            Tablet/laptop browser
          │                            │                    │  ▲ REST: course, settings,
          ▼                            ▼                    │  │ manual wind, active mark
   ┌──────────────── core (one asyncio loop, injected clock) ─┴──┼──────────────────────┐
   │ StateStore (path,src → value, ref, age)                     │                      │
   │      │ latest() per path, stale thresholds                  │                      │
   │      ▼                                                       │                      │
   │ 1 Hz tick ──► nav.wind: M→T (variation+offset), own TW from AWA/AWS/BSP/HDG,        │
   │               Jabuka zone → COG, vector EMA (τ10 s helm / τ60 s laylines),          │
   │               source = LIVE | MANUEL | none (+ PÉRIMÉ)                              │
   │          ──► nav.polar: targets(TWS) × efficiency, %polar                           │
   │          ──► nav.course: active mark, anchor point (side+radius), rounding FSM ──┐  │
   │          ──► nav.laylines: leg type (beat/run/reach), layline GeoJSON,            │  │
   │               dist/time to layline, overstood, other-tack hdg, TTW, CTS          │  │
   │          ──► derived log line ──► WS publish {"type":"nav"} (+ "diag")           │  │
   │ course/settings change ─► atomic_write_json(/var/lib/jabuka/*.json) ─► WS "course"│  │
   │ /tiles/{z}/{x}/{y}.mvt ◄── PMTiles index (mmap) of racepack/race.pmtiles         │  │
   │ /racepack/seamarks.geojson, static (index.html, vendor/, glyphs/, sprites/)      │  │
   └────────────────────────────────────────────────────────────────────────────────────┘
          │ WS /ws (1 Hz)                                       ▲
          ▼                                                     │ laptop prep (internet):
   Browser: MapLibre 5.24 (day/night style) + helm bands,       │ go-pmtiles extract → race.pmtiles
   lock overlay, wake lock, tabs Barre/Carte/Réglages/Diag      │ pyosmium → seamarks.geojson
                                                                │ node → style-day/night.json
```

### Recommended Project Structure
```
src/jabuka/nav/            # PURE (no I/O, no clock reads; time passed in) — add to the no-wallclock scan
├── geo.py                 # local ENU projection (nm), bearing/distance, ray/line intersection
├── polar.py               # parse OpenCPN grid / Expedition / CSV → Polar; speed(); targets(); pct()
├── wind.py                # VectorEma, WindPipeline (M→T, own TW, zone, arbitration, cross-check)
├── laylines.py            # leg type, anchor, decomposition, outputs dataclass, GeoJSON
├── course.py              # Mark/Course models, templates A/B, rounding FSM, shorten, versioning
├── tacks.py               # tack detection + sailed angle medians (NAV-01 toggle)
└── data/marks.json, data/x35-orc-od-2019.exp  # package data (ships in the wheel)
src/jabuka/core/nav_service.py   # glue: reads StateStore, runs nav at tick, persistence, WS msgs
src/jabuka/core/tiles.py         # PMTiles index + /tiles route
src/jabuka/core/web.py           # + REST routes (course, settings, wind/manual), static mount last
src/jabuka/prep/map.py           # jabuka-prep-map (laptop): pmtiles extract + seamarks
src/jabuka/web/static/           # index.html (app shell), helm.js, map.js, course_ui.js,
                                 # helm_logic.js (pure, node-tested), wakelock.js, lock.js,
                                 # diag.html/diag.js (moved), vendor/, glyphs/, sprites/,
                                 # style-day.json, style-night.json
scripts/vendor-web.sh + scripts/build-styles.mjs   # reproducible vendoring (laptop, internet)
```

### Pattern 1: Reuse the existing conventions, don't re-derive
`jabuka.common.conventions` already has `true_wind_from_apparent(awa: float, aws: float, bsp: float, hdg: float) -> TrueWind` (`TrueWind(twa, tws, twd)`), `mag_to_true(mag: float, variation_east: float)`, `apply_heading_offset(heading: float, offset: float)` and `current_towards_uv(direction_towards: float, speed: float)`. They are pinned by golden tests [VERIFIED: src/jabuka/common/conventions.py:33-91]. Units: radians, m/s. TWA "signed, negative = port". Variation "EAST-positive (true = magnetic + variation)".

Input paths available in the store [VERIFIED: src/jabuka/sim/synth.py:162-172 `udp_values`; src/jabuka/ingest/fastnet_decode.py:24-28; src/jabuka/ingest/gpsd_client.py:100-122]:
- `"environment.wind.angleApparent"` (rad), `"environment.wind.speedApparent"` (m/s), `"environment.wind.angleTrueWater"`, `"environment.wind.speedTrue"`, `"environment.wind.direction"` (with `ref`), `"navigation.heading"` (with `ref` `"M"`/`"T"`/`"?"`), `"navigation.speedThroughWater"`.
- `ROUTED_CHANNELS`: `0x49: "navigation.heading"`, `0x6D: "environment.wind.direction"`, `0x84: "environment.current.set"` (each carries `ref`).
- gpsd: `"navigation.position"` with value `{"latitude": lat, "longitude": lon}` and unit `"deg"`, `"navigation.courseOverGroundTrue"` (rad, ref `"T"`), `"navigation.speedOverGround"` (m/s).
- Drift: pyfastnet 0x83 `"path": "environment.current.drift"`, `"unit": "m/s"` [VERIFIED: .venv/.../fastnet_decoder/data/fastnet.json:1058-1067].
- Stale thresholds: `"environment.wind.": 5.0`, `"navigation.heading": 5.0`, `"navigation.position": 3.0`, `"navigation.courseOverGroundTrue": 3.0`, `"environment.current.": 60.0` [VERIFIED: src/jabuka/core/state.py:16-26].

### Pattern 2: Wind pipeline (WIND-03/04/07)
At each tick (not per message, because inputs arrive asynchronously):
1. `hdg_raw = latest("navigation.heading")`. If `ref == "M"` or `"?"` (setting `heading_ref_unknown = "M"`): `hdg_T = mag_to_true(apply_heading_offset(v, offset), variation)`. If `"T"`: apply the offset only.
2. **Jabuka zone:** `dist(pos, zone_center) < zone_radius` → `heading_trusted = False`. Use `COG` (gpsd) as the heading for TWD, and ignore instrument `environment.wind.direction` (it is compass-derived too). Flag `"CAP NON FIABLE"` on the helm.
3. If AWA, AWS and BSP are fresh: `tw = true_wind_from_apparent(awa, aws, bsp, hdg_T)` → source `LIVE`. Cross-check: if Hercules `angleTrueWater`/`speedTrue` are fresh, publish `dTWA`, `dTWS` (debug page) and an alert if |dTWA| > 10° for over 60 s. If only the instrument true wind is fresh (no AWA), use it as `LIVE (B&G)`.
4. Else if manual `{twd, tws, ref, t_set}` exists → source `MANUEL` (age shown; `PÉRIMÉ` after e.g. 30 min, a setting). Manual TWD entry must take **M or T** (default M), because B&G displays may be magnetic.
5. Else source `none`. Laylines are suppressed and the helm shows "PAS DE VENT".
6. **Damping:** time-based `α = 1 − exp(−Δt/τ)`, Δt from `clock.monotonic()`. Damp TWD as the vector `(TWS·sin TWD, TWS·cos TWD)`, with two filters (τ_helm = 10 s, τ_lay = 60 s). Damp TWS as a scalar EMA, because vector-averaged speed under-reads in oscillating wind. Reset the filters on a source change (LIVE↔MANUEL) so manual→live doesn't drift in over 60 s.

```python
# Source: designed this session; maths = standard circular mean on vectors
import math
class VectorEma:
    def __init__(self, tau_s: float): self.tau, self.x, self.y, self.t = tau_s, None, None, None
    def update(self, direction: float, weight: float, t: float) -> float:
        sx, sy = weight * math.sin(direction), weight * math.cos(direction)
        if self.x is None or t <= self.t:            # first sample / clock went backwards
            self.x, self.y = sx, sy
        else:
            a = 1.0 - math.exp(-(t - self.t) / self.tau)
            self.x += a * (sx - self.x); self.y += a * (sy - self.y)
        self.t = t
        return math.atan2(self.x, self.y) % (2 * math.pi)   # wrap_2pi
```

Variation default **+4.72° E** (WMM-2025 at 43.4 N 15.65 E on 2026-11-13, uncertainty ±0.35°) [VERIFIED: NOAA NCEI calculateDeclination API, model "WMM-2025", declination 4.72136]. That matches the CONTEXT default of +4.7°.

### Pattern 3: Polar as per-TWS curves (Expedition semantics)
Store `curves: list[(tws_kn, [(twa_deg, bsp_kn), …])]` plus optional explicit `beat_angle[]`/`gybe_angle[]` per TWS.
- `speed(tws, twa)`: `|twa|` folded into [0,180]. Linear in TWA within each bracketing TWS curve, then linear across TWS. Add an implicit (0°, 0 kn) point and an implicit TWS 0 curve of zeros. Clamp above the max TWS (no extrapolation).
- `targets(tws)`: if the file gives beat/gybe angles, interpolate them across TWS. Otherwise search for max VMG over a 0.5° grid of the interpolated curve (upwind `bsp·cos`, downwind `−bsp·cos`).
- Efficiency `eff` (default 0.92, optional `eff_up`/`eff_down`) multiplies BSP only. A uniform factor leaves the VMG-optimal angle unchanged, so laylines don't move with `eff` (only time-to-layline does).
- `%polar = BSP / (eff × speed(TWS, |TWA|))`. Target BSP = `eff × speed(TWS, target_TWA)`.
- Parsers: (a) OpenCPN/qtVlm grid: first cell `TWA\TWS` or `twa/tws`, separator auto-detected (`\t ; ,` or spaces); (b) Expedition: `!` comments, each line `TWS (TWA BSP)+`; (c) ORC-style CSV with "Beat Angles"/"Gybe Angles" rows. Convert all to the JSON curve form and store it in the race pack (CONTEXT).

### Pattern 4: Laylines by vector decomposition (NAV-01/02/03)
Work in a local flat frame around the mark (east/north in nm; equirectangular `x = Δlon·cos(lat_mark)·60`, `y = Δlat·60`; error < 0.1% over 40 nm). Velocities are in kn (nm/h).

- Leg type (on the 60 s-damped TWD, with ±5° hysteresis): `β = |wrap_pi(BRG_boat→anchor − TWD)|`. **Beat** if `β < TWA_up`. **Run** if `β > TWA_down`. Else **reach** (no laylines; primary = CTS).
- Tack headings (TWA sign convention: positive = starboard): beat → `h_stbd = TWD − TWA_up`, `h_port = TWD + TWA_up`. Run → `h_stbd = TWD − TWA_down`, `h_port = TWD + TWA_down`.
- Ground vectors `g = BSP_target·(sin h, cos h) + c`, where `c` = current u/v from `current_towards_uv(set_T, drift)` when NAV-03 is on (set may be `ref M`, so convert it) else 0.
- **Anchor** (island/shoal radius): `A = M + R·u(leg_bearing + 90°)` for a mark left to **port** (boat passes on its right), `−90°` for **starboard**. Use `leg_bearing` = previous mark → M (boat → M for the first leg). Laylines pass through A, not through the rock.
- Decompose `D = A − P = a·g_cur + b·g_other` (2×2 solve). `a` = hours on the current tack before tacking, `b` = hours after.
  - `a > 0, b > 0`: normal. **Time to tack = a**, distance to layline `= a·|g_cur|`, TTW `= a + b`.
  - `a ≤ 0`: **overstood** (passed the other-tack layline). Show "DÉPASSÉE" and the extra time.
  - `b ≤ 0`: mark is **fetchable on the current tack** ("ÇA PASSE"). CTS = bearing to A.
- Other-tack heading = `h_other` (display convention: Open Question 2).
- Countdown per CONTEXT uses the boat's **actual** track: intersect the ray `P + s·u(COG)` with the other-tack layline `A + t·ĝ_other` (t ≤ 0). Time = `s / SOG` when SOG > 1 kn, else fall back to `a`.
- Layline GeoJSON: two LineStrings from A back along `−g_stbd`, `−g_port`, length ≈ max(DTW·1.5, 2 nm), converted back to lon/lat.

Prototype checks [VERIFIED: scratch run of the code below]: wind 000°, TWA 45°, 6 kn, mark 5 nm upwind gives `a = b = 0.5893 h` (analytic 5/(2·6·cos45°)). A boat 6 nm west on starboard gives `a = −0.118` (overstood). A 1 kn east current gives `a = 0.728, b = 0.450`.

```python
# Source: prototype written + executed this session (scratchpad/scripts/layline_proto.py)
def decompose(d, ga, gb):
    det = ga[0] * gb[1] - ga[1] * gb[0]
    if abs(det) < 1e-9:
        return None                       # tacks parallel (degenerate polar) → no laylines
    a = (d[0] * gb[1] - d[1] * gb[0]) / det
    b = (ga[0] * d[1] - ga[1] * d[0]) / det
    return a, b
```

### Pattern 5: Sailed tacking angles (NAV-01 toggle)
Detect a tack (beat) or gybe (run) when the sign of the 10 s-damped TWA flips and stays flipped for ≥ 30 s. For each settled tack (≥ 120 s steady), record `θ = wrap_pi(COG_mean − TWD_mean)` over that window. Use the median of the last 3 per side. Because θ is **ground-referenced**, it already includes leeway and current. **Do not add the current vector again** in this mode (Pitfall 8). Fall back to the polar per side when there is no sample. Persist the samples in the derived log, not in settings.

### Pattern 6: Course model + rounding state machine (CRSE-01..04)
- `Mark{id, name, lat, lon, radius_nm, side: "port"|"stbd"|"none", kind: "start"|"mark"|"finish", builtin: bool}`. `Course{version, template: "A"|"B"|"custom", seq: [mark_id…], active_idx, finish_idx}`.
- Templates A/B from `marks.json`. Selecting one sets `active_idx = 1` (the start is index 0 and never auto-advances).
- **FSM per active mark:** `APPROACH` → `IN_ZONE` when `d(P, M) ≤ radius + 0.25 nm`. Then `ROUNDED` when **either** (i) `dot(P−M, u_in) > 0` (passed abeam of the mark relative to the incoming leg, the Signal K "perpendicularPassed" idea) **or** (ii) the zone was entered and then left. Gate: only while `d ≤ 2 nm`, and the condition must hold for **10 consecutive seconds** (debounce; GPS noise is negligible against 0.3–0.6 nm radii, but tack wobble isn't). Then advance, push a banner "Marque suivante : Blitvenica — Annuler" (60 s) and persist.
- **Annuler** restores `active_idx` and sets `suppress_until_exit[mark]` so it can't re-fire until the boat leaves the zone.
- Manual next/prev clears the pending advance.
- **Finir ici** (CRSE-04) on mark k: `finish_idx = k` (the course is truncated after k and the UI shows "ARRIVÉE à k"). Reaching the finish ends auto-advance.
- Hairpin (Jabuka in A: in 203°, out 009°): criterion (i) fires when abeam of the island. That is slightly early but safe, and laylines then point to Blitvenica. Accept it and document.

### Pattern 7: Persistence (CRSE-05)
`atomic_write_json(path, obj)` / `load_json_with_bak(path, default)` [VERIFIED: src/jabuka/common/atomicio.py:41-53]. Files go in `--data-dir` (Pi: `/var/lib/jabuka`, from `ExecStart=… --http-port 80 --data-dir /var/lib/jabuka …` and `ReadWritePaths=/var/lib/jabuka`) [VERIFIED: deploy/systemd/jabuka-core.service:21,32]:
`course.json` (includes `active_idx`, `finish_idx` and a pending-advance timestamp, so a power cut mid-race resumes on the right mark), `settings.json` (variation, heading offset, heading_ref_unknown, efficiency, layline source, current on/off, zone center/radius, damping τ, manual-wind age limit) and `wind_manual.json`. Validate with pydantic on load and fall back to defaults with an alert. Use `base_version` optimistic concurrency on PUT (409 on mismatch).

Race pack dir: new flag `--racepack DIR` (default `<data-dir>/racepack`). It holds `race.pmtiles`, `seamarks.geojson` and an optional `polar.json` (else the packaged placeholder). The tablet copy is scp'd at the dock. The binaries are gitignored.

### Pattern 8: Map editing (CRSE-02) and land warning
Tap → `map.queryRenderedFeatures(e.point, {layers: ["earth"]})`. A non-empty result means the point is on land, so warn "Marque à terre ?" and offer to keep it or move it. The Protomaps style has a fill layer with id `earth` on source-layer `earth` [VERIFIED: generated style inspected]. Drag = `pointerdown` on the mark's circle layer → `map.dragPan.disable()` → pointermove updates a temp GeoJSON → `PUT` on pointerup. Editing is only allowed in the Carte tab and only when unlocked.

### Pattern 9: Helm view numbers (HELM-02)
Primary number from the actual damped |TWA| with ±5° hysteresis: < 70 → target TWA up; > 110 → target TWA down; else CTS. Secondary: deviation (TWA − target, coloured), BSP / target BSP, % polar, DTW / TTW, "Virement dans 12 min" (or "Empannage dans …"), other-tack heading, source badge, `CAP NON FIABLE` in the zone. All values come from the WS `nav` message. The browser formats only.

### Pattern 10: Night style (HELM-03) — generated, red channel only
Generate `style-night.json` at vendoring time. Map every colour of the `BLACK` flavor to `#RR0000` with `RR = round(luminance × 0.55)`, then set `water = background = "#000000"` and `earth = "#260000"` (land/sea contrast). On the night style, delete `icon-image` from `places_locality` and drop `roads_shields`, `roads_oneway` and `pois` (their sprites contain grey/white). The night overlay (marks, laylines, boat) uses red only. CSS: `background:#000`; numbers `#ff0000`-family with a user brightness factor. Override MapLibre control CSS (`.maplibregl-ctrl-attrib` is white by default). Verified render: [VERIFIED: headless screenshot this session].

```js
// Source: scratchpad/scripts/build-styles.mjs (executed this session with @protomaps/basemaps 5.7.2)
const B = await import(basemapsEsmPath);                 // dist/esm/index.js
const toRed = (hex) => { const n = parseInt(hex.slice(1), 16);
  const lum = 0.2126 * (n >> 16 & 255) + 0.7152 * (n >> 8 & 255) + 0.0722 * (n & 255);
  return "#" + Math.round(lum * 0.55).toString(16).padStart(2, "0") + "0000"; };
const mapFlavor = (f) => Object.fromEntries(Object.entries(f).map(([k, v]) =>
  [k, typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v) ? toRed(v) : (v && typeof v === "object" ? mapFlavor(v) : v)]));
const night = { ...mapFlavor(B.namedFlavor("black")), water: "#000000", background: "#000000", earth: "#260000" };
const style = (layers, sprite) => ({ version: 8, glyphs: "/glyphs/{fontstack}/{range}.pbf", sprite: "/sprites/" + sprite,
  sources: { protomaps: { type: "vector", tiles: ["/tiles/{z}/{x}/{y}.mvt"], maxzoom: 14,
    attribution: '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>' } },
  layers });
// write style("light") with B.layers("protomaps", B.namedFlavor("light"), {lang: "hr"}) and style(night)
```

### Pattern 11: Lock mode (HELM-04)
A full-screen `div` above everything with `touch-action:none`, swallowing `pointerdown/move/up` and `wheel`. The only hit target is a 64 px padlock: `pointerdown` starts a 2 s timer and `pointerup/pointercancel/pointerleave` clears it. Ignore it when `event.isPrimary === false` (multi-touch spray). Show a progress ring. While locked, also `map.dragPan/scrollZoom/touchZoomRotate.disable()`. Add `<meta name="viewport" content="…, user-scalable=no">`. Put the pure timing logic in `lock_logic.js` (node-testable).

### Pattern 12: Screen awake (HELM-04)
```js
// Source: pattern from NoSleep.js 0.12.0 src (read this session) + Screen Wake Lock spec behaviour
let lock = null, nosleep = null;
export async function keepAwake() {                       // call from a user gesture (first tap)
  if ("wakeLock" in navigator) {
    try { lock = await navigator.wakeLock.request("screen"); return "verrou"; } catch (e) { /* fall through */ }
  }
  nosleep ??= new NoSleep();                              // vendor/NoSleep.min.js (UMD global)
  if (!("wakeLock" in navigator)) { await nosleep.enable(); return "vidéo"; }
  return "aucun";                                          // native rejected: NoSleep would retry native
}
document.addEventListener("visibilitychange", () => {      // locks are released when hidden
  if (document.visibilityState === "visible" && lock !== null) keepAwake();
});
```
Verified: Chromium 148 on an insecure IP origin gives `{"secure":false,"wakeLockInNavigator":false}`. With `--unsafely-treat-insecure-origin-as-secure=<origin>` it gives `{"secure":true,"wakeLockInNavigator":true}` [VERIFIED: local headless run]. Android: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, value `http://10.42.0.1` [CITED: chromium.org "Deprecating Powerful Features on Insecure Origins"; Android behaviour not tested here → human item]. Always also set Android "Stay awake while charging" (Developer options). Show a badge "ÉCRAN: verrou / vidéo / aucun".

### Pattern 13: Tile endpoint (HELM-01)
```python
# Source: verified this session (index build 4.6 ms for 6190 entries; lookup+slice 3.4 µs vs Reader.get 3.2 ms)
import mmap
from pmtiles.reader import deserialize_directory, deserialize_header, zxy_to_tileid

class TileIndex:
    def __init__(self, path):
        self._f = open(path, "rb")
        self.mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self.header = h = deserialize_header(self.mm[0:127])
        self.idx: dict[int, tuple[int, int]] = {}
        stack = [(h["root_offset"], h["root_length"])]
        while stack:
            off, length = stack.pop()
            for e in deserialize_directory(self.mm[off:off + length]):
                if e.run_length == 0:
                    stack.append((h["leaf_directory_offset"] + e.offset, e.length))
                else:
                    for i in range(e.run_length):
                        self.idx[e.tile_id + i] = (h["tile_data_offset"] + e.offset, e.length)
    def get(self, z, x, y):
        hit = self.idx.get(zxy_to_tileid(z, x, y))
        return None if hit is None else self.mm[hit[0]:hit[0] + hit[1]]

@app.get("/tiles/{z}/{x}/{y}.mvt")
def tile(z: int, x: int, y: int) -> Response:
    if not (0 <= z <= 14 and 0 <= x < 2**z and 0 <= y < 2**z) or tiles is None:
        return Response(status_code=204)
    data = tiles.get(z, x, y)
    if data is None:
        return Response(status_code=204)                   # empty tile, no MapLibre error
    return Response(data, media_type="application/vnd.mapbox-vector-tile",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=3600"})
```
The extract's header says `tile compression: gzip`, `tile type: mvt` [VERIFIED: `pmtiles show`]. Assert `header["tile_compression"] == Compression.GZIP` at load. Register the route **before** the static mount (the existing comment says "Static files LAST").

Client: fetch the style JSON, absolutize, then construct the map. Relative URLs fail with `Invalid sprite URL "/sprites/light", must be absolute` and `Failed to parse URL from /tiles/11/…` [VERIFIED: headless run]. `transformStyle` is a `setStyle` option, not a constructor option (constructor use was silently ignored in the test):
```js
const abs = (s) => { const o = location.origin; s.glyphs = o + s.glyphs; s.sprite = o + s.sprite;
  for (const src of Object.values(s.sources)) if (src.tiles) src.tiles = src.tiles.map((t) => o + t); return s; };
const map = new maplibregl.Map({ container: "map", style: abs(await (await fetch(`/style-${theme}.json`)).json()),
  center: [15.70, 43.45], zoom: 9, maxBounds: [[14.9, 42.7], [16.4, 44.1]], attributionControl: { compact: true } });
// theme switch: map.setStyle(abs(nextStyleJson), { transformStyle: (prev, next) => ({ ...next,
//   sources: { ...next.sources, ...overlaySources(prev) }, layers: [...next.layers, ...overlayLayers(theme)] }) });
```

### Offline map prep (laptop) — exact steps
1. `pmtiles extract https://build.protomaps.com/YYYYMMDD.pmtiles race.pmtiles --bbox=15.0,42.8,16.3,44.0 --maxzoom=14`. Result: 12 MB, 66 requests, about 12 s (maxzoom 15 = 21 MB) [VERIFIED: run 2026-11-06 against `20261105.pmtiles`, 139 GB, `accept-ranges: bytes`]. Daily builds are kept for **one week** [CITED: docs.protomaps.com/basemaps/downloads]. The script tries today, then going back 7 days.
2. `curl -L https://download.geofabrik.de/europe/croatia-latest.osm.pbf` (201 MB, ~30 s) → pyosmium `FileProcessor(pbf).with_locations().with_filter(KeyFilter("seamark:type"))`, clipped to the bbox. Result: **1657 features, 3.3 s, 267 KB** [VERIFIED: run this session]. Keep the types `light_*`, `beacon_*`, `buoy_*`, `rock`, `wreck`, `obstruction`, `landmark`, `marine_farm` (night hazard). Drop `mooring`, `small_craft_facility`, `seagrass` and similar.
3. Vendoring (once, committed): `npm pack maplibre-gl@5.24.0 nosleep.js@0.12.0 @protomaps/basemaps@5.7.2` (no install scripts run), check `dist.integrity`, copy the dist files, `curl` the glyph ranges and `sprites/v4/{light,dark}*` from `https://protomaps.github.io/basemaps-assets/`, run `node scripts/build-styles.mjs …/dist/esm/index.js src/jabuka/web/static`. Include `LICENSE.txt` (MapLibre BSD-3), `OFL.txt` (fonts), and ODbL attribution in the style.

### Anti-Patterns to Avoid
- **Computing nav maths in the browser:** two tablets would disagree. The server computes, the browser formats.
- **`Reader.get()` per request on the Pi:** it re-deserializes the root directory each call. Build the index once.
- **Async `def` tile route doing CPU work:** blocks the 1 Hz tick. With the index, the work is µs, so `def` (threadpool) or `async def` are both fine.
- **Damping degrees as scalars:** wraps at 0/360. Use vectors.
- **Adding current twice** in sailed-angle mode (ground angles already include it).
- **Trusting `ref == "?"` as true:** treat unknown as magnetic by setting and show it on Diag.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Apparent→true wind, M↔T, u/v | new formulas | `jabuka.common.conventions` | Already golden-tested; sign conventions pinned |
| Crash-safe JSON | own fsync code | `atomicio.atomic_write_json` / `load_json_with_bak` | Already proven against power cuts |
| PMTiles parsing | own v3 parser | `pmtiles.reader` (`deserialize_header/directory`, `zxy_to_tileid`) | Hilbert tile-id maths, run-length entries, leaf dirs |
| Basemap styling | hand-written style JSON | `@protomaps/basemaps` `layers()` + flavor | 71 layers matched to the tile schema |
| Seamark parsing | regex over OSM XML | pyosmium `FileProcessor` + `KeyFilter` | Way node locations, PBF decoding |
| Video wake fallback media | own base64 video | NoSleep.js | Battle-tested data URIs, mp4/webm handling |
| WS fan-out | new hub | existing `Hub` (drop-oldest queues) | Already handles slow clients |
| Headless browser | Selenium/xvfb | Playwright + system Chromium | Verified working, no sudo |

**Key insight:** the only genuinely new maths is about 150 lines (layline decomposition, vector EMA, polar curves, rounding FSM). Everything else is wiring around already-tested Phase 1 seams or vendored upstream code.

## Common Pitfalls

### Pitfall 1: Wrong Chrome-flag origin
**What goes wrong:** Wake Lock is still missing on the boat. **Why:** CONTEXT says `http://10.42.0.1:8080`, but the Pi serves on **port 80** (`--http-port 80`; PI-SETUP: "http://10.42.0.1/"). The flag needs the exact origin (scheme, host and port). **Avoid:** document `http://10.42.0.1` for the boat and `http://<laptop-ip>:8080` for dev. **Warning sign:** the badge shows "ÉCRAN: vidéo" or "aucun".

### Pitfall 2: Relative URLs in the MapLibre style
Sprite and tile URLs must be absolute (verified errors above). Absolutize client-side before `new Map()`.

### Pitfall 3: Missing glyph ranges = missing labels, silently
Croatian č/ć/š/ž/đ live in `256-511`. Vendor at least `0-255`, `256-511`, `512-767` and `8192-8447` (punctuation) per font. The Playwright smoke test asserts no HTTP ≥ 400.

### Pitfall 4: Night mode leaks white/green light
Default sprites (road shields, POIs), the MapLibre attribution box, focus outlines, scrollbars and the Android status bar. Strip icons in the night style, override control CSS, use fullscreen, and only `#xx0000` colours. `#ff2a00` contains green; prefer a pure red channel.

### Pitfall 5: WS silent staleness on the helm
On a half-open Wi-Fi link the last numbers stay on screen (Phase 1 review WR-05). The helm must grey out and show "PERTE DONNÉES" when no message arrives for 3 s, and close/reconnect after 6 s.

### Pitfall 6: Manual TWD entered as magnetic, treated as true
The B&G display may show TWD in °M. Add an M/T selector on the manual form (default M), and convert at the boundary.

### Pitfall 7: Jabuka anomaly corrupts instrument TWD too
Not only our own TWD: Hercules TWD and set/drift are compass-derived. Inside the zone, ignore them and use COG for TWD. Freeze sailed-angle learning there.

### Pitfall 8: Double-counting current
In sailed-angle mode (COG-based angles) don't add `c`. In polar mode with NAV-03 on, do add `c`. Unit-test both.

### Pitfall 9: Efficiency factor moving laylines
It must not change target angles (uniform scaling), only speeds and times. A test asserts that `targets(tws).twa` is independent of `eff`.

### Pitfall 10: Drop-oldest WS queue loses "course" updates
`WS_QUEUE_MAX = 4` with drop-oldest [VERIFIED: src/jabuka/core/web.py:20]. A one-off `course` message can be dropped for a slow client. Put `course_version`/`settings_version` in every `nav` message. The client re-GETs `/api/course` when they differ. Also send course and settings in the on-connect snapshot.

### Pitfall 11: Auto-advance misfires
Passing near a mark on a different leg, or tacking at the zone edge. Mitigate with active-mark-only, the 2 nm gate, the 10 s debounce, suppress-after-undo, and never advancing from the start index.

### Pitfall 12: NoSleep does not fall back when native Wake Lock rejects
`NoSleep.enable()` picks native whenever `navigator.wakeLock` exists and just throws on rejection (read in its source). Use the wrapper (Pattern 12) and the OS stay-awake setting.

### Pitfall 13: Existing tests pin "/" to the diagnostics page
`tests/test_tracer_e2e.py:120` asserts `"Jabuka diagnostics" in page.text` for `GET /`, and `tests/test_event_marker.py:102` reads `/` [VERIFIED: grep + read]. Moving diag to `/diag.html` and making `/` the app shell requires updating those tests in the same plan. `diag.js` already ignores non-`diag` messages (`if (msg.type !== "diag") return;`, diag.js:138), so a new `nav` type is safe.

### Pitfall 14: New nav modules escape the wall-clock ban
`_scanned()` only globs `core/*.py` and `common/*.py` [VERIFIED: tests/test_no_wallclock.py:42-44]. Extend it to `nav/*.py` (and `prep` excluded).

### Pitfall 15: Pi lock drift
Adding `pmtiles` to pyproject without `deploy/requirements.in`, `EXPECTED_LOCKED` (`tests/deploy/test_lock.py:11`) and a relock breaks `test_lock` and the offline Pi install. One task must do all four.

### Pitfall 16: Displaying true headings to a helm steering by a magnetic compass
CTS and other-tack heading in °T differ from the B&G/compass by ~4.7°. Always suffix °T/°M and make the helm heading display unit a setting (Open Question 2).

### Pitfall 17: Laylines through the island
Anchoring at the island centroid makes the "fetching" call put you on the rocks of Jabuka at night. Anchor at radius on the rounding side (Pattern 4).

## Code Examples
See Patterns 2 (VectorEma), 4 (decompose), 10 (night style), 12 (wake lock) and 13 (tile index + endpoint + client). The seamark extractor (verified run):
```python
# Source: scratchpad/scripts/seamarks.py — pyosmium 4.3.2, 1657 features in 3.3 s
import osmium
from osmium.filter import KeyFilter
fp = osmium.FileProcessor(pbf_path).with_locations().with_filter(KeyFilter("seamark:type"))
for o in fp:
    if o.is_node():
        lon, lat = o.location.lon, o.location.lat
    elif o.is_way():
        pts = [(n.lon, n.lat) for n in o.nodes if n.location.valid()]
        if not pts:
            continue
        lon, lat = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    else:
        continue
    # keep if inside bbox and seamark:type in the allow-list; props from o.tags[...]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raster OSM tiles + CSS invert for night | Vector tiles + generated flavor styles | Protomaps v4 / basemaps 5.x | True red-only night, tiny pack |
| Browser PMTiles protocol (HTTP Range) | Server-side PMTiles index → plain XYZ | (project decision) | No extra JS lib, no Range quirks |
| `osmium-tool` via apt | pyosmium 4.x `FileProcessor` + filters | pyosmium 4.0 | pip-installable, no sudo |
| `playwright install chromium` | `executable_path="/usr/bin/chromium"` | — | No browser download |

**Deprecated/outdated:** MapLibre v6 (WebGL2-only, ESM-only) is deliberately not used. `@protomaps/basemaps` CLI `generate_style` points at a `.ts` file (`./src/cli.ts`), so use the ESM API from node instead.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default rounding sides: Course A starboard, Course B port (loop geometry) | Race Marks | Wrong side → laylines/anchor on wrong side; auto-advance still works. SIs decide (human) |
| A2 | Vodice start/finish placeholder 43.7500 N 15.7800 E | Race Marks | First/last leg DTW off by < 0.5 nm until the SI line is entered |
| A3 | Jabuka unlit (no light found in OSM) | Race Marks | Only a display/brief note; check the chart |
| A4 | Committing ORC-derived numbers with attribution is acceptable | X35 polar | Licence complaint → keep the polar in the gitignored race pack instead |
| A5 | ORC beat angles are narrower than the instrument TWA upwind | X35 polar | Laylines too tight; mitigated by sailed-angle mode |
| A6 | Android Chrome's `chrome://flags` switch exposes Wake Lock exactly like desktop | Pattern 12 | Screen sleeps; mitigated by NoSleep video + OS stay-awake |
| A7 | NoSleep video keeps an Android tablet awake | Pattern 12 | Same mitigation |
| A8 | Pi 3B `Reader.get` ≈ 30 ms (10× x86) | Pattern 13 | Irrelevant if the index is used |
| A9 | Heading with unknown ref (`"?"`) should default to magnetic | Pattern 2 | 4.7° rotation of TWD and laylines; visible on Diag, a setting |
| A10 | Arrival zone = radius + 0.25 nm, 2 nm gate, 10 s debounce suit offshore marks | Pattern 6 | Early or late advance; undo exists |

## Open Questions (RESOLVED)

Resolution (2026-11-07): Q1 rounding sides → defaults + "Côtés à confirmer (IC)" flag in 02-01, confirm at briefing (human item); Q2 → settings heading_display="M"; Q3 → settings true_wind_source="computed"; Q4 tablet WebGL and Q5 real X35 polar → end-of-phase human items.

1. **Rounding sides and start/finish line (SIs not published / 403).**
   - Known: course order and "check point can be an auxiliary finish".
   - Recommendation: ship the defaults (A1/A2) with a red "à confirmer" flag in Carte. Human checkpoint at the skipper briefing.
2. **Heading display reference on the helm (°M vs °T).**
   - Known: internals are true. The B&G displays and the compass are likely magnetic.
   - Recommendation: setting `helm_heading_ref`, default **M**, with a suffix always shown. Ask the user.
3. **Own true wind vs Hercules true wind as primary.**
   - CONTEXT locks "computed + cross-check". Hercules TW includes calibration tables (upwash).
   - Recommendation: keep computed as default, add setting `tw_primary: computed|instrument` and decide on 12 Nov from the cross-check.
4. **Tablet model / WebGL.** Unknown. Check `chrome://gpu` early. MapLibre 5.24 falls back to WebGL1 (verified in source).
5. **Real X35 polar file.** The user mentioned one. Its loader formats are covered. Human item: "load your real X35 polar".

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| node | style generation, JS logic tests | ✓ | v24.21.0 (`/usr/bin/node`) | — |
| npm | `npm pack` for vendoring | ✓ | 9.2.0 | direct tarball curl from registry |
| go | `go install go-pmtiles` | ✓ | 1.24.4 | release binary (downloaded + ran OK) |
| go-pmtiles CLI | basemap extract | ✗ installed (✓ release binary works) | 1.31.2 | — |
| osmium-tool | seamarks | ✗ | — | pyosmium 4.3.2 wheel (verified) |
| chromium | Playwright UI tests | ✓ | 148.0.7778.167 | google-chrome 146 |
| uv | venvs/lock | ✓ | 0.6.6 | — |
| Python | tests | ✓ | 3.14.7 (.venv), 3.13.12 (.venv313) | — |
| Internet (protomaps, geofabrik, unpkg) | prep/vendoring only | ✓ | — | race pack must be built before leaving shore |
| Disk on /home | prep downloads | ⚠ 13 GB free (96% used) | — | Fine for 201 MB pbf + 12 MB pack; don't download the full planet |

**Missing dependencies with no fallback:** none.
**Missing with fallback:** osmium-tool → pyosmium; pmtiles CLI → release binary or `go install`.

## Verification Map (success criteria → tests)

> `workflow.nyquist_validation` is `false` in `.planning/config.json`, so this replaces the formal Validation Architecture section, as the orchestrator requested (item 7).

| SC | Behaviour | Automated on laptop | Human on tablet/boat |
|----|-----------|---------------------|----------------------|
| 1 | Helm shows map + boat + marks + course; primary number by point of sail; deviation, target BSP, %polar, DTW/TTW, countdown | pytest: polar parse/targets/pct; `nav` message schema via TestClient WS; node: `helm_logic.js` primary-number selection + hysteresis; Playwright: page loads offline (no external requests), map `idle`, zero HTTP ≥ 400, primary number font ≥ 20% of viewport height | Read numbers in sunlight and at night |
| 2 | Laylines ~1 Hz, dist/time to layline, overstood, other-tack heading, polar/sailed toggle, set/drift toggle | pytest: analytic decomposition cases (symmetric beat, overstood, fetching, current), sailed-angle detection on synthetic tracks, current double-count guard; closed-loop sim at 20–60× on `--clock sim`: boat tacks when countdown ≤ 0 and fetches the mark | Visual sanity vs B&G on 12 Nov |
| 3 | Course A/B one action; tap add/move/delete; side/radius; reorder; auto-advance + undo; next/prev; finish here; survives reboot | pytest: course API (409 base_version, validation bounds), FSM (abeam, enter/leave, debounce, undo suppression, hairpin), persistence via restart of `CoreContext` + kill mid-write (reuse Phase 1 crash tests); Playwright: tap on map adds a mark (land warning on the `earth` layer) | Course-change drill < 30 s; confirm sides vs SIs |
| 4 | Everything TRUE; variation/offset; own TW damped; manual TWD/TWS with badge; Jabuka COG | pytest: M/T boundary incl. `ref "?"`, VectorEma wrap at 359/1°, arbitration LIVE>MANUEL>none + stale, manual M/T entry, zone switch to COG; sim with `bus-silent` fault → badge MANUEL | COG vs HDG motoring check on board |
| 5 | Night true black/red; lock ignores touches; screen awake | node: lock long-press logic; Playwright: night theme computed styles contain no non-red colours on helm elements; lock overlay blocks a click on the map; `--unsafely-treat-insecure-origin-as-secure` run reports wake state "verrou" | Real tablet: flag set, stays awake ≥ 30 min, night readability, wet-finger test |

**Commands:** quick `.venv/bin/python -m pytest -q tests/nav tests/web -x`; full `bash scripts/check.sh`. Playwright tests `pytest.importorskip("playwright")` + skip if `shutil.which("chromium")` is None; JS logic via the existing node harness pattern of `tests/test_diag_logic.py` (`node --input-type=module -e`).

**Wave 0 gaps:** `tests/nav/` (polar, wind, laylines, course, tacks), `tests/web/test_tiles.py` (uses a tiny PMTiles fixture. Generate one in-test by `pmtiles extract` of a single z0–z6 box, or commit a ≤ 200 KB extract as a fixture), `tests/ui/test_helm_smoke.py` (Playwright), extend `tests/test_no_wallclock.py` to `nav/`.

## Security Domain

`security_enforcement: true`, ASVS level 1.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (WPA2 AP is the boundary; document) | — |
| V3 Session Management | no | — |
| V4 Access Control | partial | Any AP client can edit the course. Mitigate with optimistic concurrency + undo + event log of edits; note IN-08 (bind dev to 127.0.0.1) |
| V5 Input Validation | yes | pydantic models: lat ∈ [42, 45], lon ∈ [14, 17], radius ∈ [0, 3] nm, name ≤ 40 chars (control chars stripped, reuse `strip_control`), ≤ 30 marks, efficiency ∈ [0.5, 1.2], variation ∈ [−30, 30]°; tile z/x/y ints range-checked |
| V6 Cryptography | no | — |
| V12 Files/Resources | yes | Tile route reads only from an index (no path from the user); race-pack path from CLI only; static mount stays last |
| V14 Config | yes | Vendored assets pinned by integrity hash; no CDN at runtime |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via mark names on other tablets | Tampering | Render with `textContent` only. MapLibre `text-field` from GeoJSON is safe (no HTML) |
| Course vandalism / accidental edits from a 2nd device | Tampering | base_version 409, undo, edit log line in the events log |
| Oversized JSON bodies | DoS | pydantic `max_length` on lists/strings |
| Malicious `.pmtiles`/GeoJSON in race pack | Tampering | Built by our own prep; validate header type/compression at load; GeoJSON served as a static file, not parsed by the core |

## Sources

### Primary (HIGH confidence)
- Repo files read this session: `src/jabuka/common/{conventions,units,atomicio}.py`, `core/{state,web,main}.py`, `sim/synth.py`, `ingest/{fastnet_decode,gpsd_client}.py`, `deploy/systemd/jabuka-core.service`, `deploy/requirements.in`, `tests/test_no_wallclock.py`, `tests/deploy/test_lock.py`, `tests/test_diag_logic.py`, pyfastnet `data/fastnet.json`.
- Local executions: go-pmtiles 1.31.2 extract, `pmtiles show`, Python pmtiles reader + index benchmark, pyosmium seamark extraction, node style generation, FastAPI tile server + MapLibre 5.24.0 render in headless Chromium 148 via Playwright 1.64.1, Wake-Lock flag test, layline prototype.
- OSM Overpass API / Nominatim: nodes 498394251, 8883790953, 1377046673, 498383293; ways 10520887, 8838344, 6186065; Vodice coastline/seamarks.
- NOAA NCEI WMM-2025 declination API (43.4 N 15.65 E, 2026-11-13: 4.72136°, ±0.346°).
- ORC certificate PDF `data.orc.org/public/od/2019/x35.od.pdf`.
- npm registry (`npm view` integrity/versions), PyPI JSON (pmtiles, osmium, playwright, pygeomag), GitHub API (go-pmtiles releases, basemaps-assets tree).

### Secondary (MEDIUM confidence)
- [Notice of Race](https://www.regata-jabuka.com/index.php/en/notice-of-race), [regata-jabuka.com](https://www.regata-jabuka.com): courses, auxiliary finish, schedule.
- [Protomaps downloads docs](https://docs.protomaps.com/basemaps/downloads): 1-week retention, ODbL, style compatibility.
- [Chromium: Deprecating Powerful Features on Insecure Origins](https://chromium.org/Home/chromium-security/deprecating-powerful-features-on-insecure-origins): flag location and semantics.
- [Samsung browser policy page](https://developer.samsung.com/browser/policy/override-security-restrictions-on-insecure-origin.html): enterprise override precedence.

### Tertiary (LOW confidence)
- [nautica.news 22nd Jabuka](https://nautica.news/?p=42709), web search snippets about past courses (Komorica variant, start times). Not used for decisions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH. Every component was installed or run locally. Versions come from the registries.
- Map/tiles/night style/wake lock: HIGH on desktop Chromium. MEDIUM for the Android tablet (untested hardware).
- Nav maths: HIGH for the geometry (prototype + analytic checks). MEDIUM for the tuning constants (damping, zone, debounce).
- Marks: HIGH for positions (OSM). LOW for rounding sides and the start line (SIs unread).
- Polar: MEDIUM. Credible ORC class data, but optimistic for night racing.

**Research date:** 2026-11-06
**Valid until:** 2026-11-13 (race). Protomaps daily build URLs expire after 7 days, so re-extract with a current date.
