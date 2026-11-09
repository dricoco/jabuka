// Lock mode (HELM-04, RESEARCH Pattern 11, T-02-05-03): spray, rain and stray fingers must not
// change anything on the helm.
//
// A 64 px padlock in the top bar locks. #lock-overlay then covers the whole screen above
// everything (transparent: the numbers keep updating underneath) and swallows every pointer,
// touch, wheel, click and context-menu event. Its only live spot is its own 64 px padlock, which
// unlocks when the primary pointer is lifted after a 2-4 s press (lock_logic.js, G-4-R07). A
// longer press, or one that never lifts (a water drop, a palm), does nothing; a second finger or a
// non-primary pointer never unlocks. A progress ring fills over 2 s and the padlock turns inverted
// (.ready) while the release window is open. While locked the map's own interactions are disabled
// too. The state persists per tablet in localStorage "jabuka.locked".
import { t } from "./i18n.js";
import { createLongPress } from "./lock_logic.js";

const KEY = "jabuka.locked";
const HOLD_MS = 2000;
const MAX_MS = 4000; // a press longer than this is void: lifting after it does nothing
const SVG = "http://www.w3.org/2000/svg";
const RING_R = 28;
const RING_LEN = 2 * Math.PI * RING_R;
const MAP_HANDLERS = [
  "dragPan",
  "scrollZoom",
  "boxZoom",
  "dragRotate",
  "keyboard",
  "doubleClickZoom",
  "touchZoomRotate",
  "touchPitch",
];

const $ = (id) => document.getElementById(id);

function load() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function store(locked) {
  try {
    localStorage.setItem(KEY, locked ? "1" : "0");
  } catch {
    /* private mode: per-session only */
  }
}

function svg(tag, attrs) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}

// Padlock drawn with currentColor (an emoji would bring its own colours, Pitfall 4).
function padlock(open, ring) {
  const s = svg("svg", { viewBox: "0 0 64 64", width: 64, height: 64, "aria-hidden": "true" });
  if (ring) {
    s.append(svg("circle", { cx: 32, cy: 32, r: RING_R, fill: "none", stroke: "currentColor", "stroke-width": 2, opacity: 0.35 }));
    s.append(
      svg("circle", {
        class: "lock-ring",
        cx: 32,
        cy: 32,
        r: RING_R,
        fill: "none",
        stroke: "currentColor",
        "stroke-width": 5,
        "stroke-dasharray": RING_LEN.toFixed(2),
        "stroke-dashoffset": RING_LEN.toFixed(2),
        transform: "rotate(-90 32 32)",
      }),
    );
  }
  const shackle = open ? "M24 29 V22 a8 8 0 0 1 16 0" : "M24 29 V23 a8 8 0 0 1 16 0 V29";
  s.append(svg("path", { d: shackle, fill: "none", stroke: "currentColor", "stroke-width": 4, "stroke-linecap": "round" }));
  s.append(svg("rect", { x: 19, y: 29, width: 26, height: 19, rx: 3, fill: "currentColor" }));
  return s;
}

let mapQueue = Promise.resolve();

function toggleHandlers(map, enabled) {
  for (const name of MAP_HANDLERS) {
    const h = map[name];
    if (h && typeof h.enable === "function") enabled ? h.enable() : h.disable();
  }
}

function setMapInteractions(enabled) {
  const ready = globalThis.jabuka?.map;
  if (ready) toggleHandlers(ready, enabled); // map already up: at once, no async gap
  mapQueue = mapQueue.then(() => applyMap(enabled));
  return mapQueue;
}

async function applyMap(enabled) {
  try {
    const m = await import("./map.js");
    // idempotent: the same map app.js loads (also when the lock is restored before it is ready)
    toggleHandlers(await m.ensureMap(document.getElementById("map")), enabled);
  } catch {
    /* no map on this tablet: nothing to disable */
  }
}

export function mount(ctx) {
  const overlay = $("lock-overlay");
  if (!overlay) return;
  const lp = createLongPress({ holdMs: HOLD_MS, maxMs: MAX_MS });
  let locked = false;
  let raf = 0;

  // top-bar padlock (locks)
  let box = $("top-ctrls");
  if (!box) {
    box = document.createElement("div");
    box.id = "top-ctrls";
    $("topbar").append(box);
  }
  const lockBtn = document.createElement("button");
  lockBtn.type = "button";
  lockBtn.id = "lock-btn";
  lockBtn.className = "ctrl lock-btn";
  lockBtn.setAttribute("aria-label", t("lock.lockAria"));
  lockBtn.append(padlock(true, false));
  box.append(lockBtn);

  // overlay: padlock with progress ring (unlocks) + hint
  const unlockBtn = document.createElement("div");
  unlockBtn.id = "unlock-btn";
  unlockBtn.className = "unlock-btn";
  unlockBtn.setAttribute("role", "button");
  unlockBtn.setAttribute("aria-label", t("lock.unlockAria"));
  unlockBtn.append(padlock(false, true));
  const hint = document.createElement("div");
  hint.className = "lock-hint";
  hint.textContent = t("lock.hint");
  overlay.replaceChildren(unlockBtn, hint);
  const ring = unlockBtn.querySelector(".lock-ring");

  const drawRing = (p) => ring?.setAttribute("stroke-dashoffset", (RING_LEN * (1 - p)).toFixed(2));
  const setReady = (on) => unlockBtn.classList.toggle("ready", on);
  const idle = () => {
    drawRing(0);
    setReady(false);
  };

  function apply(next) {
    locked = next;
    // a focused input would still take keys from a Bluetooth keyboard or the IME (IN-08)
    if (locked) document.activeElement?.blur?.();
    overlay.hidden = !locked;
    document.body.classList.toggle("locked", locked);
    store(locked);
    lp.reset();
    idle();
    setMapInteractions(!locked);
    ctx.bus?.dispatchEvent(new CustomEvent("lock", { detail: locked }));
  }

  // feedback only: a hold never unlocks, the pointerup handler does (G-4-R07)
  function tick() {
    raf = 0;
    const now = performance.now();
    lp.check(now); // voids a press held past MAX_MS
    if (!locked || !lp.pressing()) {
      idle();
      return;
    }
    drawRing(lp.progress(now));
    setReady(lp.ready(now));
    raf = requestAnimationFrame(tick);
  }

  const swallow = (ev) => {
    if (ev.cancelable) ev.preventDefault();
    ev.stopPropagation();
  };

  // every event on the overlay is swallowed; pointer events on the padlock also drive the press
  for (const type of ["pointermove", "click", "dblclick", "contextmenu", "mousedown", "mouseup", "touchmove", "touchend", "touchstart"]) {
    overlay.addEventListener(type, swallow, { passive: false });
  }
  overlay.addEventListener("wheel", swallow, { passive: false });
  overlay.addEventListener(
    "pointerdown",
    (ev) => {
      swallow(ev);
      if (!locked) return;
      if (unlockBtn.contains(ev.target)) {
        if (lp.down(performance.now(), { isPrimary: ev.isPrimary, pointerId: ev.pointerId })) {
          if (!raf) raf = requestAnimationFrame(tick);
        } else {
          idle();
        }
      } else if (lp.pressing()) {
        lp.cancel(); // another finger elsewhere: not a deliberate press
        idle();
      }
    },
    { passive: false },
  );
  const release = (ev) => {
    swallow(ev);
    if (!locked) return;
    if (lp.up(performance.now(), ev.pointerId)) {
      apply(false);
      return;
    }
    if (!lp.pressing()) idle(); // another pointer's lift leaves the press running
  };
  overlay.addEventListener("pointerup", release, { passive: false });
  overlay.addEventListener(
    "pointercancel",
    (ev) => {
      swallow(ev);
      lp.cancel();
      idle();
    },
    { passive: false },
  );
  unlockBtn.addEventListener("pointerleave", () => {
    lp.cancel();
    idle();
  });
  // keyboard (a Bluetooth keyboard, a stuck key) does nothing while locked
  document.addEventListener(
    "keydown",
    (ev) => {
      if (locked) swallow(ev);
    },
    { capture: true },
  );

  lockBtn.addEventListener("click", () => apply(true));
  apply(load());
}
