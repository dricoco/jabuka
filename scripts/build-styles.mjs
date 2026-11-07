// Generate the two offline basemap styles (laptop, once; RESEARCH Pattern 10, Pitfalls 2-4).
//
//   node scripts/build-styles.mjs <@protomaps/basemaps dist/esm/index.js> <static dir>
//
// style-day.json:   layers("protomaps", namedFlavor("light"), {lang: "hr"}), sprite /sprites/light
// style-night.json: the "black" flavor mapped to a pure red channel (round(luminance x 0.55)),
//                   water/background #000000, earth #260000; every colour left in the layers is
//                   forced to the red channel too; icons removed (icon-image deleted, shields,
//                   one-way arrows and POIs dropped) because sprites carry grey/white light.
// Both: relative glyph/sprite/tile URLs (the client absolutizes them against location.origin),
// tiles from the core's /tiles endpoint, maxzoom 14, attribution without links (no "http" in the
// file, nothing is ever fetched from outside).
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [basemapsPath, outDir] = process.argv.slice(2);
if (!basemapsPath || !outDir) {
  console.error("usage: node build-styles.mjs <basemaps dist/esm/index.js> <static dir>");
  process.exit(2);
}
const B = await import(pathToFileURL(basemapsPath).href);

const GAIN = 0.55;
const hex2 = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
const lum = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

// Any CSS colour string -> pure red channel (same alpha); other strings unchanged.
function toRed(value) {
  if (typeof value !== "string") return value;
  const s = value.trim();
  let m = /^#([0-9a-f]{3})$/i.exec(s);
  if (m) {
    const [r, g, b] = [...m[1]].map((c) => parseInt(c + c, 16));
    return `#${hex2(lum(r, g, b) * GAIN)}0000`;
  }
  m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(s);
  if (m) {
    const n = parseInt(m[1], 16);
    // Already a pure red (the night flavor was converted once, then the layer paint built from
    // it goes through toRed again): keep it, or earth #260000 dims to #040000 on #000000 water
    // and the islands vanish at night.
    if ((n & 0xffff) === 0) return value;
    const v = hex2(lum((n >> 16) & 255, (n >> 8) & 255, n & 255) * GAIN);
    return m[2] ? `rgba(${parseInt(v, 16)},0,0,${(parseInt(m[2], 16) / 255).toFixed(3)})` : `#${v}0000`;
  }
  m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(s);
  if (m) {
    if (+m[2] === 0 && +m[3] === 0) return value; // already red (see above)
    const v = Math.round(lum(+m[1], +m[2], +m[3]) * GAIN);
    return m[4] !== undefined ? `rgba(${v},0,0,${m[4]})` : `#${hex2(v)}0000`;
  }
  if (/^(hsl|white|black|gray|grey)/i.test(s)) return s.toLowerCase() === "black" ? "#000000" : "#400000";
  return value;
}

const deepMap = (v, fn) =>
  Array.isArray(v)
    ? v.map((x) => deepMap(x, fn))
    : v && typeof v === "object"
      ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, deepMap(x, fn)]))
      : fn(v);

const night = deepMap(B.namedFlavor("black"), toRed);
Object.assign(night, { water: "#000000", background: "#000000", earth: "#260000" });

const DROP_AT_NIGHT = new Set(["roads_shields", "roads_oneway", "pois"]);

// The earth fill alone is a dim #260000: small islands disappear at night. Outline it with the
// same #600000 coastline the no-tiles fallback style draws (map.js coastlineStyle).
const COAST_AT_NIGHT = {
  id: "earth_coastline",
  type: "line",
  source: "protomaps",
  "source-layer": "earth",
  paint: { "line-color": "#600000", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.6, 12, 1.5] },
};

function nightLayers() {
  return B.layers("protomaps", night, { lang: "hr" })
    .flatMap((layer) => (layer.id === "earth" ? [layer, COAST_AT_NIGHT] : [layer]))
    .filter((layer) => !DROP_AT_NIGHT.has(layer.id))
    .map((layer) => {
      const out = { ...layer };
      if (out.layout) {
        out.layout = { ...out.layout };
        delete out.layout["icon-image"];
        out.layout = deepMap(out.layout, toRed);
      }
      if (out.paint) out.paint = deepMap(out.paint, toRed);
      return out;
    });
}

const style = (name, layers, sprite) => ({
  version: 8,
  name,
  glyphs: "/glyphs/{fontstack}/{range}.pbf",
  sprite: `/sprites/${sprite}`,
  sources: {
    protomaps: {
      type: "vector",
      tiles: ["/tiles/{z}/{x}/{y}.mvt"],
      minzoom: 0,
      maxzoom: 14,
      attribution: "Protomaps © OpenStreetMap",
    },
  },
  layers,
});

const day = style("jabuka-day", B.layers("protomaps", B.namedFlavor("light"), { lang: "hr" }), "light");
const dark = style("jabuka-night", nightLayers(), "dark");
writeFileSync(`${outDir}/style-day.json`, JSON.stringify(day, null, 1) + "\n");
writeFileSync(`${outDir}/style-night.json`, JSON.stringify(dark, null, 1) + "\n");
console.log(`build-styles: day ${day.layers.length} layers, night ${dark.layers.length} layers`);
