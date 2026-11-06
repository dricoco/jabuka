# Quick 002: Barre tab as a left column, so the map shows

Asked by the owner, in French:

> c'est bien mais on voit tres peu la carte. donc je voudrais a gauche 1/3 de l ecran des blocs
> avec 1 bloc : TWA route, 8°tribord Écart0°, au dessous un deuxieme bloc Virement dans 09:36 /
> Ne pas virer : +3 min / Route : il y a 10 min / Cap route 120°M / Biais GRIB +0° ×1.01
> (s'estompe), et un 3eme bloc avec le reste

In short: "Good, but very little of the map shows. I want blocks in the left third of the screen.
Block 1: TWA route, 8° starboard, deviation 0°. Below it, block 2: tack in 09:36 / don't tack:
+3 min / route: 10 min ago / route course 120°M / GRIB bias. Block 3: everything else."

## Layout (Barre tab only; the other tabs are unchanged)

### Landscape (`min-aspect-ratio: 1/1`, width ≥ height)

`#helm-col` is the left column:
- Width: `--col-w: clamp(300px, 33.333vw, 640px)`.
- It runs from under the top bar to the bottom, on an opaque `--bg-band` background.
- It is a flex column with three blocks: blocks 1 and 2 at their natural height, block 3 filling
  the rest (`min-height: 0`, `overflow: auto`).
- The blocks are separated by a 1 px `--line` border and a gap.

1. **`#helm-steer`** (block 1, centred):
   - `#primary-label`
   - the big `#primary` and `#primary-unit`
   - the deviation row: label, value and hint (LOFER/ABATTRE, ORCAJ/ODPADI…)
   - "PERTE DONNÉES" when the link is stale

   Sizing the primary:
   - The font size is `min(height term, column-width term)`, so "888°M" can never overflow the
     column.
   - A one-letter unit (°M/°T) stays inline, at 0.3 of the primary's size.
   - A word unit (tribord / starboard / desno) goes on its own line under the number. The
     `unit-word` class is set by helm.js.
2. **`#helm-route`** (block 2, left-aligned, one item per line):
   - countdown
   - layline distance
   - `#route-band`, reordered so that cost comes before status:
     - cost
     - status
     - age
     - target
     - bias
   - the ON RESTE button, 64 px high and the full width of the block

   `.route-row` becomes a vertical stack inside the column.
3. **`#helm-rest`** (block 3): a 2-column grid of cells:
   - speed / target and polar %
   - mark (spans both columns)
   - distance and time (separate cells again, `#helm-dtw` / `#helm-ttw`)
   - bearing and `#helm-other`

   The labels reuse the existing i18n keys, so no new key and no review-doc change.

The map buttons (`.map-ctrls`) sit absolutely at the bottom right of `#tab-barre`, over the map.
They stay clear of the MapLibre attribution and the lock hint.

### Portrait (height > width)

There is one top area across the full width:
- block 1 in full (the primary is the same size as today)
- under it, blocks 2 and 3 side by side (two half-width columns)
- the map below, as one contiguous area

**Why:**
- Stacking the three blocks full-width uses the same height as today's top and bottom bands.
- Putting blocks 2 and 3 side by side saves about the height of block 3 (~200 px at 800×1280).
- The primary stays at today's full-width size: `max(18.5vh, min(22vh, 26vw))` with the width
  cap.
- The two bands of today cut the map into a middle strip. Here the visible map is one region, and
  the padding centres the boat in it.

## Map padding (map.js + helm.js)

- map.js gains `setMapPadding({top, right, bottom, left})`:
  - It remembers the wanted padding and applies it with `map.setPadding` once the map exists,
    and again on load.
  - It is a no-op when the padding is unchanged.
  - `overlays.js` easeTo/getCenter then work against the padded centre. That is how MapLibre
    behaves, and it keeps course-up, north-up and centring correct.
- helm.js computes the padding:
  - **Landscape on Barre:** `{left: col.right, top: topbar.bottom}`.
  - **Portrait on Barre:** `{top: col.bottom}`.
  - **Other tabs:** all zero, as before.
- It recomputes on the bus "tab" event, on window resize and orientationchange, and through a
  ResizeObserver on `#helm-col` and `#topbar`.

## Must keep working

- Night mode: theme custom properties only, so it stays red-only, including the column
  background.
- The lock overlay, which covers everything.
- `#tab-barre.stale`: the dimming selector moves from `.band` to `.helm-block`.
- The banner, the badges, and all three languages.

## Requirement HELM-02 ("primary ≥ 20% vh", 02-CONTEXT)

- Keep the ≥ 20% vh primary-box rule wherever the 1/3 column allows it: 1280×800, 1024×600, and
  portrait.
- If any landscape size cannot hold it, assert the strongest bound that holds (e.g. ≥ 15vh) and
  record it as a HELM-02 deviation for the owner.

## Tests

- **Update:**
  - `test_helm.py`: the band texts, the sizes at 1280×800, 1024×600 and 800×1280, and the
    boat-centring check, which now uses the padded centre via `map.getPadding()`.
  - `test_i18n_ui.py`: the fit check moves to the new blocks, at 1280×800, 1024×600 and
    800×1280.
- **New `tests/ui/test_helm_column.py`** (Playwright, /usr/bin/chromium, real core with a route,
  the 03-06 fixtures):
  - At 1280×800 and 1024×600 landscape and at 800×1280 portrait:
    - the column is about 1/3 of the width (portrait: full width, map below);
    - the visible map is about 2/3;
    - blocks 1 and 2 are fully inside the viewport, with no clipping or overflow, in fr, en and
      sl, with long values forced (a 3-digit primary with °M, a long countdown and a long bias);
    - ON RESTE is inside block 2 and clickable (`elementFromPoint`);
    - `map.getPadding()` matches the column.
  - Night: every visible element of the column is black, pure red or transparent.
  - Screenshots (day and night, fr and sl) are saved in `var/screens/quick-002/` (gitignored).
- **Live check:** run `scripts/demo.sh --port <free>` and take a Playwright screenshot once the
  route is up.

## Gate

`JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1`, run with ruff, then pytest on .venv (3.14) and
.venv313. All must be green.

## Out of scope

- core/router Python (plan 04-01 is running in parallel)
- STATE.md and ROADMAP.md
