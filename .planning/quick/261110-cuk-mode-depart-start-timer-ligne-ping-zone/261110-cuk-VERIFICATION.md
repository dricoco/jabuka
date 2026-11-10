---
phase: quick-261110-cuk
verified: 2026-11-10T10:05:00Z
status: human_needed
score: 8/9 must-haves verified
covered_files:
  - ".planning/quick/261110-cuk-mode-depart-start-timer-ligne-ping-zone/261110-cuk-PLAN.md"
  - ".planning/quick/261110-cuk-mode-depart-start-timer-ligne-ping-zone/261110-cuk-SUMMARY.md"
  - "docs/COMMISSIONING-SL.md"
  - "docs/COMMISSIONING.md"
  - "docs/I18N-SL-REVIEW.md"
  - "docs/TABLET-SETUP.md"
  - "src/jabuka/core/nav_service.py"
  - "src/jabuka/core/start_api.py"
  - "src/jabuka/core/web.py"
  - "src/jabuka/nav/settings.py"
  - "src/jabuka/nav/start.py"
  - "src/jabuka/tools/i18n_review.py"
  - "src/jabuka/web/static/app.css"
  - "src/jabuka/web/static/app.js"
  - "src/jabuka/web/static/i18n.js"
  - "src/jabuka/web/static/start.js"
  - "src/jabuka/web/static/start_logic.js"
  - "tests/nav/test_start.py"
  - "tests/test_start_logic.py"
  - "tests/ui/test_start_ui.py"
  - "tests/web/test_start_api.py"
covered_digest: "v1:sha256:b981ee1466a9c9192431ea9b8f5976638664a653fa131125ade847590fe3f1d8"
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "When the other-tack margin reaches zero the panel turns into an inverted TACK alert and the tablet beeps once (no repeat within 10 s)"
    test: "On the real Android tablet (Chrome, http://10.42.0.1), open start mode, tap the panel once, then bring the other-tack margin into (-10 s, 0] (dock drill with a typed line and the simulator, or on the water)"
    expected: "Panel inverts with VIREZ POUR LA LIGNE and three short 1 kHz tones are audible once; no second beep within 10 s"
    why_human: "tack_now (Python) and beepDue rising edge (node) are tested, but no test calls start.js beep(); Web Audio unlock by gesture on Android cannot be exercised headless"
human_verification:
  - test: "Audible TACK beep on the real tablet after one tap on the start panel"
    expected: "Three short tones on the rising edge of the TACK alert; visual alert alone if audio is blocked"
    why_human: "Web Audio autoplay/gesture policy on the Android tablet; not observable in headless Chromium"
  - test: "Night mode on the real tablet with start mode open and the timer running (night start 13 Nov 20:00)"
    expected: "Panel, zone fill/edge, line and ends are red on black with no white or green light"
    why_human: "Playwright checks computed CSS colours (g = b = 0) and startLayers night colours, but not the physical screen / MapLibre rendering on the tablet"
  - test: "Landscape layout on the real tablet with start mode open"
    expected: "The start panel leaves the boat (map centre) visible and does not cover the helm column or the map controls"
    why_human: "Playwright layout checks at 1280x800 / 1024x600 / 600x1024 pass; the real tablet resolution and browser chrome are unknown"
---

# Quick 261110-cuk: Mode départ — Verification Report

**Goal:** Start mode on the helm tablet — pinged/typed start line persisted on the Pi, 5:00 timer with SYNC/STOP surviving a page reload, time to the line on both tacks with margins, TACK alert + beep, start zone on the map, gun closes start mode; routing untouched (H-01).
**Verified:** 2026-11-10
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | DÉPART opens start mode (state on the Pi, nav message); Ping comité / Ping bouée store GPS position; typed DM fallback via coord_logic; ends survive a core restart (start.json, .bak) | ✓ VERIFIED | `start.py` StartStore `_commit` write-then-memory, `load_json_status(... validate=)` with restored bak/unreadable; `start_api.py` ping reads `ctx.nav.state.latest(wind.POSITION)` (409 no_position), PUT line/{end} typed; `start.js` checkForm uses `checkPosition(..., RACE_AREA)`. Tests: test_round_trip, test_torn_file_falls_back_to_bak_then_defaults, test_restart_keeps_line_and_timer, test_start_mode_end_to_end, UI test_start_mode_ping_typed_timer_reload_close — all pass (run by verifier) |
| 2 | 5:00 countdown on the Pi survives a page reload (±2 s); SYNC rounds to nearest minute (<0:30 = gun); STOP; Fermer closes | ✓ VERIFIED | `start_timer` sets gun_mono + gun_utc; `sync` = floor(rem/60+0.5)*60, 0 → `_gun("sync")`; `stop` clears; `set_open(False)` clears timer. test_timer_sync_stop, test_sync_under_half_a_minute_is_the_gun, Playwright reload test asserts `abs(shown - server) <= 2.0` after `pg.reload()` — passed |
| 3 | Time to line on current heading and other tack (mirror about TWD, same TWA, beat clamp, + start_tack_s), margin = remaining − t; without inputs "—" and no zone, never an error | ✓ VERIFIED | `tack_headings`, `ray_to_line`, `_side`. Verifier's independent spot-check: TWD 0, hdg 45 → now (45, −45 port), other (315, +45); hdg 20 → clamped (40/320); hdg 0 → starboard (320, +40); TWD 161 hdg 200 (TWA −39) → (203, −42)/(119, +42). Boat 0.2 nm S of an E-W line, hdg 40, const 6 kn × 0.92: t_s 170.3 s (expected 170.27), other 180.3 (= +10 s), margins = 120 − t. ray: N → 0.2 nm on_line; 180 → None; parallel → None. Units deg/nm/kn/s consistent (`bearing_distance` rad → `math.degrees`, efficiency fraction 0.92). test_times_margins_and_zone recomputes independently; test_reason_precedence, test_no_wind_gives_a_reason_and_no_zone pass |
| 4 | While the timer runs the map shows a shrinking start zone (reverse isochrone, derated polar × efficiency, T' = remaining − start_tack_s, towards course side) | ✓ VERIFIED | `zone_ring`: hull of A, B, A − T'v, B − T'v for v·n > 0. Spot-check (6 kn, up 40°, TWD 0, T=300, tack 10 s): max y = 0.0 (pre-start side only), min y −0.3852 nm vs expected −0.3851. test_zone_ring_shape_and_size, test_zone_only_while_the_timer_runs_and_towards_the_mark, API span shrink check; Playwright test_start_zone_and_times_on_the_map confirms a Polygon in source "start-zone" |
| 5 | Réglages field start_tack_s (10 s, 0–60, −1/61 → 422) fr/en/sl; changes only other-tack time and zone; tack_penalty_s and routing untouched | ✓ VERIFIED | settings.py diff = 2 added lines only; `grep tack_penalty_s src/jabuka/nav/start.py` → none (only docstring mention). i18n SETTINGS_FR/EN/SL labels present. test_start_tack_s_setting (0/60 ok, −1/61 422 unchanged, tack_penalty_s 90 changes nothing), test_settings_file_without_start_tack_s_loads pass. `git diff 80da557 HEAD -- src/jabuka/route src/jabuka/nav/laylines.py src/jabuka/nav/course.py src/jabuka/core/router_service.py` is empty |
| 6 | Other-tack margin reaching zero → inverted TACK alert + one beep (no repeat within 10 s) | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | `tack_now()` window (−10, 0] + on_line tested (test_tack_now_window, test_tack_now_in_the_block); `beepDue` rising edge + 10 s gap tested (node); `start.js` toggles `.tack-now` and calls `beep()` (Web Audio, unlocked on pointerdown). No test exercises the actual sound — human item |
| 7 | At the gun the timer stops and start mode closes with an events-log line; every change is an events-log line | ✓ VERIFIED | `tick()` → `_gun("timer")` closes even if the write fails; `write_event` installed by `start_api.router` (fsync). test_the_gun_closes_start_mode_with_an_event (action gun, via timer, boat position, key gone), test_start_mode_end_to_end asserts actions `[open, ping, typed, timer_start, sync, stop, close]` with t_mono/t_wall/utc |
| 8 | Routing/laylines/FSM/nav fields unchanged; closed → no 'start' key; failure → {open: true, error: true}, never touches other blocks or the tick; start.js in try/catch | ✓ VERIFIED | nav_service diff: import, 2 attrs, one `_add_start` call after the existing try/except, `_add_start` with own try/except (`start_errors`, not `errors`); key only set when block not None. Inner `_geometry` try → calc_error. app.js `loadModule` try/catch; start.js `safeRender`/`safeMap`/timer interval each try/catch. test_closed_mode_has_no_start_key, tests/nav/test_nav_tracer.py, test_a_start_failure_never_touches_the_rest (patches `jabuka.core.nav_service.start_block` to raise; other blocks equal, errors unchanged, `tick_once()` runs) — pass |
| 9 | fr/en/sl strings complete; review sheet regenerated; panel red-only at night; TABLET-SETUP §11; gate green on both venvs | ✓ VERIFIED | 34 `start.*` keys in each of FR/EN/SL; docs/I18N-SL-REVIEW.md has the "Start mode (Départ)" section; tests/test_i18n.py passes; Playwright test_start_panel_night_is_red_only and test_start_panel_layout pass; TABLET-SETUP "## 11. Start mode — Mode départ" + night-before checklist line; COMMISSIONING §7 13:30 row; COMMISSIONING-SL "## Start (DÉPART)" (card 62 lines). Full gate not re-run by the verifier (per instructions); targeted suites green on both venvs |

**Score:** 8/9 truths verified (1 present, behavior-unverified)

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/jabuka/nav/start.py` | ✓ VERIFIED | 584 lines; `def start_block`, StartStore, geometry; used by nav_service |
| `src/jabuka/core/start_api.py` | ✓ VERIFIED | `def router`; all 5 routes; included in web.py |
| `src/jabuka/core/nav_service.py` | ✓ VERIFIED | `_add_start` present and called in `update()` |
| `src/jabuka/nav/settings.py` | ✓ VERIFIED | `start_tack_s` (10.0, ge 0, le 60) |
| `src/jabuka/web/static/start_logic.js` | ✓ VERIFIED | `export function startView` + beepDue/startData/startLayers |
| `src/jabuka/web/static/start.js` | ✓ VERIFIED | `export function mount`; loaded from app.js MODULES |
| tests (4 files) | ✓ VERIFIED | 22 + 10 + 12 + 4 tests, all pass |
| `docs/TABLET-SETUP.md` | ✓ VERIFIED | §11 "Mode départ" |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| nav_service.py | start.py | `start_block(self.start, msg, self.polar, self.settings, t_mono, utc_epoch(self.clock))` | WIRED |
| start.py | settings.py | `settings.start_tack_s` in `_geometry` (other tack) and `zone_ring` (T'); no `tack_penalty_s` read | WIRED |
| settings.py | i18n.js | `start_tack_s` in SETTINGS_FR/EN/SL; test_i18n green | WIRED |
| web.py | start_api.py | `app.include_router(start_api.router(ctx))` before static mount | WIRED |
| start_api.py | start.py | `store.on_event = write_event`; every mutation → `fresh_nav()` → `ctx.publish_nav()` | WIRED |
| app.js | start.js | `["start", "./start.js", "tab-barre"]` | WIRED |
| start.js | coord_logic.js | `checkPosition`, `formatDM`, `RACE_AREA` | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| start panel (#start-timer, #start-now/#start-other) | `nav.start` | NavService.update → start_block (StartStore + msg boat/wind/mark + polar) → WS/REST nav | Yes (Playwright shows a time and Polygon from live simulator feed) | ✓ FLOWING |
| map overlay "start" | `startData(nav.start)` | zone ring from `zone_ring` | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Start unit/API/node + isolation/i18n/settings/runbook/no-wallclock | `.venv313/bin/pytest tests/nav/test_start.py tests/web/test_start_api.py tests/test_start_logic.py tests/nav/test_nav_tracer.py tests/test_i18n.py tests/nav/test_settings_core.py tests/commissioning/test_runbook_docs.py tests/test_no_wallclock.py` | 91 passed | ✓ PASS |
| Same core start tests on second venv | `.venv/bin/python -m pytest tests/nav/test_start.py tests/web/test_start_api.py tests/test_start_logic.py tests/nav/test_settings_core.py` | 55 passed | ✓ PASS |
| Playwright start UI (reload ±2 s, zone Polygon, layout, night) | `JABUKA_REQUIRE_UI=1 .venv313/bin/pytest tests/ui/test_start_ui.py` | 4 passed (20 s) | ✓ PASS |
| Geometry sanity (independent script) | scratchpad chk.py vs start.py | tack mirror, ray distance, zone extent, t_s all match hand calc | ✓ PASS |
| Ruff on new Python files | `.venv313/bin/ruff check ...` | All checks passed | ✓ PASS |

### Probe Execution

Not applicable (no probes declared).

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| HELM-01/02/03 | ✓ SATISFIED | panel on Barre tab, night red-only test, helm untouched |
| CRSE-05 | ✓ SATISFIED | line ends persisted like the course (start.json + .bak) |
| DATA-07 | ✓ SATISFIED | events-log lines for every start action |

### Repo-rule checks (H-07)

- `git diff 80da557 HEAD -- cad stl hardware docs/SOAK.md .planning/` → empty.
- `docs/I18N-SL-REVIEW.md.bak` untracked, not committed.
- All 4 commits carry `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- app.css: additions only (no existing helm rule changed).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (new start files) | — | TBD/FIXME/XXX/TODO | none found | — |
| `src/jabuka/nav/start.py` | 305-320 | `ray_to_line` does not check crossing direction: a boat already on the course side (OCS) heading back gets a time to the line | ℹ️ Info | Model limitation, arguably useful (time to return); not in the contract |
| `src/jabuka/nav/start.py` | 292-302 | A boat reaching/running away from the line shows "—" on both rows (mirror about TWD of a heading away is also away) | ℹ️ Info | Documented simple model (H-03) |
| deferred-items.md | — | Raw JSON `NaN` body → 500 instead of 422 (pre-existing, app-wide) | ℹ️ Info | Out of scope; logged by executor |
| environment | — | Both gate venvs are Python 3.13.12 (`.venv` not 3.14) | ℹ️ Info | Gate coverage of 3.14 not demonstrated in this environment |
| — | — | src/jabuka fingerprint changed after code freeze; soak evidence predates this code | ℹ️ Info | Owner decision D-05; SOAK.md untouched |

### Human Verification Required

1. **Audible TACK beep** — on the real tablet, tap the start panel once, then trigger the TACK alert. Expected: three short tones once, no repeat within 10 s. Why human: Web Audio gesture unlock on Android is not testable headless; no test calls `beep()`.
2. **Night colours on the tablet** — night mode with start mode open and the timer running. Expected: panel, zone, line, ends red on black only. Why human: physical display and MapLibre rendering on the real device.
3. **Landscape layout on the tablet** — Expected: panel leaves the boat visible and clear of the helm column and map controls. Why human: real device resolution unknown (Playwright layout checks pass at 3 sizes).

### Gaps Summary

No gaps. All code-level must-haves are present, wired and exercised by passing tests (verifier ran the unit, API, node and Playwright suites; independent geometry spot-check matches). The router, laylines, course FSM and router_service are byte-identical to 80da557. Remaining items are device-level checks (beep audio, night rendering, landscape layout) on the real tablet, as the plan itself deferred to end of phase.

---

_Verified: 2026-11-10_
_Verifier: Claude (gsd-verifier)_
