---
phase: quick-261110-iil
verified: 2026-11-10T13:32:36Z
status: passed
score: 7/7 must-haves verified
covered_files:
  - .planning/quick/261110-iil-on-reste-route-stay-complete-legs-suivan/261110-iil-PLAN.md
  - .planning/quick/261110-iil-on-reste-route-stay-complete-legs-suivan/261110-iil-SUMMARY.md
  - docs/ROUTING.md
  - src/jabuka/core/router_service.py
  - src/jabuka/route/stay.py
  - tests/route/test_stay_route.py
  - tests/routing/test_tack_advice_core.py
covered_digest: "v1:sha256:7e4e6f029146ab3c04f745b8d5976ce52c2b73aa6eb4cdf6d49f067ba15ee915"
behavior_unverified: 0
overrides_applied: 0
---

# Quick 261110-iil: "On reste" route keeps the later legs. Verification Report

**Goal:** With "On reste" active, the displayed route is the forced current leg followed by the same cycle's optimal continuation, shifted by delta. Its ETA is the finish ETA (optimal + delta). The forced route, the cost of not tacking, the hysteresis semantics and the current-leg advice are unchanged. Edge cases fall back safely.
**Verified:** 2026-11-10T13:32:36Z
**Status:** passed
**Re-verification:** No (initial)
**Commits checked:** 726706f, 170e9da, 8be5f9b (base 2271c39). `git diff --name-only 2271c39..HEAD` lists only these 5 files: stay.py (new), router_service.py, test_stay_route.py (new), test_tack_advice_core.py, docs/ROUTING.md.

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | D-01: the stay route has every remaining leg. Leg 1 is forced, the later legs are the optimal legs shifted by delta, and the LineString ends at the finish. | VERIFIED | `stay.py` builds the path as `forced.path[:-1]` + the junction (forced arrival carrying the optimal mark-point state) + `optimal.path[j+1:]` shifted by delta. Legs are `forced.legs[0]` + `optimal.legs[1:]` with eta+delta. `router_service._on_outcome` calls `shown = stay_route(f, opt)`. `test_stay_route_keeps_the_later_legs` checks this through GET /api/route: 2 legs, leg1 = t0+4020, leg2 = t0+5820, coordinates[-1] = the finish, and the leg-2 tack shifted by 420 s. It passes. |
| 2 | D-02: eta_utc is the finish ETA (optimal + delta) and leg_eta_utc is the forced arrival. | VERIFIED | `eta=float(optimal.eta)+delta`, and `_whole_eta` returns `shown.eta`. The same test asserts on the msg eta_utc and on the nav block eta_utc/leg_eta_utc (t0+5820 / t0+4020). |
| 3 | D-03: the forced route, res.forced and the cost are unchanged; test_forced_cost passes untouched. | VERIFIED | `git diff 2271c39..HEAD` is empty on route/cycle.py, route/isochrone.py and route/advice.py, as well as on web/, cad/, stl/, hardware/ and docs/SOAK.md. stay_route returns a new dataclass and never mutates `forced`, and `_adopt` still takes cost from `res.cost_s`. tests/route/test_forced_cost.py passes (included in the targeted run). |
| 4 | D-04: should_replace receives the composed finish ETA. An equal re-evaluation is kept, and a gain > 3 min replaces. | VERIFIED | `should_replace(float(shown.eta...), ..., res.eta_old_now, ...)` with `shown` = the composed route. `test_stay_hysteresis_compares_whole_routes` keeps version 2 on an equal re-evaluation and moves to version 3 on +600 s. It passes. |
| 5 | D-05: current-leg advice from the composed route equals the forced leg alone (target TWA/tack, XTE, course deviation, next tack, countdown). | VERIFIED | `test_current_leg_advice_is_the_forced_legs` compares RouteFollower outputs (idx, xte_nm, course_dev_deg, target_twa, target_tack, next_tack, countdown) between `stay_route(f, o)` and `f`. In the core test, next_tack = the forced tack (t0+1500) and countdown ~1500 s. Both pass. Documented intended change: once the forced leg has no tack left, the countdown points at the first tack after the mark instead of "no tack". |
| 6 | D-06: edge cases return forced and never raise, and an exception in the core falls back to forced. | VERIFIED | 12 parametrized fallbacks (`stay_route(f, o) is f`): single leg, mark-id mismatch, no point at the mark ETA, point 5 s off, mark point last, junction far, optimal/forced not ok, forced eta None, optimal eta NaN, empty path, no legs. All pass. Logging: `log.debug` for the last leg and `log.info` for other reasons. Core exception path: the try/except calls `log.exception` and sets `shown = f`. I checked this behaviourally with a scratch test outside the repo that monkeypatches `router_service.stay_route` to raise. The cycle was still adopted (kind stay, version 2), /api/route had 1 leg (forced only), and "stay route composition failed" was logged. It passed. |
| 7 | The gate is green (ruff check, ruff format --check, pytest on both venvs). | VERIFIED (scoped) | I re-ran ruff check and ruff format --check on the 4 changed Python files: they pass. Targeted suites on .venv313 gave 114 passed, 2 skipped. I did not re-run the full gate, as instructed. The only full-run failure the SUMMARY reports is the pre-existing flaky UI test (see Anti-Patterns): it passes alone, and the change cannot reach it. |

**Score:** 7/7 verified (0 present, behavior-unverified)

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| src/jabuka/route/stay.py | VERIFIED | 134 lines, `def stay_route` present. Pure (stdlib + route.types); test_route_purity passes. Wired into router_service. |
| src/jabuka/core/router_service.py | VERIFIED | Import plus `stay_route(f, opt)` inside try/except. D-04 comment and `_whole_eta` docstring updated. |
| tests/routing/test_tack_advice_core.py | VERIFIED | Has `test_stay_route_keeps_the_later_legs` and `test_stay_hysteresis_compares_whole_routes`. |
| tests/route/test_stay_route.py | VERIFIED | Composition, junction tack/gybe, negative delta, 12 fallbacks, advice invariance, and a real-router two-mark run. |
| docs/ROUTING.md | VERIFIED | The English paragraph references `src/jabuka/route/stay.py`. There is a French ON RESTE bullet "La route affichée va jusqu'à l'arrivée…". |

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| router_service.py | route/stay.py | `shown = stay_route(f, opt)` in `_on_outcome` (pattern `stay_route\(f, opt\)`) | WIRED |
| router_service.py | advice.should_replace / RouteFollower | `should_replace(shown.eta, …, res.eta_old_now …)`; `_on_new_route` builds `RouteFollower(route.path, route.tacks, legs=composed leg ETAs)` | WIRED |
| stay.py | isochrone tack rule | `_appended_tacks`: prev/tk non-zero, a sign change makes a tack, or a gybe when abs(twa) >= 90 | WIRED (junction tack/gybe test passes) |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Targeted suites | `.venv313/bin/pytest -q tests/route/test_stay_route.py tests/routing/ tests/route/test_forced_cost.py tests/route/test_route_purity.py` | 114 passed, 2 skipped | PASS |
| Core exception fallback | scratch test (scratchpad, not in repo) that monkeypatches `router_service.stay_route` to raise | 1 passed: forced-only route adopted, log.exception emitted | PASS |
| Flaky UI test alone | `.venv313/bin/pytest -q tests/ui/test_i18n_ui.py::test_switch_to_slovenian_then_english_persists_and_fits` | 1 passed | PASS |
| Lint/format of changed files | `.venv313/bin/ruff check` + `ruff format --check` | all passed / 4 files already formatted | PASS |
| Protected files unchanged | `git diff --name-only 2271c39..HEAD -- route/cycle.py route/isochrone.py route/advice.py web cad stl hardware docs/SOAK.md` | empty | PASS |

## Requirements Coverage

ROUT-07, ROUT-10, ROUT-05 and ROUT-06 (as declared by the plan) are satisfied for this fix's scope, through truths 1–6: the stay display, the hysteresis, the advice and the robustness.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none in changed files) | - | No TBD/FIXME/XXX/TODO introduced | - | - |
| tests/ui/test_i18n_ui.py | - | Pre-existing flaky race: it reads `#settings-form` inner_text without waiting for the async /api/settings fill | Info | Not caused by this change. The diff touches no web/, i18n or settings file, and the test's flow (language switch and settings form) never activates "On reste", so the modified `_on_outcome` stay branch is not reached. It passed alone just now. A follow-up `wait_for_function` would make it deterministic. |
| src/jabuka/core/router_service.py | ~993 | When a stay cycle switches between the forced-only fallback and the composed route, should_replace compares a leg ETA with a finish ETA once | Info | Documented in a comment. At worst it causes one extra replacement, which is harmless. |

## Human Verification Required

None blocking. Optional: once the orchestrator restarts the demo on :8080 (it still runs the old code), look at the map with "On reste" active and check that the later legs are drawn and the finish ETA is shown.

## Gaps Summary

No gaps. The SUMMARY's claims match the code and the tests. The only gate deviation (the 3.13 full run) comes from a pre-existing flaky UI test that this change cannot affect.

---

_Verified: 2026-11-10T13:32:36Z_
_Verifier: Claude (gsd-verifier)_
