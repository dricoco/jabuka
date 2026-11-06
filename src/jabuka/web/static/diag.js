// Jabuka diagnostics page: renders the server's 1 Hz "diag" message from /ws.
// Ages and staleness are computed by the server (injected clock); this file only formats.

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
  gate.textContent = `routing: ${clock.routing_time_gate}`;
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
    alive.textContent = h.alive ? "alive" : "silent";
    title.append(alive);
    const table = document.createElement("table");
    table.className = "kv";
    kvTable(table, h);
    box.append(title, table);
    frag.append(box);
  }
  root.replaceChildren(frag);
}

function render(msg) {
  if (msg.type !== "diag") return;
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

let backoff = 1000;

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => {
    backoff = 1000;
    setConn(true, "live");
  };
  ws.onmessage = (ev) => {
    try {
      render(JSON.parse(ev.data));
    } catch (e) {
      console.error("bad message", e);
    }
  };
  ws.onclose = () => {
    setConn(false, `reconnecting in ${backoff / 1000}s`);
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };
  ws.onerror = () => ws.close();
}

connect();
