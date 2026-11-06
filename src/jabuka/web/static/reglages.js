// Réglages tab: a form generated from GET /api/settings/schema (French labels in "label"), saving
// one field per change with PUT {base_version, patch}; a 409 (edited on another tablet) reloads.
// Plan 02-03 adds the manual wind form in this file.

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

export function mount(ctx) {
  const root = ctx.section;
  if (!root) return;
  let schema = null;
  let current = null; // {version, settings}
  const form = el("form", { class: "reglages-form", id: "settings-form" });
  const status = el("div", { class: "reglages-status", "aria-live": "polite" });
  const title = el("h2", {}, "Réglages");
  root.replaceChildren(title, status, form);
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
