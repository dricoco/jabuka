# Feature Research

**Domain:** Live offshore race navigation (live GRIB routing, laylines, helm display). Owner-built, offline, Pi 3B, tablet browser.
**Researched:** 2026-11-05
**Confidence:** MEDIUM overall. Expedition, OpenCPN Tactics, Freeboard-SK, SailGrib, Navimetrix and Raymarine behaviour comes from their official manuals and help pages. B&G SailSteer and qtVlm details come from secondary sources. The helm-UX recommendations are opinionated synthesis and are tagged as such.

**Confidence tags used below:** `[M]` = MEDIUM, verified against official vendor docs or manuals. `[L]` = LOW, from a single secondary source or my own inference. No claim here rates HIGH because the research seam classifies web-sourced findings at MEDIUM or lower.

---

## 0. Key Findings That Should Shape Requirements

1. **The "bias at the boat, decaying with lead time" GRIB correction already exists in the leading products, but it is manual there.** Expedition's routing settings have *Scale wind*, *Rotate wind* and *Time shift*, plus a checkbox to "Reduce scaling and rotation over <N> minutes". That checkbox reduces the correction linearly, from full strength now to zero after N minutes `[M]`. Expedition's separate "Use instrument wind" option starts routing from damped instrument wind. The manual says its "utility is still under review and it isn't often used" `[M]`. qtVlm can scale GRIB winds to match observed wind, with a factor that "gradually fade[s] into the pure grib wind over a fixed period" `[M, via Starpath/Burch]`. **Implication:** computing the bias automatically from damped instrument TWD/TWS, with a manual override, is a real differentiator. The decay model itself (linear fade over N hours) is proven, so copy it.
2. **Every serious product lets the user override instrument wind and current for laylines.** Examples are Expedition's *Hold* and *What if?* `[M]`, Navimetrix's "constant wind" `[M]` and Raymarine's fixed-angle mode `[M]`. Expedition states the reason directly: "especially helpful when the wind/current instruments are acting up". This validates the manual TWD/TWS degraded mode as a table-stakes feature.
3. **Experienced users know polars are optimistic, and products expose efficiency factors.** Navimetrix defaults to 80% below 10 kn and 90% above 20 kn, plus night and crossed-sea (75%) multipliers `[M]`. qtVlm has night, upwind/downwind and gust efficiency factors `[M]`. Expedition has a "Bsp + twa as targets" option that draws laylines from damped *actual* values instead of polar targets `[M]`. Raymarine's "Mirrored TWA" mode does the same thing `[M]`. **Implication:** a polar-efficiency % and a layline source toggle (polar targets vs. actual sailed TWA) are table stakes. They are not polish.
4. **Layline uncertainty display is standard on premium systems.** Expedition has *Layline bounds*, which draws extreme laylines over the preceding N minutes `[M]`. Raymarine shades triangles showing TWD variation `[M]`. OpenCPN Tactics widens the laylines with COG yaw, damped exponentially `[M]`. B&G draws a dotted "Limits" line `[L]`. A cheap implementation is a wedge built from the min and max of damped TWD over a 5–15 minute window. It is a differentiator worth building because it makes the display trustworthy.
5. **Auto-advance to the next mark has two established triggers.** Freeboard-SK / Signal K Course API uses `arrivalCircleEntered` or `perpendicularPassed`, with a 0–30 s delay before advancing `[M]`. Expedition has no auto-advance; the navigator presses next or previous mark `[M]`. **Implication:** build auto-advance with a delay and a one-tap undo. Always keep the manual next and previous controls.
6. **Rounding side matters for island marks.** Expedition uses leave-to-port or leave-to-starboard only to offset laylines by half a boat width `[M]`. For Jabuka (an island), Blitvenica (a lighthouse islet) and Plić Sestre (a shoal), that offset is far too small. The mark needs a rounding radius on the correct side, and routing needs land avoidance. Otherwise the route and laylines point through rock at night `[L, my inference; strongly recommended]`.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Without these the tool feels broken, untrustworthy or unusable at the helm at night. IDs (TS-x) are for traceability into REQUIREMENTS.

#### A. Data ingest and trust

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-1 | Live instrument ingest (AWA/AWS, TWA/TWS/TWD, STW, HDG, depth, set/drift if present) + GPS (pos, COG, SOG) | Every product's input contract. Expedition lists exactly these as the key inputs `[M]` | MEDIUM | Fastnet goes through fastnet2ip to NMEA over UDP. Prefer Hercules-computed TW. Only recompute TW from AW+STW+HDG when TW is missing (SailGrib and Expedition both do this) `[M]` |
| TS-2 | Per-value freshness and source indicator (LIVE / MANUAL / GRIB / STALE), with stale values greyed or dashed | Without this, the helmsman cannot tell a frozen number from a live one, and core value requires the data to be trustworthy. Freeboard-SK keeps showing the last values when data stops, a known trap `[M]` | LOW | Timestamp each value and treat it as stale after N s. Show a single overall "data health" badge on the helm view |
| TS-3 | Damping / smoothing of wind, heading and current | All layline systems damp. Expedition uses "damped true wind and damped current" `[M]`, and Tactics uses exponential smoothing factors `[M]` | LOW | Use exponential or rolling means with separate time constants for TWD (~30–60 s), TWS, and current (minutes). Current must be heavily damped |
| TS-4 | Replay / simulator input | Bus untested until race day. Expedition and qtVlm both replay logged or recorded NMEA `[M]` | MEDIUM | Replays the same NMEA/UDP stream format the live path uses. This also becomes the post-race analysis tool |

#### B. Performance core (polar)

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-5 | Polar load (Expedition/OpenCPN/CSV TWA×TWS grid) with interpolation | Prerequisite for everything. Tactics uses a 181×61 lookup table with no extrapolation, showing "no polar data" out of range `[M]` | LOW | Clamp sensibly outside the polar range, and show that the value is extrapolated |
| TS-6 | Target TWA and target BSP (upwind/downwind optimum VMG angle) for the current TWS | Core helm number in Tactics, SailGrib, Expedition and B&G `[M]` | LOW | Optimum VMG = tangent to the polar curve `[M]` |
| TS-7 | Polar % (STW / polar speed at current TWA/TWS) | SailGrib and Tactics both output "efficiency vs polar" `[M]` | LOW | Use a long damping window. Instant values are noise |
| TS-8 | Global polar efficiency factor (%) + target-angle offset | Theoretical polars are optimistic (stated in PROJECT.md). Navimetrix/qtVlm efficiency settings `[M]` | LOW | One % factor applied to routing and laylines. Add an optional ±degrees offset on target TWA. Editable in-race |
| TS-9 | Tack/gybe time penalty in routing | Navimetrix defaults to 30 s each, and Expedition has "Penalties" `[M]` | LOW | 30–60 s for a short-handed night race. Without it the router zig-zags |

#### C. Laylines

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-10 | Port and starboard laylines to the active mark, upwind and downwind, red/green per convention | Universal across B&G, Raymarine, Garmin, SailGrib, Tactics and Expedition `[M]` | MEDIUM | Layline COG for each tack = vector sum of (target BSP at heading TWD ± targetTWA ± leeway) + current. Draw it through the mark at the reciprocal bearing. Truncate at the tack/gybe point when the boat is not yet on the layline (SailGrib behaviour) `[M]` |
| TS-11 | Layline source toggle: polar targets vs. damped actual TWA/BSP (mirrored) | Expedition's "Bsp + twa as targets" and Raymarine's "Mirrored TWA" `[M]`. Covers the optimistic-polar risk | LOW | Default to *actual* when polar % is consistently below ~90%. Let the user flip it |
| TS-12 | Distance and time to layline ("tack in 12 min / 1.8 nm") + overstood indicator | SailGrib shows distance and time to layline, and Expedition has time to layline with optional negative countdown "past the layline" `[M]` | LOW | Show a negative value when overstood ("+0.3 nm OVER"). That is Expedition's "countdown past laylines" option `[M]` |
| TS-13 | Current in laylines from measured set/drift (Hercules) or SOG/COG vs STW/HDG, with an Ignore option | SailGrib modes: ignore / instrument-derived (default) / atlas / GRIB `[M]`. Tactics computes the current triangle `[M]` | MEDIUM | Instrument-derived current needs a calibrated compass and log. SailGrib warns about this explicitly `[M]`. The default should be **Ignore** until on-boat checks prove the compass and log are calibrated. Adriatic currents are usually weak |
| TS-14 | Manual wind / current override for laylines ("Hold" / "What if?") | Expedition Hold/What-if, Navimetrix constant wind `[M]` | LOW | Same UI as the degraded-mode manual TWD/TWS entry (TS-20). Override is per value: wind only, current only, or both |

#### D. Routing

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-15 | Isochrone routing from current position and time to the active mark (and onward marks) | Core value. Expedition's "Optimize from current position/time" is "the normal mode during a race" `[M]` | HIGH | Auto re-run every N minutes. Route only the remaining course. Expedition's "optimise first leg only" is useful as a speed fallback on the Pi 3B `[M]` |
| TS-16 | Land avoidance in routing | Expedition, SailGrib and Navimetrix all avoid land and zones `[M]`. Šibenik archipelago + island marks make it critical here `[L inference]` | MEDIUM–HIGH | Use pre-clipped coastline polygons for the race box with a safety buffer (e.g. 0.2–0.3 nm). Without this, the route literally crosses islands at night |
| TS-17 | GRIB wind correction from measured wind with decay over lead time | Expedition scale/rotate + "reduce over N minutes" (manual), qtVlm fade (manual) `[M]`. Doing it automatically is our differentiator (D-1) | MEDIUM | v1 minimum: rotation ΔTWD and scale TWS ratio. Use damped instrument wind (10–20 min mean across tacks) vs GRIB at the boat position and time. Apply uniformly across the field, then fade linearly to 0 over T hours (default 3–6 h). Clamp the values and expose them in the UI |
| TS-18 | Masthead → 10 m wind height scaling | Expedition: TWS_mast = TWS_10m·(h/10)^a, a≈0.11–0.14, e.g. 20 m → ~109% `[M]`. If ignored, the bias computation reads GRIB as ~7–9% too light | LOW | X35 masthead ≈ 16–17 m gives a factor of ~1.06–1.07. Apply it before computing the bias |
| TS-19 | Display of route on map + recommended course/TWA from route's first leg + route ETA | Every router draws the optimal route `[M]` | MEDIUM | The helm needs "what to steer now", not a full path. See helm view |

#### E. Degraded modes

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-20 | Manual TWD/TWS entry (read off B&G displays), with timestamp, used for laylines and GRIB correction | PROJECT.md requirement. Precedent in Expedition Hold / What-if `[M]` | LOW | Big steppers (±5°, ±1 kn), not a keyboard. Show "MANUAL, 12 min old". Expire or warn after ~30 min |
| TS-21 | GPS-only mode (no Fastnet): routing from GRIB (+ manual correction), laylines from GRIB/manual TWD, SOG/COG as speed proxies | PROJECT.md requirement | LOW–MEDIUM | Polar % and current cannot be computed without STW/HDG. Hide them and don't show zeros |
| TS-22 | Survives restart: course, marks, active-mark index, settings, manual-wind state persisted on Pi | 36 h unattended with power cycles | LOW | Write state to disk atomically on change. The tablet reconnects and resumes |

#### F. Course and marks

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-23 | Mark library pre-loaded with known race marks (Vodice start/finish, Plić Sestre, Jabuka, Blitvenica, Mulo) + tap-on-map to add ad-hoc marks | Tapping on a moving tablet at night is error-prone. Known marks should not need tapping `[L, opinion]` | LOW | Tap-to-create stays as the PROJECT.md fallback. Allow long-press drag to adjust a mark |
| TS-24 | Course = ordered list of marks with rounding side (port/stbd/pass-through); reorder, insert, delete | Expedition routes carry Leave to port / Leave to starboard / Sail to mark `[M]`. The committee can change the course | LOW–MEDIUM | Use an up/down button list, not drag-and-drop, because drag misfires with wet hands |
| TS-25 | Pre-defined course templates (Course A, Course B) switchable in one tap | SIs define A and B. A change is announced at short notice | LOW | Cheap and high value |
| TS-26 | Active-mark selection: manual next/previous always available | Expedition: next/prev buttons only `[M]`. Freeboard: skip next/prev `[M]` | LOW | Big buttons, with a confirm step to avoid fat-finger errors |
| TS-27 | Auto-advance on rounding (arrival circle or perpendicular passed), with delay and undo | Freeboard-SK / Signal K Course API `[M]` | LOW–MEDIUM | For an island mark, a perpendicular-passed check through the rounding point is better than a small circle. Add a 10–30 s delay with a visible "Advancing to Blitvenica… UNDO" banner |

#### G. Helm view (night)

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-28 | Big-number helm panel over map: primary steering target + delta, BSP vs target, DTW/TTW next mark, layline/tack advice | Core value. SailSteer-style single view with heading, COG, laylines and tide `[M]`. Expedition can push "TARG HDG NL/FL" (target heading near/far layline) and layline time/distance to B&G displays `[M]` | MEDIUM | See "Helm Display Specification" below |
| TS-29 | Night mode: true-black background, dim red/amber monochrome, no white anywhere including map tiles | Night-vision convention. Orca, Expedition (Day/Dusk/Night) and chart-plotter palettes `[M]`. Sources disagree on red vs dim white, but all agree on **dim** `[L]` | LOW–MEDIUM | Raster OSM tiles are bright, so apply a CSS invert/hue/brightness filter or use pre-rendered dark tiles. Provide a one-tap Day/Night toggle and a software dim slider, because the Android minimum brightness is often too bright |
| TS-30 | Screen never sleeps, full-screen, no browser chrome | The tablet turning off mid-race is fatal | LOW | **Caveat:** `navigator.wakeLock` needs a secure context (HTTPS) and does not work over plain `http://pi.local`. Use the Android "stay awake" / screen-timeout setting, a NoSleep-style fallback, or local HTTPS `[L, must verify on device]` |
| TS-31 | Large touch targets, minimal interaction at the helm, optional "locked" mode against accidental taps | Wet hands, motion, gloves | LOW | Put all settings behind a long-press or a separate settings route |

#### H. Logging

| ID | Feature | Why Expected | Complexity | Notes |
|----|---------|--------------|------------|-------|
| TS-32 | Continuous log: raw NMEA stream with timestamps + 1 Hz processed CSV (time, pos, COG/SOG, HDG, STW, AWA/AWS, TWA/TWS/TWD, depth, set/drift, target TWA/BSP, polar %, active mark, wind source, GRIB bias) | Expedition logs 1 Hz CSV (0.5 Hz suggested offshore), in daily UTC files `[M]`. Needed for post-race polar work (PROJECT.md) and for building the replay | LOW | Rotate files hourly. fsync periodically, because Pi SD corruption on power loss is real. The raw stream doubles as replay input |
| TS-33 | Event marker button (sail change, reef, tack, "note") | Expedition and Stripchart events for sail changes `[M]` | LOW | One button with a small preset list. Makes post-race polar filtering possible |

### Differentiators (Competitive Advantage)

These are aligned with the Core Value ("trustworthy, continuously updated steer-this / tack-here, even if parts fail"). Commercial products either lack them or leave them manual.

| ID | Feature | Value Proposition | Complexity | Notes |
|----|---------|-------------------|------------|-------|
| D-1 | **Automatic** GRIB bias from live wind with decay over lead time, re-estimated each routing cycle | Expedition and qtVlm require the navigator to type in scale and rotate values `[M]`. Automating this for the owner-navigator, who is also crew, is the headline feature | MEDIUM | Estimate over a 10–20 min window that spans both tacks, which cancels upwash/heel TWD tack-bias. Clamp to rotation ±40°, scale 0.5–2.0. Freeze the estimate during tacks and when data is stale. Show "GRIB bias: +15° / ×1.2, fading over 4 h" |
| D-2 | GRIB-disagreement alarm + time-shift suggestion | A large bias usually means front or bora timing is off, not a constant offset. Expedition offers a manual "Time shift" `[M]` | MEDIUM | v1: warn when \|ΔTWD\| > 30° or the TWS ratio is outside 0.6–1.6. Optional v1.x: search ±3 h for the GRIB time that best matches the observed wind |
| D-3 | Tack-choice cost from the router: "Port 5h12 / Stbd 5h14, marginal" | Expedition shows per-side lay times and "time sensitivity" shading `[M]`. It turns a route into a decision the helm can act on and exposes when the choice doesn't matter | MEDIUM | Run two constrained routings (first leg forced on each tack), or read the isochrone result. A "marginal" label below a threshold (e.g. 3 min) |
| D-4 | Route-advice hysteresis: recommendation changes only if the gain is above a threshold and persists across 2 runs | Re-routing every few minutes flips "tack now / don't" on noise. Erratic advice destroys trust `[L inference]` | LOW | Show a "route age" and a "changed" flag. Never flash |
| D-5 | Layline uncertainty wedge (min/max over last N min of TWD) | Expedition layline bounds, Raymarine shift triangles, Tactics yaw width `[M]`. Shows how much the layline can be trusted | LOW | Use a rolling min/max of damped TWD over 5–15 min and draw a translucent wedge around each layline |
| D-6 | Mode-aware primary steering number: upwind/downwind → target TWA (steer to wind), reaching → course-to-steer heading | Helmsmen steer to angle when beating or running and to heading when reaching `[L, practice]`. Generic apps show one fixed set | LOW | Switch on \|TWA\| bands with hysteresis (e.g. upwind < 70°, downwind > 130°) |
| D-7 | Other-tack heading + "next leg" preview (TWA/side of next leg after rounding) | Expedition "Opposite tack" predictor and "next leg" channels `[M]`. B&G SailSteer shows opposite-tack data `[L]`. Night without visual references → the helm needs the heading to settle onto after tacking | LOW | Other-tack heading = TWD ∓ target TWA (± leeway, current-corrected for COG) |
| D-8 | Lift/header trend indicator (TWD vs N-min mean) | Raymarine wind-shift bar, B&G shift history `[M]`. Cheap tactical gain for the helm | LOW | A small bar or arrow next to the TWA number |
| D-9 | Distance-aware display emphasis: far from mark → routing guidance; within layline zone (< ~5–8 nm or both laylines in range) → laylines prominent | Laylines to a mark 60 nm away are meaningless because the wind changes. B&G only draws them within 150 nm `[M]` | LOW | Avoids showing two conflicting "truths" at once |
| D-10 | Night-specific polar factor / wave reduction from TWS when no wave file | qtVlm and Navimetrix have night efficiency `[M]`. The whole race is at night, so the global factor (TS-8) covers most of this | LOW | Wave fallback: Hs estimated from TWS via a small lookup, fed into the wave table (see Wave Handling) |
| D-11 | One-screen health / diagnostics page (bus up? GPS fix? GRIB coverage until? last routing time and duration? CPU temp) | Unattended 36 h on a Pi. A quick on-boat validation procedure is needed on 12–13 Nov | LOW | Also used for the dock check before the start |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Full navigator / chart-table UI with every routing parameter exposed | Expedition and Adrena do it | Weeks of work. Every exposed knob is a way to break the router at 3 a.m. Out of scope in PROJECT.md | ~8 editable parameters (efficiency %, tack penalty, decay hours, current mode, layline source, wave on/off, routing interval, manual wind) in a simple settings page |
| Ensemble / multi-model blending and routing | Expedition's flagship feature `[M]` | Pi 3B CPU. The navigator would have to interpret it. No in-race downloads, so the loaded models are fixed | Pre-race: pick the best model on the laptop by comparing models against the evening's observations. In race: one active GRIB with a one-tap switch |
| Automatic instrument calibration / polar learning during the race | Appealing | Wrong-in-the-loop risk, and no time to validate. Out of scope in PROJECT.md | Log everything (TS-32/33) and do it after the race |
| Start-line tools (line bias, time to burn) | Every race package has them | Night start with a 4 h window. Not needed for Jabuka. Out of scope in PROJECT.md | None |
| AIS / collision avoidance, depth alarms | "Safety" | Duplicates B&G and the dedicated plotter. False confidence. Out of scope in PROJECT.md | Show a clear "not for navigation safety" banner. Rely on B&G depth alarm and plotter |
| Writing targets back to B&G displays | Expedition sends TARG HDG etc. to H2000 `[M]` | Fastnet write path is untested and risky to the boat's main system | Read-only bus. The tablet is the only output |
| Animated / continuously moving route redraws, live isochrone animation | Looks impressive | Distracting at night. Costs the Pi CPU and tablet battery | Redraw on each routing completion only. Isochrones off by default on the helm view |
| Silent auto-advance on rounding | "Hands-free" | A wrong advance (e.g. passing near a mark early) silently invalidates laylines and route | Auto-advance with banner + delay + undo (TS-27) |
| Rigid "follow the route" cross-track steering | Seems natural | The route is a strategy recomputed every few minutes. XTE to a stale route fights the newest advice | Steer to the target TWA/heading from the latest route's first leg (TS-19, D-6) |
| Recomputing true wind from apparent when Hercules already provides it | "Better" TW | Duplicates Hercules calibration and adds error without heel or leeway data | Use the Hercules TW. Compute only as fallback (TS-1) |
| Vector charts (S-57), tiled vector rendering on tablet | Prettier | Pi 3B is too weak, and there is no time. Out of scope in PROJECT.md | Pre-rendered raster tiles for the race box, plus coastline polygons for routing |
| Native app / PWA install as v1 | Nicer UX | PWA install and Wake Lock need HTTPS. Certificates on an offline Pi cost time | Plain browser in full-screen + Android stay-awake setting (TS-30) |

---

## Helm Display Specification (synthesis)

Order is priority; the top rows are largest. `[L, synthesized from SailSteer/Expedition channels + practice]`

| Zone | Content | Format |
|------|---------|--------|
| 1 (largest, ~20–25% of screen height digits) | **Primary steering target** (D-6): upwind/downwind → `TWA 42 → 40` (actual → target, delta arrow). Reaching → `HDG 215 → 208` (course to steer) | Readable at 1.5–2 m. Delta coloured only by brightness (no green or red at night) |
| 2 | **BSP 6.8 / 7.2 (94%)**: actual / target / polar % | Large |
| 3 | **Next mark**: name, DTW nm, TTW from route (not VMC), bearing | Medium |
| 4 | **Tack/gybe advice**: `TACK IN 14 min / 2.1 nm` · `ON LAYLINE` · `OVERSTOOD +0.3 nm` · route advice `STAY STBD (marginal: 2 min)` | Medium, short words |
| 5 | **Other-tack heading** (after tack, steer ~ 128°) + **next leg** preview | Small |
| 6 | **Wind**: TWD/TWS + lift/header bar, source badge (LIVE/MANUAL/GRIB) | Small |
| 7 (status strip) | Data health, route age, GRIB bias, active course/mark index | Tiny, but shows a warning state when something is wrong |
| Map behind | Boat, heading/COG vector, route, laylines (red=port, green=stbd, dimmed at night) + uncertainty wedge, marks with rounding side | Dark-filtered tiles. North-up default, with a course-up option |

Night conventions: black background, a single dim red (or amber) foreground palette, no pure white, no animations, no pop-ups at the helm except the auto-advance banner and critical data-loss warnings. Day mode is the same layout with higher contrast. `[M for "dim + red palette" convention; L for exact sizes]`

---

## Laylines: How They Are Computed (reference for requirements)

Consensus model from Expedition, Tactics, SailGrib, Raymarine and B&G `[M]`:

1. **Wind:** damped TWD/TWS from instruments (or a manual / what-if override). Expedition optionally adds "twist" to TWD for laylines `[M]`.
2. **Angle and speed:** target TWA and BSP from the polar for the current TWS (TS-6), **or** the damped actual TWA/BSP (TS-11). Apply the efficiency factor and optional angle offset.
3. **Leeway:** Expedition, B&G and Ockam use `leeway = k·heel/bsp²`, k≈10–12 `[M]`. The X35 likely has no heel sensor, so use a fixed user leeway (e.g. 3–5° upwind, 0 downwind) or fold it into the angle offset. Modern B&G may already include leeway in TWA `[M]`. Do not double-count it.
4. **Current:** the COG on each tack = water-track vector + current vector (measured set/drift, GRIB/file, or none). Expedition curves the laylines when it uses a tidal model rather than set/drift at the boat `[M]`. Straight laylines with the measured or ignored current are enough for v1.
5. **Geometry:** lines through the mark (offset by rounding radius on the correct side) at the reciprocal of each tack's COG. Intersect with the boat's current-tack line to get the tack point and the time/distance to the layline. Truncate there (SailGrib) `[M]`.
6. **Uncertainty:** a wedge from the TWD min/max over N minutes (D-5).
7. **Downwind:** the same model with downwind target angles and gybe points.

---

## Wave and Current Handling (reference)

**Waves (approaches seen):**
- Expedition: correction tables of % speed loss by significant wave height (m) × angle to the boat. Uses swell direction, or wind-wave direction as fallback. Also "avoid waves over X" `[M]`.
- qtVlm: wave polar (TWS × Hs × wave angle) + cross-sea correction + wave-height avoidance `[M]`.
- SailGrib/Navimetrix: crossed-sea detection (both systems > 2 m, 45–135° apart) → polar × 75%. Max-wave limit with an optional "heave-to" `[M]`.
- Simple guides: % loss per metre of Hs (e.g. 5%/m) `[L]`.

**Recommendation:** a 2-D factor table (Hs bins 0/1/2/3/4+ m × upwind/reaching/downwind) applied multiplicatively to the polar. Take Hs from a wave GRIB if one is loaded, otherwise estimate it from TWS with a small fetch-limited lookup (Adriatic bora/jugo). Skip cross-sea logic in v1. Complexity LOW.

**Current:**
- Routing uses a file (Copernicus Adriatic, converted to GRIB or a grid). Expedition's "Extend current forecast in time" assumes a static field when the file has one timestep `[M]`. Copy that.
- Laylines use measured set/drift (Hercules or SOG/COG − STW/HDG), heavily damped. Expedition does exactly this split: instrument current drives laylines, GRIB current drives routing `[M]`.
- Default to Ignore for laylines until compass and log calibration is confirmed on the boat (SailGrib warning) `[M]`.

---

## Feature Dependencies

```
TS-1 Ingest ──┬──> TS-2 Freshness ──> TS-28 Helm view (trust badges)
              ├──> TS-3 Damping ──┬──> TS-10 Laylines ──> TS-12 Time/dist to layline
              │                   ├──> D-5 Uncertainty wedge
              │                   ├──> D-8 Lift/header
              │                   └──> TS-17 GRIB bias ──> D-1 Auto bias ──> D-2 Disagreement alarm
              └──> TS-32 Logging ──> TS-4 Replay (logged raw stream = replay input)

TS-4 Replay/sim ──required-by──> all development and testing (build first)

TS-5 Polar ──> TS-6 Targets ──┬──> TS-7 Polar %
                              ├──> TS-10 Laylines
                              ├──> D-6 Mode-aware steering target
                              ├──> D-7 Other-tack heading
                              └──> TS-15 Routing
TS-8 Efficiency ──modifies──> TS-6, TS-10, TS-15
TS-11 Layline source toggle ──modifies──> TS-10

GRIB import ──> TS-18 Height scaling ──> TS-17 Bias ──> TS-15 Routing
TS-16 Land avoidance ──required-by──> TS-15 Routing (in archipelago)
TS-9 Tack penalty ──> TS-15 Routing
Wave table / current file ──enhance──> TS-15 Routing
TS-13 Measured current ──enhances──> TS-10 Laylines

TS-23 Mark library ──> TS-24 Course ──> TS-26 Active mark ──┬──> TS-10 Laylines (to active mark)
                         └─> TS-25 Templates                 ├──> TS-15 Routing (remaining marks)
                                                             └──> TS-27 Auto-advance
TS-15 Routing ──> TS-19 Route display/advice ──> D-3 Tack cost ──> D-4 Hysteresis
TS-14/TS-20 Manual wind ──substitutes-for──> TS-1 wind (degraded) ; feeds TS-17
TS-21 GPS-only ──requires──> TS-20 + TS-15 working without STW/HDG
TS-29 Night mode, TS-30 Wake, TS-31 Touch ──> TS-28 Helm view
TS-22 Persistence ──required-by──> TS-24/26 (survive restart)

D-9 Distance-aware emphasis ──requires──> TS-10 + TS-19
TS-17 automatic bias ──conflicts──> TS-14 manual wind override
   (when manual is active, freeze auto bias or derive the bias from manual values; never mix the two silently)
TS-27 auto-advance ──conflicts──> manual active-mark edits in the same 30 s window (undo/lock needed)
```

### Dependency Notes

- **Replay/simulator (TS-4) comes first.** Nothing else can be tested before 12 Nov. Logging (TS-32) and replay should share one stream format so the race log can be replayed later.
- **Polar (TS-5/6) is the root of both laylines and routing.** Build and verify it early with known X35 numbers.
- **Laylines (TS-10) do not depend on routing (TS-15).** They are independent, cheap and deliver the core value even if routing is late or too slow on the Pi. **Laylines + helm view should ship before routing.** This ordering is a deliberate risk hedge.
- **Land avoidance (TS-16) is a hard prerequisite for showing a route at all** in this race area. A route through an island at night is worse than no route.
- **Manual wind (TS-20) and automatic bias (D-1) must share one wind-source state machine**: LIVE → MANUAL → GRIB-only, with a visible badge. Conflicting sources must never mix silently.
- **Course/marks (TS-23–27) gate laylines and routing.** Without an active mark there is nothing to show. Pre-loading the mark library removes the riskiest tap UX from the critical path.

---

## MVP Definition

### Launch With (v1, race-ready 12 Nov)

- [ ] TS-1, TS-2, TS-3: ingest + freshness + damping. Without these the numbers can't be trusted
- [ ] TS-4: replay/simulator. The only way to test before boat access
- [ ] TS-5–TS-8: polar, targets, polar %, efficiency factor
- [ ] TS-10, TS-11, TS-12, TS-14: laylines (polar/actual toggle), time/distance to layline, manual override
- [ ] TS-20, TS-21, TS-22: manual wind, GPS-only mode, persistence
- [ ] TS-23–TS-27: mark library, course with rounding side, A/B templates, manual + auto-advance with undo
- [ ] TS-28–TS-31: helm view, night mode, stay-awake, big touch targets
- [ ] TS-32, TS-33: logging (raw + 1 Hz CSV) + event button
- [ ] TS-15, TS-16, TS-17, TS-18, TS-19, TS-9: routing with land avoidance, decaying GRIB bias, height scaling, tack penalty, route advice. Core value, but scheduled **after** laylines/helm as the highest-risk item
- [ ] D-1 (auto bias), D-6 (mode-aware target), D-7 (other-tack heading), D-11 (health page). Low cost, high value for this race

### Add After Validation (v1.x, only if v1 is done before 11 Nov)

- [ ] D-5 layline uncertainty wedge: once laylines prove stable on replay
- [ ] D-3 tack-choice cost + D-4 hysteresis: once routing runs within budget on the Pi
- [ ] D-8 lift/header bar, D-9 distance-aware emphasis
- [ ] TS-13 measured current in laylines: enable only after the on-boat compass/log sanity check
- [ ] Wave reduction table (+ TWS-based Hs fallback), current file in routing
- [ ] D-2 GRIB disagreement alarm (warning only)

### Future Consideration (v2+, after the race)

- [ ] Polar learning from logs, post-race analysis tooling (Stripchart-like)
- [ ] D-2 automatic GRIB time-shift search, multi-model comparison against the log
- [ ] Navigator/chart-table view, PWA/APK packaging with HTTPS
- [ ] Curved laylines from current models, rate-of-turn-aware layline times (Expedition) `[M]`

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Replay/simulator (TS-4) | HIGH | MEDIUM | P1 |
| Ingest + freshness + damping (TS-1–3) | HIGH | MEDIUM | P1 |
| Polar + targets + efficiency (TS-5–8) | HIGH | LOW | P1 |
| Laylines + time to layline + source toggle (TS-10–12) | HIGH | MEDIUM | P1 |
| Helm view + night mode + stay-awake (TS-28–31) | HIGH | MEDIUM | P1 |
| Course/marks, templates, auto-advance (TS-23–27) | HIGH | LOW–MEDIUM | P1 |
| Manual wind + GPS-only + persistence (TS-20–22, TS-14) | HIGH | LOW | P1 |
| Logging + events (TS-32–33) | MEDIUM (post-race HIGH) | LOW | P1 |
| Isochrone routing + land avoidance (TS-15, 16, 19, 9) | HIGH | HIGH | P1 (highest risk) |
| GRIB bias with decay, auto (TS-17/18, D-1) | HIGH | MEDIUM | P1 |
| Mode-aware target, other-tack heading (D-6, D-7) | HIGH | LOW | P1 |
| Health page (D-11) | MEDIUM | LOW | P1 |
| Uncertainty wedge (D-5) | MEDIUM | LOW | P2 |
| Tack cost + hysteresis (D-3, D-4) | MEDIUM | MEDIUM | P2 |
| Measured current in laylines (TS-13) | MEDIUM | MEDIUM | P2 |
| Wave table + current file in routing | MEDIUM (bora/jugo) | LOW–MEDIUM | P2 |
| Lift/header, distance-aware emphasis (D-8, D-9) | MEDIUM | LOW | P2 |
| GRIB disagreement alarm (D-2) | MEDIUM | LOW (warning) / MEDIUM (time-shift) | P2/P3 |
| Polar learning, ensemble, start tools, AIS | LOW for Jabuka | HIGH | P3 / anti |

---

## Competitor Feature Analysis

| Feature | Expedition | SailGrib WR | qtVlm | OpenCPN Tactics / DashT | B&G SailSteer (Zeus/H5000) | Freeboard-SK / Signal K | Navimetrix | **Jabuka approach** |
|---------|-----------|-------------|-------|------------------------|---------------------------|------------------------|-----------|-------------------|
| Live routing from boat position | Yes, "optimize from current position/time" `[M]` | Routing yes. Auto re-run not documented `[L]` | Routing yes. Live re-run not confirmed `[L]` | No (Weather Routing pi is on demand, per PROJECT.md) | No | No | Yes (pre-planned) | Auto re-run every N min |
| GRIB correction from observed wind | Manual scale/rotate/time-shift, linear fade over N min `[M]`. "Use instrument wind" rarely used `[M]` | Fixed wind % per file `[M]` | Scale to observed, fade to GRIB `[M]` | No GRIB in laylines `[M]` | No | No | Wind % per file. Constant wind `[M]` | **Automatic** bias from damped instruments, linear fade, manual override |
| Laylines | Polar + leeway + damped wind/current, bounds, from boat, tidal-curved, opposite tack `[M]` | Instrument TW + 4 current modes, truncated at tack point, dist/time `[M]` | Not confirmed `[L]` | Polar target TWA, current, heel-based leeway, yaw-width `[M]` | Red/green, tide-corrected, limits, within 150 nm `[M]` | Display only, needs performance data `[M]` | Yes `[L]` | Polar/actual toggle, current optional, uncertainty wedge, tack point |
| Rounding side | Leave port/stbd (½ boat width) `[M]` | n/a | n/a | n/a | n/a | n/a | Cardinal mark passing (C-MAP) `[M]` | Rounding radius on side + land avoidance |
| Mark advance | Manual next/prev `[M]` | Manual | Manual | Single temp waypoint `[M]` | Route on MFD | Auto: arrival circle / perpendicular passed + delay `[M]` | — | Auto + banner + undo + manual |
| Polar efficiency | Polar scaling, multiple polars `[M]` | Polar edit, efficiency output `[M]` | Night, up/downwind, gust factors `[M]` | No | Polar upload | Polar plugin | <10 kn 80%, >20 kn 90%, night, cross-sea 75% `[M]` | Global % + angle offset (+ wave table) |
| Waves | % tables by Hs × angle, avoid > X `[M]` | Crossed-sea coefficient `[M]` | Wave polar + cross-sea + avoid `[M]` | No | No | No | Max height, heave-to, cross-sea `[M]` | Hs × sailing-mode factor table, Hs from TWS fallback |
| Manual wind / degraded | Hold + What-if `[M]` | Simplified TW calc fallback `[M]` | Simulated wind `[M]` | Fixed leeway/heel options | Fixed angles (Raymarine analogue) `[M]` | Freezes last values `[M]` | Constant wind `[M]` | Manual TWD/TWS entry, GPS-only mode, source badges |
| Night display | Day/Dusk/Night colours `[M]` | Night mode `[L]` | — | — | Night palettes | Dark/night mode via `environment.mode` `[M]` | — | Black/red only, dark map tiles, dim slider |
| Logging | 1 Hz CSV daily UTC, events, Stripchart tests, polar overlay `[M]` | KML routings `[M]` | NMEA record/replay `[M]` | — | — | Server-side | — | Raw NMEA + 1 Hz CSV + events. Replay = log |

---

## Sources

- Expedition user manual (PDF via winsome.nl), sections *Optimal routing settings* (Use instrument wind; Scale/Rotate wind; "Reduce scaling and rotation over <selected> minutes"; Time shift; Penalties; wave correction), *Racing → Laylines / Layline bounds / Opposite tack / Laylines using predicted tides*, *Hold*, *Options → Bsp + twa as targets*, *Scale 10m wind* formula, *Boat logging*, *Routes → Leave to port/starboard*, *Leeway* `[M]`: https://www.winsome.nl/wp-content/uploads/Expedition.pdf
- Expedition feature list: https://expeditionmarine.com/ `[M]`
- SailGrib WR, Display Laylines: https://sailgrib.com/en/apps/sailgrib-wr/aide/nmea/display-laylines/ `[M]`
- SailGrib WR, Receive and display NMEA data: https://sailgrib.com/en/apps/sailgrib-wr/aide/general/receive-and-display-nmea-data/ `[M]`
- SailGrib WR, Do you use waves in routing: https://sailgrib.com/en/apps/sailgrib-wr/faq/routing/do-you-use-waves-in-routing/ `[M]`
- Navimetrix routing settings: https://www.navimetrix.com/en/faq/routing/how-do-i-calculate-a-routing-what-are-the-different-settings/ `[M]`
- David Burch on qtVlm routing (GRIB scaling + fade, efficiency factors, wave polar): https://davidburchnavigation.blogspot.com/2021/02/qtVlm-routing.html `[M]`
- Starpath qtVlm notes: https://www.starpath.com/qtVlm `[L]`
- OpenCPN Tactics manual: https://opencpn-manuals.github.io/main/tactics/index.html `[M]`. Dashboard Tactics: https://opencpn-manuals.github.io/main/dashboard_tactics/index.html
- Freeboard-SK help (Course API, arrival circle, auto-advance, dark/night mode): https://demo.signalk.org/@signalk/freeboard-sk/assets/help/index.html `[M]`. Changelog: https://app.unpkg.com/@signalk/freeboard-sk@2.14.3/files/CHANGELOG.md
- Signal K racer / polar performance plugins: https://unpkg.com/signalk-racer@1.1.2/README.md, https://www.npmjs.com/package/signalk-polar-performance-plugin `[L]`
- Raymarine LightHouse laylines: https://docs.raymarine.com/81406/en-US/latest/Laylines-1699BA9C.html `[M]`
- B&G Zeus manual (layline limits): https://www.manualsdir.com/manuals/599978/bg-zeus-12-zeus-8.html?page=20. Mark Chisnell RacePanel SailSteer article (403 on fetch, summary via search): https://prod.bandg.com/blog/racepanel-series-with-mark-chisnell-part-5-sailsteer/. boats.com SailSteer review: https://www.boats.com/reviews/bg-sailsteer-software-brings-racing-level-data-to-cruisers/ `[L]`
- Adrena feature table: https://aegeanel.com/wp-content/uploads/2025/04/ADRENA-Functions-Table.pdf `[L]`
- Night-vision display conventions: https://getorca.com/blog/dark-mode/. Forum discussions (ybw, trawlerforum) `[L]`
- Pip Hare routing software review (Yachting World): https://www.yachtingworld.com/reviews/gear-reviews/tested-pip-hare-tries-five-latest-weather-routeing-packages `[L]`

---
*Feature research for: live sailing race navigation (routing + laylines + helm display), Regata Jabuka 2026*
*Researched: 2026-11-05*
