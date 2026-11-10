// App shell: theme, navigation, hash routing, live state.
import { apiGet, openStream } from "./api.js";
import { createUiHost } from "./slots.js";
import { esc } from "./util.js";
import { mountDashboard } from "./pages/dashboard.js";
import { mountDevices } from "./pages/devices.js";
import { mountPlugins } from "./pages/plugins.js";

const $ = (id) => document.getElementById(id);
const host = createUiHost();
let state = null;
let plugins = [];
let current = null; // {route, page}
let refreshTimer = null;

// ---------- theme
const root = document.documentElement;
try {
  const saved = localStorage.getItem("netview-theme");
  if (saved === "light" || saved === "dark") root.dataset.theme = saved;
} catch (e) {
  /* storage unavailable: follow the system theme */
}
$("btnTheme").addEventListener("click", () => {
  const now = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = now === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  try {
    localStorage.setItem("netview-theme", next);
  } catch (e) {
    /* not persisted */
  }
});

// ---------- routes
const CORE_ROUTES = [
  { path: "/", label: "Dashboard", mount: mountDashboard },
  { path: "/devices", label: "Devices", mount: mountDevices },
  { path: "/plugins", label: "Plugins", mount: mountPlugins },
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
  const path = currentPath();
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

function setState(s) {
  state = s;
  renderMeta();
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
    } else if (evt.type === "domain") {
      refreshSoon();
    }
  });
}

start();
