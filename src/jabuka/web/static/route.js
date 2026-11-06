// The route on the tablet (plan 03-06, render only: every number comes from the core's route
// block and route message, 03-05):
//   - map: overlay "route" on the shared map (map.js registerOverlay, so day/night style swaps
//     keep it): the route line, its tack points and the next tack point (followed from
//     nav.route.tack_lat/lon every second). Greyed out without tack points while the core
//     says the route is withdrawn ("outdated"), hidden in every other non-ok state.
//   - Barre tab: #route-band under the helm countdown with the route state, the cost of not
//     tacking, the route age, the complementary target and the GRIB bias, and the big
//     "ON RESTE" button (POST /api/route/stay {active}). The button does nothing while the
//     screen is locked: lock.js's overlay swallows the taps, and the handler also checks
//     body.locked / the bus "lock" event (a scripted or keyboard click cannot get through).
// The route message comes from the WS (bus "route", also sent on connect); whenever
// nav.route.version differs from the drawn one, GET /api/route heals a missed message.
// Every string goes through textContent (T-03-06-01).
import { t, trServer } from "./i18n.js";
import { ensureMap, mapReady, registerOverlay, setOverlayData, setOverlayVisible } from "./map.js";
import {
  STR,
  nextTackData,
  routeBand,
  routeData,
  routeLayers,
  routeVisible,
  stayButton,
  staleLine,
} from "./route_logic.js";

const $ = (id) => document.getElementById(id);
const EMPTY = { type: "FeatureCollection", features: [] };
const REFETCH_MS = 5000; // a failed GET /api/route for the same version is retried after this

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  if (text !== undefined) e.textContent = text;
  return e;
}

function setLine(e, text, cls) {
  if (!e) return;
  const t = text ?? "";
  if (e.textContent !== t) e.textContent = t;
  e.hidden = !t;
  if (cls !== undefined) {
    e.classList.remove("warn", "bad");
    if (cls) e.classList.add(cls);
  }
}

// #route-band, under the countdown (and the layline distance) in the bottom band
function buildBand(section) {
  let band = $("route-band");
  if (band) return band;
  band = el("div", { id: "route-band", class: "route-band", hidden: "" });
  band.append(
    el("div", { id: "route-status", class: "route-line route-status", hidden: "" }),
    el("div", { id: "route-cost", class: "route-line route-cost", hidden: "" }),
  );
  const row = el("div", { class: "route-row" });
  row.append(
    el("span", { id: "route-age", class: "route-item", hidden: "" }),
    el("span", { id: "route-target", class: "route-item", hidden: "" }),
    el("span", { id: "route-bias", class: "route-item", hidden: "" }),
  );
  band.append(row);
  // "ON RESTE": full band width, >= 64 px high (app.css)
  band.append(el("button", { type: "button", id: "stay-button", class: "stay-btn", disabled: "" }, STR.stay));
  const anchor = $("helm-layline-dist") ?? $("helm-countdown");
  if (anchor) anchor.after(band);
  else (section ?? $("tab-barre"))?.append(band);
  return band;
}

export function renderBand(nav) {
  const band = $("route-band");
  if (!band) return null;
  const v = routeBand(nav);
  band.hidden = !v.visible;
  band.classList.remove("warn", "bad");
  if (v.cls) band.classList.add(v.cls);
  setLine($("route-status"), v.lines.status, v.cls);
  setLine($("route-cost"), v.lines.cost);
  setLine($("route-age"), v.lines.age, v.ageCls);
  setLine($("route-target"), v.lines.target);
  setLine($("route-bias"), v.lines.bias);
  return v;
}

const FLASH_MS = 6000; // a refused "On reste" is said in the status line this long

export function mount(ctx) {
  buildBand(ctx.section);
  let nav = ctx.latest?.("nav") ?? null;
  let locked = document.body.classList.contains("locked");
  let pending = false; // a POST in flight: the button stays disabled until the answer
  let flash = null; // {text, until}
  const button = $("stay-button");

  const renderButton = () => {
    if (!button) return;
    const v = stayButton(nav?.route);
    if (button.textContent !== v.label) button.textContent = v.label;
    button.classList.toggle("active", v.active);
    button.setAttribute("aria-pressed", v.active ? "true" : "false");
    button.disabled = pending || v.disabled;
  };

  const render = () => {
    renderBand(nav);
    if (flash && performance.now() < flash.until) setLine($("route-status"), flash.text, "bad");
    else flash = null;
    renderButton();
  };

  button?.addEventListener("click", async () => {
    if (locked || document.body.classList.contains("locked") || pending) return;
    const v = stayButton(nav?.route);
    if (v.disabled) return;
    pending = true;
    renderButton();
    try {
      // the answer is the fresh nav message, with the new stay state
      const fresh = await ctx.api.post("/api/route/stay", { active: !v.active });
      if (fresh && typeof fresh === "object" && fresh.route) nav = fresh;
    } catch (e) {
      const why = e?.body?.error ?? e?.body?.detail ?? e?.message;
      const r = typeof why === "string" && why ? trServer(why) : t("common.error");
      flash = { text: t("route.stayRefused", { r }), until: performance.now() + FLASH_MS };
    } finally {
      pending = false;
      render();
    }
  });
  ctx.bus.addEventListener("lock", (ev) => {
    locked = Boolean(ev.detail);
  });
  let ready = false; // overlay registered on the map
  let drawn = 0; // version of the drawn route line
  let shown = null; // overlay visibility applied
  let nextKey = "";
  const data = { route: EMPTY, "route-tack": EMPTY, "route-next": EMPTY };
  let raw = { line: EMPTY, tacks: EMPTY }; // the drawn route message, before the stale styling
  let stale = false; // drawn greyed out (route withdrawn by the core)
  let inflight = false;
  let tried = { version: 0, t: 0 };

  const put = (name, value) => {
    data[name] = value;
    if (ready) setOverlayData(name, value);
  };

  const draw = (msg) => {
    if (!msg || msg.type !== "route" || !msg.geojson) return;
    const d = routeData(msg);
    raw = { line: d.line, tacks: d.tacks };
    put("route", staleLine(raw.line, stale));
    put("route-tack", stale ? EMPTY : raw.tacks);
    if (!nav?.route) put("route-next", d.next); // until the first nav message says where it is
    drawn = Number(msg.version) || 0;
    globalThis.jabuka = Object.assign(globalThis.jabuka ?? {}, { routeVersion: drawn });
  };

  const refetch = async (version) => {
    if (inflight) return;
    const now = performance.now();
    if (tried.version === version && now - tried.t < REFETCH_MS) return;
    tried = { version, t: now };
    inflight = true;
    try {
      draw(await ctx.api.get("/api/route"));
    } catch (e) {
      if (e?.status !== 404) console.warn("route fetch", e);
    } finally {
      inflight = false;
    }
  };

  const sync = () => {
    const r = nav?.route;
    const visible = routeVisible(r);
    if (ready && visible !== shown) {
      setOverlayVisible("route", visible);
      shown = visible;
    }
    const out = r?.state === "outdated";
    if (out !== stale) {
      stale = out;
      put("route", staleLine(raw.line, stale));
      put("route-tack", stale ? EMPTY : raw.tacks);
    }
    if (!r) return;
    // the next tack point follows the boat's progress along the route (nav every second)
    const key = `${r.tack_lat},${r.tack_lon}`;
    if (key !== nextKey) {
      nextKey = key;
      put("route-next", nextTackData(r));
    }
    const v = Number(r.version) || 0;
    if (visible && v > 0 && v !== drawn) refetch(v);
  };

  ctx.bus.addEventListener("nav", (ev) => {
    nav = ev.detail;
    try {
      render();
    } catch (e) {
      console.error("route band", e);
    }
    sync();
  });
  ctx.bus.addEventListener("route", (ev) => draw(ev.detail));
  draw(ctx.latest?.("route"));
  render();
  if (nav) sync();

  // the map is optional: the band works without it, the overlay comes up whenever it loads
  (async () => {
    try {
      await ensureMap($("map"));
    } catch {
      await mapReady();
    }
    const sources = {};
    for (const [name, value] of Object.entries(data)) sources[name] = { type: "geojson", data: value };
    registerOverlay("route", { sources, layers: routeLayers });
    ready = true;
    shown = null;
    sync();
  })().catch((e) => console.error("route overlay", e));
}
