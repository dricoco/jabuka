---
status: testing
phase: 02-helm-mvp-laylines-marks-map
source: [02-VERIFICATION.md]
started: 2026-11-06T18:36:43Z
updated: 2026-11-06T18:36:43Z
---

## Current Test

number: 1
name: Helm view on the real tablet, offline
expected: |
  Race pack copied to the Pi (docs/RACE-PACK.md: rsync var/racepack → /var/lib/jabuka/racepack, restart jabuka-core).
  Tablet in airplane mode with Wi-Fi to SSID `jabuka`, open http://10.42.0.1 (TABLET-SETUP §1, §5).
  The Barre tab shows the big numbers over a MapLibre map of Vodice → Jabuka. Zoom to 14: labels, seamarks,
  course, marks with radius circles, laylines and boat all render. chrome://inspect shows no network error.
awaiting: user response

## Tests

### 1. Helm view on the real tablet, offline (HELM-01, SC1)
expected: the map renders at every zoom up to 14 with labels and seamarks; boat, course, mark radii and laylines are drawn; the primary number fills ≥ 20% of the screen height; no failed request in chrome://inspect (if WebGL fails, the numbers still work without the map)
result: [pending]

### 2. Screen stays awake (HELM-04, SC5, TABLET-SETUP §2–3)
expected: with the Chrome flag `unsafely-treat-insecure-origin-as-secure` = `http://10.42.0.1`, the badge says "verrou" after the first tap; without the flag it says "vidéo"; on the charger the screen never sleeps for ≥ 2 h (ideally overnight); after switching to another app and back, the badge comes back
result: [pending]

### 3. Night readability (HELM-03, SC5)
expected: in the dark, "☾ Nuit" makes every tab (Barre, Carte, Réglages, Diag), sheet, map control and badge red on true black, with nothing white or blue; the brightness slider dims it; the primary number is readable from the helm; night vision is still good after 5 min
result: [pending]

### 4. Lock mode in spray and rain (HELM-04, SC5)
expected: once locked, water spray, wet fingers, a palm or two fingers change nothing (no tab change, map pan or button press); a press of 2 s or more on the padlock unlocks; a short or two-finger press does not; a page reload while locked comes back locked before the map loads
result: [pending]

### 5. Real X35 polar (WIND-01)
expected: `jabuka-prep-polar <owner file> --out var/racepack/polar.json` prints a target table matching the owner's numbers; after copying the pack, the core uses it (polar name on the helm/Diag) instead of the interim ORC X-35 OD 2019 polar; efficiency 0.92 (or the chosen value) shows in target BSP and % polar
result: [pending]

### 6. Marks, rounding sides and start/finish against the SIs (CRSE-01/02, 13 Nov briefing)
expected: on the Carte tab, Course A and Course B rounding sides and radii match the Sailing Instructions; the Vodice start/finish is moved from the 43.7500N 15.7800E placeholder to the real line; "Côtés confirmés" clears "Côtés à confirmer (IC)"
result: [pending]

### 7. Primary number on a beat (review CR-03)
expected: in the sim (`jabuka-sim --follow`) or on the water, a beat leg shows "TWA CIBLE ↑" and never ↓. Bearing away to a reach on a beat leg shows "CAP À SUIVRE" equal to the current tack's close-hauled heading, never the bearing into the wind. Fetching shows the fetch course. Rounding the leeward mark onto a beat switches cleanly. The helmsman finds it clear
result: [pending]

### 8. Live wind and manual fallback on the boat (WIND-03/04, NAV-03, 12 Nov)
expected: with the bus live, the badge shows LIVE and Diag shows the computed-vs-B&G difference under 10° (otherwise set the heading offset, AWA sign or variation). Laylines are plausible on both tacks. With the bus unplugged, entering TWD/TWS in °M on Réglages gives MANUEL and the laylines keep updating. Set/drift stays off until compass and log are checked
result: [pending]

### 9. Course and settings survive a power cut (CRSE-05)
expected: after adding a mark, "Finir ici", changing a setting and entering manual wind, a Pi power pull and reboot bring back the same course, active mark, finish point, settings and manual wind, with no "illisible" alert
result: [pending]

### 10. Lock review
expected: deploy/requirements.lock holds the 19 expected canonical projects: Phase 1's 17 (annotated-doc, annotated-types, anyio, click, fastapi, h11, idna, opentelemetry-api, pydantic, pydantic-core, pyfastnet, pyserial, starlette, typing-extensions, typing-inspection, uvicorn, websockets) plus pmtiles (Phase 2) and numpy (Phase 3)
result: [pending]

## Summary

total: 10
passed: 0
issues: 0
pending: 10
skipped: 0

## Gaps

From 02-VERIFICATION.md (status gaps_found). These need a fix or a decision, not a tablet test:
- NAV-02 / SC2: the distance to the layline (`layline.dist_nm`) is computed but not shown on the helm. Small fix in helm_logic.js plus a node test.
- CRSE-01 / SC3: changing Course A/B takes a confirming second tap (review fix WR-05). Owner decision: accept it via the override in 02-VERIFICATION.md, or restore a single tap.
