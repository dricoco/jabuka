// Pure (DOM-free) logic for the diagnostics page, unit-tested from pytest through node
// (tests/test_diag_logic.py).

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
    const what = {
      low: "disk space below the reserve",
      pruning: "deleting old logs to free disk space",
      error: `retention failed: ${disk.last_error ?? "?"}`,
    }[disk.state] ?? `disk ${disk.state}`;
    out.push(`Core: ${what} (${mb(disk.free_bytes)} free)`);
  }
  if (disk && disk.raw_floor_breaches > 0) {
    out.push(`Core: raw history inside the 36 h floor was deleted (${disk.raw_floor_breaches} files)`);
  }
  for (const [src, h] of Object.entries(msg?.health ?? {})) {
    if (h && h.disk_state && h.disk_state !== "ok") {
      out.push(`${src}: disk ${h.disk_state} (${mb(h.disk_free_bytes)} free)`);
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
