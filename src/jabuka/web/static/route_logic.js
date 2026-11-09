// Pure (DOM-free) formatting of the core's route block (nav.route, plan 03-05) for the helm,
// unit-tested from pytest through node (tests/test_route_logic.py). The core computes every
// number (countdown, cost, age, bias, targets); this file only formats them. Every string goes
// to the page through textContent (route.js), never as HTML.
//
// Every helm string of the route features is a "route.*" key of i18n.js (fr / en / sl); STR.x is
// t("route.x") in the tablet's language. The core's reasons go through trServer.
import { fmtCountdown, fmtDuration, fmtHeading } from "./helm_logic.js";
import { SERVER, t, trServer } from "./i18n.js";

export const STR = new Proxy({}, { get: (_o, k) => (typeof k === "string" ? t(`route.${k}`) : undefined) });

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const pad2 = (n) => String(n).padStart(2, "0");
const EMPTY = { type: "FeatureCollection", features: [] };
const fc = (features) => ({ type: "FeatureCollection", features });
const MISSED_S = -120; // the core recomputes 2 min after a missed advised tack

// A route the helm may steer: the core says "ok" (an adopted, valid route).
export const routeOk = (route) => Boolean(route) && route.state === "ok";

// Countdown clock: "08:30" below one hour, "1 h 07" above.
export function fmtClock(seconds) {
  if (!isNum(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 3600) return `${pad2(Math.floor(s / 60))}:${pad2(s % 60)}`;
  const m = Math.round(s / 60);
  return `${Math.floor(m / 60)} h ${pad2(m % 60)}`;
}

export const tackWord = (tack) => (tack === "stbd" || tack === "port" ? t(`tack.${tack}`) : "");

// The helm's countdown line: {text, cls ("" | "warn" | "alert"), source ("route" | "layline")}.
// From the route when it is valid, else exactly the Phase 2 layline text.
export function countdownView(nav) {
  const r = nav?.route;
  if (!routeOk(r)) return { text: fmtCountdown(nav?.layline, nav?.leg), cls: "", source: "layline" };
  const route = (text, cls = "") => ({ text, cls, source: "route" });
  if (r.updating) return route(STR.updating, "warn");
  const stay = r.stay ?? {};
  // only before the release: afterwards the forced tack is due, VIREZ below (03-REVIEW LO-08)
  if (stay.active && stay.released_land && isNum(stay.release_in_s) && stay.release_in_s > 0) {
    return route(t("route.landTackIn", { t: fmtClock(stay.release_in_s) }), "warn");
  }
  const cd = r.countdown_s;
  if (!isNum(cd)) return route(STR.noTack);
  const gybe = r.tack_kind === "gybe";
  if (cd <= 0) {
    if (cd > MISSED_S) return route(gybe ? STR.gybeNow : STR.tackNow, "alert");
    return route(STR.updating, "warn");
  }
  return route(t(gybe ? "helm.gybeIn" : "helm.tackIn", { t: fmtClock(cd) }));
}

const OTHER_TACK = { stbd: "port", port: "stbd" };

// The manoeuvre cue of the primary box (G-4-R03): {word, tack, label, kind} or null. The cue the
// countdown line already shows ("VIREZ", 26 px) also takes over the primary box (review C/R03),
// because a missed cue costs a forced recompute 2 min later. kind "due": the advised tack is due
// now (countdown <= 0, above the missed-tack limit), go to the other tack than the route's;
// kind "wrong": the boat is on the other tack than the route's, go to the route's tack.
export function tackCue(route) {
  if (!routeOk(route) || route.updating) return null;
  const cd = route.countdown_s;
  const due = isNum(cd) && cd <= 0 && cd > MISSED_S;
  const wrong = route.wrong_tack === true;
  if (!due && !wrong) return null;
  const kind = wrong ? "wrong" : "due";
  const to = wrong ? route.target_tack : (OTHER_TACK[route.target_tack] ?? null);
  const gybe = wrong ? isNum(route.target_twa) && Math.abs(route.target_twa) >= 90 : route.tack_kind === "gybe";
  return {
    word: gybe ? STR.gybeNow : STR.tackNow,
    tack: tackWord(to),
    label: wrong ? STR.wrongTack : STR.cueNow,
    kind,
  };
}

// "Ne pas virer : +4 min" / "Ne pas virer : < 1 min"; null when the core has no cost.
export function costText(route) {
  if (!routeOk(route) || !route.cost_text) return null;
  return t("route.cost", { c: String(route.cost_text) });
}

// "Biais GRIB +12° ×1.15" (+ " (s'estompe)" / " (gelé, Jabuka)"); null when nothing to say.
export function biasText(bias) {
  if (!bias) return null;
  if (bias.enabled === false || bias.state === SERVER.BIAS_OFF) return STR.biasOff;
  if (bias.valid && isNum(bias.dir_deg) && isNum(bias.ratio)) {
    const d = Math.round(bias.dir_deg);
    const dir = `${d >= 0 ? "+" : "-"}${Math.abs(d)}°`;
    const suffix = { [SERVER.BIAS_FADING]: STR.biasFading, [SERVER.BIAS_FROZEN]: STR.biasFrozenSuffix }[bias.state];
    return t("route.bias", { d: dir, k: bias.ratio.toFixed(2) }) + (suffix ?? "");
  }
  if (bias.state === SERVER.BIAS_LEARNING) return STR.biasLearning;
  if (bias.state === SERVER.BIAS_FROZEN) return STR.biasFrozen;
  return null;
}

// The big button: {label, active, disabled}. Holding the tack needs a valid route with a known
// tack; cancelling is always possible.
export function stayButton(route) {
  const active = Boolean(route?.stay?.active);
  const usable = routeOk(route) && Boolean(route.target_tack);
  return { label: active ? STR.stayCancel : STR.stay, active, disabled: !active && !usable };
}

function ageText(ageS) {
  if (!isNum(ageS)) return null;
  if (ageS < 60) return t("route.age", { a: STR.ageRecent });
  if (ageS < 3600) return t("route.age", { a: `${Math.floor(ageS / 60)} min` });
  return t("route.age", { a: fmtDuration(ageS) });
}

// The state line: why there is no route, or what the current route is doing (the core's reason
// in the tablet's language).
function statusText(r) {
  const why = (key, fallback) => t(key, { r: r.reason ? trServer(r.reason) : fallback });
  switch (r.state) {
    case "ok": {
      if (r.updating) return STR.updating;
      const parts = [];
      if (r.stay?.active) {
        const w = tackWord(r.stay.tack);
        parts.push(w ? t("route.stayOnTack", { w }) : STR.stayOn);
      }
      if (r.off_route) parts.push(STR.offRoute);
      if (r.level && r.level !== "L0") parts.push(t("route.level", { l: String(r.level) }));
      // the route is still steerable but its last recompute failed (03-REVIEW CR-02)
      if (r.stale && r.last_fail) parts.push(t("route.staleFail", { r: trServer(r.last_fail) }));
      return parts.join(" · ");
    }
    case "outdated":
      return why("route.outdated", STR.outdatedDefault);
    case "blocked_clock":
      return why("route.blockedClock", STR.blockedClockDefault);
    case "no_pack":
      return why("route.noPack", STR.noPackDefault);
    case "computing":
      return STR.computing;
    case "failed":
      return why("route.failed", STR.failedDefault);
    case "disabled":
      return STR.disabled;
    default:
      return why("route.routing", String(r.state));
  }
}

const STATE_CLS = {
  ok: "",
  computing: "warn",
  disabled: "warn",
  no_course: "warn",
  no_position: "warn",
  outdated: "warn",
};

// The route band of the Barre tab: {visible, lines: {status, countdown, cost, age, target, bias},
// cls, ageCls}. Lines are strings, or null/"" when hidden.
export function routeBand(nav) {
  const r = nav?.route;
  const lines = { status: null, countdown: null, cost: null, age: null, target: null, bias: null };
  if (!r || !r.state) return { visible: false, lines, cls: "", ageCls: "" };
  const ok = routeOk(r);
  lines.status = statusText(r);
  lines.bias = biasText(r.bias);
  let ageCls = "";
  if (ok) {
    lines.countdown = countdownView(nav).text;
    lines.cost = costText(r);
    lines.age = ageText(r.age_s);
    if (isNum(r.age_s) && r.age_s > 1200) ageCls = "warn";
    if (r.primary === "twa") {
      const h = fmtHeading(r.target_hdg_t, nav?.display);
      lines.target = h === "—" ? null : t("route.capRouteLine", { h });
    } else if (r.primary === "hdg" && isNum(r.target_twa)) {
      const w = tackWord(r.target_tack);
      lines.target = t("route.twaRouteLine", { a: `${Math.round(Math.abs(r.target_twa))}°${w ? ` ${w}` : ""}` });
    }
  }
  const cls = ok ? (r.updating || r.stale ? "warn" : "") : (STATE_CLS[r.state] ?? "bad");
  return { visible: true, lines, cls, ageCls };
}

// -- map ------------------------------------------------------------------------------------------
// The WS/REST "route" message split into the overlay sources: {line, tacks, next}.
export function routeData(msg) {
  const out = { line: EMPTY, tacks: EMPTY, next: EMPTY };
  const feats = msg?.geojson?.features;
  if (!Array.isArray(feats)) return out;
  const role = (f) => f?.properties?.role;
  out.line = fc(feats.filter((f) => f?.geometry?.type === "LineString"));
  out.tacks = fc(feats.filter((f) => f?.geometry?.type === "Point" && role(f) === "tack"));
  out.next = fc(feats.filter((f) => f?.geometry?.type === "Point" && role(f) === "next_tack"));
  return out;
}

// A withdrawn ("outdated", 03-REVIEW CR-02) route stays on the map, greyed out: the line
// features get properties.stale, which the route-line paint turns grey (dark red at night).
export const routeVisible = (route) => route?.state === "ok" || route?.state === "outdated";

export function staleLine(line, stale) {
  const feats = Array.isArray(line?.features) ? line.features : [];
  return fc(feats.map((f) => ({ ...f, properties: { ...(f?.properties ?? {}), stale: Boolean(stale) } })));
}

// The next tack point from the nav route block (followed every second).
export function nextTackData(route) {
  if (!route || !isNum(route.tack_lat) || !isNum(route.tack_lon)) return EMPTY;
  return fc([
    {
      type: "Feature",
      properties: { kind: route.tack_kind ?? "tack" },
      geometry: { type: "Point", coordinates: [route.tack_lon, route.tack_lat] },
    },
  ]);
}

const ROUTE_COLORS = {
  day: { line: "#8b008b", stale: "#9e9e9e", tack: "#8b008b", next: "#8b008b", halo: "#ffffff" },
  night: { line: "#ff0000", stale: "#550000", tack: "#aa0000", next: "#ff0000", halo: "#000000" },
};

// Layers of the "route" overlay (map.js registerOverlay): day a 4 px dark-magenta line with
// white-cased tack circles; night pure red on black only (dashed line).
export function routeLayers(theme) {
  const night = theme === "night";
  const c = night ? ROUTE_COLORS.night : ROUTE_COLORS.day;
  return [
    {
      id: "route-line",
      type: "line",
      source: "route",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": ["case", ["boolean", ["get", "stale"], false], c.stale, c.line],
        "line-width": 4,
        ...(night ? { "line-dasharray": [3, 2] } : {}),
      },
    },
    {
      id: "route-tack",
      type: "circle",
      source: "route-tack",
      paint: { "circle-radius": 5, "circle-color": c.tack, "circle-stroke-width": 2, "circle-stroke-color": c.halo },
    },
    {
      id: "route-next",
      type: "circle",
      source: "route-next",
      paint: { "circle-radius": 9, "circle-color": c.next, "circle-stroke-width": 3, "circle-stroke-color": c.halo },
    },
  ];
}
