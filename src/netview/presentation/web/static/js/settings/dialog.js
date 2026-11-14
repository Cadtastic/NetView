// Settings dialog on the blade layout: a side menu (Personal: Appearance, My dashboard; Plugins: Installed, Available)
// and a page. A plugin's settings open in the child blade.
import { apiGet, apiSend } from "../api.js";
import { toast } from "../toast.js";
import * as util from "../util.js";
import * as icons from "../icons.js";
import { createBlade, pageHeadHtml } from "../blade.js";
import { renderAppearance } from "./appearance.js";
import { renderInstalled } from "./installed.js";
import { renderAvailable } from "./available.js";
import { mountMyDashboard } from "./my-dashboard.js";
import { createInstaller } from "./installer.js";
import { availableCount as fetchAvailableCount } from "./uninstall.js";

// Earlier versions stored "1" / "0" (Plugins open / collapsed) under this key; the blade stores the names of folded groups.
const OPEN_KEY = "netview.settings.pluginsOpen";

let env = { host: null, getPlugins: () => [], setPlugins: () => {}, removePlugin: () => {}, opener: null, getAuth: () => null };
let dlg = null;
let blade = null;
let page = null; // the section handle on the blade page ({destroy} or null)
let plugins = [];
let availableCount = 0;
let active = "appearance";
let installer = null; // install jobs live as long as the dialog is open, whichever section is showing

/** main.js hands over the UI host, the plugin list accessors and the gear button (focus returns to it). */
export function configureSettings(options) {
  env = { ...env, ...options };
}

/** The blade's stored value for an old `pluginsOpen` value: "0" folds Plugins, "1" opens it; anything else is left alone (null). */
export function migratePluginsOpen(raw) {
  if (raw === "0") return JSON.stringify(["Plugins"]);
  if (raw === "1") return "[]";
  return null;
}

function migrateOpenPref() {
  try {
    const next = migratePluginsOpen(localStorage.getItem(OPEN_KEY));
    if (next !== null) localStorage.setItem(OPEN_KEY, next);
  } catch (e) {
    /* storage unavailable: the group just starts open */
  }
}

/** The side menu: Personal (Appearance, My dashboard) and Plugins (Installed, Available). */
export function settingsMenu(list, available = 0, canInstall = true, canCustomize = true) {
  return [
    {
      group: "Personal",
      items: [
        { id: "appearance", label: "Appearance", icon: icons.palette },
        ...(canCustomize ? [{ id: "dashboard", label: "My dashboard", icon: icons.layoutDashboard }] : []),
      ],
    },
    {
      group: "Plugins",
      items: [
        { id: "plugins:installed", label: "Installed", count: list.length, icon: icons.puzzle },
        ...(canInstall ? [{ id: "plugins:available", label: "Available", count: available, icon: icons.download }] : []),
      ],
    },
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

/** Where a tab id lands: {tab, overlay}. "plugin:<id>" is Installed with that plugin's child blade open. */
export function resolveTab(tabId) {
  if (tabId === "plugins") return { tab: "plugins:installed", overlay: null };
  if (typeof tabId === "string" && tabId.startsWith("plugin:") && tabId.length > 7) {
    return { tab: "plugins:installed", overlay: tabId.slice(7) };
  }
  if (tabId === "appearance" || tabId === "dashboard" || tabId === "plugins:installed" || tabId === "plugins:available") {
    return { tab: tabId, overlay: null };
  }
  return { tab: "appearance", overlay: null };
}

function shown() {
  return configurable(plugins, env.getAuth());
}

function menu() {
  return settingsMenu(shown(), availableCount, isAdmin(), can("core.dashboard"));
}

/** Keep the menu counts current after the plugin list or the Available count changed. */
function refreshMenu() {
  if (blade) blade.setMenu(menu());
}

function build() {
  const el = document.createElement("dialog");
  el.className = "dlg";
  el.setAttribute("aria-labelledby", "dlg-title");
  el.innerHTML = `<div class="dlg-head"><h2 id="dlg-title">Settings</h2><span class="spacer"></span>
      <button type="button" class="icon" data-close aria-label="Close settings">${icons.close}</button></div>
    <div class="blade-crumb dlg-crumb"></div>
    <div class="dlg-blade"></div>`;
  el.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) el.close();
    else if (e.target === el) el.close(); // a click on the backdrop
  });
  el.addEventListener("close", () => {
    if (installer) installer.stop();
    installer = null;
    stopPage();
    if (blade) blade.destroy();
    blade = null;
    if (env.opener) env.opener.focus();
  });
  document.body.appendChild(el);
  return el;
}

function stopPage() {
  if (page && page.destroy) page.destroy();
  page = null;
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
  refreshMenu(); // the Installed and Available counts
}

function ctxFor() {
  return {
    host: env.host,
    installer: getInstaller(),
    util,
    plugins: shown,
    can,
    isAdmin,
    select: (id) => blade && blade.select(id),
    redraw: () => blade && blade.select(active),
    setAvailable(n) {
      availableCount = n;
      refreshMenu();
    },
    reloadPlugins,
    /** The server removed `info`: forget it everywhere with no reload, then refresh the Available count. */
    removePlugin(info) {
      plugins = plugins.filter((p) => p.id !== info.id);
      env.setPlugins(plugins);
      env.removePlugin(info.id); // the shell drops its slots, pages and nav tab
      refreshMenu();
    },
    finishUninstall(info) {
      this.removePlugin(info);
      // not awaited: the child blade must close now; the Available count follows when the catalog answers
      fetchAvailableCount()
        .then((n) => {
          if (n !== null) {
            availableCount = n;
            refreshMenu();
          }
        })
        .catch((e) => console.warn("could not refresh the Available count", e));
    },
    replacePlugin(info) {
      plugins = plugins.map((p) => (p.id === info.id ? info : p));
      env.setPlugins(plugins);
      refreshMenu(); // the Installed count may have changed
    },
  };
}

const HEADS = {
  appearance: { title: "Appearance", sub: "Choose how NetView looks." },
  "plugins:installed": { title: "Installed plugins", sub: "Open a plugin to change its settings." },
  "plugins:available": { title: "Available plugins", sub: "" },
};

/** Fill the blade page for section `id`. `overlay` is a plugin whose child blade opens at once (Installed only). */
function fillPage(id, el, api, overlay) {
  stopPage();
  active = id;
  if (id === "dashboard") {
    page = mountMyDashboard(el);
    return;
  }
  const head = HEADS[id] || HEADS.appearance;
  el.innerHTML = `${pageHeadHtml(head)}<div data-body></div>`;
  const body = el.querySelector("[data-body]"); // a fresh element per section, so listeners never pile up on the shared page
  if (id === "plugins:installed") renderInstalled(body, ctxFor(), { blade: api, overlayId: overlay });
  else if (id === "plugins:available") renderAvailable(body, ctxFor());
  else renderAppearance(body);
}

/** Open the dialog on a section: "appearance", "dashboard", "plugins", "plugins:installed", "plugins:available" or "plugin:<id>". */
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
  if (!dlg.open) dlg.showModal();
  const resolved = resolveTab(tabId);
  let tab = resolved.tab;
  if (tab === "plugins:available" && !isAdmin()) tab = "plugins:installed"; // installing is for administrators
  if (tab === "dashboard" && !can("core.dashboard")) tab = "appearance";
  let pending = resolved.overlay; // opens with the first fill of Installed only
  stopPage();
  if (blade) blade.destroy();
  migrateOpenPref();
  blade = createBlade(dlg.querySelector(".dlg-blade"), {
    crumbRoot: "Settings",
    crumbHost: dlg.querySelector(".dlg-crumb"),
    menu: menu(),
    initial: tab,
    storageKey: OPEN_KEY,
    onSelect: (id, el, api) => {
      const overlay = id === "plugins:installed" ? pending : null;
      pending = null;
      fillPage(id, el, api, overlay);
    },
  });
  if (!dlg.querySelector(".blade-child.open")) dlg.querySelector(".blade-item.on")?.focus();
}
