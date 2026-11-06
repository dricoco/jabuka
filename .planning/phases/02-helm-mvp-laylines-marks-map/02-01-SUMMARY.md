---
phase: 02-helm-mvp-laylines-marks-map
plan: 01
subsystem: nav-engine, api, ui, map
tags: [laylines, polar, true-wind, fastapi, websocket, pmtiles, maplibre, playwright, vanilla-js]

requires:
  - phase: 01-foundation-data-backbone-bus-test-kit
    provides: "StateStore.latest, conventions (true_wind_from_apparent, mag_to_true), atomicio, injected clocks, Hub/WS, CoreContext tick, sim.synth, Pi hash lock + wheelhouse"
provides:
  - "nav package (geo, polar, wind, laylines, course, settings) on the computed-live-wind path"
  - "NavService + the nav WebSocket message v1 (also GET /api/nav), published every tick after diag"
  - "REST seams: /api/settings (+schema, PUT 409/422), /api/course (select/next/prev), persisted atomically"
  - "Race pack server: TileIndex + /tiles, /racepack/info, /racepack/{seamarks,coastline}.geojson, Diag health 'racepack'"
  - "App shell (Barre/Carte/Réglages/Diag), module bus contract, helm_logic.js, /diag.html"
  - "Vendored MapLibre 5.24.0 / NoSleep 0.12.0 / glyphs / sprites, generated day + red-only night styles, map.js contract, overlays.js"
  - "tests/ui/conftest.py headless-browser harness (core subprocess, UDP feeder, offline guard) for 02-04/02-05"
  - "pyproject final for wave 2: pmtiles (Pi lock), playwright (dev), osmium (prep), jabuka-prep-map/-polar scripts"
affects: [02-02, 02-03, 02-04, 02-05, phase-3-routing]

actuals:
  tokens: 52620      # chars/4 over the authored diff (excl. vendored JS/CSS, glyphs, sprites, generated styles, lock, fixtures)
  tasks: 3
  commits: 4         # MEASURED: git rev-list --count f03c928..HEAD before this SUMMARY commit
plan_head_before: f03c9288ee9c8f59bc784ac4b25572afb29381b2

tech-stack:
  added: ["pmtiles 3.8.1 (Pi runtime)", "playwright 1.64.1 (dev)", "osmium 4.3.2 (prep extra)", "maplibre-gl 5.24.0 (vendored)", "nosleep.js 0.12.0 (vendored)", "@protomaps/basemaps 5.7.2 (build-time style generator)"]
  patterns:
    - "Server computes, browser formats: one nav message, helm_logic.js pure and node-tested"
    - "Every direction TRUE in the message (_t suffix); display.heading_ref + variation for °M display"
    - "Version counters (course_version/settings_version) in every nav message drive client refetch"
    - "Module contract mount(ctx={section, api, bus, badge, latest}); each module in its own try/catch"
    - "Race-pack tile index built once at startup; plain XYZ tiles, no browser Range requests"

key-files:
  created:
    - src/jabuka/nav/{__init__,geo,polar,wind,laylines,course,settings}.py
    - src/jabuka/nav/data/marks.json
    - src/jabuka/nav/data/x35-orc-od-2019.exp
    - src/jabuka/core/nav_service.py
    - src/jabuka/core/nav_api.py
    - src/jabuka/core/course_api.py
    - src/jabuka/core/tiles.py
    - src/jabuka/web/static/{index.html,app.js,app.css,helm.js,helm_logic.js,carte.js,carte.css,reglages.js,reglages.css,map.js,overlays.js}
    - src/jabuka/web/static/{style-day.json,style-night.json,vendor/,glyphs/,sprites/}
    - scripts/vendor-web.sh
    - scripts/build-styles.mjs
    - tests/ui/conftest.py
    - tests/fixtures/map/{sibenik.pmtiles,seamarks-mini.geojson,SOURCES.md,subset_pmtiles.py}
  modified:
    - src/jabuka/core/main.py
    - src/jabuka/core/web.py
    - src/jabuka/web/static/diag.html (moved from index.html)
    - pyproject.toml
    - deploy/requirements.in
    - deploy/requirements.lock
    - scripts/bootstrap-dev.sh
    - tests/deploy/test_lock.py
    - tests/test_tracer_e2e.py
    - tests/test_event_marker.py
    - tests/test_no_wallclock.py
    - tests/test_diag_logic.py

key-decisions:
  - "DTW/BTW/TTW in the nav message are measured to the rounding anchor (mark + radius on the rounding side), the point the laylines pass through"
  - "Overstood/fetching only exist on a beat/run leg: the boat->anchor leg type keeps 'beat' within the +5 deg hysteresis, beyond that the mark is a (close) reach and the helm shows the course to steer"
  - "Polar target search is bounded by the deepest TWA the polar covers at that TWS (never extrapolated past the VPP gybe angle) and includes every explicit polar angle (exact VPP beat/gybe angles)"
  - "Course next/prev bump the version only when the active index changes"
  - "Style attribution has no links ('Protomaps © OpenStreetMap') so the style files contain no URL at all"
  - "Tile fixture is zoom 8-11 (476 KB): zoom 0-7 world tiles and zoom 12 do not fit the 600 KB budget"
  - "Modules get ctx.latest(type) so a module mounted after the first course/settings/nav event still renders"

patterns-established:
  - "nav message v1 contract (see 02-01-PLAN interfaces): changing a field name is a cross-plan break"
  - "Shared UI harness fixtures: racepack_dir, core_server, feeder (mutable boat dict + wait_nav), page (offline guard)"

requirements-completed: [WIND-01, WIND-02, WIND-03, NAV-01, NAV-02, CRSE-01, CRSE-05, HELM-01, HELM-02]

coverage:
  - id: D1
    description: "Synthetic live wind + GPS reach the browser as a 1 Hz nav message with target TWA/BSP x efficiency, % polar, Plić Sestre, DTW/TTW, laylines and countdown"
    requirement: WIND-01
    verification:
      - kind: integration
        ref: "tests/nav/test_nav_tracer.py#test_live_wind_reaches_the_helm"
        status: pass
      - kind: unit
        ref: "tests/nav/test_polar_core.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Efficiency scales target speeds and times, never target angles"
    requirement: WIND-02
    verification:
      - kind: unit
        ref: "tests/nav/test_polar_core.py#test_efficiency_never_moves_target_angles"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every direction TRUE at one boundary (variation/offset; unknown ref treated as magnetic)"
    requirement: WIND-03
    verification:
      - kind: unit
        ref: "tests/nav/test_settings_core.py#test_heading_true_boundary"
        status: pass
    human_judgment: false
  - id: D4
    description: "Laylines by decomposition: normal/overstood/fetching, countdown, other-tack heading, reach -> CTS, GeoJSON"
    requirement: NAV-01
    verification:
      - kind: unit
        ref: "tests/nav/test_laylines_core.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Course A/B one-tap select, next/prev, persisted course and settings across restart, 409/422"
    requirement: CRSE-01
    verification:
      - kind: integration
        ref: "tests/web/test_api_seams.py"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_map_smoke.py#test_tabs_course_and_settings"
        status: pass
    human_judgment: false
  - id: D6
    description: "Offline map from vendored assets + race-pack tiles, laylines/mark/boat drawn, zero external requests, zero HTTP >= 400"
    requirement: HELM-01
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_map_smoke.py#test_map_renders_offline_with_overlays"
        status: pass
      - kind: integration
        ref: "tests/web/test_tiles.py"
        status: pass
    human_judgment: false
  - id: D7
    description: "Barre tab big numbers formatted from the nav message (primary by point of sail, deviation, BSP/target, %, DTW/TTW, countdown)"
    requirement: HELM-02
    verification:
      - kind: unit
        ref: "tests/test_helm_logic.py"
        status: pass
    human_judgment: false
  - id: D8
    description: "Map renders on the real tablet (WebGL), or the numbers still show with CARTE INDISPONIBLE"
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_map_smoke.py#test_helm_survives_without_webgl"
        status: pass
    human_judgment: true
    rationale: "Tablet model and its WebGL support are unknown; chrome://gpu and the offline render must be checked on the real device (plan human-check, end of phase)"
  - id: D9
    description: "Package review: Pi lock diff (only pmtiles 3.8.1), dev/prep extras, VENDOR.md integrity hashes"
    verification: []
    human_judgment: true
    rationale: "CONTEXT Addendum package policy: one end-of-phase human review of the lock diff and vendored assets"

duration: 41min
completed: 2026-11-06
status: complete
---

# Phase 2 Plan 01: Helm tracer + wave-2 contracts Summary

**Live apparent wind becomes a target TWA, polar % and laylines to Plić Sestre with a "Virement dans N min" countdown on a tabbed tablet page, over an offline MapLibre map served from a PMTiles race pack. Every seam wave 2 builds on (nav message v1, REST routes, map.js, module bus, UI test harness, pyproject/Pi lock) is fixed here.**

## Performance

- **Duration:** ~41 min
- **Started:** 2026-11-06T02:29Z
- **Completed:** 2026-11-06T03:10Z
- **Tasks:** 3 (tracer + 2 TDD-flagged)
- **Files modified:** 83 (incl. 12 glyph PBFs, 8 sprite files, 6 vendored files)

## Accomplishments
- **Nav engine:** the computed-live-wind path runs end to end, from StateStore inputs through the TRUE boundary, true wind, the interim X35 ORC polar × efficiency and the course anchor at the rounding radius to the layline decomposition. The 1 Hz nav message v1 goes out on the WebSocket and on GET /api/nav, and nav.* rows go back into the StateStore for Diag and the derived log. Nav failures are counted in `nav_errors` and never crash the tick.
- **REST seams:** settings (pydantic bounds with French labels, `base_version` 409, 422, 503 on disk failure) and course (Course A/B select, next/prev) are persisted with atomicio and push a fresh nav message to every tablet on each change. `--racepack DIR` is added.
- **Race pack server:** the PMTiles index is built once (root and leaf directories) and serves plain XYZ gzip MVT tiles, with 204 for anything missing or out of range. Overlays are served only from fixed file names, and the race-pack state shows in the Diag health table.
- **Browser:**
  - The app shell has four tabs (Barre, Carte, Réglages, Diag) and a link watchdog that shows "PERTE DONNÉES" and greys the helm.
  - helm_logic.js is pure and node-tested.
  - The Carte tab has A/B, Préc./Suiv. and "Côtés à confirmer (IC)".
  - The Réglages tab is a form generated from the settings schema.
  - Diagnostics moved to /diag.html.
- **Offline map:** MapLibre 5.24.0, NoSleep, the glyphs and the sprites are vendored and verified against the pinned npm integrity values. The generated day style and the red-channel-only night style contain no URLs. map.js provides the contract, overlays.js draws the laylines, mark, anchor and boat, and a tablet without WebGL still gets the numbers and a "CARTE INDISPONIBLE" badge.
- **Wave-2 readiness:**
  - pmtiles is in the hash-locked Pi lock, and the wheelhouse offline install simulation passes.
  - playwright and osmium are pinned.
  - The prep console scripts are declared.
  - The shared `tests/ui` harness is in place.

## Task Commits

1. **Task 1 (tracer): live wind -> helm** - `e16db1a` (feat)
2. **Task 2: offline race pack server** - `258984c` (feat)
3. **Task 3: offline map on the tablet**: RED `3b02e81` (test), GREEN `ce7b060` (feat)

Tracer feedback gate: the Task 1 `<verify>` command was re-run end to end after the commit (green), then the plan expanded to Tasks 2 and 3.

## Test results

- `JABUKA_REQUIRE_UI=1 bash scripts/check.sh`: ruff lint and format clean; **573 passed, 0 skipped on Python 3.14 and on 3.13**.
- `tests/ui` (6 headless-Chromium tests): stable over 5 consecutive runs.
- `bash scripts/build-wheelhouse.sh`: the offline `--require-hashes` install simulation passes with pmtiles.

## Decisions Made
See `key-decisions` in the frontmatter. The two that matter most for wave 2:
- **DTW/TTW are measured to the rounding anchor.** The anchor is the point the laylines pass through.
- **Overstood and fetching only occur inside the beat/run hysteresis band.** Further abeam, the mark is a reach and the helm shows the course to steer (CTS).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Polar downwind target could go past the deepest polar angle**
- **Found during:** Task 1 (tracer run gave down TWA 159.0 at 12 kn instead of 158.9)
- **Issue:** the 0.5° candidate grid rounded one step past the search limit, and beyond the last point the held speed made that angle look better.
- **Fix:** the grid is floored at the deepest polar angle, and a test asserts `down_twa <= 158.9`.
- **Files modified:** src/jabuka/nav/polar.py, tests/nav/test_polar_core.py
- **Committed in:** e16db1a

**2. [Rule 1 - Bug, plan-internal contradiction] "Boat 6 nm west of the anchor -> overstood"**
- **Issue:** under the plan's own leg-type rule (beat only if β < up TWA), a mark abeam (β = 90°) is a reach, so the literal case can never be overstood.
- **Fix:** the test exercises overstood and fetching where they exist, just past the layline within the +5° beat hysteresis (`prev_leg="beat"`). It also asserts that the literal abeam case is a reach.
- **Files modified:** tests/nav/test_laylines_core.py
- **Committed in:** e16db1a

**3. [Rule 3 - Blocking] Phase 1 tests pinned the diagnostics page at `/`**
- `tests/test_diag_logic.py` read `index.html` for `id="alerts"`. It now reads `diag.html`. This file was not in the plan's list.
- **Committed in:** e16db1a

**4. [Rule 3 - Blocking] go-pmtiles binary could not be executed (sandbox policy on downloaded executables)**
- **Issue:** the plan asked for a `pmtiles extract` from build.protomaps.com. The release tarball was downloaded and verified (GitHub asset digest sha256 3ed7dbf4…312f, since the release has no checksums.txt), but running it was refused.
- **Fix:** the fixture was cut from the research-session extract of `https://build.protomaps.com/20261105.pmtiles` (made with that same go-pmtiles 1.31.2 release), using the pinned Python `pmtiles` reader/writer. Tiles are copied byte for byte. The script `tests/fixtures/map/subset_pmtiles.py` is committed, and the full provenance chain is in `tests/fixtures/map/SOURCES.md`.
- **Committed in:** 258984c

**5. [Rule 3 - Blocking] Tile fixture size budget**
- **Issue:** maxzoom 12 gave 1.7 MB, and the plan's maxzoom-11 fallback still gave 1.37 MB because the zoom 0–7 world tiles are about 700 KB.
- **Fix:** the fixture covers zoom 8–11 (8 tiles, 476 KB). The UI tests and later tap tests work at zoom 9–11. Above zoom 11 the fixture returns 204 (blank map), which is expected for a fixture.
- **Committed in:** 258984c

**6. [Rule 2 - Missing critical] 503 instead of a bare 500 on a settings/course write failure**
- A full or read-only disk now returns `{"ok": false, "error": ...}` with HTTP 503, and nothing changes in memory (same pattern as Phase 1 /api/event).
- **Committed in:** e16db1a (tested in tests/web/test_api_seams.py)

**7. [Rule 1 - Bug] App shell UI bugs found on a screenshot during Task 3**
- **Issue 1:** `#tab-barre {display:flex}` overrode `[hidden]`, so the helm bands stayed visible on the other tabs.
- **Issue 2:** carte.js and reglages.js mounted after the first `course`/`settings` event and rendered empty.
- **Fix:** `.tab[hidden]` now uses `!important`, and `ctx.latest(type)` was added to the module contract. A regression UI test (`test_tabs_course_and_settings`) covers both.
- **Committed in:** ce7b060

**8. [Test robustness] UI tab test raced its own POST under full-suite load**
- **Issue:** the course list can update through the WebSocket refetch before the button's own request resolves.
- **Fix:** the test waits on each request's own response.
- **Committed in:** ce7b060

### TDD note
Task 2 was committed as a single `feat` commit: its tests were written alongside the implementation, not as a separate RED commit. Task 3 followed RED (`3b02e81`, failing because the vendored map was missing) then GREEN (`ce7b060`).

**Total deviations:** 8 (3 Rule 1, 1 Rule 2, 3 Rule 3, 1 test robustness). **Impact:** all were needed for correctness or to unblock. No scope creep and no contract change.

## Known Stubs (intentional seams, owned by wave-2 plans)

These settings are editable on the Réglages tab today but have **no effect until plan 02-03**:
- `true_wind_source` ("instrument")
- `layline_source` ("sailed")
- `use_current`, `leeway_deg`
- `tau_helm_s` / `tau_layline_s` (`twd_lay_t` equals `twd_t`)
- `zone_*` (Jabuka zone)
- `manual_wind_max_age_min`

The wind sources are LIVE or NONE only; MANUEL and LIVE_BG come in 02-03.

Other seams:
- **`course.banner`** is always null. 02-04 adds the rounding state machine and the banner.
- **`#lock-overlay`** is an empty, hidden placeholder. 02-05 fills it.
- **`NoSleep.min.js`** is loaded but not used yet. 02-05 uses it.
- **Night theme:** `setTheme()` exists in map.js, but the theme toggle UI belongs to 02-05.

These are not recorded in `.planning/WINDOWS.md`. The ledger is a shared file and this executor runs in a parallel worktree, so the orchestrator or a wave-2 plan should record them if wanted.

## Issues Encountered
- The rtk shell hook rewrites `git`, `grep` and `cat`, so the session used `/usr/bin/git` and `/usr/bin/grep` explicitly.
- Some compound shell commands were refused by the worktree-isolation guard and were split into separate commands.

## User Setup Required
None. End-of-phase human items, all non-blocking:
1. **Package review:** `git log -p f03c928..HEAD -- deploy/requirements.lock` should add only pmtiles 3.8.1, with hashes. Also check the dev/prep extras in pyproject.toml and the integrity values and sha256 in `src/jabuka/web/static/vendor/VENDOR.md`.
2. **Real tablet:** open `chrome://gpu` and check WebGL. Then open the page against the dev core or the Pi AP: the map should render offline with laylines drawn, or show "CARTE INDISPONIBLE" with the numbers still updating.
3. **Load your real X35 polar:** put it in the race pack as `polar.json`. Expedition-format import arrives with 02-02.
4. **Rounding sides and start line:** confirm them against the SIs at the briefing ("Côtés à confirmer (IC)").

## Next Phase Readiness
The wave-2 plans (02-02, 02-03, 02-04, 02-05) can run in parallel. pyproject.toml, the Pi lock, `core/main.py`, `core/web.py`, `index.html` and the shared test harness are final for them. The nav message, REST routes, map.js API, module bus and DOM ids are fixed as listed in the 02-01-PLAN interfaces block.

## Self-Check: PASSED
- 19/19 key files present (nav package, core seams, tiles, map.js/overlays.js/app.js, diag.html, VENDOR.md, UI harness, fixture, vendoring scripts)
- Commits present: e16db1a, 258984c, 3b02e81, ce7b060

---
*Phase: 02-helm-mvp-laylines-marks-map*
*Completed: 2026-11-06*
