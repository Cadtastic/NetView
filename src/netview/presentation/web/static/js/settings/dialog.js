// Settings dialog: a tab rail (Appearance, a collapsible Plugins group with Installed and Available) and a pane.
import { apiGet, apiSend } from "../api.js";
import { toast } from "../toast.js";
import { esc } from "../util.js";
import * as util from "../util.js";
import * as icons from "../icons.js";
import { dotHtml } from "../dot.js";
import { renderAppearance } from "./appearance.js";
import { renderInstalled } from "./installed.js";
import { renderAvailable } from "./available.js";
import { attention } from "./gallery.js";
import { createInstaller } from "./installer.js";

const OPEN_KEY = "netview.settings.pluginsOpen";

let env = { host: null, getPlugins: () => [], setPlugins: () => {}, opener: null, getAuth: () => null };
let dlg = null;
let plugins = [];
let availableCount = 0;
let active = "appearance";
let installer = null; // install jobs live as long as the dialog is open, whichever tab is showing

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
export function tabsFor(list, available = 0, canInstall = true) {
  return [
    { id: "appearance", label: "Appearance" },
    { id: "plugins", label: "Plugins", group: true },
    { id: "plugins:installed", label: "Installed", parent: "plugins", count: list.length, dot: attention(list) },
    ...(canInstall ? [{ id: "plugins:available", label: "Available", parent: "plugins", count: available }] : []),
  ];
}

/** The plugins whose settings this user may change. */
export function configurable(list, auth) {
  return auth ? list.filter((p) => auth.can(p.guid + ".configure") || auth.can("core.plugins")) : list;
}

const can = (id) => {
  const auth = env.getAuth();
  return auth ? auth.can(id) : true;
};
const isAdmin = () => {
  const auth = env.getAuth();
  return auth ? auth.isAdmin : true;
};

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

function shown() {
  return configurable(plugins, env.getAuth());
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
    if (installer) installer.stop();
    installer = null;
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
    const header = rail.querySelector("[data-group]");
    if (header && document.activeElement === header && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      // from the group header, move to the adjacent visible tab in rail order
      const order = [...rail.querySelectorAll("[role=tab], [data-group]")];
      const at = order.indexOf(header) + (e.key === "ArrowDown" ? 1 : -1);
      const target = order[at];
      if (target && target.getAttribute("role") === "tab") {
        e.preventDefault();
        select(target.dataset.tab);
        target.focus();
      }
      return;
    }
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
  const activeHidden = !pluginsOpen && tabsFor(shown(), availableCount, isAdmin()).some((t) => t.id === active && t.parent);
  rail.innerHTML = tabsFor(shown(), availableCount, isAdmin())
    .map((t) => {
      if (t.group) {
        return `<button type="button" class="rail-group" data-group aria-expanded="${pluginsOpen}"><span class="caret" aria-hidden="true">${pluginsOpen ? "\u25be" : "\u25b8"}</span>${esc(t.label)}</button>`;
      }
      if (t.parent && !pluginsOpen) return "";
      const dot = t.dot
        ? dotHtml(t.dot, t.dot === "bad" ? "A plugin needs a restart or failed" : "A plugin needs configuring", { size: "sm", still: true })
        : "";
      const count = t.count != null ? `<span class="count">${t.count}</span>` : "";
      return `<button type="button" role="tab" class="${t.parent ? "sub" : ""}" id="tab-${esc(t.id.replace(":", "-"))}" data-tab="${esc(t.id)}" aria-selected="${t.id === active}" tabindex="${t.id === active || (activeHidden && t.id === "appearance") ? 0 : -1}"><span class="lbl">${esc(t.label)}</span>${dot}${count}</button>`;
    })
    .join("");
}

function getInstaller() {
  if (!installer) {
    installer = createInstaller({
      get: apiGet,
      send: apiSend,
      async onDone(id, name) {
        availableCount = Math.max(0, availableCount - 1);
        await reloadPlugins();
        toast(`${name || id} installed. Restart netview to load it.`);
      },
    });
  }
  return installer;
}

async function reloadPlugins() {
  try {
    plugins = await apiGet("/api/v1/plugins");
    env.setPlugins(plugins);
  } catch (e) {
    /* keep the list we have */
  }
  if (dlg) renderRail(); // the Installed count, dot and Available count
}

function ctxFor() {
  return {
    host: env.host,
    installer: getInstaller(),
    util,
    plugins: shown,
    can,
    select,
    redraw: () => select(active),
    setAvailable(n) {
      availableCount = n;
      if (dlg) renderRail();
    },
    reloadPlugins,
    replacePlugin(info) {
      plugins = plugins.map((p) => (p.id === info.id ? info : p));
      env.setPlugins(plugins);
      if (dlg) renderRail(); // the Installed dot and count may have changed
    },
  };
}

/** Show a tab. An unknown id falls back to Appearance; `plugins` and `plugin:<id>` open Installed. */
export function select(tabId) {
  const resolved = resolveTab(tabId);
  const overlay = resolved.overlay;
  const tab = resolved.tab === "plugins:available" && !isAdmin() ? "plugins:installed" : resolved.tab; // installing is for administrators
  active = tab;
  renderRail();
  const pane = dlg.querySelector(".dlg-pane");
  pane.setAttribute("aria-labelledby", dlg.querySelector(`#tab-${tab.replace(":", "-")}`) ? `tab-${tab.replace(":", "-")}` : "dlg-title");
  pane.innerHTML = "";
  const body = document.createElement("div"); // fresh element per tab so listeners never pile up
  pane.appendChild(body);
  pane.scrollTop = 0;
  if (tab === "appearance") renderAppearance(body);
  else if (tab === "plugins:installed") renderInstalled(body, ctxFor(), { overlayId: overlay });
  else renderAvailable(body, ctxFor());
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
    availableCount = isAdmin() ? (await apiGet("/api/v1/plugins/catalog")).plugins.length : 0;
  } catch (e) {
    availableCount = 0;
  }
  if (!dlg.open) dlg.showModal(); // before select, so an overlay opened by select stacks on top
  select(tabId);
  if (!document.querySelector("dialog.pov")) dlg.querySelector(".dlg-rail [aria-selected=true]").focus();
}
