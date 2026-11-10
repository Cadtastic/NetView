// Settings forms from a plugin's JSON schema. fieldsFromSchema and collectValues are pure;
// fieldHtml returns an escaped HTML string.
import { esc } from "../util.js";

function omit(obj, ...keys) {
  const out = { ...obj };
  for (const k of keys) delete out[k];
  return out;
}

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

/** "ping_timeout_ms" -> "Ping timeout (ms)"; a trailing _ms or _s becomes a unit in brackets. */
export function labelFromName(name) {
  let base = String(name);
  let unit = "";
  const m = /^(.+)_(ms|s)$/.exec(base);
  if (m) {
    base = m[1];
    unit = ` (${m[2]})`;
  }
  const words = base.split("_").filter(Boolean).join(" ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1) + unit;
}

/** pydantic fills `title` with "Ping Timeout Ms" when none was written; that is not a real title. */
function isAutoTitle(name, title) {
  const auto = String(name)
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  return title === auto;
}

function kindOf(field) {
  if (Array.isArray(field.enum)) return "enum";
  if (field.type === "array" && field.items && field.items.type === "string") return "string-list";
  if (["integer", "number", "string", "boolean"].includes(field.type)) return field.type;
  return "unsupported";
}

/** Field = {name, label, kind, help, min, max, options, default}; kind "unsupported" is shown read-only. */
export function fieldsFromSchema(schema) {
  const props = (schema && schema.properties) || {};
  return Object.keys(props).map((name) => {
    const f = resolveField(props[name], schema);
    const dflt = props[name].default !== undefined ? props[name].default : f.default;
    return {
      name,
      label: f.title && !isAutoTitle(name, f.title) ? f.title : labelFromName(name),
      kind: kindOf(f),
      help: f.description || "",
      min: f.minimum,
      max: f.maximum,
      options: Array.isArray(f.enum) ? f.enum : undefined,
      default: dflt,
    };
  });
}

const getter = (formData) => (typeof formData.get === "function" ? (k) => formData.get(k) : (k) => formData[k]);

/** Turn submitted form data into the settings object: numbers, booleans and lists are converted. */
export function collectValues(fields, formData) {
  const get = getter(formData);
  const out = {};
  for (const f of fields) {
    const raw = get(f.name);
    if (f.kind === "boolean") {
      out[f.name] = raw === true || raw === "on" || raw === "true";
    } else if (f.kind === "integer" || f.kind === "number") {
      if (raw == null || String(raw).trim() === "") continue;
      out[f.name] = Number(raw);
    } else if (f.kind === "string-list") {
      out[f.name] = String(raw ?? "")
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean);
    } else if (f.kind === "enum" || f.kind === "string") {
      if (raw != null) out[f.name] = String(raw);
    }
  }
  return out;
}

/** One labelled input. Ids are prefixed with the plugin id so two plugins never collide. */
export function fieldHtml(pluginId, field, value) {
  const id = `f-${pluginId}-${field.name}`;
  const name = esc(field.name);
  const label = `<label for="${esc(id)}" class="lbl">${esc(field.label)}</label>`;
  const hint = field.help ? `<div class="hint" id="${esc(id)}-h">${esc(field.help)}</div>` : "";
  const described = field.help ? ` aria-describedby="${esc(id)}-h"` : "";
  let input;
  switch (field.kind) {
    case "boolean":
      input = `<input type="checkbox" id="${esc(id)}" name="${name}"${described} ${value ? "checked" : ""}>`;
      break;
    case "enum":
      input = `<select id="${esc(id)}" name="${name}"${described}>${field.options
        .map((o) => `<option value="${esc(o)}" ${o === value ? "selected" : ""}>${esc(o)}</option>`)
        .join("")}</select>`;
      break;
    case "string-list":
      input = `<textarea id="${esc(id)}" name="${name}" rows="3"${described}>${esc((value || []).join("\n"))}</textarea>`;
      break;
    case "integer":
    case "number": {
      const bounds = (field.min != null ? ` min="${esc(field.min)}"` : "") + (field.max != null ? ` max="${esc(field.max)}"` : "");
      input = `<input type="number" id="${esc(id)}" name="${name}" step="${field.kind === "integer" ? "1" : "any"}"${bounds}${described} value="${esc(value ?? "")}">`;
      break;
    }
    case "string":
      input = `<input type="text" id="${esc(id)}" name="${name}"${described} value="${esc(value ?? "")}">`;
      break;
    default:
      return `<div class="field"><span class="lbl">${esc(field.label)}</span><span class="scope">Not editable here.</span></div>`;
  }
  const extra = field.kind === "string-list" ? '<div class="hint">One per line.</div>' : "";
  return `<div class="field">${label}${input}${hint}${extra}</div>`;
}
