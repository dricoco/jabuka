# Route test fixtures: attribution

`landmask_race_25m.npz` / `landmask_race_25m.json` are derived from OpenStreetMap data.

© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)

## Coastline

- Query (Overpass API, https://overpass-api.de/api/interpreter):
  `[out:json][timeout:180];way["natural"="coastline"](42.7,14.9,44.1,16.4);out geom;`
- OSM base timestamp: `2026-11-06T02:01:33Z` (934 ways)
- The response was fetched with that query on 2026-11-06 during phase 3 research and reused from
  the prep cache (`var/cache/prep/osm-37d73116fc1162e1.json`): overpass-api.de refused
  connections from the build laptop when the fixture was built.

## Build

```bash
.venv/bin/python -m jabuka.prep.land build --out var/racepack-fixture --offline
cp var/racepack-fixture/landmask.npz tests/fixtures/route/landmask_race_25m.npz
cp var/racepack-fixture/landmask.json tests/fixtures/route/landmask_race_25m.json
```

Defaults: 25 m cells, 100 m shore margin, local frame lat0 43.4 / lon0 15.65, grid over
15.0–16.3 E, 42.8–44.0 N (5334 x 4199 cells).

- sha256 (`landmask_race_25m.npz`): `a63eb3b3820435e235882b87b1382433ed3ca44c7fe28c0cd7a84cd19b6c063f`
- 129418 bytes, 474 land faces, 0 unclassified

`osm/coastline_mini.json` is hand-written (not OSM data).
