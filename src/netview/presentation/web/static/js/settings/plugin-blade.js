// The plugin child blade: one plugin's settings view in the child blade of the Settings dialog.
import { esc } from "../util.js";
import { dotHtml } from "../dot.js";
import { renderPlugin } from "./plugins-tab.js";
import { startUninstall, uninstallBlockHtml } from "./uninstall.js";
import { chipsHtml, findByKey, pluginStatus } from "./gallery.js";

const PENDING_NOTE = "This plugin loads the next time netview starts. Its settings appear after that.";

/** The body of a plugin that loads at the next start: its description, abilities, a note, and Uninstall. */
export function pendingBodyHtml(ctx, info) {
  return `${info.description ? `<p class="sub">${esc(info.description)}</p>` : ""}
        ${(info.capabilities || []).length ? `<h4>What it can do</h4><div class="chips">${chipsHtml(info.capabilities)}</div>` : ""}
        <p class="note setup" role="status">${esc(PENDING_NOTE)}</p>
        ${uninstallBlockHtml(ctx, info)}`;
}

/**
 * Open the child blade for the plugin with card key `key` (a plugin id works too). `opener` gets focus back when it closes.
 * `onClose` runs before the blade closes itself (Cancel, or its plugin being gone); a close by the blade's own X or Esc is the blade's,
 * so callers that must redraw before focus returns do it in the opener's `focus()`.
 * The footer holds Save (submits the settings form), Cancel, and a right-aligned Uninstall.
 * Returns the `{ close }` handle, or null when `key` is not an installed plugin.
 */
export function openPluginBlade(blade, ctx, key, opener, { onClose = null } = {}) {
  const first = findByKey(ctx.plugins(), key);
  if (!first) return null;
  let handle = null;
  let body = null;
  let foot = null;
  const closeSelf = () => {
    if (onClose) onClose();
    if (handle) handle.close();
  };

  const draw = () => {
    const info = findByKey(ctx.plugins(), key);
    if (!info) {
      closeSelf();
      return;
    }
    const st = pluginStatus(info);
    body.innerHTML = `<div class="pb-meta"><span class="pver">${esc(info.version)}</span>${dotHtml(st.kind, st.tip)}</div>`;
    const inner = document.createElement("div");
    body.appendChild(inner);
    const octx = { ...ctx, redraw: draw };
    if (info.state === "pending") inner.innerHTML = pendingBodyHtml(octx, info);
    else renderPlugin(inner, octx, info.id);

    // Save and Uninstall live in the footer: take the form's own Save button and the Uninstall section out of the body.
    const form = inner.querySelector("form.settings");
    if (form) {
      form.id = "pb-form";
      form.querySelector(".formfoot button[type=submit]")?.remove();
    }
    const section = inner.querySelector("section.uninstall");
    const errBox = document.createElement("div");
    errBox.className = "err uninstall-err";
    errBox.setAttribute("role", "status");
    if (section) section.replaceWith(errBox);
    foot.innerHTML = `${form ? '<button type="submit" class="primary" form="pb-form">Save</button>' : ""}
      <button type="button" data-pb-close>Cancel</button>
      ${section ? '<button type="button" class="danger" data-pb-uninstall>Uninstall</button>' : ""}`;
    foot.querySelector("[data-pb-close]").addEventListener("click", closeSelf);
    foot.querySelector("[data-pb-uninstall]")?.addEventListener("click", () => {
      startUninstall(octx, info, (text) => {
        errBox.textContent = text;
      });
    });
  };

  handle = blade.openChild({
    title: first.name,
    opener,
    body: (el) => {
      body = el;
    },
    foot: (el) => {
      foot = el;
      draw();
    },
  });
  return handle;
}
