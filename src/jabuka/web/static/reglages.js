// Réglages tab:
// - "Vent manuel" panel (WIND-04): TWD/TWS read off the B&G display, °M (default, Pitfall 6) or °T,
//   POST /api/wind/manual {twd, tws_kn, ref}; "Effacer" = DELETE. The wind source and the manual
//   age come from the nav bus events. 422 errors are shown inline, in French.
// - a form generated from GET /api/settings/schema (French labels in "label"), saving one field per
//   change with PUT {base_version, patch}; a 409 (edited on another tablet) reloads.
// DOM built with textContent only.

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

const SOURCE_TEXT = {
  LIVE: "Vent instruments (LIVE)",
  LIVE_BG: "Vent B&G (LIVE B&G)",
  MANUEL: "Vent manuel utilisé (MANUEL)",
  NONE: "PAS DE VENT",
};

function fmtAge(s) {
  if (typeof s !== "number" || !Number.isFinite(s)) return "";
  const m = Math.floor(s / 60);
  return m < 1 ? "à l'instant" : `il y a ${m} min`;
}

// Pure: the manual wind form values -> request body, or an error string (French).
export function manualBody(twdText, twsText, ref) {
  const twd = Number(String(twdText).replace(",", "."));
  const tws = Number(String(twsText).replace(",", "."));
  if (String(twdText).trim() === "" || !Number.isFinite(twd) || twd < 0 || twd >= 360) {
    return { error: "TWD : entre 0 et 359,9°" };
  }
  if (String(twsText).trim() === "" || !Number.isFinite(tws) || tws < 0 || tws > 80) {
    return { error: "TWS : entre 0 et 80 nds" };
  }
  return { body: { twd, tws_kn: tws, ref: ref === "T" ? "T" : "M" } };
}

function manualPanel(ctx) {
  const box = el("section", { class: "manual-wind", id: "manual-wind", "aria-label": "Vent manuel" });
  const title = el("h3", {}, "Vent manuel");
  const source = el("div", { class: "manual-wind-source", id: "manual-wind-source" }, "—");
  const form = el("form", { class: "manual-wind-form", id: "manual-wind-form", novalidate: "" });
  const twd = el("input", {
    type: "number", name: "twd", min: "0", max: "359.9", step: "any", inputmode: "decimal",
    "aria-label": "TWD (°)",
  });
  const tws = el("input", {
    type: "number", name: "tws_kn", min: "0", max: "80", step: "any", inputmode: "decimal",
    "aria-label": "TWS (nds)",
  });
  const ref = el("select", { name: "ref", "aria-label": "Référence TWD" });
  ref.append(el("option", { value: "M" }, "°M"), el("option", { value: "T" }, "°T"));
  ref.value = "M";
  const apply = el("button", { type: "submit", class: "manual-apply" }, "Appliquer");
  const clear = el("button", { type: "button", class: "manual-clear" }, "Effacer");
  const error = el("div", { class: "manual-wind-error", id: "manual-wind-error", "aria-live": "polite" });
  const stored = el("div", { class: "manual-wind-stored", id: "manual-wind-stored" });
  const field = (label, input) => {
    const l = el("label", { class: "manual-field" });
    l.append(el("span", {}, label), input);
    return l;
  };
  form.append(field("TWD (°)", twd), field("TWS (nds)", tws), field("Réf.", ref), apply, clear);
  box.append(title, source, form, stored, error);

  function showStored(m) {
    if (!m) {
      stored.textContent = "Aucun vent manuel enregistré";
      return;
    }
    stored.textContent =
      `Enregistré : ${m.twd_entered}°${m.ref_entered} / ${m.tws_kn} nds` +
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
    let text = SOURCE_TEXT[w.source] ?? String(w.source);
    if (w.source === "MANUEL") {
      const age = fmtAge(w.manual_age_s);
      text += age ? ` — saisi ${age}` : " — âge inconnu"; // no trusted UTC (WR-03)
      if (w.stale) text += " — PÉRIMÉ";
    }
    source.textContent = text;
    source.dataset.source = w.source;
  }

  async function refresh() {
    try {
      showStored((await ctx.api.get("/api/wind/manual")).manual);
    } catch (e) {
      stored.textContent = `Vent manuel indisponible (${e.status ?? e})`;
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
      error.textContent = e.status === 422 ? "Valeurs refusées (TWD 0-359,9°, TWS 0-80 nds)" : `Échec (${e.status ?? e})`;
    }
  });
  clear.addEventListener("click", async () => {
    try {
      const nav = await ctx.api.del("/api/wind/manual");
      error.textContent = "";
      showNav(nav);
      refresh();
    } catch (e) {
      error.textContent = `Échec (${e.status ?? e})`;
    }
  });

  ctx.bus.addEventListener("nav", (ev) => showNav(ev.detail));
  showNav(ctx.latest?.("nav"));
  refresh();
  return box;
}

export function mount(ctx) {
  const root = ctx.section;
  if (!root) return;
  let schema = null;
  let current = null; // {version, settings}
  const form = el("form", { class: "reglages-form", id: "settings-form" });
  const status = el("div", { class: "reglages-status", "aria-live": "polite" });
  const title = el("h2", {}, "Réglages");
  let manual = null;
  try {
    manual = manualPanel(ctx);
  } catch (e) {
    console.error("manual wind panel", e);
  }
  root.replaceChildren(title, ...(manual ? [manual] : []), status, form);
  form.addEventListener("submit", (ev) => ev.preventDefault());

  function inputFor(key, prop) {
    const spec = fieldSpec(prop);
    const value = current?.settings?.[key];
    let input;
    if (spec.kind === "enum") {
      input = el("select", { name: key });
      for (const opt of spec.options) input.append(el("option", { value: opt }, String(opt)));
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
    input.addEventListener("change", () => save(key, spec, input));
    return input;
  }

  function render() {
    if (!schema || !current) return;
    const rows = Object.entries(schema.properties ?? {}).map(([key, prop]) => {
      const row = el("label", { class: "reglages-row" });
      row.append(el("span", { class: "reglages-label" }, prop.label ?? prop.title ?? key));
      row.append(inputFor(key, prop));
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
        status.textContent = "Valeur invalide";
        return;
      }
    } else value = input.value;
    try {
      current = await ctx.api.put("/api/settings", {
        base_version: current.version,
        patch: { [key]: value },
      });
      status.textContent = "Enregistré";
      render();
    } catch (e) {
      if (e.status === 409 && e.body) {
        current = e.body;
        render();
        status.textContent = "Modifié sur une autre tablette : rechargé, recommencez";
      } else if (e.status === 422) {
        status.textContent = "Valeur hors limites";
        render();
      } else {
        status.textContent = `Échec (${e.status ?? e})`;
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
      status.textContent = `Schéma indisponible (${e.status ?? e})`;
    });
}
