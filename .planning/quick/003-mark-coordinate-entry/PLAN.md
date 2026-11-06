# Quick 003: type a mark's coordinates (degrees + decimal minutes)

Asked by the owner: at sea the race committee may announce an extra mark by VHF with coordinates
("bouée en 43°45,2'N 15°40,1'E"). Today a mark can only be added by tapping the map and moved by
dragging it. "oui fais la saisie des coordonnées".

Scope: `carte.js`, `carte.css`, a new `coord_logic.js`, the `carte.*` keys of `i18n.js`, tests,
`docs/I18N-SL-REVIEW.md` (regenerated). No core Python change (the server already accepts
`POST /api/marks` and `PATCH /api/marks/{id}` with lat/lon; a builtin mark gets an override).
Parallel agents own `app.css`, `index.html`, `route.js`, `helm*.js`, `map.js`: not touched.

## 1. `static/coord_logic.js` (pure, node-tested)

- `parseCoord(text, axis)` with axis `"lat"` | `"lon"` -> `{ok: true, value}` or
  `{ok: false, error}`, error in `empty | format | minutes | seconds | range | hemisphere`.
  - Decimal comma or point. Hemisphere letter before or after (`N`/`S` for lat, `E`/`W` for
    lon; the other axis's letter is an error), or a leading `-`. No letter = N / E.
  - Separators between fields: spaces, `°` `º` `*` `'` `′` `’` `"` `″` `:`.
  - One number = decimal degrees (`43.7533`, `43,7533`). Two = degrees + decimal minutes
    (`43 45,2`, `43°45,2'`, `43°45.2N`). Three = degrees, minutes, seconds.
  - Digits with exactly two `.`/`,` separators (`43.45.2`, `43,45,2`): the first one splits degrees
    and minutes (a numeric keypad without a space key).
  - Degrees must be an integer when minutes follow; minutes >= 60 and seconds >= 60 refused;
    |lat| <= 90, |lon| <= 180.
- `dmParts(value, digits)` and `formatDM(value, axis, {digits = 3, sep = "."})`: `43°45,200' N`,
  carrying 59.9996' to the next degree (never `60,000'`).
- `RACE_AREA` (the map's maxBounds, 42.7-44.1 N, 14.9-16.4 E), `SERVER_LIMITS` (42-45 N, 14-17 E
  from `course_api.MarkIn`), `areaFrom(maxBounds)` (the map's live maxBounds clipped to the
  server limits), `inArea(lat, lon, area)`.
- `checkPosition(latText, lonText, area)` -> `{lat, lon, ok, latError, lonError, areaError}` for
  the sheet's live validation.

Why the map's maxBounds and not `/racepack/info` `bounds`: the latter is the tile extent only (in
the test fixture just the Šibenik corner, 15.70-15.95 E) and would refuse marks the map can show
and the server accepts. The race area the map is clamped to is the "race-pack area" the user sees.

## 2. Carte UI (`carte.js`, `carte.css`)

- A coordinate editor (two text inputs, `inputmode="decimal"`, `autocomplete=off`, select-all on
  focus) with a format hint and a live error line under each field; an area error under both.
- Add sheet: the read-only position becomes the editor, prefilled from the tapped point (3
  decimal minutes). While typing: the pending marker follows a valid in-area position and the map
  eases there (debounced, offset so the point lands left of the panel and above the sheet).
  "Ajouter" is disabled while invalid. On "Ajouter", typed coordinates that differ from an already
  accepted land position run the same "earth" land check (after the map has moved there): on land,
  an inline "Marque à terre ?" block with Garder / Annuler keeps the typed values.
- Panel button "＋ Marque (coordonnées)" (`#mark-coords`): opens the same sheet prefilled with the
  boat position (nav.boat), else the map centre.
- Mark sheet: a "Position" editor prefilled with the mark's coordinates and a "Déplacer ici"
  (`#mark-move`) button -> `PATCH /api/marks/{id}` `{lat, lon, base_version}` (same land check).
  Drafts survive a course refresh of the open sheet.
- The course list shows each mark's coordinates in the same format (`.coord` line).
- A `lock` bus event makes the Carte refuse writes (defence in depth behind the lock overlay).

## 3. i18n

New `carte.*` keys in fr, en and sl next to the existing ones; regenerate
`docs/I18N-SL-REVIEW.md` (`python -m jabuka.tools.i18n_review`).

## 4. Tests

- `tests/test_coord_logic.py` (node harness like `test_route_logic.py`): formats, hemispheres,
  comma decimals, DMS, two-separator keypad form, 59.99' rounding carry, invalid input, area
  checks, round trips parse(format(x)) within 1e-6 deg over a grid.
- `tests/ui/test_carte_coords.py` (Playwright): button -> type `43 45,2` / `15 40,1` -> add ->
  course has the mark at 43.75333 / 15.66833 (+-1e-5) right after the active mark; move a custom
  mark by typing; out-of-area entry refused (button disabled, error shown, no request); typed
  coordinates on Zlarin ask "Marque à terre ?"; the same in sl; the lock blocks the button,
  the inputs and "Ajouter".

## Gate

`JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1`: ruff check + format check, pytest on Python 3.14
and 3.13, all green.
