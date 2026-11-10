---
phase: quick-261110-cuk
plan: 01
subsystem: helm-ui / nav
tags: [start-mode, timer, start-line, reverse-isochrone, web-audio, maplibre, i18n]
status: complete

requires:
  - phase: 02 (nav message, course, settings, helm Barre tab, map overlays)
    provides: NavService tick + nav message, SettingsStore, coord_logic.js, map.js overlays, events log
provides:
  - "Start mode on the Pi: start.json (line ends ping/typed, open flag, gun UTC), 5:00 timer with SYNC/STOP, gun closes start mode"
  - "Optional nav block 'start' (absent while closed) with timer, line, times to the line on both tacks, margins, tack_now, start zone ring"
  - "REST /api/start, /api/start/open, /api/start/ping, /api/start/line/{end}, /api/start/timer with events-log lines"
  - "Barre tab DÉPART button + start panel, TACK alert + beep, map overlay 'start' (zone, line, ends)"
  - "Setting start_tack_s (Départ : durée d'un virement (s), 10 s, 0-60)"
affects: [helm tablet, Réglages, events log, TABLET-SETUP, COMMISSIONING runbook]

actuals:
  tokens: 35600
  tasks: 3
  commits: 4
plan_head_before: 80da55798bf74b8c9256a47d0f6e1dec4bd80183

tech-stack:
  added: []
  patterns:
    - "Optional nav block added after the nav computation in its own try/except (NavService._add_start), key absent when inactive"
    - "Store write-then-commit with load_json_status .bak fallback (same as settings / manual wind)"
    - "Timer anchored on t_mono in memory, gun UTC from the trusted GPS clock persisted for restarts"

key-files:
  created:
    - src/jabuka/nav/start.py
    - src/jabuka/core/start_api.py
    - src/jabuka/web/static/start_logic.js
    - src/jabuka/web/static/start.js
    - tests/nav/test_start.py
    - tests/web/test_start_api.py
    - tests/test_start_logic.py
    - tests/ui/test_start_ui.py
  modified:
    - src/jabuka/core/nav_service.py
    - src/jabuka/core/web.py
    - src/jabuka/nav/settings.py
    - src/jabuka/web/static/app.js
    - src/jabuka/web/static/app.css
    - src/jabuka/web/static/i18n.js
    - src/jabuka/tools/i18n_review.py
    - docs/I18N-SL-REVIEW.md
    - docs/TABLET-SETUP.md
    - docs/COMMISSIONING.md
    - docs/COMMISSIONING-SL.md

key-decisions:
  - "Start-mode geometry helpers take headings and angles in degrees TRUE (the nav message's unit) rather than radians; distances in nm in a local frame centred on the line midpoint"
  - "Pinching above the polar beat angle counts as bearing away to it on the same tack; head to wind exactly = starboard"
  - "Course side = active mark's side of the line, else windward; the zone only uses polar velocities crossing towards it"
  - "Zone = convex hull of the line ends and A - T'v, B - T'v (5 deg heading steps), T' = remaining - start_tack_s; none when T' <= 0; drawn only while the timer runs"
  - "SYNC rounding to 0:00 fires the gun (via sync); the gun closes start mode even if the SD write fails"
  - "Timer started without trusted GPS UTC runs in memory (survives a reload, not a core restart) and records its gun UTC as soon as UTC is trusted"
  - "start_tack_s is the only tack cost of start mode; tack_penalty_s and routing are untouched (O-01)"

requirements-completed: [HELM-01, HELM-02, HELM-03, CRSE-05, DATA-07]

duration: 43min
completed: 2026-11-10
---

# Quick 261110-cuk: Mode départ (start timer, line ping, start zone) Summary

**Start mode on the helm tablet: a start line pinged from the boat's GPS (or typed in degrees + decimal minutes), a 5:00 timer with SYNC/STOP that lives on the Pi and survives a page reload, the time to the line on the current heading and on the other tack with signed margins, a TACK alert with a beep, and the start zone (a reverse isochrone from the line) on the map. At the gun start mode closes; routing, laylines and the closed-mode nav message are unchanged.**

## Performance

- **Duration:** 43 min
- **Started:** 2026-11-10T08:40:30Z
- **Completed:** 2026-11-10T09:23:10Z
- **Tasks:** 3 (Task 1 committed in two steps, core then tablet, as the plan checker allowed)
- **Files:** 8 created, 11 modified

## Accomplishments

- **Core (D-01, D-02, D-04, H-02):** `nav/start.py` StartStore (start.json + .bak; restored "bak" / "unreadable" shown in the start block only), timer (`gun_mono` in memory, `gun_utc` from trusted GPS UTC persisted, "clock" state after a restart without UTC), SYNC `floor(rem/60 + 0.5) * 60`, STOP, the gun closing start mode with one `gun` event carrying the boat position. Every change is a `{"type": "start", "action": ...}` events-log line (open, close, ping, typed, timer_start, sync, stop, gun).
- **REST:** `core/start_api.py` (GET /api/start; POST open / ping / timer; PUT line/{end}); 409 `no_position` / `no_timer`, 422 (strict bodies, out of area, unknown end), 503 on a write failure with nothing changed. Mutations return and publish the fresh nav message.
- **Isolation (H-01):** `NavService._add_start` runs after the nav computation in its own try/except (`start_errors`, never `errors`); a failure gives `{"open": true, "error": true}` and the rest of the message is byte-identical (test). Closed mode: no `start` key (tests/nav/test_nav_tracer.py unchanged). No file under route/, laylines.py, course.py or router_service.py changed; settings.py only gains `start_tack_s`.
- **Model (D-03a/b, H-03, O-01):** measured TWD/TWS, derated polar × efficiency_for, beat-angle clamp, other tack mirrored about TWD + `start_tack_s`, margins = remaining − time; `tack_now` when the other-tack margin is in (−10 s, 0] and it lays the segment; zone = convex hull of the backward polar velocities over T' = remaining − start_tack_s, towards the course side; reasons no_line > no_position > no_heading > no_wind > calc_error (geometry exception contained, timer intact).
- **Tablet:** `start_logic.js` (pure; fmtTimer, fmtSigned, remainingAt, startView, beepDue, startData, startLayers, coordErrorKey) and `start.js` (DÉPART button, panel, typed form reusing coord_logic checkPosition/formatDM, one request in flight, ignored while locked, every render in try/catch, Web Audio beep unlocked by a tap, map overlay "start"). Night colours red-only (theme vars; night layer colours g = b = 0).
- **Settings (O-01):** `start_tack_s` (« Départ : durée d'un virement (s) », default 10, 0–60) with fr/en/sl labels; Réglages renders it from the schema.
- **i18n (H-04):** start.* keys in fr/en/sl, SL marked for proofreading; docs/I18N-SL-REVIEW.md regenerated (new section "Start mode (Départ)").
- **Docs (H-05):** TABLET-SETUP §11 "Start mode — Mode départ" + night-before checklist line; COMMISSIONING §7 row 13:30 (dock drill) + the "ping at sea before the warning signal" sentence; COMMISSIONING-SL "## Start (DÉPART)" (4 lines, card 62 lines).

## Task Commits

1. **Task 1 (tracer), core:** `afc9dbe` feat(quick-261110-cuk): mode départ — ligne (ping/saisie) et chrono 5:00 sur le Pi, côté core (D-01, D-02, D-04)
2. **Task 1 (tracer), tablet:** `8c5fe4a` feat(quick-261110-cuk): mode départ — ligne (ping/saisie) et chrono 5:00 sur le Pi, tablette (D-01, D-02, D-04)
3. **Task 2:** `1025cb1` feat(quick-261110-cuk): mode départ — temps à la ligne, marges, alerte virement + bip, zone de départ, réglage start_tack_s (D-03, O-01)
4. **Task 3:** `a004a17` docs(quick-261110-cuk): mode départ — TABLET-SETUP §11, runbook §7, carte SL; tests nuit et mise en page

## Verification

- **Full gate `JABUKA_REQUIRE_UI=1 bash scripts/check.sh`: `check: ok`** (bootstrap, ruff check, ruff format --check, both suites).
  - `.venv`: **1989 passed, 4 skipped** (720.9 s); baseline 1915 passed (STATE.md).
  - `.venv313`: **1989 passed, 4 skipped** (701.4 s); baseline 1915 passed.
  - +74 vs the STATE.md baseline. This task adds 48 test functions (tests/nav/test_start.py 22, tests/web/test_start_api.py 10, tests/test_start_logic.py 12, tests/ui/test_start_ui.py 4); the other 26 were not attributed (tests added after the baseline was recorded, or parametrised existing tests). None of the 4 skips is in a start-mode test.
  - Note: in this environment `.venv` is Python 3.13.12 (not 3.14), see Deviations 1.
- Task verify commands (Tasks 1, 2, 3) each green before their commit; the start UI tests were run 3x in a row without a flake after the fix in Deviations 4.

- Tracer gate (Task 1): the `<verify>` command re-run end to end after the commit, green, before Task 2.
- TDD (Task 2): RED with stub functions (10 failing assertions in tests/nav/test_start.py: tack_headings, ray_to_line, course_normal, convex_hull, start_block keys, tack_now, reason, zone), then GREEN; test and implementation committed together per the plan's single Task 2 commit.

## Deviations from Plan

### Auto-fixed / adjusted

1. **[Rule 3 - Blocking] `.venv` was a bare Python 3.13 runtime venv without dev tools** (no ruff/pytest). Lint ran on `.venv313/bin/ruff` until Task 3, where `scripts/bootstrap-dev.sh` (run by check.sh) installed `[dev,prep]` into it. Both gate venvs are therefore Python 3.13.12 in this environment (bootstrap does not recreate an existing venv as 3.14).
2. **[Test adjustment] NaN body test sends `"NaN"` as a string** (as tests/web/test_manual_wind.py does): a raw JSON `NaN` literal makes FastAPI's default 422 handler fail to serialize (pre-existing, every endpoint) — logged in deferred-items.md, not fixed (out of scope).
3. **Units:** the start geometry helpers use degrees (plan text said radians for the geometry); headings in the nav message, the polar and the behaviour cases are degrees, so this avoids conversions. Documented in the module docstring.
4. **UI test:** the "remaining < 300 after reload" assertion was dropped (nav.last can still be the message computed at the 5:00 tap); the reload check is the plan's ±2 s comparison.

### Not done

- None of the plan's items were skipped.

## Claude's discretion (as decided in the plan, implemented)

- Pinching / head to wind: bear away to the beat angle on the same tack; head to wind = starboard.
- Course side: the active mark's side (nav mark block), else windward.
- Zone: VMG hull with tacks/gybes over T' = max(0, remaining − start_tack_s); none when T' <= 0; only while the timer runs; needs the line and the wind, not the position.
- SYNC to 0:00 fires the gun.
- Timer without trusted GPS UTC: memory only, gun UTC recorded once UTC is trusted.

## Open human UAT

- **Audible beep on the real Android tablet** (Chrome, plain-http origin): after one tap on the start panel, the TACK alert must beep (three short 1 kHz tones). Not verifiable headless.
- Night start check on the tablet: panel, zone and line red on black with no white/green light; panel leaves the boat visible on the map in landscape.

## Fingerprint note

The `src/jabuka` fingerprint changed with this quick task: the soak and code-freeze evidence (docs/SOAK.md, FREEZE) predates this code. docs/SOAK.md was not touched (H-07).

## Threat surface

All new surface is in the plan's threat model (T-cuk-01..07): unauthenticated start REST on the boat AP (accepted, same as course/settings), strict bodies, atomic start.json, isolated nav block, textContent only. No other new surface.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: src/jabuka/nav/start.py, src/jabuka/core/start_api.py, src/jabuka/web/static/start_logic.js, src/jabuka/web/static/start.js, tests/nav/test_start.py, tests/web/test_start_api.py, tests/test_start_logic.py, tests/ui/test_start_ui.py
- FOUND commits: afc9dbe, 8c5fe4a, 1025cb1, a004a17 (git rev-list --count 80da557..HEAD = 4)
