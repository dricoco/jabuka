---
phase: 04-race-readiness-hardening-commissioning
type: project-review
reviewed: 2026-11-09
head: 7b00200
scope: [routing-math, runtime-backend, helm-ergonomics]
method: three independent read-only reviews (routing/nav math, core+ingest+deploy, tablet UI), every finding re-checked against the code; tests run tests/route tests/nav tests/routing (469 passed, 1 skipped), tests/gps tests/web tests/test_rawlog_full_disk.py tests/test_retention.py tests/test_no_wallclock.py (155 passed); demo probed on 127.0.0.1:8080 (GET only)
gaps_recorded_in: 04-UAT.md (## Gaps, G-4-R01..G-4-R12)
---

# Project review before the 2026-11-11 freeze

Whole-project review requested by the owner on 2026-11-09: bugs, skipper ergonomics, routing
calculation. The gaps the owner chose to fix are recorded in `04-UAT.md` (`## Gaps`, ids
`G-4-R01..R12`) for `/gsd-plan-phase 4 --gaps`. Everything else below is deferred with a reason.

## Verdict

No CRITICAL defect. Conventions (TWA sign, heading = TWD − TWA, bias rotation, u/v FROM, current
lee-bow, knots in route/*, m/s in nav/*) are consistent and numerically verified. Clock, atomic
persistence, bounded logs, forkserver router pool and the red-only night theme are sound. Three
items deserve a fix before the freeze: stale manual wind still drives the helm target (R01), a zone
exit alone advances the course (R02), and the "VIREZ" cue is the smallest text on screen (R03).

## A. Routing and navigation math

| id | sev | where | finding |
|----|-----|-------|---------|
| R02 | HIGH | `src/jabuka/nav/course.py:699-707` | After `_entered` (d ≤ radius + 0.25 nm) the candidate is `d > zone or _abeam(...)`: any zone exit held 10 s advances the course, whatever side the boat is on. Reproduced: approach Plić Sestre from the NNW to 0.45 nm, retreat on the same side, `active_idx` 1→2. Plausible at night (laylines target the anchor 0.3 nm from the mark, inside the 0.55 nm zone). Only safeguard: 60 s Annuler banner. Fix: on the zone-exit branch require the boat to be past the mark along the incoming leg (or the outgoing leg for hairpins), as `_abeam` already does. |
| R04 | MEDIUM | `src/jabuka/nav/polar.py:116-129,146-169` vs `src/jabuka/route/polar_grid.py:100-105` | The nav polar interpolates speed linearly between 150° and 180°, creating the VMG bump `polar_grid` fixes with its VMG-linear rule. Shipped X35 polar: helm "TWA CIBLE ↓" 170–171° at 14–25 kn vs router 180° (ORC gives 180°). When the route drops, the target jumps 10° and downwind laylines use 170°. Fix: same VMG-linear rule in `Polar.targets`, or derive helm targets from `PolarGrid`. |
| — | LOW | `polar_grid.py:187-189` vs `nav/polar.py:173-191` | Efficiency split differs (up < 90° / down ≥ 90° vs < 70° / > 110° / general). Only when efficiency_up/down are set. Deferred: default None. |
| — | LOW | `nav/polar.py:54-59` vs `polar_grid.py:91-96` | Polar tail beyond the last TWA: nav holds, router tails to 0.9×. Helm "% polar" reads low on a deep run. Deferred. |
| — | LOW | `route/isochrone.py:345-371` | Two-board arrival shot applies the tack penalty in time, not in geometry (~0.08 nm/tack). Deferred. |
| — | LOW | `isochrone.py:52,303` | Pinching speeds from the implicit (0°, 0 kn) point are optimistic at 30–35°; cannot beat two boards when beat angle < 49°, so only land-constrained expansions are affected. Deferred. |
| — | LOW | `route/advice.py:277-291,312-313` | Follower fallback reopens the whole path when the leg filter empties the candidates. Deferred (edge case). |
| — | LOW | `isochrone.py:415-494` | Exact calm (TWS = 0) loops to `max_steps` 800 before failing: ~40–60 s on the Pi, near the 60 s pool timeout. Deferred: realistic 1–2 kn fields converge. Watch Diag `timeouts` on the Pi. |

Verified correct: geodesy, bias estimator (learns 10.0°/1.20 from gated samples; decay), current
(10 nm upwind at 12 kn with 2 kn cross current → 1.806 h = hand-solved lee-bow), isochrone upwind
1.967 h vs D/VMG 1.944, downwind 1.596 vs 1.583, exact arrival shots, deterministic pruning, land
checks on every segment, backtracking, tack0 on the wrong tack, forced-tack release on land,
`evaluate_path` re-sails to the same ETA, laylines symmetric on both tacks, rounding waypoints A/B,
hairpin `_abeam`, router service staleness/withdrawal rules, no CPU-bound work on the loop.

## B. Runtime backend (core, ingest, common, deploy)

| id | sev | where | finding |
|----|-----|-------|---------|
| R05 | MEDIUM | `ingest/rawlog.py:192-202`, `core/main.py:204-230`, `core/nav_api.py:81-96`, `core/course_api.py:102-115`, `common/atomicio.py:28-42`, `core/router_service.py:727-733` | Synchronous fsync on the event loop: three logs fsync in the same 10 s tick; events, course edits, settings, route adoption and `bias.json` (every 60 s) do write + fsync + dir fsync inline. An SD garbage-collection stall of 5 s freezes tick, WS pushes and UDP consumption (loopback rcvbuf ≈ 3–4 s of bus); > 30 s trips `WatchdogSec=30`. Fix: fsync via `asyncio.to_thread`, or stagger `fsync_s`. |
| R06 | MEDIUM-LOW | `deploy/systemd/jabuka-core.service:31`, `route/pool.py:47-50` | The forkserver worker inherits `OOMScoreAdjust=-500`; under memory pressure the kernel kills gpsd, NetworkManager (the AP) or journald before the biggest allocator. Fix: write a positive value to `/proc/self/oom_score_adj` in `_pool_init`. |
| R12 | LOW | `deploy/systemd/jabuka-fastnet-relay.service`, `fastnet2ip.service` | Plan-B units lack `StartLimitIntervalSec=0`; a crash loop leaves them dead after 5 starts in 10 s. Main units are protected. |
| — | LOW | `core/tiles.py:208,222,232,236` | Sync `def` tile handlers run in the AnyIO threadpool (verified), not on the loop as the comment says; a zoom burst = 30 thread hops. Deferred: correct output, latency only. |
| — | LOW | `ingest/retention.py:148,178-185` | Retention ages by mtime; a > 36 h backward clock step plus budget pressure could prune recent raw files. Open files protected. Deferred. |
| — | LOW | `core/main.py:355-375` | No task-death supervision in the core; watchdog ping decoupled from the tick. Mitigated (tick loop catches, gpsd client never raises). Deferred. |
| — | LOW | `ingest/gpsd_client.py:279-281` | Diag shows `connected: True, mode: 3` after the receiver disappears (`mode` only updated on TPV). `alive`/stale are right. Deferred. |
| — | LOW | `core/main.py:327` | `json.dumps(diag)` without `allow_nan=False` (inputs are filtered). Deferred. |
| — | INFO | `fastnet_main.py:166-184` | Derived log ≈ 0.6 GB/day; `health()` omits `messages_sent`. Deferred. |

Checked and sound: monotonic staleness everywhere (`tests/test_no_wallclock.py` enforces by AST),
GPS clock with 3-fix sync/holdover/re-anchor, gpsd WATCH re-sent, backoff, mode < 2 rejected,
bounded resync; both Fastnet checksums checked, 8 KB buffer cap, NaN/Infinity rejected; tmp + fsync
+ `.bak` + rename + dir fsync, `.bak` fallback with alert, 409 concurrency, pydantic bounds; WS
per-client bounded queues drop-oldest, 20 s ping, client refetches on version mismatch, Host check,
64 KiB body cap, CSP, no request-derived paths (traversal probes 404); `Type=notify` + `WatchdogSec`
+ `Restart=always` + `StartLimitIntervalSec=0`, journald volatile 32 M, chrony `makestep 1 -1`,
gpsd `USBAUTO=false`; all per-tick containers bounded.

## C. Helm ergonomics (tablet UI)

| id | sev | where | finding |
|----|-----|-------|---------|
| R01 | P0 | `nav/wind.py:197,387`, `core/nav_service.py:209-215,265-287`, `web/static/helm_logic.js:69,168-185` | A MANUEL wind older than `manual_wind_max_age_min` only sets `sol.stale`; `WindSolution.ok` ignores it, so target TWA, laylines and countdown keep computing from hours-old wind. On the tablet only the top badge turns PÉRIMÉ; the 115 px number, deviation colours and countdown look live. Fix: when `nav.wind.stale`, show "VENT PÉRIMÉ" in the steer block and apply `.stale` dimming to blocks 1–2, or null `helm.target` in the core as for NONE. |
| R03 | P0 | `route_logic.js:49`, `app.css:120,165-171`, `helm_logic.js:198-212` | "VIREZ" is the countdown line (~26 px) while the primary box keeps the current-tack target until the core flips `target_tack`, then "MAUVAIS BORD". A missed cue costs a forced recompute 2 min later. Fix: when `countdown_s ≤ 0` or `wrong_tack`, the primary box shows VIREZ / EMPANNEZ + the new tack word. |
| R08 | P1 | `state.py:20`, `nav_service.py:131,260`, `helm_logic.js:156-177`, `route_logic.js:131` | GPS loss: label and number both "—", wind badge still green LIVE, only a 15–17 px "pas de position GPS" route status. Fix: red `PAS DE GPS` badge used as the primary label. |
| R09 | P1 | `app.js:125-133`, `app.css:150` | Brightness slider scales every night colour; at 40 % `--dim` = rgb(51,0,0): primary label, block-3 labels, route age/bias line, "Autre bord" vanish. Also `#primary-label` is 16 px: "TWA CIBLE ↑" vs "CAP À SUIVRE" is not glanceable. Fix: floor `--dim` (≥ ~rgb(110,0,0)) and size the primary label with `--f-word`/`--fg`. |
| R07 | P1 | `lock.js:155-167`, `lock_logic.js:26-30,44-47` | Unlock fires inside `tick()` once the primary pointer has been down 2 s; only a second pointer cancels. A water drop resting on the padlock for 2 s unlocks. Fix: unlock on `pointerup` between 2 and ~4 s. |
| R10 | P1 | `diag.css:1-10`, `app.css:240`, `diag.js` | Diag tab is white at night (`#diag-frame{background:#fff}`); one tap destroys night vision. Fix: read `jabuka.theme` in `diag.js` and add a red-on-black variant, or confirm before opening Diag in night mode. |
| R11 | P1 | `app.css:249-250` | `user-select:none`, `-webkit-touch-callout:none`, `overscroll-behavior:none` only on `#lock-overlay`: long-press on the big number opens Android's white selection sheet; pull-to-refresh reloads (~5 s blank). Fix: apply to `#helm-col`, `#topbar`, `.map-ctrls`, `html, body`. |
| — | P1 | `app.css:37,50-54,72-76` | Top bar non-wrapping flex, min-content ~700–750 px, `overflow:hidden`: padlock/badges may clip below ~800 px CSS width (8" tablet at DPR 1.5, 10" portrait). Deferred: verify on the real tablet (UAT test 8), then `flex-wrap` or icon tabs. |
| — | P1 | `overlays.js:413` | Course-up re-rotates with a 0.5° deadband at 1 Hz: chart wobbles with compass noise. Deferred: 3–5° deadband, check on the boat first. |
| — | P1 | `route_logic.js:31`, `helm_logic.js:205-207`, `i18n.js` | SL "desno"/"levo" under the TWA reads "turn right/left", not "starboard tack". Routed to UAT test 9 (SL proofreading): propose "tribord/bâbord amures" and the SL tack term. |
| — | P2 | `route_logic.js:216`, `overlays.js:246`; `helm.js:23-24`, `overlays.js:404`; `app.js:194`; `app.css:31`; `reglages.js:232`, `carte.js:771-773`; `lock-early.js:7-10`; `docs/TABLET-SETUP.md` §1 | Route vs port layline both red dashed at night; zoom not persisted; fullscreen only on the Nuit click; `color-scheme: only light` makes native selects white at night; `routing_enabled`/`variation_deg`/"Rendre active" save on one tap; transparent dead overlay if `lock.js` fails to import while locked; docs should mention Android's "stay connected without internet" prompt. Deferred. |

Done well: link watchdog dims the whole helm and prints PERTE DONNÉES, silent reconnect after a
power cut; night theme is red-channel-only end to end (tokens, map, controls, `style-night.json`);
lock restored before any module loads, ring progress, map handlers disabled while locked;
destructive course actions two-tap with undo; `coord_logic.js` accepts DD/DDM/DMS with comma or dot
and checks ranges and the race area.

## Demo checks worth doing (owner)

1. Enter Plić Sestre's zone (< 0.55 nm) and tack away without passing the mark: the course advances today (R02). Watch the Annuler banner in night mode.
2. Run leg at ≥ 14 kn: "TWA CIBLE ↓" (no route) vs "TWA ROUTE ↓" → 170 vs 180 (R04).
3. Real Hercules AWA sign on 12 Nov: watch "Écart TWA calculé/B&G > 10°"; `--awa-sign` if needed.
4. Jabuka magnetic zone with SOG < 1 kn: no TWA/laylines, "On reste impossible : amure inconnue"; route band and `wrong_tack` must not flicker.
5. Pack with current + `route_current` on: forced/stay route under a cross current; "Cap route" vs layline CTS agree in sense.
6. Pi: near-calm GRIB patch, cycle time vs the 60 s pool timeout; Diag `timeouts`.
