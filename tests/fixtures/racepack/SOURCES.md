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
