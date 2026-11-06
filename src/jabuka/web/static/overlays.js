// Helm overlay on the map: laylines, the active mark (and its rounding anchor) and the boat, fed by
// every "nav" bus event. Day: dark lines; night: red only. Plan 02-05 extends this file (boat
// arrow, course-up, seamarks).
import { ensureMap, registerOverlay, setOverlayData } from "./map.js";

const EMPTY = { type: "FeatureCollection", features: [] };

const point = (lon, lat, props = {}) => ({
  type: "FeatureCollection",
  features: [{ type: "Feature", properties: props, geometry: { type: "Point", coordinates: [lon, lat] } }],
});

const isNum = (x) => typeof x === "number" && Number.isFinite(x);

const COLORS = {
  day: { layline: "#202020", mark: "#c00000", anchor: "#c00000", boat: "#0050b3", text: "#000000", halo: "#ffffff" },
  night: { layline: "#ff0000", mark: "#ff0000", anchor: "#b00000", boat: "#ff0000", text: "#ff0000", halo: "#000000" },
};

function layers(theme) {
  const c = COLORS[theme] ?? COLORS.day;
  return [
    {
      id: "helm-laylines",
      type: "line",
      source: "laylines",
      paint: { "line-color": c.layline, "line-width": 2, "line-dasharray": [4, 2] },
    },
    {
      id: "helm-anchor",
      type: "circle",
      source: "anchor",
      paint: { "circle-radius": 4, "circle-color": c.anchor, "circle-opacity": 0.6 },
    },
    {
      id: "helm-mark",
      type: "circle",
      source: "mark",
      paint: { "circle-radius": 7, "circle-color": c.mark, "circle-stroke-width": 2, "circle-stroke-color": c.halo },
    },
    {
      id: "helm-mark-label",
      type: "symbol",
      source: "mark",
      layout: {
        "text-field": ["get", "name"],
        "text-font": ["Noto Sans Medium"],
        "text-size": 14,
        "text-offset": [0, 1.3],
        "text-anchor": "top",
      },
      paint: { "text-color": c.text, "text-halo-color": c.halo, "text-halo-width": 1.5 },
    },
    {
      id: "helm-boat",
      type: "circle",
      source: "boat",
      paint: { "circle-radius": 6, "circle-color": c.boat, "circle-stroke-width": 2, "circle-stroke-color": c.halo },
    },
  ];
}

export function overlayData(nav) {
  const mark = nav?.mark;
  const boat = nav?.boat;
  return {
    laylines: nav?.layline?.geojson ?? EMPTY,
    mark: mark && isNum(mark.lat) && isNum(mark.lon) ? point(mark.lon, mark.lat, { name: mark.name }) : EMPTY,
    anchor:
      mark && isNum(mark.anchor_lat) && isNum(mark.anchor_lon) ? point(mark.anchor_lon, mark.anchor_lat) : EMPTY,
    boat: boat && isNum(boat.lat) && isNum(boat.lon) ? point(boat.lon, boat.lat) : EMPTY,
  };
}

export async function mount(ctx) {
  let last = null;
  let ready = false;
  const apply = () => {
    if (!ready || !last) return;
    for (const [name, data] of Object.entries(overlayData(last))) setOverlayData(name, data);
  };
  ctx.bus.addEventListener("nav", (ev) => {
    last = ev.detail;
    apply();
  });
  last = ctx.latest?.("nav") ?? null;
  try {
    await ensureMap(document.getElementById("map"));
  } catch {
    return; // no map on this tablet: app.js shows "CARTE INDISPONIBLE", the numbers keep going
  }
  registerOverlay("helm", {
    sources: {
      laylines: { type: "geojson", data: EMPTY },
      anchor: { type: "geojson", data: EMPTY },
      mark: { type: "geojson", data: EMPTY },
      boat: { type: "geojson", data: EMPTY },
    },
    layers,
  });
  ready = true;
  apply();
}
