// The route on the tablet (plan 03-06, render only: every number comes from the core's route
// block and route message, 03-05):
//   - map: overlay "route" on the shared map (map.js registerOverlay, so day/night style swaps
//     keep it): the route line, its tack points and the next tack point (followed from
//     nav.route.tack_lat/lon every second). Hidden while the route is not valid.
//   - Barre tab: #route-band under the helm countdown with the route state, the cost of not
//     tacking, the route age, the complementary target and the GRIB bias.
// The route message comes from the WS (bus "route", also sent on connect); whenever
// nav.route.version differs from the drawn one, GET /api/route heals a missed message.
// Every string goes through textContent (T-03-06-01).
import { ensureMap, mapReady, registerOverlay, setOverlayData, setOverlayVisible } from "./map.js";
import { nextTackData, routeBand, routeData, routeLayers } from "./route_logic.js";

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

export function mount(ctx) {
  buildBand(ctx.section);
  let nav = ctx.latest?.("nav") ?? null;
  let ready = false; // overlay registered on the map
  let drawn = 0; // version of the drawn route line
  let shown = null; // overlay visibility applied
  let nextKey = "";
  const data = { route: EMPTY, "route-tack": EMPTY, "route-next": EMPTY };
  let inflight = false;
  let tried = { version: 0, t: 0 };

  const put = (name, value) => {
    data[name] = value;
    if (ready) setOverlayData(name, value);
  };

  const draw = (msg) => {
    if (!msg || msg.type !== "route" || !msg.geojson) return;
    const d = routeData(msg);
    put("route", d.line);
    put("route-tack", d.tacks);
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
    const ok = r?.state === "ok";
    if (ready && ok !== shown) {
      setOverlayVisible("route", ok);
      shown = ok;
    }
    if (!r) return;
    // the next tack point follows the boat's progress along the route (nav every second)
    const key = `${r.tack_lat},${r.tack_lon}`;
    if (key !== nextKey) {
      nextKey = key;
      put("route-next", nextTackData(r));
    }
    const v = Number(r.version) || 0;
    if (ok && v > 0 && v !== drawn) refetch(v);
  };

  ctx.bus.addEventListener("nav", (ev) => {
    nav = ev.detail;
    try {
      renderBand(nav);
    } catch (e) {
      console.error("route band", e);
    }
    sync();
  });
  ctx.bus.addEventListener("route", (ev) => draw(ev.detail));
  draw(ctx.latest?.("route"));
  if (nav) {
    renderBand(nav);
    sync();
  }

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
