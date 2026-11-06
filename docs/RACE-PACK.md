# Race pack: offline map and polar

The Pi has no internet during the race. Everything the tablets show on the map comes from the
**race pack**, a directory you build on the laptop before departure and copy to the Pi at
`/var/lib/jabuka/racepack`. The core reads it once at startup.

| File | What it is | Built by |
|---|---|---|
| `race.pmtiles` | Protomaps vector basemap of the race box 15.0,42.8 → 16.3,44.0, zoom 0–14 (gzip MVT) | `jabuka-prep-map` |
| `seamarks.geojson` | Night hazards from OpenStreetMap: lights, beacons, buoys, rocks, wrecks, obstructions, landmarks, marine farms | `jabuka-prep-map` |
| `coastline.geojson` | OSM coastline (islands as polygons): land/water when there are no tiles | `jabuka-prep-map` |
| `racepack.json` | Manifest: bbox, maxzoom, Protomaps build date, sources, sha256 and size of each file above, fallback, warnings | `jabuka-prep-map` |
| `polar.json` | The boat polar (optional; without it the core uses the interim ORC X-35 polar) | `jabuka-prep-polar` |

All of it is generated and gitignored (`var/`). Rebuild it at any time with the commands below.

## Prerequisites (laptop)

- Internet access (build.protomaps.com, download.geofabrik.de; github.com only for `--extractor go`).
- The dev environment: `bash scripts/bootstrap-dev.sh` (installs the `prep` extra, which includes
  `osmium` for the seamarks).
- About 300 MB free under `var/` (200 MB OSM download cache + 15 MB pack).

## Build

```bash
.venv/bin/jabuka-prep-map --out var/racepack
```

What happens, and what to expect:

1. **Basemap.** The tool probes the Protomaps daily builds from today back 7 days (HTTP HEAD) and
   extracts the race box from the newest one into `race.pmtiles`: about **12 MB, 6 190 tiles,
   about 10 s**, in about 40 HTTP range requests.
   - The default extractor is in-process Python, using the pinned `pmtiles` package. No executable
     is downloaded.
   - `--extractor go` (or `--pmtiles-bin PATH`, or a `pmtiles` on your PATH) uses go-pmtiles
     1.31.2 instead. Its release tarball is checked against the sha256 pinned in
     `src/jabuka/prep/map.py` before anything is unpacked.
2. **Seamarks + coastline.** The tool downloads the Geofabrik Croatia extract (about **200 MB, under
   a minute**). The file is cached in `var/cache/` and reused for 2 days. A single osmium pass then
   writes `seamarks.geojson` (about 1 000 features, 0.3 MB) and `coastline.geojson` (about 450
   features, 1.6 MB), in **about 10 s**.
   - Use `--pbf FILE` to give it a `.osm.pbf` you already have.
   - Use `--skip-seamarks` to build the basemap only.
3. **Manifest.** `racepack.json` is written last. The tool then prints a summary (file sizes, tile
   count, zoom range, build date, counts, warnings) and the copy commands.

Other options: `--bbox W,S,E,N`, `--maxzoom N` (at most 15), `--date YYYYMMDD` (the newest build
to try), `--cache DIR`.

Exit codes: 0 ok, 1 build failed (or the OSM step failed: the pack is written but incomplete),
2 usage error, 3 `--check` failed.

### The 7-day Protomaps window

Protomaps keeps each daily build for **one week only**. A build made more than 7 days ago cannot be
re-downloaded. Rebuild the pack on **11 or 12 November** from a fresh build, then check it and copy
it to the Pi.

### Fallbacks (`fallback` in racepack.json)

| Value | Meaning | What the tablet shows |
|---|---|---|
| `null` | Full basemap at the requested maxzoom | Protomaps map + seamarks |
| `maxzoom-12` / `maxzoom-10` | The z14 extract failed, so a smaller one was used | Same map, less detail when zoomed in |
| `coastline-only` | No build reachable or every extract failed | Land/water drawn from `coastline.geojson`, plus seamarks |

A coastline-only build still exits 0, but prints a loud `COASTLINE-ONLY PACK` banner. Any previous
`race.pmtiles` in the directory is moved to `race.pmtiles.old` and is not served. Rebuild with
internet before departure. If there is neither a basemap nor a coastline, the build fails (exit 1).

## Check before leaving the dock

```bash
.venv/bin/jabuka-prep-map --check var/racepack
```

The check validates the following, and prints `check ok` or one `CHECK FAILED` line per problem
(exit 3):
- the `race.pmtiles` header: vector tiles (MVT), gzip, bounds covering the bbox, maxzoom as in the
  manifest;
- the sha256 and size of every file in the manifest;
- both GeoJSON files: a FeatureCollection, Points for seamarks, LineString/Polygon for the
  coastline, finite coordinates inside the bbox (the coastline may extend 0.3° past it);
- a coastline is present when there are no tiles.

## Copy to the Pi

Join the `jabuka` Wi-Fi (or use Ethernet and `jabuka.local`), then:

```bash
rsync -a --delete var/racepack/ <user>@10.42.0.1:/tmp/racepack/
ssh <user>@10.42.0.1
sudo rsync -a --delete /tmp/racepack/ /var/lib/jabuka/racepack/
sudo chown -R jabuka:jabuka /var/lib/jabuka/racepack
sudo systemctl restart jabuka-core
```

Then open **Diag** on a tablet. The `racepack` health row must show `tiles true` (or `tiles false`
with `coastline true` for a coastline-only pack). The map must render with Wi-Fi as the only
connection, so the tablet has no internet. Check that you can see Plić Sestre (beacon), Blitvenica
and Mulo (lights).

`jabuka-core` reads `/var/lib/jabuka/racepack` by default (`--data-dir /var/lib/jabuka`).
`--racepack DIR` overrides it, which is how the dev core is pointed at `var/racepack`:

```bash
.venv/bin/jabuka-core --data-dir var/dev --racepack var/racepack
```

## Polar

Without `polar.json` in the pack, the core uses the **interim polar**: "X35 ORC OD 2019
(intérim)", derived from the ORC X-35 One Design certificate. The polar in use is shown in the nav
message (`polar.name`, visible on Diag and the helm). Your own polar takes over as soon as it is
in the pack:

```bash
.venv/bin/jabuka-prep-polar "polaire générique X35.pol" --name "X35 owner" --out var/racepack/polar.json
```

- **Formats** are detected by content:
  - OpenCPN / qtVlm grids (first cell `TWA\TWS` or `twa/tws`; separator tab, `;`, `,` or spaces;
    decimal commas with `;` or tab; empty and zero cells ignored; an optional boat-name line).
  - Expedition files (`!` comments, `TWS TWA BSP TWA BSP …`).
  - ORC certificate tables (`Beat Angles`, `Beat VMG`, `52°` … `150°`, `Run VMG`, `Gybe Angles`,
    as CSV, `;` or pdftotext columns).
  - The race-pack JSON itself.
- **Checks:** every number must be finite, with TWS in (0, 60] kn, TWA in (0, 180]°, BSP in
  [0, 30] kn, at least 2 TWS curves and at most 1 MB. A bad value is reported with its line number
  (exit 2) and nothing is written.
- **Sanity check:** the tool prints the VMG target table (TWS | up TWA / BSP | down TWA / BSP, for
  6–20 kn). Compare it with what the boat really sails before you copy it. These speeds are raw
  polar speeds; the efficiency setting (Réglages, default 0.92) scales them on board.
- **Copy:** `polar.json` travels with the pack (same rsync as above). Restart `jabuka-core` and
  check the polar name on Diag. If the core cannot validate `polar.json`, it falls back to the
  interim polar.

`polar.json` is not listed in `racepack.json`, so you can re-convert the polar without rebuilding
the map, and `jabuka-prep-map --check` still passes.

## Licence and attribution

The map data is © OpenStreetMap contributors, under ODbL 1.0. The race pack is a Produced Work.
The basemap tiles are built by Protomaps (the code is BSD-3; the data is ODbL). `racepack.json`
records the attribution `© OpenStreetMap contributors (ODbL), Protomaps`, and the map styles show
"Protomaps © OpenStreetMap".
