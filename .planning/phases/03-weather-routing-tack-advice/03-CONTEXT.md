# Phase 3: Weather Routing & Tack Advice - Context

**Gathered:** 2026-11-07
**Status:** Ready for planning
**Mode:** Smart discuss auto-accepted — user is AFK and explicitly asked to "continue without me". Decisions are Claude's recommended answers grounded in `.planning/research/` (ARCHITECTURE.md "Router design details", STACK.md, PITFALLS.md, SUMMARY.md) and the user's explicit requirements (tack countdown, "On reste", cost of not tacking, auto-recompute after 2 min, route must never cross land). Revisit if the user objects.

<domain>
## Phase Boundary

Optimal route from the boat through the remaining marks using live-corrected GRIB wind, polar × efficiency, waves and current — never crossing land — rerun automatically on the Pi without blocking the live display, plus stable tack advice (route-based countdown, stay-on-this-tack, cost of not tacking, auto-recompute 2 min after a missed advised tack). Includes the laptop race-pack prep tool (GRIB/waves/current/land mask) and the GPS+GRIB-only degraded mode.

Not in this phase: polar/laylines/course/map UI basics (Phase 2 — consumed here), soak/hardening/runbook (Phase 4).

</domain>

<decisions>
## Implementation Decisions

### Race pack prep (laptop: `jabuka-prep`)
- Downloads **ICON-EU** (DWD opendata, regular lat/lon, 10 m U/V; latest run covering 13 Nov 18Z → 15 Nov 10Z local) and **EWAM** waves (significant wave height + mean direction) from opendata.dwd.de; imports any GRIB1/GRIB2 file (organizer forecast) with pygrib; imports Copernicus Med currents NetCDF (user downloads with their free account / `copernicusmarine` CLI — tool accepts a file path; credentials never stored in repo).
- Crops to race bbox ≈ 15.0–16.3E, 42.8–44.0N; writes `wind.npz` (u, v float32 [t, lat, lon], UTC epoch seconds, model/run metadata), `waves.npz`, `current.npz` into a gitignored race-pack dir, plus `landmask.npz` and a coverage report.
- **Coverage validation (GRIB-02)**: every mark and every hour 13 Nov 18:00 → 15 Nov 10:00 local (UTC+1) must be inside the data; otherwise loud warning in the prep output and on the Pi Diag/helm.
- DWD keeps only ~24 h of runs → the prep tool must be re-run Friday before the start; document in runbook.
- Organizer forecast format still unknown → generic GRIB importer + clear error for other formats.

### Land mask & never-cross-land (ROUT-01, ROUT-11)
- Source: OSM land polygons (osmdata.openstreetmap.de land-polygons-split-4326, cropped) + hand hazard polygons (Plić Sestre shoal, reefs near Blitvenica/Jabuka, any other charted dangers found via OSM seamark hazards/rocks).
- Rasterized on the laptop to a boolean grid at ≈ 25–50 m resolution in a local equirectangular frame — fine enough that the **narrow inter-island channels of the Šibenik archipelago stay open** (e.g. Prvić–Tijat, Zlarin channel); then dilated by a configurable **shore margin (default 100 m; hazards 200 m)**. Narrowest critical channel width must be measured and the margin validated so no required channel closes.
- **Segment-level check**: every isochrone expansion segment is sampled at ≤ half-cell spacing (or Bresenham/DDA over the raster) — not just endpoints. A segment touching land is rejected.
- **Test suite of island-crossing cases** with known geometry: Vodice → open sea (must exit via a real channel), straight line through Prvić/Zlarin/Tijat must be rejected, rounding Blitvenica and Jabuka by the correct side, passing Plić Sestre. Every computed route polyline is re-validated against the mask (assertion in tests; runtime sanity check flags and discards an invalid route).
- Marks placed on land (islands as marks) → rounding waypoints on a circle of per-mark radius at sea (from Phase 2 course model).

### Router
- Own numpy-vectorised isochrone engine (port of libweatherrouting's approach; libweatherrouting only as test oracle/fallback). Local planar frame in nm; headings every 5° (degraded: 10°); time step 10–15 min near the boat growing to 30–60 min far out; pruning by bearing sectors from start; tack/gybe penalty (default 45 s, configurable) on heading side change; u/v trilinear interpolation (space + time); polar × efficiency (Phase 2 settings) × wave factor; current vector added to velocity.
- Wave factor: speed multiplier f(Hs, TWA sector) from a small table (default ~ -5 %/m of Hs upwind, less downwind, cap -30 %), else f(TWS) when no wave file. Tunable; LOW-confidence numbers documented.
- Multi-leg sequential: arrival of leg k starts leg k+1; whole remaining course for ETA; UI emphasises current leg.
- Pure function `route(RouteRequest) -> RouteResult` in a `ProcessPoolExecutor(max_workers=1)` worker at nice 10, 60 s timeout, recreated on crash; last good route kept with age. Routing blocked until the GPS clock gate is ok (Phase 1).
- **Pi 3B benchmark gate (2026-11-09)**: a benchmark script with a realistic remaining-course scenario; if optimal + forced-tack routes don't fit the cadence, apply documented degraded settings in order: 10° headings → 30-min steps → route next mark + one only → cadence 10 min → cost-of-not-tacking every other cycle.

### Wind correction (WIND-05, WIND-06)
- Wind source now: LIVE > MANUAL > GRIB-only (GPS + GRIB) — badge shows GRIB when the bus is silent.
- Bias estimator: measured (damped, steady-sailing gate: no tack in last 3 min, all inputs fresh, BSP > 2 kn) minus GRIB at boat position/time, averaged ~10 min, as direction offset + speed ratio; clamps ±35°, ratio 0.6–1.5; applied to the GRIB with exponential time decay τ default 2.5 h (configurable); shown on helm ("+12° ×1.15, fading"); toggle off; **frozen inside the Jabuka magnetic zone** (Phase 2 flag). Manual wind uses the same path.

### Supervisor, triggers, hysteresis (ROUT-02, ROUT-05, ROUT-09)
- Triggers: timer (default 5 min), course change, bias change beyond threshold, manual wind change, off-route (> 0.5 nm or > 20° heading divergence sustained 2 min), stay-on-tack toggled, **missed advised tack + 2 min**.
- Hysteresis: a new route replaces the current one only if it improves ETA by > max(3 min, 1 %) or the current route became invalid/outdated (> 20 min old) — except forced triggers (course change, stay-on-tack, missed tack) which replace immediately.

### Tack advice (ROUT-06..ROUT-10)
- Route segments carry target TWA + tack; the helm keeps steering the target TWA between reruns (heading = TWD + target TWA).
- **Countdown** to next recommended tack/gybe = time until the route's first side change (fallback: Phase 2 layline countdown when no valid route).
- **"On reste" (Stay on this tack)** button: rerun with first leg forced on current tack for a minimum duration (default: until the next route-suggested tack point is ≥ 5 min later than optimal) → earliest next tack + updated countdown; persists until the next tack is detected or the user cancels.
- **Cost of not tacking now** = ETA(forced current tack) − ETA(optimal), minutes; computed every cycle as the second (forced) routing (or every other cycle when degraded).
- **Tack detection**: TWA sign change sustained > 30 s (with COG fallback inside the Jabuka zone).
- **Auto-recompute**: if now > advised tack time + 2 min and no tack detected → trigger reroute, display stops saying "VIRE" and shows "Route mise à jour…".

### Display
- Route polyline + next tack point on the map; helm adds countdown "Virement dans 08:30", cost "Ne pas virer : +4 min", "On reste" button (big, lock-mode aware), route age, routing health on Diag.

### Claude's Discretion
- Module layout (suggested `src/jabuka/route/`: `racepack.py`, `landmask.py`, `isochrone.py`, `supervisor.py`, `bias.py`; prep under `src/jabuka/prep/`), exact constants within the stated ranges, data formats.

</decisions>

<code_context>
## Existing Code Insights

- Phase 1: clock (GPS clock + routing time gate), units/conventions (golden-tested), atomic IO, state store, WS, synthetic boat (closed loop extended in Phase 2), diagnostics page.
- Phase 2 (being planned/executed in parallel): polar loader/targets/efficiency, wind pipeline + source arbitration, laylines, course model with rounding waypoints/radius, Jabuka zone flag, helm view + map. **Phase 3 plans must integrate with Phase 2 module interfaces** — the router core (prep, land mask, isochrone engine, bias math, benchmark) is pure and can be built before Phase 2 lands; UI/supervisor integration waits for Phase 2.

</code_context>

<specifics>
## Specific Ideas

- User (2026-11-06): "on va passer entre des îles, et le bateau ne doit pas passer au travers sur le routage" → ROUT-11 is a hard requirement with its own tests.
- User (2026-11-05): tack countdown, "On reste" button, cost of not tacking, auto-recompute after 2 minutes.
- No internet at sea → everything from the pre-start race pack.

</specifics>

<deferred>
## Deferred Ideas

- Multi-model/ensemble comparison, GRIB disagreement alarm (v2).
- Spatial decay of bias (time-only in v1).
- Polar learning from logs (v2).

</deferred>
