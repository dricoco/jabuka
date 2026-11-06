// Pure (DOM-free) long-press unlock state machine of the helm lock (HELM-04, RESEARCH Pattern 11,
// T-02-05-03), node-tested from tests/test_lock_logic.py. Timestamps are passed in (ms), so the
// browser drives it with performance.now() and the tests with plain numbers.
//
//   const lp = createLongPress({holdMs: 2000});
//   lp.down(t, {isPrimary, pointerId})  primary pointer: (re)start the press from t;
//                                       non-primary pointer (a second finger, spray): cancel
//   lp.up(t, pointerId)                 end the press of that pointer (another id is ignored)
//   lp.cancel()                         end any press (pointercancel / pointerleave)
//   lp.check(t) -> "locked" | "unlocked"  "unlocked" once one press has lasted holdMs (latched)
//   lp.progress(t) -> 0..1              for the progress ring; 0 when not pressing
//   lp.pressing() -> bool
//   lp.reset()                          back to "locked" (when the helm locks again)

export function createLongPress({ holdMs = 2000 } = {}) {
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
      if (start === null) return;
      if (pointerId !== undefined && pointerId !== id) return;
      if (t - start >= holdMs) unlocked = true;
      clear();
    },
    cancel() {
      clear();
    },
    check(t) {
      if (!unlocked && start !== null && t - start >= holdMs) unlocked = true;
      return unlocked ? "unlocked" : "locked";
    },
    progress(t) {
      if (start === null) return 0;
      return Math.min(1, Math.max(0, (t - start) / holdMs));
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
