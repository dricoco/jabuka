---
phase: quick-261110-kxm
verified: 2026-11-10T00:00:00Z
status: human_needed
score: 7/7 must-haves verified
covered_files:
  - ".planning/quick/261110-kxm-aide-reglages-comment-saisir-chaque-vale/261110-kxm-PLAN.md"
  - ".planning/quick/261110-kxm-aide-reglages-comment-saisir-chaque-vale/261110-kxm-SUMMARY.md"
  - "docs/I18N-SL-REVIEW.md"
  - "src/jabuka/tools/i18n_review.py"
  - "src/jabuka/web/static/i18n.js"
  - "src/jabuka/web/static/reglages.css"
  - "src/jabuka/web/static/reglages.js"
  - "tests/test_i18n.py"
  - "tests/ui/test_reglages.py"
covered_digest: "v1:sha256:a8dfb25fb897b170b865d9c5e697c0cebd791998b2c0cd1cc7f54c0d8528086f"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "On the real Android tablet (or a tablet-sized browser), open Réglages and tap '?' next to Décalage compas, Déclinaison and Efficacité polaire in FR, EN and SL, in day and in night mode"
    expected: "Help expands below the row, is readable at arm's length, red-on-black at night, no sideways scroll; tapping again collapses"
    why_human: "Readability and touch feel on the real tablet; the Playwright test covers geometry and colours only"
  - test: "Native Slovenian speaker proofreads the 'Settings help' section of docs/I18N-SL-REVIEW.md"
    expected: "SL help texts are correct, idiomatic, and keep the same signs/formulas as FR"
    why_human: "Translation quality cannot be checked programmatically (the SL text is a proposed translation)"
---

# Quick 261110-kxm: Réglages "?" help — Verification Report

**Goal:** a "?" next to every Réglages setting that expands a short, code-faithful help (FR/EN/SL) plus a range/default line from the schema; accessible, collapsed by default, night-safe.
**Commits:** 4fe27cf, 3b57cc0, 3570af3 (base 2143ea7). The diff touches only the 7 planned files (router_service.py is not touched).
**Status:** human_needed. All automated checks pass. Two non-blocking human items remain: checking the tablet in person and having a native speaker proofread the SL text.

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every row has a "?" button: type=button, aria-expanded=false, aria-controls, localised aria-label, ≥48 px, panel collapsed | ✓ VERIFIED | reglages.js render() builds `button.help-btn` with type/aria-expanded/aria-controls=`reglages-help-<key>`/aria-label `t("reglages.helpAria",{label})` and `panel.hidden = !open`. helpAria is "Aide : {label}", "Help: {label}" and "Pomoč: {label}". CSS has min 48x48 and `.reglages-help[hidden]{display:none}`. UI test `test_settings_help_every_row_night_and_layout` asserts rows == btns == 33, expanded 0, open 0, small 0. |
| 2 | Tapping expands the help plus a "Plage : min à max · Défaut : v" line, tapping again collapses it, and an open panel survives a save | ✓ VERIFIED | `helpMeta()` (fieldSpec-aware; null→helpEmpty, bool→yes/no, enum→optionLabel, decimal comma fr/sl). The `openHelp` Set persists across render(). UI tests assert "Plage : -30 à 30 · Défaut : 0", the toggle back to collapsed, and that the efficiency panel stays open after a PUT. test_i18n asserts helpMeta output in fr/en/sl. |
| 3 | Help texts are faithful to the code (heading offset, variation, efficiency) | ✓ VERIFIED | Details in the Content Spot-Check section below. |
| 4 | Every Settings field has non-empty help in fr/en/sl, ≤450 chars, no orphan keys, and a test checks it | ✓ VERIFIED | Node count: 33 help.* keys in each of fr, en and sl, matching the 33 schema properties. Max lengths: fr 414, en 423, sl 411. `test_every_setting_has_a_help_text_in_every_language` passes. |
| 5 | Inputs keep their label, edits still PUT, and existing UI tests pass | ✓ VERIFIED | The row is now a div with `label[for=reglages-in-<key>]` and `input.id` is set. UI tests assert labels[0].textContent and a 200 PUT. test_reglages, test_i18n_ui, test_map_smoke and test_helm_logic all pass. |
| 6 | Night: buttons and panels use only black, pure red or transparent; all panels open at 800x1280 give no sideways scroll | ✓ VERIFIED | CSS uses theme variables only. The UI test runs HELP_COLORS_JS in night mode (bad == [], checked > 33) and checks scrollWidth ≤ 1 with all 33 helps open at 800x1280. |
| 7 | docs/I18N-SL-REVIEW.md is regenerated with a Settings help section and is in sync | ✓ VERIFIED | SECTIONS has `("help.", "Settings help (Réglages ? buttons)")`. `python -m jabuka.tools.i18n_review --check` printed "à jour", rc=0. The full check.sh was not re-run on request, because another executor is active. |

**Score:** 7/7 verified (0 behaviour-unverified)

## Content Spot-Check (FR/EN texts vs code)

| Setting | Help claim | Code evidence | Result |
|---|---|---|---|
| heading_offset_deg | Added to the B&G compass reading and to the compass-derived B&G directions (instrument TWD, current), before the variation. New = current + (reference − displayed). Example: 115 read, COG 120 → +5 | `wind.heading_true`: `apply_heading_offset` (sensor + offset), then `mag_to_true`. It is used for TWD_INSTR and `current_true` (set) | ✓ |
| variation_deg | True = magnetic + variation, East positive | `conventions.mag_to_true`: `true = mag + variation_east` | ✓ |
| efficiency | New = current × % / 100, and it changes speeds, not angles | `nav_service`: `pct = speed / (eff_now × polar) × 100`, so the true efficiency = eff × pct/100. `apply_efficiency` scales the bsp only | ✓ |
| leeway_deg | Used only for the Pi-computed true wind | `wind.py` step 2a: `lam = leeway × sign` only in the computed-wind branch | ✓ |
| route_level | L1 10° headings, L2 longer steps, L3 next mark + one, L4 10 min, L5 hold-tack every other cycle | `route/types.py`: L1 hdg_step 10, L2 dt_schedule, L3 max_marks_ahead=2, L4 cadence 600 s, L5 forced_every_n=2 | ✓ |
| route_cadence_min | L4/L5 force at least 10 min | `router_service`: `cadence_s = max(level.cadence_s, setting×60)`, with L4/L5 cadence 600 s | ✓ |
| route_waves | Slowdown of at most −30 % | `wave_floor = 0.70` in `isochrone.wave_factor` (max(floor, 1−k·Hs)) | ✓ |
| tack_penalty_s vs start_tack_s | The penalty is counted as time without progress and is not used by start mode. start_tack_s is for start mode only and is not used by routing | `isochrone`: `bsp × (dt − penalty)` on a flip. `start.py` reads only `start_tack_s`, and its docstring says "tack_penalty_s is never read here". The router reads only `tack_penalty_s` | ✓ |

The SL texts for heading_offset_deg, variation_deg and efficiency keep the same signs and formulas as FR (read via node).

## Key Links

| From | To | Status |
|---|---|---|
| reglages.js | i18n.js (`help.<key>`, reglages.helpAria/helpRange/helpDefault/helpEmpty/yes/no) | WIRED |
| reglages.js helpMeta | schema min/max/default via fieldSpec | WIRED (fr/en/sl outputs tested) |
| tests/test_i18n.py | Settings.model_json_schema() properties == help.* keys | WIRED |
| i18n_review.py | docs/I18N-SL-REVIEW.md | WIRED (--check in sync) |

## Behavioral Spot-Checks

| Check | Result |
|---|---|
| `.venv313/bin/pytest -q tests/test_i18n.py tests/ui/test_reglages.py` | 16 passed |
| `.venv313/bin/pytest -q tests/ui/test_i18n_ui.py tests/ui/test_map_smoke.py tests/test_helm_logic.py` | 33 passed |
| `.venv313/bin/python -m jabuka.tools.i18n_review --check` | "à jour", rc 0 |
| Node: help.* key count and max length per language | fr 33/414, en 33/423, sl 33/411 |

## Anti-Patterns

No TBD, FIXME, XXX or TODO in the added lines of the diff 2143ea7..3570af3. The DOM is still built with textContent and setAttribute.

## Human Verification Required

1. **Check on the tablet:** tap "?" for Décalage compas, Déclinaison and Efficacité polaire in FR, EN and SL, in day and in night mode. Expect the help to be readable, red on black at night, with no sideways scroll.
2. **Slovenian proofreading:** a native speaker reviews the "Settings help" section of docs/I18N-SL-REVIEW.md.

## Gaps Summary

None. Both remaining items are non-blocking human checks.

_Verifier: Claude (gsd-verifier)_
