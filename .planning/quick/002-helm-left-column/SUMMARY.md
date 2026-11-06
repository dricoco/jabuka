---
phase: quick
plan: 002
subsystem: web/helm, web/map
status: complete
tags: [helm, barre, layout, tablet, map-padding, night]
decisions:
  - "Landscape: the Barre tab is a left column (clamp(300px, 33.333vw, 640px)) with three blocks (steer / route+tack / rest); the map shows on the right two thirds"
  - "Portrait: one top area (block 1 full width, blocks 2 and 3 side by side), with the map below as one contiguous region"
  - "The map centre follows the visible part: map.js setMapPadding, helm.js keeps it in sync on tab/resize/orientation/ResizeObserver; Barre only, zero on other tabs"
  - "map maxBounds widened to 13.9-17.4 E, 42.0-44.8 N so that Centrer can put a boat near the area's edge in the middle of the visible map despite the padding"
  - "The column background is opaque in both themes (day #ffffff, night #000000): no map ghosting behind the helm numbers"
actuals: {tasks: 2, commits: 4}
plan_head_before: ee06cd2cb759d5f5b82a6283c3f017f31cdc9455
commits: 4
completed: 2026-11-07
---
# Quick 002: Barre tab as a left column, map on the right two thirds

The owner's request: "on voit très peu la carte" (the map hardly shows). The helm now takes the
left third in landscape, laid out as the owner described, in three blocks:
- Block 1 `#helm-steer`:
  - the label and the big primary (sized by height and by column width, so "888°M" always fits)
  - the tack word (tribord / starboard / desno) on its own line (`unit-word`)
  - the deviation with its LOFER/ABATTRE hint
  - PERTE DONNÉES when the link is stale
- Block 2 `#helm-route`, one item per line:
  - countdown
  - layline distance
  - cost (route.js now puts it before the status)
  - status, age, target, bias
  - ON RESTE, 64 px high and the full width of the block
- Block 3 `#helm-rest`, a 2-column grid:
  - BSP / target and polar %
  - mark
  - distance and time (separate cells again)
  - bearing and the other-tack heading

The map buttons sit bottom right over the map. Portrait keeps block 1 at full width, puts
blocks 2 and 3 side by side, and shows the map below. No new i18n key.

Map:
- map.js `setMapPadding` (remembered until the map loads; a no-op when unchanged).
- helm.js computes the padding:
  - landscape: left = right edge of the column, top = bottom of the top bar
  - portrait: top = bottom of the column
  - other tabs: zero
- easeTo, getCenter and Centrer work against the visible part.

Deviations:
- maxBounds widened, so that Centrer still centres a boat near the area's edge.
- Fix after the crash resume: the day column was rgba(255,255,255,0.96) and the map ghosted
  behind the primary at 800×1280 on the live demo, while the plan asks for an opaque column. It is
  now #ffffff, and the test asserts it.
- HELM-02: no deviation. The primary box is ≥ 20% vh at 1280×800, 1024×600 and 800×1280, in fr,
  en and sl, with long values forced.

Verification:
- Gate (JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1):
  - ruff check clean; ruff format clean on src/ and tests/
  - 1346 passed, 7 skipped on both .venv (3.14) and .venv313 (3.13)
  - Skips: netCDF4, weatherrouting, the full rehearsal, the wheelhouse ×2 and the real pack ×2.
- New tests (tests/ui/test_helm_column.py, 2), covering 1280×800, 1024×600 and 800×1280 in
  fr/en/sl with long values:
  - column ≈ 1/3, map ≈ 2/3
  - blocks 1 and 2 fully on screen
  - ON RESTE in block 2, hit-testable, toggling
  - map padding per orientation and per tab
  - night red/black only
  - day background opaque
- Updated tests: test_helm.py (sizes, padded centre) and test_i18n_ui.py (fit check on the new
  blocks).
- Live check: the demo on port 18765, with a route up after 2 s. Playwright screenshots are in
  var/screens/quick-002/ (gitignored):
  - 1280×800: column 427 px, padding {left 427, top 69}
  - 800×1280: top area down to 723 px, padding {top 723}

Known stubs: none.
