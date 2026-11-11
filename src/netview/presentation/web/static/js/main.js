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
import { createMetricsClient } from "./metrics.js";
import { configureReport, openReport, updateReport } from "./report/dialog.js";
import { navHtml, navItems, nextNavMarkup, pickRoute } from "./nav.js";

const $ = (id) => document.getElementById(id);
const host = createUiHost();
const metrics = createMetricsClient(apiGet);
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
    renderNav(current ? current.route.path : currentPath()); // a plugin that is now configured gets its tab back
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
    pluginId: spec.pluginId,
    unavailable: spec.unavailable,
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

let navShown = null;
function renderNav(active) {
  const markup = nextNavMarkup(navShown, navHtml(navItems(routes(), plugins, active)));
  if (markup === null) return;
  navShown = markup;
  $("nav").innerHTML = markup;
}

// A disabled tab (its plugin needs configuring) opens that plugin's settings instead.
function openSetup(e) {
  const t = e.target.closest("[data-setup]");
  if (!t) return;
  if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
  e.preventDefault();
  openSettings(`plugin:${t.dataset.setup}`);
}
$("nav").addEventListener("click", openSetup);
$("nav").addEventListener("keydown", openSetup);

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
  const pick = pickRoute(navItems(all, plugins, path), path);
  const found = all.find((r) => r.path === pick.path);
  if (found.path !== path && all.some((r) => r.path === path)) history.replaceState(null, "", "#" + found.path); // a disabled tab
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
  openReport: (ip, options) => openReport(ip, options),
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
  state.metrics = metrics.cache; // name -> [[t_ms, value|null], ...]; set before any page draws
  renderMeta();
  renderScan();
  if (current && current.page.update) current.page.update(state);
  updateReport(state);
}

/** Fetch the metrics delta. A failure keeps the old cache, and the charts keep what they had. */
async function refreshMetrics() {
  try {
    await metrics.refresh();
    return true;
  } catch (e) {
    return false;
  }
}

async function refresh() {
  try {
    const [s] = await Promise.all([apiGet("/api/v1/state"), refreshMetrics()]);
    setState(s);
  } catch (e) {
    setLive(false, "Cannot reach NetView");
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
// The nav is redrawn too: a page's unavailable() may have changed, and a now-disabled page falls back.
host.setRenderer(() => {
  if (!current) return;
  const path = current.route.path;
  const items = navItems(routes(), plugins, path);
  renderNav(path);
  if (items.some((i) => i.path === path && i.disabled)) return route();
  if (state && current.page.update) current.page.update(state);
});
host.setReportOpener((ip, options) => openReport(ip, options));
configureReport({ host, getState: () => state, refresh: () => refreshSoon(0) });

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
      refreshMetrics().then((ok) => ok && state && setState(state)); // the polling fallback has no other trigger
    } else if (evt.type === "domain" || evt.type === "state") {
      pulse();
      refreshSoon();
    }
  });
}

start();
