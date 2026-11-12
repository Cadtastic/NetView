// The plugin settings overlay: a second modal dialog on top of Settings, holding one plugin's settings view.
import { esc } from "../util.js";
import * as icons from "../icons.js";
import { dotHtml } from "../dot.js";
import { renderPlugin } from "./plugins-tab.js";
import { chipsHtml, findByKey, monogram, pluginStatus } from "./gallery.js";

const PENDING_NOTE = "This plugin loads the next time netview starts. Its settings appear after that.";

/**
 * Open the overlay for the plugin with card key `key` (a plugin id works too). Focus returns to `returnFocus` on close, then `onClose` runs.
 * Returns the dialog element, or null when the id is not an installed plugin.
 */
export function openPluginOverlay(ctx, key, returnFocus, { onClose = null } = {}) {
  if (!findByKey(ctx.plugins(), key)) return null;
  const el = document.createElement("dialog");
  el.className = "pov";
  el.setAttribute("aria-labelledby", "pov-title");
  el.innerHTML = `<div class="pov-head"></div><div class="pov-body"></div>`;
  const head = el.querySelector(".pov-head");
  const body = el.querySelector(".pov-body");

  const draw = () => {
    const info = findByKey(ctx.plugins(), key);
    if (!info) {
      el.close();
      return;
    }
    const st = pluginStatus(info);
    head.innerHTML = `<span class="mono" aria-hidden="true">${esc(monogram(info.name))}</span>
      <h2 id="pov-title">${esc(info.name)}</h2><span class="pver">${esc(info.version)}</span>${dotHtml(st.kind, st.tip)}
      <span class="spacer"></span>
      <button type="button" class="icon" data-close aria-label="Close plugin settings">${icons.close}</button>`;
    body.innerHTML = "";
    const inner = document.createElement("div");
    body.appendChild(inner);
    if (info.state === "pending") {
      inner.innerHTML = `${info.description ? `<p class="sub">${esc(info.description)}</p>` : ""}
        ${(info.capabilities || []).length ? `<h4>What it can do</h4><div class="chips">${chipsHtml(info.capabilities)}</div>` : ""}
        <p class="note setup" role="status">${esc(PENDING_NOTE)}</p>`;
    } else {
      renderPlugin(inner, { ...ctx, redraw: draw }, info.id);
    }
  };

  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]") || e.target === el) el.close(); // the backdrop is the dialog itself
  });
  el.addEventListener("close", () => {
    el.remove();
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
    if (onClose) onClose();
  });
  document.body.appendChild(el);
  draw();
  el.showModal();
  const first = el.querySelector("[data-close]");
  if (first) first.focus();
  return el;
}
