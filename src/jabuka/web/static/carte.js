// Carte tab (CRSE-01..04) and the global advance banner (CRSE-03).
//
// - Course A / B in one tap, previous / next mark, the course list (tap a leg to edit it), the
//   "Côtés à confirmer (IC)" warning with "Côtés confirmés".
// - Map editing on the shared map (map.js overlay "carte", shown only on this tab): tap open water
//   to add a mark (a tap on the "earth" layer first asks "Marque à terre ?"), drag a mark to move
//   it (one PATCH on release), tap a mark for its sheet: name, side, radius, Monter / Descendre,
//   Supprimer (confirmed), "Finir ici", "Rendre active".
// - Typed coordinates (quick 003, coord_logic.js): the add sheet and the mark sheet edit the
//   position in degrees + decimal minutes (VHF format), validated live against the race area (RACE_AREA,
//   not the padded map bounds); a valid entry shows the pending marker and eases the map there; the land
//   check runs on typed positions before "Ajouter" / "Déplacer ici". "＋ Marque (coordonnées)"
//   opens the add sheet at the boat (else the map centre). The list shows every mark's position.
// - Every write carries base_version; a 409 shows "Parcours modifié ailleurs — rechargé" and
//   loads the current course from the 409 body.
// - #banner (every tab): "Marque suivante : <nom>" with a 48 px "Annuler" while the nav message's
//   t_mono is before undo_until_s; "ARRIVÉE — <nom>" without Annuler.
// DOM built with textContent only: mark names are data typed on another tablet (T-02-04-02).
// Texts in the tablet's language (i18n.js); the core's banner text goes through trServer.
import { areaFrom, checkPosition, formatDM, inArea } from "./coord_logic.js";
import { fmtDec, t, trServer } from "./i18n.js";
import { ensureMap, mapReady, registerOverlay, setOverlayData, setOverlayVisible } from "./map.js";

const sideWord = (side) => (side === "port" || side === "stbd" ? t(`tack.${side}`) : "");
const sides = () => ["port", "stbd", "none"].map((v) => [v, t(`side.${v}`)]);
const RADIUS_STEP = 0.05;
const RADIUS_MAX = 3;
const DRAG_START_PX = 6;
const EMPTY = { type: "FeatureCollection", features: [] };
const OVERLAY = "carte";
const SRC = { marks: "carte-marks", zones: "carte-zones", line: "carte-line", pending: "carte-pending" };

const COLORS = {
  day: {
    line: "#0050b3",
    todo: "#0050b3",
    active: "#c00000",
    done: "#7a7a7a",
    finish: "#000000",
    zone: "#0050b3",
    text: "#000000",
    halo: "#ffffff",
  },
  night: {
    line: "#a00000",
    todo: "#c00000",
    active: "#ff0000",
    done: "#600000",
    finish: "#ff0000",
    zone: "#800000",
    text: "#ff0000",
    halo: "#000000",
  },
};

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  if (text !== undefined) e.textContent = text;
  return e;
}

function button(text, attrs = {}, onClick) {
  const b = el("button", { type: "button", class: "big", ...attrs }, text);
  if (onClick) b.addEventListener("click", onClick);
  return b;
}

const round6 = (x) => Math.round(x * 1e6) / 1e6;
const roundR = (x) => Math.round(x * 100) / 100;
const posKey = (lat, lon) => `${round6(lat)},${round6(lon)}`;
const PREVIEW_MS = 350;
const LAND_WAIT_MS = 3000;

// Coordinates in degrees + decimal minutes, decimal comma in fr / sl (fmtDec's separator).
const decSep = () => fmtDec(0.5, 1).charAt(1);
const fmtLat = (v, digits = 3) => formatDM(v, "lat", { digits, sep: decSep() });
const fmtLon = (v, digits = 3) => formatDM(v, "lon", { digits, sep: decSep() });
export const fmtPos = (lat, lon) => `${fmtLat(lat)}  ${fmtLon(lon)}`;
const ERR_KEYS = {
  empty: "carte.errEmpty",
  format: "carte.errFormat",
  minutes: "carte.errMinutes",
  seconds: "carte.errSeconds",
  range: "carte.errRange",
};
function coordError(code, axis) {
  if (!code) return "";
  if (code === "hemisphere") return t("carte.errHemi", { h: axis === "lat" ? "N / S" : "E / W" });
  return t(ERR_KEYS[code] ?? "carte.errFormat");
}
const areaText = (a) =>
  t("carte.errArea", { s: fmtLat(a.south, 0), n: fmtLat(a.north, 0), w: fmtLon(a.west, 0), e: fmtLon(a.east, 0) });

// -- pure helpers (course JSON -> GeoJSON) ------------------------------------------------------
export function lastIdx(course) {
  return course.finish_idx ?? course.seq.length - 1;
}

export function circle(lat, lon, radiusNm, n = 48) {
  const k = Math.cos((lat * Math.PI) / 180);
  const ring = [];
  for (let i = 0; i <= n; i++) {
    const t = (2 * Math.PI * i) / n;
    ring.push([lon + (radiusNm * Math.sin(t)) / (60 * k), lat + (radiusNm * Math.cos(t)) / 60]);
  }
  return ring;
}

// The leg a tap on a mark edits: the first one still to sail, else the last one using it.
export function legFor(course, markId) {
  const idxs = course.seq.map((l, i) => (l.mark_id === markId ? i : -1)).filter((i) => i >= 0);
  const ahead = idxs.find((i) => i >= 1 && i >= course.active_idx && i <= lastIdx(course));
  if (ahead !== undefined) return ahead;
  const any = idxs.filter((i) => i >= 1);
  return any.length ? any[any.length - 1] : (idxs[0] ?? -1);
}

function legState(course, i) {
  if (i === course.active_idx && !course.finished) return "active";
  if (i === lastIdx(course)) return "finish";
  if (i < course.active_idx) return "done";
  return "todo";
}

export function courseGeo(course, moved = null) {
  if (!course) return { marks: EMPTY, zones: EMPTY, line: EMPTY };
  const pos = (id) => {
    if (moved && moved.id === id) return [moved.lon, moved.lat];
    const m = course.marks[id];
    return m ? [m.lon, m.lat] : null;
  };
  const marks = [];
  for (const id of new Set(course.seq.map((l) => l.mark_id))) {
    const p = pos(id);
    if (!p) continue;
    const leg = legFor(course, id);
    marks.push({
      type: "Feature",
      properties: { id, name: course.marks[id].name, leg, state: leg >= 0 ? legState(course, leg) : "todo" },
      geometry: { type: "Point", coordinates: p },
    });
  }
  const zones = [];
  const coords = [];
  course.seq.forEach((leg, i) => {
    const p = pos(leg.mark_id);
    if (!p || i > lastIdx(course)) return;
    coords.push(p);
    if (i >= 1 && leg.radius_nm > 0) {
      zones.push({
        type: "Feature",
        properties: { idx: i, state: legState(course, i) },
        geometry: { type: "Polygon", coordinates: [circle(p[1], p[0], leg.radius_nm)] },
      });
    }
  });
  const fc = (features) => ({ type: "FeatureCollection", features });
  const line =
    coords.length >= 2 ? fc([{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }]) : EMPTY;
  return { marks: fc(marks), zones: fc(zones), line };
}

// Banner view from a nav message: {text, undo} or null (text in the tablet's language).
export function bannerView(nav) {
  const b = nav?.course?.banner;
  if (!b || !b.text) return null;
  const undo =
    b.kind !== "finish" &&
    Boolean(b.token) &&
    typeof b.undo_until_s === "number" &&
    typeof nav.t_mono === "number" &&
    nav.t_mono < b.undo_until_s;
  return { text: trServer(String(b.text).replace(/\s*—\s*Annuler\s*$/, "")), undo, token: b.token ?? null };
}

function layers(theme) {
  const c = COLORS[theme] ?? COLORS.day;
  const byState = ["match", ["get", "state"], "active", c.active, "done", c.done, "finish", c.finish, c.todo];
  return [
    { id: "carte-zones-fill", type: "fill", source: SRC.zones, paint: { "fill-color": byState, "fill-opacity": 0.12 } },
    { id: "carte-zones-line", type: "line", source: SRC.zones, paint: { "line-color": byState, "line-width": 1.5 } },
    {
      id: "carte-line",
      type: "line",
      source: SRC.line,
      paint: { "line-color": c.line, "line-width": 2, "line-dasharray": [2, 2], "line-opacity": 0.8 },
    },
    {
      id: "carte-pending",
      type: "circle",
      source: SRC.pending,
      paint: { "circle-radius": 8, "circle-color": c.active, "circle-opacity": 0.5 },
    },
    {
      id: "carte-marks",
      type: "circle",
      source: SRC.marks,
      paint: {
        "circle-radius": 10,
        "circle-color": byState,
        "circle-stroke-width": 2,
        "circle-stroke-color": c.halo,
      },
    },
    {
      id: "carte-marks-label",
      type: "symbol",
      source: SRC.marks,
      layout: {
        "text-field": ["get", "name"],
        "text-font": ["Noto Sans Medium"],
        "text-size": 15,
        "text-offset": [0, -1.4],
        "text-anchor": "bottom",
      },
      paint: { "text-color": c.text, "text-halo-color": c.halo, "text-halo-width": 1.5 },
    },
  ];
}

// -- module -------------------------------------------------------------------------------------
export function mount(ctx) {
  const root = ctx.section;
  if (!root) return;
  let course = null;
  let busy = false;
  let tab = ctx.latest?.("tab") ?? "barre";
  let map = null;
  let drag = null;
  let suppressClickUntil = 0;
  let sheetFor = null; // {kind: "mark", markId, idx, draft} | {kind: "add"|"land", ...}
  let locked = document.body.classList.contains("locked"); // then the "lock" bus events
  let previewTimer = null;

  // -- side panel ------------------------------------------------------------------------------
  const panel = el("div", { class: "carte-panel" });
  const tpl = el("div", { class: "carte-row" });
  const btnA = button(t("carte.template", { x: "A" }), { "data-template": "A" });
  const btnB = button(t("carte.template", { x: "B" }), { "data-template": "B" });
  tpl.append(btnA, btnB);
  const navRow = el("div", { class: "carte-row" });
  const btnPrev = button(t("carte.prev"), { id: "course-prev" });
  const btnNext = button(t("carte.next"), { id: "course-next" });
  navRow.append(btnPrev, btnNext);
  const warn = el("div", { class: "carte-warn", id: "sides-warning" });
  const warnText = el("span", {}, t("carte.sidesWarn"));
  const btnSides = button(t("carte.sidesOk"), { id: "sides-confirm" });
  warn.append(warnText, btnSides);
  const status = el("div", { class: "carte-status", id: "carte-status", "aria-live": "polite" });
  const hint = el("div", { class: "carte-hint" }, t("carte.hint"));
  const btnCoords = button(t("carte.coordButton"), { id: "mark-coords" });
  const list = el("ol", { class: "carte-list", id: "course-list", start: "0" });
  panel.append(tpl, navRow, warn, status, hint, btnCoords, list);
  const sheet = el("div", { class: "carte-sheet", id: "carte-sheet", role: "dialog" });
  sheet.hidden = true;
  root.replaceChildren(panel, sheet);

  function renderList() {
    if (!course) return;
    btnA.classList.toggle("active", course.template === "A");
    btnB.classList.toggle("active", course.template === "B");
    warn.hidden = Boolean(course.sides_confirmed);
    const last = lastIdx(course);
    const items = course.seq.map((leg, i) => {
      const mark = course.marks[leg.mark_id];
      const li = el("li", { "data-idx": String(i) });
      const cls = [];
      if (i === course.active_idx && !course.finished) cls.push("active");
      else if (i < course.active_idx) cls.push("done");
      if (i > last) cls.push("cut");
      li.className = cls.join(" ");
      const name = el("span", { class: "name" }, mark ? mark.name : leg.mark_id);
      const side = sideWord(leg.side);
      const radius = `${fmtDec(leg.radius_nm, 2)} nm`;
      const meta = el("span", { class: "meta" }, side ? `${side} · ${radius}` : radius);
      li.append(name, meta);
      if (mark) li.append(el("span", { class: "coord" }, fmtPos(mark.lat, mark.lon)));
      if (i === 0) li.append(el("span", { class: "tag" }, t("carte.start")));
      if (i === last) li.append(el("span", { class: "tag finish" }, t("carte.finish")));
      li.addEventListener("click", () => openMarkSheet(leg.mark_id, i));
      return li;
    });
    list.replaceChildren(...items);
  }

  function renderMap() {
    if (!map) return;
    const moved = drag && drag.moved && drag.lngLat ? { id: drag.id, lat: drag.lngLat.lat, lon: drag.lngLat.lng } : null;
    const g = courseGeo(course, moved);
    setOverlayData(SRC.marks, g.marks);
    setOverlayData(SRC.zones, g.zones);
    setOverlayData(SRC.line, g.line);
  }

  function setPending(lat, lon) {
    if (!map) return;
    setOverlayData(
      SRC.pending,
      lat === null
        ? EMPTY
        : { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [lon, lat] } }] },
    );
  }

  function render() {
    renderList();
    renderMap();
    if (sheetFor && sheetFor.kind === "mark") openMarkSheet(sheetFor.markId, sheetFor.idx, true);
  }

  async function act(fn, after) {
    if (busy || locked) return false;
    busy = true;
    status.textContent = "";
    try {
      course = await fn();
      if (after) after(course);
      render();
      return true;
    } catch (e) {
      if (e.status === 409 && e.body && e.body.seq) {
        course = e.body;
        status.textContent = t("carte.conflict");
        closeSheet();
        render();
      } else if (e.status === 422) {
        status.textContent = t("carte.refused");
      } else {
        status.textContent = t("common.failed", { s: e.status ?? e });
      }
      return false;
    } finally {
      busy = false;
    }
  }

  const version = () => (course ? course.version : null);

  // WR-05: a template change rebuilds the course (custom marks and leg edits dropped), so it
  // takes two taps like "Supprimer"; the template already in use is a no-op.
  const tplLabel = (b) => t("carte.template", { x: b.dataset.template });
  let tplTimer = null;
  const tplReset = () => {
    clearTimeout(tplTimer);
    for (const b of [btnA, btnB]) {
      delete b.dataset.confirm;
      b.textContent = tplLabel(b);
    }
  };
  for (const b of [btnA, btnB]) {
    b.addEventListener("click", () => {
      if (!course) return;
      if (course.template === b.dataset.template) {
        tplReset();
        status.textContent = t("carte.alreadyActive", { tpl: tplLabel(b) });
        return;
      }
      if (b.dataset.confirm !== "1") {
        tplReset();
        b.dataset.confirm = "1";
        b.textContent = t("carte.confirmTpl", { tpl: tplLabel(b) });
        status.textContent = t("carte.willReset");
        tplTimer = setTimeout(tplReset, 5000);
        return;
      }
      tplReset();
      act(() => ctx.api.post("/api/course/select", { template: b.dataset.template, base_version: version() }));
    });
  }
  btnPrev.addEventListener("click", () => act(() => ctx.api.post("/api/course/prev", { base_version: version() })));
  btnNext.addEventListener("click", () => act(() => ctx.api.post("/api/course/next", { base_version: version() })));
  btnSides.addEventListener("click", () =>
    act(() => ctx.api.post("/api/course/confirm-sides", { base_version: version() })),
  );

  // -- sheets ----------------------------------------------------------------------------------
  function closeSheet() {
    clearTimeout(previewTimer);
    sheetFor = null;
    sheet.hidden = true;
    sheet.replaceChildren();
    setPending(null, null);
  }

  function showSheet(title, ...children) {
    const head = el("div", { class: "sheet-head" });
    head.append(el("h2", { class: "sheet-title" }, title), button(t("common.close"), { class: "big sheet-close" }, closeSheet));
    sheet.replaceChildren(head, ...children);
    sheet.hidden = false;
  }

  function segmented(options, value, onPick, name) {
    const row = el("div", { class: "carte-row seg", "data-name": name });
    for (const [v, label] of options) {
      const b = button(label, { "data-value": v }, () => onPick(v));
      b.classList.toggle("active", v === value);
      row.append(b);
    }
    return row;
  }

  function stepper(value, onChange, name) {
    const row = el("div", { class: "carte-row stepper", "data-name": name });
    const out = el("span", { class: "step-value" }, `${fmtDec(value, 2)} nm`);
    const set = (v) => onChange(roundR(Math.min(RADIUS_MAX, Math.max(0, v))));
    row.append(
      button("−", { "data-step": "-" }, () => set(value - RADIUS_STEP)),
      out,
      button("+", { "data-step": "+" }, () => set(value + RADIUS_STEP)),
    );
    return row;
  }

  function field(label, input) {
    const wrap = el("label", { class: "sheet-field" });
    wrap.append(el("span", { class: "label" }, label), input);
    return wrap;
  }

  // -- typed coordinates (quick 003) -----------------------------------------------------------
  // The race area itself (clipped to what the core accepts). Not the map's maxBounds: since
  // quick 002 those carry a camera margin of up to 1° around the area, for the helm column's
  // padding, so a mark typed 50 nm outside the area would have passed.
  const area = () => areaFrom(null);

  // Camera offset that puts the target in the middle of the largest map area left free by the
  // side panel and the sheet: above the sheet, or beside it when the sheet is tall.
  function viewOffset() {
    const box = map.getContainer().getBoundingClientRect();
    const pr = panel.getBoundingClientRect();
    const sr = sheet.hidden ? null : sheet.getBoundingClientRect();
    const right = pr.width ? Math.min(box.width, Math.max(0, pr.left - box.left)) : box.width;
    const size = (r) => Math.max(0, r.x1 - r.x0) * Math.max(0, r.y1 - r.y0);
    let free = { x0: 0, x1: right, y0: 0, y1: box.height };
    if (sr && sr.height) {
      const above = { x0: 0, x1: right, y0: 0, y1: sr.top - box.top };
      const beside = { x0: sr.right - box.left, x1: right, y0: 0, y1: box.height };
      const best = size(above) >= size(beside) ? above : beside;
      if (size(best) >= 120 * 120) free = best;
    }
    return [(free.x0 + free.x1) / 2 - box.width / 2, (free.y0 + free.y1) / 2 - box.height / 2];
  }

  function showOnMap(lat, lon, duration = 500) {
    if (map) map.easeTo({ center: [lon, lat], offset: viewOffset(), duration });
  }

  // The tap's land check for a typed position: bring it on screen, let the tiles render, then
  // look for the "earth" layer under it (no map or no earth layer: not land).
  async function isLand(lat, lon) {
    if (!map || !map.getLayer("earth")) return false;
    const idle = new Promise((resolve) => {
      const timer = setTimeout(resolve, LAND_WAIT_MS);
      map.once("idle", () => {
        clearTimeout(timer);
        resolve();
      });
    });
    showOnMap(lat, lon, 0);
    map.triggerRepaint();
    await idle;
    if (!map.getLayer("earth")) return false;
    const p = map.project([lon, lat]);
    const c = map.getContainer();
    if (p.x < 0 || p.y < 0 || p.x > c.clientWidth || p.y > c.clientHeight) return false;
    return map.queryRenderedFeatures([p.x, p.y], { layers: ["earth"] }).length > 0;
  }

  // Pending marker at a valid typed position; the map eases there after a pause in typing.
  function preview(res, move) {
    clearTimeout(previewTimer);
    if (!res.ok) {
      setPending(null, null);
      return;
    }
    setPending(res.lat, res.lon);
    if (move) previewTimer = setTimeout(() => showOnMap(res.lat, res.lon), PREVIEW_MS);
  }

  // Latitude and longitude fields (tolerant text, numeric keyboard) with live errors.
  // onCheck(res, fromInput) after every edit and on check(); texts() gives the drafts.
  function coordEditor(latText, lonText, onCheck) {
    const mk = (axis, value) => {
      const input = el("input", {
        id: `coord-${axis}`,
        type: "text",
        inputmode: "decimal",
        enterkeyhint: axis === "lat" ? "next" : "done",
        autocomplete: "off",
        autocapitalize: "characters",
        spellcheck: "false",
        maxlength: "24",
        value,
      });
      // the first tap selects the whole value (typing replaces it); a second tap places the caret
      // (the click after the focus would otherwise drop the selection)
      let fresh = false;
      input.addEventListener("focus", () => {
        fresh = true;
        input.select();
      });
      input.addEventListener("click", () => {
        if (fresh) input.select();
        fresh = false;
      });
      input.addEventListener("blur", () => {
        fresh = false;
      });
      const err = el("div", { class: "coord-error", id: `coord-${axis}-err`, "aria-live": "polite" });
      const wrap = el("label", { class: "sheet-field coord-field" });
      wrap.append(el("span", { class: "label" }, t(`carte.${axis}`)), input, err);
      return { input, err, wrap };
    };
    const la = mk("lat", latText);
    const lo = mk("lon", lonText);
    const areaErr = el("div", { class: "coord-error", id: "coord-area-err", "aria-live": "polite" });
    const row = el("div", { class: "coord-row" });
    row.append(la.wrap, lo.wrap);
    const box = el("div", { class: "coord-editor", "data-name": "coords" });
    box.append(row, el("div", { class: "sheet-text coord-hint" }, t("carte.coordHint")), areaErr);
    const check = (fromInput = false) => {
      const a = area();
      const res = checkPosition(la.input.value, lo.input.value, a);
      la.err.textContent = coordError(res.latError, "lat");
      lo.err.textContent = coordError(res.lonError, "lon");
      la.input.setAttribute("aria-invalid", String(Boolean(res.latError)));
      lo.input.setAttribute("aria-invalid", String(Boolean(res.lonError)));
      areaErr.textContent = res.areaError ? areaText(a) : "";
      onCheck(res, fromInput);
      return res;
    };
    la.input.addEventListener("input", () => check(true));
    lo.input.addEventListener("input", () => check(true));
    la.input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") lo.input.focus();
    });
    return { el: box, check, texts: () => ({ lat: la.input.value, lon: lo.input.value }) };
  }

  // Inline "Marque à terre ?" for a typed position (the sheet and its values stay).
  function landBox(onKeep) {
    const box = el("div", { class: "coord-land", id: "coord-land" });
    box.hidden = true;
    const row = el("div", { class: "carte-row" });
    row.append(
      button(t("carte.keep"), { id: "coord-land-keep" }, () => {
        box.hidden = true;
        onKeep();
      }),
      button(t("common.cancel"), { id: "coord-land-cancel" }, () => {
        box.hidden = true;
      }),
    );
    box.append(el("strong", {}, t("carte.landTitle")), el("p", { class: "sheet-text" }, t("carte.landText")), row);
    return box;
  }

  // The write button of a coordinate editor: runs the land check on a position not checked yet,
  // shows the inline warning on land, else writes.
  function landChecked(getPos, isChecked, land, write) {
    return async (btn) => {
      const pos = getPos();
      if (!pos.ok || busy || locked) return;
      const key = posKey(pos.lat, pos.lon);
      if (!isChecked(key)) {
        btn.disabled = true;
        const onLand = await isLand(pos.lat, pos.lon);
        const now = getPos();
        btn.disabled = !now.ok;
        if (!btn.isConnected || !now.ok || posKey(now.lat, now.lon) !== key) return; // edited
        if (onLand) {
          land.hidden = false;
          return;
        }
      }
      write(pos);
    };
  }

  function openLandWarning(lat, lon) {
    sheetFor = { kind: "land" };
    setPending(lat, lon);
    const row = el("div", { class: "carte-row" });
    row.append(
      button(t("carte.keep"), { id: "land-keep" }, () => openAddSheet(lat, lon, { checked: true })),
      button(t("common.cancel"), { id: "land-cancel" }, closeSheet),
    );
    showSheet(t("carte.landTitle"), el("p", { class: "sheet-text" }, t("carte.landText")), row);
  }

  // checked: the land check already ran for (lat, lon) (a tap on water, or "Garder");
  // move: bring (lat, lon) into view (opened from the button, not from a tap).
  function openAddSheet(lat, lon, { checked = false, move = false } = {}) {
    sheetFor = { kind: "add" };
    setPending(lat, lon);
    const st = { side: "none", radius: RADIUS_STEP, pos: "active" };
    let pos = { ok: true, lat, lon };
    let checkedAt = checked ? posKey(lat, lon) : null;
    const n = Object.values(course.marks).filter((m) => !m.builtin).length + 1;
    const name = el("input", { id: "mark-name", type: "text", maxlength: "40", value: `M${n}`, autocomplete: "off" });
    const body = el("div", { class: "sheet-body" });
    const post = async (at) => {
      // "à la fin" = before the finish (the finish stays the finish)
      const insertAt = st.pos === "end" ? lastIdx(course) : null;
      const ok = await act(() =>
        ctx.api.post("/api/marks", {
          name: name.value,
          lat: round6(at.lat),
          lon: round6(at.lon),
          radius_nm: st.radius,
          side: st.side,
          insert_at: insertAt,
          base_version: version(),
        }),
      );
      if (ok) closeSheet();
    };
    const land = landBox(() => {
      checkedAt = posKey(pos.lat, pos.lon);
      post(pos);
    });
    const onAdd = landChecked(
      () => pos,
      (key) => key === checkedAt,
      land,
      (at) => {
        checkedAt = posKey(at.lat, at.lon);
        post(at);
      },
    );
    const addBtn = button(t("carte.add"), { id: "mark-add", class: "big primary" }, () => onAdd(addBtn));
    const editor = coordEditor(fmtLat(lat), fmtLon(lon), (res, fromInput) => {
      pos = res;
      addBtn.disabled = !res.ok;
      land.hidden = true;
      if (fromInput) preview(res, true);
    });
    const draw = () => {
      body.replaceChildren(
        field(t("carte.name"), name),
        editor.el,
        field(t("carte.side"), segmented(sides(), st.side, (v) => ((st.side = v), draw()), "side")),
        field(t("carte.radius"), stepper(st.radius, (v) => ((st.radius = v), draw()), "radius")),
        field(
          t("carte.position"),
          segmented(
            [
              ["active", t("carte.afterActive")],
              ["end", t("carte.atEnd")],
            ],
            st.pos,
            (v) => ((st.pos = v), draw()),
            "pos",
          ),
        ),
        land,
        addBtn,
      );
    };
    draw();
    showSheet(t("carte.newMark"), body);
    if (move) showOnMap(lat, lon);
  }

  function openAtBoatOrCentre() {
    if (!course || locked) return;
    const a = area();
    const b = ctx.latest?.("nav")?.boat;
    let at = null;
    if (b && Number.isFinite(b.lat) && Number.isFinite(b.lon) && inArea(b.lat, b.lon, a)) at = [b.lat, b.lon];
    else if (map) {
      const c = map.getCenter();
      at = [c.lat, c.lng];
    } else at = [(a.south + a.north) / 2, (a.west + a.east) / 2];
    openAddSheet(at[0], at[1], { move: true });
  }
  btnCoords.addEventListener("click", openAtBoatOrCentre);

  function openMarkSheet(markId, idx, refresh = false) {
    if (!course) return;
    const mark = course.marks[markId];
    if (!mark || (idx >= 0 && course.seq[idx]?.mark_id !== markId)) {
      if (refresh) closeSheet();
      return;
    }
    if (refresh && sheet.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    // typed coordinates not sent yet survive a refresh of the same mark's sheet
    const draft = refresh && sheetFor?.kind === "mark" && sheetFor.markId === markId ? (sheetFor.draft ?? null) : null;
    const s = { kind: "mark", markId, idx, draft };
    sheetFor = s;
    setPending(null, null);
    const leg = idx >= 0 ? course.seq[idx] : null;
    const last = course.seq.length - 1;
    const name = el("input", { id: "mark-name", type: "text", maxlength: "40", value: mark.name, autocomplete: "off" });
    const rename = button(t("carte.rename"), { id: "mark-rename" }, () =>
      act(() => ctx.api.patch(`/api/marks/${encodeURIComponent(markId)}`, { name: name.value, base_version: version() })),
    );
    const nameRow = el("div", { class: "carte-row" });
    nameRow.append(name, rename);
    const body = el("div", { class: "sheet-body" });
    body.append(field(t("carte.name"), nameRow));

    // "Déplacer ici": PATCH lat/lon (a builtin mark gets an override in course.json)
    const lat0 = fmtLat(mark.lat);
    const lon0 = fmtLon(mark.lon);
    let pos = { ok: false };
    let checkedAt = null;
    const move = (at) =>
      act(
        () =>
          ctx.api.patch(`/api/marks/${encodeURIComponent(markId)}`, {
            lat: round6(at.lat),
            lon: round6(at.lon),
            base_version: version(),
          }),
        () => {
          if (sheetFor?.kind === "mark") sheetFor.draft = null;
        },
      );
    const land = landBox(() => {
      checkedAt = posKey(pos.lat, pos.lon);
      move(pos);
    });
    const onMove = landChecked(() => pos, (key) => key === checkedAt, land, move);
    const moveBtn = button(t("carte.moveHere"), { id: "mark-move", class: "big primary" }, () => onMove(moveBtn));
    // the callback runs from editor.check() / typing, after editor is assigned
    const editor = coordEditor(draft?.lat ?? lat0, draft?.lon ?? lon0, (res, fromInput) => {
      pos = res;
      const tx = editor.texts();
      const changed = tx.lat !== lat0 || tx.lon !== lon0;
      s.draft = changed ? tx : null;
      moveBtn.disabled = !(res.ok && changed);
      land.hidden = true;
      preview(changed ? res : { ok: false }, fromInput);
    });
    const coords = el("div", { class: "sheet-field", "data-name": "mark-coords" });
    coords.append(el("span", { class: "label" }, t("carte.coords")), editor.el, land, moveBtn);
    body.append(coords);
    editor.check();
    if (leg && idx >= 1) {
      const patchLeg = (patch) =>
        act(() => ctx.api.patch(`/api/course/legs/${idx}`, { ...patch, base_version: version() }));
      body.append(
        field(t("carte.side"), segmented(sides(), leg.side, (v) => patchLeg({ side: v }), "side")),
        field(t("carte.radius"), stepper(leg.radius_nm, (v) => patchLeg({ radius_nm: v }), "radius")),
      );
      const order = el("div", { class: "carte-row" });
      const up = button(t("carte.up"), { id: "leg-up" }, () =>
        act(
          () => ctx.api.post("/api/course/reorder", { from_idx: idx, to_idx: idx - 1, base_version: version() }),
          () => (sheetFor = { kind: "mark", markId, idx: idx - 1 }),
        ),
      );
      const down = button(t("carte.down"), { id: "leg-down" }, () =>
        act(
          () => ctx.api.post("/api/course/reorder", { from_idx: idx, to_idx: idx + 1, base_version: version() }),
          () => (sheetFor = { kind: "mark", markId, idx: idx + 1 }),
        ),
      );
      up.disabled = idx <= 1;
      down.disabled = idx >= last;
      order.append(up, down);
      const isFinish = course.finish_idx === idx;
      const finish = button(t(isFinish ? "carte.fullCourse" : "carte.finishHere"), { id: "leg-finish" }, () =>
        act(() => ctx.api.post("/api/course/finish", { idx: isFinish ? null : idx, base_version: version() })),
      );
      const activate = button(t("carte.makeActive"), { id: "leg-activate" }, () =>
        act(() => ctx.api.post("/api/course/activate", { idx, base_version: version() })),
      );
      activate.disabled = idx > lastIdx(course);
      const del = button(t("carte.delete"), { id: "leg-delete", class: "big danger" });
      del.disabled = course.seq.length <= 2;
      del.addEventListener("click", () => {
        if (del.dataset.confirm !== "1") {
          del.dataset.confirm = "1";
          del.textContent = t("carte.confirmDelete");
          return;
        }
        act(
          () => ctx.api.del(`/api/course/legs/${idx}?base_version=${encodeURIComponent(version())}`),
          () => (sheetFor = null),
        ).then((ok) => ok && closeSheet());
      });
      const more = el("div", { class: "carte-row" });
      more.append(finish, activate);
      body.append(order, more, del);
    }
    showSheet(idx >= 1 ? t("carte.markTitle", { name: mark.name, idx }) : mark.name, body);
  }

  // -- map -------------------------------------------------------------------------------------
  const pointOf = (ev) => {
    const r = map.getCanvasContainer().getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };
  const hitMark = (pt) =>
    map.getLayer("carte-marks") ? map.queryRenderedFeatures([pt.x, pt.y], { layers: ["carte-marks"] }) : [];

  function endDrag(commit) {
    const d = drag;
    drag = null;
    if (!d) return;
    map.dragPan.enable();
    if (!d.moved || !d.lngLat) return;
    suppressClickUntil = performance.now() + 500;
    if (!commit || !course) {
      renderMap();
      return;
    }
    act(() =>
      ctx.api.patch(`/api/marks/${encodeURIComponent(d.id)}`, {
        lat: round6(d.lngLat.lat),
        lon: round6(d.lngLat.lng),
        base_version: version(),
      }),
    ).then((ok) => ok || renderMap());
  }

  function wireMap(m) {
    map = m;
    registerOverlay(OVERLAY, {
      sources: {
        [SRC.zones]: { type: "geojson", data: EMPTY },
        [SRC.line]: { type: "geojson", data: EMPTY },
        [SRC.pending]: { type: "geojson", data: EMPTY },
        [SRC.marks]: { type: "geojson", data: EMPTY },
      },
      layers,
    });
    setOverlayVisible(OVERLAY, tab === "carte");
    renderMap();
    const canvas = map.getCanvasContainer();
    canvas.addEventListener("pointerdown", (ev) => {
      if (tab !== "carte" || !course || busy || (ev.button !== undefined && ev.button !== 0)) return;
      const p = pointOf(ev);
      const f = hitMark(p)[0];
      if (!f) return;
      drag = { id: f.properties.id, start: p, moved: false, lngLat: null };
      map.dragPan.disable();
    });
    window.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const p = pointOf(ev);
      if (!drag.moved && Math.hypot(p.x - drag.start.x, p.y - drag.start.y) < DRAG_START_PX) return;
      drag.moved = true;
      drag.lngLat = map.unproject([p.x, p.y]);
      renderMap();
    });
    window.addEventListener("pointerup", () => endDrag(true));
    window.addEventListener("pointercancel", () => endDrag(false));
    map.on("click", (e) => {
      if (tab !== "carte" || !course || performance.now() < suppressClickUntil) return;
      const hit = hitMark(e.point);
      if (hit.length) {
        const id = hit[0].properties.id;
        openMarkSheet(id, legFor(course, id));
        return;
      }
      if (sheetFor) {
        closeSheet();
        return;
      }
      const { lat, lng } = e.lngLat;
      const land = map.getLayer("earth") ? map.queryRenderedFeatures(e.point, { layers: ["earth"] }) : [];
      if (land.length) openLandWarning(lat, lng);
      else openAddSheet(lat, lng, { checked: true });
    });
  }

  ensureMap(document.getElementById("map"))
    .then(wireMap)
    .catch(() => {
      hint.textContent = t("carte.noMap");
      mapReady().then((m) => {
        hint.textContent = t("carte.hint");
        wireMap(m); // a later retry of app.js succeeded (IN-02)
      });
    });

  // -- banner (all tabs) -----------------------------------------------------------------------
  const bannerEl = document.getElementById("banner");
  const bannerText = el("span", { id: "banner-text" });
  const bannerUndo = button(t("banner.undo"), { id: "banner-undo", class: "big banner-undo" });
  let bannerToken = null;
  bannerUndo.addEventListener("click", async () => {
    if (!bannerToken) return;
    bannerUndo.disabled = true;
    try {
      course = await ctx.api.post("/api/course/undo", { token: bannerToken });
      render();
    } catch (e) {
      bannerText.textContent = e.status === 410 ? t("banner.expired") : t("common.failed", { s: e.status ?? e });
    } finally {
      bannerUndo.disabled = false;
    }
  });
  function renderBanner(nav) {
    if (!bannerEl) return;
    const v = bannerView(nav);
    if (!v) {
      bannerToken = null;
      if (!bannerEl.hidden) {
        bannerEl.hidden = true;
        bannerEl.replaceChildren();
      }
      return;
    }
    bannerToken = v.undo ? v.token : null;
    if (bannerText.textContent !== v.text) bannerText.textContent = v.text;
    if (bannerText.parentNode !== bannerEl) bannerEl.replaceChildren(bannerText);
    if (v.undo && bannerUndo.parentNode !== bannerEl) bannerEl.append(bannerUndo);
    if (!v.undo && bannerUndo.parentNode === bannerEl) bannerUndo.remove();
    bannerEl.classList.toggle("finish", nav.course.banner.kind === "finish");
    bannerEl.hidden = false;
  }

  // -- bus -------------------------------------------------------------------------------------
  ctx.bus.addEventListener("course", (ev) => {
    course = ev.detail;
    if (!drag) render();
  });
  ctx.bus.addEventListener("nav", (ev) => renderBanner(ev.detail));
  // behind the lock overlay (lock.js) the Carte also refuses writes
  ctx.bus.addEventListener("lock", (ev) => {
    locked = Boolean(ev.detail);
  });
  ctx.bus.addEventListener("tab", (ev) => {
    tab = ev.detail;
    setOverlayVisible(OVERLAY, tab === "carte");
    if (tab !== "carte") {
      closeSheet();
      if (drag) endDrag(false);
    }
  });
  course = ctx.latest?.("course") ?? null;
  render();
  renderBanner(ctx.latest?.("nav"));
}
