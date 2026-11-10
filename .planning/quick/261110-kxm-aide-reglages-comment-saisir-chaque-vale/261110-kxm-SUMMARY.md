---
phase: quick-261110-kxm
plan: 01
subsystem: web-ui (Réglages tab), i18n
tags: [reglages, help, i18n, accessibility, night-mode]
status: complete
requires: [quick-261110-klg (committed, HEAD 2143ea7)]
provides:
  - "'?' help toggle next to every Réglages setting (FR/EN/SL), range/default line from the schema"
  - "reglages.js exported pure helpMeta(prop)"
  - "HELP_FR / HELP_EN / HELP_SL tables (help.<field>) in i18n.js"
affects: [src/jabuka/web/static/reglages.js, src/jabuka/web/static/reglages.css, src/jabuka/web/static/i18n.js, src/jabuka/tools/i18n_review.py, docs/I18N-SL-REVIEW.md]
tech-stack:
  added: []
  patterns: ["div.reglages-row[data-key] + label[for] + button.help-btn[aria-expanded/aria-controls] + div.reglages-help[hidden]", "open state kept in a Set across render()"]
key-files:
  created: []
  modified:
    - src/jabuka/web/static/reglages.js
    - src/jabuka/web/static/reglages.css
    - src/jabuka/web/static/i18n.js
    - src/jabuka/tools/i18n_review.py
    - docs/I18N-SL-REVIEW.md
    - tests/test_i18n.py
    - tests/ui/test_reglages.py
decisions:
  - "Settings row is now a div (not a label) with label[for=reglages-in-<key>], so the '?' button never steals the input's label"
  - "Help for heading_offset_deg states the offset also applies to compass-derived B&G directions (instrument TWD, current set), per wind.heading_true (plan-checker advisory)"
  - "Bench output NIVEAU RECOMMANDÉ kept verbatim in EN/SL route_level help (the bench tool prints French only), with a translated gloss"
metrics:
  duration: "~45 min"
  completed: 2026-11-10
  tasks: 3
  files: 7
estimate:
  tokens: 120000
  tasks: 3
actuals:
  tokens: 13400
  tasks: 3
  commits: 3
commits: 3
plan_head_before: 2143ea77386d9104c169966a9e021aa9d0296b3e
---

# Phase quick-261110-kxm Plan 01: Réglages "?" help Summary

Every Réglages setting (33 Settings fields) now has an accessible 48 px "?" toggle next to its label. It expands a short skipper-language help in FR/EN/SL (what the setting does, how to measure or choose it on board), followed by a "Plage : min à max · Défaut : v" line generated from the JSON schema. The help is collapsed by default, stays open across saves, and is pure red on black at night.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: heading_offset_deg help wired end to end (i18n keys, row rewrite, CSS, review-sheet section, UI test) | 4fe27cf |
| 2 | Help texts for all 33 fields in FR/EN/SL + coverage / anchors / helpMeta tests (RED first: A and B failed, C passed) | 3b57cc0 |
| 3 | Browser test: one '?' per field, 48 px, collapsed; open state survives a PUT; night colours; no sideways scroll at 800x1280 with all helps open | 3570af3 |

## Verification

- `.venv313/bin/pytest tests/test_i18n.py tests/test_helm_logic.py tests/ui/test_reglages.py tests/ui/test_i18n_ui.py tests/ui/test_map_smoke.py`: green (45 passed after Task 1; reglages 3 passed after Task 3).
- `python -m jabuka.tools.i18n_review --check`: "à jour".
- `bash scripts/check.sh`: green, with ruff check, ruff format, then 2029 passed and 4 skipped on both 3.14 and 3.13 ("check: ok"). The known flaky language-switch test did not fail.
- Tracer gate: Task 1's `<verify>` passed end to end before expanding.

## Implementation notes

- `helpMeta(prop)` uses `fieldSpec` (aware of `anyOf`) for the bounds. It shows the range only for numbers that have both bounds. Defaults are formatted per type: null → vide/empty/prazno, booleans → oui/non (yes/no, da/ne), enums → option label, numbers → decimal comma in fr/sl and point in en.
- Help text lengths: FR is at most 414 characters (variation_deg 414 and heading_offset_deg 404 are above the 380 FR target, under the 450 hard cap). EN is at most 423 and SL at most 411.
- Badge and alert names in the EN/SL texts are taken from that language's i18n values: SAILED ANGLES/DEJANSKI KOTI, CURRENT/TOK, STALE/ZASTARELO, WIND STALE/VETER ZASTAREL, HEADING UNRELIABLE/SMER NI ZANESLJIVA, WEATHER INCOMPLETE/VREME NEPOPOLNO, NO WIND/NI VETRA, HOLD TACK/OSTANEMO, HEAD UP/BEAR AWAY, ORCAJ/ODPADI, “Routing off (Settings)”, “GRIB bias”/„Popravek GRIB“. Diag paths are kept verbatim.

## Deviations from Plan

1. **[Advisory applied] heading_offset_deg help.** In FR/EN/SL the text says the offset also applies to the B&G directions derived from the compass (instrument TWD, current), as `wind.heading_true` is used for the TWD and for `current_true`. It stays at or under 450 characters.
2. **[Test addition] Extra checks.** Test C also asserts `en use_current → "Default: no"` and `fr heading_offset_deg → "Plage : -30 à 30 · Défaut : 0"`. The Task 3 test also checks that the efficiency help still contains "0,87" after the save.

Otherwise the plan was executed as written. No change was needed to reglages.css or reglages.js in Task 3, and router_service.py was not touched.

## Known Stubs

None.

## Threat Flags

None. The DOM is built with textContent/setAttribute only (test_dom_built_without_inner_html still passes), and no new endpoint or write path was added.

## Human check pending (non-blocking)

On a tablet-sized browser (or on the tablet at the dock), go to Réglages and tap "?" next to Décalage compas, Déclinaison and Efficacité polaire in FR, then in EN and SL, in day and in night. The Slovenian help texts are a proposed translation and still need a native speaker's proofreading (docs/I18N-SL-REVIEW.md, "Settings help" section).

## Self-Check: PASSED

- FOUND: src/jabuka/web/static/reglages.js (export function helpMeta), reglages.css (.help-btn), i18n.js (HELP_FR), i18n_review.py ("help."), docs/I18N-SL-REVIEW.md (help.heading_offset_deg), tests/test_i18n.py (test_every_setting_has_a_help_text_in_every_language), tests/ui/test_reglages.py (test_settings_help)
- FOUND commits: 4fe27cf, 3b57cc0, 3570af3
