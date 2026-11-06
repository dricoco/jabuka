---
phase: 03-weather-routing-tack-advice
plan: 06
subsystem: web/helm-routing-ui
status: complete
tags: [routing, helm, tablet, maplibre, on-reste, lock, night, grib-only, bias, dry-run, docs, ROUT-06, ROUT-07, ROUT-08, ROUT-09, ROUT-10, WIND-05, WIND-06, ROUT-01, GRIB-01, NAV-02]

requires:
  - phase: 03-05
    provides: "nav.route block, WS route message, GET /api/route, POST /api/route/stay, wind.source GRIB, router health row"
  - phase: 02-05
    provides: "helm bands, helm_logic.js, lock.js overlay, night theme, map.js registerOverlay"
provides:
  - "static/route_logic.js: countdownView, costText, biasText, stayButton, routeBand, routeData, nextTackData, routeLayers, STR (all route helm strings in one table)"
  - "static/route.js: overlay 'route' on the shared map, #route-band, #stay-button (ON RESTE, lock-aware)"
  - "helm_logic.js: route-first primary number, deviation and countdown with layline fallback; GRIB badge; layline distance (NAV-02)"
  - "tests/ui/conftest.py hooks racepack_extra and core_extra_args; tests/ui/test_route_ui.py (real core, --clock gps on a fake gpsd)"
  - "scripts/racepack-dryrun.sh and tests/routing/test_real_pack_e2e.py (JABUKA_REAL_PACK)"
  - "docs/ROUTING.md operator section, docs/WEATHER-PACK.md Friday 13 Nov checklist"
affects: [phase-4]

actuals:
  tokens: 21000
  tasks: 3
  commits: 6
plan_head_before: 7730f5147eb6c7adc43553fcf10b864ff27b24b7
commits: 6

tech-stack:
  added: []
  patterns:
    - "Route helm strings live in one STR table (route_logic.js) for a later fr/sl language switch"
    - "helm_logic.js <-> route_logic.js import each other (function declarations only, no top-level calls), so the Phase 2 helm functions delegate to the route formatter"
    - "UI tests that need routing: racepack_extra adds the land mask + a uniform wind.npz covering now +- 2 days; core_extra_args runs --clock gps against an in-thread FakeGpsd pushing TPVs stamped now"

key-files:
  created:
    - src/jabuka/web/static/route.js
    - src/jabuka/web/static/route_logic.js
    - tests/test_route_logic.py
    - tests/ui/test_route_ui.py
    - tests/routing/test_real_pack_e2e.py
    - scripts/racepack-dryrun.sh
  modified:
    - src/jabuka/web/static/app.js
    - src/jabuka/web/static/app.css
    - src/jabuka/web/static/helm.js
    - src/jabuka/web/static/helm_logic.js
    - tests/test_helm_logic.py
    - tests/ui/conftest.py
    - docs/ROUTING.md
    - docs/WEATHER-PACK.md

key-decisions:
  - "With a valid route the primary label is 'TWA ROUTE ↑/↓' with the tack word as the small unit ('42°' + 'tribord'), or 'CAP ROUTE' 114°M; any other route state gives exactly the Phase 2 output"
  - "The route band sits in #helm-bottom under the countdown (and the layline distance), not as a separate flex child, so the Barre layout keeps its two bands"
  - "ON RESTE cancel is always enabled while active, even when the route state is not ok"
  - "The next tack point is drawn from nav.route.tack_lat/lon every second (authoritative), the route line and tack points from the route message"
  - "GET /api/route is only called when nav.route.version > 0 and differs from the drawn version, so Phase 2 tests (no pack) never see a 404"

requirements-completed: [ROUT-06, ROUT-07, ROUT-08, ROUT-09, ROUT-10, WIND-05, WIND-06, ROUT-01, GRIB-01]

duration: about 45 min
completed: 2026-11-06
---

# Phase 3 Plan 06: Route on the helm Summary

**The tablet now shows the route. The core's route line and tack points are drawn on the offline
map, red-only at night. With a valid route the Barre tab's big number and countdown come from it
(`TWA ROUTE ↑ 42° tribord`, `Virement dans 08:30`, `VIREZ`, `Route mise à jour…`,
`Virement imposé (terre) dans 01:35`), with the cost of not tacking, the route age and the GRIB
bias. A 64 px "ON RESTE" button does nothing while the screen is locked. Without a valid route
the Phase 2 laylines come back by themselves, with the reason shown. A real DWD pack was built on
the laptop and Course A was routed end to end on it.**

## Performance

- **Duration:** about 45 min (first commit 19:38, last 19:55 local, plus the gate)
- **Tasks:** 3 (1 tracer, 2 TDD), 6 commits (RED + GREEN per task)
- **Files:** 6 created, 8 modified (1708 lines added)

## Accomplishments

- **route_logic.js** (pure, node-tested). It formats the 03-05 route block:
  - `countdownView` gives mm:ss below one hour and "1 h 07" above. It shows `VIREZ`/`EMPANNEZ`
    (class alert) for 0 to -120 s, `Route mise à jour…` when the core says updating, and
    `Virement imposé (terre) dans …` while ON RESTE runs into land. Without a valid route it
    returns the Phase 2 layline text.
  - `routeBand` gives the state line (blocked clock, no pack, computing, failed, disabled,
    stay, off route, level), `Ne pas virer : +4 min`, `Route : il y a 3 min`, the
    complementary target and the bias.
  - `biasText`, `stayButton`, and `routeData`/`nextTackData`/`routeLayers` for the map.
  - The `STR` table holds every new helm string.
- **helm_logic.js / helm.js.**
  - `primaryView`, `deviationView` and `fmtCountdown(layline, leg, route)` prefer a valid
    route.
  - `helmView` gains `countdownCls`, `countdownSource` and `laylineDist`. The source badge maps
    `GRIB` to "GRIB" (warn).
  - helm.js toggles `.alert`/`.warn` on the countdown and adds `#helm-layline-dist`. Every
    Phase 2 test is unchanged and green.
- **route.js.**
  - Registers overlay `route` (sources `route`, `route-tack`, `route-next`). Day: a 4 px
    dark-magenta line with white-cased circles. Night: a #ff0000 dashed line with #aa0000 and
    #ff0000 circles on black. The overlay is hidden while the route is not ok.
  - Draws on every bus `route` event. When `nav.route.version` differs from the drawn version
    it fetches `GET /api/route`, so a missed message heals itself.
  - Builds `#route-band` and `#stay-button`. The button POSTs `{active: !current}` and stays
    disabled until the answer, which is the fresh nav message. A 409 shows
    `On reste impossible : …` for 6 s.
  - Ignores clicks while locked: it checks `body.locked`, the bus `lock` event and the overlay.
- **app.js.** WS messages of type `route` go on the bus as `route`. route.js is imported last,
  in its own try/catch.
- **Real-data dry run.** `scripts/racepack-dryrun.sh` ran wind, waves, land, geofields, check,
  the quick bench and the e2e test against today's DWD runs (output below).
- **Docs.**
  - ROUTING.md (now 319 lines) has a French operator section: what each helm line means, when
    to press ON RESTE, land release, `Route mise à jour…`, the GRIB badge, switching the bias
    off, `route_level`, each alert and its action, the laylines fallback, Diag and the dry run.
  - WEATHER-PACK.md has "Checklist vendredi 13 novembre" with UTC times and "Si DWD est en
    retard".

### Dry-run summary (2026-11-06, 37 s)

```
RÉPÉTITION PACK DE COURSE : var/racepack-dryrun   (37 s)
  fenêtre          : 2026-11-06T22:00 -> 2026-11-07T22:00 (heure locale)
  vent             : ICON-EU run 2026-11-06T15:00:00Z, 2026-11-06T21:00:00Z -> 2026-11-07T21:00:00Z
  vagues           : EWAM run 2026-11-06T12:00:00Z
  masque terre     : REPRIS de tests/fixtures/route/landmask_race_25m (Overpass injoignable, cache OSM vide)
  couverture       : COUVERTURE MÉTÉO : OK
  niveau recommandé: L0 (banc rapide, ce portable)
  route (instruments): 45 points, 12 tacks, ETA 2026-11-07T17:02:47Z, level L0, wind 39°/5.0 kn at Vodice
  route (GRIB only  ): 45 points, 12 tacks, ETA 2026-11-07T17:02:47Z, level L0, wind 39°/5.0 kn at Vodice
```

Quick bench on this pack (laptop): L0 p50 0.43 s, p95 0.44 s, jitter 1.0 ms, ETA 18.55 h. L1 p95
0.36 s, jitter 1.6 ms.

## Task Commits

1. **Task 1 (tracer): route on the map + route-driven helm.** RED `8ac331b`, GREEN `e85882a`.
   Tracer feedback gate (auto mode): the plan's automated verify was re-run after GREEN.
   `tests/ui` (29 passed, Phase 2 included) and the node tests were green, so execution
   expanded.
2. **Task 2: ON RESTE, lock, night, GRIB badge, Diag.** RED `ad7895a`, GREEN `3465d42`.
3. **Task 3: real pack dry run + procedures.** RED `39b3645`, GREEN `0109bc0`.

## TDD Gate Compliance

The plan type is `execute`, so no plan-level gate applies. Each task still has a RED commit:

- **Task 1:** 10 node tests failed (missing module and exports), and the browser test failed on
  an empty `route` source after the real core had adopted a route.
- **Task 2:** the ON RESTE browser test failed (no `#stay-button`). Its node cases
  (`stayButton`, `biasText`, the GRIB badge) were already green: those functions were part of
  the Task 1 `route_logic.js` contract (interfaces block) and were written with it.
- **Task 3:** the e2e test failed with `JABUKA_REAL_PACK` set and no pack, and skips without
  the variable.

## Verification

- **Gate.** `JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 bash scripts/check.sh` printed
  `check: ok`.
  - ruff check is clean and ruff format --check reports 190 files formatted.
  - Results: Python 3.14 gave 1226 passed, 5 skipped; Python 3.13 gave 1226 passed,
    5 skipped. The master baseline was 1203 passed, 2 skipped; this plan adds 23 tests.
  - The 5 skips:
    - 2 are `test_real_pack_e2e.py`, which needs `JABUKA_REAL_PACK` (by design: no data in CI).
    - 1 is the weatherrouting oracle (by policy).
    - 2 are the wheelhouse checks in `tests/deploy/test_lock.py`, because this fresh worktree
      has no `deploy/wheelhouse`.
- **Plan verify.** `JABUKA_REQUIRE_UI=1 pytest tests/ui tests/test_route_logic.py
  tests/test_helm_logic.py` gave 61 passed, 0 skipped.
- **Real-pack e2e.** `JABUKA_REAL_PACK=var/racepack-dryrun pytest
  tests/routing/test_real_pack_e2e.py` gave 2 passed (instruments and GRIB-only).
  `var/racepack-dryrun/bench.json` exists.
- **Acceptance greps.**
  - `registerOverlay("route"` appears once in route.js.
  - `innerHTML` appears 0 times in route.js and route_logic.js.
  - `/api/route/stay` appears in route.js, `ON RESTE` in route_logic.js and `"GRIB"` in
    helm_logic.js.
  - `ON RESTE` appears 5 times in ROUTING.md and `vendredi` once in WEATHER-PACK.md.
    ROUTING.md is 319 lines.

## Deviations from Plan

### Requested by the coordinator during execution

1. **Added NAV-02 layline distance (02 verification gap).** The server's `layline.dist_nm` was
   never displayed.
   - `helmView` now returns `laylineDist`, e.g. "Layline à 1,5 nm" (string in `STR`). It is
     present only when the countdown comes from the laylines and the layline is ahead
     ("normal" state, not a reach).
   - helm.js shows it in `#helm-layline-dist`, right under the countdown.
   - Node test: `test_layline_distance_next_to_the_layline_countdown`.
   - Commit: `e85882a`.

### Auto-fixed / adjusted (user away, recommended option taken)

2. **[Rule 3 - Blocking] Overpass unreachable.** overpass-api.de refused connections from this
   laptop (the same situation the 03-01 fixture ATTRIBUTION records), and no OSM cache existed.
   - By default the script stops at the land step with a clear message.
   - `JABUKA_DRYRUN_LANDMASK=DIR` lets a rehearsal reuse an existing mask. This run reused
     `tests/fixtures/route/landmask_race_25m`, which is real OSM data from 2026-11-06, not
     invented data. The summary line says `REPRIS de …`.
   - Wind and waves were downloaded live from DWD.
   - **Gap recorded:** the land step itself was not exercised online today.
3. **ON RESTE lock guard.** As the coordinator asked, the handler also checks `body.locked` and
   the bus `lock` event, besides relying on the overlay. The UI test proves that neither a tap
   nor a scripted `.click()` POSTs while locked.
4. **Bodies.** Every POST sends JSON (`{active: …}`), per the 415 rule on master.
5. **Test layout.**
   - The night-colour and Diag checks run inside the ON RESTE browser test, which already has
     an active button. This avoids a third routed core.
   - The route wait in the UI tests is 90 s (core) plus 30 s (browser), rather than a strict
     30 s, to absorb laptop load. Routing actually took a few seconds.
6. **"No tack ahead" text.** When the route has no tack before the mark, the countdown reads
   `Pas de virement prévu`. The plan did not specify this case.
7. **`EMPANNEZ`.** A due gybe shows `EMPANNEZ`. The plan only named `VIREZ`, for tacks.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register.

- **T-03-06-01:** textContent only, grep-checked.
- **T-03-06-02:** lock overlay plus handler guard, UI-tested.
- **T-03-06-03:** age always shown, state lines, layline fallback, `Route mise à jour…`.
- **T-03-06-04:** the offline guard records 0 external requests.

## Human items (end of phase, non-blocking)

| Item | Due | Source |
|---|---|---|
| Tablet check: route line and next tack readable over the map by day and at night; ON RESTE easy to hit with a wet thumb and ignored when locked; countdown, cost, bias and layline-distance lines fit next to the Phase 2 numbers (portrait and landscape) | before 2026-11-12 | 03-06 |
| Run `bash scripts/racepack-dryrun.sh` once more where overpass-api.de is reachable (land step online, OSM cache filled for Friday) | before 2026-11-13 | 03-06 |
| Pi bench (`jabuka-route-bench` on the Pi 3B), set `route_level` | 2026-11-09 | 03-03 |
| Copernicus current with the owner's account | before 2026-11-13 | 03-02 |
| Organiser forecast import when published | when published | 03-02 |
| Package lock review (numpy 2.5.4, prep pins) | end of phase | 03-05 |
| Friday 13 Nov final pack per docs/WEATHER-PACK.md checklist | 2026-11-13 | 03-06 docs |

## Self-Check: PASSED

All 6 created files and `var/racepack-dryrun/bench.json` exist. All 6 commits (`8ac331b`,
`e85882a`, `ad7895a`, `3465d42`, `39b3645`, `0109bc0`) are in `git log`.
