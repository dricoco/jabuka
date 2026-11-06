// Barre tab (HELM-02): renders the helm bands from helm_logic.js output only (the server
// computes, the browser formats). Every server string goes through textContent (T-02-05-01).
//
//   top band:    label, the big primary number (>= 20% of the viewport height), the deviation
//                with its LOFER/ABATTRE or steer-left/right hint, "PERTE DONNÉES" when the link
//                is not live (Pitfall 5: frozen numbers must never look live)
//   map buttons: "Nord en haut" / "Cap en haut" and "Centrer" (localStorage jabuka.mapMode,
//                jabuka.centred; overlays.js turns the map on the next nav message)
//   bottom band: countdown, BSP / target, % polar, mark + DTW · TTW, bearing, other-tack heading
//   #badges:     wind source (app.js) + CAP NON FIABLE / COURANT / ANGLES RÉELS + one red badge
//                per nav alert (B&G cross-check, unreadable files, nav computation failure...)
import { helmView } from "./helm_logic.js";

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

const cellOf = (id) => $(id)?.closest(".cell") ?? null;

// Re-arrange the 02-01 band markup: speed and % polar go to the bottom band next to the mark,
// the deviation gets its hint, DTW/TTW join the mark line, map buttons sit between the bands.
function layout(section) {
  const top = $("helm-top");
  const bottom = $("helm-bottom");
  const box = top.querySelector(".primary-box");
  if (!$("helm-stale")) box.append(el("div", { id: "helm-stale", class: "stale-msg", hidden: "" }, "PERTE DONNÉES"));
  const devCell = cellOf("helm-deviation");
  if (devCell && !$("helm-hint")) {
    devCell.classList.add("dev-cell");
    devCell.append(el("span", { id: "helm-hint", class: "hint" }));
  }
  const bottomRow = bottom.querySelector(".secondary");
  const markCell = cellOf("helm-mark");
  for (const id of ["helm-speed", "helm-pct"]) {
    const c = cellOf(id);
    if (c && bottomRow && markCell) bottomRow.insertBefore(c, markCell);
  }
  const speedLabel = cellOf("helm-speed")?.querySelector(".label");
  if (speedLabel) speedLabel.textContent = "BSP / cible";
  for (const id of ["helm-dtw", "helm-ttw"]) cellOf(id)?.remove();
  markCell?.classList.add("mark-cell");

  if (!$("map-ctrls")) {
    const ctrls = el("div", { id: "map-ctrls", class: "map-ctrls" });
    const north = el("button", { type: "button", id: "map-north", class: "ctrl" }, "Nord en haut");
    const course = el("button", { type: "button", id: "map-course", class: "ctrl" }, "Cap en haut");
    const centre = el("button", { type: "button", id: "map-centre", class: "ctrl" }, "Centrer");
    ctrls.append(north, course, centre);
    section.insertBefore(ctrls, bottom);
  }
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
  setText("helm-deviation", v.dev.text, v.dev.cls);
  setText("helm-hint", v.dev.hint, v.dev.cls);
  setText("helm-speed", v.speed);
  setText("helm-pct", v.pct);
  setText("helm-mark", v.markLine);
  setText("helm-btw", v.btw);
  setText("helm-countdown", v.countdown);
  setText("helm-other", v.otherTack);
  if (badge) {
    const keys = new Set(v.flags.map((f) => f.key));
    for (const key of ["cap", "courant", "angles"]) if (!keys.has(key)) badge(`flag-${key}`, null);
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
    msg.textContent = "PERTE DONNÉES";
    msg.hidden = !stale;
  }
}

export function mount(ctx) {
  const section = ctx.section ?? $("tab-barre");
  layout(section);
  renderMapButtons();
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
