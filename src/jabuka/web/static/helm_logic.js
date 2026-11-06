// Pure (DOM-free) formatting of the server's "nav" message for the Barre tab, unit-tested from
// pytest through node (tests/test_helm_logic.py). The server computes every number; this file
// only formats. Every direction in the message is TRUE; display.heading_ref says whether the helm
// shows magnetic (true - variation) or true headings, always with a °M/°T suffix (Pitfall 16).

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
// "ÇA PASSE"; "" when there is no layline (reach leg, no wind).
export function fmtCountdown(layline, leg) {
  if (!layline) return "";
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
    case "MANUEL":
      return { text: "MANUEL", cls: "warn" };
    default:
      return { text: String(wind.source), cls: "warn" };
  }
}

// Colour class of the deviation (actual - target): small = good.
export function deviationClass(deviation) {
  if (!isNum(deviation)) return "";
  const a = Math.abs(deviation);
  if (a <= 3) return "good";
  if (a <= 8) return "warn";
  return "bad";
}

// Primary number by point of sail (D-6): {label, value, unit}.
export function primaryView(nav) {
  const helm = nav?.helm;
  if (!nav || !helm || !helm.primary) {
    const noWind = !nav?.wind || nav.wind.source === "NONE";
    return { label: noWind ? "PAS DE VENT" : "—", value: "—", unit: "" };
  }
  if (helm.primary === "twa_up" || helm.primary === "twa_down") {
    const label = helm.primary === "twa_up" ? "TWA CIBLE ↑" : "TWA CIBLE ↓";
    return { label, value: isNum(helm.target) ? `${Math.round(helm.target)}°` : "—", unit: "" };
  }
  const h = fmtHeading(helm.cts_t, nav.display);
  if (h === "—") return { label: "CAP À SUIVRE", value: "—", unit: "" };
  return { label: "CAP À SUIVRE", value: h.slice(0, -1), unit: h.slice(-1) };
}

const signed = (x, unit) => (isNum(x) ? `${x > 0 ? "+" : ""}${Math.round(x)}${unit}` : "—");

// Every text of the helm bands from one nav message.
export function helmView(nav) {
  const helm = nav?.helm ?? {};
  const polar = nav?.polar ?? {};
  const boat = nav?.boat ?? {};
  const mark = nav?.mark;
  const lay = nav?.layline;
  const bsp = isNum(boat.bsp_kn) ? frNum(boat.bsp_kn, 1) : "—";
  const tgt = isNum(polar.target_bsp_kn) ? frNum(polar.target_bsp_kn, 1) : "—";
  return {
    primary: primaryView(nav),
    deviation: signed(helm.deviation, "°"),
    deviationClass: deviationClass(helm.deviation),
    speed: `${bsp} / ${tgt} kn`,
    pct: isNum(polar.pct) ? `${Math.round(polar.pct)} %` : "— %",
    mark: mark ? mark.name : "—",
    dtw: fmtDistance(mark?.dtw_nm),
    ttw: fmtDuration(mark?.ttw_s),
    btw: fmtHeading(mark?.btw_t, nav?.display),
    countdown: fmtCountdown(lay, nav?.leg),
    otherTack: lay ? `Autre bord ${fmtHeading(lay.other_tack_hdg_t, nav?.display)}` : "",
    badge: sourceBadge(nav?.wind),
    alerts: Array.isArray(nav?.alerts) ? nav.alerts.map(String) : [],
  };
}
