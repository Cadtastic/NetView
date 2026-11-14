// Settings -> My dashboard: the signed-in user's saved dashboard layout, with a way back to the default.
import { esc, fmtAgo } from "../util.js";
import { toast } from "../toast.js";
import { pageHeadHtml } from "../blade.js";
import { undo } from "../icons.js";
import { getLayout, resetLayout } from "../dashboard/api.js";

const SUB = "Your saved layout. Change it on the dashboard with Customize.";
const COMMANDS = [{ id: "reset", label: "Reset to default", icon: undo }];
const GROUPING = { none: "None", plugin: "By plugin", plugin_type: "By plugin type" };

/** The body lines for a `{layout, source, updated_ms}` view. */
export function summaryHtml(view, now = Date.now()) {
  const layout = (view && view.layout) || {};
  const own = !!view && view.source === "user";
  const which = own ? `Your own (saved ${fmtAgo(view.updated_ms, now)})` : "The default";
  const hidden = Array.isArray(layout.hidden) ? layout.hidden.length : 0;
  return `<p>Layout: ${esc(which)}</p>
    <p>Grouping: ${esc(GROUPING[layout.group] || GROUPING.none)}</p>
    <p>Hidden cards: ${hidden}</p>`;
}

export function mountMyDashboard(el) {
  let dead = false;
  el.innerHTML = `${pageHeadHtml({ title: "My dashboard", sub: SUB, commands: COMMANDS })}
    <div class="admin-form" data-body><p class="note">Loading…</p></div>
    <p class="err" role="alert" data-msg></p>`;
  const bodyEl = el.querySelector("[data-body]");
  const msg = el.querySelector("[data-msg]");
  const resetBtn = el.querySelector('[data-cmd="reset"]');
  resetBtn.disabled = true;

  function show(view) {
    if (dead) return;
    bodyEl.innerHTML = summaryHtml(view);
    resetBtn.disabled = view.source !== "user";
  }

  async function load() {
    try {
      show(await getLayout());
    } catch (e) {
      if (!dead) bodyEl.innerHTML = `<p class="err">${esc(e.message)}</p>`;
    }
  }

  const onClick = async (e) => {
    const b = e.target.closest('[data-cmd="reset"]');
    if (!b || b.disabled) return;
    msg.textContent = "";
    b.disabled = true;
    try {
      show(await resetLayout());
      toast("Dashboard reset to the default layout");
    } catch (err) {
      if (!dead) {
        msg.textContent = err.message;
        b.disabled = false;
      }
    }
  };
  el.addEventListener("click", onClick);

  load();
  return {
    destroy() {
      dead = true;
      el.removeEventListener("click", onClick); // the page element outlives the section
    },
  };
}
