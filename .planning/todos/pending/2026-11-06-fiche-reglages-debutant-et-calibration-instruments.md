---
created: 2026-11-06T22:41:47.521Z
title: Fiche réglages débutant et calibration instruments
area: docs
severity: minor
files:
  - docs/COMMISSIONING.md:204-225
  - src/jabuka/nav/settings.py:43-72
  - src/jabuka/nav/polar.py:165-200
  - src/jabuka/core/nav_service.py:176-190
---

## Problem

The owner wants, at the end of development (before 2026-11-12 commissioning), a detailed settings
sheet written in French **for a beginner**: what to set in the tablet's Réglages tab, when, why, and
safe default values. Plus a beginner-readable procedure to check the calibration of the on-board
B&G Hercules instruments. Today this knowledge is spread across docs/COMMISSIONING.md §4 (written
for the developer, with test tags) and chat explanations.

## Solution

One printable French doc (e.g. docs/FICHE-REGLAGES.md), plain language, one page per topic:

- Polar efficiency: general / upwind (TWA < 70°) / downwind (> 110°) fields. Procedure: 5–10 min
  steady leg, read average "% polaire", new = current × % / 100 (the % is already relative to the
  efficiency-scaled polar). Default 0.92 (0.90 for a crew new to the boat); aim for a sustainable
  value (night, 5/6 Bft), not the best leg. Re-check during the first race hours. Note the value
  on the course card (SPARE-SD).
- Heavy-weather reduction from task (b): how it stacks on top of efficiency, threshold and percentage.
- Damping: tau_helm_s 10 s, tau_layline_s 60 s; raise laylines to 90–120 s in gusty/oscillating wind.
- Variation (4.7° E default), compass offset, true-wind source (computed vs instrument),
  route level, GRIB bias decay (2.5 h).
- Instrument calibration checks (from COMMISSIONING §4): log BSP vs SOG under engine at slack
  water (±0.3 kn, else calibrate log on the B&G), compass vs COG under engine (< 3°), AWA sign
  (starboard = +), computed TWD vs Hercules TWD on both tacks (< 10°), TWD jumping at each tack =
  masthead offset / AWA asymmetry or upwash, symmetric AWA/TWA on both tacks. Note: the log must be
  right before calibrating the efficiency.
- Polar source: currently the generic X-35 OD ORC 2019 certificate; import the boat's own
  certificate/polar with jabuka-prep-polar if received (the downloaded XC 35 CSV is the wrong boat).
