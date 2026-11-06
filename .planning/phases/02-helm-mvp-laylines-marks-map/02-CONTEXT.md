# Phase 2: Helm MVP — Laylines, Marks & Map - Context

**Gathered:** 2026-11-07
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted — user is AFK and explicitly asked to "continue without me". All decisions below are Claude's recommended answers, grounded in `.planning/research/` (FEATURES.md, ARCHITECTURE.md, PITFALLS.md, SUMMARY.md) and Phase 1 outcomes. Revisit if the user objects.

<domain>
## Phase Boundary

The helmsman can race to the next mark on laylines alone: polar targets, true-wind pipeline (live or manual), live laylines, course/marks management, offline map and a night-readable helm view in the tablet browser, served by the Phase 1 core (FastAPI + WebSocket). This is the guaranteed fallback if routing (Phase 3) never ships.

Not in this phase: GRIB, routing, route-based tack countdown, GRIB bias, waves/current files (Phase 3). Hardening/soak (Phase 4).

</domain>

<decisions>
## Implementation Decisions

### UI language & layout
- UI strings in **French** (user is French); code/identifiers in English.
- Single-page app, vanilla ES modules, no build chain, served from `src/jabuka/web/static/` by the existing core. Pages/tabs: **Barre** (helm, default), **Carte** (map + course editing), **Réglages** (settings), **Diag** (existing diagnostics).
- Helm view: map full-screen behind a top/bottom band of big numbers. Primary number by point of sail (D-6): |TWA| < ~70° → target TWA (upwind), |TWA| > ~110° → target TWA (downwind), else course to steer (CTS) to mark. Secondary: deviation (actual − target, colored), BSP vs target BSP and % polar, DTW/TTW to active mark, time/distance to layline ("Virement dans 12 min"), other-tack heading (D-7), wind source badge (LIVE / MANUEL / GRIB / PÉRIMÉ).
- Minimum font: primary number ≥ 20% of viewport height; all touch targets ≥ 48 px; lock mode = full-screen transparent overlay, unlock by long-press (≥ 2 s) on a padlock.

### Night mode & screen awake
- Two themes: day and night (true black #000 background, red #ff2a00-ish foreground, dimmed map with dark/red MapLibre style). Toggle button on helm view; persist in localStorage (per-viewer convenience).
- Screen awake: try Screen Wake Lock API; fallback NoSleep-style muted looping video; plus document the Android settings (stay awake while charging, Chrome flag `unsafely-treat-insecure-origin-as-secure` for http://10.42.0.1:8080) in a TABLET-SETUP doc. Human-verify on the real tablet.

### Map (offline)
- **MapLibre GL JS 5.24.0** (UMD build, vendored into static/vendor — pin exact version) + **Protomaps PMTiles** basemap extract for bbox ≈ 15.0,42.8,16.3,44.0 maxzoom ~14, served by the core as plain XYZ `/tiles/{z}/{x}/{y}.mvt` via the `pmtiles` Python reader (avoid browser Range requests). Glyphs + sprites vendored. Seamark overlay = OSM `seamark:*` GeoJSON extracted with osmium from Geofabrik Croatia (prep tool on laptop).
- Fallback if tablet lacks WebGL: Leaflet + protomaps-leaflet (document only; implement only if time allows).
- Prep tool (`jabuka-prep-map`, laptop) builds `race.pmtiles` + `seamarks.geojson` into a race-pack dir; binary outputs are NOT committed to git (gitignored), the build is reproducible by script. If downloading the Protomaps daily build fails, fall back to a smaller extract / raster-free style with coastline from OSM land polygons.
- Course-up / north-up toggle; boat centered option.

### Polar
- Polar file formats: OpenCPN/Expedition tab-separated (TWA rows × TWS cols) and CSV; bilinear interpolation; derive upwind/downwind target TWA & BSP per TWS (max VMG). Store as JSON in race pack.
- **No X35 polar file is in the repo yet** — user said they have a "polaire générique X35" but it was not provided. Executor must ship a clearly labelled **placeholder X35 polar** (from public sources if a credible one is found, else a conservative synthetic 35-ft cruiser-racer polar) and a loader so the user can drop the real file in. Flag as human-verify: "load your real X35 polar".
- Efficiency factor (default 0.92) applied to target BSP and routing; separate upwind/downwind factors optional.

### Wind pipeline
- Everything TRUE at one boundary: variation default +4.7°E (verify WMM 2026 Šibenik; configurable), heading offset (configurable), AWA sign config from Phase 1 (`awa_sign`).
- True wind computed from AWA/AWS/BSP/HDG (no leeway, no upwash in v1; leeway fixed configurable default 0°); cross-check against Hercules TWA/TWS/TWD when present; damping via circular EMA on vectors (τ ≈ 10 s for helm, ≈ 60 s for laylines TWD).
- Wind source arbitration: LIVE (instruments fresh) > MANUAL (user-entered TWD/TWS, sticky until cleared) > none; GRIB source arrives in Phase 3. Badge always visible. Stale threshold ~5 s.
- Jabuka magnetic zone (WIND-07): configurable center (Jabuka island) + radius default 3 nm; inside → heading untrusted, use GPS COG for laylines/true wind heading, flag on helm.

### Laylines
- Computed in the core at ~1 Hz: from the active mark, two lines at TWD ± target TWA (upwind or downwind as appropriate for the leg), with current offset when NAV-03 enabled (Hercules set/drift; off by default). Source toggle: polar target angles (×efficiency) vs actually sailed tacking angles (median of last tack(s) per side; fallback to polar if none).
- Outputs: layline geometry (GeoJSON) for the map, distance & time to layline on current tack, overstood flag, other-tack heading, time-to-tack countdown (= time to reach layline at current VMC/SOG).
- Reach legs (mark not upwind/downwind): no laylines; show CTS.

### Course & marks
- Mark library pre-loaded with the race marks: Vodice start/finish, Plić Sestre, Jabuka, Blitvenica, Mulo — coordinates to be researched precisely (OSM/charts) and stored in a JSON; islands are marks with a **rounding radius** (default: island → 0.5 nm offset from coast; Plić Sestre shoal → 0.3 nm) and side.
- Course A = Vodice → Plić Sestre → Jabuka → Blitvenica → Vodice; Course B = … → Jabuka → Mulo → Vodice. Rounding sides per NoR/SIs unknown → default sides configurable, user must confirm against SIs (human item).
- Map editing (Carte tab): tap to add mark, drag to move, tap mark → sheet with side (bâbord/tribord), radius, delete, reorder (up/down). One-tap course A/B select, next/prev, "Finir ici" (shorten course).
- Auto-advance: arrival circle (radius) entered then left OR bearing passes beam of mark → advance after 10 s, banner with "Annuler" for 60 s.
- Persistence: course + settings stored on the Pi via Phase 1 atomic IO (JSON), loaded at core start; REST endpoints for edits; WebSocket pushes changes to all clients.

### Simulation
- Extend L2 synthetic boat to closed loop: steers to the core's target TWA / CTS, tacks at laylines, to exercise laylines, auto-advance and countdown in automated tests.

### Claude's Discretion
- Exact REST/WS schema, CSS details, damping constants within stated ranges, module layout under `src/jabuka/nav/` (suggested: `polar.py`, `wind.py`, `laylines.py`, `course.py`, `marks.json`).

</decisions>

<code_context>
## Existing Code Insights (from Phase 1)

### Reusable Assets
- `src/jabuka/common/` — clock (System/Sim/GPS clocks + routing time gate), units & conventions (golden-tested), atomic IO, messages, sdnotify.
- `src/jabuka/core/` — state store (path → value/unit/source/ref/age), bus (UDP deltas), derived 1 Hz log, FastAPI web + WebSocket, main (`jabuka-core --clock {system,sim,gps} --gpsd`).
- `src/jabuka/sim/` — pty replay with faults, synthetic boat (UDP + pty modes, fault injection), fastnet encoder, fake gpsd.
- `src/jabuka/web/static/` — diagnostics page (index.html, diag.js, diag.css).
- `scripts/check.sh` — full gate (ruff + pytest on Python 3.13 and 3.14).

### Established Patterns
- SI units + Signal K-style paths internally; M/T ref preserved per value; injected clock for all domain time (no wall-clock calls — there is a test banning them); test-first (RED commit then GREEN); fixtures under tests/fixtures.

### Integration Points
- New nav computations hook into the core's 1 Hz tick and publish derived paths to the state store + WebSocket; static UI extends the existing web app.

</code_context>

<specifics>
## Specific Ideas

- User explicitly asked (2026-11-05) for time-to-next-tack on the helm; Phase 2 provides the layline-based countdown, Phase 3 the route-based one + "On reste" button, cost of not tacking, auto-recompute after 2 min.
- Race: night start 13 Nov 20:00–24:00 → night mode is critical.
- The route must never cross land (ROUT-11, Phase 3) — Phase 2 map must already render coastline/islands clearly and the course editor should warn if a mark is placed on land.

</specifics>

<deferred>
## Deferred Ideas

- Layline uncertainty wedge, lift/header bar (v2 TACT-01/02).
- Leaflet fallback implementation (only if tablet lacks WebGL).
- Upwash/heel-based TWA correction.

</deferred>
