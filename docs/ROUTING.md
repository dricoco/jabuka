# Routing

Weather routing for Regata Jabuka (Phase 3). This document grows section by section: the land
mask first (plan 03-01), then the router and the race-day procedure (plans 03-03, 03-06).

## Land mask (never cross land, ROUT-11)

The router may only produce routes whose every segment stays in clear water. "Clear" is decided
on a raster built on the laptop and copied to the Pi in the race pack:

- `landmask.npz`: two boolean grids, packed with `np.packbits` along the rows.
  - `mask` (what the router uses): land + shore margin, charted hazards + hazard margin, and
    submerged rocks as small discs.
  - `raw`: land only. Used to get out of the margin when the boat starts inside it (marina,
    close to shore): the exit segment only has to avoid real land.
- `landmask.json`: sidecar with the sha256 of the npz, the OSM timestamps, the cell size,
  the margins and the hazard counts.

The Pi loads the npz with numpy only (`np.load(..., allow_pickle=False)`, every key, dtype and
shape checked). Shapely and the network are only used on the laptop.

### Data sources

| Layer | Source | Notes |
|---|---|---|
| Land | OSM `natural=coastline` via Overpass, bbox 42.7–44.1 N, 14.9–16.4 E | Ways merged and polygonized; each face classified with the OSM rule "land on the left of the coastline direction". Zero unclassified faces is required. |
| Hazards | OSM seamarks via Overpass: rocks, `beacon_isolated_danger`, `buoy_isolated_danger`, wrecks, obstructions, `natural=reef/shoal` | Same bbox. |
| Hand hazards | Built in: Plić Sestre beacon (node 498394251) and rock (node 8883790953) | Always added, even if OSM loses them. |
| Extra hazards | `--hazards FILE.geojson` | Dangers seen on the paper chart or in the sailing instructions. |

OSM data © OpenStreetMap contributors, ODbL 1.0. The committed test fixture
(`tests/fixtures/route/landmask_race_25m.npz`) carries its attribution in
`tests/fixtures/route/ATTRIBUTION.md`.

### Defaults

| Setting | Default | Flag |
|---|---|---|
| Cell size | 25 m (5334 x 4199 cells over 15.0–16.3 E, 42.8–44.0 N) | `--cell-m` |
| Shore margin | 100 m around all land | `--shore-margin-m` |
| Hazard margin | 200 m around awash/covering rocks, isolated-danger marks, wrecks, obstructions, reefs, shoals and the hand hazards (points are 50 m discs, ways a 25 m buffer, before the margin) | `--hazard-margin-m` |
| Submerged rocks | 50 m discs, no extra margin (depth unknown in OSM; 757 in the race area) | `--submerged-rocks` / `--no-submerged-rocks` |

Segment checks are exact on the raster: every cell a segment passes through is looked up, never
just the endpoints. A coarse 200 m grid first skips segments far from anything blocked; the
answer is the same as the exact pass (tested on 5000 random segments).

### Gap rule and the channels of the course

A gap of width `g` between two obstacles stays open when `g > 2 x margin + 2 x cell` (hazard
discs inside the gap count too). With the defaults that is 250 m. The guaranteed clearance from
real land is about `margin - 0.71 x cell`, i.e. 82 m.

Channel widths measured in research (exact polygon distance, OSM 2026-11-06):

| Gap | Width | Default mask | Course |
|---|---|---|---|
| Prvić–Tijat | 1065 m | open (narrowest point of Vodice → open sea, 43.7229 N 15.7828 E) | required |
| Prvić–mainland (Vodice side) | 824 m | open | alternative exit |
| Galijola–Prvić | 549 m | open by the gap rule (hazard discs inside not checked) | — |
| Obonjan–Zmajan | 419 m | open by the gap rule (hazard discs inside not checked) | — |
| Logorun–Tijat | 412 m | open by the gap rule (hazard discs inside not checked) | — |
| Obonjan–Sestrica Vela | 288 m | closed on purpose (too tight at night) | — |
| Kamenica–Tijat | 260 m | closed on purpose | — |
| Prvić–Lupac | 255 m | closed on purpose | — |

Raising the shore margin to about 400 m still leaves the course feasible but closes
Prvić–mainland. At 450 m the Prvić–Tijat check fails.

### Rebuild

On the laptop, with internet (Overpass answers are cached in `var/cache/prep/` and reused):

```bash
.venv/bin/python -m jabuka.prep.land build --out var/racepack
# offline rerun from the cache (e.g. on the boat):
.venv/bin/python -m jabuka.prep.land build --out var/racepack --offline
# force a fresh download:
.venv/bin/python -m jabuka.prep.land build --out var/racepack --refresh
# extra dangers from the chart (GeoJSON in lon/lat; Points, LineStrings, Polygons; max 5 MB):
.venv/bin/python -m jabuka.prep.land build --out var/racepack --hazards dangers.geojson
```

`build` always ends with `check` and exits 1 when a required channel is closed: do not copy
that mask to the Pi; lower the margins or fix the extra hazards instead.

If overpass-api.de refuses connections (it did on 2026-11-06 from the build laptop), use a
cached answer: the cache file name is `osm-<first 16 hex of sha256(query)>.json`, holding an
Overpass `out geom` JSON. The committed fixture was built that way (see its ATTRIBUTION.md).

### Reading the check report

```bash
.venv/bin/python -m jabuka.prep.land check var/racepack
```

It prints the cell size, margins, OSM timestamp and blocked fraction, verifies the sidecar
sha256, then one line per required sea point: the Vodice start, the open sea to the south-west
and the rounding anchors of Plić Sestre (0.3 nm), Jabuka (0.6 nm), Blitvenica (0.55 nm) and
Mulo (0.5 nm), each with its geodesic distance by water from Vodice (200 m grid; `-` when that
coarse grid closes a narrow channel the fine raster keeps open) and `ok` or the reason it fails
(`dans le masque`, `inaccessible`, `hors de la grille`). The last line is the Prvić–Tijat
passage: every cell within 0.1 nm of its narrowest point must be clear (`ouvert`). Exit code 0
means every required point is reachable by water from Vodice.

### What the mask does not know

Absence of a hazard in OSM is not proof that the water is clear. Check the paper chart around
Jabuka and Blitvenica in particular (OSM shows no hazard within 1.5 nm of either) and add what
you find with `--hazards`. Submerged rocks have no depth in OSM; they are all kept as 50 m discs
by default, which closes no required channel.
