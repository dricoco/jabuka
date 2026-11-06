// Jabuka diagnostics page: renders the server's 1 Hz "diag" message from /ws.
// Ages and staleness are computed by the server (injected clock); this file only formats, except
// for the link watchdog: when no message arrives for RX_STALE_MS the whole page turns stale.

import { alertsFor, errorAlerts, linkState } from "./diag_logic.js";
import { applyI18n, t } from "./i18n.js";

// the page's static labels in the tablet's language (same localStorage as the helm app)
applyI18n(document);
document.title = t("diag.title");

const $ = (id) => document.getElementById(id);

const RAD2DEG = 180 / Math.PI;
const MS2KN = 3600 / 1852;

function fmtPos(v) {
  const part = (deg, pos, neg) => {
    const h = deg >= 0 ? pos : neg;
    const a = Math.abs(deg);
    const d = Math.floor(a);
    const m = (a - d) * 60;
    return `${d}°${m.toFixed(3)}'${h}`;
  };
  return `${part(v.latitude, "N", "S")} ${part(v.longitude, "E", "W")}`;
}

// Pure formatting of SI values for humans.
export function display(value, unit) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    if ("latitude" in value && "longitude" in value) return fmtPos(value);
    return JSON.stringify(value);
  }
  if (typeof value !== "number") return String(value);
  switch (unit) {
    case "rad": return `${(value * RAD2DEG).toFixed(1)}°`;
    case "m/s": return `${(value * MS2KN).toFixed(2)} kn`;
    case "m": return `${value.toFixed(1)} m`;
    case "K": return `${(value - 273.15).toFixed(1)} °C`;
    default: return String(Math.round(value * 1000) / 1000);
  }
}

function fmtSI(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return String(Math.round(value * 10000) / 10000);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function td(text, cls) {
  const el = document.createElement("td");
  el.textContent = text ?? "";
  if (cls) el.className = cls;
  return el;
}

function ageClass(row) {
  if (row.stale) return "stale";
  const thr = row.stale_after_s ?? 10;
  return row.age_s > thr / 2 ? "aging" : "fresh";
}

function renderValues(rows) {
  const body = $("values-body");
  const frag = document.createDocumentFragment();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.className = ageClass(r);
    tr.append(
      td(r.path),
      td(fmtSI(r.value), "num"),
      td(display(r.value, r.unit), "num"),
      td(r.unit ?? ""),
      td(r.src),
      td(r.ref ?? ""),
      td(r.ch ?? ""),
      td(r.disp ?? ""),
      td(Number(r.age_s).toFixed(1), "num age"),
    );
    frag.append(tr);
  }
  body.replaceChildren(frag);
}

function kvTable(table, obj, firstKey) {
  const keys = Object.keys(obj);
  if (firstKey && keys.includes(firstKey)) {
    keys.splice(keys.indexOf(firstKey), 1);
    keys.unshift(firstKey);
  }
  const frag = document.createDocumentFragment();
  for (const k of keys) {
    const tr = document.createElement("tr");
    const v = obj[k];
    tr.append(td(k), td(typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)));
    frag.append(tr);
  }
  table.replaceChildren(frag);
}

function renderClock(clock) {
  const gate = $("gate");
  const ok = clock.routing_time_gate === "ok";
  gate.textContent = t("diag.gate", { g: clock.routing_time_gate });
  gate.className = `gate ${ok ? "gate-ok" : "gate-blocked"}`;
  kvTable($("clock-table"), clock, "routing_time_gate");
}

function renderHealth(health) {
  const root = $("health");
  const frag = document.createDocumentFragment();
  for (const [src, h] of Object.entries(health)) {
    const box = document.createElement("div");
    box.className = "health-src";
    const title = document.createElement("h3");
    title.textContent = `${src} `;
    const alive = document.createElement("span");
    alive.className = `alive-${Boolean(h.alive)}`;
    alive.textContent = t(h.alive ? "diag.alive" : "diag.silent");
    title.append(alive);
    const table = document.createElement("table");
    table.className = "kv";
    kvTable(table, h);
    box.append(title, table);
    frag.append(box);
  }
  root.replaceChildren(frag);
}

function renderAlerts(lines) {
  const el = $("alerts");
  el.replaceChildren(...lines.map((line) => {
    const div = document.createElement("div");
    div.textContent = line;
    return div;
  }));
  el.hidden = lines.length === 0;
}

const errorMemory = {};

function render(msg) {
  if (msg.type !== "diag") return;
  renderAlerts([...alertsFor(msg), ...errorAlerts(msg, errorMemory, performance.now())]);
  renderClock(msg.clock ?? {});
  renderValues(msg.values ?? []);
  renderHealth(msg.health ?? {});
  kvTable($("core-table"), { ...(msg.core ?? {}), ...(msg.log ?? {}) });
}

function setConn(up, text) {
  const el = $("conn");
  el.textContent = text;
  el.className = `conn ${up ? "conn-up" : "conn-down"}`;
}

// -- event marker ---------------------------------------------------------------------------
function hhmmss(utc) {
  const d = utc ? new Date(utc) : new Date();
  return d.toISOString().slice(11, 19);
}

async function sendEvent() {
  const ack = $("event-ack");
  const input = $("event-label");
  const btn = $("event-btn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: input.value }),
    });
    if (res.status === 201) {
      const body = await res.json();
      ack.textContent = t("diag.markerLogged", {
        n: body.n,
        time: hhmmss(body.utc),
        z: body.utc ? "Z" : t("diag.localClock"),
      });
      input.value = "";
    } else if (res.status === 429) {
      ack.textContent = t("diag.tooFast");
    } else if (res.status === 422) {
      ack.textContent = t("diag.tooLong");
    } else if (res.status === 503) {
      ack.textContent = t("diag.diskFull");
    } else {
      ack.textContent = t("diag.httpFail", { s: res.status });
    }
  } catch (e) {
    ack.textContent = t("diag.fail", { e });
  } finally {
    btn.disabled = false;
  }
}

$("event-btn").addEventListener("click", sendEvent);
$("event-label").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") sendEvent();
});

let backoff = 1000;
let ws = null;
let lastMsg = NaN; // performance.now() of the last message; NaN until the first one
let connectStarted = 0;

// Frozen data must never look fresh: mark every value row stale and every source silent.
function markAllStale() {
  for (const tr of document.querySelectorAll("#values-body tr")) tr.className = "stale";
  for (const el of document.querySelectorAll("#health [class^='alive-']")) {
    el.className = "alive-false";
    el.textContent = t("diag.noData");
  }
}

function watchdog() {
  if (ws === null) return; // onclose already scheduled the reconnect
  if (ws.readyState === WebSocket.CONNECTING) {
    // a connect attempt over a half-open link can hang: give up and retry
    if (linkState(performance.now() - connectStarted) === "reconnect") ws.close();
    return;
  }
  if (ws.readyState !== WebSocket.OPEN) return;
  const since = performance.now() - lastMsg;
  const state = linkState(since);
  if (state === "live") return;
  const secs = Number.isFinite(since) ? Math.round(since / 1000) : "?";
  setConn(false, t("diag.noDataFor", { s: secs }));
  markAllStale();
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
    lastMsg = performance.now(); // the server sends a snapshot right away
    setConn(true, t("diag.connected"));
  };
  sock.onmessage = (ev) => {
    lastMsg = performance.now();
    try {
      render(JSON.parse(ev.data));
      setConn(true, t("diag.live"));
    } catch (e) {
      console.error("bad message", e);
    }
  };
  sock.onclose = () => {
    if (ws !== sock) return; // an older socket closing late
    ws = null;
    markAllStale();
    setConn(false, t("diag.reconnecting", { s: backoff / 1000 }));
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };
  sock.onerror = () => sock.close();
}

setInterval(watchdog, 1000);
connect();
