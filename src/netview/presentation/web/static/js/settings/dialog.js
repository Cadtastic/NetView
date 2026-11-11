// Settings dialog: a tab rail (Appearance, Plugins, one tab per plugin) and a pane.
import { apiGet } from "../api.js";
import { esc } from "../util.js";
import * as util from "../util.js";
import * as icons from "../icons.js";
import { renderAppearance } from "./appearance.js";
import { renderOverview, renderPlugin } from "./plugins-tab.js";
import { needsSetup } from "../nav.js";

let env = { host: null, getPlugins: () => [], setPlugins: () => {}, opener: null };
let dlg = null;
let plugins = [];
let active = "appearance";

/** main.js hands over the UI host, the plugin list accessors and the gear button (focus returns to it). */
export function configureSettings(options) {
  env = { ...env, ...options };
}

export function tabsFor(list) {
  return [
    { id: "appearance", label: "Appearance" },
    { id: "plugins", label: "Plugins" },
    ...list.map((p) => ({ id: `plugin:${p.id}`, label: p.name, state: p.state, setup: needsSetup(p) })),
  ];
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
    const t = e.target.closest("[role=tab]");
    if (t) select(t.dataset.tab);
  });
  rail.addEventListener("keydown", (e) => {
    const keys = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
    const tabs = [...rail.querySelectorAll("[role=tab]")];
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

function renderRail() {
  const rail = dlg.querySelector(".dlg-rail");
  rail.innerHTML = tabsFor(plugins)
    .map(
      (t) =>
        `<button type="button" role="tab" id="tab-${esc(t.id.replace(":", "-"))}" data-tab="${esc(t.id)}" aria-selected="${t.id === active}" tabindex="${t.id === active ? 0 : -1}">${esc(t.label)}${t.state === "failed" ? ` <span class="badge">Failed</span>` : ""}${t.setup ? ` <span class="badge setup" title="Needs configuring">Set up</span>` : ""}</button>`,
    )
    .join("");
}

function ctxFor() {
  return {
    host: env.host,
    util,
    plugins: () => plugins,
    select,
    replacePlugin(info) {
      plugins = plugins.map((p) => (p.id === info.id ? info : p));
      env.setPlugins(plugins);
    },
  };
}

/** Show a tab. An unknown id falls back to Appearance. */
export function select(tabId) {
  if (!tabsFor(plugins).some((t) => t.id === tabId)) tabId = "appearance";
  active = tabId;
  renderRail();
  const pane = dlg.querySelector(".dlg-pane");
  pane.setAttribute("aria-labelledby", `tab-${tabId.replace(":", "-")}`);
  pane.innerHTML = "";
  const body = document.createElement("div"); // fresh element per tab so listeners never pile up
  pane.appendChild(body);
  pane.scrollTop = 0;
  if (tabId === "appearance") renderAppearance(body);
  else if (tabId === "plugins") renderOverview(body, ctxFor());
  else renderPlugin(body, ctxFor(), tabId.slice("plugin:".length));
}

/** Open the dialog on a tab: "appearance", "plugins" or "plugin:<id>". */
export async function openSettings(tabId = "appearance") {
  if (!dlg) dlg = build();
  try {
    plugins = await apiGet("/api/v1/plugins");
    env.setPlugins(plugins);
  } catch (e) {
    plugins = env.getPlugins();
  }
  select(tabId);
  if (!dlg.open) dlg.showModal();
  dlg.querySelector(".dlg-rail [aria-selected=true]").focus();
}
