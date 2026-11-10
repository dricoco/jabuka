// Pure (DOM-free) formatting of the core's start block (nav.start, quick 261110-cuk "Mode départ"),
// node-tested from tests/test_start_logic.py. The core computes every number (remaining time, line
// ends); this file only formats them. Every string goes to the page through textContent (start.js).
//
//   fmtTimer(s)                  "5:00", "0:05" (ceil: 0:00 only at the gun), "—:—" for null
//   fmtSigned(s)                 "+0:35" / "−0:05" (U+2212), "0:00", "" for null
//   remainingAt(block, rxMs, nowMs)
//                                the running timer's remaining seconds now, interpolated from the
//                                nav message's receive time (clamped at 0); null when not running
//   coordErrorKey(code)          coord_logic error code -> carte.err* key (hemisphere: caller)
//   startView(block, remaining, display)
//                                {visible, error, timer {text, state}, status, reason, lineInfo,
//                                ends {committee, pin: {label, text, ok}}, now / other rows
//                                {label, time, margin, cls, offLine, text}, tackNow,
//                                buttons {syncDisabled, stopDisabled}}
//   beepDue(prev, tackNow, nowMs)
//                                {beep, state}: one beep on the rising edge of the TACK alert,
//                                never twice within BEEP_GAP_MS
//   startData(block)             {zone, line, ends} GeoJSON FeatureCollections for the map
//   startLayers(theme)           layers of the "start" overlay (night: pure red only)
import { formatDM } from "./coord_logic.js";
import { fmtDistance, fmtHeading } from "./helm_logic.js";
import { fmtDec, t } from "./i18n.js";

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const pad2 = (n) => String(n).padStart(2, "0");
const MINUS = "−";

export const END_NAMES = ["committee", "pin"];
export const BEEP_GAP_MS = 10000;
const GOOD_S = 5; // |margin| within this: on time
const EMPTY = { type: "FeatureCollection", features: [] };
const fc = (features) => ({ type: "FeatureCollection", features });
const REASONS = {
  no_line: "start.rNoLine",
  no_position: "start.rNoPosition",
  no_heading: "start.rNoHeading",
  no_wind: "start.rNoWind",
  calc_error: "start.rCalc",
};

export function fmtTimer(seconds) {
  if (!isNum(seconds)) return "—:—";
  const s = Math.max(0, Math.ceil(seconds - 1e-9));
  return `${Math.floor(s / 60)}:${pad2(s % 60)}`;
}

export function fmtSigned(seconds) {
  if (!isNum(seconds)) return "";
  const s = Math.round(Math.abs(seconds));
  const text = `${Math.floor(s / 60)}:${pad2(s % 60)}`;
  if (s === 0) return text;
  return `${seconds < 0 ? MINUS : "+"}${text}`;
}

export function remainingAt(block, rxMs, nowMs) {
  const timer = block?.timer;
  if (!timer || timer.state !== "running" || !isNum(timer.remaining_s)) return null;
  const dt = isNum(rxMs) && isNum(nowMs) ? Math.max(0, (nowMs - rxMs) / 1000) : 0;
  return Math.max(0, timer.remaining_s - dt);
}

const ERR_KEYS = {
  empty: "carte.errEmpty",
  format: "carte.errFormat",
  minutes: "carte.errMinutes",
  seconds: "carte.errSeconds",
  range: "carte.errRange",
};

export const coordErrorKey = (code) => ERR_KEYS[code] ?? "carte.errFormat";

// Degrees + decimal minutes with the language's decimal separator (same as the Carte tab).
const decSep = () => fmtDec(0.5, 1).charAt(1);
export const fmtPos = (lat, lon) =>
  `${formatDM(lat, "lat", { sep: decSep() })}  ${formatDM(lon, "lon", { sep: decSep() })}`;

function endView(name, end) {
  const label = t(`start.${name}`);
  if (!end || !isNum(end.lat) || !isNum(end.lon)) return { label, text: t("start.endUnset"), ok: false };
  const src = t(end.src === "ping" ? "start.srcPing" : "start.srcTyped");
  return { label, text: `${fmtPos(end.lat, end.lon)} (${src})`, ok: true };
}

function statusText(block, state) {
  const parts = [];
  if (block.restored === "bak") parts.push(t("start.restoredBak"));
  else if (block.restored === "unreadable") parts.push(t("start.unreadable"));
  if (state === "off") parts.push(t("start.timerOff"));
  else if (state === "clock") parts.push(t("start.waitClock"));
  return parts.join(" · ");
}

// One time-to-line row ("Ligne au cap" / "Autre bord"): time, signed margin, colour class
// (good: on time within 5 s, bad: late by more than 5 s, "" early) and the off-the-line suffix.
export function sideRow(name, side) {
  const label = t(`start.${name}`);
  if (!side || !isNum(side.t_s)) return { label, time: "—", margin: "", cls: "", offLine: false, text: "—" };
  const time = fmtTimer(side.t_s);
  const m = side.margin_s;
  const margin = isNum(m) ? fmtSigned(m) : "";
  let cls = "";
  if (isNum(m)) {
    if (Math.abs(m) <= GOOD_S) cls = "good";
    else if (m < -GOOD_S) cls = "bad";
  }
  const offLine = side.on_line === false;
  let text = margin ? t("start.timeMargin", { t: time, m: margin }) : time;
  if (offLine) text += ` · ${t("start.offLine")}`;
  return { label, time, margin, cls, offLine, text };
}

function lineInfo(line, display) {
  if (!line || !isNum(line.length_nm)) return "";
  return t("start.lineInfo", { d: fmtDistance(line.length_nm), h: fmtHeading(line.bearing_t, display) });
}

// The start panel: what start.js shows. block = nav.start (absent while start mode is closed),
// remaining = remainingAt(...) (the interpolated countdown, null when not running), display =
// nav.display (°M / °T of the line bearing).
export function startView(block, remaining, display) {
  const hidden = {
    visible: false,
    error: false,
    timer: { text: fmtTimer(null), state: "off" },
    status: "",
    reason: "",
    lineInfo: "",
    ends: { committee: endView("committee", null), pin: endView("pin", null) },
    now: sideRow("now", null),
    other: sideRow("other", null),
    tackNow: false,
    buttons: { syncDisabled: true, stopDisabled: true },
  };
  if (!block || !block.open) return hidden;
  if (block.error) return { ...hidden, visible: true, error: true, status: t("start.error") };
  const state = block.timer?.state ?? "off";
  const rem = state === "running" ? (isNum(remaining) ? remaining : block.timer?.remaining_s) : null;
  const line = block.line ?? {};
  const reason = REASONS[block.reason] ? t(REASONS[block.reason]) : "";
  return {
    visible: true,
    error: false,
    timer: { text: fmtTimer(rem), state },
    status: [statusText(block, state), reason].filter(Boolean).join(" · "),
    reason,
    lineInfo: lineInfo(line, display),
    ends: { committee: endView("committee", line.committee), pin: endView("pin", line.pin) },
    now: sideRow("now", block.now),
    other: sideRow("other", block.other),
    tackNow: block.tack_now === true,
    buttons: { syncDisabled: state !== "running", stopDisabled: state === "off" },
  };
}

export function beepDue(prev, tackNow, nowMs) {
  const was = Boolean(prev?.was);
  const last = isNum(prev?.lastMs) ? prev.lastMs : null;
  const rising = Boolean(tackNow) && !was;
  const beep = rising && (last === null || nowMs - last >= BEEP_GAP_MS);
  return { beep, state: { was: Boolean(tackNow), lastMs: beep ? nowMs : last } };
}

// -- map ------------------------------------------------------------------------------------------
const okEnd = (e) => e && isNum(e.lat) && isNum(e.lon);

export function startData(block) {
  const out = { zone: EMPTY, line: EMPTY, ends: EMPTY };
  if (!block || !block.open || block.error) return out;
  const ring = block.zone;
  if (Array.isArray(ring) && ring.length >= 4) {
    out.zone = fc([{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } }]);
  }
  const com = block.line?.committee;
  const pin = block.line?.pin;
  const ends = [];
  for (const [role, e] of [
    ["committee", com],
    ["pin", pin],
  ]) {
    if (okEnd(e)) ends.push({ type: "Feature", properties: { role }, geometry: { type: "Point", coordinates: [e.lon, e.lat] } });
  }
  out.ends = fc(ends);
  if (okEnd(com) && okEnd(pin)) {
    out.line = fc([
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: [
            [com.lon, com.lat],
            [pin.lon, pin.lat],
          ],
        },
      },
    ]);
  }
  return out;
}

const START_COLORS = {
  day: { zone: "#e65c00", edge: "#b34700", line: "#202020", end: "#202020", halo: "#ffffff" },
  night: { zone: "#ff0000", edge: "#ff0000", line: "#ff0000", end: "#ff0000", halo: "#000000" },
};

// Layers of the "start" overlay (map.js registerOverlay): the zone (light fill + dashed edge),
// the line and its two ends. Night: pure red on black only, fill opacity 0.12.
export function startLayers(theme) {
  const night = theme === "night";
  const c = night ? START_COLORS.night : START_COLORS.day;
  return [
    {
      id: "start-zone-fill",
      type: "fill",
      source: "start-zone",
      paint: { "fill-color": c.zone, "fill-opacity": night ? 0.12 : 0.15 },
    },
    {
      id: "start-zone-edge",
      type: "line",
      source: "start-zone",
      paint: { "line-color": c.edge, "line-width": 2, "line-dasharray": [2, 2] },
    },
    {
      id: "start-line",
      type: "line",
      source: "start-line",
      layout: { "line-cap": "round" },
      paint: { "line-color": c.line, "line-width": 3 },
    },
    {
      id: "start-ends",
      type: "circle",
      source: "start-ends",
      paint: { "circle-radius": 6, "circle-color": c.end, "circle-stroke-width": 2, "circle-stroke-color": c.halo },
    },
  ];
}
