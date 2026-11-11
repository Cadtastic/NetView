// Top navigation: one tab per route. A plugin page stays disabled while its plugin needs configuring.
import { esc } from "./util.js";
import { dotHtml } from "./dot.js";

/** True when a plugin runs (enabled and active) but its settings miss something its schema requires. */
export function needsSetup(info) {
  return !!info && info.enabled === true && info.state === "active" && info.configured === false;
}

/** Why a disabled tab is disabled; shown as its tooltip. */
export function setupHint(info) {
  return `${info.name} needs configuring in Settings before this page can be used`;
}

/**
 * Nav items for `routes` ({path, label, pluginId?}) given the plugin list.
 * Item = {path, label, on, disabled, pluginId, title}.
 */
export function navItems(routes, plugins, active) {
  const byId = new Map((plugins || []).map((p) => [p.id, p]));
  return routes.map((r) => {
    const info = r.pluginId ? byId.get(r.pluginId) : null;
    const disabled = needsSetup(info);
    return {
      path: r.path,
      label: r.label,
      pluginId: r.pluginId || null,
      on: !disabled && r.path === active,
      disabled,
      title: disabled ? setupHint(info) : "",
    };
  });
}

/** The route to show for `path`: an unknown or disabled path falls back to the first route. */
export function pickRoute(items, path) {
  return items.find((i) => i.path === path && !i.disabled) || items[0];
}

/** A disabled tab has no href; a click on it opens that plugin's settings (data-setup). */
export function navHtml(items) {
  return items
    .map((i) =>
      i.disabled
        ? `<a role="link" aria-disabled="true" tabindex="0" class="off" data-setup="${esc(i.pluginId)}" title="${esc(i.title)}">${esc(i.label)}${dotHtml("warn", "Needs configuring", { size: "sm" })}</a>`
        : `<a href="#${esc(i.path)}" class="${i.on ? "on" : ""}"${i.on ? ' aria-current="page"' : ""}>${esc(i.label)}</a>`,
    )
    .join("");
}
