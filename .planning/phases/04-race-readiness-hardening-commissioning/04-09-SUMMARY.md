---
phase: 04-race-readiness-hardening-commissioning
plan: 09
subsystem: nav
tags: [rounding-state-machine, polar, vmg, course, gap-closure]
gap_ids: [G-4-R02, G-4-R04]
plan_head_before: 0a4e8638e614664103f150148bd0d5c4564518fb

requires:
  - phase: 02
    provides: "nav/course.py rounding state machine (CRSE-03), nav/polar.py helm polar (WIND-01)"
  - phase: 03
    provides: "route/polar_grid.py VMG-linear rule (VMG_SEGMENT_MIN_DEG = 120)"
provides:
  - "CourseStore._beyond latch, _leg_dots(), _past_mark(): the zone-exit candidate counts only past the mark"
  - "jabuka.nav.polar.VMG_SEGMENT_MIN_DEG = 120.0 and _interp_curve() used by Polar.speed"
  - "tests/nav/test_course.py G-4-R02 regressions; tests/nav/test_polar_vmg.py helm/router agreement"
affects: [04-10, 04-11, 04-12, commissioning, wheelhouse-rebuild]

actuals:
  tokens: 5000      # chars/4 over the plan's own diff (src/jabuka/nav + tests/nav, 19904 chars)
  tasks: 2
  commits: 5        # MEASURED rev-list 0a4e863..HEAD; includes the owner's CAD commit 372cf6c (not this plan). Plan commits: 4

tech-stack:
  added: []
  patterns:
    - "Zone exit gated on geometry (past the mark), with a latch for hairpins"
    - "One polar interpolation rule shared by helm and router (VMG-linear on deep segments)"

key-files:
  created:
    - tests/nav/test_polar_vmg.py
  modified:
    - src/jabuka/nav/course.py
    - src/jabuka/nav/polar.py
    - tests/nav/test_course.py

key-decisions:
  - "04-09: a zone exit advances the course only past the mark: dot_in > 0 for a normal turn; at a hairpin (> 90 deg) the boat must have been past along the incoming leg since entering (_beyond latch) and be past along the outgoing leg now; no incoming leg keeps the zone exit alone"
  - "04-09: CR-02 (leaving the zone suppressed after Annuler) sets the _beyond latch, since the suppressed ticks never update it; the 2 nm gate resets it"
  - "04-09: the helm polar adopts the router rule (VMG-linear between knots both >= 120 deg); route/polar_grid.py unchanged. 9/11/13 kn residual (tail/deepest rule) stays deferred"

patterns-established:
  - "Helm/router parity is pinned by a test that builds the router curves exactly like router_service._polar_curves"

requirements-completed: []  # REQUIREMENTS.md untouched (plan lists CRSE-03, WIND-01, NAV-01, already complete)

coverage:
  - id: D1
    description: "An approach-side zone exit never advances the course (Plić review repro, Jabuka A/B); real roundings, the hairpin _abeam rule and CR-02 still advance"
    requirement: "CRSE-03"
    verification:
      - kind: unit
        ref: "tests/nav/test_course.py#test_leaving_the_zone_on_the_approach_side_never_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_hairpin_approach_side_retreat_never_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_hairpin_wide_swing_then_rounding_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_hairpin_course_b_rounding_advances"
        status: pass
      - kind: unit
        ref: "tests/nav/test_course.py#test_hairpin_annuler_then_real_rounding_advances"
        status: pass
      - kind: integration
        ref: "tests/sim/test_closed_loop.py#test_closed_loop_beats_tacks_rounds_and_advances"
        status: pass
    human_judgment: false
  - id: D2
    description: "Helm downwind target 180 deg from 14 kn on the shipped X35 polar; helm and router targets agree within 0.1 deg at 4-8, 10, 12, 14-18, 20, 25 kn"
    requirement: "WIND-01"
    verification:
      - kind: unit
        ref: "tests/nav/test_polar_vmg.py#test_helm_and_router_targets_agree_on_the_shipped_polar"
        status: pass
      - kind: unit
        ref: "tests/nav/test_polar_vmg.py#test_downwind_target_is_180_from_14_kn"
        status: pass
      - kind: unit
        ref: "tests/nav/test_polar_vmg.py#test_speed_is_vmg_linear_between_deep_knots"
        status: pass
      - kind: unit
        ref: "tests/nav/test_polar_vmg.py#test_threshold_matches_the_router"
        status: pass
    human_judgment: false
  - id: D3
    description: "Full gate green on Python 3.14 and 3.13 (JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1 scripts/check.sh)"
    verification:
      - kind: other
        ref: "var/gate-04-09.log (check: ok, EXIT=0)"
        status: pass
    human_judgment: false

duration: 30min
completed: 2026-11-09
status: complete
---

# Phase 4 Plan 09: Nav-core gap closure (G-4-R02, G-4-R04) Summary

**The course now advances on a zone exit only once the boat is past the mark (with a latch for the Jabuka hairpin). The helm polar uses the router's VMG-linear rule on deep segments, so the X35 run target reads 180 deg from 14 kn on both the helm and the router.**

## Performance

- **Duration:** 30 min
- **Started:** 2026-11-09T10:13:05Z
- **Completed:** 2026-11-09T10:43:25Z
- **Tasks:** 2 (tracer + auto, both TDD)
- **Files modified:** 4 (2 src, 2 tests)

## Accomplishments

### G-4-R02 (blocker): a zone exit counts only past the mark

`CourseStore._fsm` (in `src/jabuka/nav/course.py`) now builds its candidate as `_abeam(...) or (d > zone and _past_mark(dots))`.
- `_leg_dots` returns `(dot_in, dot_out, turn)`.
- `_past_mark` checks:
  - normal turn: `dot_in > 0`;
  - hairpin: `_beyond and dot_out > 0`;
  - no incoming leg: `True`.
- The `_beyond` latch:
  - is set once the boat, after entering the zone, is past the mark along the incoming leg;
  - is reset by `_reset_fsm` and by the 2 nm gate;
  - is set by CR-02's `left_this_zone`.

`_abeam` is byte-identical to before.

**RED evidence.** These failed before the fix:
- `test_leaving_the_zone_on_the_approach_side_never_advances`: `AssertionError: nnw / assert 2 == 1`. This is the review repro: approach Plić Sestre from the NNW to 0.45 nm, retreat on the same side, hold 30 s outside the zone, and the course moved to `active_idx` 2.
- The large-radius approach-side half: 2 == 1.
- Jabuka A/B approach-side retreat.
- The Jabuka wide swing: 3 == 2.

### G-4-R04 (major): one polar rule for helm and router

- New `VMG_SEGMENT_MIN_DEG = 120.0`.
- New `_interp_curve()`: on a segment whose two knots are both >= 120 deg, it interpolates `bsp x -cos TWA` linearly and divides back by `-cos(x)`.
- `Polar.speed` uses it on both bracketing curves. `targets`, `_deepest`, the cache and `derate_polar`/`_knot_curve` are unchanged.

**RED evidence.** Before the fix:
- 14 kn: helm **170.5 deg** vs router **180.0 deg**.
- 4 kn: 146.0 vs 142.4.
- `speed(14, 165)` was 7.25 instead of 6.98.
- `VMG_SEGMENT_MIN_DEG` did not exist.

### Helm vs router targets after the fix (shipped X35 polar)

| TWS | helm up | router up | helm down | router down |
|----:|--------:|----------:|----------:|------------:|
| 4 | 42.1 | 42.1 | 142.40 | 142.4 |
| 5 | 42.1 | 42.1 | 142.40 | 142.4 |
| 6 | 42.1 | 42.1 | 142.40 | 142.4 |
| 7 | 42.1 | 42.1 | 150.00 | 150.0 |
| 8 | 40.8 | 40.8 | 150.00 | 150.0 |
| **9** | 40.8 | 40.8 | **150.70** | **151.4** |
| 10 | 39.0 | 39.0 | 151.40 | 151.4 |
| **11** | 39.0 | 39.0 | **155.15** | **158.9** |
| 12 | 37.7 | 37.7 | 158.90 | 158.9 |
| **13** | 37.7 | 37.7 | **169.45** | **180.0** |
| 14 | 37.7 | 37.7 | 180.00 | 180.0 |
| 15 | 37.7 | 37.7 | 180.00 | 180.0 |
| 16 | 37.2 | 37.2 | 180.00 | 180.0 |
| 17 | 37.2 | 37.2 | 180.00 | 180.0 |
| 18 | 38.0 | 38.0 | 180.00 | 180.0 |
| 20 | 38.0 | 38.0 | 180.00 | 180.0 |
| 25 | 38.0 | 38.0 | 180.00 | 180.0 |

The 9, 11 and 13 kn rows (bold) are the documented residual. These TWS lie between curves, where nav holds the last speed beyond a curve's last angle and caps its search at the interpolated deepest TWA, while the router tails to 0.9x. That tail/deepest rule is deferred (review A LOW; 04-09-PLAN "Deferred findings"). Upwind targets were already identical.

## Task Commits

1. **Task 1 (tracer): an approach-side zone exit never advances (G-4-R02)**
   - `3668b87` (test, RED)
   - `af85f55` (fix, GREEN)
   - Tracer gate: the verify was re-run green on both venvs before expanding.
2. **Task 2: the helm polar uses the VMG-linear rule; full gate (G-4-R04)**
   - `85a9b1c` (test, RED)
   - `b791f0a` (fix, GREEN)

The owner's CAD commit `372cf6c` (feat(hardware), berceau) landed between Task 1 and Task 2 in the same tree. It is not part of this plan and was not touched.

## Files Created/Modified

- `src/jabuka/nav/course.py`:
  - `_beyond` latch, `_leg_dots()`, `_past_mark()`;
  - the zone-exit branch is gated on past-the-mark;
  - the GATE reset and CR-02 handle the latch;
  - the module docstring states the rule.
- `src/jabuka/nav/polar.py`: `VMG_SEGMENT_MIN_DEG`, `_interp_curve()`, `Polar.speed` uses it, and the docstring states the rule and the deferred tail. `_interp` is kept unchanged and is now unused.
- `tests/nav/test_course.py`:
  - New section "a zone exit counts only past the mark (G-4-R02)" with:
    - the approach-side retreat (Plić NNW and ENE);
    - the Jabuka A/B approach-side retreat;
    - the wide swing then rounding;
    - the Course B rounding.
  - Four bug-encoding tests rewritten:
    - `test_enter_then_leave_without_abeam_advances` is now `test_leaving_the_zone_past_the_mark_advances`;
    - `test_undo_outside_the_zone_needs_a_fresh_entry`;
    - `test_hairpin_annuler_then_real_rounding_advances`, now triggered by the far-side wedge;
    - `test_large_radius_zone_exit_still_advances`, which gains an approach-side half.
- `tests/nav/test_polar_vmg.py` (new): four tests covering agreement, 180 deg from 14 kn, VMG-linear speed and constant parity.

## Verification

- `tests/nav/test_course.py`: 36 passed on `.venv` (3.14) and `.venv313` (3.13).
- `tests/nav tests/sim/test_closed_loop.py tests/web/test_course_api.py`: 275 passed.
- `tests/nav tests/route/test_polar_grid.py tests/routing tests/sim tests/web/test_manual_wind.py tests/test_helm_logic.py tests/prep/test_prep_polar.py`: 452 passed, 2 skipped on both venvs. This includes `test_polar_core` (12 kn down 158.9) and `test_heavy_wind` (exact reproduction).
- Acceptance checks:
  - `grep -c _past_mark course.py` = 2.
  - `grep -c _beyond course.py` = 6.
  - `grep -c VMG_SEGMENT_MIN_DEG polar.py` = 4.
  - `grep -c _interp_curve polar.py` = 3.
  - No hunk inside `def _abeam`.
  - This plan's commits touch `src/jabuka/route/` 0 times.
  - `[p.targets(t).down_twa for t in (14,16,20,25)]` = `[180.0, 180.0, 180.0, 180.0]`.
- Full gate `var/gate-04-09.log`:

```
All checks passed!
1642 passed, 4 skipped in 644.98s (0:10:44)
1642 passed, 4 skipped in 642.33s (0:10:42)
check: ok
EXIT=0
```

## New src/jabuka fingerprint

`FINGERPRINT_SH` over `git archive HEAD src/jabuka` at the plan's last code commit `b791f0a`. The working tree gives the same value.

**`ddd393d90ee18146d32facc2755d04994dfe26fdecae7864a02ba4a77c69ed90`**

Re-provisioning (wheelhouse rebuild, Pi, soaks) waits until after 04-12, per the plan's Human Items.

## Decisions Made

- The hairpin rule uses the latch, not a literal "past along the outgoing leg". At Jabuka the approach side is also past along the outgoing leg, so the literal rule would still advance on an approach-side retreat. This follows the plan.
- CR-02's `left_this_zone` sets `_beyond`. The stay inside the suppressed zone is the rounding evidence, and the suppressed ticks never update the latch.

## Deviations from Plan

None. The plan was executed as written.

Two notes:
- The rewritten `test_large_radius_zone_exit_still_advances` and the new `test_leaving_the_zone_on_the_approach_side_never_advances` use per-scenario sub-directories of `tmp_path`, created with `mkdir()`, because they need two stores. `CourseStore` does not create its data dir.
- The hairpin paragraph of the course.py docstring now says "left the zone past the mark (above)" instead of "left the zone", to stay accurate.

## Issues Encountered

None. The full gate passed on its first run.

## Known Stubs

None.

## User Setup Required

None. The owner's on-boat demo checks are in the plan's Human Items:
- Plić approach-side tack-away keeps Plić active, then the real rounding advances with Annuler.
- On a run at >= 14 kn, "TWA CIBLE ↓" and "TWA ROUTE ↓" both read 180.

## Next Phase Readiness

- G-4-R02 and G-4-R04 are closed in code and tests.
- 04-10, 04-11 and 04-12 do not touch these files.
- After 04-12: rebuild the wheelhouse from the final HEAD, re-provision the Pi, and re-run the soaks (04-UAT tests 1, 2, 5) before the 2026-11-11 freeze.

## Self-Check: PASSED

- FOUND: src/jabuka/nav/course.py, src/jabuka/nav/polar.py, tests/nav/test_course.py, tests/nav/test_polar_vmg.py
- FOUND commits: 3668b87, af85f55, 85a9b1c, b791f0a
- Gate log ends with `check: ok` / `EXIT=0`

---
*Phase: 04-race-readiness-hardening-commissioning*
*Completed: 2026-11-09*
