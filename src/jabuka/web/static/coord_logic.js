// Pure (DOM-free) coordinate parsing and formatting for the Carte tab (quick 003), node-tested
// from tests/test_coord_logic.py. A race committee gives an extra mark by VHF in degrees and
// decimal minutes ("43°45,2'N 15°40,1'E"); the tablet keyboard may be a numeric pad.
//
//   parseCoord(text, axis)        axis "lat" | "lon" -> {ok: true, value} | {ok: false, error}
//                                 error: empty | format | minutes | seconds | range | hemisphere
//     - decimal comma or point; hemisphere letter before or after (N/S for lat, E/W or the
//       French O for lon), or a leading "-"; no letter = N / E
//     - fields separated by spaces or ° º * ' ′ ’ " ″ :
//     - 1 number = decimal degrees, 2 = degrees + decimal minutes, 3 = degrees minutes seconds
//     - digits with exactly two "."/"," (43.45.2, 43,45,2): the first splits degrees / minutes
//   dmParts(value, digits)        {deg, min, neg} with the minutes rounded to digits, carrying
//                                 59.9996' to the next degree (never 60,000')
//   formatDM(value, axis, {digits = 3, sep = "."})   "43°45,200' N"
//   RACE_AREA, SERVER_LIMITS      {south, north, west, east}
//   areaFrom(maxBounds)           the map's [[w, s], [e, n]] clipped to SERVER_LIMITS
//   inArea(lat, lon, area)
//   checkPosition(latText, lonText, area)
//                                 {lat, lon, ok, latError, lonError, areaError} (values null
//                                 when the field does not parse)

// The race area the map is clamped to (map.js BOUNDS). /racepack/info "bounds" is only the tile
// extent, smaller than the area a mark may sit in.
export const RACE_AREA = { south: 42.7, north: 44.1, west: 14.9, east: 16.4 };
// What POST /api/marks and PATCH /api/marks/{id} accept (core/course_api.py MarkIn / MarkPatch).
export const SERVER_LIMITS = { south: 42.0, north: 45.0, west: 14.0, east: 17.0 };

const HEMI = { lat: { pos: "N", neg: "S" }, lon: { pos: "E", neg: "W" } };
const SEPARATORS = /[\s°º*'′’"″:]+/g;
const NUMBER = /^\d+(?:\.\d+)?$/;
const INTEGER = /^\d+$/;
const fail = (error) => ({ ok: false, error });

export function parseCoord(text, axis) {
  const h = HEMI[axis];
  if (!h) throw new Error(`axis ${axis}`);
  let s = String(text ?? "")
    .trim()
    .toUpperCase();
  if (!s) return fail("empty");
  let sign = 1;
  let letter = null;
  const lead = s.match(/^([NSEWO])\s*/);
  if (lead) {
    letter = lead[1];
    s = s.slice(lead[0].length);
  }
  const trail = s.match(/\s*([NSEWO])$/);
  if (trail) {
    if (letter) return fail("format");
    letter = trail[1];
    s = s.slice(0, s.length - trail[0].length);
  }
  if (letter === "O") letter = "W"; // ouest
  if (letter) {
    if (letter === h.neg) sign = -1;
    else if (letter !== h.pos) return fail("hemisphere");
  }
  s = s.trim();
  if (s.startsWith("-")) {
    if (letter) return fail("format");
    sign = -1;
    s = s.slice(1).trim();
  } else if (s.startsWith("+")) {
    s = s.slice(1).trim();
  }
  if (!s) return fail("format");
  // a numeric keypad without a space key: "43.45.2" / "43,45,2" = 43° 45.2'
  const keypad = s.match(/^(\d+)[.,](\d+[.,]\d+)$/);
  if (keypad) s = `${keypad[1]} ${keypad[2]}`;
  const fields = s.replace(/,/g, ".").replace(SEPARATORS, " ").trim().split(" ");
  if (fields.length > 3 || fields.some((f) => !NUMBER.test(f))) return fail("format");
  const nums = fields.map(Number);
  if (fields.length >= 2 && !INTEGER.test(fields[0])) return fail("format");
  if (fields.length === 3 && !INTEGER.test(fields[1])) return fail("format");
  if (fields.length >= 2 && nums[1] >= 60) return fail("minutes");
  if (fields.length === 3 && nums[2] >= 60) return fail("seconds");
  const deg = nums[0] + (nums[1] ?? 0) / 60 + (nums[2] ?? 0) / 3600;
  if (deg > (axis === "lat" ? 90 : 180)) return fail("range");
  return { ok: true, value: sign * deg };
}

export function dmParts(value, digits = 3) {
  const neg = value < 0;
  const a = Math.abs(value);
  let deg = Math.floor(a);
  const scale = 10 ** digits;
  let min = Math.round((a - deg) * 60 * scale) / scale;
  if (min >= 60) {
    deg += 1;
    min = 0;
  }
  return { deg, min, neg };
}

export function formatDM(value, axis, { digits = 3, sep = "." } = {}) {
  const h = HEMI[axis];
  if (!h || typeof value !== "number" || !Number.isFinite(value)) return "";
  const { deg, min, neg } = dmParts(value, digits);
  let m = min.toFixed(digits);
  if (min < 10) m = `0${m}`;
  if (sep !== ".") m = m.replace(".", sep);
  return `${deg}°${m}' ${neg ? h.neg : h.pos}`;
}

export function areaFrom(maxBounds) {
  const L = SERVER_LIMITS;
  let a = RACE_AREA;
  if (Array.isArray(maxBounds) && maxBounds.length === 2) {
    const [[w, s], [e, n]] = maxBounds;
    if ([w, s, e, n].every((x) => typeof x === "number" && Number.isFinite(x)) && s < n && w < e) {
      a = { south: s, north: n, west: w, east: e };
    }
  }
  const out = {
    south: Math.max(a.south, L.south),
    north: Math.min(a.north, L.north),
    west: Math.max(a.west, L.west),
    east: Math.min(a.east, L.east),
  };
  return out.south < out.north && out.west < out.east ? out : { ...RACE_AREA };
}

export function inArea(lat, lon, area = RACE_AREA) {
  return lat >= area.south && lat <= area.north && lon >= area.west && lon <= area.east;
}

export function checkPosition(latText, lonText, area = RACE_AREA) {
  const la = parseCoord(latText, "lat");
  const lo = parseCoord(lonText, "lon");
  const lat = la.ok ? la.value : null;
  const lon = lo.ok ? lo.value : null;
  const both = la.ok && lo.ok;
  const areaError = both && !inArea(lat, lon, area);
  return {
    lat,
    lon,
    ok: both && !areaError,
    latError: la.ok ? null : la.error,
    lonError: lo.ok ? null : lo.error,
    areaError,
  };
}
