---
phase: 04-race-readiness-hardening-commissioning
reviewed: 2026-11-09T14:38:37Z
depth: standard
scope: incremental (bfed642..HEAD 3e5f9ab, gap-closure plan 04-13; previous review CR-01, WR-01, WR-02 ingest part, WR-03, WR-06, WR-07)
files_reviewed: 8
files_reviewed_list:
  - deploy/systemd/jabuka-fastnet-relay.service
  - src/jabuka/ingest/fastnet_main.py
  - src/jabuka/ingest/rawlog.py
  - src/jabuka/nav/course.py
  - tests/bus/test_ingest_resilience.py
  - tests/deploy/test_units.py
  - tests/nav/test_course.py
  - tests/test_background_durability.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 4: Code Review Report (incremental, 04-13)

**Reviewed:** 2026-11-09T14:38:37Z
**Depth:** standard (diff bfed642..HEAD plus the code it calls: `atomicio`, `fastnet_relay`, `carte.js` mark edits, the fastnet2ip 3.3.1 wheel)
**Files Reviewed:** 8
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

Plan 04-13 closes most of the previous review. The ingest durability tail is correct:

- **WR-03:** the cadence flag is cleared on a pre-queue raise.
- **WR-07:** a raw-log close error no longer skips the drain or the socket close.
- **WR-02 (ingest part):** the ingest heartbeat now exports `bg_write_errors`.

The relay unit's `RestartMode=direct` works. I re-checked it on the laptop's user-scope systemd 260 with a stand-in that behaves like the real fastnet2ip 3.3.1, which **dies** on pty EIO rather than surviving. The chain recovers: the relay restarts at about 2 s and Plan B at about 5 s, and StopWhenUnneeded does not stop the relay. A plain fastnet2ip crash also recovers without stopping the relay.

The rounding change fixes the original CR-01 tracks. I traced the state machine against the probe tracks in a scratch script, running the real `CourseStore` with `.venv` and `-I`. Three defects remain, one of them a blocker:

1. **Blocker (CR-01):** `_fsm_geometry` throws away evidence that never depended on what was edited. Nudging the next mark by about 1 m, inserting a new next mark (the default `add_mark` position) or changing the side, while the boat is still inside the zone after a tight rounding, leaves the course stuck on the mark it just rounded, even when the mark was entered exactly. Residual R6 does not cover this. R6 says "after the zone exit", and this happens before it.
2. **G-4-R02 reopened after Annuler (WR-01):** at normal marks, the CR-02 path now forces `_beyond = True`. So after any Annuler, the next zone exit in **any** direction advances, including a tack away on the approach side.
3. **One-sample latch outside the zone (WR-02):** `_beyond` latches on a single fix, anywhere within 2 nm after the first entry. Outside the zone that one fix holds the candidate for the full 10 s, so a boat approaching along the abeam line (a layline) can advance before it reaches the mark.

### Previous findings: status

| Previous finding | Status after 04-13 |
|---|---|
| CR-01: a non-hairpin zone exit on the approach side of the abeam line never advances | **Closed** for the reported tracks (latch, `dot_in > 0`, `dot_out > 0 and _near`), with residuals R1-R7 accepted. A new stuck path is introduced by the WR-01 fix; see CR-01 below |
| WR-01: moving the active mark keeps the old latch | **Closed**, but too broad: it also resets on next-mark and side edits; see CR-01 below |
| WR-02: background write failures are invisible | **Partially closed.** The ingest heartbeat exports `bg_write_errors`. Still open, deferred by plan 04-13: the Diag `CORE_ERRORS`/`SOURCE_ERRORS` alert line and a helm/course write alert for background failures |
| WR-03: `_fsync_inflight` stuck after a pre-queue raise | **Closed** (`rawlog.py:210-218`, the test covers dup and submit). The defensive reset in `_open()` was not done; that is acceptable, since a queued job always runs `on_done` |
| WR-04: the night floor erases dim = stale | Open (advisory, deferred) |
| WR-05: MANUEL wind of unknown age is never stale | Open (advisory, deferred) |
| WR-06: Plan B dies after one relay crash | **Closed.** Verified here on user-scope systemd 260, including the real fastnet2ip EIO exit. The test does not model that exit; see WR-03 below. The Pi (system scope, 257) is still a human item |
| WR-07: a raw-log close error skips the drain | **Closed** (`fastnet_main.py:451-460`) |
| IN-01 .. IN-04 | Open (info, deferred) |

## Critical Issues

### CR-01: An edit of the next mark (or of the side) while the boat is in the zone after a tight rounding leaves the course stuck on the mark just rounded, outside residual R6

**File:** `src/jabuka/nav/course.py:612-631` (`_fsm_geometry`), `:767-770` (the reset), `:444` (the `add_mark` default `insert_at = active_idx + 1`)

**Issue:** The state-machine key includes `leg.side` and `pos(idx + 1)`. None of the stored evidence depends on either of them:

- `_beyond` uses only `dot_in`, which comes from the previous mark and the active mark (`_leg_dots`, lines 693-698).
- `_near` and `_entered` use only the active mark and `leg.radius_nm`.
- The next mark and the side are read fresh on every tick, by `_past_mark` (turn, `dot_out`) and by `_abeam`.

Any change to them still runs a full `_reset_fsm()`. Take a tight rounding (turn 75-89 deg, the boat rounding at 0.005 nm and then beating out at turn + 45 deg). The boat spends under 10 s past the abeam line, so the only evidence left is the latch.

If the edit comes while the boat is still inside the zone but more than radius + `MARK_TOL_NM` away, the evidence is gone:

- the boat is already at `dot_in < 0`, so the latch never sets again;
- `_near` never sets again;
- the zone exit is rejected;
- at 2 nm the gate clears `_entered`.

The course stays on the rounded mark for good, and the router steers back to it.

Reproduction (real `CourseStore`, the `_committee`/`_round` geometry from `tests/nav/test_course.py`, mark placed **exactly** on the buoy, edit at 0.2 nm out):

```
turn 75, tack 45:  no edit -> advanced | rename next -> advanced | next mark moved 0.0005 nm -> STUCK | set_leg(side="port") -> STUCK
turn 89, tack 45:  no edit -> advanced | rename next -> advanced | next mark moved 0.0005 nm -> STUCK | set_leg(side="port") -> STUCK
turn 75, tack 45:  add_mark("New", ...) with the default position (new next mark, same turn) -> STUCK
```

This is the most natural in-race edit. The committee changes the next leg, and the crew adds the new mark at the default position "right after the active mark" just after rounding. A "Déplacer ici" re-save also counts: `round6` of a reformatted coordinate makes a few-metre move.

Residual R6 in 04-13-SUMMARY covers edits "after the zone exit and before the 10 s debounce ends". This window is before the zone exit, so R6 does not cover it. The `_fsm_geometry` docstring says the latch and near evidence "were measured against the old incoming and outgoing legs". That is wrong for the outgoing leg.

The crew fallback (« Suiv. ») exists. But the reset is avoidable, and this is the same "stuck on the mark rounded" class as the previous CR-01.

**Fix:** Key the evidence only on what it was measured against. When only the outgoing geometry changes, restart just the debounce:

```python
def _fsm_geometry(self, idx: int) -> tuple:
    """Evidence (entry, latch, near) is measured against the incoming leg, the active mark and
    the leg radius only."""
    c = self.course
    leg = c.seq[idx]
    ...
    return (idx, leg.mark_id, leg.radius_nm, pos(idx - 1), pos(idx))

def _fsm_outgoing(self, idx: int) -> tuple:
    c = self.course
    ...
    return (c.seq[idx].side, pos(idx + 1))

# in _fsm:
key = self._fsm_geometry(idx)
if key != self._fsm_key:
    self._reset_fsm()
    self._fsm_key = key
    self._fsm_out = self._fsm_outgoing(idx)
elif (out := self._fsm_outgoing(idx)) != self._fsm_out:
    self._fsm_out = out
    self._cand_since = None  # the candidate was judged with the old outgoing leg
```

Keeping `_beyond` when the mark becomes a hairpin through a next-mark edit adds nothing that the unedited hairpin rule does not already allow. The latch is the same "past along the incoming leg" quantity either way.

Add a regression test next to `test_tight_rounding_then_a_beat_out_advances`: a 75 deg turn with a 45 deg tack, with `add_mark` at the default position or the next mark nudged at 0.2 nm out, must advance exactly once. Keep the moved-active, moved-previous and radius-shrink tests as they are. Update the `_fsm_geometry` docstring and R6.

## Warnings

### WR-01: After Annuler at a normal mark, a zone exit in any direction advances, including an approach-side retreat (G-4-R02 reopened)

**File:** `src/jabuka/nav/course.py:788-794` (CR-02 path) with `:733-738` (`_past_mark`)

**Issue:** Leaving the suppressed zone sets `self._beyond = True`. Since 04-13 the normal-turn rule starts with `self._beyond or ...`, so the exit counts unconditionally. Before 04-13 it still needed `dot_in > 0` at normal marks. The comment at 790-793 says this is intended. But Annuler is tapped exactly when the crew thinks the mark is *not* rounded yet. The track that follows is the rest of the approach, and on a beat that often includes a tack out of a 0.25 nm zone.

Reproduction (real `CourseStore`):

- **Plić, Course A.** An advance, then Annuler in the zone, then the boat back on the approach side, then a retreat to 341 deg / 0.8 nm (the G-4-R02 NNW track). Result: **advanced** (2 `course_advance` events).
- **Committee mark, turn 60.** The R1 false advance, then Annuler, then a re-entry at 0.25 nm on the approach side, then straight back down the approach to 0.6 nm. Result: **advanced a second time**.

This false-advance path is not among R1-R7. It loops: the crew taps Annuler again, and the next approach-side exit fires again.

**Fix:** At a normal mark, the stay inside the suppressed zone should stand in for "came near", not for the latch. Then the exit needs `dot_in > 0 or dot_out > 0`, which both G-4-R02 retreats fail (`dot_in < 0` and `dot_out < 0`). The hairpin path is unchanged:

```python
if left_this_zone:
    self._entered = True
    self._near = True          # normal mark: exit past the mark along either leg
    dots = self._leg_dots(lat, lon, idx, mark)
    if dots is not None and dots[2] is not None and abs(dots[2]) > HAIRPIN_DEG:
        self._beyond = True    # hairpin: the far-side stand-in, as before
```

A better fix keeps `_leg_dots` running on the suppressed in-zone ticks, so the real latch and near evidence are collected instead of assumed. Add the two tracks above as regression tests.

### WR-02: A single fix past the abeam line, anywhere within 2 nm after the first entry, latches `_beyond`; outside the zone that one fix advances the course 10 s later

**File:** `src/jabuka/nav/course.py:811-814`

**Issue:** The latch is set on any tick with `dot_in > 0` once `_entered` is true. It is gated only by the 2 nm gate, not by the zone, and it has no hysteresis.

Outside the zone, `d > zone and self._past_mark(dots)` is then true on every following tick, and `_cand_since` keeps running. So one sample just past the abeam line holds the candidate, and the course advances 10 s later wherever the boat goes, provided it stays outside the zone and within 2 nm.

Before 04-13, a normal mark needed 10 consecutive seconds of `dot_in > 0`. When the rhumb line is about 45 deg off the wind, one layline *is* the abeam line. A boat that dipped into the zone earlier and then comes back up that layline has GPS and steering noise of a few metres around `dot_in = 0`.

Reproduction at Plić:

1. entered at 0.6 nm, then at 0.28 nm 5 deg short of abeam;
2. **one** fix 1 deg past abeam (about 9 m past the line, 0.28 nm out, just outside the 0.25 nm zone);
3. back short of abeam, then a retreat on the approach side.

Result: **advanced**.

**Fix:** Latch only inside the zone, where tight roundings happen. Optionally require a small margin:

```python
if d <= zone and dots is not None and dots[0] > 0.0:
    self._beyond = True
```

Outside the zone, `_abeam` (10 s continuous) and `dot_in > 0` now still apply. The CR-01 tracks are unaffected (the latch is set during the arc, inside the zone). Add the repro as a regression test.

### WR-03: The single-crash Plan B test asserts a fastnet2ip behaviour that does not happen, so the real recovery chain is untested

**File:** `tests/deploy/test_units.py:183-252` (assertion at `:246`); Human Items in 04-13-SUMMARY

**Issue:** The Plan B stand-in is `sleep infinity`, and the test asserts that Plan B keeps the **same MainPID** after the relay's kill -9. The real fastnet2ip 3.3.1, from the wheel in `deploy/wheelhouse`, behaves differently:

- `run_loop` does `select` followed by `Serial.read()` on the pty slave and catches only `KeyboardInterrupt`.
- When the relay dies, the pty master closes. The slave read then raises `SerialException` (EIO), and fastnet2ip exits with status 1.
- Its restart (`Restart=on-failure`, `RestartSec=5`) briefly puts it in failed. That is the same transient that WR-06 was about, and it is on the side of the unit that has `BindsTo=`. It re-opens `/run/jabuka-relay/fastnet-ro`, which now points at the new pty.

I ran this chain on user-scope systemd 260. The stand-in exits 1 when the relay's PID dies. Result: the relay is active (NRestarts 1) at about 2 s, Plan B is active (NRestarts 1) at about 5 s, and the relay is not stopped by StopWhenUnneeded.

So the fix works, but the committed test proves a different scenario. The Pi human check (`sleep 10; systemctl is-active ...`) does not show data flow either. A fastnet2ip that is active but deaf would pass both.

**Fix:**

- Make the Plan B stand-in exit 1 when the relay's MainPID disappears, e.g.:

  ```
  ExecStart=/bin/sh -c 'p=$(systemctl --user show -p MainPID --value R); while kill -0 $p; do sleep 0.2; done; exit 1'
  ```

- Assert that both units end `active`, with Plan B `NRestarts >= 1`.
- Drop the same-MainPID assertion.
- In the Pi human item, also check the NMEA output after the kill, e.g. `timeout 15 nc -ul 2002 | head -3`, with the bus or a replay connected, and `systemctl show -p NRestarts fastnet2ip`.

## Info

### IN-01: The ingest's crash-path exit drain can outlast the watchdog

**File:** `src/jabuka/ingest/fastnet_main.py:445-460`

**Issue:** When a supervised task dies, `done` is 1 and no `STOPPING=1` is sent, so the systemd watchdog (`WatchdogSec=30`, pinged every 15 s) is still armed. The watchdog task is cancelled, and `disable_background(20.0)` then blocks the loop for up to 20 s. On a stalled SD the process can be SIGABRTed mid-drain, a core-dumped watchdog kill instead of a clean exit 1. The outcome is the same (restart), but it is noisier.

**Fix:** Call `sdnotify.notify("STOPPING=1")` at the top of the `finally` block, or send `EXTEND_TIMEOUT_USEC` / a last `WATCHDOG=1` before the drain.

### IN-02: A persistent pre-queue fsync failure logs at ERROR every second

**File:** `src/jabuka/ingest/rawlog.py:210-219`, `src/jabuka/ingest/fastnet_main.py:219-223`

**Issue:** After the WR-03 fix, a lasting `EMFILE` or thread-start failure re-raises on every 1 s `flush_once`. `_last_fsync` is not advanced, so this repeats each second, adding one `raw_errors` and one `log.error` line per second for as long as it lasts. journald rate-limits it, but it buries other ingest logs.

**Fix:** Optional: on a pre-queue failure, set `self._last_fsync = now` so the retry follows the normal `fsync_s` cadence. Or log the first failure at ERROR and the repeats at DEBUG.

---

_Reviewed: 2026-11-09T14:38:37Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
