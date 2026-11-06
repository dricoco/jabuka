---
phase: 03-weather-routing-tack-advice
plan: 01
subsystem: route/land-mask
status: complete
tags: [routing, land-mask, osm, numpy, shapely, ROUT-11, ROUT-01]
requires: []
provides:
  - "src/jabuka/route/frame.py: Frame, DEFAULT_FRAME (lat0 43.4, lon0 15.65), RACE_BBOX, NM_M"
  - "src/jabuka/route/landmask.py: LandMask (load, points_clear, segments_clear, raw_segments_clear, fine_pass_needed, near_land, snap_clear, validate_polyline), segments_touch, flood_reachable, GeoField, compute_geofield, coarse_blocked, save_geofields, load_geofields"
  - "src/jabuka/prep/land.py: main (build/check), build_mask, coastline_to_land, rasterize, classify_hazards, load_user_hazards, REQUIRED_SEA_POINTS, disc_clear, check"
  - "tests/fixtures/route/landmask_race_25m.{npz,json} (real 25 m race-area mask with hazards, ODbL) + ATTRIBUTION.md"
  - "tests/route/test_route_purity.py: purity scan of every src/jabuka/route/*.py"
  - "docs/ROUTING.md (land mask section)"
affects: [03-02, 03-03, 03-04, 03-05, 03-06]
tech-stack:
  added: ["numpy 2.5.4 and shapely 2.2.0 installed dev-only into .venv/.venv313 (03-05 declares them)"]
  patterns:
    - "Route-deps guard: JABUKA_REQUIRE_ROUTE=1 imports numpy/shapely directly, else pytest.importorskip"
    - "npz race-pack files: packbits + 0-d scalars/strings, np.load(allow_pickle=False), key/dtype/shape validation, sha256 sidecar"
    - "Exact raster traversal for segment checks (grid-line crossings), coarse 8x8 near grid in front"
key-files:
  created:
    - src/jabuka/route/__init__.py
    - src/jabuka/route/frame.py
    - src/jabuka/route/landmask.py
    - src/jabuka/prep/land.py
    - tests/route/test_frame.py
    - tests/route/test_land_prep.py
    - tests/route/test_landmask.py
    - tests/route/test_island_crossings.py
    - tests/route/test_connectivity.py
    - tests/route/test_route_purity.py
    - tests/fixtures/route/landmask_race_25m.npz
    - tests/fixtures/route/landmask_race_25m.json
    - tests/fixtures/route/osm/coastline_mini.json
    - tests/fixtures/route/ATTRIBUTION.md
    - docs/ROUTING.md
  modified: []
decisions:
  - "Segment checks use an exact raster traversal (every cell the segment passes through) instead of half-cell sampling: strictly safer, same cost order"
  - "flood_reachable joins row runs with union-find instead of alternating row/column passes (9.2 s -> 0.4 s on the 22 Mcell mask, same result)"
  - "Geodesic fields use 16-neighbour moves (8-neighbour cannot meet 3 % accuracy) relaxed by Gauss-Seidel row sweeps (9.7 s -> 0.4 s at 200 m) and bilinear lookup"
  - "check fails (exit 1) on any required point outside the grid, inside the mask or unreachable, and when the Prvic-Tijat 0.1 nm disc is not clear; build always ends with check"
  - "Rocks with water level dry/always_dry/partly_submerged_at_high_water are treated like awash/covers (full hazard margin)"
metrics:
  duration: "about 31 min"
  completed: 2026-11-06
  tasks: 3
  files: 15
actuals:
  tokens: 28300
  tasks: 3
  commits: 3
plan_head_before: 347437420f839a8c03cfa35e69e883cab2603c4d
---

# Phase 3 Plan 01: Never cross land Summary

A 25 m OSM land and hazard raster of the race area is built on the laptop: land plus a 100 m
shore margin, charted dangers plus 200 m, and Plić Sestre built in. A numpy-only runtime loads it
without pickle, checks segments exactly (straight lines through Prvić, Zlarin and Tijat are
rejected) and proves that every required channel stays open. A committed fixture makes the
whole suite run offline.

## What was built

- **`route/frame.py`**: the shared local equirectangular frame in nm (`Frame.to_xy/to_ll/to_m/from_m`, scalar or vectorised), `DEFAULT_FRAME`, `RACE_BBOX`.
- **`route/landmask.py`** (numpy only, no clock, no network):
  - `LandMask.load` validates every key, dtype, shape and finite scalar, rejects object arrays and non-npz files, and unpacks with `np.unpackbits(count=nx)`.
  - `segments_clear` runs a coarse pass first: segments are sampled at block spacing on an 8 x 8 "near" grid dilated by one block, with outside the grid counted as blocked. Only segments near something blocked go through the exact traversal. The results equal the exact pass alone, tested on 5000 random archipelago segments.
  - Also provided: `raw_segments_clear`, `points_clear`, `near_land` (cached zone rasters per distance), `snap_clear` (nearest clear cell centre within `max_nm` whose exit segment avoids raw land) and `validate_polyline`.
  - `flood_reachable` labels row runs with a cumsum and joins vertically touching runs with union-find: exact 4-connectivity.
  - `compute_geofield` works in `centre` mode (prep, 200 m) or `any` mode (on demand, 400 m), seeds with exact distances, uses 16-neighbour moves with corner-cut checks and Gauss-Seidel sweeps. Also `GeoField.distance` (bilinear interpolation, inf when unreachable or outside) and `save_geofields`/`load_geofields` (keys `(lat, lon, radius_nm)`, `allow_pickle=False`).
- **`prep/land.py`** (laptop):
  - Overpass fetch: User-Agent, 180 s timeout, 64 MB chunked cap, schema validation, atomic cache `osm-<sha16>.json`, plus `--offline` and `--refresh`.
  - `coastline_to_land`: linemerge, clip, polygonize, classification by the land-on-the-left rule. A failure is raised if any face stays unclassified.
  - `rasterize`: even-odd scanline fill with cell-centre semantics, using uint8 parity toggles.
  - Hazard classes: awash/covers rocks, isolated-danger beacons and buoys, wrecks, obstructions and reefs/shoals get 50 m discs or 25 m way buffers plus the 200 m margin. Submerged rocks get 50 m discs behind `--submerged-rocks` (on by default). The Plić Sestre hand hazard (nodes 498394251 and 8883790953) is always included.
  - `--hazards FILE.geojson`: 5 MB cap, type and coordinate validation, French errors.
  - Output: packbits npz plus a sha256 sidecar with hazard counts.
  - `check` verifies the sha256, floods from Vodice, prints each `REQUIRED_SEA_POINTS` entry with its geodesic nm from Vodice, and reports the Prvić–Tijat pinch. `build` always runs `check` at the end.
- **Fixture** (`tests/fixtures/route/landmask_race_25m.npz`): 131,696 bytes, sha256 `d0788629…`. Grid 5334 x 4199, 474 land faces, 0 unclassified. Hazards: 55 awash/covers rocks, 757 submerged rocks, 24+3 isolated-danger marks, 9 wrecks, 13 obstructions, 5 reefs, 2 shoals, 2 hand hazards. `check` reports every required point ok (Plić Sestre anchors 4.4 nm by water from Vodice, Jabuka 43 nm, Blitvenica 13.4 nm, Mulo 16.1 nm) and the Prvić–Tijat passage open.
- **`docs/ROUTING.md`**: land mask section covering sources, defaults, gap rule, channel table, rebuild, reading the check report, and its limits.

## Verification

- `JABUKA_REQUIRE_ROUTE=1 pytest tests/route -q`: 63 passed on Python 3.14 (`.venv`) and 3.13 (`.venv313`), no skips.
- `bash scripts/check.sh`: `check: ok`, 634 passed and 2 skipped on each Python. The 2 skips are pre-existing and outside `tests/route`.
- `python -m jabuka.prep.land check tests/fixtures/route/landmask_race_25m.npz` exits 0. A build with `--shore-margin-m 450` exits 1 and names the Prvić–Tijat passage.
- Acceptance greps all pass: the fixture is under 256,000 bytes; `ATTRIBUTION.md` contains "OpenStreetMap contributors" and "hazard"; the sidecar sha256 equals `sha256sum` of the npz; `498394251` appears in `prep/land.py`; `docs/ROUTING.md` has 111 lines and mentions Prvić; no commit touches `src/jabuka/prep/__init__.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Overpass unreachable from the laptop**
- **Found during:** Task 1 (precondition check).
- **Issue:** overpass-api.de refused TCP connections on IPv4 (curl exit 7) and IPv6 gave "Cannot assign requested address", both from inside and outside the sandbox. Trying alternate Overpass mirrors was denied by the permission classifier.
- **Fix:**
  - Coastline: the research session's real Overpass response for the identical query (`osm_base 2026-11-06T02:01:33Z`, 934 ways) was placed in the prep cache under the builder's own cache key. The builder then ran with `--offline`.
  - Hazards: the plan's hazard selection was exported with a one-off pyosmium script from the research session's Geofabrik `croatia.osm.pbf` (2026-11-04T21:21Z), written in the Overpass `out geom` layout and placed in the cache. The script is in the scratchpad, not in the repo. The export is a strict superset of the research session's Overpass hazard response: every element is present.
  - The provenance is documented in `tests/fixtures/route/ATTRIBUTION.md` and `docs/ROUTING.md`.
- **Follow-up:** re-run `jabuka-prep land build` with live Overpass during the Friday race-pack prep. The code path (fetch, validate, cache) is unit-tested with mocks but has not been exercised against the live server in this plan.
- **Commits:** 66377b0, 675d29c

**2. [Rule 2 - Safety] Exact raster traversal instead of half-cell sampling**
- **Issue:** half-cell sampling can miss a corner clip, so it cannot guarantee "no segment reported clear that touches a blocked cell" against quarter-cell brute force.
- **Fix:** the fine pass looks up the cells on both sides of every grid-line crossing, plus both end cells. It is strictly safer and costs about the same.
- **Tests:** the coarse+fine result equals the exact pass exactly, never reports clear where quarter-cell brute force finds a blocked cell, and agrees with it on more than 99.5 % of segments.
- **Commit:** 66377b0, 675d29c

**3. [Rule 1 - Plan inconsistency] Skip-rate assertion**
- **Issue:** "≥ 40 % of the 5000 random segments skip the fine pass" cannot hold. Only 37.5 % of that sample is clear at all, and only clear segments can skip. Measured overall skip rate: 28.7 %.
- **Fix:** the test now asserts that at least 60 % of the clear segments skip (measured 77 % on the land-only mask; still passes with hazards) and at least 20 % overall. 8 x 8 blocks were measured as the fastest block size.
- **Commit:** 675d29c

**4. [Rule 1 - Performance] flood_reachable**
- **Issue:** alternating row/column passes took 9.2 s on the 22 Mcell mask.
- **Fix:** row runs joined by union-find (still run-based, exact 4-connectivity, no passes) take 0.42 s with an identical reachable set.
- **Interface change:** the `max_passes` parameter is gone.
- **Tests:** "far fewer passes than the path length" became BFS equivalence on 20 random grids plus a timed 2001² serpentine with a path of about a million cells.
- **Commit:** b94ead6

**5. [Rule 1 - Accuracy/performance] compute_geofield**
- **Issue:** 8-neighbour chamfer error reaches 8 %, and Jacobi relaxation took 9.7 s.
- **Fix:**
  - 16-neighbour moves (2.74 % worst case), each blocked when it cuts through a blocked cell.
  - Gauss-Seidel row sweeps with a segmented running minimum along rows: same fixed point, 0.38 s.
  - Bilinear `distance()`.
- **Interface additions:** `seed_radius_nm` and `max_iter` parameters, and a `coarse_blocked` helper.
- **Commit:** b94ead6

**6. [Rule 2] check is stricter than the plan text**
- It also fails on a closed Prvić–Tijat disc and on points outside the grid ("hors de la grille").
- It accepts `DIR` or `FILE.npz`.
- Task 1's tests that ran `check` on the mini grid now expect exit 1, and the sha256 mismatch test moved to the real fixture.
- **Commit:** b94ead6

**7. Minor**
- `--refresh` flag added.
- `coastline_mini.json` splits the mainland chain into two ways, which exercises `linemerge`.
- Rocks with water level dry/always_dry/partly_submerged_at_high_water get the full hazard margin.
- `snap_clear`'s nearest-cell test checks minimality by brute force instead of a fixed 0.2 nm bound. With the Vodice danger beacon the nearest clear cell is 0.202 nm away.

## Known Stubs

None.

## Threat Flags

None. The only network surface (the Overpass fetch on the laptop) is in the plan's threat model, and its mitigations are implemented: timeout, size cap, schema validation, cache, `allow_pickle=False` and a sha256 check.

## Notes for downstream plans

- 03-02 (racepack, cli): call `jabuka.prep.land.main(argv)` for `jabuka-prep land …`. `build_mask(..., bbox=...)` exists for small test grids.
- 03-03 (router):
  - `LandMask.segments_clear` takes arrays of segments.
  - Use `near_land(x, y, 1.0)` for the fine-step rule and `snap_clear` for a start or target inside the margin.
  - Use `validate_polyline` for final validation.
  - Use `compute_geofield(lm, [(x, y)], 200/1852, "centre", seed_radius_nm=r)` for ranking. Prep cost is about 0.4 s per field at 200 m; 400 m "any" mode takes 0.1 s.
- The purity scan covers every `src/jabuka/route/*.py` automatically.

## Self-Check: PASSED

- All 15 files in key-files.created exist.
- Commits 66377b0, 675d29c and b94ead6 are present on `worktree-agent-a60c40880d8d1517b`.
