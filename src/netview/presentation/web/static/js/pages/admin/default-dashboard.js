// Admin -> Default dashboard: the layout new users start with, who may customize, and a reset for everyone.
import { esc } from "../../util.js";
import { toast } from "../../toast.js";
import { pageHeadHtml } from "../../blade.js";
import { pencil, undo } from "../../icons.js";
import { getDefault, resetEveryone } from "../../dashboard/api.js";
import { requestDefaultEdit } from "../dashboard.js";
import { showError } from "./errors.js";

const SUB = "The layout new users start with, and what anyone gets when they choose Reset to default.";
const COMMANDS = [
  { id: "edit", label: "Edit default layout", icon: pencil },
  { id: "reset", label: "Reset everyone to the default", icon: undo },
];

/** The body lines: who may customize, and how many users have their own layout. */
export function summaryHtml(view) {
  const roles = view.roles_with_permission || [];
  const n = view.users_with_own_layout || 0;
  return `<p>Users may customize: ${roles.length ? roles.map(esc).join(", ") : "no role"}</p>
    <p>Customized layouts: ${n} ${n === 1 ? "user has" : "users have"} their own layout</p>`;
}

export function mountDefaultDashboard(el) {
  let dead = false;
  el.innerHTML = `${pageHeadHtml({ title: "Default dashboard", sub: SUB, commands: COMMANDS })}
    <div class="admin-form" data-body><p class="note">Loading…</p></div>
    <p class="err" role="alert" data-msg></p>
    <div data-confirm hidden class="confirm"><p>Remove every user's own dashboard layout? Everyone gets the default layout again. This can't be undone.</p>
      <button type="button" class="danger" data-really>Reset everyone</button>
      <button type="button" data-nope>Keep</button></div>`;
  const bodyEl = el.querySelector("[data-body]");
  const msg = el.querySelector("[data-msg]");

  async function load() {
    try {
      const view = await getDefault();
      if (!dead) bodyEl.innerHTML = summaryHtml(view);
    } catch (e) {
      if (!dead) bodyEl.innerHTML = `<p class="err">${esc(e.message)}</p>`;
    }
  }

  const confirmBox = el.querySelector("[data-confirm]");

  async function reallyReset() {
    msg.textContent = "";
    try {
      const out = await resetEveryone();
      confirmBox.hidden = true;
      const n = out && out.removed != null ? out.removed : 0;
      toast(`Reset ${n} ${n === 1 ? "layout" : "layouts"} to the default`);
      await load();
    } catch (err) {
      showError(msg, err);
    }
  }

  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-really]")) return reallyReset();
    if (e.target.closest("[data-nope]")) {
      confirmBox.hidden = true;
      return;
    }
    const b = e.target.closest("[data-cmd]");
    if (!b) return;
    msg.textContent = "";
    if (b.dataset.cmd === "edit") {
      requestDefaultEdit();
      location.hash = "#/";
    } else if (b.dataset.cmd === "reset") confirmBox.hidden = false;
  });

  load();
  return { destroy: () => (dead = true) };
}
