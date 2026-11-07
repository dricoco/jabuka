// Map contract (HELM-01): one MapLibre GL JS 5.24.0 map (UMD global `maplibregl`, vendored) behind
// every tab, shared by overlays.js (02-01/02-05), carte.js (02-04) and the night theme (02-05).
//
//   ensureMap(container, {theme}) -> Promise<Map>   idempotent singleton; rejects Error("webgl")
//                                                   when WebGL/MapLibre is unavailable
//   getMap() -> Promise<Map> | null
//   mapReady() -> Promise<Map>                      resolves once a map has loaded, even after a
//                                                   failed first attempt (never rejects)
//   registerOverlay(id, {sources: {name: spec}, layers: (theme) => LayerSpec[]})
//   setOverlayData(sourceName, geojson)             keeps the data across style switches
//   setOverlayVisible(id, bool)
//   registerImage(id, () => {data: ImageData, pixelRatio})  icon added whenever a layer needs it
//                                                   (survives day/night style switches)
//   setTheme("day" | "night")                       re-styles, re-adding every overlay
//   setMapPadding({top, right, bottom, left})       px of the map hidden under the UI (quick 002:
//                                                   the helm column); the camera centre, easeTo
//                                                   and getCenter use the visible part. Kept for
//                                                   a map that loads later; no-op when unchanged
//   absolutizeStyle(style, origin)                  MapLibre rejects relative URLs (Pitfall 2)
//   storedTheme()                                   localStorage "jabuka.theme", default "day"
// window.jabuka.map is set once the map has loaded (debug, tests).
//
// The style comes from the race pack: the vector basemap when /racepack/info says tiles, else a
// coastline-only style built here (fill layer "earth", so land checks work the same), else a
// background-only style. Nothing is fetched outside the core.

const THEME_KEY = "jabuka.theme";
const CENTER = [15.7, 43.45];
// The race area (14.9-16.4 E, 42.7-44.1 N) plus a margin: MapLibre keeps the whole canvas inside
// maxBounds, padding included, so without it the helm column's padding (quick 002) would stop
// "Centrer" from putting a boat near the edge of the area in the middle of the visible map at
// CENTRE_ZOOM (up to ~0.9° of longitude beside a 640 px column, ~0.5° of latitude above a
// portrait top area). Outside the tiles the map is plain water.
const BOUNDS = [
  [13.9, 42.0],
  [17.4, 44.8],
];
const LOAD_TIMEOUT_MS = 30000;
const GLYPHS = "/glyphs/{fontstack}/{range}.pbf";

let mapPromise = null;
let mapInstance = null;
let currentTheme = null;
let racepack = { tiles: false, seamarks: false, coastline: false };
const overlays = new Map(); // id -> {sources, layers, visible}
let readyResolve = null;
const ready = new Promise((resolve) => {
  readyResolve = resolve;
});

export function storedTheme() {
  try {
    return globalThis.localStorage?.getItem(THEME_KEY) === "night" ? "night" : "day";
  } catch {
    return "day";
  }
}

// Prefix root-relative URLs (glyphs, sprite, tiles, geojson data) with origin; absolute URLs stay.
export function absolutizeStyle(style, origin) {
  const abs = (u) => (typeof u === "string" && u.startsWith("/") && !u.startsWith("//") ? origin + u : u);
  if (style.glyphs) style.glyphs = abs(style.glyphs);
  if (typeof style.sprite === "string") style.sprite = abs(style.sprite);
  else if (Array.isArray(style.sprite)) style.sprite = style.sprite.map((s) => ({ ...s, url: abs(s.url) }));
  for (const src of Object.values(style.sources ?? {})) {
    if (Array.isArray(src.tiles)) src.tiles = src.tiles.map(abs);
    if (typeof src.url === "string") src.url = abs(src.url);
    if (typeof src.data === "string") src.data = abs(src.data);
  }
  return style;
}

const PALETTE = {
  day: { water: "#b9d3e6", earth: "#ece8dc", line: "#7a7a7a" },
  night: { water: "#000000", earth: "#260000", line: "#600000" },
};

function backgroundStyle(theme) {
  const p = PALETTE[theme] ?? PALETTE.day;
  return {
    version: 8,
    name: `jabuka-${theme}-empty`,
    glyphs: GLYPHS,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": p.water } }],
  };
}

function coastlineStyle(theme) {
  const p = PALETTE[theme] ?? PALETTE.day;
  const style = backgroundStyle(theme);
  style.name = `jabuka-${theme}-coastline`;
  style.sources.coastline = { type: "geojson", data: "/racepack/coastline.geojson" };
  style.layers.push(
    {
      id: "earth",
      type: "fill",
      source: "coastline",
      filter: ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false],
      paint: { "fill-color": p.earth },
    },
    {
      id: "coastline",
      type: "line",
      source: "coastline",
      filter: ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false],
      paint: { "line-color": p.line, "line-width": 1 },
    },
  );
  return style;
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

// The vendored styles declare the full extract's maxzoom (14). A degraded race pack (prep fallback
// to maxzoom 12 or 10) must say its real maxzoom, or MapLibre asks for tiles the core answers 204
// and draws nothing above it instead of overzooming the last level (WR-06).
export function fitStyleToPack(style, info) {
  const z = info?.maxzoom;
  if (!info?.tiles || !Number.isInteger(z) || z < 0) return style;
  for (const src of Object.values(style.sources ?? {})) {
    if (src.type === "vector") src.maxzoom = z;
  }
  return style;
}

async function loadStyle(theme) {
  let style;
  if (racepack.tiles) style = fitStyleToPack(await fetchJson(`/style-${theme}.json`), racepack);
  else if (racepack.coastline) style = coastlineStyle(theme);
  else style = backgroundStyle(theme);
  return absolutizeStyle(style, location.origin);
}

function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

// -- overlays -----------------------------------------------------------------------------------
function overlayLayers(id, def, theme) {
  return def.layers(theme).map((layer) => ({
    ...layer,
    layout: { ...(layer.layout ?? {}), visibility: def.visible ? "visible" : "none" },
    metadata: { ...(layer.metadata ?? {}), "jabuka:overlay": id },
  }));
}

// Layers whose metadata says "jabuka:top" (the boat) stay above every other overlay, whatever
// order the overlays were registered in (route.js registers after overlays.js).
const isTop = (layer) => Boolean(layer?.metadata?.["jabuka:top"]);
const topLast = (layers) => [...layers.filter((l) => !isTop(l)), ...layers.filter(isTop)];

function addOverlay(map, id, def) {
  for (const [name, spec] of Object.entries(def.sources)) {
    if (!map.getSource(name)) map.addSource(name, spec);
  }
  for (const layer of overlayLayers(id, def, currentTheme)) {
    if (!map.getLayer(layer.id)) map.addLayer(layer);
  }
  for (const layer of map.getStyle()?.layers ?? []) {
    if (isTop(layer)) map.moveLayer(layer.id);
  }
}

export function registerOverlay(id, { sources, layers }) {
  const def = { sources: { ...sources }, layers, visible: true };
  overlays.set(id, def);
  if (mapInstance) addOverlay(mapInstance, id, def);
}

// Runtime icons (the boat): a style switch drops every image added with addImage, so they are
// (re)added on demand when a layer asks for a missing one. factory() -> {data: ImageData, pixelRatio}.
const images = new Map();

export function registerImage(id, factory) {
  images.set(id, factory);
}

function addMissingImage(map, id) {
  const factory = images.get(id);
  if (!factory || map.hasImage(id)) return;
  try {
    const { data, pixelRatio } = factory();
    map.addImage(id, data, { pixelRatio });
  } catch (e) {
    console.warn("image", id, e);
  }
}

export function setOverlayData(sourceName, data) {
  for (const def of overlays.values()) {
    if (def.sources[sourceName]) def.sources[sourceName] = { ...def.sources[sourceName], data };
  }
  const src = mapInstance?.getSource(sourceName);
  if (src && typeof src.setData === "function") src.setData(data);
}

export function setOverlayVisible(id, visible) {
  const def = overlays.get(id);
  if (!def) return;
  def.visible = Boolean(visible);
  if (!mapInstance) return;
  for (const layer of def.layers(currentTheme)) {
    if (mapInstance.getLayer(layer.id)) {
      mapInstance.setLayoutProperty(layer.id, "visibility", def.visible ? "visible" : "none");
    }
  }
}

// -- padding (quick 002) ------------------------------------------------------------------------
let wantedPadding = { top: 0, right: 0, bottom: 0, left: 0 };

const clampPx = (v) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.round(v) : 0);

function applyPadding() {
  if (!mapInstance) return;
  const cur = mapInstance.getPadding();
  const p = wantedPadding;
  if (cur.top === p.top && cur.right === p.right && cur.bottom === p.bottom && cur.left === p.left) return;
  mapInstance.setPadding(p);
}

export function setMapPadding(padding) {
  const p = padding ?? {};
  wantedPadding = { top: clampPx(p.top), right: clampPx(p.right), bottom: clampPx(p.bottom), left: clampPx(p.left) };
  applyPadding();
}

// -- map ----------------------------------------------------------------------------------------
export function getMap() {
  return mapPromise;
}

export function mapReady() {
  return ready;
}

// A failed attempt (load timeout on a busy Pi, style fetch error) is torn down and forgotten
// (IN-02): the next ensureMap() call retries instead of returning the same rejection forever.
export function ensureMap(container, opts = {}) {
  if (mapPromise) return mapPromise;
  let built = null;
  const attempt = (async () => {
    const gl = globalThis.maplibregl;
    if (!gl || typeof gl.Map !== "function") throw new Error("webgl");
    if (typeof gl.supported === "function" && !gl.supported()) throw new Error("webgl");
    if (!webglAvailable()) throw new Error("webgl");
    const theme = opts.theme ?? storedTheme();
    try {
      racepack = await fetchJson("/racepack/info");
    } catch {
      racepack = { tiles: false, seamarks: false, coastline: false };
    }
    const style = await loadStyle(theme);
    currentTheme = theme;
    let map;
    try {
      map = new gl.Map({
        container,
        style,
        center: CENTER,
        zoom: 9,
        maxBounds: BOUNDS,
        attributionControl: { compact: true },
      });
    } catch (e) {
      console.error("map construction failed", e);
      throw new Error("webgl");
    }
    built = map;
    map.on("error", (ev) => console.warn("map:", ev?.error?.message ?? ev));
    map.on("styleimagemissing", (ev) => addMissingImage(map, ev.id));
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("map load timeout")), LOAD_TIMEOUT_MS);
      map.once("load", () => {
        clearTimeout(timer);
        resolve();
      });
    });
    mapInstance = map;
    applyPadding();
    for (const [id, def] of overlays) addOverlay(map, id, def);
    globalThis.jabuka = Object.assign(globalThis.jabuka ?? {}, { map, racepack });
    // a theme toggled while the map was loading (WR-04)
    if (wantedTheme !== null && wantedTheme !== currentTheme) setTheme(wantedTheme).catch(() => {});
    readyResolve(map);
    return map;
  })();
  const p = attempt.catch((e) => {
    try {
      built?.remove(); // frees the WebGL context of the half-built map
    } catch {
      /* already gone */
    }
    if (mapPromise === p) mapPromise = null;
    throw e;
  });
  mapPromise = p;
  return p;
}

// Theme switches are serialized and only the latest request is applied (WR-04): a fast double
// tap must never leave the day style under the night UI because the first style fetch finished
// after the second tap had already returned.
let wantedTheme = null;
let themeChain = Promise.resolve();

export function setTheme(theme) {
  const t = theme === "night" ? "night" : "day";
  try {
    globalThis.localStorage?.setItem(THEME_KEY, t);
  } catch {
    /* private mode: per-session only */
  }
  wantedTheme = t;
  themeChain = themeChain.catch(() => {}).then(applyWantedTheme);
  return themeChain;
}

async function applyWantedTheme() {
  const t = wantedTheme;
  // no map yet: ensureMap applies wantedTheme once loaded (currentTheme tracks the real style)
  if (!mapInstance || t === null || t === currentTheme) return;
  const style = await loadStyle(t);
  if (t !== wantedTheme) return; // superseded while loading: the queued request applies
  currentTheme = t;
  // transformStyle is a setStyle option (a constructor option would be ignored, Pattern 13)
  mapInstance.setStyle(style, {
    transformStyle: (_prev, next) => {
      const sources = { ...next.sources };
      const layers = [...next.layers];
      for (const [id, def] of overlays) {
        Object.assign(sources, def.sources);
        layers.push(...overlayLayers(id, def, t));
      }
      return { ...next, sources, layers: topLast(layers) };
    },
  });
}
