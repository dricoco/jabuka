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
//   startView(block, remaining)  {visible, timer {text, state}, status, ends {committee, pin:
//                                {label, text, ok}}, buttons {syncDisabled, stopDisabled}}
import { formatDM } from "./coord_logic.js";
import { fmtDec, t } from "./i18n.js";

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const pad2 = (n) => String(n).padStart(2, "0");
const MINUS = "−";

export const END_NAMES = ["committee", "pin"];

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

// The start panel: what start.js shows. block = nav.start (absent while start mode is closed),
// remaining = remainingAt(...) (the interpolated countdown, null when not running).
export function startView(block, remaining) {
  const hidden = {
    visible: false,
    error: false,
    timer: { text: fmtTimer(null), state: "off" },
    status: "",
    ends: { committee: endView("committee", null), pin: endView("pin", null) },
    buttons: { syncDisabled: true, stopDisabled: true },
  };
  if (!block || !block.open) return hidden;
  if (block.error) return { ...hidden, visible: true, error: true, status: t("start.error") };
  const state = block.timer?.state ?? "off";
  const rem = state === "running" ? (isNum(remaining) ? remaining : block.timer?.remaining_s) : null;
  const line = block.line ?? {};
  return {
    visible: true,
    error: false,
    timer: { text: fmtTimer(rem), state },
    status: statusText(block, state),
    ends: { committee: endView("committee", line.committee), pin: endView("pin", line.pin) },
    buttons: { syncDisabled: state !== "running", stopDisabled: state === "off" },
  };
}
