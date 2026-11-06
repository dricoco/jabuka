// Carte tab (CRSE-01..04) and the global advance banner (CRSE-03).
//
// - Course A / B in one tap, previous / next mark, the course list (tap a leg to edit it), the
//   "Côtés à confirmer (IC)" warning with "Côtés confirmés".
// - Map editing on the shared map (map.js overlay "carte", shown only on this tab): tap open water
//   to add a mark (a tap on the "earth" layer first asks "Marque à terre ?"), drag a mark to move
//   it (one PATCH on release), tap a mark for its sheet: name, side, radius, Monter / Descendre,
//   Supprimer (confirmed), "Finir ici", "Rendre active".
// - Every write carries base_version; a 409 shows "Parcours modifié ailleurs — rechargé" and
//   loads the current course from the 409 body.
// - #banner (every tab): "Marque suivante : <nom>" with a 48 px "Annuler" while the nav message's
//   t_mono is before undo_until_s; "ARRIVÉE — <nom>" without Annuler.
// DOM built with textContent only: mark names are data typed on another tablet (T-02-04-02).
import { ensureMap, mapReady, registerOverlay, setOverlayData, setOverlayVisible } from "./map.js";

const SIDE = { port: "bâbord", stbd: "tribord", none: "" };
const SIDES = [
  ["port", "Bâbord"],
  ["stbd", "Tribord"],
  ["none", "Aucun"],
];
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

// Banner view from a nav message: {text, undo} or null.
export function bannerView(nav) {
  const b = nav?.course?.banner;
  if (!b || !b.text) return null;
  const undo =
    b.kind !== "finish" &&
    Boolean(b.token) &&
    typeof b.undo_until_s === "number" &&
    typeof nav.t_mono === "number" &&
    nav.t_mono < b.undo_until_s;
  return { text: String(b.text).replace(/\s*—\s*Annuler\s*$/, ""), undo, token: b.token ?? null };
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
  let sheetFor = null; // {kind: "mark", markId, idx} | {kind: "add"|"land", ...}

  // -- side panel ------------------------------------------------------------------------------
  const panel = el("div", { class: "carte-panel" });
  const tpl = el("div", { class: "carte-row" });
  const btnA = button("Parcours A", { "data-template": "A" });
  const btnB = button("Parcours B", { "data-template": "B" });
  tpl.append(btnA, btnB);
  const navRow = el("div", { class: "carte-row" });
  const btnPrev = button("Préc.", { id: "course-prev" });
  const btnNext = button("Suiv.", { id: "course-next" });
  navRow.append(btnPrev, btnNext);
  const warn = el("div", { class: "carte-warn", id: "sides-warning" });
  const warnText = el("span", {}, "Côtés à confirmer (IC)");
  const btnSides = button("Côtés confirmés", { id: "sides-confirm" });
  warn.append(warnText, btnSides);
  const status = el("div", { class: "carte-status", id: "carte-status", "aria-live": "polite" });
  const hint = el("div", { class: "carte-hint" }, "Toucher la carte pour ajouter une marque");
  const list = el("ol", { class: "carte-list", id: "course-list", start: "0" });
  panel.append(tpl, navRow, warn, status, hint, list);
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
      const side = SIDE[leg.side] ?? "";
      const meta = el("span", { class: "meta" }, side ? `${side} · ${leg.radius_nm} nm` : `${leg.radius_nm} nm`);
      li.append(name, meta);
      if (i === 0) li.append(el("span", { class: "tag" }, "DÉPART"));
      if (i === last) li.append(el("span", { class: "tag finish" }, "ARRIVÉE"));
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
    if (busy) return false;
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
        status.textContent = "Parcours modifié ailleurs — rechargé";
        closeSheet();
        render();
      } else if (e.status === 422) {
        status.textContent = "Valeur refusée";
      } else {
        status.textContent = `Échec (${e.status ?? e})`;
      }
      return false;
    } finally {
      busy = false;
    }
  }

  const version = () => (course ? course.version : null);

  // WR-05: a template change rebuilds the course (custom marks and leg edits dropped), so it
  // takes two taps like "Supprimer"; the template already in use is a no-op.
  const tplLabel = (b) => `Parcours ${b.dataset.template}`;
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
        status.textContent = `${tplLabel(b)} déjà actif`;
        return;
      }
      if (b.dataset.confirm !== "1") {
        tplReset();
        b.dataset.confirm = "1";
        b.textContent = `Confirmer ${tplLabel(b)}`;
        status.textContent = "Le parcours sera réinitialisé";
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
    sheetFor = null;
    sheet.hidden = true;
    sheet.replaceChildren();
    setPending(null, null);
  }

  function showSheet(title, ...children) {
    const head = el("div", { class: "sheet-head" });
    head.append(el("h2", { class: "sheet-title" }, title), button("Fermer", { class: "big sheet-close" }, closeSheet));
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
    const out = el("span", { class: "step-value" }, `${value.toFixed(2)} nm`);
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

  function openLandWarning(lat, lon) {
    sheetFor = { kind: "land" };
    setPending(lat, lon);
    const row = el("div", { class: "carte-row" });
    row.append(
      button("Garder", { id: "land-keep" }, () => openAddSheet(lat, lon)),
      button("Annuler", { id: "land-cancel" }, closeSheet),
    );
    showSheet("Marque à terre ?", el("p", { class: "sheet-text" }, "Ce point est sur une île ou la côte."), row);
  }

  function openAddSheet(lat, lon) {
    sheetFor = { kind: "add" };
    setPending(lat, lon);
    const st = { side: "none", radius: RADIUS_STEP, pos: "active" };
    const n = Object.values(course.marks).filter((m) => !m.builtin).length + 1;
    const name = el("input", { id: "mark-name", type: "text", maxlength: "40", value: `M${n}`, autocomplete: "off" });
    const body = el("div", { class: "sheet-body" });
    const draw = () => {
      body.replaceChildren(
        field("Nom", name),
        el("div", { class: "sheet-text" }, `${lat.toFixed(4)}° N  ${lon.toFixed(4)}° E`),
        field("Côté", segmented(SIDES, st.side, (v) => ((st.side = v), draw()), "side")),
        field("Rayon", stepper(st.radius, (v) => ((st.radius = v), draw()), "radius")),
        field(
          "Position",
          segmented(
            [
              ["active", "Après la marque active"],
              ["end", "À la fin"],
            ],
            st.pos,
            (v) => ((st.pos = v), draw()),
            "pos",
          ),
        ),
        button("Ajouter", { id: "mark-add", class: "big primary" }, async () => {
          // "à la fin" = before the finish (the finish stays the finish)
          const insertAt = st.pos === "end" ? lastIdx(course) : null;
          const ok = await act(() =>
            ctx.api.post("/api/marks", {
              name: name.value,
              lat: round6(lat),
              lon: round6(lon),
              radius_nm: st.radius,
              side: st.side,
              insert_at: insertAt,
              base_version: version(),
            }),
          );
          if (ok) closeSheet();
        }),
      );
    };
    draw();
    showSheet("Nouvelle marque", body);
  }

  function openMarkSheet(markId, idx, refresh = false) {
    if (!course) return;
    const mark = course.marks[markId];
    if (!mark || (idx >= 0 && course.seq[idx]?.mark_id !== markId)) {
      if (refresh) closeSheet();
      return;
    }
    if (refresh && sheet.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    sheetFor = { kind: "mark", markId, idx };
    setPending(null, null);
    const leg = idx >= 0 ? course.seq[idx] : null;
    const last = course.seq.length - 1;
    const name = el("input", { id: "mark-name", type: "text", maxlength: "40", value: mark.name, autocomplete: "off" });
    const rename = button("Renommer", { id: "mark-rename" }, () =>
      act(() => ctx.api.patch(`/api/marks/${encodeURIComponent(markId)}`, { name: name.value, base_version: version() })),
    );
    const nameRow = el("div", { class: "carte-row" });
    nameRow.append(name, rename);
    const body = el("div", { class: "sheet-body" });
    body.append(field("Nom", nameRow));
    if (leg && idx >= 1) {
      const patchLeg = (patch) =>
        act(() => ctx.api.patch(`/api/course/legs/${idx}`, { ...patch, base_version: version() }));
      body.append(
        field("Côté", segmented(SIDES, leg.side, (v) => patchLeg({ side: v }), "side")),
        field("Rayon", stepper(leg.radius_nm, (v) => patchLeg({ radius_nm: v }), "radius")),
      );
      const order = el("div", { class: "carte-row" });
      const up = button("Monter", { id: "leg-up" }, () =>
        act(
          () => ctx.api.post("/api/course/reorder", { from_idx: idx, to_idx: idx - 1, base_version: version() }),
          () => (sheetFor = { kind: "mark", markId, idx: idx - 1 }),
        ),
      );
      const down = button("Descendre", { id: "leg-down" }, () =>
        act(
          () => ctx.api.post("/api/course/reorder", { from_idx: idx, to_idx: idx + 1, base_version: version() }),
          () => (sheetFor = { kind: "mark", markId, idx: idx + 1 }),
        ),
      );
      up.disabled = idx <= 1;
      down.disabled = idx >= last;
      order.append(up, down);
      const isFinish = course.finish_idx === idx;
      const finish = button(isFinish ? "Parcours complet" : "Finir ici", { id: "leg-finish" }, () =>
        act(() => ctx.api.post("/api/course/finish", { idx: isFinish ? null : idx, base_version: version() })),
      );
      const activate = button("Rendre active", { id: "leg-activate" }, () =>
        act(() => ctx.api.post("/api/course/activate", { idx, base_version: version() })),
      );
      activate.disabled = idx > lastIdx(course);
      const del = button("Supprimer", { id: "leg-delete", class: "big danger" });
      del.disabled = course.seq.length <= 2;
      del.addEventListener("click", () => {
        if (del.dataset.confirm !== "1") {
          del.dataset.confirm = "1";
          del.textContent = "Confirmer la suppression";
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
    showSheet(idx >= 1 ? `${mark.name} (n° ${idx})` : mark.name, body);
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
      else openAddSheet(lat, lng);
    });
  }

  ensureMap(document.getElementById("map"))
    .then(wireMap)
    .catch(() => {
      hint.textContent = "Carte indisponible : édition par la liste";
      mapReady().then((m) => {
        hint.textContent = "Toucher la carte pour ajouter une marque";
        wireMap(m); // a later retry of app.js succeeded (IN-02)
      });
    });

  // -- banner (all tabs) -----------------------------------------------------------------------
  const bannerEl = document.getElementById("banner");
  const bannerText = el("span", { id: "banner-text" });
  const bannerUndo = button("Annuler", { id: "banner-undo", class: "big banner-undo" });
  let bannerToken = null;
  bannerUndo.addEventListener("click", async () => {
    if (!bannerToken) return;
    bannerUndo.disabled = true;
    try {
      course = await ctx.api.post("/api/course/undo", { token: bannerToken });
      render();
    } catch (e) {
      bannerText.textContent = e.status === 410 ? "Annuler expiré" : `Échec (${e.status ?? e})`;
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
