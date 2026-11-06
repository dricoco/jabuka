// Barre tab: renders the helm bands from helm_logic.js output only (the server computes).
import { helmView } from "./helm_logic.js";

const $ = (id) => document.getElementById(id);

function setText(id, text, cls) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  if (cls !== undefined) {
    el.classList.remove("good", "warn", "bad");
    if (cls) el.classList.add(cls);
  }
}

export function render(nav) {
  const v = helmView(nav);
  setText("primary-label", v.primary.label);
  setText("primary", v.primary.value);
  setText("primary-unit", v.primary.unit);
  setText("helm-deviation", v.deviation, v.deviationClass);
  setText("helm-speed", v.speed);
  setText("helm-pct", v.pct);
  setText("helm-mark", v.mark);
  setText("helm-dtw", v.dtw);
  setText("helm-ttw", v.ttw);
  setText("helm-btw", v.btw);
  setText("helm-countdown", v.countdown);
  setText("helm-other", v.otherTack);
  return v;
}

export function mount(ctx) {
  ctx.bus.addEventListener("nav", (ev) => render(ev.detail));
}
