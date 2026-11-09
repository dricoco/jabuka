---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-09T12:48:56Z
depth: standard
scope: incremental (dbcd536..HEAD 215d3d2, gap-closure plans 04-09..04-12, G-4-R01..R12)
files_reviewed: 43
files_reviewed_list:
  - deploy/systemd/fastnet2ip.service
  - deploy/systemd/jabuka-core.service
  - deploy/systemd/jabuka-fastnet-relay.service
  - docs/COMMISSIONING.md
  - docs/I18N-SL-REVIEW.md
  - docs/ROUTING.md
  - docs/TABLET-SETUP.md
  - src/jabuka/common/atomicio.py
  - src/jabuka/core/main.py
  - src/jabuka/ingest/fastnet_main.py
  - src/jabuka/ingest/rawlog.py
  - src/jabuka/nav/course.py
  - src/jabuka/nav/polar.py
  - src/jabuka/route/pool_probe.py
  - src/jabuka/route/pool.py
  - src/jabuka/web/static/app.css
  - src/jabuka/web/static/app.js
  - src/jabuka/web/static/diag.css
  - src/jabuka/web/static/diag.html
  - src/jabuka/web/static/diag.js
  - src/jabuka/web/static/diag-theme.js
  - src/jabuka/web/static/helm.js
  - src/jabuka/web/static/helm_logic.js
  - src/jabuka/web/static/i18n.js
  - src/jabuka/web/static/lock.js
  - src/jabuka/web/static/lock_logic.js
  - src/jabuka/web/static/route_logic.js
  - tests/deploy/test_units.py
  - tests/nav/test_course.py
  - tests/nav/test_polar_vmg.py
  - tests/nav/test_wind.py
  - tests/route/test_pool.py
  - tests/test_background_durability.py
  - tests/test_helm_logic.py
  - tests/test_lock_logic.py
  - tests/test_route_logic.py
  - tests/ui/test_helm_column.py
  - tests/ui/test_helm.py
  - tests/ui/test_i18n_ui.py
  - tests/ui/test_lock_wake.py
  - tests/ui/test_night.py
  - tests/ui/test_route_ui.py
  - tests/ui/test_tablet_hardening.py
findings:
  critical: 1
  warning: 7
  info: 4
  total: 12
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-09..04-12)

**Reviewed:** 2026-11-09T12:48:56Z
**Depth:** standard (diff dbcd536..HEAD plus the code it calls)
**Files Reviewed:** 43
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

This review covers the gap closures G-4-R01..R12:

- the background durability thread (`atomicio`, `rawlog`, core and ingest entry points)
- the zone-exit latch in `course.py`
- VMG-linear polar interpolation
- the routing worker's `oom_score_adj`
- the helm takeovers (stale wind, no GPS, VIREZ/EMPANNEZ cue)
- the release-to-unlock padlock
- night text floor, Diag night theme and the anti-selection CSS

The targeted suites pass (407 tests in `tests/test_background_durability.py`, `tests/nav`, `tests/route/test_pool.py`, `tests/test_no_wallclock.py`, the lock/helm/route logic and the deploy tests). Several modules held up under tracing:

- **Durability thread:** FIFO order, the `.bak` chain, the orphan sweep (it cannot delete a temp from the current process), `test_no_wallclock` compliance and the counter locking.
- **`raise_oom_score_adj`:** it cannot crash the worker initializer.
- **Polar:** the VMG-linear interpolation stays continuous at 120 deg and never divides by less than cos(60 deg).
- **Lock:** the release-only unlock works. A held press past 4 s is voided both in `check()` and in `up()`.

**The critical defect:** G-4-R02 swapped the old lenient rule ("a zone exit after entering advances") for a strict "past the mark along the incoming leg *now*" rule on every non-hairpin mark. The new rule ignores the latch it introduced. Some ordinary roundings now leave the course stuck on the mark for good. This was reproduced against both the new code and the pre-change `course.py` (CR-01).

**Warnings:**

- The background write mode hides SD failures from the helm and from the Diag alerts.
- A new rawlog flag can get stuck.
- Moving the active mark keeps the old latch.
- The night text floor erases the "dim = stale" signal.
- Manual wind of unknown age still drives the tack cue.
- Plan B dies after a single relay crash. `StartLimitIntervalSec=0` does not fix that.
- The ingest shutdown can skip the drain.

## Critical Issues

### CR-01: A non-hairpin mark whose zone is left on the approach side of the abeam line never advances (stuck on the mark rounded)

**File:** `src/jabuka/nav/course.py:676-688` (`_past_mark`), `:752-758` (call site), `:736-741` (Annuler path)

**Issue:** For `abs(turn) <= HAIRPIN_DEG` (Plić Sestre 43 deg, Blitvenica 41 deg, Mulo -61 deg, every custom mark with a turn up to 90 deg), a zone exit now counts only if `dot_in > 0.0` *at the moment of the exit*. The `_beyond` latch is set on every tick (line 754) but is read only in the hairpin branch.

If the turn plus the first tack takes the boat to more than 90 deg off the incoming bearing, it leaves the zone with `dot_in < 0`. That happens with a 60-89 deg turn followed by a beat at 45-50 deg. After that, the only remaining trigger is `_abeam` (`dot_in > 0` for 10 *consecutive* seconds). That fails in two cases:

- **Tight rounding:** a rounding at 2-3 boat lengths spends less than 10 s past the abeam line, and GPS jitter of a few metres around `dot_in = 0` makes it shorter still.
- **Mis-placed custom mark:** the committee mark was typed or tapped some tens of metres beyond the real buoy, so the boat is never past the *entered* point at all.

The candidate is reset, the zone exit is rejected, and the gate reset at 2 nm then clears `_entered`. The course stays on the rounded mark forever, and the router keeps steering back to it.

Reproduction: Course A with a custom mark (default radius 0.05) inserted at index 1, a 60 deg turn, and the boat rounding at 0.01 nm then sailing out at turn + 45 deg:

```
new code: 60 45 err=0.05 nm  -> STUCK on m1, 2.9 nm away
          45 50 err=0.05 nm  -> STUCK on m1, 2.9 nm away
          60 45 err=0.0      -> STUCK on m1, 2.9 nm away
          (tight rounding r=0.005 nm, turns 60..89 deg, tack 45/50: STUCK in every case)
dbcd536:  the same five tracks -> all advanced (t=460..471 s)
```

The Annuler path has the same flaw. Line 741 sets `_beyond = True` "as the rounding evidence", but a non-hairpin exit ignores `_beyond`. So the CR-02 rationale in the comment above it ("Discarding it would leave the course stuck on the mark just rounded") is only implemented for hairpins.

**Fix:** For non-hairpin marks, accept the latch, and accept "past along the outgoing leg". Neither of the G-4-R02 repros satisfies either condition. At Plić, the NNW retreat (bearing 341) has `dot_out = cos 138 < 0` and the ENE retreat (bearing 51) has `dot_out = cos -152 < 0`, and neither ever has `dot_in > 0`.

```python
def _past_mark(self, dots):
    if dots is None:
        return True
    dot_in, dot_out, turn = dots
    if turn is None or dot_out is None or abs(turn) <= HAIRPIN_DEG:
        # past the abeam line now, or at any time since entering the zone, or already out
        # along the next leg (a mark entered a few tens of metres off still advances)
        return self._beyond or dot_in > 0.0 or (dot_out is not None and dot_out > 0.0)
    return self._beyond and dot_out > 0.0
```

Add the tight-rounding and mis-placed-mark tracks above as regression tests next to `test_leaving_the_zone_on_the_approach_side_never_advances`.

## Warnings

### WR-01: Moving the active mark (or editing its leg) keeps the rounding latch computed against the old position

**File:** `src/jabuka/nav/course.py:301-309` (`_set`), `:716-719`

**Issue:** `_reset_fsm()` runs only when `(active_idx, mark_id)` changes. `edit_mark(lat, lon)` on the active mark keeps the key, and so does `set_leg` (anchor/side/radius) or a change of the *next* mark (which changes `turn`). In all these cases `_entered`, `_cand_since` and the new `_beyond` latch survive.

This is the committee-mark correction scenario: the mark is entered roughly, the boat sails "past" that point, then the crew corrects the position. `_beyond` is still `True`. At a hairpin, a zone exit with `dot_out > 0` (which is the *approach* side at a hairpin) then advances without the boat ever passing the corrected mark. That is the exact G-4-R02 failure, reintroduced by an edit.

**Fix:** In `_set`, also reset when the active mark's coordinates or the active leg change:

```python
old_geom = (old_mark.lat, old_mark.lon, old_leg.side, old_leg.radius_nm, old_next_id)
...
if new_active != old_active or new_geom != old_geom:
    self._reset_fsm()
```

### WR-02: In background mode, a failed write is invisible on the helm and raises no Diag alert; the ingest no longer reports fsync failures at all

**File:** `src/jabuka/common/atomicio.py:197-237`, `src/jabuka/nav/course.py:294-295`, `src/jabuka/core/main.py:257-259`, `src/jabuka/web/static/diag_logic.js:56`, `src/jabuka/ingest/rawlog.py:207-213`, `src/jabuka/ingest/fastnet_main.py:212-219`

**Issue:** `atomic_write_json` now returns once the temp file is written. Every later failure lands only in `atomicio._errors`: fsync EIO on a dying SD, the `.bak` `link`, the `rename`.

- **Course writes:** `CourseStore._commit` calls `_clear_write_alert()` immediately, so "Écriture du parcours impossible" is never raised for these failures. It is even cleared when one is pending. An auto-advance that never reached disk reverts after the next power cycle, and the helm then routes back to a rounded mark with no warning on the day.
- **Core Diag:** the counter appears only as a raw `bg_write_errors` row in the kv table. `CORE_ERRORS` in `diag_logic.js` does not list it, so no red alert line appears. Before the change, fsync errors raised on the caller and incremented `derived_errors`, `events_errors` and `flush_errors`, which *are* alerted.
- **Ingest:** fsync errors from `RotatingAppendLog` used to raise into `flush_once` and count in `raw_errors`, which Diag shows as "raw log write failed". They now run on the ingest's own durability thread, and that process never sends `background_status()` anywhere. The regression is total: a failing SD is no longer visible from the Fastnet raw log.

**Fix:**

- Add `bg_write_errors` to `CORE_ERRORS`, with an i18n `diag.err.bg_write_errors` string in fr/en/sl.
- Put `background_status()["errors"]` into the ingest heartbeat (`bus_stats()`, e.g. as `bg_write_errors`) and add it to `SOURCE_ERRORS`.
- Raise a nav alert (helm badge) when `bg_write_errors` increases. Alternatively, let `atomic_write_bytes` take an `on_error` callback so that `CourseStore` can raise `WRITE_ALERT` from the worker.

### WR-03: `_fsync_inflight` stays `True` forever if `fsync_fd` raises before the job is queued

**File:** `src/jabuka/ingest/rawlog.py:210-213`, `src/jabuka/common/atomicio.py:133-149`

**Issue:** `_cadence` sets `self._fsync_inflight = True` and then calls `atomicio.fsync_fd(..., on_done=self._fsync_done)`. In background mode, two calls can raise *before* the job exists, and then `on_done` is never called:

- `os.dup(fd)` (EMFILE)
- `_submit()`, through `threading.Thread.start()`, which raises `RuntimeError: can't start new thread` under memory pressure on a 1 GB Pi

The flag is never reset, not even by `_open()` on rotation. From then on every cadence fsync is skipped for the life of the process, which is 36 h for the core's derived log and the Fastnet raw log. Only rotation and close still fsync.

**Fix:**

```python
self._fsync_inflight = True
try:
    atomicio.fsync_fd(fh.fileno(), on_done=self._fsync_done)
except BaseException:
    self._fsync_inflight = False
    raise
```

Also reset `_fsync_inflight` to False in `_open()` (stale-flag safety).

### WR-04: The night text floor erases the only visual difference between live and stale numbers

**File:** `src/jabuka/web/static/app.js:96, 130-136`, `src/jabuka/web/static/app.css:260, 266-269`

**Issue:** Two stale states signal staleness only through `color: var(--dim)`:

- link lost: `#tab-barre.stale .helm-block *`
- stale wind: `#tab-barre.wind-stale #primary ...`

The floor now sets `--fg = max(255k, 110)` and `--dim = max(128k, 110)`, and `storedBrightness()` clamps k to at least 0.4. At k = 0.4 both values are `rgb(110,0,0)`, so stale numbers look exactly like live ones. At k = 0.5 they are 127 vs 110, which is not distinguishable at a glance on a wet tablet. A link-lost helm at night on low brightness therefore shows full-confidence numbers, apart from the text banner. That is the confident-stale-number failure this phase set out to remove.

**Fix:**

- Keep a ratio between the tiers: floor `--fg` higher (e.g. 160) and `--dim` lower (e.g. 70), or floor `--dim` at a fixed fraction of `--fg`.
- Or add a non-colour stale cue, such as an outline, a strike or a `text-decoration`.

Extend `tests/ui/test_night.py` to assert `fg - dim >= N` at the minimum brightness.

### WR-05: Manual wind of unknown age is never "VENT PÉRIMÉ", so the tack cue shows on it indefinitely

**File:** `src/jabuka/web/static/helm_logic.js:167-169, 190-198`, `src/jabuka/web/static/route_logic.js:62-77` (with `src/jabuka/nav/wind.py:380-388`)

**Issue:** `windStale()` is `nav.wind.stale === true`. `WindEngine._manual_age` returns early and never sets `stale` when `manual.t_set_wall is None`, i.e. when the wind was entered before chrony had trusted UTC (after a power cycle at sea, before the GPS fix).

The core's routing gate later goes "ok", so `routeOk` holds and `tackCue` drives the inverted VIREZ / MAUVAIS BORD box from `wrong_tack` and a TWD of unknown age, for the rest of the race. The only hint is the small "MANUEL âge ?" badge.

**Fix:** Treat unknown-age manual wind as not confident for cues:

```js
export function windStale(nav) {
  const w = nav?.wind;
  return w?.stale === true || (w?.source === "MANUEL" && !isNum(w?.manual_age_s));
}
```

A better fix is to also record `t_set_mono` in `ManualWindStore` and age the entry on the monotonic clock within a boot.

### WR-06: Plan B dies after one relay crash; `StartLimitIntervalSec=0` does not prevent it

**File:** `deploy/systemd/jabuka-fastnet-relay.service:17-19, 29`, `deploy/systemd/fastnet2ip.service:24-27, 34`

**Issue:** `fastnet2ip` has `BindsTo=` + `After=jabuka-fastnet-relay`. The relay has `StopWhenUnneeded=yes` and `Restart=on-failure` with the default `RestartMode=normal`. The failure sequence is:

1. With the default restart mode, an auto-restart passes through the failed/inactive state (systemd.service(5): only `RestartMode=direct` skips it). Trixie ships systemd 257, so this applies.
2. When the relay crashes, `BindsTo` therefore stops `fastnet2ip`. That is a stop, not a failure, so its `Restart=on-failure` does not fire.
3. The relay comes back from auto-restart with nothing requiring it, and `StopWhenUnneeded` stops it.

Plan B is then permanently down until someone types `systemctl start fastnet2ip`. The new `StartLimitIntervalSec=0` lines, and their comment, address a crash *loop* and miss this single-crash path.

**Fix:**

- Add `RestartMode=direct` to `jabuka-fastnet-relay.service` (systemd >= 254), so `fastnet2ip` never sees the transient failure.
- Alternatively, replace `BindsTo=` with `Requires=` + `PartOf=`.
- Verify on the Pi with `systemctl start fastnet2ip; kill -9 $(systemctl show -p MainPID --value jabuka-fastnet-relay); sleep 10; systemctl is-active fastnet2ip jabuka-fastnet-relay`.

### WR-07: An exception from `rawlog.close()` at ingest shutdown skips the drain (queued fsyncs dropped) and the socket close

**File:** `src/jabuka/ingest/fastnet_main.py:443-451`

**Issue:** In the `finally`, `rawlog.close()` can raise. `_close_file` → `_flush_pending` re-raises ENOSPC/EIO, and in background mode `fsync_fd` can raise on dup or thread start. When it does, `atomicio.disable_background(20.0)` and `sock.close()` never run.

Any rotation or cadence fsync still queued is then lost when the interpreter kills the daemon worker. The core wraps every close in `close_logs()`; the ingest does not.

**Fix:**

```python
try:
    rawlog.close()
except Exception:
    log.exception("raw log close failed")
finally:
    if not atomicio.disable_background(20.0):
        log.warning("durability thread not drained in 20 s: the SD may be stalled")
    sock.close()
```

## Info

### IN-01: The `polar.py` header says helm and router "agree", but they still differ beyond the last polar angle

**File:** `src/jabuka/nav/polar.py:6-10`

**Issue:** The helm holds the last speed beyond the deepest given TWA. `route/polar_grid.py` uses a 0.9x tail capped at 98 % of the last point's VMG. For a polar that ends before 180 deg (common for ORC-derived files), the helm's downwind target is still 180 deg at full speed while the router's is not, which is the G-4-R04 symptom. The comment states this as deferred, but "helm and router agree" overstates it.

**Fix:** Port `TAIL_FACTOR` / `TAIL_VMG_CAP` into `_interp_curve`'s `x >= xs[-1]` branch, or reword the header.

### IN-02: `_abeam` and `_leg_dots` duplicate the same leg geometry

**File:** `src/jabuka/nav/course.py:616-688`

**Issue:** Both functions recompute the bearings, `to_local` and the turn with identical guards. A future fix to one (e.g. the degenerate-leg threshold) can silently diverge from the other.

**Fix:** Have `_abeam` consume `_leg_dots(...)` plus the side check.

### IN-03: Diag night red ignores the helm brightness slider

**File:** `src/jabuka/web/static/diag.css:15-26`

**Issue:** Diag at night is a fixed `#ff0000` / `#a00000`, while the helm scales red by k (down to 0.4). Switching to Diag on a dimmed tablet is the brightest screen on board.

**Fix:** Propagate `--fg` / `--muted` from `app.js` into the frame, like the class toggle at `app.js:155-160`, or read `jabuka.brightness` in `diag-theme.js`.

### IN-04: A dead `os` import is kept only so that tests can patch the process-wide `os.fsync`

**File:** `src/jabuka/ingest/rawlog.py:34`

**Issue:** `import os  # noqa: F401 - kept: tests patch rawlog.os.fsync`. Patching `rawlog.os.fsync` patches the global `os.fsync`, including the durability thread's. The tests pass by accident of module identity, and the import misleads readers into thinking rawlog calls `os` directly.

**Fix:** Patch `jabuka.common.atomicio.os.fsync` (or `os.fsync`) in the tests and drop the import.

---

_Reviewed: 2026-11-09T12:48:56Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
