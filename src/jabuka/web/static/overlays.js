// Helm overlays on the shared map (HELM-01), registered through map.js so they survive every
// theme switch (setTheme re-adds them with their last data):
//   "helm-course": the whole course line, every course mark with its name and rounding radius
//                  (circle outline: port dashed, starboard solid, none dotted), the active mark
//                  emphasised. Hidden on the Carte tab, where the "carte" overlay (02-04) draws it.
//   "helm-live":   the two laylines to the active mark (starboard solid, port dashed), the rounding
//                  anchor, the boat and a 0.3 nm heading line.
//   "seamarks":    /racepack/seamarks.geojson (lights, beacons, buoys, hazards), names from zoom 11.
// Day colours, or red shades only at night (HELM-03, Pitfall 4). Labels use text-field only (no
// HTML, T-02-05-01). Sources are prefixed "helm-" except the 02-01 names (laylines, anchor, mark,
// boat) the smoke test reads, so the 02-04 "carte" sources never collide with them.
import { ensureMap, registerOverlay, setOverlayData, setOverlayVisible } from "./map.js";

const EMPTY = { type: "FeatureCollection", features: [] };
const HEADING_LINE_NM = 0.3;
const CIRCLE_POINTS = 48;
const DEG = Math.PI / 180;

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const fc = (features) => ({ type: "FeatureCollection", features });
const feature = (geometry, properties = {}) => ({ type: "Feature", properties, geometry });
const pt = (lon, lat) => ({ type: "Point", coordinates: [lon, lat] });

// Point at distance nm and true bearing deg from (lat, lon) (flat-earth, fine below a few nm).
export function offsetNm(lat, lon, bearingDeg, nm) {
  const b = bearingDeg * DEG;
  const dLat = (nm / 60) * Math.cos(b);
  const dLon = ((nm / 60) * Math.sin(b)) / Math.cos(lat * DEG);
  return [lon + dLon, lat + dLat];
}

// Closed ring of n points at radius nm around (lat, lon).
export function circleRing(lat, lon, nm, n = CIRCLE_POINTS) {
  const ring = [];
  for (let i = 0; i < n; i++) ring.push(offsetNm(lat, lon, (360 * i) / n, nm));
  ring.push(ring[0]);
  return ring;
}

// GeoJSON of the whole course from GET /api/course (the "course" bus event).
export function courseData(course) {
  const out = { line: EMPTY, marks: EMPTY, radius: EMPTY };
  if (!course || !Array.isArray(course.seq) || !course.marks) return out;
  const coords = [];
  const marks = [];
  const radius = [];
  const seen = new Set();
  course.seq.forEach((leg, i) => {
    const m = course.marks[leg.mark_id];
    if (!m || !isNum(m.lat) || !isNum(m.lon)) return;
    coords.push([m.lon, m.lat]);
    const active = i === course.active_idx;
    if (!seen.has(leg.mark_id) || active) {
      seen.add(leg.mark_id);
      marks.push(feature(pt(m.lon, m.lat), { name: String(m.name), idx: i, active }));
    }
    if (isNum(leg.radius_nm) && leg.radius_nm > 0) {
      radius.push(
        feature(
          { type: "LineString", coordinates: circleRing(m.lat, m.lon, leg.radius_nm) },
          { side: leg.side ?? "none", idx: i, active },
        ),
      );
    }
  });
  out.line = coords.length >= 2 ? fc([feature({ type: "LineString", coordinates: coords })]) : EMPTY;
  out.marks = fc(marks);
  out.radius = fc(radius);
  return out;
}

// Heading used to draw (and, in course-up, to rotate) the boat: compass heading, or COG when the
// server says the heading comes from COG.
export function boatHeading(boat) {
  if (!boat) return null;
  if (boat.heading_src === "cog" && isNum(boat.cog_t)) return boat.cog_t;
  if (isNum(boat.hdg_t)) return boat.hdg_t;
  return isNum(boat.cog_t) ? boat.cog_t : null;
}

// GeoJSON of the live layer from one nav message.
export function liveData(nav) {
  const mark = nav?.mark;
  const boat = nav?.boat;
  const hasBoat = boat && isNum(boat.lat) && isNum(boat.lon);
  const hdg = boatHeading(boat);
  return {
    laylines: nav?.layline?.geojson ?? EMPTY,
    mark: mark && isNum(mark.lat) && isNum(mark.lon) ? fc([feature(pt(mark.lon, mark.lat), { name: String(mark.name) })]) : EMPTY,
    anchor: mark && isNum(mark.anchor_lat) && isNum(mark.anchor_lon) ? fc([feature(pt(mark.anchor_lon, mark.anchor_lat))]) : EMPTY,
    boat: hasBoat ? fc([feature(pt(boat.lon, boat.lat))]) : EMPTY,
    "helm-heading":
      hasBoat && isNum(hdg)
        ? fc([
            feature({
              type: "LineString",
              coordinates: [[boat.lon, boat.lat], offsetNm(boat.lat, boat.lon, hdg, HEADING_LINE_NM)],
            }),
          ])
        : EMPTY,
  };
}

// Seamark category from the OSM seamark:type (and light) tags.
export function seamarkCategory(props) {
  const t = String(props?.["seamark:type"] ?? "");
  if (t.startsWith("buoy")) return "buoy";
  if (t.startsWith("beacon")) return "beacon";
  if (t.startsWith("light")) return "light";
  if (/rock|wreck|obstruction|danger|reef/.test(t)) return "hazard";
  if (props?.light || props?.["seamark:light:character"]) return "light";
  return "other";
}

export function seamarkData(geojson) {
  const features = (geojson?.features ?? [])
    .filter((f) => f?.geometry?.type === "Point")
    .map((f) => feature(f.geometry, { name: String(f.properties?.name ?? ""), cat: seamarkCategory(f.properties) }));
  return fc(features);
}

// -- colours ------------------------------------------------------------------------------------
const COLORS = {
  day: {
    course: "#404040",
    radius: "#c00000",
    marks: "#c00000",
    active: "#c00000",
    layline: "#202020",
    anchor: "#c00000",
    boat: "#0050b3",
    heading: "#0050b3",
    text: "#000000",
    halo: "#ffffff",
    light: "#d4a000",
    beacon: "#006000",
    buoy: "#c05000",
    hazard: "#800080",
    other: "#606060",
  },
  night: {
    course: "#600000",
    radius: "#b00000",
    marks: "#b00000",
    active: "#ff0000",
    layline: "#ff0000",
    anchor: "#b00000",
    boat: "#ff0000",
    heading: "#ff0000",
    text: "#ff0000",
    halo: "#000000",
    light: "#b00000",
    beacon: "#800000",
    buoy: "#800000",
    hazard: "#ff0000",
    other: "#600000",
  },
};
const palette = (theme) => COLORS[theme] ?? COLORS.day;
const FONT = ["Noto Sans Medium"];

export function courseLayers(theme) {
  const c = palette(theme);
  const radius = (side, dash) => ({
    id: `helm-course-radius-${side}`,
    type: "line",
    source: "helm-course-radius",
    filter: ["==", ["get", "side"], side],
    paint: {
      "line-color": c.radius,
      "line-width": ["case", ["get", "active"], 2.5, 1.5],
      ...(dash ? { "line-dasharray": dash } : {}),
    },
  });
  return [
    {
      id: "helm-course-line",
      type: "line",
      source: "helm-course-line",
      paint: { "line-color": c.course, "line-width": 1.5, "line-dasharray": [6, 3] },
    },
    radius("port", [3, 2]),
    radius("stbd", null),
    radius("none", [1, 3]),
    {
      id: "helm-course-marks",
      type: "circle",
      source: "helm-course-marks",
      paint: { "circle-radius": 4, "circle-color": c.marks, "circle-stroke-width": 1, "circle-stroke-color": c.halo },
    },
    {
      id: "helm-course-marks-label",
      type: "symbol",
      source: "helm-course-marks",
      filter: ["!", ["get", "active"]],
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT,
        "text-size": 12,
        "text-offset": [0, 1.1],
        "text-anchor": "top",
      },
      paint: { "text-color": c.text, "text-halo-color": c.halo, "text-halo-width": 1.2 },
    },
    {
      id: "helm-mark",
      type: "circle",
      source: "mark",
      paint: { "circle-radius": 8, "circle-color": c.active, "circle-stroke-width": 2, "circle-stroke-color": c.halo },
    },
    {
      id: "helm-mark-label",
      type: "symbol",
      source: "mark",
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT,
        "text-size": 15,
        "text-offset": [0, 1.3],
        "text-anchor": "top",
      },
      paint: { "text-color": c.text, "text-halo-color": c.halo, "text-halo-width": 1.5 },
    },
  ];
}

export function liveLayers(theme) {
  const c = palette(theme);
  return [
    {
      id: "helm-laylines-stbd",
      type: "line",
      source: "laylines",
      filter: ["!=", ["get", "tack"], "port"],
      paint: { "line-color": c.layline, "line-width": 2.5 },
    },
    {
      id: "helm-laylines-port",
      type: "line",
      source: "laylines",
      filter: ["==", ["get", "tack"], "port"],
      paint: { "line-color": c.layline, "line-width": 2.5, "line-dasharray": [4, 2] },
    },
    {
      id: "helm-anchor",
      type: "circle",
      source: "anchor",
      paint: { "circle-radius": 4, "circle-color": c.anchor, "circle-opacity": 0.7 },
    },
    {
      id: "helm-heading",
      type: "line",
      source: "helm-heading",
      paint: { "line-color": c.heading, "line-width": 3 },
    },
    {
      id: "helm-boat",
      type: "circle",
      source: "boat",
      paint: { "circle-radius": 7, "circle-color": c.boat, "circle-stroke-width": 2, "circle-stroke-color": c.halo },
    },
  ];
}

export function seamarkLayers(theme) {
  const c = palette(theme);
  const byCat = ["match", ["get", "cat"], "light", c.light, "beacon", c.beacon, "buoy", c.buoy, "hazard", c.hazard, c.other];
  return [
    {
      id: "seamarks-points",
      type: "circle",
      source: "seamarks",
      paint: {
        "circle-radius": ["match", ["get", "cat"], "light", 5, "hazard", 5, 4],
        "circle-color": byCat,
        "circle-stroke-width": 1,
        "circle-stroke-color": c.halo,
      },
    },
    {
      id: "seamarks-label",
      type: "symbol",
      source: "seamarks",
      minzoom: 11,
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT,
        "text-size": 11,
        "text-offset": [0, 1],
        "text-anchor": "top",
        "text-optional": true,
      },
      paint: { "text-color": c.text, "text-halo-color": c.halo, "text-halo-width": 1 },
    },
  ];
}

// -- mount --------------------------------------------------------------------------------------
async function loadSeamarks() {
  if (!globalThis.jabuka?.racepack?.seamarks) return EMPTY;
  try {
    const res = await fetch("/racepack/seamarks.geojson");
    if (!res.ok) return EMPTY;
    return seamarkData(await res.json());
  } catch (e) {
    console.warn("seamarks", e);
    return EMPTY;
  }
}

export async function mount(ctx) {
  let nav = ctx.latest?.("nav") ?? null;
  let course = ctx.latest?.("course") ?? null;
  let tab = ctx.latest?.("tab") ?? "barre";
  let ready = false;

  const applyLive = () => {
    if (!ready || !nav) return;
    for (const [name, data] of Object.entries(liveData(nav))) setOverlayData(name, data);
  };
  const applyCourse = () => {
    if (!ready || !course) return;
    const d = courseData(course);
    setOverlayData("helm-course-line", d.line);
    setOverlayData("helm-course-marks", d.marks);
    setOverlayData("helm-course-radius", d.radius);
  };
  const applyTab = () => {
    if (ready) setOverlayVisible("helm-course", tab !== "carte");
  };

  ctx.bus.addEventListener("nav", (ev) => {
    nav = ev.detail;
    applyLive();
  });
  ctx.bus.addEventListener("course", (ev) => {
    course = ev.detail;
    applyCourse();
  });
  ctx.bus.addEventListener("tab", (ev) => {
    tab = ev.detail;
    applyTab();
  });

  try {
    await ensureMap(document.getElementById("map"));
  } catch {
    return; // no map on this tablet: app.js shows "CARTE INDISPONIBLE", the numbers keep going
  }
  const src = () => ({ type: "geojson", data: EMPTY });
  registerOverlay("seamarks", { sources: { seamarks: src() }, layers: seamarkLayers });
  registerOverlay("helm-course", {
    sources: {
      "helm-course-line": src(),
      "helm-course-radius": src(),
      "helm-course-marks": src(),
      mark: src(),
    },
    layers: courseLayers,
  });
  registerOverlay("helm-live", {
    sources: { laylines: src(), anchor: src(), "helm-heading": src(), boat: src() },
    layers: liveLayers,
  });
  ready = true;
  applyCourse();
  applyLive();
  applyTab();
  setOverlayData("seamarks", await loadSeamarks());
}
