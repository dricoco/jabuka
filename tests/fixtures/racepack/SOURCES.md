# Race-pack test fixtures: sources

Weather data: **Datenbasis: Deutscher Wetterdienst** (DWD open data, https://opendata.dwd.de,
licence "Nutzungsbedingungen / terms of use" of the DWD Open Data server: free reuse with source
attribution). Every GRIB-derived file below keeps the DWD message headers (centre 78 = Offenbach).

Tests never touch the network. They generate every GRIB they need from the templates below by
editing grid, values, parameter and forecastTime with pygrib (see `tests/racepack/conftest.py`).

## grib/icon_template.grib2 (206 bytes)

- Source: `https://opendata.dwd.de/weather/nwp/icon-eu/grib/12/u_10m/icon-eu_europe_regular-lat-lon_single-level_2026110512_000_U_10M.grib2.bz2`
  (ICON-EU run 2026-11-05 12Z, step +000, 10 m U), downloaded 2026-11-06 over https,
  sha256 of the .bz2 `1699de5da0930e17f207bf856f37d007e02ab97a4f1e09c5196e7d6a1566dbb6`.
- Shrinking (pygrib 2.1.8, first and only message): `packingType = grid_simple`,
  `Ni = 23`, `Nj = 21`, first grid point 42.75N 14.875E, last 44.0N 16.25E, increments 0.0625,
  `values = 0` (constant), then `g.tostring()`. Everything else (centre, discipline/category/number
  = 10u, heightAboveGround 10, `indicatorOfUnitOfTimeRange = 0` i.e. forecastTime in MINUTES) is the
  real ICON-EU header.
- sha256 `56d2993f3589d6265077b57a2850f0fd7b5dd807ee9c45571866b2546670d479`.

## grib/ewam_template.grib2 (187 bytes)

- Source: `https://opendata.dwd.de/weather/maritime/wave_models/ewam/grib/00/swh/EWAM_SWH_2026110600_000.grib2.bz2`
  (EWAM run 2026-11-06 00Z, step +000, significant wave height), downloaded 2026-11-06 by
  `python -m jabuka.prep.cli waves` (see the samples below), sha256 of the .bz2
  `3ade41cfeabe11035068c93fe82ad095877c81a857ed34f8ccdffd8c72857b13`.
- Shrinking (pygrib 2.1.8): `packingType = grid_simple`, `Ni = 5`, `Nj = 4`, first grid point
  43.15N 15.0E, last 43.0N 15.4E (rows NORTH TO SOUTH, `jScansPositively = 0`, as EWAM),
  increments 0.1 (lon) x 0.05 (lat) kept from the source, `missingValue = 9999`,
  `bitmapPresent = 1`, values 1.0 with one cell set to 9999 (masked, i.e. "land"), then
  `g.tostring()`. forecastTime is in HOURS in EWAM (`indicatorOfUnitOfTimeRange = 1`).
- sha256 `16bb433b96b31462a90bf5afa1082e98ec084145e90436cee8fb122673e846fd`.

## dwd/*.html (directory listings, fetched 2026-11-06 ~03:40 UTC)

| File | Source listing | sha256 |
|------|----------------|--------|
| `icon-eu_u_10m_12.html` | `https://opendata.dwd.de/weather/nwp/icon-eu/grib/12/u_10m/` (run 2026110512, 93 files, unmodified) | `4601ea083fe9b2ca92327c4eccb2fd465bfcff66bc580555bca7820c5c880639` |
| `icon-eu_v_10m_12.html` | `https://opendata.dwd.de/weather/nwp/icon-eu/grib/12/v_10m/` (run 2026110512, 93 files, unmodified) | `046a57e11be397d1b7b662843e9e239ff966b5f5f08f677dcddd931e57f8b1c7` |
| `icon-eu_u_10m_15_partial.html` | `https://opendata.dwd.de/weather/nwp/icon-eu/grib/15/u_10m/` (run 2026110515, 52 files, sha256 of the full listing `1aeb4a82...1e63`) **trimmed** to steps +000..+030 to reproduce a run still being published (files appear progressively over ~50 min, RESEARCH Pitfall 5) | `f9140cd9d76234a7ec0df552b76781a58ea3742f9367c5ef2994cb74057307ce` |
| `ewam_swh_12.html` | `https://opendata.dwd.de/weather/maritime/wave_models/ewam/grib/12/swh/` (two runs kept: 2026110412 and 2026110512, 79 files each, unmodified) | `01e88c6d4f676027f9eddab1b8dde8467ee1fbcc589efbe2b31a378d08889f79` |

Tests move these runs to 13 Nov by replacing the date string `20261105` (the listing structure
is what matters) and derive the 15Z v_10m listing from the u_10m one.

## wind_icon_eu_sample.{npz,json} and waves_ewam_sample.{npz,json} (real DWD samples)

Built on 2026-11-06 with the real tools against opendata.dwd.de, default crop (race bbox
15.0-16.3E x 42.8-44.0N plus 0.25 deg), window set to the 24 h after the newest run:

```bash
python -m jabuka.prep.cli wind  --out var/racepack-sample --cache var/cache/prep \
    --window-start 2026-11-06T01:00 --window-end 2026-11-07T00:00
python -m jabuka.prep.cli waves --out var/racepack-sample --cache var/cache/prep \
    --window-start 2026-11-06T01:00 --window-end 2026-11-07T00:00
```

- Wind: ICON-EU run **2026-11-06 00Z**, steps +000..+023 (48 files, 57.6 MB downloaded in ~40 s),
  `https://opendata.dwd.de/weather/nwp/icon-eu/grib/00/{u_10m,v_10m}/icon-eu_europe_regular-lat-lon_single-level_2026110600_{000..023}_{U,V}_10M.grib2.bz2`.
  Grid 28 x 29 (lat 42.5625..44.25, lon 14.75..16.5, 0.0625 deg), 24 hourly steps
  2026-11-06T00:00Z..23:00Z, TWS 0.0..11.5 kn. 110,848 bytes,
  sha256 `5e4594b4f66d8c7c620ea0816558cdb012cff23b0deb367afdd6188735d5e48c`.
- Waves: EWAM run **2026-11-06 00Z**, steps +000..+023 (48 files, 7.7 MB),
  `https://opendata.dwd.de/weather/maritime/wave_models/ewam/grib/00/{swh,mwd}/EWAM_{SWH,MWD}_2026110600_{000..023}.grib2.bz2`.
  Grid 34 x 18 (lat 42.55..44.2 step 0.05, lon 14.8..16.5 step 0.1), hs 0.02..0.33 m, mwd in
  degrees true FROM, land cells filled from the nearest sea cell (no NaN). 43,701 bytes,
  sha256 `39d92c2592aa8bb6c5d98d13ad95ed6f053d4349e95c332381d86997ac6da6d4`.
- The committed files are the pack files re-written under their fixture stem (24 steps kept,
  nothing else changed) so the sidecar `file`/`sha256` match the committed bytes. Tests copy them
  to wind.npz/wind.json and waves.npz/waves.json.

## grib/sample_grib1.grb (168 bytes, synthetic GRIB edition 1)

Built once with eccodes 2.50.0 (dev-only, in a throwaway venv; tests never need eccodes) from the
`regular_ll_sfc_grib1` sample, then read back with pygrib 2.1.8:

- two messages: `indicatorOfParameter` 33 (u, value 4.0 m/s) then 34 (v, 3.0 m/s), i.e. wind FROM
  about 233 deg at 5 m/s; `indicatorOfTypeOfLevel 105` (height above ground), `level 10`;
- `centre 7`, `table2Version 50`: a WMO-range table eccodes has no definitions for, so pygrib
  decodes `shortName = "unknown"` (not `10u`). In GRIB1 tables < 128, parameters 1-127 are the
  WMO standard ones, which is what `prep/grib.py` relies on (RESEARCH Pitfall 14: the ECMWF table
  128 decodes the same number 33 as `rsn`, snow density);
- regular lat/lon 9 x 8 at 0.25 deg, 44.5N -> 42.75N (rows NORTH TO SOUTH,
  `jScansPositively = 0`), 14.5E -> 16.5E, `bitsPerValue 12`;
- `dataDate 20261113`, `dataTime 1200`, `step 6` (hours) -> valid 2026-11-13 18Z. pygrib's
  `validDate` returns the analysis time (12Z) for this GRIB1 message; the importer uses eccodes'
  `validityDate`/`validityTime` (18Z).
- sha256 `ba8a7fb77b62d7a12631ce8c88d70af941a595501e4e60d5b8a0e097b535e31e`.

Recipe (eccodes python API), per message: `h = codes_grib_new_from_samples("regular_ll_sfc_grib1")`,
`codes_set` of `centre`, `table2Version`, `indicatorOfParameter`, `indicatorOfTypeOfLevel`,
`level`, `dataDate`, `dataTime`, `stepUnits`, `step`, `timeRangeIndicator 0`, `Ni`, `Nj`,
`jScansPositively`, first/last grid points, increments, `bitsPerValue`, then `codes_set_values`
and `codes_get_message`; the two messages are concatenated.
