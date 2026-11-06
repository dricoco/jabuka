// Pure (DOM-free) formatting of the server's "nav" message for the Barre tab, unit-tested from
// pytest through node (tests/test_helm_logic.py). The server computes every number; this file
// only formats. Every direction in the message is TRUE; display.heading_ref says whether the helm
// shows magnetic (true - variation) or true headings, always with a °M/°T suffix (Pitfall 16).
//
// Plan 03-06: when the core has a valid route (nav.route.state "ok"), the primary number, the
// deviation and the countdown come from the route block (route_logic.js formats it); without one
// the Phase 2 layline values come back by themselves.
import { STR, countdownView, routeOk, tackWord } from "./route_logic.js";

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const pad2 = (n) => String(n).padStart(2, "0");
const frNum = (x, digits) => x.toFixed(digits).replace(".", ",");

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

// Distance: "0,35 nm", "4,2 nm", "38 nm".
export function fmtDistance(nm) {
  if (!isNum(nm)) return "—";
  if (nm < 1) return `${frNum(nm, 2)} nm`;
  if (nm < 10) return `${frNum(nm, 1)} nm`;
  return `${Math.round(nm)} nm`;
}

// Time-to-tack line: "Virement dans 12 min", "Empannage dans 4 min 30", "DÉPASSÉE +3 min",
// "ÇA PASSE"; "" when there is no layline (reach leg, no wind). With a valid route block as the
// third argument the route's countdown is used instead ("Virement dans 08:30", "VIREZ", ...).
export function fmtCountdown(layline, leg, route) {
  if (routeOk(route)) return countdownView({ route, layline, leg }).text;
  if (!layline || leg === "reach") return "";
  switch (layline.state) {
    case "normal": {
      const verb = leg === "run" ? "Empannage" : "Virement";
      return `${verb} dans ${fmtDuration(layline.countdown_s)}`;
    }
    case "overstood":
      return `DÉPASSÉE +${fmtDuration(layline.overstood_s)}`;
    case "fetching":
      return "ÇA PASSE";
    default:
      return "";
  }
}

// Wind source badge: {text, cls} with cls good | warn | bad.
export function sourceBadge(wind) {
  if (!wind || wind.source === "NONE") return { text: "PAS DE VENT", cls: "bad" };
  if (wind.stale) return { text: "PÉRIMÉ", cls: "bad" };
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
        text: isNum(wind.manual_age_s) ? `MANUEL ${Math.round(wind.manual_age_s / 60)} min` : "MANUEL âge ?",
        cls: "warn",
      };
    default:
      return { text: String(wind.source), cls: "warn" };
  }
}

// The server's alert when the whole nav computation raised (nav_service.update): every number is
// then null, which must never read as "no wind" (CR-01).
export const NAV_FAILED = "Erreur de calcul nav";
const NO_WIND = "PAS DE VENT";

export const navFailed = (nav) => Array.isArray(nav?.alerts) && nav.alerts.map(String).includes(NAV_FAILED);

// Wind badge of the top bar: a failed nav computation is shown as such, not as "PAS DE VENT".
export function windBadge(nav) {
  if (navFailed(nav)) return { text: "ERREUR CALCUL", cls: "bad" };
  return sourceBadge(nav?.wind);
}

// Alert badges (CR-01): every nav alert, de-duplicated, in server order. "PAS DE VENT" is left
// out because the wind badge already says it.
export function navAlerts(nav) {
  if (!Array.isArray(nav?.alerts)) return [];
  const out = [];
  for (const a of nav.alerts) {
    const text = String(a);
    if (text && text !== NO_WIND && !out.includes(text)) out.push(text);
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
    if (route.wrong_tack) return { text: "—", hint: STR.wrongTack, cls: "bad" };
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
    if (r > 0) hint = "◄ BÂBORD";
    else if (r < 0) hint = "TRIBORD ►";
  } else if (r > 0) hint = "LOFER";
  else if (r < 0) hint = "ABATTRE";
  return { text, hint, cls: deviationClass(dev) };
}

// Badges next to the source badge: {key, text, cls}.
export function helmFlags(nav) {
  const out = [];
  const wind = nav?.wind;
  const lay = nav?.layline;
  if (wind && wind.heading_trusted === false) out.push({ key: "cap", text: "CAP NON FIABLE", cls: "bad" });
  if (lay?.current) out.push({ key: "courant", text: "COURANT", cls: "warn" });
  if (lay?.src === "sailed") out.push({ key: "angles", text: "ANGLES RÉELS", cls: "warn" });
  return out;
}

// Primary number by point of sail (D-6): {label, value, main, unit}; value is the full text
// ("38°", "115°M"), main + unit the same split so the °M/°T suffix can be drawn smaller.
export function primaryView(nav) {
  const helm = nav?.helm;
  const plain = (label, value) => ({ label, value, main: value, unit: "" });
  if (navFailed(nav)) return plain("ERREUR CALCUL", "—");
  const route = routePrimary(nav);
  if (route) return route;
  if (!nav || !helm || !helm.primary) {
    const noWind = !nav?.wind || nav.wind.source === "NONE";
    return plain(noWind ? "PAS DE VENT" : "—", "—");
  }
  if (helm.primary === "twa_up" || helm.primary === "twa_down") {
    const label = helm.primary === "twa_up" ? "TWA CIBLE ↑" : "TWA CIBLE ↓";
    return plain(label, isNum(helm.target) ? `${Math.round(helm.target)}°` : "—");
  }
  const h = fmtHeading(helm.cts_t, nav.display);
  if (h === "—") return plain("CAP À SUIVRE", "—");
  return { label: "CAP À SUIVRE", value: h, main: h.slice(0, -1), unit: h.slice(-1) };
}

// Distance to the layline next to the layline countdown (NAV-02): "Layline à 1,5 nm"; "" when the
// countdown comes from the route or the layline is not ahead ("normal" state only).
export function laylineDistText(nav, source = countdownView(nav).source) {
  const lay = nav?.layline;
  if (source !== "layline" || !lay || lay.state !== "normal" || nav?.leg === "reach") return "";
  if (!isNum(lay.dist_nm)) return "";
  return `${STR.laylineDist}${fmtDistance(lay.dist_nm)}`;
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
    const label = a >= 90 ? STR.twaRouteDown : STR.twaRouteUp;
    return { label, value: word ? `${main} ${word}` : main, main, unit: word };
  }
  const h = fmtHeading(r.target, nav.display);
  if (h === "—") return null;
  return { label: STR.capRoute, value: h, main: h.slice(0, -1), unit: h.slice(-1) };
}

// Every text of the helm bands from one nav message (missing blocks give "—" or "").
export function helmView(nav) {
  const polar = nav?.polar ?? {};
  const boat = nav?.boat ?? {};
  const mark = nav?.mark;
  const lay = nav?.layline;
  const bsp = isNum(boat.bsp_kn) ? frNum(boat.bsp_kn, 1) : "—";
  const tgt = isNum(polar.target_bsp_kn) ? frNum(polar.target_bsp_kn, 1) : "—";
  const dev = deviationView(nav);
  const other = lay ? fmtHeading(lay.other_tack_hdg_t, nav?.display) : "—";
  const markName = mark?.name ? String(mark.name) : "—";
  const dtw = fmtDistance(mark?.dtw_nm);
  const ttw = fmtDuration(mark?.ttw_s);
  const cd = countdownView(nav);
  return {
    primary: primaryView(nav),
    dev,
    deviation: dev.text,
    deviationClass: dev.cls,
    speed: `${bsp} / ${tgt} nds`,
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
    otherTack: other === "—" ? "" : `Autre bord ${other}`,
    badge: windBadge(nav),
    flags: helmFlags(nav),
    alerts: navAlerts(nav),
  };
}
