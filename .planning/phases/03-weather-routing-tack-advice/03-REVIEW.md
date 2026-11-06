---
phase: 03-weather-routing-tack-advice
reviewed: 2026-11-06T19:25:52Z
depth: deep
files_reviewed: 33
files_reviewed_list:
  - src/jabuka/route/__init__.py
  - src/jabuka/route/advice.py
  - src/jabuka/route/bias.py
  - src/jabuka/route/cycle.py
  - src/jabuka/route/evaluate.py
  - src/jabuka/route/fields.py
  - src/jabuka/route/frame.py
  - src/jabuka/route/isochrone.py
  - src/jabuka/route/landmask.py
  - src/jabuka/route/polar_grid.py
  - src/jabuka/route/pool.py
  - src/jabuka/route/pool_probe.py
  - src/jabuka/route/racepack.py
  - src/jabuka/route/rounding.py
  - src/jabuka/route/types.py
  - src/jabuka/route/bench.py
  - src/jabuka/prep/grib.py
  - src/jabuka/prep/dwd.py
  - src/jabuka/prep/current.py
  - src/jabuka/prep/wxpack.py
  - src/jabuka/prep/land.py
  - src/jabuka/prep/cli.py
  - src/jabuka/core/router_service.py
  - src/jabuka/core/route_api.py
  - src/jabuka/core/main.py
  - src/jabuka/core/nav_service.py
  - src/jabuka/nav/wind.py
  - src/jabuka/nav/settings.py
  - src/jabuka/web/static/route.js
  - src/jabuka/web/static/route_logic.js
  - src/jabuka/web/static/helm.js
  - src/jabuka/web/static/helm_logic.js
  - scripts/racepack-dryrun.sh
findings:
  critical: 6
  warning: 5
  info: 8
  total: 19
by_severity:
  critical: 2
  high: 4
  medium: 5
  low: 8
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-06T19:25:52Z
**Depth:** deep. I followed the whole chain: the race-pack prep tools, the pack loader, the weather fields and bias, the isochrone router and land mask, the worker pool, the core supervisor (`RouterService`), the REST/WS route message and the helm and route UI.
**Files Reviewed:** 33. `bench.py` was only skimmed: it is a laptop/Pi measuring tool and nothing in it reaches the helm.
**Status:** issues_found

Severity mapping: BLOCKER = critical/high, WARNING = medium, INFO = low.

## Summary

**Scope.** The review covers `/usr/bin/git diff 1f56fa5^..ad9fd01` restricted to the paths in the request:

- `route/`
- `prep/{grib,dwd,current,wxpack,land,cli}.py`
- `core/router_service.py` and `core/route_api.py`
- the Phase 3 hunks of `nav/wind.py`, `nav/settings.py`, `core/main.py` and `core/nav_service.py`
- `web/static/route*.js` and the helm hunks of `helm.js`/`helm_logic.js`
- `scripts/racepack-dryrun.sh`

The interleaved Phase 2 review-fix commits were not re-reviewed.

**Method.** Every important finding was confirmed by running code. The scripts are in the session scratchpad (`stale_route.py`, `course_change.py`, `missed_stuck2.py`, `pool_wedge.py`, `tack_now.py`, `bias_stale.py`). They drive:

- the real `RouterService` through the committed `tests/routing/conftest.py` harness (`RoutingCore` + `FakePool`)
- the real `RouterPool` with forkserver workers
- the real isochrone router on the committed 25 m race mask

**What is sound.**

- **Never crossing land (ROUT-11).** I fuzzed `LandMask.segments_clear` against sampling at 1/20 of a cell. Over 40 000 random segments (0.01 to 3 nm) on the real 25 m race mask it gave 28 311 "clear" answers and no false clears.
  - Every shipped path goes through `validate_polyline` before it is returned as `ok`.
  - Decimation shortcuts, two-board arrival shots and the margin exit segment are each land-checked.
  - The land, rounding, advice, bias and pool suites pass (88 tests).
- **Conventions.** These hold at every boundary I traced:
  - heading = TWD − TWA, with TWA negative = port (`isochrone.heading_from_twa`, `_shots`, `advice.target_heading`)
  - wind FROM = atan2(−u, −v)
  - current is a TOWARDS vector: subtracted from the air motion to get the wind over the water, added to the ground displacement
  - the bias rotation is clockwise for a positive offset
  - Cramer's rule in the two-board shot is right
- **Time.** GRIB valid times are UTC epoch, from eccodes' `validityDate`/`validityTime`. Domain code has no wall-clock calls; the only `datetime.now` calls are in laptop prep metadata.
- **Pool recovery.** Timeout kill and crash recovery work for the failure modes they anticipate.
- **REST bodies** are strict: `extra="forbid"` and `StrictBool`.

**Key concerns.** All of them are in the supervisor and the advice, not in the geometry:

1. One unexpected exception permanently wedges the routing pool.
2. An adopted route is never withdrawn. After a course change, a persistently failing worker, or a missed tack whose reroute fails, the helm keeps steering an old route that reports `state: "ok"`. "Route mise à jour…" then stays up for as long as the worker keeps failing (30 min in the test). Because the route is "ok", the Phase 2 layline fallback never comes back.
3. A tack the route wants *right now* (at t0) is never announced: no countdown, no VIREZ, no missed-tack reroute, and the deviation reads 0 on the wrong tack.
4. A GRIB bias learned hours earlier comes back at full strength after a single gated sample.
5. The generic GRIB importer does not rotate grid-relative u/v, so organiser files on rotated or Lambert grids are off by 4–11°.
6. On the Jabuka hairpin the follower can latch onto the return leg and never come back.

## Critical Issues

### CR-01: [BLOCKER / critical] One unexpected exception while submitting a job wedges the RouterPool for the rest of the race, silently

**File:** `src/jabuka/route/pool.py:179-195` (`_job`), `:207-223` (`_execute`); `src/jabuka/core/router_service.py:710-724`

**Issue.** `_execute` catches only `BrokenProcessPool`/`RuntimeError` around `self.start()` and the first `ex.submit`. The retry branch (`:216-223`) is not guarded at all.

On Python 3.13 the submit spawns the worker through the forkserver. Any other exception propagates out of `_execute` and `_job`. Examples:
- `OSError` ENOMEM/EAGAIN when the fork fails on a 1 GB Pi under memory pressure
- EMFILE (too many open files)
- a second `RuntimeError` in the retry

When that happens, `_job` skips `self._busy = False` and the pending-launch code. From then on, every `run_latest` sees `_busy` True and parks as the pending request, and nothing ever launches it. The request futures never resolve. `RouterService._inflight` stays above 0, and the task's exception is never retrieved (only a GC-time log line). No restart path exists. `RouterService` has no watchdog on "running for longer than the timeout".

**Reproduced** (`pool_wedge.py`, real forkserver pool, one injected `OSError(12)` on the second submit):
```
job1 ok
job2 done? False | pool task exception: OSError(12, 'Cannot allocate memory')
job3 never runs: pool wedged, stats {... 'running': 1, 'pending': 1}
```

**Failure scenario.** At hour 20 the Pi is short on memory and one fork fails. Routing stops for the remaining 16 h. The helm keeps showing the last route as "ok" with a growing age (CR-02), and the only trace is `running: 1` on the Diag pool row.

**Fix.** Make `_job` total, and add a stuck-job watchdog in the service:
```python
async def _job(self, req):
    try:
        outcome = await self._execute(req.fn, req.arg)
    except asyncio.CancelledError:
        ...  # as today
        raise
    except Exception as exc:  # never leave _busy set
        self._stats["errors"] += 1
        outcome = PoolOutcome("error", None, 0.0, repr(exc))
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._discard)  # next job recreates the executor
    if not req.fut.done():
        req.fut.set_result(outcome)
    self._busy = False
    ...  # launch pending as today
```
Also wrap the retry `self.start()`/`submit` in the same `try`. In `RouterService._tick`, if `pool.stats["running"]` has been 1 for more than `2 * POOL_TIMEOUT_S`, call `pool.close()`, build a fresh pool and raise an alert.

### CR-02: [BLOCKER / critical] The adopted route is never withdrawn: a changed course, a dead worker or a failed missed-tack reroute leave the helm steering a stale route marked "ok"

**Files:**
- `src/jabuka/core/router_service.py:843-865` (`_fill_advice` sets `state "ok"` whenever `self.route` exists)
- `:757-759` (course check only on new results)
- `:814-816` (`missed` cleared only in `_adopt`)
- `:1001-1018` (`restore` shows a route of any age)
- `src/jabuka/web/static/route_logic.js:56,72-89`

**Issue.** Once a route is adopted, `_fill_advice` reports `state: "ok"` and fills the target TWA/heading, the countdown and the cost from it for as long as `self.route` is set.

Nothing clears or downgrades it:
- **Course change.** `course_version` is checked on incoming results, but never against the displayed route.
- **Failures.** `_last_fail` is only used when there is no route.
- **Age.** `ROUTE_MAX_AGE_S` only feeds the hysteresis; the UI merely tints the age label amber after 20 min.

Separately, `self.missed` (`updating`) is set by the missed-tack watch and reset only when a new route is adopted. Because the route is "ok", `routeOk()` keeps the helm on the route and the Phase 2 layline fallback never returns.

**Reproduced** with the real `RouterService` and the test harness:
- **Worker failing (`stale_route.py`).** Every job times out after the first adoption. Three hours later: `state ok age_s 10801.0 reason None target_twa 40.0 countdown 1800.0`, while `health.last_fail` = "timeout: no result after 60 s".
- **Course change (`course_change.py`).** The navigator advances the course from Plić Sestre to Jabuka and the worker crashes. Two minutes later the nav block is still `state ok`, steering the route whose only leg is `plic-sestre`, with `route.course_version 0` against a live course version of 1.
- **Missed tack (`missed_stuck2.py`).** The advised tack is missed and the reroute crashes. From +200 s to +1799 s: `state ok missed True updating True countdown -1739`. The helm shows "Route mise à jour…" for half an hour, never VIREZ, and never the layline countdown.

**Failure scenario.** After Plić Sestre the navigator switches to Course B, or a mark is moved. If the reroute fails, the helmsman keeps getting "TWA ROUTE 40° tribord" and tack countdowns toward the previous mark, with nothing on the helm to say they are wrong.

**Fix.** Downgrade or withdraw in `_tick`, before `_fill_advice`:
```python
r = self.route
if r is not None and (
    r.course_version != self.nav.course.version         # computed for another course
    or now - r.t0 > ROUTE_STALE_S                        # e.g. 2 x ROUTE_MAX_AGE_S
):
    self._set_state(block, "outdated", "route périmée : recalcul en cours")
    # do not fill target/countdown -> routeOk() false -> Phase 2 laylines come back
```
Also:
- Clear `self.missed` (or time-box `updating` to about 3 min) when the reroute it asked for ends in failure.
- Have `routeBand` show `last_fail` while a route is displayed.
- Keep the outdated line on the map greyed out instead of in route colours.

## High

### HI-01: [BLOCKER / high] A tack the route schedules at the start (t = t0) is never announced; the deviation reads 0 while the boat is on the wrong tack

**Files:**
- `src/jabuka/route/advice.py:257` (`upcoming = next(k for k in self.tacks if k[0] > t_here)`)
- `src/jabuka/core/router_service.py:1216` (`tk.t > r.adopted_t`)
- `src/jabuka/route/isochrone.py:629-640` (emits a TackPoint at t0 when the first segment's tack differs from `tack0`)
- `src/jabuka/core/router_service.py:880-884` (TWA deviation ignores the sign)

**Issue.** When the optimal route starts on the other tack, `_tack_points` emits the tack at `t = t0`. Two strict comparisons then skip it:
- `RouteFollower.follow` keeps only tacks strictly after the boat's route time. At the start, `t_here == t0`, so the tack is skipped. If the boat stays on the old tack its projection does not advance, so the tack is never reached.
- `route_message` drops it from `next_tack` for the same reason.

The countdown is `None` ("Pas de virement prévu"). `MissedTackWatch` never fires. The primary number switches to the new tack's TWA, but the deviation is `|TWA_now| − |target|`, which is 0 for −40° against +40°.

**Reproduced** (`tack_now.py`, real router, real 25 m mask, wind 045/18 kn, boat on port 4 nm S of Plić Sestre):
```
tacks [(0, -1, 1, 'tack')]
0   target_twa 40.0 next_tack None countdown None
300 target_twa 40.0 next_tack None countdown None
```

**Failure scenario.** This is the most common "tack now" case: right after a wind shift or a reroute. The helm shows "TWA ROUTE 40° tribord", a deviation of 0° (green) and "Pas de virement prévu" while the boat sails port. The only recovery is the off-route soft trigger 2 min later, which routes from the boat again and reproduces the same t0 tack.

**Fix.**
- Use `>=` with a tolerance: `next((k for k in self.tacks if float(k[0]) >= t_here - 1.0), None)`. The existing `_advised` overdue logic then turns it into VIREZ and, after 2 min, a missed tack. Do the same in `route_message`.
- In `_fill_advice`, when `self._tack0(msg)` is non-zero and differs from `f.target_tack`, set `countdown_s = 0` and `deviation = None` (or a "MAUVAIS BORD" flag), never a signed |TWA| difference.

### HI-02: [BLOCKER / high] The GRIB bias learned hours ago returns at full weight after a single gated sample (and after every restart)

**File:** `src/jabuka/route/bias.py:197-218` (`update`), `:252-260` (`params`), `:321-345` (`from_json`)

**Issue.** The EMA state (`_s`, `_c`, `_m`, `_g`) only moves on gated samples (`alpha = 1 - exp(-dt/600)`, with dt capped at 10 s). Nothing ages it while the gate is closed.

Meanwhile the decay weight `w = exp(-(t - t_obs)/tau_decay)` is reset to 1 by *any* new gated sample, because `t_obs = sample.t`. After a long closed-gate period, the first gated second re-applies the hours-old estimate at full strength, and it then takes about 10 min of EMA to fade. `_gated_s` also stays above `min_gated_s`, so there is no re-learning period. Closed-gate periods include:
- the Jabuka zone
- light air
- MANUEL or GRIB source
- a core restart (the state is restored from `bias.json`)

**Reproduced** (`bias_stale.py`): learn +30° ×1.25, close the gate for 6 h (decayed to +2.7° ×1.02), then feed one sample where measured equals the GRIB:
```
6h later (decayed)    2.7  1.02  s'estompe
1 gated sample later  29.5 1.25  actif
60 s later            26.8 1.25  actif
```

**Failure scenario.** The boat leaves the Jabuka zone at night after 4 h of frozen bias. The router immediately gets a TWD 25–30° off (the clamp is 35°) and a 25 % speed ratio, both on the GRIB-only helm wind and in every isochrone. That fires a bias reroute and adopts a route built on a stale wind. The helm text says "actif".

**Fix.** Treat a gap longer than `tau_ema_s` as a new learning episode:
```python
if self._t_obs is not None and sample.t - self._t_obs > self.tau_ema_s:
    # keep the old estimate only as a decaying fallback, start learning afresh
    self._fallback = (*self.raw(), self._t_obs)   # used by _source() until the new EMA is valid
    self._s = self._c = self._m = self._g = 0.0
    self._gated_s = 0.0
```
`_source()` then uses `_fallback` (with its original `t_obs`, so it keeps decaying) until `_gated_s >= min_gated_s` again. `from_json` should restore the EMA as such a fallback, never as the live EMA.

### HI-03: [BLOCKER / high] Organiser GRIB on a rotated or Lambert grid: grid-relative u/v are taken as east/north (4–11° wind-direction error)

**File:** `src/jabuka/prep/grib.py:452-467` (projected/rotated branch), `:474-494` (regrid)

**Issue.** `import_generic` reads u/v from any grid type and IDW-regrids them as earth-relative components. It never reads `uvRelativeToGrid` / `resolutionAndComponentFlags`.

For rotated-pole (COSMO/ICON-LAM style) and Lambert conformal grids (WRF, ALADIN), u/v are normally grid-relative. Grid north differs from true north at the race area by:
- **4.3°** at 15.6 E for the test fixture's own rotated pole (south pole −40 N 10 E; computed bearing to the rotated north pole 40 N 170 W)
- about 4° for a Lambert grid with LoV 10 E
- about 11° for LoV 0°

The test `test_rotated_grid_regridded_to_regular_0025` only checks that values are finite.

**Failure scenario.** The organiser's WRF/OpenSkiron file is imported. Every TWD in `wind.npz` is rotated by a constant 4–11°. The router picks the wrong tack and the wrong laylines. The bias estimator partly hides the error near the boat, but only in time and with decay, never along the rest of the route.

**Fix.**
- When `_key(g, "uvRelativeToGrid") == 1` (GRIB2 flag bit 5; GRIB1 `resolutionAndComponentFlags` & 0x08), rotate each (u, v) to earth-relative before regridding. Take the local grid-north angle from `g.latlons()`: the bearing between neighbouring points along the j axis.
- If the angle cannot be computed, refuse the file with a clear French error.
- Add a test with a grid-relative rotated message whose expected TWD is known.

### HI-04: [BLOCKER / high] RouteFollower latches onto the return leg of a hairpin and can never come back

**File:** `src/jabuka/route/advice.py:239-246` (`follow`), `:215-221` (`_nearest`)

**Issue.** The projection takes the nearest segment among the next `SEARCH_AHEAD = 40` segments, with ties going to the later one. The decimated path for a whole course is often fewer than 40 segments. `_idx` is then never allowed to decrease, and the "global" search also starts at `lo`.

On the Jabuka hairpin, the outbound and return tracks pass within a few cables. If the boat is a little off its own route on the side of the return track, it projects onto the return leg. From then on:
- the target TWA, the tack and the countdown are those of the return leg
- `remaining_s` (the ETA) loses the whole outbound leg plus the rounding
- it never projects back, even when the boat is back on its own track

**Reproduced** with a synthetic hairpin: outbound stbd TWA +40, return 0.6 nm east at TWA −140. The boat is 0.35 nm east of its route:
```
y=3.0: seg 18 target_twa -140.0 remaining 0.50 h xte 0.25
back on own route y=6.5: seg 18 target_twa -140.0 xte 3.55
```

**Failure scenario.** Approaching Jabuka at night, the helm switches to "TWA ROUTE ↓ 140° bâbord" while the boat is beating. The only recovery is the off-route soft trigger (COG about 180° off for 2 min), followed by the routing time.

**Fix.**
- Bound the search by route time: only accept segments whose time range overlaps `[t_here_prev - 10 min, t_here_prev + (t_now - t_prev) + 30 min]`.
- Allow a backward re-projection inside that window.
- Among near-ties, prefer the segment whose course is closest to COG.
- Never jump across a leg arrival point unless the boat is within the mark zone.

## Warnings

### MD-01: [WARNING / medium] NaN wind cells become 0 kn of wind (router calms and a GRIB-only helm wind of 0 kn / 180°)

**Files:** `src/jabuka/route/fields.py:138-139,151-152`; `src/jabuka/route/racepack.py:144-147`; `src/jabuka/prep/grib.py:136,447-450`

**Issue.**
- `_check_grid` accepts a wind cube as long as each time step has *some* finite value.
- The prep keeps masked or bitmap cells as NaN, and fills only the waves.
- The IDW regrid leaves NaN beyond `max_dist` at the edges.
- `WindField.uv_kn`/`at` then turn every NaN (and every bilinear stencil touching one) into u = v = 0.
- `_grib_raw` checks `isfinite` *after* `nan_to_num`, so it returns a finite calm.

The coverage report only checks marks and the straight legs, not the area the isochrones explore.

**Reproduced.** A pack whose wind is NaN west of 15.4 E loads with `errors: []`:
```
lon 15.2:  TWS 0.00 kn TWD 180
lon 15.45: TWS 0.00 kn TWD 180   (stencil touches a NaN cell)
lon 15.6:  TWS 13.75 kn TWD 45
```

**Failure scenario.** An organiser GRIB with land-masked cells, or a projected grid with NaN edges, creates "holes of calm". The router detours around them. In GRIB-only mode the helm shows a GRIB wind of 0 kn from 180°.

**Fix.**
- In prep, `fill_nearest` u and v together for wind, as for waves, and report the filled fraction.
- In `racepack._check_grid`, reject or alert when any wind NaN remains inside `RACE_BBOX`.
- At runtime, keep NaN out of `uv_kn` and make `_grib_raw` return `None` on a NaN stencil instead of a calm.

### MD-02: [WARNING / medium] A detected tack never triggers a reroute; COG noise at low speed causes reroute churn

**Files:**
- `src/jabuka/core/router_service.py:376-382` (a `TackEvent` only ends "On reste")
- `src/jabuka/route/advice.py:453-471` (`OffRouteWatch` has no SOG gate)
- `src/jabuka/core/router_service.py:773-774` (off-route forces "outdated")

**Issue.**
- **Early tack.** When the helmsman tacks early (say 3 min before the advised point), `_advised` keeps counting down to the tack he has already made. Nothing reroutes until `OffRouteWatch` has seen a course deviation for 2 min, plus the routing time.
- **Low-speed COG.** `OffRouteWatch` compares raw GPS COG with the segment course at any speed. In light air at night (SOG < 1–2 kn) COG wanders by tens of degrees. That fires an `off_route` trigger every 2 min, and the result is always adopted because `age` is forced past `ROUTE_MAX_AGE_S`. Each adoption writes `route.json` and resets the helm countdown.

**Fix.**
- On a `TackEvent` whose new side differs from the followed segment's `target_tack`, call `self.request("tack", forced=False)` with the same "outdated" treatment as off-route.
- Ignore `course_dev_deg` when SOG < 2 kn (or use the damped COG).

### MD-03: [WARNING / medium] Hysteresis input: the old route is re-evaluated from a global nearest projection and ignores the cross-track distance

**File:** `src/jabuka/route/evaluate.py:28-38,76-80`; `src/jabuka/core/router_service.py:771-782`

**Issue.**
- `evaluate_path` projects the boat onto the nearest segment of the *whole* old path; this is the same hairpin hazard as HI-04.
- It re-sails from the projected point, so the boat-to-route distance costs nothing.

On the hairpin, or after a long excursion, `eta_old_now` can come out hours too early. Every better new route then fails the `gain > max(3 min, 1 %)` test and is "kept" for up to 20 min, until `ROUTE_MAX_AGE_S`.

**Fix.**
- Pass the follower's current segment index (`self.follower.idx`) in the `CycleRequest` and project only from it, inside the HI-04 time window.
- Add the time to rejoin: XTE divided by the BSP at the reaching angle.

### MD-04: [WARNING / medium] "Ne pas virer : +N min" can come from a route that was not adopted

**File:** `src/jabuka/core/router_service.py:743-744,783-786,908-910`

**Issue.** `cost_s` is overwritten from every forced cycle *before* the result is checked against the course version and before the hysteresis. When the hysteresis keeps the old route ("kept"), or the result is superseded by a course change, the helm shows a cost computed for the new optimal route's tack timing. That cost sits next to the countdown of the old, displayed route.

**Fix.** Store the cost with the route it belongs to: set `cost_s` only in `_adopt` from the adopted `CycleResult`. Alternatively, keep `(cost_s, request_id)` and display it only when it matches the adopted route's request.

### MD-05: [WARNING / medium] The core and the worker load the race pack independently, and a restored route is never re-validated

**Files:**
- `src/jabuka/core/router_service.py:228-248,260-273` (pack loaded once at startup; the `pack_version` trigger can never fire)
- `src/jabuka/route/cycle.py:81-88` (every new worker process reloads the pack from disk)
- `src/jabuka/core/router_service.py:1001-1018` (restore checks only `course_version`)

**Issue.**
- **Two copies of the pack.** The core (GRIB-only wind, bias reference, coverage) keeps the pack it read at startup. Each worker (first job, and every timeout or crash restart) reads whatever is on disk at that moment. If the pack is replaced without restarting the core (`docs/WEATHER-PACK.md` asks for a restart, but nothing enforces it), the bias is learned against one GRIB and applied by the router to another, and the coverage alerts describe the old pack.
- **No integrity check on the land mask.** `landmask.npz` is opened without its sidecar sha256 at runtime.
- **Restored route.** After a reboot, a `route.json` computed against a previous pack or mask is shown as "ok" until the first cycle replaces it. Nothing re-validates it against the current mask.

**Fix.**
- Record the sha256 of `wind/waves/current/landmask` at core startup and send it in each `CycleRequest`. The worker returns a "pack changed" failure (or reloads) on mismatch, and the core shows an alert asking for a restart.
- Verify `landmask.json`'s sha256 in `build_env`.
- Show a restored route only after the first worker cycle reports `old_valid is True`.

## Info

### LO-01: [INFO / low] Manual wind entries made while the GPS clock is not synced are never observed

**File:** `src/jabuka/core/router_service.py:383-392`

**Issue.** The change key is `entry.t_set_wall`, which is `None` without trusted UTC (`nav/settings.py` ManualWind). Clearing an entry and setting a new one without GPS time both give the key `None`. The `manual_version` bump (reroute trigger) and the bias observation are both skipped.

**Fix.** Key on `id(entry)` or on a counter that `ManualWindStore.set/clear` increments.

### LO-02: [INFO / low] The route line on the map can be truncated

**File:** `src/jabuka/route/isochrone.py:754-758`; `src/jabuka/core/router_service.py:1192`

**Issue.** Decimation stops at `tol > 1.0` even when the path still has more than 300 points. `route_message` then keeps only `path[:300]`, so the map line stops short of the finish.

**Fix.** Keep doubling `tol` until the path fits, or decimate evenly in `route_message` instead of truncating.

### LO-03: [INFO / low] Worker caches grow without bound over 36 h

**File:** `src/jabuka/route/isochrone.py:82-84,99-120`

**Issue.**
- `geo_cache` gets one on-demand geofield (about 0.7 MB) per new mark key: every moved or added mark.
- `polar_cache` gets one PolarGrid (about 0.6 MB) per efficiency setting change.

They are never evicted, and are reset only when the worker happens to be restarted.

**Fix.** Use a small LRU (e.g. 8 entries each).

### LO-04: [INFO / low] Failures are classified as "ROUTE INVALIDE" by French substring matching

**File:** `src/jabuka/core/router_service.py:93,748`

**Issue.** Any reason containing "invalide", "terre" or "masque" raises the 5-min "ROUTE INVALIDE" alert. That includes "réglages invalides", "requête invalide", "marque invalide" and "départ dans la terre" (a GPS glitch).

**Fix.** Have the worker return a machine-readable `kind` (`"land"` / `"input"` / `"engine"`) in `RouteResult`.

### LO-05: [INFO / low] The generic GRIB importer silently overwrites duplicate messages for the same valid time

**File:** `src/jabuka/prep/grib.py:450,467`

**Issue.** `recs.setdefault(t, {})[kind] = ...` keeps the last message per (valid time, component). A file with ensemble members, several runs or several levels mapped to 10 m can produce u from one member and v from another, with no warning. `decode_wind_files --from-files var/cache/prep/icon-eu` likewise mixes cached runs under the first run's metadata.

**Fix.** Refuse duplicates unless `perturbationNumber`/`dataDate` are identical, and print which run was kept.

### LO-06: [INFO / low] `bias.json` is only partly validated

**File:** `src/jabuka/route/bias.py:321-345`

**Issue.** `config` values are passed straight to the constructor. A `tau_ema_s` of 0 makes every `update` raise `ZeroDivisionError`, which turns every tick into `route.state "failed"`. `t_obs` and `manual` are not checked for being finite, so a NaN `t_obs` gives NaN weights.

**Fix.** Range-check the config (or ignore it and keep the code defaults) and require finite `t_obs` and `manual`.

### LO-07: [INFO / low] Prep and script robustness

**Issue.**
- `scripts/racepack-dryrun.sh:33-36`: the `var/*` guard accepts `OUT=var/../../tmp/x`.
- `src/jabuka/prep/dwd.py:311`: `urlopen` follows redirects to any host after `check_host` approved the first URL.
- `src/jabuka/prep/current.py:69-75`: a NetCDF time variable without `units` raises an uncaught `AttributeError` (a traceback instead of the French `PrepError`).

**Fix.**
- Use `realpath` and check the prefix in the script.
- Use an opener whose redirect handler re-runs `check_host`.
- Catch `AttributeError` and report "time sans unités".

### LO-08: [INFO / low] After a land release, "Virement imposé (terre) dans 00:00" replaces VIREZ

**File:** `src/jabuka/web/static/route_logic.js:78-80`; `src/jabuka/core/router_service.py:854-856`

**Issue.** Once `release_in_s` goes negative, `fmtClock` clamps it to 00:00 and the warn line wins over the countdown branch. The helm never shows the red VIREZ for a land-forced tack; it only switches to "Route mise à jour…" once the missed-tack watch fires.

**Fix.** Show the land line only while `release_in_s > 0`, and fall through to the VIREZ branch afterwards.

---

_Reviewed: 2026-11-06T19:25:52Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
