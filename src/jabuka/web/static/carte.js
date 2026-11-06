// Carte tab: one-tap Course A / B (CRSE-01), previous/next mark, the course list and the
// "sides to confirm" warning. DOM built with textContent only (mark names are data, T-02-01-02).
// Plan 02-04 adds map editing, "Finir ici" and the rounding banner in this file.

const SIDE = { port: "bâbord", stbd: "tribord", none: "" };

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  if (text !== undefined) e.textContent = text;
  return e;
}

export function mount(ctx) {
  const root = ctx.section;
  if (!root) return;
  let course = null;
  let busy = false;

  const panel = el("div", { class: "carte-panel" });
  const tpl = el("div", { class: "carte-row" });
  const btnA = el("button", { type: "button", class: "big", "data-template": "A" }, "Parcours A");
  const btnB = el("button", { type: "button", class: "big", "data-template": "B" }, "Parcours B");
  tpl.append(btnA, btnB);
  const nav = el("div", { class: "carte-row" });
  const btnPrev = el("button", { type: "button", class: "big", id: "course-prev" }, "Préc.");
  const btnNext = el("button", { type: "button", class: "big", id: "course-next" }, "Suiv.");
  nav.append(btnPrev, btnNext);
  const warn = el("div", { class: "carte-warn", id: "sides-warning" }, "Côtés à confirmer (IC)");
  const status = el("div", { class: "carte-status", "aria-live": "polite" });
  const list = el("ol", { class: "carte-list", id: "course-list" });
  panel.append(tpl, nav, warn, status, list);
  root.replaceChildren(panel);

  function render() {
    if (!course) return;
    btnA.classList.toggle("active", course.template === "A");
    btnB.classList.toggle("active", course.template === "B");
    warn.hidden = Boolean(course.sides_confirmed);
    const items = course.seq.map((leg, i) => {
      const mark = course.marks[leg.mark_id];
      const li = el("li");
      if (i === course.active_idx) li.className = "active";
      else if (i < course.active_idx) li.className = "done";
      const name = el("span", { class: "name" }, mark ? mark.name : leg.mark_id);
      const side = SIDE[leg.side] ?? "";
      const meta = el("span", { class: "meta" }, side ? `${side} · ${leg.radius_nm} nm` : "");
      li.append(name, meta);
      return li;
    });
    list.replaceChildren(...items);
  }

  async function act(fn) {
    if (busy) return;
    busy = true;
    status.textContent = "";
    try {
      course = await fn();
      render();
    } catch (e) {
      if (e.status === 409 && e.body) {
        course = e.body;
        render();
        status.textContent = "Parcours modifié ailleurs : rechargé";
      } else {
        status.textContent = `Échec (${e.status ?? e})`;
      }
    } finally {
      busy = false;
    }
  }

  for (const b of [btnA, btnB]) {
    b.addEventListener("click", () =>
      act(() =>
        ctx.api.post("/api/course/select", {
          template: b.dataset.template,
          base_version: course ? course.version : null,
        }),
      ),
    );
  }
  btnPrev.addEventListener("click", () => act(() => ctx.api.post("/api/course/prev")));
  btnNext.addEventListener("click", () => act(() => ctx.api.post("/api/course/next")));

  ctx.bus.addEventListener("course", (ev) => {
    course = ev.detail;
    render();
  });
  course = ctx.latest?.("course") ?? null;
  render();
}
