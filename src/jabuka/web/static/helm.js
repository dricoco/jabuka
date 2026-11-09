// Barre tab (HELM-02): renders the helm blocks from helm_logic.js output only (the server
// computes, the browser formats). Every server string goes through textContent (T-02-05-01).
//
// Layout (quick 002): #helm-col is the left third of the screen in landscape (the map shows on
// the right two thirds) and one top area in portrait (the map below):
//   block 1 #helm-steer: label, the big primary number with its °M/°T suffix or tack word, the
//                        deviation with its LOFER/ABATTRE or steer-left/right hint, "PERTE DONNÉES"
//                        when the link is not live (Pitfall 5: frozen numbers never look live)
//   block 2 #helm-route: countdown, layline distance, then route.js's #route-band (cost, state,
//                        age, target, bias, one per line) and the ON RESTE button
//   block 3 #helm-rest:  BSP / target, % polar, mark, distance, time, bearing, other-tack heading
//   map buttons:         "Nord en haut" / "Cap en haut" and "Centrer" over the map, bottom right
//                        (localStorage jabuka.mapMode, jabuka.centred; overlays.js turns the map)
//   map padding:         the camera centre sits in the visible part of the map (map.js
//                        setMapPadding), on Barre only, kept up to date on resize/orientation/tab
//   #badges:             wind source (app.js) + PAS DE GPS (red, G-4-R08) / CAP NON FIABLE /
//                        COURANT / ANGLES RÉELS + one red badge per nav alert (B&G cross-check,
//                        unreadable files, nav failure...)
import { helmView } from "./helm_logic.js";
import { t } from "./i18n.js";
import { setMapPadding } from "./map.js";

const $ = (id) => document.getElementById(id);
const MODE_KEY = "jabuka.mapMode";
const CENTRE_KEY = "jabuka.centred";

function load(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: per-session only */
  }
}

export const mapMode = () => (load(MODE_KEY) === "course" ? "course" : "north");
export const mapCentred = () => load(CENTRE_KEY) === "1";

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  if (text !== undefined) e.textContent = text;
  return e;
}

function setText(id, text, cls) {
  const e = $(id);
  if (!e) return;
  if (e.textContent !== text) e.textContent = text;
  if (cls !== undefined) {
    e.classList.remove("good", "warn", "bad");
    if (cls) e.classList.add(cls);
  }
}

// The dynamic pieces of the static markup: the stale message, the deviation hint, the layline
// distance under the countdown and the map buttons (idempotent).
function layout(section) {
  const box = $("helm-steer")?.querySelector(".primary-box");
  if (box && !$("helm-stale")) {
    box.append(el("div", { id: "helm-stale", class: "stale-msg", hidden: "" }, t("helm.stale")));
  }
  const devCell = $("helm-deviation")?.closest(".cell");
  if (devCell && !$("helm-hint")) devCell.append(el("span", { id: "helm-hint", class: "hint" }));
  // distance to the layline under the layline countdown (NAV-02)
  const countdown = $("helm-countdown");
  if (countdown && !$("helm-layline-dist")) {
    countdown.after(el("div", { id: "helm-layline-dist", class: "other layline-dist", hidden: "" }));
  }
  if (!$("map-ctrls")) {
    const ctrls = el("div", { id: "map-ctrls", class: "map-ctrls" });
    const north = el("button", { type: "button", id: "map-north", class: "ctrl" }, t("helm.northUp"));
    const course = el("button", { type: "button", id: "map-course", class: "ctrl" }, t("helm.courseUp"));
    const centre = el("button", { type: "button", id: "map-centre", class: "ctrl" }, t("helm.centre"));
    ctrls.append(north, course, centre);
    section.append(ctrls);
  }
}

// Map padding (quick 002): the part of the map the helm covers, so the camera centre (the boat
// when "Centrer" is on) sits in the middle of the visible map. The top bar always covers the top
// of the map; landscape adds the column on the left, portrait the top area. Other tabs: none.
const LANDSCAPE = "(min-aspect-ratio: 1/1)";
const ZERO = { top: 0, right: 0, bottom: 0, left: 0 };

export function helmPadding(tab) {
  if (tab !== "barre") return ZERO;
  const col = $("helm-col")?.getBoundingClientRect();
  if (!col || !col.width || !col.height) return ZERO;
  const top = Math.round($("topbar")?.getBoundingClientRect().bottom ?? 0);
  if (globalThis.matchMedia?.(LANDSCAPE).matches) return { ...ZERO, top, left: Math.round(col.right) };
  return { ...ZERO, top: Math.max(top, Math.round(col.bottom)) };
}

function trackPadding(ctx) {
  let tab = ctx.latest?.("tab") ?? "barre";
  let queued = false;
  const update = () => {
    queued = false;
    setMapPadding(helmPadding(tab));
  };
  const soon = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(update);
  };
  ctx.bus.addEventListener("tab", (ev) => {
    tab = ev.detail;
    soon();
  });
  window.addEventListener("resize", soon);
  window.addEventListener("orientationchange", soon);
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(soon);
    for (const id of ["helm-col", "topbar"]) if ($(id)) ro.observe($(id));
  }
  soon();
}

function renderMapButtons() {
  const mode = mapMode();
  $("map-north")?.setAttribute("aria-pressed", mode === "north" ? "true" : "false");
  $("map-course")?.setAttribute("aria-pressed", mode === "course" ? "true" : "false");
  $("map-centre")?.setAttribute("aria-pressed", mapCentred() ? "true" : "false");
}

let shownAlerts = 0; // alert badges currently shown

export function render(nav, badge) {
  const v = helmView(nav);
  setText("primary-label", v.primary.label);
  setText("primary", v.primary.main);
  setText("primary-unit", v.primary.unit);
  // a tack word (tribord / starboard / desno) goes on its own line under the number; a °M/°T
  // suffix stays inline, so "888°M" always fits the column
  $("primary-unit")?.classList.toggle("unit-word", (v.primary.unit ?? "").length > 1);
  // G-4-R03: VIREZ / EMPANNEZ takes over the box, inverted, the word sized to the column
  const cue = Boolean(v.primary.cue);
  $("helm-steer")?.querySelector(".primary-box")?.classList.toggle("cue", cue);
  $("primary")?.classList.toggle("cue-word", cue);
  // G-4-R01 / R08: VENT PÉRIMÉ / PAS DE GPS in the alert colour; stale wind dims blocks 1-2
  $("primary-label")?.classList.toggle("alert", Boolean(v.primary.alert));
  $("tab-barre")?.classList.toggle("wind-stale", Boolean(v.windStale));
  setText("helm-deviation", v.dev.text, v.dev.cls);
  setText("helm-hint", v.dev.hint, v.dev.cls);
  setText("helm-speed", v.speed);
  setText("helm-pct", v.pct);
  setText("helm-mark", v.mark);
  setText("helm-dtw", v.dtw);
  setText("helm-ttw", v.ttw);
  setText("helm-btw", v.btw);
  setText("helm-countdown", v.countdown);
  const cd = $("helm-countdown");
  if (cd) {
    // route countdown: "VIREZ" (alert) / "Route mise à jour…" (warn); data-source route|layline
    cd.classList.toggle("alert", v.countdownCls === "alert");
    cd.classList.toggle("warn", v.countdownCls === "warn");
    cd.dataset.source = v.countdownSource;
  }
  const dist = $("helm-layline-dist");
  if (dist) {
    setText("helm-layline-dist", v.laylineDist);
    dist.hidden = !v.laylineDist;
  }
  setText("helm-other", v.otherTack);
  if (badge) {
    const keys = new Set(v.flags.map((f) => f.key));
    for (const key of ["gps", "cap", "courant", "angles"]) if (!keys.has(key)) badge(`flag-${key}`, null);
    for (const f of v.flags) badge(`flag-${f.key}`, f.text, f.cls);
    // nav alerts (CR-01): one red badge each in the top bar, so they show on every tab
    const n = Math.max(v.alerts.length, shownAlerts);
    for (let i = 0; i < n; i++) badge(`alert-${i}`, i < v.alerts.length ? v.alerts[i] : null, "bad");
    shownAlerts = v.alerts.length;
  }
  return v;
}

function setStale(stale) {
  const sec = $("tab-barre");
  sec?.classList.toggle("stale", stale);
  const msg = $("helm-stale");
  if (msg) {
    msg.textContent = t("helm.stale");
    msg.hidden = !stale;
  }
}

export function mount(ctx) {
  const section = ctx.section ?? $("tab-barre");
  layout(section);
  renderMapButtons();
  trackPadding(ctx);
  const changed = () => {
    renderMapButtons();
    ctx.bus.dispatchEvent(new CustomEvent("mapmode", { detail: { mode: mapMode(), centred: mapCentred() } }));
  };
  $("map-north").addEventListener("click", () => {
    store(MODE_KEY, "north");
    changed();
  });
  $("map-course").addEventListener("click", () => {
    store(MODE_KEY, "course");
    changed();
  });
  $("map-centre").addEventListener("click", () => {
    store(CENTRE_KEY, mapCentred() ? "0" : "1");
    changed();
  });

  ctx.bus.addEventListener("nav", (ev) => {
    render(ev.detail, ctx.badge);
    setStale(false);
  });
  ctx.bus.addEventListener("link", (ev) => setStale(ev.detail !== "live"));
  const last = ctx.latest?.("nav");
  if (last) render(last, ctx.badge);
  const link = ctx.latest?.("link");
  setStale(link ? link !== "live" : document.body.classList.contains("link-stale"));
}
