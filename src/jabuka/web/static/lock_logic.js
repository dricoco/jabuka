// Pure (DOM-free) long-press unlock state machine of the helm lock (HELM-04, RESEARCH Pattern 11,
// T-02-05-03, G-4-R07), node-tested from tests/test_lock_logic.py. Timestamps are passed in (ms),
// so the browser drives it with performance.now() and the tests with plain numbers.
//
// Only a release unlocks: a water drop or a palm resting on the padlock is a single primary
// pointer that never lifts, so a time-based unlock would let it through (review C/R07).
//
//   const lp = createLongPress({holdMs: 2000, maxMs: 4000});
//   lp.down(t, {isPrimary, pointerId})  primary pointer: (re)start the press from t;
//                                       non-primary pointer (a second finger, spray): cancel
//   lp.up(t, pointerId) -> bool         end the press of that pointer (another id is ignored and
//                                       returns false); true when this release unlocks, i.e. the
//                                       press lasted holdMs..maxMs (inclusive); latches "unlocked"
//   lp.cancel()                         end any press (pointercancel / pointerleave)
//   lp.check(t) -> "locked" | "unlocked"  the latch only: never unlocks during a hold; a press
//                                       longer than maxMs is void (cleared) here
//   lp.progress(t) -> 0..1              for the progress ring; 0 when not pressing or void
//   lp.ready(t) -> bool                 "lift now": pressing and holdMs <= t - start <= maxMs
//   lp.pressing() -> bool
//   lp.reset()                          back to "locked" (when the helm locks again)

export function createLongPress({ holdMs = 2000, maxMs = 4000 } = {}) {
  let start = null;
  let id = null;
  let unlocked = false;

  const clear = () => {
    start = null;
    id = null;
  };

  return {
    down(t, { isPrimary = true, pointerId = 1 } = {}) {
      if (!isPrimary) {
        clear(); // multi-finger contact is never a deliberate unlock
        return false;
      }
      start = t;
      id = pointerId;
      return true;
    },
    up(t, pointerId) {
      if (start === null) return false;
      if (pointerId !== undefined && pointerId !== id) return false;
      const d = t - start;
      clear();
      if (d >= holdMs && d <= maxMs) {
        unlocked = true;
        return true;
      }
      return false;
    },
    cancel() {
      clear();
    },
    check(t) {
      if (start !== null && t - start > maxMs) clear(); // too long: void, the lift does nothing
      return unlocked ? "unlocked" : "locked";
    },
    progress(t) {
      if (start === null || t - start > maxMs) return 0;
      return Math.min(1, Math.max(0, (t - start) / holdMs));
    },
    ready(t) {
      return start !== null && t - start >= holdMs && t - start <= maxMs;
    },
    pressing() {
      return start !== null;
    },
    reset() {
      clear();
      unlocked = false;
    },
  };
}
