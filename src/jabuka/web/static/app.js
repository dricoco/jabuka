// App shell: tabs, one WebSocket with a link watchdog, the module bus, version-driven refetch of
// the course and settings, and the dynamically imported feature modules.
//
// Module contract: each module exports mount(ctx), ctx = {section, api, bus, badge, latest}.
//   bus events (CustomEvent detail): "nav" (nav message), "course" (GET /api/course JSON),
//   "settings" ({version, settings}), "tab" (tab name), "link" ("live" | "stale" | "reconnect").
//   api: {get, post, put, patch, del} -> parsed JSON; throws ApiError {status, body}.
//   badge(key, text | null, cls): show/clear a badge in #badges.
//   latest(type): the last detail emitted for a bus event type (a module mounted after the first
//   "course"/"settings"/"nav" event starts from it), or null.
// A module that fails to load or mount never stops the helm numbers.
//
// Night theme (HELM-03, 02-05): the toggle in #top-ctrls sets body.theme-night, persists
// localStorage "jabuka.theme" and re-styles the map with map.js setTheme (overlays survive);
// "jabuka.brightness" (0.4-1.0) scales the red of every night colour.

import { linkState } from "./diag_logic.js";
import { sourceBadge } from "./helm_logic.js";

const $ = (id) => document.getElementById(id);
export const bus = new EventTarget();
const lastEvent = new Map();
const emit = (type, detail) => {
  lastEvent.set(type, detail);
  bus.dispatchEvent(new CustomEvent(type, { detail }));
};
export const latest = (type) => lastEvent.get(type) ?? null;

// -- REST helper --------------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function request(method, url, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, body) => request("POST", url, body ?? {}),
  put: (url, body) => request("PUT", url, body),
  patch: (url, body) => request("PATCH", url, body),
  del: (url) => request("DELETE", url),
};

// -- badges -------------------------------------------------------------------------------------
const badges = new Map();
export function badge(key, text, cls = "warn") {
  const root = $("badges");
  let el = badges.get(key);
  if (text === null || text === undefined || text === "") {
    if (el) {
      el.remove();
      badges.delete(key);
    }
    return;
  }
  if (!el) {
    el = document.createElement("span");
    el.dataset.badge = key;
    badges.set(key, el);
    root.append(el);
  }
  el.textContent = text;
  el.className = `badge ${cls}`;
}

// -- night theme (HELM-03) ----------------------------------------------------------------------
const THEME_KEY = "jabuka.theme";
const BRIGHT_KEY = "jabuka.brightness";

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: per-session only */
  }
}

function load(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export const storedTheme = () => (load(THEME_KEY) === "night" ? "night" : "day");

export function storedBrightness() {
  const v = Number.parseFloat(load(BRIGHT_KEY));
  return Number.isFinite(v) ? Math.min(1, Math.max(0.4, v)) : 1;
}

// Every night colour is a pure red channel scaled by the brightness (no green/blue light).
function applyBrightness() {
  const s = document.body.style;
  const names = ["--fg", "--dim", "--line", "--good", "--warn", "--bad", "--accent", "--map-k"];
  if (!document.body.classList.contains("theme-night")) {
    for (const n of names) s.removeProperty(n);
    return;
  }
  const k = storedBrightness();
  const red = (v) => `rgb(${Math.round(v * k)}, 0, 0)`;
  s.setProperty("--fg", red(255));
  s.setProperty("--good", red(255));
  s.setProperty("--bad", red(255));
  s.setProperty("--accent", red(255));
  s.setProperty("--warn", red(192));
  s.setProperty("--dim", red(128));
  s.setProperty("--line", red(64));
  s.setProperty("--map-k", String(k));
}

function applyThemeClass(theme) {
  const night = theme === "night";
  document.body.classList.toggle("theme-night", night);
  document.body.classList.toggle("theme-day", !night);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", night ? "#000000" : "#ffffff");
  const btn = $("night-toggle");
  if (btn) {
    btn.textContent = night ? "Jour" : "☾ Nuit";
    btn.setAttribute("aria-pressed", night ? "true" : "false");
  }
  const slider = $("night-brightness");
  if (slider) slider.hidden = !night;
  applyBrightness();
}

export async function setAppTheme(theme) {
  const t = theme === "night" ? "night" : "day";
  store(THEME_KEY, t);
  applyThemeClass(t);
  emit("theme", t);
  try {
    const m = await import("./map.js");
    await m.setTheme(t);
  } catch (e) {
    console.warn("map theme", e);
  }
}

function buildTopControls() {
  let box = $("top-ctrls");
  if (!box) {
    box = document.createElement("div");
    box.id = "top-ctrls";
    $("topbar").append(box);
  }
  const slider = document.createElement("input");
  slider.type = "range";
  slider.id = "night-brightness";
  slider.min = "40";
  slider.max = "100";
  slider.step = "10";
  slider.value = String(Math.round(storedBrightness() * 100));
  slider.setAttribute("aria-label", "Luminosité nuit");
  slider.addEventListener("input", () => {
    store(BRIGHT_KEY, String(Number(slider.value) / 100));
    applyBrightness();
  });
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "night-toggle";
  btn.className = "ctrl";
  btn.setAttribute("aria-label", "Mode nuit");
  btn.addEventListener("click", () => {
    const night = !document.body.classList.contains("theme-night");
    setAppTheme(night ? "night" : "day");
    // fullscreen hides the Android status bar (white icons) at night (Pitfall 4)
    if (night && document.fullscreenEnabled && !document.fullscreenElement) {
      document.documentElement.requestFullscreen?.({ navigationUI: "hide" })?.catch?.(() => {});
    }
  });
  box.append(slider, btn);
}

// main/banner follow the real top bar height (the badges may wrap on a portrait tablet)
function trackTopbar() {
  const bar = $("topbar");
  const set = () => document.documentElement.style.setProperty("--topbar-h", `${bar.offsetHeight}px`);
  set();
  if (typeof ResizeObserver === "function") new ResizeObserver(set).observe(bar);
}

// -- tabs ---------------------------------------------------------------------------------------
let currentTab = "barre";
function showTab(name) {
  currentTab = name;
  for (const btn of document.querySelectorAll("#topbar [data-tab]")) {
    btn.classList.toggle("active", btn.dataset.tab === name);
  }
  for (const sec of document.querySelectorAll("main > .tab")) {
    const on = sec.id === `tab-${name}`;
    sec.hidden = !on;
    sec.classList.toggle("active", on);
  }
  if (name === "diag") {
    const frame = $("diag-frame");
    if (frame && !frame.getAttribute("src")) frame.setAttribute("src", "/diag.html");
  }
  emit("tab", name);
}

// -- course / settings refetch (Pitfall 10: versions in every nav message) ----------------------
const fetched = { course: null, settings: null };
const inflight = { course: false, settings: false };

async function refetch(kind) {
  if (inflight[kind]) return;
  inflight[kind] = true;
  try {
    const data = await api.get(kind === "course" ? "/api/course" : "/api/settings");
    fetched[kind] = data.version;
    emit(kind, data);
  } catch (e) {
    console.error(`refetch ${kind}`, e);
  } finally {
    inflight[kind] = false;
  }
}

function onNav(nav) {
  if (nav.course_version !== fetched.course) refetch("course");
  if (nav.settings_version !== fetched.settings) refetch("settings");
  if (window.jabuka) window.jabuka.lastNav = nav;
  const b = sourceBadge(nav.wind);
  badge("wind", b.text, b.cls);
  emit("nav", nav);
}

// -- WebSocket + link watchdog (Pitfall 5) ------------------------------------------------------
let ws = null;
let lastMsg = NaN;
let connectStarted = 0;
let backoff = 1000;
let link = "stale";

function setLink(state) {
  if (state === link) return;
  link = state;
  document.body.classList.toggle("link-stale", state !== "live");
  badge("link", state === "live" ? null : "PERTE DONNÉES", "bad");
  emit("link", state);
}

function watchdog() {
  if (ws === null) return;
  if (ws.readyState === WebSocket.CONNECTING) {
    if (linkState(performance.now() - connectStarted) === "reconnect") ws.close();
    return;
  }
  if (ws.readyState !== WebSocket.OPEN) return;
  const state = linkState(performance.now() - lastMsg);
  setLink(state);
  if (state === "reconnect") ws.close();
}

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sock = new WebSocket(`${proto}//${location.host}/ws`);
  ws = sock;
  lastMsg = NaN;
  connectStarted = performance.now();
  sock.onopen = () => {
    backoff = 1000;
    lastMsg = performance.now();
    // a fresh connection may have missed one-off changes: refetch both once
    refetch("course");
    refetch("settings");
  };
  sock.onmessage = (ev) => {
    lastMsg = performance.now();
    setLink("live");
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (e) {
      console.error("bad message", e);
      return;
    }
    if (msg && msg.type === "nav") {
      try {
        onNav(msg);
      } catch (e) {
        console.error("nav handler", e);
      }
    }
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    ws = null;
    setLink("reconnect");
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };
  sock.onerror = () => sock.close();
}

// -- modules ------------------------------------------------------------------------------------
const MODULES = [
  ["helm", "./helm.js", "tab-barre"],
  ["carte", "./carte.js", "tab-carte"],
  ["reglages", "./reglages.js", "tab-reglages"],
  ["overlays", "./overlays.js", null],
];

// The map is optional for the helm: without WebGL (or MapLibre) the numbers keep updating and a
// badge says so (the Leaflet fallback stays deferred).
async function loadMap() {
  try {
    const m = await import("./map.js");
    const theme = storedTheme();
    await m.ensureMap($("map"), { theme });
    // the theme may have been toggled while the map was loading
    if (storedTheme() !== theme) await m.setTheme(storedTheme());
    badge("map", null);
  } catch (e) {
    console.error("map unavailable", e);
    badge("map", "CARTE INDISPONIBLE", "bad");
  }
}

async function loadModule(name, path, sectionId) {
  try {
    const mod = await import(path);
    await mod.mount({ section: sectionId ? $(sectionId) : null, api, bus, badge, latest });
  } catch (e) {
    console.error(`module ${name} failed`, e);
    badge(`mod-${name}`, `${name.toUpperCase()} INDISPONIBLE`, "warn");
  }
}

function init() {
  applyThemeClass(storedTheme());
  buildTopControls();
  applyThemeClass(storedTheme());
  trackTopbar();
  for (const btn of document.querySelectorAll("#topbar [data-tab]")) {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  }
  window.jabuka = Object.assign(window.jabuka ?? {}, { bus, api, setAppTheme });
  badge("link", "PERTE DONNÉES", "bad");
  document.body.classList.add("link-stale");
  // helm first and awaited: the numbers must show even if a later module fails
  loadModule(...MODULES[0]).then(() => {
    connect();
    setInterval(watchdog, 1000);
    loadMap();
    for (const m of MODULES.slice(1)) loadModule(...m);
  });
  showTab(currentTab);
}

init();
