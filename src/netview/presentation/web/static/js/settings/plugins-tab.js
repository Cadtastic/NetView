// Plugins overview tab and the per-plugin tab (header, chips, settings form, plugin-provided sections).
import { apiGet, apiSend } from "../api.js";
import { esc } from "../util.js";
import { toast } from "../toast.js";
import { collectValues, fieldHtml, fieldsFromSchema } from "./schema-form.js";

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
async function toggle(ctx, id, enabled, box) {
  try {
    const info = await apiSend("PATCH", `/api/v1/plugins/${encodeURIComponent(id)}`, { enabled });
    ctx.replacePlugin(info);
    if (info.restart_required) toast("Restart netview to apply", "warn");
    return info;
  } catch (err) {
    if (box) box.textContent = err.message;
    toast(err.message, "bad");
    return null;
  }
}

/** The Plugins tab: one row per plugin. */
export function renderOverview(pane, ctx) {
  const draw = () => {
    const rows = ctx
      .plugins()
    .map(
      (p) => `<section class="card plugin" data-plugin="${esc(p.id)}">
      <div class="plugin-head">
        <h3>${esc(p.name)}</h3><span class="ver">${esc(p.version)}</span>${stateBadge(p)}
        ${p.restart_required ? '<span class="badge restart">Restart netview to apply</span>' : ""}
        <span class="spacer"></span>
        ${enableSwitch(p, p.enabled ? "On" : "Off")}
        <button type="button" class="small" data-open="${esc(p.id)}">Settings</button>
      </div>
      ${p.description ? `<p class="sub">${esc(p.description)}</p>` : ""}
      ${p.error ? `<p class="err">${esc(p.error)}</p>` : ""}
      ${p.capabilities.length ? `<div class="chips">${chips(p.capabilities, CAPABILITY_LABELS)}</div>` : ""}
      <div class="err toggle-err" role="status"></div>
    </section>`,
    )
    .join("");
    pane.innerHTML = `<h3>Plugins</h3>${rows || '<p class="empty">No plugins are installed.</p>'}`;
  };
  draw();
  pane.addEventListener("click", (e) => {
    const b = e.target.closest("[data-open]");
    if (b) ctx.select(`plugin:${b.dataset.open}`);
  });
  pane.addEventListener("change", async (e) => {
    const id = e.target.dataset.enable;
    if (!id) return;
    const info = await toggle(ctx, id, e.target.checked, e.target.closest(".card").querySelector(".toggle-err"));
    if (info) draw();
    else e.target.checked = !e.target.checked;
  });
}

/** One plugin's tab. */
export function renderPlugin(pane, ctx, id) {
  const info = ctx.plugins().find((p) => p.id === id);
  if (!info) {
    pane.innerHTML = '<p class="empty">That plugin is no longer installed.</p>';
    return;
  }
  const fields = fieldsFromSchema(info.settings_schema);
  const uiError = ctx.host.errors[id];
  const form = fields.length
    ? `<form class="settings" autocomplete="off" novalidate>${fields
        .map((f) => fieldHtml(id, f, info.settings[f.name] ?? f.default))
        .join("")}<div class="formfoot"><button type="submit" class="primary">Save settings</button><span class="err" role="status"></span></div></form>`
    : '<p class="note">This plugin has no settings.</p>';
  pane.innerHTML = `<div class="plugin-head">
      <h3>${esc(info.name)}</h3><span class="ver">${esc(info.version)}</span>${stateBadge(info)}
      <span class="spacer"></span>
      ${info.restart_required ? '<span class="badge restart">Restart netview to apply</span>' : ""}
      ${enableSwitch(info, "Enabled")}
    </div>
    <div class="err toggle-err" role="status"></div>
    ${info.description ? `<p class="sub">${esc(info.description)}</p>` : ""}
    ${info.error ? `<p class="err">${esc(info.error)}</p>` : ""}
    ${uiError ? `<p class="err">Its interface failed to load: ${esc(uiError)}</p>` : ""}
    ${info.capabilities.length ? `<h4>What it can do</h4><div class="chips">${chips(info.capabilities, CAPABILITY_LABELS)}</div>` : ""}
    ${info.permissions.length ? `<h4>Access it asks for</h4><div class="chips">${chips(info.permissions, PERMISSION_LABELS)}</div>` : ""}
    ${form}
    <div class="sections"></div>`;

  pane.querySelector("[data-enable]").addEventListener("change", async (e) => {
    const box = pane.querySelector(".toggle-err");
    box.textContent = "";
    const updated = await toggle(ctx, id, e.target.checked, box);
    if (updated) ctx.select(`plugin:${id}`);
    else e.target.checked = !e.target.checked;
  });

  const formEl = pane.querySelector("form.settings");
  if (formEl) {
    formEl.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errBox = formEl.querySelector(".err");
      errBox.textContent = "";
      errBox.classList.remove("ok");
      try {
        const updated = await apiSend("PATCH", `/api/v1/plugins/${encodeURIComponent(id)}`, {
          settings: collectValues(fields, new FormData(formEl)),
        });
        ctx.replacePlugin(updated);
        toast("Settings saved");
        if (updated.restart_required) {
          toast("Restart netview to apply", "warn");
          ctx.select(`plugin:${id}`);
        }
      } catch (err) {
        errBox.textContent = err.message; // a 422 carries the validation message
      }
    });
  }

  const sections = pane.querySelector(".sections");
  for (const spec of ctx.host.get("settings.section").filter((s) => s.pluginId === id)) {
    const el = document.createElement("section");
    el.className = "card";
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
