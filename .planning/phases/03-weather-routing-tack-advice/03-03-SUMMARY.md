---
phase: 03-weather-routing-tack-advice
plan: 03
subsystem: route/isochrone-engine
status: complete
tags: [routing, isochrones, numpy, polar, rounding, waves, current, forced-tack, benchmark, ROUT-01, ROUT-03, ROUT-04, ROUT-07, ROUT-08, ROUT-11, ROUT-02]

requires:
  - phase: 03-01
    provides: "LandMask (segments_clear, near_land, snap_clear, validate_polyline), compute_geofield / save/load_geofields, Frame"
  - phase: 03-02
    provides: "load_pack / Grid / RacePack, read_marks_file, prep cli + wxpack.write_npz, ICON-EU/EWAM samples"
  - phase: 03-04
    provides: "BiasParams.weights, RouterPool (forkserver, nice, timeout), route-follower path contract"
provides:
  - "jabuka.route.types: CourseMark, Waypoint, RouterSettings, LEVELS (L0-L5), RouteRequest, PathPoint, TackPoint, LegResult, RouteResult, CycleRequest, CycleResult"
  - "jabuka.route.polar_grid: PolarGrid (from_curves, from_polar_json, speed, raw_speed, targets, vmg_up/down), curves_from_json, normalize_curves"
  - "jabuka.route.fields: WindField (sample, uv_kn, at, horizon_hold), WaveField, CurrentField, Fields, fields_from_pack, hs_from_tws, uv_to_dir_speed"
  - "jabuka.route.rounding: expand(prev, marks, boat_lat, boat_lon, mask=None, notes=None)"
  - "jabuka.route.isochrone: route, RouterEnv (geofield_for, polar_for), mark_key, heading_from_twa, tack_of, wave_factor, sample_weather, boat_speed, course_to_steer"
  - "jabuka.route.evaluate: evaluate_path, first_side_change, project"
  - "jabuka.route.cycle: init_worker, run_cycle, build_env, cycle_with_env, rss_kb"
  - "jabuka.route.bench: main (python -m jabuka.route.bench), assemble_fixture_pack, parse_levels, percentile, duty, platform_info"
  - "jabuka-prep geofields --marks FILE --out DIR [--gcell-m 200]"
  - "tests/fixtures/route/{x35_polar,marks}.json"
  - "docs/ROUTING.md: Router section + Banc d'essai Pi (porte du 2026-11-09) with the L0-L5 ladder"
affects: [03-05, 03-06, phase-4-runbook]

actuals:
  tokens: 44200
  tasks: 3
  commits: 5
plan_head_before: 9055678bedc2429fea1f194f0d6de15e454ba3e2
commits: 5

tech-stack:
  added: ["numpy 2.5.4, shapely 2.2.0, pygrib 2.1.8 installed dev-only into .venv/.venv313 (plan 03-05 declares numpy for the Pi)"]
  patterns:
    - "Arrival shots (one board, or two boards on the VMG targets) kept as the best arrival until the front time passes it: tacks on the layline are not quantised to the step"
    - "Weather sampled once per parent per step: wind (bias) minus current = the wind over the water fed to the polar; current added to the displacement"
    - "Forced routing = filter the candidate half-plane to tack0 before force_until; release only when no same-tack candidate is clear"
    - "Worker init never raises: errors kept as strings, run_cycle answers ok False"

key-files:
  created:
    - src/jabuka/route/types.py
    - src/jabuka/route/polar_grid.py
    - src/jabuka/route/fields.py
    - src/jabuka/route/rounding.py
    - src/jabuka/route/isochrone.py
    - src/jabuka/route/evaluate.py
    - src/jabuka/route/cycle.py
    - src/jabuka/route/bench.py
    - tests/route/conftest.py
    - tests/route/test_polar_grid.py
    - tests/route/test_fields.py
    - tests/route/test_isochrone_tracer.py
    - tests/route/test_rounding.py
    - tests/route/test_course_routes.py
    - tests/route/test_waves_current.py
    - tests/route/test_geofields_prep.py
    - tests/route/test_oracle_lwr.py
    - tests/route/test_forced_cost.py
    - tests/route/test_evaluate.py
    - tests/route/test_cycle.py
    - tests/route/test_bench.py
    - tests/fixtures/route/x35_polar.json
    - tests/fixtures/route/marks.json
  modified:
    - src/jabuka/prep/cli.py
    - docs/ROUTING.md

key-decisions:
  - "Exact two-board arrival shots on the VMG targets (target inside the upwind/downwind cone), held as the best arrival until the front time passes it, shots limited to max(2 dt, 1 h) of the parent's wind: the 8 nm beat went from +2.9 % to exactly VMG time + one tack penalty"
  - "Polar tail: VMG-linear interpolation between downwind points >= 120 deg, 0.9 x last speed at 180 deg capped at 98 % of the last point's run VMG: targets now match the ORC gybe angles (142.4/150/151.4/158.9/180 deg) instead of a fake 180 deg target at 6-10 kn; TWA table step 0.1 deg so given angles are exact columns"
  - "Pass-by marks (course bends away from the required side, e.g. Course B Plić Sestre to port while turning 42 deg to starboard): abeam waypoint + entry waypoint 45 deg earlier, no 318 deg loop (string rule)"
  - "Geodesic ranking keeps candidates the coarse field cannot reach (inf) ranked by straight distance after every reachable one, instead of dropping them (400 m on-demand fields close narrow channels)"
  - "Old-route evaluation samples the weather per piece of <= 2 nm and invalidates below 25 deg TWA (30 deg minus a 5 deg sampling tolerance): with 0.5 nm pieces the router's own 30 deg segments read 27-29 deg on the real ICON-EU wind"

patterns-established:
  - "Route-deps guard in every tests/route module; conftest imports numpy only inside fixtures"
  - "Picklable job functions live in the package (cycle.run_cycle, cycle.init_worker), never in tests"

requirements-completed: [ROUT-01, ROUT-03, ROUT-04, ROUT-07, ROUT-08, ROUT-11, ROUT-02]

coverage:
  - id: D1
    description: "Vodice to the open sea through a real channel (Prvić-Tijat pinch in SW 12, the gap north of Tijat in NE 18), every shipped segment re-validated"
    requirement: ROUT-11
    verification:
      - kind: unit
        ref: "tests/route/test_isochrone_tracer.py#test_vodice_to_open_sea_through_a_channel"
        status: pass
    human_judgment: false
  - id: D2
    description: "Courses A and B x (SW 12, NE 18, ICON-EU +0 h, +6 h): valid, sides by signed winding, >= 200 m from the Plić Sestre beacon, stable ETAs, L3 two marks ahead"
    requirement: ROUT-01
    verification:
      - kind: unit
        ref: "tests/route/test_course_routes.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Wave factor (Hs file or Hs(TWS), floor 0.70), current vector sum and water-referenced wind, efficiency, tack penalty"
    requirement: ROUT-03
    verification:
      - kind: unit
        ref: "tests/route/test_waves_current.py, tests/route/test_isochrone_tracer.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Forced current-leg route held on tack0 until advised + 5 min, released at land, cost of not tacking >= 0, on_reste note"
    requirement: ROUT-07
    verification:
      - kind: unit
        ref: "tests/route/test_forced_cost.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Worker cycle in process and through the forkserver RouterPool; bad pack fails cleanly; old route re-evaluated"
    requirement: ROUT-02
    verification:
      - kind: integration
        ref: "tests/route/test_cycle.py, tests/route/test_evaluate.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "Pi benchmark run on the real Raspberry Pi 3B with the race pack (gate 2026-11-09)"
    verification:
      - kind: manual_procedural
        ref: "docs/ROUTING.md 'Banc d'essai Pi (porte du 2026-11-09)'"
        status: unknown
    human_judgment: true
    rationale: "Needs the physical Pi 3B, its thermal behaviour and the same-day race pack"

duration: about 60 min
completed: 2026-11-06
---

# Phase 3 Plan 03: Isochrone router Summary

**A numpy isochrone router with geodesic sector ranking, exact layline arrivals, rounding
waypoints on the required side, waves, current, GRIB bias, efficiency and tack penalty. It routes
the whole of Course A or B in 0.3-0.56 s on the laptop without crossing the mask. One worker cycle
returns the optimal route, the "On reste" forced leg, the cost of not tacking and the old route
re-evaluated. A one-command benchmark is ready for the 2026-11-09 Pi gate.**

## Performance

- **Duration:** about 60 min (Task 1 committed 05:20, Task 3 05:42 local)
- **Tasks:** 3 (1 tracer, 2 TDD with RED commits)
- **Files:** 23 created, 2 modified

## Accomplishments

- **Contracts (`types.py`).** Frozen dataclasses and NamedTuples of plain types: `RouteRequest`, `RouteResult`, `CycleRequest`, `CycleResult`, `PathPoint`, `TackPoint`, `LegResult`, `CourseMark`, `Waypoint` and `RouterSettings`, with `problems()` validation in French. `LEVELS` L0-L5 are built with `dataclasses.replace`, exactly as in the interfaces block.
- **Polar (`polar_grid.py`).** Dense table: TWS 0-40 kn by TWA 0-180° in 0.1° steps.
  - Measured values: `speed(12, 37.7)` = 6.50 and the clamp above 20 kn.
  - Targets: upwind at 12 kn is 37.7°. Downwind is 158.9° at 12 kn and 180° at 14-20 kn; at 6, 8 and 10 kn it is 142.4°, 150° and 151.4°.
  - Efficiency never moves the targets.
  - Malformed polar JSON raises ValueError in French.
- **Weather (`fields.py`).**
  - `WindField` blends time and space and holds edge and horizon values. It applies the bias and gives the core a scalar `at()`.
  - `WaveField`, `CurrentField`, `fields_from_pack` and the Hs(TWS) table.
- **Engine (`isochrone.py`).**
  - Geodesic sector ranking with lazy land checks, and fine steps near land, the mark and the leg origin.
  - Exact arrivals: a direct shot, or two boards on the VMG targets.
  - Water-referenced wind, current, wave factor, efficiency, tack penalty and bias.
  - Multi-leg routing through `rounding.expand`; `max_marks_ahead`, `leg_only` and `force_tack_until` with release at land.
  - Mask-aware decimation to at most 300 points, then `validate_polyline` on the shipped path.
  - Failures come back as `ok False` with a French reason.
- **Rounding (`rounding.py`).** Waypoints follow Pattern 6, with these extras: pass-by entry waypoints, dropping waypoints already passed, and pushing blocked waypoints outward.
- **Cycle and evaluation.**
  - `cycle.run_cycle`: optimal route, forced route, cost and old-route evaluation from one snapshot.
  - `init_worker` never raises.
  - `evaluate.evaluate_path` and `first_side_change`.
- **Benchmark.** `python -m jabuka.route.bench` with `--quick`, `--fixture`, `--pack`, `--levels`, `--runs`, `--start`, `--json` and `--inprocess`.
- **Prep.** New subcommand `jabuka-prep geofields`.
- **Docs.** `docs/ROUTING.md` gains a router section and "Banc d'essai Pi (porte du 2026-11-09)".

## Laptop numbers (i7-7700K, Python 3.14.7, numpy 2.5.4)

Whole-course routing, 8-scenario suite (`test_course_routes.py::test_print_scenario_table`, L0, 25 m mask, 200 m geofields):

| Scenario | ETA h | Steps | ms | Path points |
|---|---|---|---|---|
| A SW 12 kn | 14.64 | 56 | 350 | 32 |
| A NE 18 kn | 13.42 | 56 | 302 | 31 |
| A ICON-EU +0 h | 27.82 | 108 | 536 | 61 |
| A ICON-EU +6 h | 25.90 | 97 | 490 | 60 |
| B SW 12 kn | 15.33 | 58 | 363 | 23 |
| B NE 18 kn | 14.27 | 56 | 328 | 27 |
| B ICON-EU +0 h | 29.01 | 109 | 540 | 60 |
| B ICON-EU +6 h | 27.01 | 98 | 498 | 59 |

Every value is below 3000 ms. The ICON-EU runs end after the 24 h sample, so `horizon_hold` is true for them and false for the uniform winds.

Bench `--fixture`, 3 runs, Courses A and B, cycle = optimal + forced through the RouterPool (`var/bench-laptop-full.json`):

| Level | p50 s | p95 s | max s | optimal ms | forced ms | RSS MB | jitter ms |
|---|---|---|---|---|---|---|---|
| L0 | 0.61 | 0.62 | 0.62 | 565 | 43 | 111 | 2 |
| L1 | 0.46 | 0.47 | 0.47 | 426 | 32 | 111 | 2 |
| L2 | 0.37 | 0.38 | 0.38 | 346 | 25 | 111 | 1 |
| L3 | 0.22 | 0.23 | 0.23 | 192 | 24 | 111 | 1 |
| L4 | 0.23 | 0.23 | 0.23 | 201 | 24 | 111 | 1 |
| L5 | 0.21 | 0.23 | 0.23 | 194 | 24 | 111 | 2 |

The recommended level is L0. `--quick --fixture` takes 4.8 s wall time, fixture pack assembly included, and writes `var/bench-laptop.json` (gitignored).

## Task Commits

1. **Task 1 (tracer): Vodice to the open sea.** `fd81c02` (feat). After the commit, the tracer feedback gate re-ran the automated verify on both venvs; it was green.
2. **Task 2: course by course, sides, waves, current.** RED `d48d413` (test), GREEN `8ad46e3` (feat).
3. **Task 3: cycle, forced route, cost, evaluation, bench.** RED `8ddc3eb` (test), GREEN `f4ddc64` (feat).

## TDD Gate Compliance

The plan type is `execute`, so no plan-level TDD gate applies. Tasks 2 and 3 still followed RED then GREEN. Each RED commit failed at collection because the new modules did not exist yet (`jabuka.route.rounding`, `wave_factor`, `jabuka.route.cycle/evaluate/bench`). The RED commits did not include interface skeletons, so these failures are import errors, not assertion failures.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Accuracy] Arrival tack quantised to the step.**
- **Found during:** Task 1.
- **Issue:** With direct shots only, a tack can happen only at a step boundary. The 8 nm beat came out 2.9 % slower than the analytic VMG time, against a budget of 1 % plus one penalty.
- **Fix:** Two-board arrival shots on the VMG targets for any target inside the upwind or downwind cone. The best arrival is kept until the front time passes it. Shots use the parent's wind for at most max(2 dt, 1 h).
- **Result:** The beat ETA is exactly VMG time plus one tack penalty.
- **Commit:** fd81c02.

**2. [Rule 1 - Polar] Fake downwind targets.**
- **Issue:** Linear speed interpolation between 150° and 180° moves the 20 kn target to about 170°. The 0.9 × last-speed tail alone gave a 180° target at 6-10 kn, above the ORC run VMG.
- **Fix:** VMG-linear interpolation between downwind points of 120° and more. The 180° tail is capped at 98 % of the last given point's VMG.
- **TWA step:** 0.1° instead of the plan's 1°, so that given angles such as 37.7° are exact columns. Without it, the required ±0.02 kn at (12 kn, 37.7°) failed at a 1° step.
- **Commit:** fd81c02.

**3. [Rule 1 - Rounding] Pass-by marks.**
- **Issue:** In Course B, Plić Sestre is rounded to port while the course turns 42° to starboard. The Pattern 6 formula then asks for a 318° loop. Under bora, a single abeam waypoint was reached by going round the beacon the wrong way.
- **Fix:** When the formula's sweep exceeds 180°, emit an abeam waypoint plus an entry waypoint 45° earlier in the rounding direction. This follows the string rule (no loop).
- **Commit:** 8ad46e3.

**4. [Rule 1 - Test helper] Winding measured per rounding.**
- **Issue:** The Mulo → Vodice finish leg of Course B passes Plić Sestre again.
- **Fix:** The winding is now computed only between the arrivals at the neighbouring marks.
- **Commit:** 8ad46e3.

**5. [Rule 1 - Evaluation] False invalidations on real wind.**
- **Issue:** With 0.5 nm pieces, the router's own 30° TWA segments read 27-29° on the real ICON-EU wind.
- **Fix:** Pieces of up to 2 nm, and a route is invalid only below 25° TWA (30° minus a 5° sampling tolerance). A 40° wind rotation is still caught.
- **Commit:** f4ddc64.

**6. [Plan wording] Land-release scenario.**
- **Issue:** The plan says "Vodice start on port tack (bora)". With heading = TWD − TWA, port in the bora means headings 075-225°, into the open Šibenik channel, so the held tack never meets land.
- **Fix:** A grid search over Vodice starts found that starboard (headings W to NNE) is blocked by the Srima/Vodice shore at the first step. The test uses (43.75, 15.77) on starboard: released at t0, cost under 2 min.
- **Commit:** f4ddc64.

**7. [Plan wording] Channel gates for the Vodice exit.**
- **Issue:** In NE 18 kn the time-optimal exit is the gap north of Tijat (about 43.735 N, 15.757 E), not the Prvić-Tijat pinch. In SW 12 kn the route uses the pinch.
- **Fix:** The test accepts the pinch, the Prvić-mainland gap or the north-of-Tijat gap, each within 0.5 nm of the shipped polyline.
- **Commit:** fd81c02.

**8. [Rule 2] Unreachable cells of the geofield.**
- **Issue:** The 400 m "any" on-demand fields close narrow channels, which would drop candidates.
- **Fix:** Candidates the field cannot reach are ranked by straight-line distance after every reachable one, instead of being dropped.
- **Commit:** fd81c02.

### Minor choices within the plan's discretion

- **`rounding.expand` notes.** It takes an optional `notes` list for its French notes ("repoussé", "déjà contournée"). It raises ValueError (French, naming the mark) when a waypoint cannot be pushed clear.
- **`evaluate.first_side_change(path, after_t, tack0=0)`.** It takes `tack0` so that a tack advised at t0 is found.
- **`cycle.cycle_with_env(env, creq)`.** This is the pure core of `run_cycle`, used by the tests.
- **Bench extras.**
  - `--inprocess`, `--eff` (default 0.92) and `--polar`.
  - Exit 1 when no level passes.
  - The JSON records `vcgencmd get_throttled` and the CPU temperature at start and end.

## Issues Encountered

- **Pre-existing lint failure at base 9055678 (not fixed, out of scope).**
  - `ruff check` reports I001 (import order) in `tests/racepack/test_current.py`. That file belongs to 03-02 and is outside this plan's `files_modified`.
  - It reproduces on a clean archive of the base commit.
  - Because of it, `bash scripts/check.sh` stops at the lint step. Every other check.sh step passes: ruff check on the rest, ruff format --check, and the full suites on 3.14 and 3.13.
  - Fix, one command, for the orchestrator: `.venv/bin/ruff check --fix tests/racepack/test_current.py`.
- **Prototypes missing.** The research prototypes (`iso_proto.py`, `bench4.py`) were no longer in the scratchpad. The engine was built from the RESEARCH text.

## Verification

- Route suite with `JABUKA_REQUIRE_ROUTE=1`: 226 passed and 1 skipped (`test_oracle_lwr.py`, weatherrouting not installed) on `.venv` (3.14.7) and on `.venv313` (3.13).
- Full suite: 1027 passed and 4 skipped on both 3.14 and 3.13. The 4 skips are the lwr oracle, the two `tests/deploy/test_lock.py` wheelhouse-absent skips, and `tests/racepack/test_current.py` (netCDF4 not installed in these worktree venvs).
- Lint and format: `ruff check --no-cache src tests --exclude tests/racepack/test_current.py` is clean, and `ruff format --check src tests` reports 168 files already formatted.
- Bench: `python -m jabuka.route.bench --quick --fixture --json var/bench-laptop.json` prints `NIVEAU RECOMMANDÉ : L0` and writes p95 for L0 and L1.
- Other acceptance checks:
  - `grep -c 'importorskip("weatherrouting")'` = 1.
  - `geofields --help` exits 0.
  - `grep -c "Banc d'essai Pi"` = 1 and `grep -c L5` = 4 in `docs/ROUTING.md`.
  - `import jabuka.route.isochrone` works while `jabuka.nav` is blocked.
  - The purity scan covers the 8 new route modules.

## Human items

- **Pi benchmark gate, by 2026-11-09 (non-blocking).** On the Raspberry Pi 3B, follow `docs/ROUTING.md` "Banc d'essai Pi" with a pack prepared the same day: `PYTHONPATH=src python -m jabuka.route.bench --pack var/racepack --runs 3 --json var/bench-pi.json`. Record p50/p95/max per level, jitter, RSS, temperature and throttling. The first passing level becomes `route_level` (plan 03-05). If no level passes, the boat races on the Phase 2 laylines.
- **libweatherrouting oracle (optional).** After reviewing the [SUS] package, the owner may install it so that `tests/route/test_oracle_lwr.py` runs. Its API calls are a best guess and it skips cleanly while the package is absent.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-03-03-01 to -04 are mitigated:
- `max_steps` per leg, a front bounded by the sector count, and every failure returns `ok False`.
- Mask-aware decimation and `validate_polyline` on every shipped path.
- `from_polar_json`, `RouterSettings.problems()` and request validation.
- On-demand geofields cached per mark key.

T-03-03-SC: weatherrouting is not installed and its test uses `importorskip`.

## Next Phase Readiness

- **03-05.**
  - `RouterPool(cycle.init_worker, (pack_dir,))` with `cycle.run_cycle(CycleRequest)`.
  - `WindField.at(t, lat, lon, bias)` returns (TWD rad, TWS kn) for GRIB-only wind.
  - `LEVELS[route_level]` for the settings.
  - `CycleResult.cost_s` goes to `advice.cost_text`.
  - `forced.tacks[0]` is the earliest next tack when "On reste" is active.
  - `eta_old_now` / `old_valid` feed `should_replace`.
  - Path points follow the 03-04 follower contract.
  - Numpy must be added to the Pi lock (03-05 owns it).
- **Race-pack procedure.** After `land build`, run `python -m jabuka.prep.cli geofields --marks <marks.json> --out var/racepack`.

## Self-Check: PASSED

- All 8 new route modules, both fixtures and the 13 test modules exist.
- Commits fd81c02, d48d413, 8ad46e3, 8ddc3eb and f4ddc64 are on branch worktree-agent-af7187e06acb8d05c (5 commits since plan_head_before 9055678).
