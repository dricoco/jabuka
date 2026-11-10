// Réglages tab:
// - "Langue / Language / Jezik" (quick 001): FR / EN / SL for this device only (localStorage
//   "jabuka.lang", i18n.js). A switch reloads the page back on this tab (sessionStorage
//   "jabuka.tab"): simpler and sturdier than re-rendering every mounted module; the lock and the
//   night theme are in localStorage and survive the reload.
// - "Vent manuel" panel (WIND-04): TWD/TWS read off the B&G display, °M (default, Pitfall 6) or °T,
//   POST /api/wind/manual {twd, tws_kn, ref}; "Effacer" = DELETE. The wind source and the manual
//   age come from the nav bus events. 422 errors are shown inline.
// - a form generated from GET /api/settings/schema, saving one field per change with
//   PUT {base_version, patch}; a 409 (edited on another tablet) reloads. Field labels come from
//   i18n.js ("settings.<field>"), the schema's French "label" being the fallback. A "?" button
//   next to each label toggles a short help ("help.<field>") plus the schema's range and default
//   (helpMeta); open helps stay open across re-renders (a save, a settings event).
// DOM built with textContent only. Texts in the tablet's language (i18n.js).
import { LANGS, getLang, setLang, t } from "./i18n.js";

const TAB_KEY = "jabuka.tab"; // app.js shows this tab first after the reload

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  if (text !== undefined) e.textContent = text;
  return e;
}

// JSON schema property -> {kind, min, max, options, nullable}
function fieldSpec(prop) {
  const variants = prop.anyOf ?? [prop];
  const real = variants.find((v) => v.type !== "null") ?? prop;
  const nullable = variants.some((v) => v.type === "null");
  if (Array.isArray(real.enum)) return { kind: "enum", options: real.enum, nullable };
  if (real.type === "boolean") return { kind: "bool", nullable };
  if (real.type === "number" || real.type === "integer") {
    return { kind: "number", min: real.minimum, max: real.maximum, nullable };
  }
  return { kind: "text", nullable };
}

function sourceText(source) {
  if (source === "NONE") return t("badge.noWind");
  if (["LIVE", "LIVE_BG", "MANUEL", "GRIB"].includes(source)) return t(`src.${source}`);
  return String(source);
}

function fmtAge(s) {
  if (typeof s !== "number" || !Number.isFinite(s)) return "";
  const m = Math.floor(s / 60);
  return m < 1 ? t("manual.justNow") : t("manual.ago", { m });
}

// Pure: the manual wind form values -> request body, or an error string.
export function manualBody(twdText, twsText, ref) {
  const twd = Number(String(twdText).replace(",", "."));
  const tws = Number(String(twsText).replace(",", "."));
  if (String(twdText).trim() === "" || !Number.isFinite(twd) || twd < 0 || twd >= 360) {
    return { error: t("manual.errTwd") };
  }
  if (String(twsText).trim() === "" || !Number.isFinite(tws) || tws < 0 || tws > 80) {
    return { error: t("manual.errTws") };
  }
  return { body: { twd, tws_kn: tws, ref: ref === "T" ? "T" : "M" } };
}

function manualPanel(ctx) {
  const box = el("section", { class: "manual-wind", id: "manual-wind", "aria-label": t("manual.title") });
  const title = el("h3", {}, t("manual.title"));
  const source = el("div", { class: "manual-wind-source", id: "manual-wind-source" }, "—");
  const form = el("form", { class: "manual-wind-form", id: "manual-wind-form", novalidate: "" });
  const twd = el("input", {
    type: "number", name: "twd", min: "0", max: "359.9", step: "any", inputmode: "decimal",
    "aria-label": "TWD (°)",
  });
  const tws = el("input", {
    type: "number", name: "tws_kn", min: "0", max: "80", step: "any", inputmode: "decimal",
    "aria-label": t("manual.twsLabel"),
  });
  const ref = el("select", { name: "ref", "aria-label": t("manual.refAria") });
  ref.append(el("option", { value: "M" }, "°M"), el("option", { value: "T" }, "°T"));
  ref.value = "M";
  const apply = el("button", { type: "submit", class: "manual-apply" }, t("manual.apply"));
  const clear = el("button", { type: "button", class: "manual-clear" }, t("manual.clear"));
  const error = el("div", { class: "manual-wind-error", id: "manual-wind-error", "aria-live": "polite" });
  const stored = el("div", { class: "manual-wind-stored", id: "manual-wind-stored" });
  const field = (label, input) => {
    const l = el("label", { class: "manual-field" });
    l.append(el("span", {}, label), input);
    return l;
  };
  form.append(field("TWD (°)", twd), field(t("manual.twsLabel"), tws), field(t("manual.ref"), ref), apply, clear);
  box.append(title, source, form, stored, error);

  function showStored(m) {
    if (!m) {
      stored.textContent = t("manual.none");
      return;
    }
    stored.textContent =
      t("manual.stored", { twd: m.twd_entered, ref: m.ref_entered, tws: m.tws_kn }) +
      (m.ref_entered === "M" ? ` (${m.twd_t_deg}°T)` : "");
    if (document.activeElement !== twd && document.activeElement !== tws) {
      twd.value = m.twd_entered;
      tws.value = m.tws_kn;
      ref.value = m.ref_entered;
    }
  }

  function showNav(nav) {
    const w = nav?.wind;
    if (!w) return;
    let text = sourceText(w.source);
    if (w.source === "MANUEL") {
      const age = fmtAge(w.manual_age_s);
      text += age ? t("manual.entered", { age }) : t("manual.ageUnknown"); // no trusted UTC (WR-03)
      if (w.stale) text += t("manual.stale");
    }
    source.textContent = text;
    source.dataset.source = w.source;
  }

  async function refresh() {
    try {
      showStored((await ctx.api.get("/api/wind/manual")).manual);
    } catch (e) {
      stored.textContent = t("manual.unavailable", { s: e.status ?? e });
    }
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const parsed = manualBody(twd.value, tws.value, ref.value);
    if (parsed.error) {
      error.textContent = parsed.error;
      return;
    }
    try {
      const nav = await ctx.api.post("/api/wind/manual", parsed.body);
      error.textContent = "";
      showNav(nav);
      refresh();
    } catch (e) {
      error.textContent = e.status === 422 ? t("manual.refused") : t("common.failed", { s: e.status ?? e });
    }
  });
  clear.addEventListener("click", async () => {
    try {
      const nav = await ctx.api.del("/api/wind/manual");
      error.textContent = "";
      showNav(nav);
      refresh();
    } catch (e) {
      error.textContent = t("common.failed", { s: e.status ?? e });
    }
  });

  ctx.bus.addEventListener("nav", (ev) => showNav(ev.detail));
  showNav(ctx.latest?.("nav"));
  refresh();
  return box;
}

// FR / EN / SL buttons: this device's language; a switch reloads the page on this tab.
function langPanel() {
  const box = el("section", { class: "lang-select", id: "lang-select", "aria-label": t("lang.title") });
  const row = el("div", { class: "lang-row" });
  for (const lang of LANGS) {
    const b = el("button", { type: "button", class: "lang-btn", "data-lang": lang }, lang.toUpperCase());
    const on = lang === getLang();
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.addEventListener("click", () => {
      if (lang === getLang() || document.body.classList.contains("locked")) return;
      setLang(lang);
      try {
        sessionStorage.setItem(TAB_KEY, "reglages");
      } catch {
        /* no session storage: back on the Barre tab */
      }
      location.reload();
    });
    row.append(b);
  }
  box.append(el("h3", {}, t("lang.title")), row);
  return box;
}

// Label of an enum option ("computed" -> "calculé"); the raw value when there is none.
function optionLabel(value) {
  const key = `opt.${value}`;
  const text = t(key);
  return text === key ? String(value) : text;
}

// A number as the tablet writes it: decimal comma in fr and sl, point in en.
function fmtNum(x) {
  const s = String(x);
  return getLang() === "en" ? s : s.replace(".", ",");
}

// Pure: the "Range: min to max · Default: v" line of a schema property ("" when nothing is known).
export function helpMeta(prop) {
  const spec = fieldSpec(prop);
  const parts = [];
  if (spec.kind === "number" && spec.min !== undefined && spec.max !== undefined) {
    parts.push(t("reglages.helpRange", { min: fmtNum(spec.min), max: fmtNum(spec.max) }));
  }
  if ("default" in prop) {
    const d = prop.default;
    let v;
    if (d === null) v = t("reglages.helpEmpty");
    else if (typeof d === "boolean") v = t(d ? "reglages.yes" : "reglages.no");
    else if (spec.kind === "enum") v = optionLabel(d);
    else if (typeof d === "number") v = fmtNum(d);
    else v = String(d);
    parts.push(t("reglages.helpDefault", { v }));
  }
  return parts.join(" · ");
}

export function mount(ctx) {
  const root = ctx.section;
  if (!root) return;
  let schema = null;
  let current = null; // {version, settings}
  const openHelp = new Set(); // fields whose help is expanded, kept across render()
  const form = el("form", { class: "reglages-form", id: "settings-form" });
  const status = el("div", { class: "reglages-status", "aria-live": "polite" });
  const title = el("h2", {}, t("tab.reglages"));
  let manual = null;
  try {
    manual = manualPanel(ctx);
  } catch (e) {
    console.error("manual wind panel", e);
  }
  root.replaceChildren(title, langPanel(), ...(manual ? [manual] : []), status, form);
  form.addEventListener("submit", (ev) => ev.preventDefault());

  function inputFor(key, prop) {
    const spec = fieldSpec(prop);
    const value = current?.settings?.[key];
    let input;
    if (spec.kind === "enum") {
      input = el("select", { name: key });
      for (const opt of spec.options) input.append(el("option", { value: opt }, optionLabel(opt)));
      input.value = value ?? spec.options[0];
    } else if (spec.kind === "bool") {
      input = el("input", { type: "checkbox", name: key });
      input.checked = Boolean(value);
    } else if (spec.kind === "number") {
      input = el("input", { type: "number", name: key, step: "any", inputmode: "decimal" });
      if (spec.min !== undefined) input.min = spec.min;
      if (spec.max !== undefined) input.max = spec.max;
      input.value = value ?? "";
      if (spec.nullable) input.placeholder = "—";
    } else {
      input = el("input", { type: "text", name: key });
      input.value = value ?? "";
    }
    input.id = `reglages-in-${key}`;
    input.addEventListener("change", () => save(key, spec, input));
    return input;
  }

  function render() {
    if (!schema || !current) return;
    const rows = Object.entries(schema.properties ?? {}).map(([key, prop]) => {
      const row = el("div", { class: "reglages-row", "data-key": key });
      const tr = t(`settings.${key}`);
      const label = tr === `settings.${key}` ? (prop.label ?? prop.title ?? key) : tr;
      const name = el("div", { class: "reglages-name" });
      name.append(el("label", { class: "reglages-label", for: `reglages-in-${key}` }, label));
      const help = t(`help.${key}`);
      let panel = null;
      if (help !== `help.${key}`) {
        const panelId = `reglages-help-${key}`;
        const open = openHelp.has(key);
        const btn = el(
          "button",
          {
            type: "button",
            class: "help-btn",
            "aria-expanded": open ? "true" : "false",
            "aria-controls": panelId,
            "aria-label": t("reglages.helpAria", { label }),
          },
          "?",
        );
        panel = el("div", { class: "reglages-help", id: panelId });
        panel.hidden = !open;
        panel.append(el("p", { class: "reglages-help-text" }, help));
        const meta = helpMeta(prop);
        if (meta) panel.append(el("p", { class: "reglages-help-meta" }, meta));
        btn.addEventListener("click", () => {
          const now = !openHelp.has(key);
          if (now) openHelp.add(key);
          else openHelp.delete(key);
          btn.setAttribute("aria-expanded", now ? "true" : "false");
          panel.hidden = !now;
        });
        name.append(btn);
      }
      row.append(name, inputFor(key, prop));
      if (panel) row.append(panel);
      return row;
    });
    form.replaceChildren(...rows);
  }

  async function save(key, spec, input) {
    let value;
    if (spec.kind === "bool") value = input.checked;
    else if (spec.kind === "number") {
      value = input.value === "" && spec.nullable ? null : Number(input.value);
      if (value !== null && !Number.isFinite(value)) {
        status.textContent = t("reglages.invalid");
        return;
      }
    } else value = input.value;
    try {
      current = await ctx.api.put("/api/settings", {
        base_version: current.version,
        patch: { [key]: value },
      });
      status.textContent = t("reglages.saved");
      render();
    } catch (e) {
      if (e.status === 409 && e.body) {
        current = e.body;
        render();
        status.textContent = t("reglages.conflict");
      } else if (e.status === 422) {
        status.textContent = t("reglages.outOfRange");
        render();
      } else {
        status.textContent = t("common.failed", { s: e.status ?? e });
      }
    }
  }

  ctx.bus.addEventListener("settings", (ev) => {
    current = ev.detail;
    if (!form.contains(document.activeElement)) render();
  });
  current = ctx.latest?.("settings") ?? null;

  ctx.api
    .get("/api/settings/schema")
    .then((s) => {
      schema = s;
      render();
    })
    .catch((e) => {
      status.textContent = t("reglages.noSchema", { s: e.status ?? e });
    });
}
