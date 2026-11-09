// Pure (DOM-free) formatting of the server's "nav" message for the Barre tab, unit-tested from
// pytest through node (tests/test_helm_logic.py). The server computes every number; this file
// only formats. Every direction in the message is TRUE; display.heading_ref says whether the helm
// shows magnetic (true - variation) or true headings, always with a °M/°T suffix (Pitfall 16).
//
// Plan 03-06: when the core has a valid route (nav.route.state "ok"), the primary number, the
// deviation and the countdown come from the route block (route_logic.js formats it); without one
// the Phase 2 layline values come back by themselves.
import { SERVER, fmtDec, t, trServer } from "./i18n.js";
import { countdownView, routeOk, tackCue, tackWord } from "./route_logic.js";

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const pad2 = (n) => String(n).padStart(2, "0");

// Heading for display: "045°M" / "045°T"; "—" when unknown.
export function fmtHeading(degT, display) {
  if (!isNum(degT)) return "—";
  const ref = display?.heading_ref === "M" ? "M" : "T";
  const variation = isNum(display?.variation) ? display.variation : 0;
  let d = ref === "M" ? degT - variation : degT;
  d = Math.round(((d % 360) + 360) % 360) % 360;
  return `${String(d).padStart(3, "0")}°${ref}`;
}

// Duration for humans: "45 s", "4 min 30", "12 min", "1 h 05".
export function fmtDuration(seconds) {
  if (!isNum(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 600) {
    const m = Math.floor(s / 60);
    const r = s % 60;
    return r === 0 ? `${m} min` : `${m} min ${pad2(r)}`;
  }
  const mins = Math.round(s / 60);
  if (mins < 60) return `${mins} min`;
  return `${Math.floor(mins / 60)} h ${pad2(mins % 60)}`;
}

// Distance: "0,35 nm", "4,2 nm", "38 nm" (decimal point in English).
export function fmtDistance(nm) {
  if (!isNum(nm)) return "—";
  if (nm < 1) return `${fmtDec(nm, 2)} nm`;
  if (nm < 10) return `${fmtDec(nm, 1)} nm`;
  return `${Math.round(nm)} nm`;
}

// Time-to-tack line: "Virement dans 12 min", "Empannage dans 4 min 30", "DÉPASSÉE +3 min",
// "ÇA PASSE"; "" when there is no layline (reach leg, no wind). With a valid route block as the
// third argument the route's countdown is used instead ("Virement dans 08:30", "VIREZ", ...).
export function fmtCountdown(layline, leg, route) {
  if (routeOk(route)) return countdownView({ route, layline, leg }).text;
  if (!layline || leg === "reach") return "";
  switch (layline.state) {
    case "normal":
      return t(leg === "run" ? "helm.gybeIn" : "helm.tackIn", { t: fmtDuration(layline.countdown_s) });
    case "overstood":
      return t("helm.overstood", { t: fmtDuration(layline.overstood_s) });
    case "fetching":
      return t("helm.fetching");
    default:
      return "";
  }
}

// Wind source badge: {text, cls} with cls good | warn | bad.
export function sourceBadge(wind) {
  if (!wind || wind.source === "NONE") return { text: t("badge.noWind"), cls: "bad" };
  if (wind.stale) return { text: t("badge.stale"), cls: "bad" };
  switch (wind.source) {
    case "LIVE":
      return { text: "LIVE", cls: "good" };
    case "LIVE_BG":
      return { text: "LIVE B&G", cls: "good" };
    case "GRIB":
      // GPS + GRIB only: the bus is silent, heading = COG, speed = SOG (03-05, WIND-05)
      return { text: "GRIB", cls: "warn" };
    case "MANUEL":
      return {
        // no trusted UTC (GPS not synced, now or at entry): the age is unknown, never guessed
        text: isNum(wind.manual_age_s)
          ? t("badge.manual", { n: Math.round(wind.manual_age_s / 60) })
          : t("badge.manualUnknown"),
        cls: "warn",
      };
    default:
      return { text: String(wind.source), cls: "warn" };
  }
}

// The server's alert when the whole nav computation raised (nav_service.update): every number is
// then null, which must never read as "no wind" (CR-01).
export const NAV_FAILED = SERVER.NAV_FAILED;
const NO_WIND = SERVER.NO_WIND;

export const navFailed = (nav) => Array.isArray(nav?.alerts) && nav.alerts.map(String).includes(NAV_FAILED);

// Wind badge of the top bar: a failed nav computation is shown as such, not as "PAS DE VENT".
export function windBadge(nav) {
  if (navFailed(nav)) return { text: t("badge.calcError"), cls: "bad" };
  return sourceBadge(nav?.wind);
}

// Alert badges (CR-01): every nav alert, de-duplicated, in server order, in the tablet's language
// (trServer). "PAS DE VENT" is left out because the wind badge already says it.
export function navAlerts(nav) {
  if (!Array.isArray(nav?.alerts)) return [];
  const out = [];
  for (const a of nav.alerts) {
    const raw = String(a);
    const text = trServer(raw);
    if (raw && raw !== NO_WIND && !out.includes(text)) out.push(text);
  }
  return out;
}

// Colour class of the deviation (actual - target): within 2 deg good, within 5 deg warn, else bad.
export function deviationClass(deviation) {
  if (!isNum(deviation)) return "";
  const a = Math.abs(deviation);
  if (a <= 2) return "good";
  if (a <= 5) return "warn";
  return "bad";
}

// Round half away from zero (-1.5 -> -2, like +1.5 -> +2).
const roundSym = (x) => Math.sign(x) * Math.round(Math.abs(x));

// Deviation with the steering hint (D-6). On a TWA target, deviation = TWA - target: positive means
// too far off the wind -> LOFER (head up), negative -> ABATTRE (bear away), upwind and downwind
// alike. On a course to steer, deviation = heading - CTS: positive -> steer to port.
export function deviationView(nav) {
  const route = nav?.route;
  if (routeOk(route) && route.primary) {
    // on the other tack than the route's: no signed |TWA| difference, say it (03-REVIEW HI-01)
    if (route.wrong_tack) return { text: "—", hint: t("route.wrongTack"), cls: "bad" };
    // same semantics from the core: |TWA| - |target| (LOFER/ABATTRE), heading - target (side)
    const primary = route.primary === "hdg" ? "cts" : "twa_up";
    return deviationView({ helm: { primary, deviation: route.deviation } });
  }
  const helm = nav?.helm;
  const dev = helm?.deviation;
  if (!helm || !isNum(dev)) return { text: "—", hint: "", cls: "" };
  const r = roundSym(dev);
  const text = `${r > 0 ? "+" : ""}${r}°`;
  let hint = "";
  if (helm.primary === "cts") {
    if (r > 0) hint = t("helm.hintPort");
    else if (r < 0) hint = t("helm.hintStbd");
  } else if (r > 0) hint = t("helm.hintUp");
  else if (r < 0) hint = t("helm.hintDown");
  return { text, hint, cls: deviationClass(dev) };
}

// G-4-R08: the core sent a boat block without a position (GPS lost or stale: nav_service always
// sends lat/lon, null when unknown). Partial messages without a boat block or without the lat/lon
// keys, and a failed nav computation (ERREUR CALCUL), are not "no position".
export function noPosition(nav) {
  if (navFailed(nav)) return false;
  const boat = nav?.boat;
  if (!boat || typeof boat !== "object") return false;
  if (!("lat" in boat) && !("lon" in boat)) return false;
  return !(isNum(boat.lat) && isNum(boat.lon));
}

// G-4-R01: the wind in use is too old (MANUEL older than manual_wind_max_age_min).
export function windStale(nav) {
  return nav?.wind?.stale === true;
}

// Badges next to the source badge: {key, text, cls}; PAS DE GPS (red) leads.
export function helmFlags(nav) {
  const out = [];
  const wind = nav?.wind;
  const lay = nav?.layline;
  if (noPosition(nav)) out.push({ key: "gps", text: t("flag.noGps"), cls: "bad" });
  if (wind && wind.heading_trusted === false) out.push({ key: "cap", text: t("flag.cap"), cls: "bad" });
  if (lay?.current) out.push({ key: "courant", text: t("flag.current"), cls: "warn" });
  if (lay?.src === "sailed") out.push({ key: "angles", text: t("flag.sailed"), cls: "warn" });
  return out;
}

const plain = (label, value) => ({ label, value, main: value, unit: "" });

// Primary number by point of sail (D-6): {label, value, main, unit}; value is the full text
// ("38°", "115°M"), main + unit the same split so the °M/°T suffix can be drawn smaller.
// Takeovers, in priority order: nav failure (ERREUR CALCUL), no position (G-4-R08: PAS DE GPS),
// stale wind (G-4-R01: VENT PÉRIMÉ), the tack cue (G-4-R03: VIREZ / EMPANNEZ + the tack to go to,
// cue: true), then the route primary, then the Phase 2 helm primary.
export function primaryView(nav) {
  if (navFailed(nav)) return plain(t("badge.calcError"), "—");
  if (noPosition(nav)) return { ...plain(t("flag.noGps"), "—"), alert: true };
  // G-4-R01: stale manual wind still drives the numbers (Phase 2 contract), but never as a
  // confident live target; no tack cue either, since wrong_tack and the follower's target use the
  // stale TWD
  if (windStale(nav)) {
    const p = routePrimary(nav) ?? helmPrimary(nav);
    return { ...p, label: t("helm.windStale"), alert: true, stale: true };
  }
  const cue = tackCue(nav?.route);
  if (cue) {
    const value = cue.tack ? `${cue.word} ${cue.tack}` : cue.word;
    return { label: cue.label, value, main: cue.word, unit: cue.tack, cue: true };
  }
  return routePrimary(nav) ?? helmPrimary(nav);
}

// The Phase 2 primary (no valid route): the TWA target or the course to steer.
function helmPrimary(nav) {
  const helm = nav?.helm;
  if (!nav || !helm || !helm.primary) {
    const noWind = !nav?.wind || nav.wind.source === "NONE";
    return plain(noWind ? t("badge.noWind") : "—", "—");
  }
  if (helm.primary === "twa_up" || helm.primary === "twa_down") {
    const label = t(helm.primary === "twa_up" ? "helm.twaUp" : "helm.twaDown");
    return plain(label, isNum(helm.target) ? `${Math.round(helm.target)}°` : "—");
  }
  const h = fmtHeading(helm.cts_t, nav.display);
  if (h === "—") return plain(t("helm.cts"), "—");
  return { label: t("helm.cts"), value: h, main: h.slice(0, -1), unit: h.slice(-1) };
}

// Distance to the layline next to the layline countdown (NAV-02): "Layline à 1,5 nm"; "" when the
// countdown comes from the route or the layline is not ahead ("normal" state only).
export function laylineDistText(nav, source = countdownView(nav).source) {
  const lay = nav?.layline;
  if (source !== "layline" || !lay || lay.state !== "normal" || nav?.leg === "reach") return "";
  if (!isNum(lay.dist_nm)) return "";
  return t("helm.laylineDist", { d: fmtDistance(lay.dist_nm) });
}

// Primary number from a valid route: "TWA ROUTE ↑" 42° tribord, or "CAP ROUTE" 114°M on a reach;
// null without a valid route (the Phase 2 targets apply).
function routePrimary(nav) {
  const r = nav?.route;
  if (!routeOk(r) || !r.primary) return null;
  if (r.primary === "twa") {
    if (!isNum(r.target)) return null;
    const a = Math.abs(r.target);
    const main = `${Math.round(a)}°`;
    const word = tackWord(r.target_tack);
    const label = t(a >= 90 ? "route.twaRouteDown" : "route.twaRouteUp");
    return { label, value: word ? `${main} ${word}` : main, main, unit: word };
  }
  const h = fmtHeading(r.target, nav.display);
  if (h === "—") return null;
  return { label: t("route.capRoute"), value: h, main: h.slice(0, -1), unit: h.slice(-1) };
}

// Every text of the helm bands from one nav message (missing blocks give "—" or "").
export function helmView(nav) {
  const polar = nav?.polar ?? {};
  const boat = nav?.boat ?? {};
  const mark = nav?.mark;
  const lay = nav?.layline;
  const bsp = isNum(boat.bsp_kn) ? fmtDec(boat.bsp_kn, 1) : "—";
  const tgt = isNum(polar.target_bsp_kn) ? fmtDec(polar.target_bsp_kn, 1) : "—";
  const stale = windStale(nav);
  let dev = deviationView(nav);
  const other = lay ? fmtHeading(lay.other_tack_hdg_t, nav?.display) : "—";
  const markName = mark?.name ? String(mark.name) : "—";
  const dtw = fmtDistance(mark?.dtw_nm);
  const ttw = fmtDuration(mark?.ttw_s);
  let cd = countdownView(nav);
  if (stale) {
    // G-4-R01: no LOFER/ABATTRE, no colours, no alert countdown on stale wind; the countdown line
    // must not say the tack the primary box refuses to cue (the route's due-tack cue is the only
    // "alert" countdownView emits). countdownView stays unchanged; other texts stay, dimmed.
    dev = { ...dev, hint: "", cls: "" };
    cd = { ...cd, text: cd.cls === "alert" ? t("helm.windStale") : cd.text, cls: "" };
  }
  return {
    primary: primaryView(nav),
    dev,
    deviation: dev.text,
    deviationClass: dev.cls,
    speed: t("helm.speed", { bsp, tgt }),
    pct: isNum(polar.pct) ? `${Math.round(polar.pct)} %` : "— %",
    mark: markName,
    dtw,
    ttw,
    markLine: mark ? `${markName} ${dtw} · ${ttw}` : "—",
    btw: fmtHeading(mark?.btw_t, nav?.display),
    countdown: cd.text,
    countdownCls: cd.cls,
    countdownSource: cd.source,
    laylineDist: laylineDistText(nav, cd.source),
    otherTack: other === "—" ? "" : t("helm.otherTack", { h: other }),
    badge: windBadge(nav),
    flags: helmFlags(nav),
    alerts: navAlerts(nav),
    windStale: stale,
    noGps: noPosition(nav),
  };
}
