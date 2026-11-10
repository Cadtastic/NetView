// Plugins: one card per plugin with state, chips, an enable toggle and a settings form built from its schema.
import { apiSend } from "../api.js";
import { esc } from "../util.js";

const STATE_TEXT = { active: "Active", disabled: "Disabled", failed: "Failed" };

/** Resolve a $ref and unwrap Optional (anyOf with null) so a field has one concrete shape. */
export function resolveField(schema, root) {
  let s = schema || {};
  for (let i = 0; i < 5; i++) {
    if (s.$ref) {
      const name = String(s.$ref).split("/").pop();
      s = { ...(root.$defs && root.$defs[name]), ...omit(s, "$ref") };
    } else if (Array.isArray(s.anyOf) || Array.isArray(s.oneOf)) {
      const options = (s.anyOf || s.oneOf).filter((o) => o.type !== "null");
      s = { ...omit(s, "anyOf", "oneOf"), ...(options[0] || {}) };
    } else break;
  }
  return s;
}

function omit(obj, ...keys) {
  const out = { ...obj };
  for (const k of keys) delete out[k];
  return out;
}

/** The kind of input a schema field gets: integer, number, string, boolean, enum, list or unsupported. */
export function fieldKind(field) {
  if (Array.isArray(field.enum)) return "enum";
  if (field.type === "array" && field.items && field.items.type === "string") return "list";
  if (["integer", "number", "string", "boolean"].includes(field.type)) return field.type;
  return "unsupported";
}

function fieldHtml(name, field, value) {
  const id = `f-${name}`;
  const kind = fieldKind(field);
  const label = field.title || name;
  let input;
  if (kind === "boolean") {
    input = `<input type="checkbox" id="${esc(id)}" data-name="${esc(name)}" data-kind="boolean" ${value ? "checked" : ""}>`;
  } else if (kind === "enum") {
    input = `<select id="${esc(id)}" data-name="${esc(name)}" data-kind="enum">${field.enum
      .map((o) => `<option value="${esc(o)}" ${o === value ? "selected" : ""}>${esc(o)}</option>`)
      .join("")}</select>`;
  } else if (kind === "list") {
    input = `<textarea id="${esc(id)}" data-name="${esc(name)}" data-kind="list" rows="3" aria-describedby="${esc(id)}-h">${esc((value || []).join("\n"))}</textarea>`;
  } else if (kind === "integer" || kind === "number") {
    const step = kind === "integer" ? "1" : "any";
    const bounds = ["minimum", "maximum"].map((k) => (field[k] != null ? ` ${k === "minimum" ? "min" : "max"}="${esc(field[k])}"` : "")).join("");
    input = `<input type="number" id="${esc(id)}" data-name="${esc(name)}" data-kind="${kind}" step="${step}"${bounds} value="${esc(value ?? "")}">`;
  } else if (kind === "string") {
    input = `<input type="text" id="${esc(id)}" data-name="${esc(name)}" data-kind="string" value="${esc(value ?? "")}">`;
  } else {
    return `<div class="field"><span class="lbl">${esc(label)}</span><span class="scope">not editable here</span></div>`;
  }
  const hint = [field.description, kind === "list" ? "One per line." : ""].filter(Boolean).join(" ");
  return `<div class="field"><label for="${esc(id)}" class="lbl">${esc(label)}</label>${input}${hint ? `<div class="scope" id="${esc(id)}-h">${esc(hint)}</div>` : ""}</div>`;
}

function readValue(input) {
  const kind = input.dataset.kind;
  if (kind === "boolean") return input.checked;
  if (kind === "integer" || kind === "number") return input.value === "" ? undefined : Number(input.value);
  if (kind === "list") return input.value.split("\n").map((l) => l.trim()).filter(Boolean);
  return input.value;
}

function cardHtml(info, uiError) {
  const schema = info.settings_schema;
  const props = (schema && schema.properties) || {};
  const names = Object.keys(props);
  const form = names.length
    ? `<form class="settings" data-plugin="${esc(info.id)}" autocomplete="off">${names
        .map((n) => fieldHtml(n, resolveField(props[n], schema), info.settings[n] ?? props[n].default))
        .join("")}<div class="formfoot"><button type="submit" class="primary small">Save</button><span class="err" role="status"></span></div></form>`
    : "";
  const chips = [...info.capabilities.map((c) => ["capability", c]), ...info.permissions.map((p) => ["permission", p])]
    .map(([kind, v]) => `<span class="chip" title="${kind}">${esc(v)}</span>`)
    .join("");
  const canToggle = info.state !== "failed";
  return `<section class="card plugin" data-plugin="${esc(info.id)}">
    <div class="plugin-head">
      <h2>${esc(info.name)}</h2>
      <span class="ver">${esc(info.version)}</span>
      <span class="pstate ${esc(info.state)}">${esc(STATE_TEXT[info.state] || info.state)}</span>
      <span class="spacer"></span>
      ${info.restart_required ? '<span class="badge restart">Restart to apply</span>' : ""}
      <label class="toggle"><input type="checkbox" data-enable="${esc(info.id)}" ${info.enabled ? "checked" : ""} ${canToggle ? "" : "disabled"}> Enabled</label>
    </div>
    ${info.description ? `<p class="sub">${esc(info.description)}</p>` : ""}
    ${info.error ? `<p class="err">${esc(info.error)}</p>` : ""}
    ${uiError ? `<p class="err">Its interface failed to load: ${esc(uiError)}</p>` : ""}
    ${chips ? `<div class="chips">${chips}</div>` : ""}
    ${form}
    <div class="err toggle-err" role="status"></div>
  </section>`;
}

export function mountPlugins(el, ctx) {
  const root = document.createElement("div");
  el.appendChild(root);
  let plugins = ctx.getPlugins();
  let busy = false;

  function render() {
    root.innerHTML = plugins.length
      ? plugins.map((p) => cardHtml(p, ctx.host.errors[p.id])).join("")
      : '<section class="card"><p class="empty">No plugins are installed.</p></section>';
  }

  function replace(info) {
    plugins = plugins.map((p) => (p.id === info.id ? info : p));
  }

  root.addEventListener("change", async (e) => {
    const id = e.target.dataset.enable;
    if (!id || busy) return;
    busy = true;
    const card = e.target.closest(".card");
    try {
      replace(await apiSend("PATCH", `/api/v1/plugins/${encodeURIComponent(id)}`, { enabled: e.target.checked }));
      render();
    } catch (err) {
      e.target.checked = !e.target.checked;
      card.querySelector(".toggle-err").textContent = err.message;
    } finally {
      busy = false;
    }
  });

  root.addEventListener("submit", async (e) => {
    const form = e.target.closest("form.settings");
    if (!form) return;
    e.preventDefault();
    const settings = {};
    for (const input of form.querySelectorAll("[data-name]")) {
      const v = readValue(input);
      if (v !== undefined) settings[input.dataset.name] = v;
    }
    const errBox = form.querySelector(".err");
    errBox.textContent = "";
    try {
      const info = await apiSend("PATCH", `/api/v1/plugins/${encodeURIComponent(form.dataset.plugin)}`, { settings });
      replace(info);
      render();
      const saved = root.querySelector(`form.settings[data-plugin="${CSS.escape(info.id)}"] .err`);
      if (saved) {
        saved.textContent = info.restart_required ? "Saved. Restart to apply." : "Saved.";
        saved.classList.add("ok");
      }
    } catch (err) {
      errBox.textContent = err.message;
    }
  });

  render();
  // The list main.js holds can be stale after an enable or settings change made on an earlier visit.
  ctx
    .reloadPlugins()
    .then((fresh) => {
      if (!root.isConnected || root.querySelector(":focus-within")) return;
      plugins = fresh;
      render();
    })
    .catch(() => {});
  return {
    update() {
      // Plugin state only changes through this page; leave an open form alone while state events arrive.
    },
  };
}
