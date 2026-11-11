// Top navigation: one tab per route. A plugin page stays disabled while its plugin needs configuring.
import { esc } from "./util.js";

/** True when a plugin runs (enabled and active) but its settings miss something its schema requires. */
export function needsSetup(info) {
  return !!info && info.enabled === true && info.state === "active" && info.configured === false;
}

/** Why a disabled tab is disabled; shown as its tooltip. */
export function setupHint(info) {
  return `${info.name} needs configuring in Settings before this page can be used`;
}

/** The reason a route's page is unavailable, or null; a missing or throwing check counts as available. */
function unavailableReason(route) {
  if (typeof route.unavailable !== "function") return null;
  try {
    return route.unavailable() || null;
  } catch (e) {
    return null;
  }
}

/**
 * Nav items for `routes` ({path, label, pluginId?, unavailable?}) given the plugin list.
 * A route may carry `unavailable: () => string | null`; a reason disables the tab and becomes its title.
 * Item = {path, label, on, disabled, pluginId, title}.
 */
export function navItems(routes, plugins, active) {
  const byId = new Map((plugins || []).map((p) => [p.id, p]));
  return routes.map((r) => {
    const info = r.pluginId ? byId.get(r.pluginId) : null;
    const setup = needsSetup(info);
    const reason = setup ? null : unavailableReason(r);
    const disabled = setup || reason != null;
    return {
      path: r.path,
      label: r.label,
      pluginId: r.pluginId || null,
      on: !disabled && r.path === active,
      disabled,
      title: setup ? setupHint(info) : reason || "",
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
        ? `<a role="link" aria-disabled="true" tabindex="0" class="off" data-setup="${esc(i.pluginId)}" title="${esc(i.title)}">${esc(i.label)}</a>`
        : `<a href="#${esc(i.path)}" class="${i.on ? "on" : ""}"${i.on ? ' aria-current="page"' : ""}>${esc(i.label)}</a>`,
    )
    .join("");
}
