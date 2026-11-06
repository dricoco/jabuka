---
phase: 02-helm-mvp-laylines-marks-map
plan: 05
subsystem: ui
tags: [helm, night-mode, maplibre, overlays, lock-mode, wake-lock, nosleep, playwright, vanilla-js]

requires:
  - phase: 02-helm-mvp-laylines-marks-map (plan 02-01)
    provides: "nav message v1, map.js contract (registerOverlay/setOverlayData/setTheme), app shell bus, helm_logic.js, red-only style-night.json, vendored NoSleep, tests/ui harness"
provides:
  - "Night theme end to end: body.theme-night, jabuka.theme + jabuka.brightness, red-only overlays and MapLibre controls, theme-color meta, full screen on switch to night"
  - "Helm overlays: helm-course (course line, marks, radius circles by side, active mark), helm-live (laylines stbd/port, anchor, boat, heading line), seamarks (from the race pack)"
  - "Course-up / north-up and boat centring (jabuka.mapMode, jabuka.centred), Barre tab only"
  - "Finished Barre bands: primary >= 20% vh, deviation with LOFER/ABATTRE or steer hint, BSP/target, % polar, mark DTW · TTW, countdown, other-tack heading, flags badges, PERTE DONNÉES"
  - "Lock mode (lock.js + pure lock_logic.js), jabuka.locked; 'lock' bus event"
  - "Screen awake (wakelock.js: keepAwake/wakeState/onWakeChange), ÉCRAN badge"
  - "docs/TABLET-SETUP.md"
affects: [phase-3-routing, phase-4-commissioning]

tech-stack:
  added: []
  patterns:
    - "helm_logic.js returns view objects (primaryView {label,value,main,unit}, deviationView {text,hint,cls}, helmFlags [{key,text,cls}]); helm.js only writes textContent"
    - "Night colours are one red channel scaled by a brightness factor set as inline custom properties on body"
    - "Map overlays keep their data in map.js defs, so a theme switch (setStyle + transformStyle) never empties them"
    - "Lock overlay swallows events in the bubble phase; the screen-awake gesture listener is on window in the capture phase so the overlay cannot hide it"

key-files:
  created:
    - src/jabuka/web/static/lock.js
    - src/jabuka/web/static/lock_logic.js
    - src/jabuka/web/static/wakelock.js
    - docs/TABLET-SETUP.md
    - tests/test_lock_logic.py
    - tests/ui/test_night.py
    - tests/ui/test_helm.py
    - tests/ui/test_lock_wake.py
  modified:
    - src/jabuka/web/static/overlays.js
    - src/jabuka/web/static/app.js
    - src/jabuka/web/static/app.css
    - src/jabuka/web/static/helm.js
    - src/jabuka/web/static/helm_logic.js
    - tests/test_helm_logic.py

key-decisions:
  - "Deviation hint: TWA modes positive deviation (TWA > target) -> LOFER, negative -> ABATTRE (upwind and downwind alike); CTS mode positive (heading right of CTS) -> ◄ BÂBORD. Colours: <= 2 deg good, <= 5 deg warn, > 5 deg bad (was 3/8 in 02-01)"
  - "primaryView value carries the °M/°T suffix ('115°M'); main/unit split kept so the suffix draws smaller and the number fits 800 px portrait"
  - "Stale link greys numbers with the --dim colour only; the 02-01 grayscale filter was removed because grey light contains green/blue at night"
  - "'Centrer' zooms to 11 once when switched on (or found on at load): at zoom 9 the race-area maxBounds stops the map from centring on the boat"
  - "Orientation and centring only act on the Barre tab, never while the Carte tab edits the course (02-04)"
  - "A second finger (non-primary pointer) cancels a running unlock press, not only never starts one"
  - "ÉCRAN badge starts at 'aucun' (alert) until a tap acquires something; every later tap retries while it is 'aucun'"
  - "Sources named 'helm-*' except the 02-01 names laylines/anchor/mark/boat that test_map_smoke reads; the heading line is its own source 'helm-heading'"

patterns-established:
  - "localStorage keys per tablet: jabuka.theme, jabuka.brightness, jabuka.mapMode, jabuka.centred, jabuka.locked"
  - "New bus events: 'theme' (day|night), 'mapmode' ({mode, centred}), 'lock' (bool); Phase 3's 'On reste' button must check body.locked / the 'lock' event"
  - "Debug hooks: window.jabuka.lastNav, window.jabuka.setAppTheme"

requirements-completed: [HELM-01, HELM-02, HELM-03, HELM-04]

actuals:
  tokens: 21600      # chars/4 over the added lines of 5c3e0ea..HEAD (86447 chars), before this SUMMARY
  tasks: 3
  commits: 6         # MEASURED: git rev-list --count 5c3e0ea..HEAD before this SUMMARY commit
plan_head_before: 5c3e0ea818552d3aedfe616ee9747cef6bca2557

coverage:
  - id: D1
    description: "Night mode true black/red across map, overlays, numbers and controls, persisted per tablet"
    requirement: HELM-03
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_night.py#test_night_toggle_is_red_only_and_persists"
        status: pass
      - kind: unit
        ref: "tests/ui/test_night.py#test_night_style_file_has_no_icons_and_only_red"
        status: pass
    human_judgment: true
    rationale: "Real tablet in a dark room at the lowest usable brightness: readability and no white/green light from the status bar (plan human-check, end of phase)"
  - id: D2
    description: "Boat with heading, course with every mark and radius, laylines, seamarks; overlays survive day/night/day; course overlay hidden on Carte"
    requirement: HELM-01
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_night.py#test_overlays_survive_theme_switches_and_carte_tab"
        status: pass
    human_judgment: false
  - id: D3
    description: "Primary number >= 20% vh landscape and portrait, controls >= 48 px, all bands and badges from a live feed"
    requirement: HELM-02
    verification:
      - kind: unit
        ref: "tests/test_helm_logic.py"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_helm.py#test_bands_sizes_and_numbers"
        status: pass
    human_judgment: true
    rationale: "Glance readability from the wheel in sunlight and at night (plan human-check)"
  - id: D4
    description: "Frozen numbers grey with PERTE DONNÉES within 4 s of the core dying"
    requirement: HELM-02
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_helm.py#test_frozen_numbers_turn_grey_when_the_core_dies"
        status: pass
    human_judgment: false
  - id: D5
    description: "Course-up / north-up / centred map, persisted"
    requirement: HELM-01
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_helm.py#test_course_up_north_up_and_centre"
        status: pass
    human_judgment: true
    rationale: "Whether course-up feels right when steering is a helm judgement"
  - id: D6
    description: "Lock mode: everything swallowed, 2 s primary press unlocks, short press / second finger never do, survives reload"
    requirement: HELM-04
    verification:
      - kind: unit
        ref: "tests/test_lock_logic.py"
        status: pass
      - kind: automated_ui
        ref: "tests/ui/test_lock_wake.py#test_lock_swallows_everything_and_unlocks_on_a_long_press"
        status: pass
    human_judgment: true
    rationale: "Real spray / wet fingers on the real tablet (plan human-check)"
  - id: D7
    description: "Screen awake: verrou on a secure origin, vidéo without Wake Lock, aucun as an alert when rejected, re-request on visibility"
    requirement: HELM-04
    verification:
      - kind: automated_ui
        ref: "tests/ui/test_lock_wake.py"
        status: pass
    human_judgment: true
    rationale: "Android Chrome flag for http://10.42.0.1 and a 30 min untouched-screen test on the real tablet (A6, A7)"

duration: 40min
completed: 2026-11-06
status: complete
---

# Phase 2 Plan 05: Helm view complete Summary

**The helm view is finished. Night mode is true black with red only, end to end. The map shows the boat, heading line, whole course with radius circles, laylines and seamarks, and can be course-up or north-up with the boat centred. The primary number fills at least 20% of the screen with a LOFER/ABATTRE hint, and greys to PERTE DONNÉES when the link dies. A spray-proof lock unlocks only with a 2 s press. The screen is kept awake (Wake Lock, or the NoSleep video) with an ÉCRAN badge. docs/TABLET-SETUP.md is the tablet checklist.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-11-06T03:12Z
- **Completed:** 2026-11-06T03:52Z
- **Tasks:** 3 (tracer + 2 TDD)
- **Files modified:** 14

## Accomplishments
- **Night (HELM-03):**
  - The "☾ Nuit" / "Jour" toggle in the top bar persists per tablet and re-styles the map without losing overlay data.
  - A 40–100 % brightness slider scales every night colour on the red channel only.
  - MapLibre controls, focus outlines and scrollbars are red or black.
  - Switching to night sets theme-color #000 and requests full screen, which hides the white Android status bar.
- **Overlays (HELM-01):**
  - Course line through every leg.
  - Every mark with its name and rounding radius: port dashed, starboard solid.
  - The active mark is emphasised.
  - Laylines: starboard solid, port dashed.
  - Anchor, boat, and a 0.3 nm heading line.
  - Seamarks from `/racepack/seamarks.geojson`, coloured by category (light, beacon, buoy, hazard), with labels from zoom 11.
  - The course overlay steps aside on the Carte tab.
- **Barre (HELM-02):**
  - The primary number by point of sail is ≥ 20 % of the viewport height in 1280×800 and 800×1280.
  - The deviation carries LOFER/ABATTRE or ◄ BÂBORD/TRIBORD ►.
  - Bottom band: BSP / cible in nds, % polaire, "Plić Sestre 2,0 nm · 25 min", bearing, the countdown and "Autre bord 194°M".
  - Badges: CAP NON FIABLE, COURANT, ANGLES RÉELS and MANUEL with age.
  - When the link is not live, every number turns --dim and a big "PERTE DONNÉES" shows.
- **Map orientation:** "Nord en haut", "Cap en haut" and "Centrer" are persisted, act on the next nav message, and only on the Barre tab.
- **Lock (HELM-04):**
  - A 64 px SVG padlock (no emoji colours) locks the screen.
  - The overlay swallows pointer, touch, wheel, click, contextmenu and key events.
  - MapLibre handlers are disabled while locked.
  - A 2 s press of the primary pointer on the overlay padlock unlocks, with a progress ring.
  - The lock state persists.
- **Screen awake:**
  - The first tap requests the lock: Wake Lock gives "ÉCRAN: verrou", the NoSleep video gives "ÉCRAN: vidéo", and a rejected request gives "ÉCRAN: aucun" as an alert.
  - The lock is requested again when the page becomes visible.
  - If the browser releases the lock, the badge drops to "aucun".
- **TABLET-SETUP.md** covers:
  - Joining the "jabuka" AP and opening http://10.42.0.1.
  - The Chrome flag with the exact origin.
  - Stay awake, battery settings and full screen.
  - The chrome://gpu check and what CARTE INDISPONIBLE means.
  - Night mode, orientation and lock.
  - A table of every badge.
  - Debugging with chrome://inspect.
  - A checklist for the night before.

## Task Commits

1. **Task 1 (tracer): night mode + helm overlays** - `20faf00` (feat)
2. **Task 2: big numbers, stale link, course-up/north-up**: RED `e527b3b` (test), GREEN `bacb137` (feat)
3. **Task 3: lock mode, wake lock, TABLET-SETUP**: RED `374994a` (test), GREEN `5130a4a` (feat), fix `b7746f9` (fix)

Tracer feedback gate: after the commit, the Task 1 `<verify>` command (`tests/ui/test_night.py` + `tests/ui/test_map_smoke.py`) was re-run green before expanding to Tasks 2 and 3.

## Test results

- `JABUKA_REQUIRE_UI=1 bash scripts/check.sh`: ruff lint and format are clean. **596 passed on Python 3.14 and on 3.13**. The only 2 skips are the pre-existing `tests/deploy/test_lock.py` wheelhouse checks (deploy/wheelhouse is absent in a fresh worktree). Neither is a UI test.
- `tests/ui`: 16 headless-Chromium tests, green on 4 consecutive runs after the lock-race fix.
- No external request and no HTTP ≥ 400 in any UI test.

## Decisions Made
See `key-decisions` in the frontmatter. The ones other plans depend on:
- **Orientation and centring never act on the Carte tab.** This avoids fighting 02-04's mark dragging.
- **Bus events added:** `theme`, `mapmode` and `lock`. Phase 3's "On reste" button must stay lock-aware: check `body.locked` or listen to `lock`.
- **Map source names:** `helm-*` (plus the 02-01 names laylines/anchor/mark/boat), so they do not collide with the 02-04 `carte` sources.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The stale-link grayscale filter leaked green/blue light at night**
- **Found during:** Task 1/2 (night review of app.css)
- **Issue:** the 02-01 rule `body.link-stale #tab-barre .band { filter: grayscale(1) }` turns red into grey, which carries green and blue light.
- **Fix:** numbers now switch to `--dim` with `!important` under `#tab-barre.stale`, and the filter is gone.
- **Files modified:** src/jabuka/web/static/app.css
- **Commit:** bacb137

**2. [Rule 1 - Bug] "Centrer" could not centre at the default zoom**
- **Found during:** Task 2 (Playwright: the boat stayed 7.6 % off centre and the map kept easing)
- **Issue:** at zoom 9, maxBounds 14.9–16.4°E clamps the centre longitude.
- **Fix:**
  - Switching Centrer on (or finding it on at load) zooms to 11 once.
  - The same unreachable centre is not re-requested every second.
- **Files modified:** src/jabuka/web/static/overlays.js
- **Commit:** bacb137

**3. [Rule 1 - Bug] A short window after locking where the map still panned**
- **Found during:** Task 3 (UI flake: 2 of 6 runs)
- **Issue:** the MapLibre handlers were disabled through an async queue (dynamic import, then ensureMap).
- **Fix:** when the map is already up, the handlers are toggled synchronously, and the queued call stays for a map still loading. The test now waits for the state instead of sampling it once.
- **Files modified:** src/jabuka/web/static/lock.js, tests/ui/test_lock_wake.py
- **Commit:** b7746f9

**4. [Contract-preserving adjustment] The boat heading line is its own source `helm-heading`**
- **Issue:** the behaviour block puts the heading line in the "boat" source. 02-01's `tests/ui/test_map_smoke.py` asserts the `boat` source is exactly `["Point"]`, and that test is not in this plan's files.
- **Fix:** the heading line lives in `helm-heading`. test_night asserts both.

**5. [Layout] index.html is final (02-01) and was not edited**
- The night toggle, brightness slider, padlock, map buttons, deviation hint and PERTE DONNÉES line are built by app.js, lock.js and helm.js with DOM methods.
- helm.js moves the speed and % polar cells to the bottom band, and folds DTW/TTW into the mark line.
- `main` and `#banner` follow the real top-bar height through `--topbar-h`, because the 64 px padlock and wrapping badges make the bar taller.

**6. [Test-contract update] The 02-01 node expectations changed with the new contract**
- `tests/test_helm_logic.py` was updated for these intended changes:
  - `primaryView` now returns `{label, value, main, unit}`, with the value carrying °M.
  - The speed unit is now "nds".

**Total deviations:** 3 auto-fixed bugs and 3 contract-preserving adjustments. **Impact:** none on other plans' files. Step 3 of Task 1 (fixing `build-styles.mjs`) was not needed, because the generated `style-night.json` is already red-only (asserted).

## Known limitations (not stubs)
- **The page can flash white when loading in night mode.** `index.html` (02-01, final) starts with `body.theme-day`, and app.js applies the stored theme only when the module runs. At the helm the page is loaded once at dusk, so this is minor. A one-line inline script in index.html would remove it if 02-01's owner allows.
- **The NoSleep video fallback is only proven in headless Chromium** (assumptions A6/A7). It is a human item on the real tablet.

## Threat Flags
None. No new endpoint or trust boundary. Every server string is rendered with textContent or MapLibre text-field (T-02-05-01), with no innerHTML in the new modules (tested). T-02-05-03, -04 and -05 are mitigated and tested as planned.

## User Setup Required
End-of-phase human items, all non-blocking:
1. **Chrome flag:** on the real Android tablet, follow `docs/TABLET-SETUP.md` §2, set the flag to `http://10.42.0.1`, and confirm "ÉCRAN: verrou".
2. **Screen stays on:** leave the helm untouched for at least 30 min on charge. The screen must never sleep.
3. **Night readability:** in a dark room at the lowest usable brightness, check there is no white or green light, including the status bar.
4. **Spray test:** with the lock on, splash water and tap with wet fingers. Nothing should change. A 2 s press unlocks.
5. **Glance check from the wheel:** in sunlight and at night, the primary number and countdown should read at a glance, and course-up should feel right.

## Next Phase Readiness
Phase 3 can add the route polyline as another `registerOverlay` id, and the "On reste" button to the Barre bands. Buttons must respect `body.locked` / the `lock` event. The helm view is otherwise complete for Phase 4 commissioning, with TABLET-SETUP.md as its runbook input.

## Self-Check: PASSED
- Files present: lock.js, lock_logic.js, wakelock.js, overlays.js, helm.js, helm_logic.js, docs/TABLET-SETUP.md, tests/test_lock_logic.py, tests/ui/test_night.py, tests/ui/test_helm.py, tests/ui/test_lock_wake.py
- Commits present: 20faf00, e527b3b, bacb137, 374994a, 5130a4a, b7746f9

---
*Phase: 02-helm-mvp-laylines-marks-map*
*Completed: 2026-11-06*
