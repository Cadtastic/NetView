// The per-plugin settings view (header, chips, settings form, plugin-provided sections).
import { apiGet, apiSend } from "../api.js";
import { esc } from "../util.js";
import { toast } from "../toast.js";
import {
  collectValues, fieldsFromSchema, formBodyHtml, requiredNow, shownNow, tabListHtml, tabsOf, validateSettings,
} from "./schema-form.js";
import { needsSetup } from "../nav.js";

// The tab last chosen on each plugin's settings form, so a redraw after saving stays on it.
const chosenTab = new Map();

/** The tab to show: the remembered one if the form still has it, else the first. Null for a form without tabs. */
export function activeTab(tabs, remembered) {
  if (!tabs.length) return null;
  return tabs.includes(remembered) ? remembered : tabs[0];
}

/** The tab reached from `current` with an arrow, Home or End key; null for any other key. */
export function tabAfterKey(tabs, current, key) {
  const i = tabs.indexOf(current);
  if (i < 0) return null;
  if (key === "ArrowRight") return tabs[(i + 1) % tabs.length];
  if (key === "ArrowLeft") return tabs[(i - 1 + tabs.length) % tabs.length];
  if (key === "Home") return tabs[0];
  if (key === "End") return tabs[tabs.length - 1];
  return null;
}

export const CAPABILITY_LABELS = {
  discovery: "Finds devices",
  identity: "Names devices",
  health: "Checks reachability",
  traffic: "Measures traffic",
  destinations: "Sees destinations",
  inspection: "Inspects devices",
  local_host: "Reads this device",
  api: "Adds API endpoints",
  web_ui: "Adds to the web page",
  storage: "Keeps its own data",
  jobs: "Runs in the background",
};

export const PERMISSION_LABELS = {
  "devices:read": "Read devices",
  "names:write": "Suggest device names",
  "types:write": "Suggest device types",
  "traffic:write": "Record traffic",
  "storage:own": "Its own tables",
  api: "API endpoints",
  ui: "Web page additions",
  "network:probe": "Probe the network",
};

const STATE_TEXT = { active: "Active", disabled: "Off", failed: "Failed" };

const label = (table, key) => table[key] || key;
const chips = (items, table) => items.map((k) => `<span class="chip" title="${esc(k)}">${esc(label(table, k))}</span>`).join("");

function stateBadge(info) {
  return `<span class="pstate ${esc(info.state)}">${esc(STATE_TEXT[info.state] || info.state)}</span>`;
}

function enableSwitch(info, text) {
  const canToggle = info.state !== "failed";
  return `<label class="switch"><input type="checkbox" data-enable="${esc(info.id)}" ${info.enabled ? "checked" : ""} ${canToggle ? "" : "disabled"}><span class="track"></span>${esc(text)}</label>`;
}

/** Turn a plugin on or off; returns the updated info and tells the dialog. */
export async function toggle(ctx, id, enabled, box) {
  try {
    const info = await apiSend("PATCH", `/api/v1/plugins/${encodeURIComponent(id)}`, { enabled });
    ctx.replacePlugin(info);
    if (info.restart_required) toast("Restart NetView to apply", "warn");
    return info;
  } catch (err) {
    if (box) box.textContent = err.message;
    toast(err.message, "bad");
    return null;
  }
}

const SETUP_NOTE =
  "Fill in the required settings (marked *) and save. Until then its page in the top bar stays disabled.";

/** Mark each `.field[data-field]` named in `errors` invalid with its message; clear the others.
 * Returns the messages for names the form has no field for. */
export function showFieldErrors(form, errors) {
  const shown = new Set();
  for (const el of form.querySelectorAll(".field[data-field]")) {
    const name = el.dataset.field;
    const msg = el.hidden ? undefined : errors[name]; // a hidden field's message goes in the summary line
    setFieldError(el, msg);
    if (msg) shown.add(name);
  }
  return Object.entries(errors)
    .filter(([n]) => !shown.has(n))
    .map(([n, m]) => `${n}: ${m}`);
}

function setFieldError(el, msg) {
  el.classList.toggle("invalid", !!msg);
  const line = el.querySelector(".field-err");
  if (line) line.textContent = msg || "";
  const input = el.querySelector("input, select, textarea");
  if (!input) return;
  if (msg) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

/** One plugin's tab. */
export function renderPlugin(pane, ctx, id) {
  const info = ctx.plugins().find((p) => p.id === id);
  if (!info) {
    pane.innerHTML = '<p class="empty">That plugin is no longer installed.</p>';
    return;
  }
  const schema = info.settings_schema;
  const fields = fieldsFromSchema(schema);
  const uiError = ctx.host.errors[id];
  const required = requiredNow(schema, info.settings);
  const tabs = tabsOf(schema, fields);
  let tab = activeTab(tabs, chosenTab.get(id));
  const form = fields.length
    ? `${tabs.length ? tabListHtml(tabs, tab) : ""}<form class="settings" autocomplete="off" novalidate>${formBodyHtml(
        id,
        schema,
        fields,
        info.settings,
        required,
        shownNow(schema, fields, info.settings),
        tab,
      )}<div class="formfoot"><button type="submit" class="primary">Save settings</button><span class="err" role="status"></span></div></form>`
    : '<p class="note">This plugin has no settings.</p>';
  pane.innerHTML = `<div class="plugin-head">
      <h3>${esc(info.name)}</h3><span class="ver">${esc(info.version)}</span>${stateBadge(info)}
      <span class="spacer"></span>
      ${info.restart_required ? '<span class="badge restart">Restart NetView to apply</span>' : ""}
      ${enableSwitch(info, "Enabled")}
    </div>
    <div class="err toggle-err" role="status"></div>
    ${info.description ? `<p class="sub">${esc(info.description)}</p>` : ""}
    ${info.error ? `<p class="err">${esc(info.error)}</p>` : ""}
    ${uiError ? `<p class="err">Its interface failed to load: ${esc(uiError)}</p>` : ""}
    ${needsSetup(info) ? `<p class="note setup" role="status"><b>Needs configuring.</b> ${esc(SETUP_NOTE)}</p>` : ""}
    ${info.capabilities.length ? `<h4>What it can do</h4><div class="chips">${chips(info.capabilities, CAPABILITY_LABELS)}</div>` : ""}
    ${info.permissions.length ? `<h4>Access it asks for</h4><div class="chips">${chips(info.permissions, PERMISSION_LABELS)}</div>` : ""}
    ${form}
    <div class="sections"></div>`;

  pane.querySelector("[data-enable]").addEventListener("change", async (e) => {
    const box = pane.querySelector(".toggle-err");
    box.textContent = "";
    const updated = await toggle(ctx, id, e.target.checked, box);
    if (updated) ctx.redraw();
    else e.target.checked = !e.target.checked;
  });

  // Tabs: show the chosen tab's panel and the plugin sections that name it. A section without a tab always shows.
  const showTab = (name, focus = false) => {
    tab = name;
    chosenTab.set(id, name);
    for (const b of pane.querySelectorAll(".ptabs [role=tab]")) {
      const on = b.dataset.tab === name;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    }
    for (const el of pane.querySelectorAll(".ftab, .sections > [data-tab]")) el.hidden = el.dataset.tab !== name;
  };
  const tabList = pane.querySelector(".ptabs");
  if (tabList) {
    tabList.addEventListener("click", (e) => {
      const b = e.target.closest("[role=tab]");
      if (b) showTab(b.dataset.tab);
    });
    tabList.addEventListener("keydown", (e) => {
      const next = tabAfterKey(tabs, tab, e.key);
      if (!next) return;
      e.preventDefault();
      showTab(next, true);
    });
  }

  const formEl = pane.querySelector("form.settings");
  if (formEl) {
    let stored = info.settings; // the saved (masked) settings; a blank secret keeps its stored value
    const collect = () => collectValues(fields, new FormData(formEl));
    const errBox = formEl.querySelector(".formfoot .err");
    const fail = (errors, fallback) => {
      const rest = showFieldErrors(formEl, errors);
      errBox.textContent = rest.length ? rest.join("; ") : fallback;
      const first = formEl.querySelector(".field.invalid input, .field.invalid select, .field.invalid textarea");
      const panel = first && first.closest(".ftab");
      if (panel && panel.hidden) showTab(panel.dataset.tab); // the first problem is on another tab: go there
      if (first) first.focus();
    };

    // Rules can depend on other fields (SNMP v3 needs a user): keep the asterisks in step, and clear
    // a field's error as soon as its value passes.
    formEl.addEventListener("input", () => {
      const values = collect();
      const now = requiredNow(schema, { ...stored, ...values });
      const shown = shownNow(schema, fields, { ...stored, ...values });
      const errors = validateSettings(schema, fields, values, stored);
      for (const el of formEl.querySelectorAll(".field[data-field]")) {
        const name = el.dataset.field;
        el.hidden = !shown.has(name);
        const f = fields.find((x) => x.name === name);
        const req = now.has(name) && f && f.kind !== "boolean";
        el.classList.toggle("required", !!req);
        const input = el.querySelector("input, select, textarea");
        if (input) {
          if (req) input.setAttribute("aria-required", "true");
          else input.removeAttribute("aria-required");
        }
        if (el.classList.contains("invalid") && !errors[name]) setFieldError(el, null);
      }
      for (const box of formEl.querySelectorAll(".fgroup")) {
        box.hidden = ![...box.querySelectorAll(".field[data-field]")].some((el) => !el.hidden);
      }
      if (!formEl.querySelector(".field.invalid")) errBox.textContent = "";
    });

    formEl.addEventListener("submit", async (e) => {
      e.preventDefault();
      errBox.textContent = "";
      errBox.classList.remove("ok");
      const values = collect();
      const errors = validateSettings(schema, fields, values, stored);
      if (Object.keys(errors).length) {
        fail(errors, "Fix the highlighted settings, then save again.");
        return;
      }
      try {
        const updated = await apiSend("PATCH", `/api/v1/plugins/${encodeURIComponent(id)}`, { settings: values });
        const wasUnconfigured = needsSetup(ctx.plugins().find((p) => p.id === id));
        stored = updated.settings;
        showFieldErrors(formEl, {});
        ctx.replacePlugin(updated);
        toast("Settings saved");
        if (updated.restart_required) toast("Restart NetView to apply", "warn");
        if (updated.restart_required || wasUnconfigured !== needsSetup(updated)) ctx.redraw();
      } catch (err) {
        if (err.fields) fail(err.fields, "The settings were not saved.");
        else errBox.textContent = err.message; // a 422 without field detail, or a network error
      }
    });
  }

  const sections = pane.querySelector(".sections");
  for (const spec of ctx.host.get("settings.section").filter((s) => s.pluginId === id)) {
    const el = document.createElement("section");
    el.className = "card";
    if (spec.tab && tabs.includes(spec.tab)) {
      el.dataset.tab = spec.tab;
      el.hidden = spec.tab !== tab;
    }
    if (spec.title) {
      const h = document.createElement("h4");
      h.textContent = spec.title;
      el.appendChild(h);
    }
    const body = document.createElement("div");
    el.appendChild(body);
    sections.appendChild(el);
    try {
      spec.render(body, { pluginId: id, apiBase: `/api/v1/plugins/${id}`, apiGet, apiSend, util: ctx.util });
    } catch (err) {
      console.error(`Plugin "${id}" settings section failed`, err);
      body.innerHTML = `<p class="err">This section failed: ${esc(err.message)}</p>`;
    }
  }
}
