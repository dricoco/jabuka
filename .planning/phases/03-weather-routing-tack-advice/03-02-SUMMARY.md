---
phase: 03-weather-routing-tack-advice
plan: 02
subsystem: race-pack weather prep (laptop) + Pi-side pack loader
status: complete
tags: [grib, icon-eu, ewam, copernicus, netcdf, coverage, racepack, prep]
requires: []
provides:
  - "jabuka.route.racepack: Grid, RacePack, load_pack, read_marks_file, MarksDoc, MarkPos, RaceWindow, window_from_local, DEFAULT_WINDOW_LOCAL, coverage, CoverageReport (+ infos), format_report, course_points_legs, fmt_local"
  - "jabuka.prep.cli main(): wind | waves | grib FILE [--name] | current FILE.nc | land ... | check; exit 0/2/3"
  - "jabuka.prep.dwd: parse_listing, select_run, download_all, icon_eu_urls, ewam_urls, model_steps, needed_steps, missing_steps"
  - "jabuka.prep.grib: decode_wind_files, decode_wave_files, import_generic, fill_nearest, idw_regrid, uv_from_speed_dir, wind_kind, valid_epoch"
  - "jabuka.prep.current: import_copernicus(path, crop)"
  - "jabuka.prep.wxpack: write_npz, write_cube, write_coverage, Crop, Cube, default_crop, RACE_BBOX, MARGIN_DEG"
  - "tests/fixtures/racepack/{wind_icon_eu_sample,waves_ewam_sample}.{npz,json}: real DWD 24 h samples (06 Nov 00Z)"
affects: [03-03, 03-05, 03-06, phase-4-runbook]
tech-stack:
  added: ["pygrib 2.1.8 (dev venvs only)", "netCDF4 1.7.5.1.post1 (dev venvs only)", "numpy 2.5.4 (dev venvs only)"]
  patterns:
    - "npz + <stem>.json sidecar with sha256, written atomically (atomicio); np.load(allow_pickle=False) on the Pi"
    - "valid time from eccodes validityDate/validityTime, never forecastTime arithmetic"
    - "crop with 0.25 deg margin, rows normalised to ascending latitude"
    - "route-deps guard per test module (JABUKA_REQUIRE_ROUTE=1 imports, else importorskip)"
key-files:
  created:
    - src/jabuka/prep/cli.py
    - src/jabuka/prep/grib.py
    - src/jabuka/prep/dwd.py
    - src/jabuka/prep/current.py
    - src/jabuka/prep/wxpack.py
    - src/jabuka/route/racepack.py
    - tests/racepack/conftest.py
    - tests/racepack/test_prep_wind_tracer.py
    - tests/racepack/test_pack_load.py
    - tests/racepack/test_dwd_runs.py
    - tests/racepack/test_waves.py
    - tests/racepack/test_generic_grib.py
    - tests/racepack/test_current.py
    - tests/racepack/test_coverage.py
    - tests/fixtures/racepack/grib/icon_template.grib2
    - tests/fixtures/racepack/grib/ewam_template.grib2
    - tests/fixtures/racepack/grib/sample_grib1.grb
    - tests/fixtures/racepack/dwd/icon-eu_u_10m_12.html
    - tests/fixtures/racepack/dwd/icon-eu_v_10m_12.html
    - tests/fixtures/racepack/dwd/icon-eu_u_10m_15_partial.html
    - tests/fixtures/racepack/dwd/ewam_swh_12.html
    - tests/fixtures/racepack/wind_icon_eu_sample.npz
    - tests/fixtures/racepack/wind_icon_eu_sample.json
    - tests/fixtures/racepack/waves_ewam_sample.npz
    - tests/fixtures/racepack/waves_ewam_sample.json
    - tests/fixtures/racepack/SOURCES.md
    - docs/WEATHER-PACK.md
  modified: []
decisions:
  - "GRIB valid time = eccodes validityDate/validityTime (falls back to pygrib validDate): pygrib's validDate ignores the GRIB1 P1 step"
  - "GRIB1 wind recognised by WMO parameter numbers 31-34 only when table2Version < 128 (local tables reuse the numbers, e.g. ECMWF 128/33 = rsn)"
  - "fill_nearest takes the first valid 4-neighbour (never averages) so mwd is not averaged across 0/360"
  - "DWD downloads restricted to https://opendata.dwd.de; ICON-EU listings fetched for all 8 run hours (03/09/15/21 runs also cover the window)"
  - "CoverageReport has an extra infos list (absent optional files); the core/UI can show it as an info line"
metrics:
  duration: "~32 min"
  completed: 2026-11-06
  tasks: 3
  files: 27
actuals:
  tokens: 38000
  tasks: 3
  commits: 4
plan_head_before: 347437420f839a8c03cfa35e69e883cab2603c4d
commits: 4
---

# Phase 3 Plan 02: Weather race pack Summary

ICON-EU wind and EWAM waves downloaded from DWD (complete-run selection, https-only parallel
download), any organiser GRIB1/GRIB2 and a Copernicus current NetCDF imported into sha256-checked
npz files. A numpy-only Pi loader then rejects tampered or malformed files and reports, in French,
every hour, mark, leg or factor the weather does not cover. The tools were run against the real
06 Nov 00Z DWD runs.

## What was built

- **Task 1 (tracer):** a GRIB2 file goes through `prep/grib.py` (pygrib decode, 0.25 deg margin crop, ascending rows, validity times, 200 MB / 100 MB caps). `prep/wxpack.py` writes the npz and its sidecar atomically. `route/racepack.py` holds `load_pack` (fixed names, sha256, `allow_pickle=False`, dtype/shape/monotonic/finite checks that never raise) and `coverage`. `prep/cli.py` provides `wind --from-files`, `check` and the lazy `land` dispatch. The ICON-EU template is 206 bytes, shrunk from a real DWD U_10M file.
- **Task 2:** `prep/dwd.py` parses listings, selects the run (newest run whose needed steps are all listed, partial run skipped, falls back to the previous run, or the newest complete run flagged incomplete) and downloads with at most 6 concurrent requests, 3 attempts, bz2 full-decompress integrity and an atomic cache. `decode_wave_files` and `fill_nearest` handle EWAM. `wind`/`waves` download from DWD and exit 3 when the run is incomplete. Real runs: ICON-EU 48 files (57.6 MB) in about 40 s, EWAM 48 files (7.7 MB) in 12.5 s. The committed samples are 24 h each: wind 110,848 B and waves 43,701 B.
- **Task 3:** `import_generic` reads GRIB1/2 10 m wind through several key families, including speed/direction. It regrids rotated or projected grids onto 0.025 deg with 4-point IDW and returns French errors. `prep/current.py` reads Copernicus `uo`/`vo` from a file path only, with land set to 0. The CLI gains `grib FILE [--name]` and `current FILE.nc`, and `docs/WEATHER-PACK.md` is new (135 lines). The GRIB1 fixture was built with eccodes and decodes as shortName `unknown`.

## Verification

- `JABUKA_REQUIRE_ROUTE=1 pytest tests/racepack -q -rs`: **83 passed, 0 skipped** on Python 3.14 (.venv) and 3.13 (.venv313). netCDF4 installed on both, so `test_current.py` runs on both.
- `bash scripts/check.sh`: **check: ok** (ruff lint + format, 654 passed / 2 skipped on 3.14 and 3.13; the 2 skips are the existing `tests/deploy/test_lock.py` wheelhouse-absent skips, unrelated).
- Acceptance greps: `icon_template.grib2` 206 B (< 4096); `Deutscher Wetterdienst` in SOURCES.md; `allow_pickle=False` x3 in racepack.py; samples < 204800 B; `opendata.dwd.de` x4 in dwd.py; `aucun champ de vent 10 m` exactly 1 in grib.py; `copernicusmarine` x3 in WEATHER-PACK.md, 135 lines; `import_copernicus` parameters `['path', 'crop']`.
- Real-data smoke run: `grib` on a real ICON-EU step (CCSDS-packed) imported correctly (10u/10v found, 28 x 29 grid, MÉTÉO INCOMPLÈTE for the far-away window, exit 3).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] GRIB1 valid time was the analysis time**
- **Found during:** Task 3 (GRIB1 fixture read back: P1 = 6 h but `g.validDate` = 12:00).
- **Issue:** pygrib's `validDate` ignores the GRIB1 time-range step, so an organiser GRIB1 would get all its steps stamped at the run time. That is both wrong and non-monotonic.
- **Fix:** `valid_epoch` uses eccodes' `validityDate`/`validityTime` (which honour minutes, hours and P1), falling back to `validDate`. This is still not forecastTime arithmetic. Re-checked on real ICON-EU/EWAM files: the times are unchanged.
- **Files:** src/jabuka/prep/grib.py. **Commit:** 8740de9.

**2. [Rule 3 - Blocking] Shared test helpers in `tests/racepack/conftest.py` (file not listed in files_modified)**
- Under `--import-mode=importlib`, test modules cannot import each other. The GRIB-from-template generator, the synthetic grid and the Phase 2 marks are therefore fixtures (`rp`, `write_grib`, `marks_file`). pygrib/numpy are imported lazily, so Phase 2 venvs can still collect the directory. **Commit:** 5d12a30.

**3. [Plan order] Coverage rules 2/4/5 and waves/current loading landed in Task 1**
- `racepack.coverage` was written in one piece (all five Pattern 3 rules, waves/current as warnings, info lines, `horizon_hold`). Task 3 then added the tests for them (`test_coverage.py`, 11 tests). As a result, those coverage tests passed already at the Task 3 RED commit. The RED failures there came from the generic GRIB and current modules not existing yet.

**4. [TDD] Task 2 tests were committed together with the implementation**
- Task 2 (`tdd="true"`) was committed as a single feat commit, with no separate RED commit. Task 3 followed RED (ae9c1c2, collection errors for the missing `import_generic` / `jabuka.prep.current`) and then GREEN (8740de9). The plan type is `execute`, not `tdd`, so no plan-level gate applies.

**5. [Test fix] IDW expectation corrected during GREEN**
- The first `test_idw_regrid` asserted that the edge targets get exactly the nearest column's value, which 4-point inverse distance does not do. The test now asserts the real properties: symmetric, exact midpoint, exact on a source point, NaN far away.

### Minor choices within the plan's discretion

- `CoverageReport` gained an `infos` list (default empty) for the "Vagues absentes ..." and "Courant absent ..." lines.
- `wind`/`waves` list all 8 ICON-EU run-hour directories (00..21), not only four, because the 03/09/15/21 runs also cover the window. EWAM lists 00 and 12.
- Download hosts are restricted to `opendata.dwd.de`, in addition to https only (threat T-03-02-03).
- `grib --name` is restricted to `[a-z][a-z0-9_]*` (path-traversal guard, T-03-02-05).
- `prep/__init__.py` and `route/__init__.py` were **not** created. The package works as PEP 420 namespace portions, as required. No Phase 2 file, pyproject.toml or deploy/ file was touched.

## Fixture provenance (details in tests/fixtures/racepack/SOURCES.md)

- `icon_template.grib2`: shrunk from ICON-EU 2026110512 +000 U_10M (sha256 of the .bz2 is recorded).
- `ewam_template.grib2`: shrunk from EWAM 2026110600 +000 SWH. It keeps the bitmap (missingValue approach) and the N->S rows.
- DWD listings: real listings fetched 06 Nov ~03:40 UTC. `icon-eu_u_10m_15_partial.html` is the real 15Z listing **trimmed** to +000..+030 to reproduce a run still being published.
- `wind_icon_eu_sample` / `waves_ewam_sample`: real 06 Nov 00Z runs, 24 hourly steps, built by the tools themselves.
- `sample_grib1.grb`: synthetic GRIB1 built with eccodes 2.50.0 (centre 7, table2Version 50, params 33/34, rows N->S, +6 h).

## Human items (non-blocking, also in docs/WEATHER-PACK.md)

- **Friday 13 Nov before departure:** run `jabuka-prep wind` and `jabuka-prep waves` after about 15:40 UTC (12Z run complete), check that `coverage.txt` says `COUVERTURE MÉTÉO : OK`, then copy the pack to the Pi.
- **Copernicus current:** the owner logs in with `copernicusmarine login`, runs the documented `subset` command, then runs `jabuka-prep current current_med.nc`. The real file layout is still an assumption (RESEARCH A4), so this is the first real check.
- **Organiser forecast:** when it is published, run `jabuka-prep grib <file> --name wind_organiser` and keep whichever wind file the skipper prefers.
- The console script `jabuka-prep` is declared by plan 03-05. Until then, use `python -m jabuka.prep.cli`.

## Known Stubs

None. The `land` subcommand dispatches to `jabuka.prep.land`, which plan 03-01 owns. While that module is absent, `land` prints a clear error and exits 2. This is intentional cross-plan coupling (documented in the plan), not a stub.

## Threat Flags

None. The new surface (https download from opendata.dwd.de, user-supplied GRIB/NetCDF parsing, npz loading on the Pi) is exactly the plan's threat register. Mitigations applied:
- T-01: `allow_pickle=False`, sha256 and schema checks, errors as strings; tested with object arrays and corrupt files.
- T-02: 200 MB input cap before parsing, 50 MB per download, 100 MB bz2 output cap.
- T-03: https + host allow-list, bz2 integrity, atomic cache, partial runs refused.
- T-04: path-only importer, tested for no credential parameter.
- T-05: fixed pack file names, `--name` regex.
- T-06: coverage on both the laptop and the Pi, exit 3 and the `MÉTÉO INCOMPLÈTE` banner text.

## Self-Check: PASSED

- Files: all 27 key files exist (checked with `git ls-files`).
- Commits: 5d12a30, 28740ea, ae9c1c2 and 8740de9 are present on branch worktree-agent-ae0d8fe96298092a8.
