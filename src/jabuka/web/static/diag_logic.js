// Pure (DOM-free) logic for the diagnostics page, unit-tested from pytest through node
// (tests/test_diag_logic.py). Texts in the tablet's language (i18n.js "diag.*" keys).
import { t } from "./i18n.js";

const MB = 1e6;

function mb(bytes) {
  return typeof bytes === "number" ? `${Math.round(bytes / MB)} MB` : "?";
}

// Alert lines for a diag message: anything here turns the page's alert banner red.
export function alertsFor(msg) {
  const out = [];
  const core = msg?.core ?? {};
  const disk = core.disk;
  if (disk && disk.state && disk.state !== "ok") {
    let what;
    if (disk.state === "low") what = t("diag.diskLow");
    else if (disk.state === "pruning") what = t("diag.diskPruning");
    else if (disk.state === "error") what = t("diag.diskError", { e: disk.last_error ?? "?" });
    else what = t("diag.diskOther", { s: disk.state });
    out.push(t("diag.coreDisk", { what, free: mb(disk.free_bytes) }));
  }
  if (disk && disk.raw_floor_breaches > 0) {
    out.push(t("diag.rawFloor", { n: disk.raw_floor_breaches }));
  }
  for (const [src, h] of Object.entries(msg?.health ?? {})) {
    if (h && h.disk_state && h.disk_state !== "ok") {
      out.push(t("diag.srcDisk", { src, state: h.disk_state, free: mb(h.disk_free_bytes) }));
    }
  }
  return out;
}

// -- link watchdog (WR-05) ------------------------------------------------------------------------
// The server pushes a diag message every second. A half-open Wi-Fi link (tablet at the edge of the
// AP, AP restart, core hung with the socket open) may not fire onclose for minutes, so the client
// times out on its own: after RX_STALE_MS without a message every value is shown stale, after
// RX_CLOSE_MS the socket is closed to force a reconnect.
export const RX_STALE_MS = 3000;
export const RX_CLOSE_MS = 6000;

// "live" | "stale" | "reconnect" for the time since the last message (ms).
export function linkState(sinceLastMs) {
  if (!(sinceLastMs >= 0)) return "stale"; // never received anything (NaN/undefined)
  if (sinceLastMs > RX_CLOSE_MS) return "reconnect";
  if (sinceLastMs > RX_STALE_MS) return "stale";
  return "live";
}

// -- log/send error counters (WR-06) --------------------------------------------------------------
// The counters are cumulative since the process started. An alert is shown for ERROR_ALERT_MS
// after a counter increases (or is first seen above zero), so a persistent failure keeps the banner
// red and a transient one fades while its count stays visible in the tables.
export const ERROR_ALERT_MS = 60000;
const CORE_ERRORS = ["derived_errors", "bus_log_errors", "events_errors", "flush_errors", "handler_errors", "nav_errors"];
const SOURCE_ERRORS = ["raw_errors", "send_errors"];

// memory: an object kept by the caller between messages; nowMs: a monotonic clock in ms.
export function errorAlerts(msg, memory, nowMs) {
  const out = [];
  const check = (key, value, line) => {
    if (typeof value !== "number") return;
    const prev = memory[key];
    if (prev === undefined || value < prev.value) {
      // first sight, or the counter restarted with its process
      memory[key] = { value, at: value > 0 && prev === undefined ? nowMs : -Infinity };
    } else if (value > prev.value) {
      memory[key] = { value, at: nowMs };
    }
    if (nowMs - memory[key].at <= ERROR_ALERT_MS) out.push(line(value));
  };
  const core = msg?.core ?? {};
  for (const key of CORE_ERRORS) {
    check(`core.${key}`, core[key], (n) => t("diag.errCore", { text: t(`diag.err.${key}`), n }));
  }
  for (const [src, h] of Object.entries(msg?.health ?? {})) {
    for (const key of SOURCE_ERRORS) {
      check(`${src}.${key}`, h?.[key], (n) => t("diag.errSrc", { src, text: t(`diag.err.${key}`), n }));
    }
  }
  return out;
}
