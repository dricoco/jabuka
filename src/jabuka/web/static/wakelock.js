// Keep the tablet screen on for the race (HELM-04, RESEARCH Pattern 12, Pitfalls 1 and 12).
//
//   keepAwake() -> Promise<"verrou" | "vidéo" | "aucun">
//     "verrou": Screen Wake Lock held (needs a secure origin: the Chrome flag
//               unsafely-treat-insecure-origin-as-secure = http://10.42.0.1 on the boat)
//     "vidéo":  no Wake Lock API on this origin -> NoSleep's muted looping video (vendored UMD
//               global NoSleep, started from a user gesture)
//     "aucun":  the native request was rejected (NoSleep would only retry native and throw,
//               Pitfall 12) or the video would not play -> the badge is an alert
//   wakeState()        last state ("aucun" until the first gesture)
//   onWakeChange(fn)   fn(state) on every change
// The lock is released by the browser whenever the page is hidden: it is requested again when
// the page becomes visible (visibilitychange), and the state drops to "aucun" if the browser
// releases it on its own (battery saver).

let sentinel = null;
let nosleep = null;
let wanted = false;
let state = "aucun";
const listeners = new Set();

function set(next) {
  if (next !== state) {
    state = next;
    for (const fn of listeners) {
      try {
        fn(state);
      } catch (e) {
        console.error("wake listener", e);
      }
    }
  }
  return state;
}

export const wakeState = () => state;

export function onWakeChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

let pending = null;

async function acquire() {
  const nav = globalThis.navigator;
  if (nav && "wakeLock" in nav && nav.wakeLock) {
    try {
      const s = await nav.wakeLock.request("screen");
      sentinel = s;
      s.addEventListener?.("release", () => {
        if (sentinel === s) {
          sentinel = null;
          set("aucun");
        }
      });
      return set("verrou");
    } catch (e) {
      console.warn("wake lock rejected", e);
      return set("aucun");
    }
  }
  try {
    const NoSleep = globalThis.NoSleep;
    if (typeof NoSleep !== "function") return set("aucun");
    nosleep ??= new NoSleep();
    await nosleep.enable();
    return set("vidéo");
  } catch (e) {
    console.warn("nosleep video failed", e);
    return set("aucun");
  }
}

export function keepAwake() {
  wanted = true;
  if (sentinel !== null && state === "verrou") return Promise.resolve(state);
  pending ??= acquire().finally(() => {
    pending = null;
  });
  return pending;
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (!wanted) return;
    if (document.visibilityState === "hidden") {
      sentinel = null; // the browser releases the lock with the page
      return;
    }
    if (document.visibilityState === "visible") keepAwake();
  });
}
