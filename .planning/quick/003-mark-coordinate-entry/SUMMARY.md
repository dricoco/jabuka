---
phase: quick
plan: 003
subsystem: web/carte
status: complete
tags: [carte, marks, coordinates, vhf, i18n, tablet]
decisions:
  - "A mark position is typed in degrees + decimal minutes (VHF format), one tolerant text field per axis (comma or point, N/S/E/W before or after, leading '-', DMS, keypad '43.45.2'); no letter = N / E"
  - "Valid area = the map's maxBounds (race area 42.7-44.1 N, 14.9-16.4 E) clipped to the core's MarkIn limits, not /racepack/info bounds (tile extent only)"
  - "Typed positions get the same 'earth' land check as a tap, shown inline in the sheet (Garder / Annuler keeps the typed values)"
  - "Moving a mark by typing is PATCH /api/marks/{id}; a builtin mark gets the core's override (no core change)"
  - "Carte refuses writes while locked (lock bus event), behind the lock overlay"
actuals: {tasks: 4, commits: 5}
plan_head_before: ee06cd2cb759d5f5b82a6283c3f017f31cdc9455
commits: 5
completed: 2026-11-06
---
# Quick 003: type a mark's coordinates (degrees + decimal minutes)

For a mark announced by VHF, e.g. "bouée en 43°45,2'N 15°40,1'E".

- static/coord_logic.js (pure, node-tested): parseCoord (error codes empty / format / minutes /
  seconds / range / hemisphere), dmParts / formatDM (59.9996' carries to the next degree),
  RACE_AREA, SERVER_LIMITS, areaFrom(maxBounds), inArea, checkPosition.
- Carte, add sheet: the position is now an editor (Latitude / Longitude, inputmode=decimal,
  select-all on the first tap) prefilled from the tap in 3-decimal minutes. Each field has a live
  error, and an area error spans both. The pending marker follows a valid entry, and after a
  pause the map eases there (to the free area left of the panel, above the sheet). "Ajouter" is
  disabled while the entry is invalid. A typed position on land asks "Marque à terre ?" inline.
- "＋ Marque (coordonnées)" (#mark-coords) opens the same sheet at the boat (nav.boat inside the
  area), else at the map centre.
- Mark sheet: a "Coordonnées" editor with "Déplacer ici" (#mark-move), disabled until the values
  change. It sends PATCH lat/lon/base_version with the same land check. Unsent drafts survive a
  course refresh of the open sheet.
- The course list shows each mark's position (.coord), with a decimal comma in fr / sl.
- i18n: 13 new carte.* keys in fr, en and sl; docs/I18N-SL-REVIEW.md regenerated.

Deviations: the French "O" (ouest) is accepted for W. The crash left a stale
docs/I18N-SL-REVIEW.md.bak, which was removed. atomic_write_bytes keeps NAME.bak by design, so
every regeneration of the review sheet recreates it; it is not gitignored (follow-up).

Verification:
- Gate (worktree): ruff check clean; ruff format --check clean on src/tests/scripts (204 files).
  `ruff format --check .` still flags 7 pre-existing .planning/*.md files, the same set as on
  master and untouched here.
- pytest with JABUKA_REQUIRE_UI=1 JABUKA_REQUIRE_ROUTE=1: 1411 passed, 6 skipped on 3.14.7;
  1411 passed, 6 skipped on 3.13.
- New tests: test_coord_logic (53 cases), test_carte_coords (6 Playwright: VHF add, move custom
  and builtin, out of area and bad input refused, land check, sl, lock).

Known stubs: none (the Slovenian strings await a native speaker's review).
