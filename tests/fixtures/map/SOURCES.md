# Map test fixtures

## sibenik.pmtiles

Offline vector tiles (Protomaps basemap v4, gzip MVT) around Šibenik: Plić Sestre, Zlarin, Prvić,
Vodice. Used by `tests/web/test_tiles.py` and the headless UI tests (`tests/ui/`).

| | |
|---|---|
| Upstream build | `https://build.protomaps.com/20261105.pmtiles` (Protomaps daily build, planetiler 0.10.2, basemap 4.15.2, OSM replication 2026-11-05T04:00:00Z) |
| Intermediate | research extract (2026-11-06): `pmtiles extract https://build.protomaps.com/20261105.pmtiles race.pmtiles --bbox=15.0,42.8,16.3,44.0 --maxzoom=14` with go-pmtiles 1.31.2 (`go-pmtiles_1.31.2_Linux_x86_64.tar.gz`, sha256 `3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f`, equal to the GitHub release asset digest); intermediate sha256 `2c7da0b8e3cd3c0924f180f0aa5032fa6e760950ebbe9d6df264bb4de8b77bef`, 12 138 328 bytes |
| Command | `python tests/fixtures/map/subset_pmtiles.py race.pmtiles tests/fixtures/map/sibenik.pmtiles --bbox 15.70,43.62,15.95,43.80 --minzoom 8 --maxzoom 11` (pmtiles 3.8.1 reader/writer: tiles copied byte for byte) |
| Content | 8 tiles, zoom 8–11, bbox 15.70,43.62,15.95,43.80 |
| sha256 | `b11a15c5f820d2bd8f4947190e56cd11a6cf37fd354ce1bc1db7385ee848eaab` |
| Size | 476 025 bytes |

Why zoom 8–11 and not 0–12: the zoom 0–7 tiles are world/region-scale (about 700 KB for the race
area alone) and zoom 12 adds 340 KB; the fixture must stay under 600 KB. The go-pmtiles binary
could not be executed in the unattended build session (sandbox policy on downloaded executables),
so the subset was cut from the intermediate extract with the pinned Python `pmtiles` package.
Re-cut at any time with the command above; a fresh extract from a newer daily build gives
equivalent (not byte-identical) tiles.

**Licence / attribution:** © OpenStreetMap contributors (ODbL 1.0, produced work), basemap
© Protomaps (BSD-3 code, ODbL data). Attribution string in the map styles:
"Protomaps © OpenStreetMap".

## seamarks-mini.geojson

Hand-written FeatureCollection of three Point seamarks with the OSM positions verified on
2026-11-06 (02-RESEARCH.md "Race Marks"): Plić Sestre `beacon_isolated_danger` (node 498394251),
Blitvenica `light_major` (node 1377046673), Hrid Mulo `landmark` (node 498383293).
© OpenStreetMap contributors, ODbL 1.0.
