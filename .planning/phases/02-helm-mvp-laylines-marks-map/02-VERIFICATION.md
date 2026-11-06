---
phase: 02-helm-mvp-laylines-marks-map
verified: 2026-11-06T18:36:43Z
status: gaps_found
score: 28/34 must-haves verified (2 FAILED, one of them with an override suggested; 2 tablet-only, routed to human verification; 2 restatements of the override item)
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-01-PLAN.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-01-SUMMARY.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-02-PLAN.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-02-SUMMARY.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-03-PLAN.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-03-SUMMARY.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-04-PLAN.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-04-SUMMARY.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-05-PLAN.md", ".planning/phases/02-helm-mvp-laylines-marks-map/02-05-SUMMARY.md", "deploy/requirements.in", "deploy/requirements.lock", "docs/RACE-PACK.md", "docs/TABLET-SETUP.md", "pyproject.toml", "scripts/bootstrap-dev.sh", "scripts/build-styles.mjs", "scripts/vendor-web.sh", "src/jabuka/common/clock.py", "src/jabuka/core/course_api.py", "src/jabuka/core/hardening.py", "src/jabuka/core/main.py", "src/jabuka/core/nav_api.py", "src/jabuka/core/nav_service.py", "src/jabuka/core/tiles.py", "src/jabuka/core/web.py", "src/jabuka/nav/__init__.py", "src/jabuka/nav/course.py", "src/jabuka/nav/data/marks.json", "src/jabuka/nav/data/x35-orc-od-2019.exp", "src/jabuka/nav/geo.py", "src/jabuka/nav/laylines.py", "src/jabuka/nav/polar.py", "src/jabuka/nav/settings.py", "src/jabuka/nav/tacks.py", "src/jabuka/nav/wind.py", "src/jabuka/prep/__init__.py", "src/jabuka/prep/map.py", "src/jabuka/prep/polar.py", "src/jabuka/sim/synth.py", "src/jabuka/web/static/app.css", "src/jabuka/web/static/app.js", "src/jabuka/web/static/carte.css", "src/jabuka/web/static/carte.js", "src/jabuka/web/static/diag.html", "src/jabuka/web/static/diag_logic.js", "src/jabuka/web/static/helm.js", "src/jabuka/web/static/helm_logic.js", "src/jabuka/web/static/index.html", "src/jabuka/web/static/lock-early.js", "src/jabuka/web/static/lock.js", "src/jabuka/web/static/lock_logic.js", "src/jabuka/web/static/map.js", "src/jabuka/web/static/overlays.js", "src/jabuka/web/static/reglages.css", "src/jabuka/web/static/reglages.js", "src/jabuka/web/static/style-day.json", "src/jabuka/web/static/style-night.json", "src/jabuka/web/static/wakelock.js"]
covered_digest: "v1:sha256:89cf91caacbc33fb1606f49a2aacecb4f7046bcd5c04fbe439e7a5afe10481f2"
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "ROADMAP SC2 / NAV-02: live laylines with distance/time to the layline, an overstood indicator and the heading on the other tack"
    status: partial
    reason: "The server computes layline.dist_nm (nav_service -> laylines.solve, src/jabuka/nav/laylines.py:366), but no browser file reads it. The helm shows only the time ('Virement dans 12 min'), DÉPASSÉE and 'Autre bord'. The distance to the layline is not shown on any tab, Diag included: _write_back publishes nav.layline.countdown only."
    artifacts:
      - path: "src/jabuka/web/static/helm_logic.js"
        issue: "fmtCountdown()/helmView() ignore layline.dist_nm; `grep dist_nm src/jabuka/web/static/*.js` finds nothing"
      - path: "src/jabuka/web/static/helm.js"
        issue: "#helm-countdown renders the time text only"
    missing:
      - "Show the layline distance next to the countdown, e.g. 'Virement dans 12 min · 1,4 nm' through fmtDistance(layline.dist_nm), in helmView()"
      - "Add a node test in tests/test_helm_logic.py: a normal-state layline with dist_nm shows the distance; overstood/fetching/reach states do not"
  - truth: "ROADMAP SC3 / CRSE-01: the user selects Course A or Course B in one action (also 02-01 truth 4 and 02-04 truth 2: 'in one tap')"
    status: partial
    reason: "The review fix WR-05 (23e861e) made changing the template take two taps. The first tap turns the button into 'Confirmer Parcours B' for 5 s, and a second tap selects (src/jabuka/web/static/carte.js:311-340). Re-selecting the active template is a no-op. This is intentional, because a template change rebuilds the course and drops custom marks. It still breaks the literal 'one action / one tap' wording."
    artifacts:
      - path: "src/jabuka/web/static/carte.js"
        issue: "tplReset/confirm flow: a template change needs a confirming second tap within 5 s"
    missing:
      - "Owner decision: accept the confirm tap as one action (add the override suggested in the report body), or restore a single tap with a different safeguard (for example the Annuler banner pattern)"
human_verification:
  - test: "Real tablet, airplane mode with Wi-Fi to the Pi AP, open http://10.42.0.1 (TABLET-SETUP 1, 5) with the race pack copied to /var/lib/jabuka/racepack"
    expected: "The MapLibre map renders Vodice to Jabuka at every zoom up to 14 with labels, seamarks, the course, marks with radius circles, laylines and the boat; zero network errors in chrome://inspect; the Barre bands sit over the map"
    why_human: "Real Android WebGL/GPU and Pi-served tiles; headless Chromium (SwiftShader) is not the tablet (HELM-01, SC1)"
  - test: "Screen awake: with the Chrome flag unsafely-treat-insecure-origin-as-secure=http://10.42.0.1, tap once, then leave the tablet on the charger for at least 2 h (ideally overnight); repeat once without the flag"
    expected: "With the flag the badge reads 'verrou'; without it, 'vidéo'. The screen never sleeps, and coming back from another app re-acquires the lock"
    why_human: "Wake Lock / NoSleep behaviour only exists on the real browser and OS power manager (HELM-04, SC5)"
  - test: "Night readability: in a dark room or on deck at night, switch to Nuit, set the brightness slider, go through Barre/Carte/Réglages/Diag, open a sheet and the keyboard, rotate course-up"
    expected: "Only red on true black, nothing white or blue (status bar hidden by fullscreen, MapLibre controls, sprites, dialogs). Primary number readable from the helm, night vision kept after 5 min of use"
    why_human: "Perceived brightness and night-vision effect cannot be measured by a pixel test (HELM-03, SC5)"
  - test: "Lock mode in spray and rain: lock, spray water and drag wet fingers, a palm and two fingers across the screen, then long-press the padlock for 2 s; reload the page while locked"
    expected: "Nothing reacts while locked (no tab change, map pan or button press). A press of 2 s or more on the padlock unlocks it; a shorter or two-finger press does not. After a reload the lock is still on before the map loads"
    why_human: "Real capacitive touch with water produces ghost touches no synthetic event reproduces (HELM-04, SC5)"
  - test: "Real X35 polar: convert the owner's file with `jabuka-prep-polar FILE --out var/racepack/polar.json`, copy the pack to the Pi, and check the Réglages/Diag polar name and the printed target table"
    expected: "Target TWA/BSP per TWS match the owner's numbers; efficiency (default 0.92) applied on the helm's target BSP and % polar. Until then the interim ORC X-35 OD 2019 polar is in use"
    why_human: "The owner's polar file is not in the repo (WIND-01, CONTEXT)"
  - test: "Rounding sides, radii and the start/finish against the Sailing Instructions (13 Nov briefing): Carte tab, Course A and Course B"
    expected: "Each mark's side (bâbord/tribord) and radius match the SIs; Vodice start/finish moved to the real line (the shipped 43.7500N 15.7800E is a placeholder); then 'Côtés confirmés' clears the 'Côtés à confirmer (IC)' warning"
    why_human: "The SIs are not published yet; marks.json has sides_confirmed false (CRSE-01/02)"
  - test: "CR-03 helm UX: in the sim (`jabuka-sim --follow`) or on the water, sail a beat leg, bear away to a reach, round a leeward mark onto a beat, and fetch the mark"
    expected: "On a beat the big number is TWA CIBLE ↑ (never ↓). When reaching across a beat leg it reads CAP À SUIVRE equal to the current tack's close-hauled heading, never the bearing into the wind. When fetching, the fetch CTS. The helmsman finds the switch clear"
    why_human: "The rule is unit-tested (tests/nav/test_laylines.py::test_beat_leg_*); whether it reads clearly at the helm is a UX judgement (review CR-03 note)"
  - test: "On the boat with the live bus (12 Nov): compare Barre/Diag TWD/TWS/TWA with the B&G displays, sail one tack each way, then enter a manual TWD/TWS (°M) with the bus disconnected"
    expected: "Source LIVE, with the computed-vs-B&G difference under 10° on Diag (otherwise adjust heading offset / AWA sign / variation 4.7°E). Laylines plausible on both tacks. With the bus off the badge goes MANUEL and laylines keep updating; set/drift stays off until compass and log are checked"
    why_human: "Real Hercules data and sensor calibration (WIND-03/04, NAV-03)"
  - test: "Power cut on the Pi during the race: edit the course (add a mark, Finir ici), change a setting, enter manual wind, then pull the power and reboot"
    expected: "Course, active mark, finish point, settings and manual wind come back identical; no 'illisible' alert"
    why_human: "Real SD-card power loss on the Pi (CRSE-05); kill -9 is tested in software"
  - test: "Review deploy/requirements.lock package names before reinstalling the Pi wheelhouse"
    expected: "19 canonical projects: the Phase 1 17 plus pmtiles (Phase 2 tile server) and numpy (Phase 3 router)"
    why_human: "Supply-chain judgement (CONTEXT package-legitimacy policy)"
---

# Phase 2: Helm MVP — Laylines, Marks & Map Verification Report

**Phase Goal:** The helmsman can race to the next mark on laylines alone. A night-readable tablet helm view over an offline map shows polar targets, live laylines and the course, using live instrument wind or manually entered wind. This is the guaranteed fallback if routing never ships.
**Verified:** 2026-11-06T18:36:43Z (master 7730f51)
**Status:** gaps_found
**Re-verification:** No, initial verification

The layline fallback works end to end in software. A simulated boat steered by the core's own targets beats to Plić Sestre, tacks on the layline, rounds the mark and advances to Jabuka (`tests/sim/test_closed_loop.py`). Two gaps remain, both against the literal ROADMAP wording:

1. The **distance to the layline** is computed but never displayed.
2. **Course A/B selection** takes a confirming second tap since review fix WR-05. That change looks intentional, so an override is suggested.

Everything else the laptop can check is present, wired and tested. Tablet and boat checks are listed under Human Verification.

## User Flow Coverage (MVP mode)

The ROADMAP `**Goal:**` line is not in user-story form. 02-01-PLAN.md restates it, and that version passes `user-story.validate` (valid=true): "As the helmsman of the X35 ..., I want to race to the next mark on laylines alone, with polar targets, live laylines and the course on a night-readable tablet helm view over an offline map, from live or manually entered wind, so that I have a guaranteed 'steer this / tack here' even if routing never ships."

| Step | Expected | Evidence in codebase | Status |
| --- | --- | --- | --- |
| Open the app | Tablet loads http://10.42.0.1 offline: Barre tab over a race-area map | index.html app shell; vendored MapLibre 5.24.0 UMD + glyphs/sprites; tiles.py serves var/racepack (spot check: z14 Šibenik tile 200 gzip); test_map_renders_offline_with_overlays (no external request, no HTTP ≥ 400) | ✓ (real tablet: human) |
| Pick the course | Course A or B, active mark Plić Sestre | marks.json templates; course_api `/api/course/select`; carte.js A/B buttons | ⚠ two taps for a change (WR-05), see gap 2 |
| Get wind | LIVE from instruments, or MANUEL typed from the B&G | wind.py arbitration LIVE > LIVE_BG > MANUEL > GRIB > NONE; reglages.js → POST /api/wind/manual; test_manual_wind_keeps_laylines_alive | ✓ |
| Steer | Big primary number by point of sail, deviation + hint, target BSP / % polar | laylines.select_primary + CR-03 leg rule; helm_logic.primaryView/deviationView; test_bands_sizes_and_numbers (≥ 20% vh) | ✓ |
| Tack here | Laylines on the map, "Virement dans N min", DÉPASSÉE, Autre bord | laylines.solve countdown/overstood/other_tack_hdg_t; overlays.js helm-laylines-*; fmtCountdown | ⚠ time shown, distance to layline not shown (gap 1) |
| Round the mark | Auto-advance + banner "Marque suivante — Annuler" | course.py FSM; carte.js #banner; test_closed_loop_beats_tacks_rounds_and_advances, test_advance_banner_on_the_helm_and_annuler | ✓ |
| Outcome | "A guaranteed steer-this / tack-here even if routing never ships" | Nav runs in the core tick independent of the router (main.update_nav before route_nav; router failures caught) | ✓ in software, ⚠ the two gaps above |

## Goal Achievement

### Observable Truths

ROADMAP success criteria (contract):

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| SC1 | Offline helm view: map with boat, marks and course behind big numbers. Primary number by point of sail, plus deviation, target BSP, % polar (polar × efficiency), DTW/TTW and the layline countdown | ✓ VERIFIED (software) | nav_service polar × `efficiency_for`; laylines.select_primary + CR-03 (tests `test_beat_leg_*`, `test_run_leg_*`); helm_logic.helmView; UI tests test_bands_sizes_and_numbers and test_map_renders_offline_with_overlays. Real tablet WebGL and CR-03 UX are human items |
| SC2 | Port/stbd laylines at ~1 Hz with distance/time to the layline, overstood, other-tack heading; polar/sailed toggle; set/drift opt-in (off by default) | ✗ FAILED (partial) | Laylines are published every tick (main.tick_once → nav.update); `layline_source` polar/sailed (test_sailed_*); `use_current` default False (settings.py:48) and ignored in the zone (test_current_ignored_in_the_jabuka_zone); DÉPASSÉE (fmtCountdown) and "Autre bord" are rendered. **The distance to the layline (`layline.dist_nm`) is never rendered**: no static JS reads it |
| SC3 | A/B in one action; add/move/delete marks by tapping, side + radius, reorder; auto-advance with banner + undo; next/prev; shorten/finish in one action; course + settings survive a reboot | ✗ FAILED (one clause, override suggested) | Everything except "one action" is verified: test_tap_adds_a_mark_and_land_tap_warns, test_drag_a_mark_sends_one_patch, test_mark_sheet_side_reorder_finish_delete_and_course_b, test_closed_loop, test_advance_banner_on_the_helm_and_annuler, test_kill9_during_edits_never_loses_the_course, test_manual_wind_survives_a_restart. **A/B change needs a confirm tap** (carte.js:311-340, WR-05) |
| SC4 | All directions TRUE with variation (~+5°E) and heading offset; true wind computed and damped; manual TWD/TWS with LIVE/MANUAL badge; Jabuka radius → heading untrusted, COG used | ✓ VERIFIED | wind.heading_true (offset, then var 4.7°E; unknown ref = M); VectorEma τ 10 s / 60 s, wrap-safe (test_vector_ema_wrap_safe, test_damping_helm_and_layline_taus); sourceBadge LIVE / LIVE B&G / MANUEL / PÉRIMÉ; zone 3 nm around Jabuka → COG, CAP NON FIABLE (test_jabuka_zone_uses_cog, test_gps_dropout_in_the_zone_keeps_the_compass_untrusted). The bias freeze half of WIND-07 is in route/bias.py `_gate` REASON_ZONE (Phase 3, tested) |
| SC5 | Night true-black/red without spoiling night vision; lock mode ignores spray/rain; screen stays awake all race | ? UNCERTAIN → human | Software verified: style-night.json has only pure-red colours (9 colours, G = B = 0, checked), test_night_toggle_is_red_only_and_persists, test_lock_swallows_everything_and_unlocks_on_a_long_press, test_stored_lock_covers_the_screen_before_the_modules_load, test_wake_lock_on_a_secure_origin / falls_back_to_the_nosleep_video / rejected_is_an_alert. The physical outcome (night vision, wet touches, a 36 h awake screen) needs the tablet |

Plan must-haves (merged, deduplicated against the SCs where a plan restates one):

| Plan | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 02-01 | 1 Hz nav WS message with target TWA/BSP × efficiency, % polar, active mark Plić Sestre, DTW/TTW, laylines + countdown | ✓ VERIFIED | test_nav_tracer.py, test_tracer_e2e.py; spot check `/api/nav` keys |
| 02-01 | Barre tab formats the primary number, deviation, target BSP / %, DTW/TTW, "Virement dans N min" from the server message only | ✓ VERIFIED | helm_logic.js is pure; tests/test_helm_logic.py (node) |
| 02-01 | Every direction TRUE at one boundary, unknown ref treated as magnetic | ✓ VERIFIED | wind.heading_true; test_heading_true_boundary |
| 02-01 | A/B in one tap on Carte, next/prev, persisted in course.json across restart | ✗ FAILED (same root cause as SC3, override suggested) | next/prev/persistence verified (test_new_core_context_reproduces_the_course); the A/B switch is two taps |
| 02-01 | Settings: schema-driven form, atomic settings.json, 409 on stale base_version, survives restart | ✓ VERIFIED | settings.py SettingsStore; test_api_seams.py; tests/ui/test_reglages.py |
| 02-01 | Offline vector tiles via index built once; MapLibre 5.24.0 offline, zero external requests, overlays drawn | ✓ VERIFIED | web.py `include_router(racepack_router(ctx))`; vendor/maplibre-gl.js header v5.24.0; test_map_renders_offline_with_overlays; spot check on real var/racepack |
| 02-01 | Diag still at /diag.html, race-pack state in health | ✓ VERIFIED | spot check `/diag.html` 200; main.record_racepack_health |
| 02-02 | `jabuka-prep-map` builds race.pmtiles (bbox, z14, latest Protomaps build) + seamarks + coastline + manifest with sha256 | ✓ VERIFIED | var/racepack built 2026-11-06T03:26Z from build 20261105: 6190 tiles z0-14, 1058 seamarks, 445 coastline features; `jabuka-prep-map --check var/racepack` exit 0 (run here) |
| 02-02 | Core serves the built pack: /racepack/info tiles true, z14 Šibenik tile 200 | ✓ VERIFIED | in-process spot check: info `tiles: True, maxzoom 14`; `/tiles/14/…` 200 gzip 53 604 B |
| 02-02 | `--check` rejects wrong tile type/compression, hash mismatch, seamark outside the bbox | ✓ VERIFIED | tests/prep/test_prep_map.py (passed) |
| 02-02 | Fallback z12 → z10 → coastline-only pack | ✓ VERIFIED | tests/prep/test_prep_map.py; WR-06 overzoom from /racepack/info (test_style_maxzoom_follows_a_degraded_pack) |
| 02-02 | `jabuka-prep-polar` converts grid / Expedition / ORC CSV / JSON → polar.json and prints the target table | ✓ VERIFIED | test_prep_polar.py; spot check on tests/fixtures/polar/expedition.txt, exit 0 |
| 02-03 | Manual wind (°M default or °T): laylines keep working as MANUEL; LIVE returns; the entry stays stored | ✓ VERIFIED | test_manual_wind_keeps_laylines_alive, test_live_wins_then_manual_returns_when_the_bus_goes_stale |
| 02-03 | Computed true wind at one boundary with leeway, vector damping τ 10/60 s, B&G fallback/setting, cross-check alert > 10° for > 60 s on Diag | ✓ VERIFIED | test_wind.py (leeway, taus, live_bg, cross_check_alert_after_60_s, cross_check_rows_reach_diag) |
| 02-03 | In the Jabuka radius: heading untrusted, COG used, Hercules TWD and set ignored | ✓ VERIFIED | wind.py zone branch (dir_i None in zone); nav_service._current_kn; test_jabuka_zone_uses_cog, test_nav_service_current_ignored_in_the_zone |
| 02-03 | Polar (× eff on speed only) or sailed angles; set/drift only when enabled and never twice; track-based countdown, overstood time, fetching + CTS | ✓ VERIFIED | test_laylines.py (sailed_mode_never_adds_the_current, countdown_follows_the_actual_track, overstood_time, fetching_gives_the_course_to_steer) |
| 02-03 | Settings and manual wind survive a restart | ✓ VERIFIED | test_manual_wind_survives_a_restart; test_api_seams persistence |
| 02-04 | Carte: tap to add (with the "Marque à terre ?" land warning), drag to move, sheet for side/radius/rename/up-down/delete/Finir ici | ✓ VERIFIED | carte.js; tests/ui/test_carte.py (3 tests) |
| 02-04 | A/B in one tap; next/prev or set active | ✗ FAILED (same root cause, override suggested) | activate/next/prev verified (`/api/course/activate`, `/next`, `/prev` with base_version); A/B is two taps |
| 02-04 | Auto-advance after 10 s rounding evidence, banner on every tablet for 60 s, Annuler without re-firing until the boat leaves the zone | ✓ VERIFIED | course.py `_fsm` / `_advance` / `undo`; test_course.py incl. the CR-02 and WR-01 hairpin cases; UI Annuler test |
| 02-04 | Course, active mark, finish point and a pending advance survive restart and kill -9 | ✓ VERIFIED | test_pending_advance_banner_survives_a_restart, test_kill9_during_edits_never_loses_the_course |
| 02-04 | Closed-loop sim beats to Plić Sestre, tacks at the layline, rounds, advances to Jabuka | ✓ VERIFIED | test_closed_loop_beats_tacks_rounds_and_advances (passed) |
| 02-04 | Concurrent edits: stale base_version → 409 + refetch | ✓ VERIFIED | test_course_api.py; test_stale_tablet_gets_409_and_reloads |
| 02-05 | Night: whole helm view black + red only, persisted per tablet | ✓ VERIFIED (software) | test_night_toggle_is_red_only_and_persists, test_night_style_file_has_no_icons_and_only_red, WR-04 double-tap test; perception is folded into SC5's human item |
| 02-05 | Map shows boat + heading, the whole course, marks + radius circles, laylines, seamarks | ✓ VERIFIED | overlays.js (course/marks/circleRing/helm-laylines/boat/helm-heading/seamarks from /racepack/seamarks.geojson); test_map_renders_offline_with_overlays, test_overlays_survive_theme_switches_and_carte_tab |
| 02-05 | Primary number ≥ 20% height with deviation and hint; target BSP vs BSP, %, DTW/TTW, countdown, other-tack heading °M/°T, source badge, CAP NON FIABLE on one screen | ✓ VERIFIED | app.css `#primary` max(18.5vh, min(22vh, 26vw)), with the box asserted ≥ 20% vh in test_bands_sizes_and_numbers; helmFlags |
| 02-05 | No data for 3 s → numbers grey + PERTE DONNÉES | ✓ VERIFIED | app.js watchdog + helm.setStale; test_frozen_numbers_turn_grey_when_the_core_dies |
| 02-05 | Lock ignores spray, rain and multi-finger touches; unlock only by a 2 s press on the padlock | ✓ VERIFIED (software) | lock_logic.createLongPress (test_lock_logic.py); test_lock_swallows_everything_and_unlocks_on_a_long_press. Wet-screen behaviour is the SC5 human item |
| 02-05 | Screen stays awake: Wake Lock with the flag, looping video otherwise, badge, documented setup | ? UNCERTAIN → human | wakelock.js keepAwake/visibilitychange re-acquire; 3 UI tests with mocked APIs; docs/TABLET-SETUP.md (122 lines). Staying awake for the race needs the tablet |

**Score:** 28/34 truths verified, with 0 present but behaviour-unverified.

- The 34 truths are 5 ROADMAP SCs plus 29 plan truths.
- FAILED (4 truths, 2 root causes):
  - SC2: the distance to the layline is not displayed.
  - SC3, 02-01 #4 and 02-04 #2: the A/B confirm tap. An override is suggested for this one.
- UNCERTAIN, routed to human verification (2): SC5 and the 02-05 wake truth.
- Every behaviour-dependent truth has a named test that passed in this run: rounding FSM, Annuler suppression, kill -9 persistence, damping/reset, source hold, stale grey-out, long-press unlock and the closed loop.

### Override suggestion (gap 2)

**This looks intentional.** Review fix WR-05 added the confirm tap so that one stray tap cannot rebuild the course mid-race and drop custom marks. If the owner accepts that as "one action", add this to this file's frontmatter. The next verification will then carry SC3, 02-01 truth 4 and 02-04 truth 2 as PASSED (override):

```yaml
overrides:
  - must_have: "The user can select Course A or Course B in one action"
    reason: "WR-05: a template change rebuilds the course, so it takes a 'Confirmer Parcours X' tap within 5 s; re-selecting the active course is a no-op. One deliberate action with confirmation."
    accepted_by: "<owner>"
    accepted_at: "<ISO timestamp>"
```

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/jabuka/core/nav_service.py` | NavService, nav message | ✓ VERIFIED | 301 lines; called from `CoreContext.update_nav` every tick and after each REST change |
| `src/jabuka/nav/polar.py` + `data/x35-orc-od-2019.exp` | Polar, parsers, interim X35 polar | ✓ VERIFIED | ORC X-35 OD 2019 derived, attributed, labelled INTERIM |
| `src/jabuka/nav/wind.py` | WindPipeline, VectorEma, heading_true | ✓ VERIFIED | 388 lines |
| `src/jabuka/nav/laylines.py` | solve, select_primary | ✓ VERIFIED | 379 lines, CR-03 leg rule |
| `src/jabuka/nav/tacks.py` | TackTracker | ✓ VERIFIED | Wired: nav_service `self.tacks.update`, `angles()` in sailed mode |
| `src/jabuka/nav/course.py` + `data/marks.json` | CourseStore, FSM, A/B templates | ✓ VERIFIED | 862 lines; 5 marks from OSM; sides provisional (`sides_confirmed: false`) |
| `src/jabuka/nav/settings.py` | Settings, SettingsStore, ManualWindStore | ✓ VERIFIED | Defaults: var 4.7°E, eff 0.92, use_current False, zone 3 nm |
| `src/jabuka/core/{nav_api,course_api,tiles,hardening}.py` | REST + tiles | ✓ VERIFIED | All routers included in web.py before the static mount |
| `src/jabuka/prep/{map,polar}.py` | Race-pack and polar CLIs | ✓ VERIFIED | Both CLIs ran here |
| `src/jabuka/sim/synth.py` (--follow) | Closed-loop L2 boat | ✓ VERIFIED | test_closed_loop |
| `src/jabuka/web/static/*` (app, helm, helm_logic, carte, reglages, map, overlays, lock, lock_logic, lock-early, wakelock, styles) | Tablet SPA | ✓ VERIFIED | Wired from index.html / app.js; vendored maplibre-gl 5.24.0 + NoSleep 0.12.0 with integrity in VENDOR.md |
| `docs/RACE-PACK.md`, `docs/TABLET-SETUP.md` | Runbooks | ✓ VERIFIED | 148 and 122 lines |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| core/main.py | nav_service.py | `tick_once` → `update_nav` → `self.nav.update()` before the diag message; `hub.publish(nav_text)` | ✓ WIRED |
| core/web.py | tiles.py | `app.include_router(racepack_router(ctx))` before `app.mount("/")` | ✓ WIRED |
| app.js | /ws | WebSocket nav dispatch; course_version/settings_version refetch | ✓ WIRED |
| map.js | /style-day.json, /style-night.json | absolutizeStyle + setTheme (serialized, WR-04) | ✓ WIRED |
| nav_service.py | state.py | `state.latest(p)` inputs; `_write_back` nav.* rows (src nav) | ✓ WIRED |
| reglages.js | /api/wind/manual | POST {twd, tws_kn, ref} / DELETE | ✓ WIRED |
| nav_service.py | tacks.py | `TackTracker.update` every tick; `angles()` when layline_source = sailed | ✓ WIRED |
| wind.py | common/conventions.py | `true_wind_from_apparent`, `mag_to_true`, `apply_heading_offset` | ✓ WIRED |
| carte.js | /api/marks, map.js | POST on tap, PATCH on drag end; `registerOverlay('carte')`; `queryRenderedFeatures` on `earth` | ✓ WIRED |
| course.py | course.json | `atomic_write_json` in `_write` (edits and FSM transitions) | ✓ WIRED |
| sim/synth.py | /api/nav | `--follow` GET each simulated second | ✓ WIRED |
| helm.js | helm_logic.js | `helmView(nav)` → `primaryView`, `deviationView` | ✓ WIRED |
| lock.js | lock_logic.js | `createLongPress` on the padlock | ✓ WIRED |
| overlays.js | /racepack/seamarks.geojson | `fetch` → GeoJSON source | ✓ WIRED |
| prep/polar.py | nav/polar.py | `polar_to_json` / `polar_from_json` | ✓ WIRED |
| **helm_logic.js** | **nav.layline.dist_nm** | (should be rendered with the countdown) | ✗ NOT_WIRED: gap 1 |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| Barre primary/deviation | `nav.helm` | laylines.solve on StateStore inputs (UDP deltas / gpsd) | Yes (tracer + closed loop drive real decoded inputs) | ✓ FLOWING |
| Countdown | `nav.layline.countdown_s/state/overstood_s` | laylines.solve | Yes | ✓ FLOWING |
| Layline distance | `nav.layline.dist_nm` | laylines.solve | Computed, never rendered | ✗ DISCONNECTED (gap 1) |
| Map basemap | `/tiles/{z}/{x}/{y}.mvt` | TileIndex over `<racepack>/race.pmtiles` | Yes (real pack, z14 tile 200) | ✓ FLOWING |
| Seamarks overlay | `/racepack/seamarks.geojson` | jabuka-prep-map from Geofabrik Croatia | Yes (1058 features) | ✓ FLOWING |
| Course overlay / Carte list | `GET /api/course` | CourseStore (course.json) | Yes | ✓ FLOWING |
| Wind badge | `nav.wind.source/stale/manual_age_s` | WindPipeline | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase 2 test suites | `.venv/bin/python -m pytest tests/nav tests/web tests/ui tests/prep tests/sim/test_closed_loop.py tests/test_helm_logic.py tests/test_lock_logic.py tests/test_tracer_e2e.py tests/test_no_wallclock.py tests/test_event_marker.py` | 403 passed, 0 skipped (203.8 s; Playwright UI tests included) | ✓ PASS |
| Built race pack is valid | `jabuka-prep-map --check var/racepack` | 6190 tiles z0-14, Protomaps 20261105, "check ok", rc 0 | ✓ PASS |
| Core serves the real pack | in-process TestClient, `--racepack var/racepack` | info tiles True maxzoom 14; z14 Šibenik 200 gzip 53 604 B; z12 Jabuka 200; seamarks 200; `/` and `/diag.html` 200; course A = vodice, plic-sestre, jabuka, blitvenica, vodice | ✓ PASS |
| Polar converter | `jabuka-prep-polar tests/fixtures/polar/expedition.txt --out …` | Target table printed, rc 0 | ✓ PASS |
| CR-03 on a beat leg | `laylines.solve`, wind 000°, mark 5 nm N, TWA +90/150/±40 | TWA 90 → cts 322.3 (stbd close-hauled, not 000); TWA 150 → twa_up 37.7; never twa_down; other tack 37.7/322.3 | ✓ PASS |
| Night style red only | parse style-night.json colours | 9 colours, all #rr0000 | ✓ PASS |
| WIND-07 bias freeze (Phase 3 half) | `pytest tests/routing/test_bias_core.py -k zone` | 1 passed | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` are declared or present. Step 7c: N/A.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| WIND-01 | 02-01, 02-02, 02-03 | Load X35 polar; target BSP/TWA, live % polar | ✓ SATISFIED (interim polar) | polar.py, prep-polar; the owner's real X35 polar is a human item |
| WIND-02 | 02-01, 02-03 | Efficiency factor on targets, laylines, routing | ✓ SATISFIED | apply_efficiency / efficiency_for, up/down split; test_efficiency.py |
| WIND-03 | 02-01, 02-03 | TRUE at one boundary, variation, offset, computed + damped true wind | ✓ SATISFIED | wind.py; test_wind.py |
| WIND-04 | 02-03 | Manual TWD/TWS, source badge | ✓ SATISFIED | /api/wind/manual, sourceBadge; GRIB badge text from Phase 3 |
| WIND-07 | 02-03 | Jabuka radius: heading untrusted, COG; bias frozen | ✓ SATISFIED | wind.py zone; bias freeze in route/bias.py (Phase 3) |
| NAV-01 | 02-01, 02-03 | Live laylines ~1 Hz, polar or sailed angles | ✓ SATISFIED | laylines.solve every tick; layline_source |
| NAV-02 | 02-01, 02-03 | Distance/time to layline, overstood, other-tack heading | ✗ BLOCKED (partial) | Time, overstood and other tack are shown; the distance is not displayed (gap 1) |
| NAV-03 | 02-03 | Hercules set/drift opt-in, off by default | ✓ SATISFIED | use_current False; COURANT flag |
| CRSE-01 | 02-01, 02-04 | Marks + Course A/B pre-loaded; select in one action | ⚠ PARTIAL (override suggested) | marks.json + templates; selection is two taps (gap 2) |
| CRSE-02 | 02-04 | Tap add/move/delete, side, radius, reorder | ✓ SATISFIED | carte.js + course_api; UI tests |
| CRSE-03 | 02-04 | Auto-advance, banner + undo, next/prev | ✓ SATISFIED | FSM + banner; closed loop; UI Annuler test |
| CRSE-04 | 02-04 | Shorten/finish at any checkpoint in one action | ✓ SATISFIED | "Finir ici" in the leg sheet → `/api/course/finish` |
| CRSE-05 | 02-01, 02-03, 02-04 | Course and settings persist across reboots and power loss | ✓ SATISFIED (software) | atomic_write_json + .bak; kill -9 test; real power pull is a human item |
| HELM-01 | 02-01, 02-02, 02-05 | Offline map with boat, course, marks, laylines (route: Phase 3) | ✓ SATISFIED (software) | Real tablet is a human item |
| HELM-02 | 02-01, 02-05 | Big numbers: primary by point of sail, deviation, target BSP / %, DTW/TTW, tack countdown | ✓ SATISFIED | helm UI tests |
| HELM-03 | 02-05 | Night true black + red | ✓ SATISFIED (software) | Readability is a human item |
| HELM-04 | 02-05 | Lock mode; screen stays awake | ✓ SATISFIED (software) | Wet-touch and awake behaviour are human items |

All 17 phase requirement IDs are claimed by at least one plan. REQUIREMENTS.md maps no other ID to Phase 2, so there are no ORPHANED requirements. REQUIREMENTS.md still lists all 17 as "Pending"; updating the traceability table is the orchestrator's job.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| (all 62 covered files) | — | TBD / FIXME / XXX | none found | — |
| (all covered files) | — | TODO / HACK / "not yet implemented" | none found | — |
| src/jabuka/nav/data/marks.json | 3 | "Vodice is a provisional start/finish placeholder" | ℹ️ Info | Intentional; SI confirmation is a human item |
| src/jabuka/nav/data/x35-orc-od-2019.exp | 8 | "INTERIM" polar | ℹ️ Info | Intentional; the real polar is a human item |
| src/jabuka/web/static/helm_logic.js | — | `layline.dist_nm` never read | ⚠️ Warning → gap 1 | NAV-02 distance missing on the helm |

### Warnings / Info (non-blocking)

- ℹ️ **MVP goal format.** ROADMAP Phase 2 has `Mode: mvp`, but its `**Goal:**` is not a user story. The restatement in 02-01-PLAN.md is valid and was used here. Consider updating ROADMAP.md, as for Phase 1.
- ℹ️ **Phase 3 code is on master.** Plans 03-01 to 03-05 are already merged (router, GRIB/GPS-only wind source, bias), and nav_service has a GRIB wind source. The Phase 2 layline path stays independent: `route_nav` runs after `update_nav`, and its failures are caught. Phase 3 itself was not verified here.
- ℹ️ **Interim polar.** No `polar.json` is in var/racepack, so the core uses the builtin ORC X-35 OD 2019 polar until the owner's file is converted.
- ℹ️ **Glyph ranges** are 0-767 and 8192-8447. That covers French and Croatian (Latin Extended-A) labels; other scripts would render without labels.

### Human Verification Required

1. **Real tablet, offline map** at http://10.42.0.1 with the race pack on the Pi. Expected: map to z14 with labels, seamarks, course, radii, laylines and boat; no network errors in chrome://inspect.
2. **Screen awake** for at least 2 h, with and without the Chrome flag. Expected: badge "verrou" or "vidéo", and the screen never sleeps.
3. **Night readability** in the dark. Expected: red on black only, nothing white or blue, night vision kept.
4. **Lock in spray and rain**, plus a reload while locked. Expected: no reaction to wet touches; only a 2 s padlock press unlocks; the lock survives a reload.
5. **Real X35 polar** via `jabuka-prep-polar` into the race pack. Expected: the targets match the owner's numbers.
6. **Rounding sides, radii and Vodice start/finish** against the SIs, then "Côtés confirmés".
7. **CR-03 primary-number UX** (sim `--follow` or on the water). Expected: on a beat, never ↓ and never a heading into the wind; the switch is clear to the helmsman.
8. **Live bus on 12 Nov.** Expected: LIVE source, computed-vs-B&G difference under 10°, plausible laylines; MANUEL works with the bus off; set/drift stays off until calibrated.
9. **Pi power pull** after course, settings and manual-wind edits. Expected: everything comes back identical.
10. **Lock review:** 19 package names (Phase 1's 17 plus pmtiles and numpy).

These items are mirrored in `02-UAT.md`.

### Gaps Summary

There are two root causes, both small.

1. **Distance to the layline is not on the helm** (NAV-02, SC2). The server already computes `layline.dist_nm`. Only the browser formatting is missing. Fix: add `fmtDistance(layline.dist_nm)` to the countdown line in `helmView()`, plus one node test. This is roughly a 10-line change in `helm_logic.js` and `tests/test_helm_logic.py`.
2. **Course A/B switch takes two taps** (CRSE-01, SC3, 02-01 truth 4, 02-04 truth 2). This is deliberate, from review fix WR-05. It is a decision for the owner, not a code defect: accept the override above, or replace the confirm tap with a single tap followed by an undo banner.

Neither gap is in a later phase's scope. Plan 03-06 reworks the countdown source but does not mention the layline distance. Neither gap is deferred.

---

_Verified: 2026-11-06T18:36:43Z_
_Verifier: Claude (gsd-verifier)_
