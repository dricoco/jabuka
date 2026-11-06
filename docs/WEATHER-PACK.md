# Weather race pack (wind, waves, current)

The router on the Pi has no internet at sea. Everything it knows about the weather comes from
the **race pack** built on the laptop before departure and copied to the Pi. This page is the
procedure: what the pack holds, when to build it, the exact commands, how to read the coverage
report, and how to copy it.

Weather data: *Datenbasis: Deutscher Wetterdienst* (DWD open data, https://opendata.dwd.de).
Currents: E.U. Copernicus Marine Service Information.

## What the pack contains

All files live in one directory (default `var/racepack/`, gitignored), with fixed names:

| File | Content | Source |
|------|---------|--------|
| `wind.npz` + `wind.json` | 10 m wind `u`, `v` (m/s, float32 `[t, lat, lon]`), `t` UTC epoch s, ascending `lat`/`lon` | DWD ICON-EU (default) or any GRIB (`grib FILE`) |
| `waves.npz` + `waves.json` | significant wave height `hs` (m), mean direction `mwd` (degrees FROM) | DWD EWAM |
| `current.npz` + `current.json` | surface current `u`, `v` (m/s TOWARDS), land = 0 | Copernicus Med (your own download) |
| `landmask.npz`, `geofields.npz` | land mask and distance fields | `jabuka-prep land ...` (plan 03-01/03-03) |
| `coverage.txt` | the last coverage report, in French | every prep command |

Every `.npz` has a `.json` sidecar with its sha256. The Pi refuses a file whose hash does not
match (a half-copied file is rejected, not used). A missing or rejected waves/current file only
disables that factor; a missing or rejected wind file means routing from the measured wind only.

Each file is cropped to the race box 15.0–16.3E x 42.8–44.0N **plus a 0.25 deg margin**
(14.75–16.55E x 42.55–44.25N). Cropping exactly at the box drops the 16.3E (ICON-EU) and 15.0E
(EWAM) columns.

## When to build it: DWD run timing

- ICON-EU runs at 00/06/12/18Z (to +120 h; hourly to +78 h, then 3-hourly) and 03/09/15/21Z (to
  +51 h, hourly). Files of a run appear progressively between **run + 2 h 40 and run + 3 h 32**.
- EWAM (waves) runs at 00 and 12Z, hourly to +78 h, published run + 3 h 16 to + 3 h 52.
- DWD keeps only about **24 h of runs** online. A pack built on Wednesday holds Wednesday's
  forecast, and it cannot cover a 13 Nov 18:00 to 15 Nov 10:00 race anyway.
- The tool picks the newest run whose steps cover the whole race window and are **all already
  published**; a run still being published is skipped automatically.
- **Friday 13 Nov, before departure (mandatory re-run):** the 12Z run is complete at about
  15:35 UTC (16:35 local). Run `wind` and `waves` **after about 15:40 UTC** so the 12Z run is
  used; it covers the window with hourly steps +5 to +45. The 15Z run completes around 18:30 UTC,
  too close to a 20:00 local start.

A pack built days ahead (for the benchmark or a dry run) cannot cover the window: the command
still writes the files, prints `MÉTÉO INCOMPLÈTE` and exits with code 3.

## Commands

Run from the repository on the laptop (venv with the `prep` extra: pygrib, netCDF4). The console
script is `jabuka-prep` (declared by plan 03-05); `python -m jabuka.prep.cli` is the same thing.

```bash
# 1. ICON-EU wind (41 hourly steps x U/V, about 100 MB, under a minute with 6 parallel requests)
jabuka-prep wind --out var/racepack

# 2. EWAM waves (significant height + mean direction)
jabuka-prep waves --out var/racepack

# 3. Organiser forecast (GRIB1 or GRIB2, any grid): writes wind.npz by default.
#    Use --name to keep both and choose later (rename to wind.npz / wind.json).
jabuka-prep grib ~/Downloads/regata_jabuka.grb --out var/racepack --name wind_organiser

# 4. Copernicus current (file downloaded by you, see below)
jabuka-prep current current_med.nc --out var/racepack

# 5. Land mask (plan 03-01/03-03 tooling, dispatched to jabuka.prep.land)
jabuka-prep land build --out var/racepack

# 6. Check the whole pack again (same loader and rules as the Pi)
jabuka-prep check --out var/racepack
```

Common options: `--out DIR` (pack, default `var/racepack`), `--cache DIR` (downloads, default
`var/cache/prep`; cached files that verify are not downloaded again), `--marks FILE` (default:
the course marks shipped in `jabuka.nav`), `--window-start` / `--window-end` (local time, default
`2026-11-13T18:00` and `2026-11-15T10:00`, Europe/Zagreb).

The `grib` command accepts u/v or speed/direction at 10 m, regular, rotated or projected grids
(projected grids are regridded to 0.025 deg). It prints the fields it found. When the file holds
no 10 m wind it stops with `aucun champ de vent 10 m trouvé ; champs présents : ...`; when the
grid does not reach the race area it says so. Files over 200 MB are refused.

## Copernicus current: your own account (manual step)

The tool never asks for or stores Copernicus credentials. With your free Copernicus Marine
account, on the laptop:

```bash
pipx install copernicusmarine        # or: uv tool install copernicusmarine
copernicusmarine login                # stores the credentials in the toolbox's own config
copernicusmarine subset --dataset-id cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m \
  --variable uo --variable vo \
  --minimum-longitude 14.75 --maximum-longitude 16.55 \
  --minimum-latitude 42.55 --maximum-latitude 44.25 \
  --start-datetime 2026-11-13T12:00:00 --end-datetime 2026-11-15T12:00:00 \
  --output-filename current_med.nc
jabuka-prep current current_med.nc --out var/racepack
```

The importer reads `uo`/`vo` (m/s, towards), squeezes a size-1 depth axis, and sets land/masked
cells to 0 (no current), never to a neighbour's value. The real file layout was only assumed in
research: the first real file must be checked (`coverage.txt` lists current as OK, no
`courant ... désactivé` line).

## Reading the coverage report (`coverage.txt`)

Every command ends with the coverage check (the same code runs on the Pi when it loads the pack):

- `COUVERTURE MÉTÉO : OK` and exit code **0**: wind covers every hour of the window, every mark
  of courses A and B and every leg (checked every nautical mile).
- `MÉTÉO INCOMPLÈTE` and exit code **3**: at least one `ALERTE : MÉTÉO INCOMPLÈTE : ...` line,
  e.g. `vent jusqu'au 14/11 19:00 seulement, fin requise 15/11 10:00` (times are local), a mark
  outside the grid, or missing values at a mark. The files are still written. Fix it (newer run,
  other GRIB) before leaving the dock. Beyond the last forecast time the router holds the last
  wind field (`horizon_hold`).
- Exit code **2**: input problem (missing file, unreadable GRIB/NetCDF, no wind found).
- `Attention : ...` lines are warnings: 3-hourly steps inside the window, or waves/current not
  covering the window (`facteur vagues désactivé` / `courant désactivé`: that factor is switched
  off, the route still works).
- `Info : Vagues absentes : vitesse réduite d'après le vent` / `Courant absent : routage sans
  courant`: optional files not provided.

## Copying the pack to the Pi

Copy the whole directory, sidecars included, then check on the Pi side (or just restart the core,
which runs the same check and shows MÉTÉO INCOMPLÈTE on the helm and Diag pages if needed):

```bash
# PI = the Pi's address, PACK_DIR = the race-pack directory configured for the core (plan 03-05)
rsync -av --delete var/racepack/ "$PI:$PACK_DIR/"
```

Never copy only the `.npz` files: without the matching `.json` sidecar (sha256) the Pi rejects
them.
