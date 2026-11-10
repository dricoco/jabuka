// Start mode on the Barre tab (quick 261110-cuk, "Mode départ"), render only: the state lives on
// the Pi (nav/start.py) and comes in the nav message's optional "start" block (absent while start
// mode is closed), so every tablet shows the same line and countdown, and a page reload keeps it.
//   - #start-ctrls: the DÉPART button over the map (bottom left of the map area), hidden while
//     start mode is open; never inside #helm-col or #map-ctrls (the helm layout is untouched)
//   - #start-panel: the countdown (#start-timer, interpolated every 250 ms from the last nav
//     message), 5:00 / SYNC / STOP / « Fermer le départ », the two line ends with « Ping comité » /
//     « Ping bouée » (the boat's GPS position, stored by the core) and a typed fallback
//     (#start-form, degrees + decimal minutes checked with coord_logic.js like the Carte tab),
//     the line length / bearing, the time to the line on the current heading and on the other
//     tack with the margin against the gun, and the TACK alert (#start-alert, the panel inverted)
//   - beep: three short 1 kHz tones on the rising edge of the TACK alert (start_logic beepDue),
//     Web Audio unlocked by a tap while the panel is shown (Android needs a gesture); no audio =
//     the visual alert only
//   - map: overlay "start" (map.js registerOverlay, survives the day/night style swap): the start
//     zone, the line and its ends; hidden while start mode is closed; the map stays optional
// Actions: POST/PUT /api/start/*, one request in flight, ignored while the screen is locked; the
// answer (the fresh nav message) is rendered at once. Every render runs in try/catch: a start-mode
// bug never stops the helm (H-01). Every string goes through textContent.
import { RACE_AREA, checkPosition, formatDM } from "./coord_logic.js";
import { fmtDec, t } from "./i18n.js";
import { ensureMap, mapReady, registerOverlay, setOverlayData, setOverlayVisible } from "./map.js";
import { beepDue, coordErrorKey, remainingAt, startData, startLayers, startView } from "./start_logic.js";

const $ = (id) => document.getElementById(id);
const FLASH_MS = 6000;
const TIMER_MS = 250;
const EMPTY = { type: "FeatureCollection", features: [] };
const TONE_HZ = 1000;
const TONE_S = 0.15;
const TONE_GAP_S = 0.1;

// -- beep (Web Audio; works on the plain-http origin) ------------------------------------------
let audio = null;

function unlockAudio() {
  try {
    const AC = globalThis.AudioContext ?? globalThis.webkitAudioContext;
    if (!AC) return;
    if (!audio) audio = new AC();
    if (audio.state === "suspended") audio.resume()?.catch?.(() => {});
  } catch (e) {
    console.warn("start audio", e);
  }
}

function beep() {
  try {
    if (!audio || audio.state !== "running") return;
    const t0 = audio.currentTime + 0.02;
    for (let i = 0; i < 3; i += 1) {
      const start = t0 + i * (TONE_S + TONE_GAP_S);
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.frequency.value = TONE_HZ;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.6, start + 0.01);
      gain.gain.setValueAtTime(0.6, start + TONE_S - 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + TONE_S);
      osc.connect(gain).connect(audio.destination);
      osc.start(start);
      osc.stop(start + TONE_S + 0.01);
    }
  } catch (e) {
    console.warn("start beep", e);
  }
}

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  if (text !== undefined) e.textContent = text;
  return e;
}

const button = (id, text, cls = "ctrl") => el("button", { type: "button", id, class: cls }, text);

function setText(e, text) {
  if (e && e.textContent !== text) e.textContent = text;
}

const decSep = () => fmtDec(0.5, 1).charAt(1);
const fmtLat = (v, digits = 3) => formatDM(v, "lat", { digits, sep: decSep() });
const fmtLon = (v, digits = 3) => formatDM(v, "lon", { digits, sep: decSep() });

function coordError(code, axis) {
  if (!code) return "";
  if (code === "hemisphere") return t("carte.errHemi", { h: axis === "lat" ? "N / S" : "E / W" });
  return t(coordErrorKey(code));
}

function build(section) {
  const ctrls = el("div", { id: "start-ctrls", class: "start-ctrls" });
  ctrls.append(button("start-open", t("start.open")));

  const panel = el("div", { id: "start-panel", class: "start-panel", hidden: "" });
  const head = el("div", { class: "start-row start-head" });
  head.append(
    el("span", { id: "start-timer", class: "start-timer" }, "—:—"),
    button("start-go", t("start.go"), "ctrl start-btn"),
    button("start-sync", t("start.sync"), "ctrl start-btn"),
    button("start-stop", t("start.stop"), "ctrl start-btn"),
    button("start-close", t("start.close"), "ctrl start-btn"),
  );
  panel.append(
    head,
    el("div", { id: "start-alert", class: "start-alert", hidden: "" }, t("start.tackNow")),
    el("div", { id: "start-status", class: "start-status" }),
  );
  const times = el("div", { class: "start-row start-times" });
  for (const name of ["now", "other"]) {
    const side = el("div", { id: `start-${name}`, class: "start-side" });
    side.append(
      el("span", { class: "start-end-label" }, t(`start.${name}`)),
      el("span", { class: "start-side-value" }, "—"),
    );
    times.append(side);
  }
  panel.append(times);
  for (const name of ["committee", "pin"]) {
    const row = el("div", { class: "start-row start-end-row" });
    const cap = name === "committee" ? "Committee" : "Pin";
    row.append(
      el("span", { class: "start-end-label" }, t(`start.${name}`)),
      el("span", { id: `start-end-${name}`, class: "start-end" }),
      button(`start-ping-${name}`, t(`start.ping${cap}`), "ctrl start-btn"),
      button(`start-type-${name}`, t("start.type"), "ctrl start-btn"),
    );
    panel.append(row);
  }
  panel.append(
    el("div", { id: "start-line-info", class: "start-line-info", hidden: "" }),
    el("div", { id: "start-msg", class: "start-msg", hidden: "" }),
  );

  const form = el("div", { id: "start-form", class: "start-form", hidden: "" });
  const field = (axis) => {
    const input = el("input", {
      id: `start-${axis}`,
      type: "text",
      inputmode: "decimal",
      autocomplete: "off",
      autocapitalize: "characters",
      spellcheck: "false",
      maxlength: "24",
    });
    const wrap = el("label", { class: "start-field" });
    wrap.append(el("span", { class: "start-end-label" }, t(`carte.${axis}`)), input);
    return wrap;
  };
  const actions = el("div", { class: "start-row" });
  actions.append(
    button("start-form-ok", "OK", "ctrl start-btn"),
    button("start-form-cancel", t("common.cancel"), "ctrl start-btn"),
  );
  form.append(
    el("div", { id: "start-form-title", class: "start-end-label" }),
    el("div", { class: "start-row" }),
    el("div", { id: "start-form-err", class: "start-form-err", "aria-live": "polite" }),
    actions,
  );
  form.children[1].append(field("lat"), field("lon"));
  panel.append(form);

  section.append(ctrls, panel);
  return { ctrls, panel, form };
}

export function mount(ctx) {
  const section = ctx.section ?? $("tab-barre");
  const ui = build(section);
  let nav = ctx.latest?.("nav") ?? null;
  let rxMs = performance.now();
  let locked = document.body.classList.contains("locked");
  let pending = false;
  let flash = null; // {text, until}
  let formEnd = null; // "committee" | "pin" while the typed form is open

  const block = () => nav?.start ?? null;

  let beepState = { was: false, lastMs: null };

  const renderTimer = () => {
    const v = startView(block(), remainingAt(block(), rxMs, performance.now()), nav?.display);
    setText($("start-timer"), v.timer.text);
    return v;
  };

  const render = () => {
    const v = renderTimer();
    ui.panel.hidden = !v.visible;
    ui.ctrls.hidden = v.visible;
    if (!v.visible) closeForm();
    ui.panel.classList.toggle("start-error", v.error);
    setText($("start-status"), v.status);
    $("start-status").hidden = !v.status;
    setText($("start-line-info"), v.lineInfo);
    $("start-line-info").hidden = !v.lineInfo;
    for (const name of ["now", "other"]) {
      const row = v[name];
      const e = $(`start-${name}`);
      setText(e.querySelector(".start-side-value"), row.text);
      e.classList.remove("good", "bad");
      if (row.cls) e.classList.add(row.cls);
    }
    ui.panel.classList.toggle("tack-now", v.tackNow);
    $("start-alert").hidden = !v.tackNow;
    const b = beepDue(beepState, v.tackNow, performance.now());
    beepState = b.state;
    if (b.beep) beep();
    for (const name of ["committee", "pin"]) {
      const e = v.ends[name];
      setText($(`start-end-${name}`), e.text);
      $(`start-end-${name}`).classList.toggle("unset", !e.ok);
    }
    const busy = pending || v.error;
    $("start-open").disabled = pending;
    $("start-go").disabled = busy;
    $("start-sync").disabled = busy || v.buttons.syncDisabled;
    $("start-stop").disabled = busy || v.buttons.stopDisabled;
    $("start-close").disabled = pending;
    for (const id of ["ping-committee", "ping-pin", "type-committee", "type-pin"]) {
      $(`start-${id}`).disabled = busy;
    }
    const msg = $("start-msg");
    if (flash && performance.now() < flash.until) {
      setText(msg, flash.text);
      msg.hidden = false;
    } else {
      flash = null;
      msg.hidden = true;
    }
  };

  const safeRender = () => {
    try {
      render();
    } catch (e) {
      console.error("start panel", e);
    }
  };

  // -- map overlay -------------------------------------------------------------------------------
  let ready = false;
  let shown = null;
  const data = { "start-zone": EMPTY, "start-line": EMPTY, "start-ends": EMPTY };
  const keys = {};
  const syncMap = () => {
    const d = startData(block());
    for (const [name, value] of [
      ["start-zone", d.zone],
      ["start-line", d.line],
      ["start-ends", d.ends],
    ]) {
      const key = JSON.stringify(value);
      if (keys[name] === key) continue;
      keys[name] = key;
      data[name] = value;
      if (ready) setOverlayData(name, value);
    }
    const visible = Boolean(block()?.open);
    if (ready && visible !== shown) {
      setOverlayVisible("start", visible);
      shown = visible;
    }
  };
  const safeMap = () => {
    try {
      syncMap();
    } catch (e) {
      console.error("start overlay", e);
    }
  };

  const onNav = (msg) => {
    nav = msg;
    rxMs = performance.now();
    safeRender();
    safeMap();
  };

  const refusal = (e) => {
    const detail = e?.body?.detail;
    if (e?.status === 409 && detail === "no_position") return t("start.noGps");
    if (e?.status === 409 && detail === "no_timer") return t("start.noTimer");
    if (e?.status === 503) return t("start.writeFailed");
    if (e?.status === 422) return t("carte.refused");
    return t("common.failed", { s: String(e?.status ?? e?.message ?? "?") });
  };

  // one request in flight, nothing while the screen is locked; true when the core accepted it
  const act = async (method, url, body) => {
    if (pending || locked || document.body.classList.contains("locked")) return false;
    pending = true;
    safeRender();
    try {
      const fresh = await ctx.api[method](url, body);
      if (fresh && typeof fresh === "object" && fresh.type === "nav") onNav(fresh);
      return true;
    } catch (e) {
      flash = { text: refusal(e), until: performance.now() + FLASH_MS };
      return false;
    } finally {
      pending = false;
      safeRender();
    }
  };

  // -- typed line end ----------------------------------------------------------------------------
  const checkForm = () => {
    const res = checkPosition($("start-lat").value, $("start-lon").value, RACE_AREA);
    const errs = [coordError(res.latError, "lat"), coordError(res.lonError, "lon")].filter(Boolean);
    if (res.areaError) {
      const a = RACE_AREA;
      errs.push(
        t("carte.errArea", { s: fmtLat(a.south, 0), n: fmtLat(a.north, 0), w: fmtLon(a.west, 0), e: fmtLon(a.east, 0) }),
      );
    }
    setText($("start-form-err"), errs.join(" · "));
    $("start-form-ok").disabled = !res.ok || pending;
    return res;
  };

  function closeForm() {
    formEnd = null;
    ui.form.hidden = true;
  }

  const openForm = (name) => {
    formEnd = name;
    const end = block()?.line?.[name];
    const boat = nav?.boat;
    const lat = end?.lat ?? boat?.lat;
    const lon = end?.lon ?? boat?.lon;
    $("start-lat").value = typeof lat === "number" ? fmtLat(lat) : "";
    $("start-lon").value = typeof lon === "number" ? fmtLon(lon) : "";
    setText($("start-form-title"), t("start.formTitle", { end: t(`start.${name}`) }));
    ui.form.hidden = false;
    checkForm();
  };

  $("start-lat").addEventListener("input", checkForm);
  $("start-lon").addEventListener("input", checkForm);
  $("start-form-cancel").addEventListener("click", closeForm);
  $("start-form-ok").addEventListener("click", async () => {
    const res = checkForm();
    if (!res.ok || !formEnd) return;
    if (await act("put", `/api/start/line/${formEnd}`, { lat: res.lat, lon: res.lon })) closeForm();
  });

  // -- buttons -------------------------------------------------------------------------------------
  $("start-open").addEventListener("click", () => act("post", "/api/start/open", { open: true }));
  $("start-close").addEventListener("click", () => act("post", "/api/start/open", { open: false }));
  $("start-go").addEventListener("click", () => act("post", "/api/start/timer", { action: "start" }));
  $("start-sync").addEventListener("click", () => act("post", "/api/start/timer", { action: "sync" }));
  $("start-stop").addEventListener("click", () => act("post", "/api/start/timer", { action: "stop" }));
  for (const name of ["committee", "pin"]) {
    $(`start-ping-${name}`).addEventListener("click", () => act("post", "/api/start/ping", { end: name }));
    $(`start-type-${name}`).addEventListener("click", () => openForm(name));
  }

  // Android plays sound only after a gesture: any tap while the panel is shown unlocks it
  window.addEventListener(
    "pointerdown",
    () => {
      if (!ui.panel.hidden) unlockAudio();
    },
    { capture: true },
  );
  ctx.bus.addEventListener("lock", (ev) => {
    locked = Boolean(ev.detail);
  });
  ctx.bus.addEventListener("nav", (ev) => onNav(ev.detail));
  setInterval(() => {
    try {
      if (!ui.panel.hidden) renderTimer();
    } catch (e) {
      console.error("start timer", e);
    }
  }, TIMER_MS);
  safeRender();
  safeMap();

  // the map is optional: the panel works without it, the overlay comes up whenever it loads
  (async () => {
    try {
      await ensureMap($("map"));
    } catch {
      await mapReady();
    }
    const sources = {};
    for (const [name, value] of Object.entries(data)) sources[name] = { type: "geojson", data: value };
    registerOverlay("start", { sources, layers: startLayers });
    ready = true;
    shown = null;
    safeMap();
  })().catch((e) => console.error("start overlay", e));
}
