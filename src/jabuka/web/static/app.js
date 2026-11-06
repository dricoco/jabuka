// App shell: tabs, one WebSocket with a link watchdog, the module bus, version-driven refetch of
// the course and settings, and the dynamically imported feature modules.
//
// Module contract: each module exports mount(ctx), ctx = {section, api, bus, badge}.
//   bus events (CustomEvent detail): "nav" (nav message), "course" (GET /api/course JSON),
//   "settings" ({version, settings}), "tab" (tab name), "link" ("live" | "stale" | "reconnect").
//   api: {get, post, put, patch, del} -> parsed JSON; throws ApiError {status, body}.
//   badge(key, text | null, cls): show/clear a badge in #badges.
// A module that fails to load or mount never stops the helm numbers.

import { linkState } from "./diag_logic.js";
import { sourceBadge } from "./helm_logic.js";

const $ = (id) => document.getElementById(id);
export const bus = new EventTarget();
const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));

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
];

async function loadModule(name, path, sectionId) {
  try {
    const mod = await import(path);
    await mod.mount({ section: sectionId ? $(sectionId) : null, api, bus, badge });
  } catch (e) {
    console.error(`module ${name} failed`, e);
    badge(`mod-${name}`, `${name.toUpperCase()} INDISPONIBLE`, "warn");
  }
}

function init() {
  for (const btn of document.querySelectorAll("#topbar [data-tab]")) {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  }
  window.jabuka = Object.assign(window.jabuka ?? {}, { bus, api });
  badge("link", "PERTE DONNÉES", "bad");
  document.body.classList.add("link-stale");
  // helm first and awaited: the numbers must show even if a later module fails
  loadModule(...MODULES[0]).then(() => {
    connect();
    setInterval(watchdog, 1000);
    for (const m of MODULES.slice(1)) loadModule(...m);
  });
  showTab(currentTab);
}

init();
