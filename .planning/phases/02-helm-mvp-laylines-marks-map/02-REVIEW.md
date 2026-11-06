---
phase: 02-helm-mvp-laylines-marks-map
reviewed: 2026-11-06T10:10:22Z
depth: deep
files_reviewed: 33
files_reviewed_list:
  - src/jabuka/nav/__init__.py
  - src/jabuka/nav/geo.py
  - src/jabuka/nav/polar.py
  - src/jabuka/nav/wind.py
  - src/jabuka/nav/laylines.py
  - src/jabuka/nav/tacks.py
  - src/jabuka/nav/course.py
  - src/jabuka/nav/settings.py
  - src/jabuka/nav/data/marks.json
  - src/jabuka/nav/data/x35-orc-od-2019.exp
  - src/jabuka/core/nav_service.py
  - src/jabuka/core/nav_api.py
  - src/jabuka/core/course_api.py
  - src/jabuka/core/tiles.py
  - src/jabuka/core/web.py
  - src/jabuka/core/main.py
  - src/jabuka/web/static/index.html
  - src/jabuka/web/static/app.css
  - src/jabuka/web/static/app.js
  - src/jabuka/web/static/map.js
  - src/jabuka/web/static/overlays.js
  - src/jabuka/web/static/helm.js
  - src/jabuka/web/static/helm_logic.js
  - src/jabuka/web/static/carte.js
  - src/jabuka/web/static/reglages.js
  - src/jabuka/web/static/lock.js
  - src/jabuka/web/static/lock_logic.js
  - src/jabuka/web/static/wakelock.js
  - src/jabuka/web/static/style-day.json
  - src/jabuka/web/static/style-night.json
  - src/jabuka/prep/map.py
  - src/jabuka/prep/polar.py
  - src/jabuka/common/clock.py
findings:
  critical: 3
  warning: 7
  info: 8
  total: 18
by_severity:
  critical: 0
  high: 3
  medium: 7
  low: 8
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-11-06T10:10:22Z
**Depth:** deep (cross-module: state store -> wind -> polar -> course FSM -> laylines -> nav message -> helm/carte/lock UI, plus the laptop prep tools)
**Files Reviewed:** 33
**Status:** issues_found

Severity mapping: BLOCKER = critical/high, WARNING = medium, INFO = low.

## Summary

**Scope.** The review covers the Phase 2 source changes, `git diff 847075b..640c36c -- src`, restricted to plans 02-01 to 02-05:

- `nav/`
- `core/` (nav_service, nav_api, course_api, tiles, web, main)
- the helm web app under `web/static/`
- `prep/map.py` and `prep/polar.py`

The Phase 3 modules (`route/`, `prep/{grib,dwd,land,current,wxpack,cli}.py`) are out of scope. `common/clock.py` was read only to check how Phase 2 uses `wall()`.

**Method.** I tested the claims by running code where it was cheap to do so:

- `laylines.solve` on edge geometries
- pydantic validation with NaN/inf
- `prep.polar.parse_any` on qtVlm-style grids
- the FastAPI body/CSRF behaviour
- the polar VMG targets from 4 to 25 kn

The existing course FSM test `tests/nav/test_course.py:262-284` pins one of the defects below (CR-02).

**What is sound.** The conventions are applied correctly at every boundary I traced:

- TWA negative = port
- `h_stbd = TWD - TWA`
- leeway rotates the water track to leeward
- current is a TOWARDS vector added to the ground vectors
- wind is FROM
- magnetic to true is `mag + var(E)`, once, in `heading_true()` and at manual entry
- the browser converts true to magnetic with `display.variation`

The vector decomposition, overstood/fetching classification, track-based countdown, CTS current correction and LOFER/ABATTRE hint signs are right. Domain code (`nav/`, `core/`) makes no wall-clock calls; time comes from the injected clock. Server-side validation rejects NaN/inf on every REST model. Every string reaches the DOM through `textContent` or MapLibre `text-field`. The lock overlay swallows every pointer, touch, wheel and key path while locked.

**Key concerns** are in what reaches the helmsman:

1. Every nav alert, including a crash of the whole nav computation, is dropped by the UI. A software failure looks like "PAS DE VENT".
2. One Annuler inside a mark zone leaves the course stuck on the mark just rounded.
3. On a beat leg the helm can show an unsailable course to steer (into the wind).

Seven medium findings cover:

- hairpin rounding
- filter resets on source flapping
- unsynced wall-clock use
- a theme-switch race that can light the map at night
- an unconfirmed one-tap course reset
- degraded-basemap zoom
- the polar converter rejecting common qtVlm files

## Critical Issues

### CR-01: [BLOCKER / high] Nav alerts are never displayed: a nav crash shows as "PAS DE VENT", and the B&G cross-check, file-fallback and write-failure alerts are invisible

**Files:**
- `src/jabuka/web/static/helm_logic.js:126-129,168`
- `src/jabuka/web/static/helm.js:98-117`
- `src/jabuka/core/nav_service.py:112-122`
- `src/jabuka/nav/wind.py:321-324`
- `src/jabuka/nav/course.py:234,292`
- `src/jabuka/nav/settings.py:82`
- `src/jabuka/web/static/diag_logic.js:55-61`

**Issue.** `NavService` puts every operational alert into `msg["alerts"]`:

- "Erreur de calcul nav"
- "Écart TWA calculé/B&G > 10°" (the only signal that the AWA sign or heading calibration is wrong)
- "Parcours illisible : Parcours A par défaut"
- "Réglages illisibles"
- "Écriture du parcours impossible"
- "Vent manuel illisible"

`helmView()` copies them into `v.alerts`, but `render()` never draws them, and no other module reads `nav.alerts`. Plan 02-05 (frontmatter, line 27) required them to be rendered. `nav_errors` is also missing from `diag_logic.js` `CORE_ERRORS`, so the Diag page does not flag it either.

Worse, when `_compute` raises, `update()` returns the envelope with `wind: null`. `primaryView()` then shows the label "PAS DE VENT", and `sourceBadge(null)` shows the badge "PAS DE VENT".

**Failure scenario.** A bad racepack polar raises inside `polar.targets` every tick (see IN-04), or any other exception occurs in `_compute`. All night, the helm reads "PAS DE VENT" with every number blank. The crew believes the instruments are down and starts entering manual wind. The manual wind is accepted but changes nothing, because the computation keeps failing. Likewise, a 15° AWA-sign error trips the 60 s cross-check alert. Nobody sees it, and the laylines stay wrong for the whole race.

**Fix.** Render the alerts in a dedicated band or badge row on every tab. Give a computation failure its own label, distinct from "no wind":

```js
// helm.js render()
const box = $("helm-alerts");            // new element in the top band
box.replaceChildren(...v.alerts.map((a) => el("div", { class: "alert bad" }, a)));
// helm_logic.js primaryView(): distinguish a nav failure from no wind
if (nav?.alerts?.includes("Erreur de calcul nav")) return plain("ERREUR CALCUL", "—");
```

Also add `nav_errors: "nav computation failed"` to `CORE_ERRORS` in `diag_logic.js`. Add a UI test that feeds a nav message with alerts and asserts that they are visible.

### CR-02: [BLOCKER / high] After Annuler inside the mark zone, the real rounding never auto-advances; the helm keeps steering back to the mark just rounded

**File:** `src/jabuka/nav/course.py:609-616,625-628` (behaviour pinned by `tests/nav/test_course.py:277-282`)

**Issue.** `undo()` sets `suppress_idx = prev`. While the boat is inside that zone, `_fsm` returns early. On the first tick outside the zone, it clears the suppression, calls `_reset_fsm()` (so `_entered = False`) and falls through. Because `d > zone` and `_entered` is False, it returns. The zone exit, which is the actual rounding evidence, is discarded. The mark only re-arms if the boat re-enters the zone, which it never does after rounding.

**Failure scenario.** Course A, Jabuka (radius 0.6 nm, zone 0.85 nm), a hairpin with legs in 203° and out 009°. The abeam rule fires while the boat is still east of the island, before it has gone round (see WR-01). The banner says "Marque suivante : Blitvenica — Annuler". The helmsman knows the island is not yet rounded and taps Annuler, which is exactly what the banner invites. He rounds the island inside the zone and heads north. On zone exit the suppression lifts and nothing else happens. For the rest of the leg (about 32 nm, around 5 h at night) the active mark is Jabuka, behind the boat. The laylines, countdown, DTW and CTS all point back south until someone notices and taps "Suiv." on the Carte tab.

**Fix.** When the suppression lifts because the boat left the same mark's zone, keep that exit as rounding evidence instead of discarding it:

```python
if c.suppress_idx is not None:
    if c.suppress_idx == idx and d <= zone:
        return
    was_this_mark = c.suppress_idx == idx
    self._save_quiet(c.model_copy(update={"suppress_idx": None}))
    self._reset_fsm()
    self._fsm_key = key
    if d <= zone:
        return
    if was_this_mark:          # left the zone we were suppressed in: that IS the rounding
        self._entered = True   # the normal 10 s "left the zone" debounce then advances
```

Then update `test_undo_restores_and_suppresses_until_exit`, which currently asserts the stuck behaviour at line 281.

### CR-03: [BLOCKER / high] On a beat leg, the helm's primary number can be a course to steer straight into the wind, or a downwind TWA target

**File:** `src/jabuka/nav/laylines.py:276-292` (and `select_primary`, lines 88-106)

**Issue.** The primary number is chosen from the boat's own |TWA| (D-6), independently of the leg type. When `primary == "cts"` on a beat or run leg, `course_to_steer(btw, ...)` returns the bearing to the mark. On a beat leg, that bearing is by definition inside the no-go zone (beta < up TWA).

I verified it with `laylines.solve`: wind from 000°, mark due north, boat reaching at TWA 90. The result is `leg='beat'`, `helm={'primary': 'cts', 'target': 0.0, 'cts_t': 0.0, 'deviation': -90.0}`. The helm shows "CAP À SUIVRE 356°M" and "◄ BÂBORD", which is head-to-wind. Similarly, right after rounding a leeward mark onto a beat, `prev_primary == "twa_down"` holds "TWA CIBLE ↓ 150°" until |TWA| drops below 105.

**Failure scenario.** This happens at every rounding onto a beat leg. With a northerly (bora/tramontana), that includes Jabuka to Blitvenica (009°) in both courses. For the 20-60 s the boat spends turning, the helm first shows a downwind TWA target, then a heading into the eye of the wind. It also happens whenever the helmsman reaches off on a beat leg (to dodge traffic or a fishing farm). A tired helmsman following the big number at night luffs into irons.

**Fix.** On beat and run legs, the CTS fallback must be a sailable heading, namely the current tack's heading (or the fetch CTS when fetching). The TWA target must follow the leg:

```python
if leg in ("beat", "run"):
    want = "twa_up" if leg == "beat" else "twa_down"
    primary = want if primary != "cts" else "cts_tack"
if primary == "cts_tack":
    h_cur = h_stbd if on_stbd else h_port
    res.helm = _cts_helm(boat, h_cur)      # sailable: the current tack's layline heading
```

Add tests for a beat leg at TWA 90 and at TWA 150.

## Warnings

### WR-01: [WARNING / medium] Hairpin marks (Jabuka in both courses) advance while abeam, before the island is rounded

**File:** `src/jabuka/nav/course.py:570-580,629-633` (documented in the module docstring, lines 26-27: "slightly early but safe")

**Issue.** The abeam test is `dot(P - M, u_in) > 0`, the line perpendicular to the incoming leg through the mark. The two Jabuka legs are 203° in and 009° (A) or 038° (B) out, a 165-195° turn. The boat passes abeam on the approach side, roughly half a lap before the rounding is complete. Ten seconds later the active mark becomes Blitvenica or Mulo, and the CTS, laylines and course line all point back along the side of the island the boat is on. Following them means turning back without rounding the mark, which is a DSQ. It also pushes the crew into the Annuler path of CR-02. The docstring calls this "safe", but it is the opposite of safe at a rounding the crew does at night.

**Fix.** For turns above about 90°, require the boat to have passed the mark relative to the outgoing leg as well, for example `dot(P - M, u_out) > 0` on the rounding side, or a swept-bearing test around M. Otherwise rely on the zone exit only.

```python
turn = abs(wrap_pi(out_bearing - in_bearing))
if turn > math.radians(90):
    passed = dot(P - M, u_in) > 0 and dot(P - M, u_out) > 0
```

### WR-02: [WARNING / medium] Source flapping (LIVE ↔ LIVE_BG ↔ MANUEL) resets the 60 s layline filter on every flip, so the laylines jump to raw, undamped TWD

**File:** `src/jabuka/nav/wind.py:267-289`

**Issue.** `key = (source, manual-json)`. Any change resets all three EMAs, and the next value is a single raw sample. There is no hold time or hysteresis on the arbitration. A single input (BSP, AWA, heading) missing one 5 s staleness window flips LIVE to LIVE_BG and back.

**Failure scenario.** Assume a fouled paddlewheel or a Fastnet buffer trim, so BSP updates every 4-6 s. The source alternates between LIVE and LIVE_BG every few seconds. `twd_lay` is supposed to be a 60 s average. Instead it is re-seeded each time with one gusty raw sample, which is ±10° in a shifty bora, and the two sources may also differ by up to the 10° cross-check tolerance. The laylines and the "Virement dans …" countdown swing by minutes from second to second. This is the jitter the 60 s τ was meant to remove.

**Fix.** Do not reset when switching between the two live sources, because both measure the same wind. Add a hold time before leaving a source, for example 10 s:

```python
family = "live" if sol.source in ("LIVE", "LIVE_BG") else sol.source
key = (family, manual.model_dump_json() if sol.source == "MANUEL" and manual else None)
```

Also keep the last LIVE solution for a few seconds before falling back to MANUEL.

### WR-03: [WARNING / medium] Manual-wind age and the post-restart Annuler window use the unsynced system wall clock

**Files:**
- `src/jabuka/core/nav_service.py:137`
- `src/jabuka/core/nav_api.py:110`
- `src/jabuka/nav/wind.py:326-334`
- `src/jabuka/nav/course.py:556-565,637-644`
- (contract) `src/jabuka/common/clock.py:281-283`

**Issue.** `GpsClock.wall()` is documented as "System wall clock: log metadata and the system_clock diagnostic only". Phase 2 uses it for domain decisions: `ManualWind.t_set_wall`, the "Vent manuel ancien" / PÉRIMÉ threshold, and the banner window restored after a restart. The Pi has no RTC. After a power cut, the system clock is fake-hwclock's last save (or worse) until chrony locks to GPS, which can take minutes.

**Failure scenario.** At 20:00, manual wind is entered while the bus is dead. A power cut at 21:05 reboots the Pi, and fake-hwclock restores 20:17. The manual wind is 65 min old (stale, since the threshold is 30 min), but `age = 20:17 - 20:00 = 17 min`. The helm shows "MANUEL 17 min" in amber, and the laylines run on hour-old wind as if it were fresh. The age only corrects itself when chrony steps the clock.

**Fix.** Use the GPS-validated time (`clock.now_utc()` / `_utc_epoch`) for `t_set_wall` and for the age. When it is None (not synced), report the age as unknown and flag the badge "MANUEL âge ?" rather than computing from the system clock. Do the same for `Banner.at_wall`/`until_wall`.

### WR-04: [WARNING / medium] A fast double tap on the night toggle can leave a bright day map under the night UI

**Files:** `src/jabuka/web/static/map.js:213-238`, `src/jabuka/web/static/app.js:151-162,188-195`

**Issue.** `setTheme` compares `t === currentTheme` before awaiting `loadStyle`, but assigns `currentTheme = t` only after the await.

Sequence, starting in night mode:

1. Tap 1 calls `setTheme("day")`: `currentTheme` is night, so it awaits the fetch of `/style-day.json` (about 12k lines from the Pi, hundreds of ms).
2. Tap 2 calls `setTheme("night")`: `currentTheme` is still night, so it returns at once.
3. Tap 1 completes and calls `setStyle(day)`.

The body class and localStorage now say night, but the map is the white/blue day style at full brightness.

**Failure scenario.** At night, with gloves and the boat moving, the helmsman double-taps "Jour"/"☾ Nuit". The tablet lights up the cockpit with the day basemap, which destroys night vision, and the UI still claims night mode.

**Fix.** Serialize theme changes and apply only the latest request:

```js
let wanted = null, chain = Promise.resolve();
export function setTheme(theme) {
  wanted = theme === "night" ? "night" : "day";
  chain = chain.then(async () => {
    const t = wanted;
    if (!mapInstance || t === currentTheme) return;
    const style = await loadStyle(t);
    if (t !== wanted) return;              // superseded while loading
    currentTheme = t;
    mapInstance.setStyle(style, { transformStyle: ... });
  });
  return chain;
}
```

### WR-05: [WARNING / medium] One tap on "Parcours A"/"Parcours B" resets race progress to the first mark, without confirmation, even when it is the template already in use

**Files:** `src/jabuka/web/static/carte.js:311-315`, `src/jabuka/nav/course.py:322-330`

**Issue.** `select()` rebuilds the course from the template:

- `active_idx` goes back to 1
- custom marks are dropped
- leg side/radius edits are lost
- `sides_confirmed` is cleared

The Carte buttons post it on a single tap. The request carries the current `base_version`, so it always passes. Tapping the template that is already active is not a no-op.

**Failure scenario.** Mid-race, past Jabuka, the navigator taps the highlighted "Parcours A" button while scrolling the Carte panel. The helm immediately shows Plić Sestre (40 nm back) as the active mark, with laylines, CTS and countdown all pointing back to it. The leg edits made at the briefing (sides, radius, an added committee mark) are gone. The banner says nothing, because this is an edit, not an advance.

**Fix.** Make re-selecting the current template a no-op. Use the same two-step confirm as "Supprimer" for a template change. Optionally preserve `active_idx` when the new template contains the same mark at the same index.

### WR-06: [WARNING / medium] A degraded basemap (prep fallback to maxzoom 12 or 10) goes blank above that zoom: the style always declares maxzoom 14

**Files:**
- `src/jabuka/web/static/map.js:102-108`
- `src/jabuka/web/static/style-day.json` and `style-night.json` (source `protomaps.maxzoom = 14`)
- `src/jabuka/core/tiles.py:210`
- `src/jabuka/prep/map.py:118,1045-1053`

**Issue.** `jabuka-prep-map` deliberately falls back to maxzoom 12, then 10, when the full extract fails. Even then `map.js` loads the vendored style unchanged. MapLibre requests z11-14 tiles, the core answers 204 for every `z > idx.maxzoom`, and MapLibre renders an empty tile. Overzooming only happens when the source's `maxzoom` matches the data.

**Failure scenario.** The marina Wi-Fi is weak the evening before, and the extract succeeds only at maxzoom 10 (manifest `fallback: maxzoom-10`). At sea, "Centrer" zooms to `CENTRE_ZOOM = 11` and the coastline and islands disappear around the boat. That is exactly where the map matters most, near Jabuka, Blitvenica and the Kornati shoals.

**Fix.** Patch the style from `/racepack/info` in `loadStyle`:

```js
if (racepack.tiles && Number.isInteger(racepack.maxzoom)) {
  for (const s of Object.values(style.sources)) if (s.type === "vector") s.maxzoom = racepack.maxzoom;
}
```

### WR-07: [WARNING / medium] `jabuka-prep-polar` rejects standard qtVlm/OpenCPN grid polars that include a TWS 0 column or a TWA 0 row

**File:** `src/jabuka/prep/polar.py:85-94,167,173`

**Issue.** `_check_tws` requires 0 < TWS ≤ 60, and `_check_twa` requires 0 < TWA ≤ 180. Many qtVlm/OpenCPN `.pol` files start with a `0` TWS column and a `0` TWA row of zeros. I verified both cases:

- `TWA\TWS\t0\t6\t10…` fails with "line 1: TWS 0 kn outside (0, 60]", exit 2.
- Without the 0 column, it fails with "line 2: TWA 0 deg outside (0, 180]".

**Failure scenario.** At the dock on 12 Nov, the owner runs the tool on the "polaire générique X35" exported from qtVlm. It is refused. With no time to hand-edit the file, the boat races on the interim ORC polar instead of the owner's own. Every target speed, target TWA and % polar is then off by whatever separates the two.

**Fix.** Skip (do not reject) a TWS = 0 column and a TWA = 0 row when all of their speeds are 0. `Polar` already adds the implicit (0, 0) origin and TWS-0 curve:

```python
keep = [j for j, t in enumerate(tws_raw) if t > 0]       # drop a 0 column
if twa == 0.0 and all(not c or _num(c, lineno, dec_comma) == 0 for c in cells):
    continue                                              # drop a 0 row
```

## Info

### IN-01: [INFO / low] REST hardening gaps: next/prev have no `base_version`, body-less POSTs are CSRF-able, there is no body-size limit and no security headers

**Files:**
- `src/jabuka/core/course_api.py:143-149`
- `src/jabuka/web/static/carte.js:316-317`
- `src/jabuka/core/web.py:82`

**Issue.** The module docstring says "Every mutating body carries base_version", but `/api/course/next` and `/api/course/prev` take no body. If the helm tablet and the navigator's tablet both tap "Suiv." for the same rounding, the boat skips a mark.

Because they have no body, these two routes also answer a cross-site simple `<form method=post>` (verified: a form-urlencoded POST to a body-less FastAPI route returns 200). A laptop on the boat Wi-Fi browsing a hostile page while at the dock can change the active mark.

No request body size is capped. A single 600 MB POST to `/api/settings` is read into RAM on the 1 GB Pi before pydantic rejects it. There is no CSP, X-Frame-Options or Host check (DNS rebinding).

**Fix:**
- Add a `VersionIn` body to next/prev and send `base_version` from carte.js.
- Reject requests whose `Content-Type` is not `application/json` on mutating routes.
- Add a small middleware that rejects `Content-Length > 64 KiB` and checks `Host` against the AP address.
- Send `Content-Security-Policy: default-src 'self'` and `X-Frame-Options: DENY`.

### IN-02: [INFO / low] A map load slower than 30 s disables the map until the page is reloaded

**File:** `src/jabuka/web/static/map.js:168-210`

**Issue.** On timeout, `mapPromise` stays rejected forever. Every later `ensureMap()` from helm/overlays/carte/lock gets the rejection. The half-built `maplibregl.Map`, with its WebGL context, is never removed. A Pi 3B busy at startup (Phase 3 router workers plus the tile threadpool) can exceed 30 s for the first `load` event, which includes tiles and glyphs. The result is "CARTE INDISPONIBLE" for the whole race unless someone reloads.

**Fix.** On failure call `map.remove()` and reset `mapPromise = null`, so a later call retries. Alternatively, resolve on `style.load` and do not time out on tiles.

### IN-03: [INFO / low] "À la fin" on the final leg inserts the new mark behind the active finish, so it is silently skipped

**Files:** `src/jabuka/web/static/carte.js:403`, `src/jabuka/nav/course.py:390-397`

**Issue.** With the finish active (`active_idx == lastIdx`), the client sends `insert_at = lastIdx`. `add_mark` then does `at <= active_idx`, which gives `active_idx += 1`. The active mark stays the finish, and the new committee mark is listed as already done. The navigator who adds a late extra mark "before the finish" gets no laylines to it.

**Fix.** When `at == active_idx`, keep `active_idx` on the inserted mark, or have the UI insert at the active index and activate it.

### IN-04: [INFO / low] A racepack `polar.json` that passes loading can still crash `targets()` every tick

**File:** `src/jabuka/nav/polar.py:145,262-274`

**Issue.** `load_racepack_polar` only smoke-tests `speed(12, 45)`. For a polar whose only curve is TWS 0 (accepted by `polar_from_json`), `targets()` raises `StopIteration` at `next(t for … if t > 0.0)`. This happens on every tick, so `_compute` fails, which combined with CR-01 shows "PAS DE VENT". `jabuka-prep-polar` rejects such a file, but a hand-copied `polar.json` bypasses it.

**Fix.** Smoke-test `targets(6.0)` and `targets(20.0)` in `load_racepack_polar` and fall back to the builtin polar on any exception. Require at least one TWS > 0 curve in `Polar.__post_init__`.

### IN-05: [INFO / low] GPS gaps weaken two safety checks: the Jabuka zone and the rounding debounce

**Files:** `src/jabuka/nav/wind.py:209-215`, `src/jabuka/nav/course.py:582-589,629-633`

**Issue.**
- `in_zone()` returns False when the position is stale (3 s), so the untrusted compass is used again near Jabuka during a GPS dropout. The laylines and TWD then use the deviated heading with no "CAP NON FIABLE" flag.
- `_fsm` only runs with a position, so `_cand_since` survives a gap. After a 30 s outage the first fix advances immediately on a single sample instead of 10 s of continuous evidence.

**Fix.** Keep the last known zone state, with an expiry of about 5 min, when the position is stale. Reset `_cand_since` when the gap between FSM samples exceeds about 2 s.

### IN-06: [INFO / low] In "sailed" layline mode, "Autre bord" shows a ground track as if it were a compass heading

**File:** `src/jabuka/nav/laylines.py:264-269,340`

**Issue.** For a sailed side, `side()` returns `trk = TWD + theta` as the "heading shown for that tack", and it is published as `other_tack_hdg_t`. That is a COG-derived track that includes leeway and current. The helmsman compares it with the compass after the tack, and the difference is leeway plus current set, typically 5-10°. The value is labelled as a heading (°M).

**Fix.** Publish the polar heading for "Autre bord" (`TWD ± target TWA`) even in sailed mode, or label the sailed value "Route fond".

### IN-07: [INFO / low] Course FSM edge cases

**File:** `src/jabuka/nav/course.py:89-100,608-628`, `src/jabuka/core/nav_service.py:243-244`

**Issue.**
- `radius_nm` is allowed up to 3.0 nm, but `GATE_NM = 2.0`. Above a radius of 1.75 nm the zone (radius + 0.25) extends past the gate, so the "left the zone" trigger can never fire: `d > GATE` resets `_entered` first. Only abeam remains.
- `_prev_leg` and `_prev_primary` hysteresis carry over to the next mark after an advance, so the first ticks of a new leg can keep the previous leg's type.
- `CourseStore.alerts` is append-only, so a single transient write failure keeps "Écriture du parcours impossible" for the rest of the run. That alert is invisible today anyway (CR-01).

**Fix.** Cap the leg radius at `GATE_NM - ZONE_MARGIN_NM`, or use `max(GATE_NM, zone + 0.5)` as the gate. Reset `_prev_leg` and `_prev_primary` when `target.idx` changes. Clear the write-failure alert after the next successful write.

### IN-08: [INFO / low] A restored lock is applied late after a page reload

**Files:** `src/jabuka/web/static/index.html:66`, `src/jabuka/web/static/app.js:391-396`, `src/jabuka/web/static/lock.js:230`

**Issue.** The overlay starts `hidden` in the HTML. The persisted lock is applied only once `lock.js` is dynamically imported, after `helm.js` has loaded and the WebSocket and map have started. When Android Chrome reloads a discarded tab, spray or a wet sleeve can hit the tabs, the Annuler banner or the map buttons during that window (from tens of ms up to a second on a slow tablet). Locking also does not blur a focused input.

**Fix.** Add a tiny inline script in `index.html` that removes `hidden` from `#lock-overlay` when `localStorage["jabuka.locked"] === "1"`, before any module loads. In `apply(true)`, call `document.activeElement?.blur()`.

## Verified non-issues (checked, no finding)

- **Signs and conventions.**
  - `true_wind_from_apparent`, the leeway rotation (`awa + λ`, track `hdg − λ`) and `heading_true` (offset, then `mag + var(E)`) are correct.
  - Manual entry converts °M to °T once.
  - The browser converts back with `display.variation`.
  - Current is used as a TOWARDS vector (`current_towards_uv`) and added to the polar ground vectors only, never to the sailed (ground-referenced) angles.
- **Laylines.** In the `decompose` normal/overstood/fetching classification, `a` is the time to the other-tack layline. The track-ray countdown has `back ≥ 0` on the approach side. The ±20° on-tack guard against the mid-tack COG spike is correct. CTS current compensation has the right sign. Deviation hints have the right sign for TWA (LOFER when too far off the wind) and for CTS (BÂBORD when heading right of CTS).
- **Rounding anchor.** The anchor is on the correct side: a mark left to port gives `leg_bearing + 90°`.
- **Undo token.** It is compared with `hmac.compare_digest`. The window runs on t_mono, and the browser compares server `t_mono` with server `undo_until_s`.
- **REST validation.** NaN and ±inf are rejected by every model (`MarkIn`, `LegPatch`, `Settings`, `ManualWindIn`), checked by running pydantic. `extra="forbid"` is set on edit bodies and `Settings`. Mark names are stripped of control characters, and indices are range-checked server-side. A JSON body sent without `Content-Type` is rejected (422), so only the body-less routes are CSRF-able (IN-01).
- **Lock overlay.** It is at z-index 100, above the top bar (20), the banner (30), main and the map, and covers the Diag iframe. It swallows pointer/touch/mouse/click/wheel/contextmenu events with `preventDefault` on `touchstart`/`touchend`, so no synthetic click reaches the padlock underneath after a long-press unlock. A second finger cancels the long-press. Map handlers are disabled synchronously when the map exists.
- **No wall clock in the domain.** There are no `time.time`/`datetime.now` calls in `nav/` or `core/`. See WR-03 for the injected `wall()` being the wrong clock.
- **36 h leaks.** All of these are bounded or registered once:
  - Hub queues (bounded, drop-oldest, unregistered in `finally`)
  - Polar cache (capped at 4096)
  - tack deques (`maxlen=3`)
  - JS listeners (registered once)
  - `lastEvent` map (latest value only)

  MapLibre `setData` at 1 Hz on small GeoJSON sources is fine.
- **Tiles.** No path is built from request input, z/x/y are range-checked before `1 << z`, and directory offsets are bounds-checked when indexing.
- **prep/map.** The go-pmtiles tarball sha256 is verified before extraction. Only the `pmtiles` member is read, so there is no tar path traversal. `subprocess` is called with argv lists. HTTP Range responses must be 206 and size-capped.

---

_Reviewed: 2026-11-06T10:10:22Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
