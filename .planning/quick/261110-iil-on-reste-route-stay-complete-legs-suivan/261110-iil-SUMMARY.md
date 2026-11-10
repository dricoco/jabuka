---
phase: quick-261110-iil
plan: 01
status: complete
subsystem: routing (core display of the "On reste" route)
tags: [routing, on-reste, stay, hysteresis, helm-advice]
requires: [route/types.py RouteResult/PathPoint/TackPoint/LegResult, route/cycle.py forced + optimal from one snapshot]
provides: [route/stay.py stay_route(forced, optimal), complete stay route with finish ETA in /api/route and the nav block]
affects: [src/jabuka/core/router_service.py _on_outcome / _whole_eta, docs/ROUTING.md]
tech-stack:
  added: []
  patterns: [pure route module (stdlib + route types), best-effort try/except fallback in the core]
key-files:
  created:
    - src/jabuka/route/stay.py
    - tests/route/test_stay_route.py
  modified:
    - src/jabuka/core/router_service.py
    - tests/routing/test_tack_advice_core.py
    - docs/ROUTING.md
decisions:
  - "D-04: should_replace receives the composed finish ETA (same span as eta_old_now, the displayed route re-evaluated by the worker); feeding the forced leg ETA would replace on every timer cycle"
  - "O-01 (marking the appended part on the map) not implemented: needs a new persisted Adopted field and a front-end change two days before the freeze"
  - "stay_route logs its fallback reason (debug for the normal last-leg case, info otherwise) so a forced-leg-only stay route can be diagnosed"
metrics:
  duration: ~35 min
  completed: 2026-11-10
  tasks: 3
  files: 5
commits: 3
plan_head_before: 2271c39f43abd07082ad4bef65723084960b34ad
actuals:
  tokens: 4700
  tasks: 3
  commits: 3
---

# Phase quick-261110-iil Plan 01: On reste route keeps the later legs Summary

With "On reste" active, the displayed route is now the forced current leg followed by the same cycle's optimal route from the active mark onward, shifted by delta = forced ETA at the mark - optimal ETA at the mark. Its eta_utc is the finish ETA (optimal + delta). Before the fix it was the forced leg alone, so later legs vanished and the ETA became the active-mark ETA.

## What was built

- **`src/jabuka/route/stay.py`**: `stay_route(forced, optimal) -> RouteResult`. This is a pure module (stdlib and route types only, no numpy, no clock). The junction is the forced arrival point (forced t/lat/lon) carrying the optimal segment that leaves the mark. The tail is the optimal path after the mark, shifted by delta, which is not clamped. Tacks are the forced tacks, plus tacks recomputed on the appended part with the `isochrone._tack_points` rule, starting from the arriving forced tack. That adds a junction tack or gybe when the next leg leaves on the other side. Legs are `forced.legs[0]` plus the later optimal legs shifted by delta. eta = optimal.eta + delta. valid = both valid; horizon_hold = either. Every other field comes from forced. The function returns `forced` itself when:
  - either route is unusable;
  - the optimal has only one leg;
  - the mark ids don't match;
  - no optimal path point lies within 1 s of the optimal mark ETA, or that point is the last one;
  - the junction is more than 0.1 nm from the forced arrival.

  The fallback reason is logged.
- **`src/jabuka/core/router_service.py`**: `_on_outcome` shows `stay_route(f, opt)`. A composition exception is caught (`log.exception`) and falls back to `f`, so a cycle is never dropped. A comment on `should_replace` records D-04. The `_whole_eta` docstring is updated. `route/cycle.py`, `route/isochrone.py`, `route/advice.py`, the cost and `_adopt` are untouched.
- **Tests**:
  - `test_stay_route_keeps_the_later_legs` (failed first, then passed): 2 legs, legs[0] = forced arrival, legs[1] and eta_utc shifted by 420 s, LineString ends at the finish, shifted leg-2 tack, next_tack = forced first tack, nav eta_utc/leg_eta_utc/countdown.
  - `test_stay_hysteresis_compares_whole_routes`: equal re-evaluated finish ETA keeps the route (version 2); +600 s replaces it (version 3). A mutation check confirmed that feeding the forced leg ETA fails this test.
  - `tests/route/test_stay_route.py` (21 tests): composition; junction tack/gybe/none; negative delta; 12 parametrized fallbacks; advice invariance on the forced leg (idx, XTE, course deviation, target TWA/tack, next tack, countdown); one real-router two-mark round (1-leg forced (D-03), composed 2 legs, eta = optimal + delta = optimal + cost).
- **`docs/ROUTING.md`**: an English router paragraph, plus a French ON RESTE bullet ("La route affichée va jusqu'à l'arrivée…").

## Hysteresis note (plan-checker advisory)

A stay cycle can alternate between the forced fallback (one leg, for example a junction mismatch) and the composed route. On that switch, `should_replace` compares a leg ETA with a finish ETA once, which causes at most one extra, harmless replacement. This is documented in the comment at the `should_replace` call. stay_route logs why it fell back (`log.info`, or `log.debug` for the normal last-leg case) so this can be diagnosed.

## Intended advice change (documented in the test docstring)

Once the forced leg has no tack left, the countdown now points at the first tack after the mark (as an optimal multi-leg route already does) instead of showing no tack.

## Deviations from Plan

- The two-leg fake script was written as the module-level helper `_two_legs(rh, delta_s, old_extra_s)` already in Task 1, rather than being extracted in Task 2. The result is the same.
- The hysteresis test reuses the existing timer-cycle trigger pattern (`core.call(core.router.request, "timer", False)` + `_run`), as the plan-checker advised.
- Otherwise the plan was executed as written. stay_route needed no fixes in Task 2.

## Gate

- `bash scripts/check.sh`: bootstrap, `ruff check`, `ruff format --check` and pytest on the 3.14 venv all passed.
- The 3.13 venv run had 1 failure out of 2012 tests, so the gate did not print "check: ok". The failing test is `tests/ui/test_i18n_ui.py::test_switch_to_slovenian_then_english_persists_and_fits`, a flaky race that this change did not cause:
  - **Cause:** after the language reload, the test reads `#settings-form` `inner_text()` without waiting. `reglages.js` fills that form asynchronously from /api/settings, so under load the text is still `''`.
  - **Evidence it is flaky:**
    - It failed in two full 3.13 runs and one `tests/ui` run at HEAD.
    - It passed alone on both venvs.
    - It passed in a later full `tests/ui` run at HEAD (51 passed).
    - `tests/ui` at the base commit 2271c39 also passed.
    - No web, i18n or settings file was touched.
  - **Status:** out of scope and not fixed. A `wait_for_function` on the form text would make it deterministic.
- The 3.13 run of the targeted suites (stay_route, tack_advice_core, forced_cost, route_purity, advice, decisions) is green.

## Deferred Issues

- Flaky `tests/ui/test_i18n_ui.py::test_switch_to_slovenian_then_english_persists_and_fits`: it does not wait for the asynchronous settings form after the language reload. It is pre-existing, outside this task's scope, and was left unfixed.

## Deployment note

`src/jabuka` changed (route/stay.py and core/router_service.py), so the src fingerprint changes. Rebuilding the wheelhouse, re-provisioning the Pi and restarting the demo on port 8080 are left to the orchestrator. The demo on 8080 still runs the old code.

## Commits

- 726706f fix(quick-261110-iil): On reste — la route affichée garde les branches suivantes et l'ETA d'arrivée
- 170e9da test(quick-261110-iil): route On reste — cas limites, conseil de barre inchangé, routeur réel, hystérésis
- 8be5f9b docs(quick-261110-iil): route On reste complète jusqu'à l'arrivée (ROUTING.md)

## Self-Check: PASSED

- FOUND: src/jabuka/route/stay.py, tests/route/test_stay_route.py
- FOUND: 726706f, 170e9da, 8be5f9b. `git rev-list --count 2271c39..HEAD` = 3.
- No change under route/cycle.py, route/isochrone.py, route/advice.py, src/jabuka/web/, cad/, stl/, hardware/ or docs/SOAK.md.
