// Settings dialog: a tab rail (Appearance, a collapsible Plugins group with Installed and Available) and a pane.
import { apiGet } from "../api.js";
import { esc } from "../util.js";
import * as util from "../util.js";
import * as icons from "../icons.js";
import { dotHtml } from "../dot.js";
import { renderAppearance } from "./appearance.js";
import { renderPlugin } from "./plugins-tab.js";
import { attention } from "./gallery.js";

const OPEN_KEY = "netview.settings.pluginsOpen";

let env = { host: null, getPlugins: () => [], setPlugins: () => {}, opener: null };
let dlg = null;
let plugins = [];
let availableCount = 0;
let active = "appearance";

/** main.js hands over the UI host, the plugin list accessors and the gear button (focus returns to it). */
export function configureSettings(options) {
  env = { ...env, ...options };
}

function readOpen() {
  try {
    return localStorage.getItem(OPEN_KEY) !== "0";
  } catch (e) {
    return true;
  }
}

function writeOpen(open) {
  try {
    localStorage.setItem(OPEN_KEY, open ? "1" : "0");
  } catch (e) {
    /* storage unavailable: the group just starts open next time */
  }
}

let pluginsOpen = readOpen();

/** The rail: Appearance, the Plugins group, and Installed / Available under it. */
export function tabsFor(list, available = 0) {
  return [
    { id: "appearance", label: "Appearance" },
    { id: "plugins", label: "Plugins", group: true },
    { id: "plugins:installed", label: "Installed", parent: "plugins", count: list.length, dot: attention(list) },
    { id: "plugins:available", label: "Available", parent: "plugins", count: available },
  ];
}

/** Where a tab id lands: {tab, overlay}. "plugin:<id>" is Installed with that plugin's overlay open. */
export function resolveTab(tabId) {
  if (tabId === "plugins") return { tab: "plugins:installed", overlay: null };
  if (typeof tabId === "string" && tabId.startsWith("plugin:") && tabId.length > 7) {
    return { tab: "plugins:installed", overlay: tabId.slice(7) };
  }
  if (tabId === "appearance" || tabId === "plugins:installed" || tabId === "plugins:available") {
    return { tab: tabId, overlay: null };
  }
  return { tab: "appearance", overlay: null };
}

function build() {
  const el = document.createElement("dialog");
  el.className = "dlg";
  el.setAttribute("aria-labelledby", "dlg-title");
  el.innerHTML = `<div class="dlg-head"><h2 id="dlg-title">Settings</h2><span class="spacer"></span>
      <button type="button" class="icon" data-close aria-label="Close settings">${icons.close}</button></div>
    <div class="dlg-body"><div class="dlg-rail" role="tablist" aria-orientation="vertical" aria-label="Settings sections"></div>
    <div class="dlg-pane" role="tabpanel" tabindex="-1"></div></div>`;
  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) el.close();
    else if (e.target === el) el.close(); // a click on the backdrop
  });
  el.addEventListener("close", () => {
    if (env.opener) env.opener.focus();
  });
  const rail = el.querySelector(".dlg-rail");
  rail.addEventListener("click", (e) => {
    if (e.target.closest("[data-group]")) {
      togglePlugins();
      return;
    }
    const t = e.target.closest("[role=tab]");
    if (t) select(t.dataset.tab);
  });
  rail.addEventListener("keydown", (e) => {
    const keys = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
    const tabs = [...rail.querySelectorAll("[role=tab]")]; // a collapsed group renders no child tabs, so they are skipped
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    let next = null;
    if (e.key in keys) next = tabs[(i + keys[e.key] + tabs.length) % tabs.length];
    else if (e.key === "Home") next = tabs[0];
    else if (e.key === "End") next = tabs[tabs.length - 1];
    if (!next) return;
    e.preventDefault();
    select(next.dataset.tab);
    next.focus();
  });
  document.body.appendChild(el);
  return el;
}

function togglePlugins() {
  pluginsOpen = !pluginsOpen;
  writeOpen(pluginsOpen);
  renderRail();
  const header = dlg.querySelector("[data-group]");
  if (header) header.focus();
}

function renderRail() {
  const rail = dlg.querySelector(".dlg-rail");
  rail.innerHTML = tabsFor(plugins, availableCount)
    .map((t) => {
      if (t.group) {
        return `<button type="button" class="rail-group" data-group aria-expanded="${pluginsOpen}"><span class="caret" aria-hidden="true">${pluginsOpen ? "\u25be" : "\u25b8"}</span>${esc(t.label)}</button>`;
      }
      if (t.parent && !pluginsOpen) return "";
      const dot = t.dot
        ? dotHtml(t.dot, t.dot === "bad" ? "A plugin needs a restart or failed" : "A plugin needs configuring", { size: "sm", still: true })
        : "";
      const count = t.count != null ? `<span class="count">${t.count}</span>` : "";
      return `<button type="button" role="tab" class="${t.parent ? "sub" : ""}" id="tab-${esc(t.id.replace(":", "-"))}" data-tab="${esc(t.id)}" aria-selected="${t.id === active}" tabindex="${t.id === active ? 0 : -1}"><span class="lbl">${esc(t.label)}</span>${dot}${count}</button>`;
    })
    .join("");
}

function ctxFor() {
  return {
    host: env.host,
    util,
    plugins: () => plugins,
    select,
    redraw: () => select(active),
    replacePlugin(info) {
      plugins = plugins.map((p) => (p.id === info.id ? info : p));
      env.setPlugins(plugins);
    },
  };
}

/** Show a tab. An unknown id falls back to Appearance; `plugins` and `plugin:<id>` open Installed. */
export function select(tabId) {
  const { tab } = resolveTab(tabId);
  active = tab;
  renderRail();
  const pane = dlg.querySelector(".dlg-pane");
  pane.setAttribute("aria-labelledby", `tab-${tab.replace(":", "-")}`);
  pane.innerHTML = "";
  const body = document.createElement("div"); // fresh element per tab so listeners never pile up
  pane.appendChild(body);
  pane.scrollTop = 0;
  if (tab === "appearance") renderAppearance(body);
  else if (tab === "plugins:installed") body.innerHTML = '<h3>Installed plugins</h3><p class="empty">Coming up.</p>';
  else body.innerHTML = '<h3>Available plugins</h3><p class="empty">Coming up.</p>';
}

/** Open the dialog on a tab: "appearance", "plugins", "plugins:installed", "plugins:available" or "plugin:<id>". */
export async function openSettings(tabId = "appearance") {
  if (!dlg) dlg = build();
  try {
    plugins = await apiGet("/api/v1/plugins");
    env.setPlugins(plugins);
  } catch (e) {
    plugins = env.getPlugins();
  }
  try {
    availableCount = (await apiGet("/api/v1/plugins/catalog")).plugins.length;
  } catch (e) {
    availableCount = 0;
  }
  select(tabId);
  if (!dlg.open) dlg.showModal();
  dlg.querySelector(".dlg-rail [aria-selected=true]").focus();
}
