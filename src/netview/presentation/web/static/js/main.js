// App shell: theme, navigation, hash routing, live state.
import { apiGet, apiSend, openStream } from "./api.js";
import { createUiHost } from "./slots.js";
import { esc } from "./util.js";
import { mountDashboard } from "./pages/dashboard.js";
import { mountDevices } from "./pages/devices.js";
import * as icons from "./icons.js";
import { BUILTIN_THEMES, applyTheme, loadThemePref, resolveTheme } from "./theme.js";
import { configureSettings, openSettings } from "./settings/dialog.js";
import { scanButtonState, scanErrorMessage } from "./scan.js";
import { toast } from "./toast.js";

const $ = (id) => document.getElementById(id);
const host = createUiHost();
let state = null;
let plugins = [];
let current = null; // {route, page}
let refreshTimer = null;
let scanning = false;

// ---------- theme and settings
// Apply a saved built-in theme straight away; the full list (with user themes) replaces it once fetched.
applyTheme(resolveTheme(loadThemePref(), BUILTIN_THEMES));
$("btnSettings").innerHTML = icons.gear;
configureSettings({
  host,
  opener: $("btnSettings"),
  getPlugins: () => plugins,
  setPlugins: (list) => {
    plugins = list;
  },
});
$("btnSettings").addEventListener("click", () => openSettings("appearance"));
apiGet("/api/v1/themes")
  .then((data) => applyTheme(resolveTheme(loadThemePref(), data.themes)))
  .catch(() => {});

// ---------- routes
const CORE_ROUTES = [
  { path: "/", label: "Dashboard", mount: mountDashboard },
  { path: "/devices", label: "Devices", mount: mountDevices },
];

function routes() {
  const pages = host.get("page").map((spec) => ({
    path: `/p/${spec.pluginId}/${spec.id}`,
    label: spec.title || spec.id,
    mount: (el, ctx) => mountPluginPage(spec, el, ctx),
  }));
  return [...CORE_ROUTES, ...pages];
}

function mountPluginPage(spec, el, ctx) {
  let handle = null;
  try {
    handle = spec.mount(el, ctx) || null;
  } catch (e) {
    console.error(`Plugin "${spec.pluginId}" page failed`, e);
    el.innerHTML = `<div class="card"><p class="err">This page failed: ${esc(e.message)}</p></div>`;
  }
  return {
    update: (s) => handle && handle.update && handle.update(s),
    destroy: () => handle && handle.destroy && handle.destroy(),
  };
}

function currentPath() {
  const h = location.hash.replace(/^#/, "");
  return h || "/";
}

function renderNav(active) {
  $("nav").innerHTML = routes()
    .map((r) => `<a href="#${esc(r.path)}" class="${r.path === active ? "on" : ""}"${r.path === active ? ' aria-current="page"' : ""}>${esc(r.label)}</a>`)
    .join("");
}

function route() {
  const all = routes();
  let path = currentPath();
  if (path === "/plugins") {
    // The old Plugins page now lives in the settings dialog; leave the address on the page we were on.
    openSettings("plugins");
    const back = current ? current.route.path : "/";
    history.replaceState(null, "", "#" + back);
    if (current) return;
    path = back;
  }
  const found = all.find((r) => r.path === path) || all[0];
  renderNav(found.path);
  if (current && current.page.destroy) current.page.destroy();
  const view = $("view");
  view.innerHTML = "";
  current = { route: found, page: found.mount(view, ctx) || {} };
  if (state && current.page.update) current.page.update(state);
}

const ctx = {
  host,
  getState: () => state,
  getPlugins: () => plugins,
  refresh: () => refreshSoon(0),
  reloadPlugins: async () => {
    plugins = await apiGet("/api/v1/plugins");
    return plugins;
  },
};

// ---------- state
function renderMeta() {
  if (!state) return;
  const h = state.host;
  $("meta").innerHTML = `<span><b>This device</b> ${esc(h.ip)} (${esc(h.hostname)})</span>`;
}

/** Keep the Scan now button in step with the latest state and any click in flight. */
function renderScan() {
  const b = scanButtonState(state, scanning);
  const el = $("btnScan");
  el.disabled = b.disabled;
  el.textContent = b.label;
  el.title = b.title;
}

async function scanNow() {
  if (scanning) return;
  scanning = true;
  renderScan();
  try {
    await apiSend("POST", "/api/v1/scan");
  } catch (e) {
    toast(scanErrorMessage(e), "warn"); // 409 already running, 503 no network
  } finally {
    scanning = false;
    refreshSoon(0);
    renderScan();
  }
}
$("btnScan").addEventListener("click", scanNow);

function setState(s) {
  state = s;
  renderMeta();
  renderScan();
  if (current && current.page.update) current.page.update(state);
}

async function refresh() {
  try {
    setState(await apiGet("/api/v1/state"));
  } catch (e) {
    setLive(false, "Cannot reach netview");
  }
}

function refreshSoon(ms = 400) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, ms);
}

function setLive(ok, text) {
  $("live").classList.toggle("stale", !ok);
  $("liveText").textContent = text;
}

/** Draw one ring on the live dot; removing and re-adding the class restarts the animation. */
function pulse() {
  const el = $("live");
  el.classList.remove("pulse");
  void el.offsetWidth;
  el.classList.add("pulse");
}

// A plugin that fetched fresh data asks for a redraw of the current page.
host.setRenderer(() => {
  if (state && current && current.page.update) current.page.update(state);
});

async function start() {
  try {
    plugins = await apiGet("/api/v1/plugins");
  } catch (e) {
    plugins = [];
  }
  await host.loadPlugins(plugins);
  await refresh();
  route();
  window.addEventListener("hashchange", route);
  openStream((evt) => {
    if (evt.type === "open") {
      setLive(true, "Live");
      refreshSoon(0);
    } else if (evt.type === "down") {
      setLive(false, "Reconnecting…");
    } else if (evt.type === "poll") {
      setLive(false, "Polling");
      setState(evt.state);
      pulse();
    } else if (evt.type === "domain" || evt.type === "state") {
      pulse();
      refreshSoon();
    }
  });
}

start();
