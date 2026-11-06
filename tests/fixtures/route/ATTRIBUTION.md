# Route test fixtures: attribution

`landmask_race_25m.npz` / `landmask_race_25m.json` are derived from OpenStreetMap data.

© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)

## Coastline (land)

- Query (Overpass API, https://overpass-api.de/api/interpreter):
  `[out:json][timeout:180];way["natural"="coastline"](42.7,14.9,44.1,16.4);out geom;`
- OSM base timestamp: `2026-11-06T02:01:33Z` (934 ways, 474 land faces, 0 unclassified)
- Fetched with that query on 2026-11-06 during phase 3 research and reused from the prep cache
  (`var/cache/prep/osm-37d73116fc1162e1.json`): overpass-api.de refused connections from the
  build laptop when the fixture was built.

## Seamark hazards

- Query (`jabuka.prep.land.HAZARD_QUERY`, same bbox):
  `node["seamark:type"~"^(rock|beacon_isolated_danger|buoy_isolated_danger|wreck|obstruction)$"]`,
  `way["seamark:type"="obstruction"]`, `nwr["natural"~"^(reef|shoal)$"]`, `out geom`
- Overpass was unreachable, so the same selection was exported with pyosmium from the Geofabrik
  Croatia extract (`croatia-latest.osm.pbf`, replication timestamp `2026-11-04T21:21:03Z`) into
  the Overpass `out geom` layout and placed in the prep cache
  (`var/cache/prep/osm-74653c1c1d05a83a.json`). It is a superset of the Overpass hazard response
  fetched during research (every element of that response is present).
- Hazard counts: rock awash/covers 55, rock submerged or without water level 757,
  beacon_isolated_danger 24, buoy_isolated_danger 3, wreck 9, obstruction 13, natural=reef 5,
  natural=shoal 2, plus the 2 built-in Plić Sestre hand hazards (OSM nodes 498394251, 8883790953).

## Build

```bash
.venv/bin/python -m jabuka.prep.land build --out var/racepack-fixture --offline
cp var/racepack-fixture/landmask.npz tests/fixtures/route/landmask_race_25m.npz
cp var/racepack-fixture/landmask.json tests/fixtures/route/landmask_race_25m.json
```

Defaults: 25 m cells, 100 m shore margin, 200 m hazard margin (50 m discs for point hazards,
25 m buffer for ways), submerged rocks as 50 m discs without margin. Local frame lat0 43.4 /
lon0 15.65, grid over 15.0–16.3 E, 42.8–44.0 N (5334 x 4199 cells).

- sha256 (`landmask_race_25m.npz`): `d07886296449346e2199efc86362f435896f5d4376560389b5fa38b5d71c4b9d`
- 131696 bytes

`osm/coastline_mini.json` is hand-written (not OSM data).
