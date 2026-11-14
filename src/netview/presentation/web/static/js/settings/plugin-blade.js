// The plugin child blade: one plugin's settings view in the child blade of the Settings dialog.
import { esc } from "../util.js";
import { dotHtml } from "../dot.js";
import { renderPlugin } from "./plugins-tab.js";
import { uninstallBlockHtml, wireUninstall } from "./uninstall.js";
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
 * `onClose` runs when the blade closes itself (the Close button, or its plugin being gone); a close by the blade's own X or Esc is the blade's.
 * Returns the `{ close }` handle, or null when `key` is not an installed plugin.
 */
export function openPluginBlade(blade, ctx, key, opener, { onClose = null } = {}) {
  const first = findByKey(ctx.plugins(), key);
  if (!first) return null;
  let handle = null;
  let body = null;
  const closeSelf = () => {
    if (handle) handle.close();
    if (onClose) onClose();
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
    if (info.state === "pending") {
      inner.innerHTML = pendingBodyHtml(octx, info);
      wireUninstall(inner, octx, info);
    } else {
      renderPlugin(inner, octx, info.id);
    }
  };

  handle = blade.openChild({
    title: first.name,
    opener,
    body: (el) => {
      body = el;
      draw();
    },
    foot: (el) => {
      el.innerHTML = '<button type="button" data-pb-close>Close</button>';
      el.querySelector("[data-pb-close]").addEventListener("click", closeSelf);
    },
  });
  return handle;
}
