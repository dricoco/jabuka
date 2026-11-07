---
phase: quick-261107-1ow
plan: 01
subsystem: nav/polar, core (nav + router), settings, web i18n
status: complete
tags: [polar, heavy-weather, settings, routing, WIND-01, WIND-02, ROUT-01]
requires: []
provides:
  - "heavy_wind_factor(tws, start, full, reduction) and derate_polar(polar, start, full, reduction) in jabuka.nav.polar"
  - "Settings.heavy_wind_start_kn / heavy_wind_full_kn / heavy_wind_reduction (18 / 25 / 0.05) + _heavy_wind_order validator"
  - "NavService.polar_raw (loaded once) and NavService.polar (derated, cached on the 3 settings, stable identity)"
  - "RouterService._polar_curves cached on the Polar object (strong reference) instead of id()"
affects: [helm targets, % polaire, reach speed, laylines, router request curves, Réglages form]
tech-stack:
  added: []
  patterns:
    - "per-TWS uniform derating applied once on the polar curves, shared by helm and router; efficiency stays a separate factor on top"
    - "identity cache holding a strong reference (is) instead of id() for objects rebuilt on settings changes"
key-files:
  created:
    - tests/nav/test_heavy_wind.py
    - tests/routing/test_heavy_wind_router.py
  modified:
    - src/jabuka/nav/polar.py
    - src/jabuka/nav/settings.py
    - src/jabuka/core/nav_service.py
    - src/jabuka/core/router_service.py
    - src/jabuka/web/static/i18n.js
    - docs/I18N-SL-REVIEW.md
    - docs/COMMISSIONING.md
    - docs/FREEZE.md
    - docs/RACE-PACK.md
decisions:
  - "Knot curves at start/full use the UNION of the bracketing curves' TWA points <= polar._deepest(k), plus _deepest(k), with speeds polar.speed(k, a) (planner deviation on S-04, approved): reproduces the raw polar exactly below start and never moves a VMG angle"
  - "RouterService caches its curves on the Polar object itself (strong reference, `is`), not id()"
  - "No reroute trigger on heavy_wind_* changes (parity with efficiency): the next cadence cycle or Recalculer picks the new curves up"
metrics:
  completed: 2026-11-07
  tasks: 3
  files: 11
actuals:
  tokens: 8300
  tasks: 3
  commits: 4  # 3 task commits + this summary commit (rev-list --count a87359b..HEAD)
plan_head_before: a87359b7d635f937922191dc86737efbfe627b0c
---

# Quick 261107-1ow: Heavy-weather polar reduction Summary

The helm and the router now share one polar, derated per TWS. The reduction is 1 at 18 kn and
below, ramps linearly to 0.95 at 25 kn and stays at 0.95 above. It is set in Réglages through
three fields with fr/en/sl labels. The efficiency still multiplies on top, and no VMG target angle
moves.

## What was built

- **`jabuka.nav.polar`**: `heavy_wind_factor` computes f = 1 - reduction × clamp((tws - start) / (full - start), 0, 1).
  `derate_polar` is pure: reduction 0 returns the same object. It raises a French `ValueError`
  unless 0 < start < full and 0 <= reduction < 1, and adds knot curves at start and full unless a
  curve already sits there (isclose, 1e-6). Every curve keeps its own TWA points and is multiplied
  by f(curve TWS). The module docstring covers the derating and Pitfall 9.
- **Settings**: `heavy_wind_start_kn` (18, 10–35), `heavy_wind_full_kn` (25, 12–40) and
  `heavy_wind_reduction` (0.05, 0–0.3) sit right after `efficiency_down`, with the exact French
  labels. The `_heavy_wind_order` validator rejects full <= start. An old `settings.json` without
  these keys still loads.
- **NavService**: `polar_raw` keeps the race-pack polar. The new `polar` property returns the
  derated polar, cached on (start, full, reduction), so it is the same object while those
  settings don't change. If `derate_polar` raises a `ValueError`, it logs the error and falls back
  to the raw polar. `_compute` reads `polar = self.polar` once per tick and uses it for the targets,
  the % polaire reference, the message's polar name and the reach speed. The efficiency calls are
  unchanged and the nav message shape is unchanged.
- **RouterService**: `_curves_key: int` (an `id()`) is replaced by `_curves_polar: Polar | None`.
  The router rebuilds when `self._curves_polar is not polar` and keeps a strong reference to that
  polar. The TWA-0 filter and `normalize_curves` are unchanged, and so are the efficiency
  arguments.
- **i18n**: `settings.heavy_wind_*` in SETTINGS_FR (the server labels), SETTINGS_EN and
  SETTINGS_SL. `docs/I18N-SL-REVIEW.md` was regenerated with `python -m jabuka.tools.i18n_review`
  and the `.bak` was deleted. `reglages.js` is unchanged because the form is built from the schema.
- **Docs**: one or two sentences each in COMMISSIONING.md §4 (Réglages concernés), FREEZE.md
  (configuration still allowed after the freeze) and RACE-PACK.md (sanity-check bullet: the
  printed table is the raw polar). No new table rows or numbered steps.

With the defaults on the X35 builtin polar, the derated curve TWS list is
6, 8, 10, 12, 14, 16, 18, 20, 25.

## Deviations from Plan

### Planner deviation on S-04 (approved, implemented as written in the plan)
Knot curves use the union of the bracketing curves' angles up to `_deepest(k)`, plus `_deepest(k)`.
They do not use "the angle set of the nearest bracketing curve". With this rule the derated polar
reproduces the raw one within 1e-9 at TWS <= 18 kn for every TWA 0–180. It is exactly 0.95 × raw
at 25, 27, 30 and 35 kn, and no up/down target angle moves anywhere from 4 to 30 kn (0.5 kn
steps). The router PolarGrid rows 0–18 are identical to raw, rows 25 and 30 are 0.95 × raw, and
up_deg/down_deg are identical on every row.

### Auto-fixed / additions
1. **[Rule 2 - Missing critical] `heavy_wind_factor` guard for full <= start.** The pure helper is
   public and would divide by zero there. It now returns a step function instead. Settings and
   `derate_polar` both reject that case before the helper is called.
2. **Test addition (router regression).** The id()-reuse hazard did not reproduce in practice:
   the old id() cache passed a 20-iteration loop of two changes between requests on CPython 3.14.
   So the regression test also checks that the strong reference is held
   (`router._curves_polar is nav.polar`). Run against the old `router_service.py`, it fails with
   `AttributeError` (RED); it passes on the new one.
3. **Extra test.** `PUT /api/settings` with start >= full or reduction 0.4 returns HTTP 422 and
   leaves the settings unchanged. This makes the "refused (HTTP 422), nothing is written"
   must-have explicit.

### Tests pinned to heavy_wind_reduction 0
None. No existing test needed pinning. tests/routing and tests/route stayed green with the
defaults (323 passed, 3 skipped on 3.14 before the full gate).

## TDD notes
- Task 1 RED: `tests/nav/test_heavy_wind.py` run against the master code fails at collection with
  `ImportError: cannot import name 'derate_polar'`. GREEN: 43 passed.
- Task 2 RED: the strong-reference assertion fails with the old id() cache (`AttributeError`);
  the curve cases already passed after Task 1, because the router reads `nav.polar`. GREEN: 5 passed.

## Gate

The venvs live in the main checkout and their editable install points to the main `src`. So the
gate was run from the worktree root with `PYTHONPATH=src:<scratchpad symlink to the worktree src>`.
Both the in-process tests and the subprocess tests (`sys.executable -m ...`, console scripts such
as `jabuka-core`, which inherit `PYTHONPATH` and resolve it ahead of the editable path) therefore
ran the worktree code. This was checked with `jabuka.nav.polar.__file__` resolving into the
worktree from a different cwd. `scripts/bootstrap-dev.sh` was not run.

- ruff check src tests: All checks passed
- ruff format --check src tests: 228 files already formatted
- Python 3.14: **1512 passed, 4 skipped**. The full run printed 1510 passed, 6 skipped: the 2 extra
  skips were `tests/deploy/test_lock.py` (wheelhouse tests), because `deploy/wheelhouse/` is
  gitignored and missing from a fresh worktree. With a temporary symlink to the main checkout's
  wheelhouse, test_lock.py gave 7 passed, so 1510 + 2 = 1512 passed, 4 skipped. The symlink was
  removed afterwards.
- Python 3.13: **1512 passed, 4 skipped**, a single full run with the wheelhouse symlink in place.
  The skips are the same 4 as the baseline: oracle_lwr (no weatherrouting), the full rehearsal
  (JABUKA_REHEARSAL_FULL unset) and 2 × real_pack_e2e (JABUKA_REAL_PACK unset).

Baseline on master 728996a: 1464 passed, 4 skipped on each interpreter. The new tests add 48
(43 in tests/nav/test_heavy_wind.py + 5 in tests/routing/test_heavy_wind_router.py), so
1464 + 48 = 1512.

## Threat model
- T-1ow-01: pydantic bounds plus `_heavy_wind_order`; PUT returns 422 and writes nothing (tested).
- T-1ow-02: if `NavService.polar` hits a `ValueError` it falls back to the raw polar with one
  `log.exception` per settings key, never once per tick.
- T-1ow-03: the identity cache holds a strong reference (tested).

## Commits
- e0a951b feat(quick-261107-1ow): heavy-weather polar reduction on the helm targets
- 40e6b04 feat(quick-261107-1ow): router takes the same derated polar, identity-cached
- 89e796f docs(quick-261107-1ow): heavy-wind polar reduction in commissioning, freeze and race-pack docs

## Known Stubs
None.

## Self-Check: PASSED
- The created files exist: tests/nav/test_heavy_wind.py and tests/routing/test_heavy_wind_router.py.
- The commits e0a951b, 40e6b04 and 89e796f are on branch worktree-agent-a16964eff5f18e347.
- `git status` showed no docs/I18N-SL-REVIEW.md.bak and no scratch files before this summary
  commit.
- ROADMAP.md and STATE.md were not touched, as the orchestrator instructed.
