// Settings forms from a plugin's JSON schema. fieldsFromSchema, collectValues, requiredNow,
// unmetRequirements and validateSettings are pure; fieldHtml returns an escaped HTML string.
//
// An enum property may carry `enum_labels`, {value: "display text"}: the <option> shows the text and the value stays
// the raw one (a value without a label shows itself). Python: json_schema_extra={"enum_labels": {...}}.
//
// Requirements come from the schema, and the host checks the same rules
// (netview/application/plugins/settings_requirements.py): the top-level `required` list, and
// `allOf` entries {if: {properties: {f: {const | enum}}}, then: {required: [...], properties: {f: {const, errorMessage?}}}}.
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
  if (field.writeOnly === true || field.format === "password") return "secret";
  if (Array.isArray(field.enum)) return "enum";
  if (field.type === "array" && field.items && field.items.type === "string") return "string-list";
  if (["integer", "number", "string", "boolean"].includes(field.type)) return field.type;
  return "unsupported";
}

/** Field = {name, label, kind, help, min, max, options, optionLabels, default, required, group, showWhen}; kind "unsupported" is
 * shown read-only. `group` and `showWhen` come from the property's `group` and `show_when` keys (layout only).
 * `required` is the schema's unconditional list only; requiredNow adds the rules that depend on other values. */
export function fieldsFromSchema(schema) {
  const props = (schema && schema.properties) || {};
  const always = new Set((schema && schema.required) || []);
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
      optionLabels: Array.isArray(f.enum) ? f.enum_labels || props[name].enum_labels || {} : undefined,
      default: dflt,
      required: always.has(name),
      group: String(props[name].group || f.group || ""),
      tab: String(props[name].tab || f.tab || ""),
      showWhen: props[name].show_when || f.show_when || null,
    };
  });
}

/** The tab that holds fields which name none, once a form has tabs. */
export const DEFAULT_TAB = "General";

/** The tab a field sits on (only meaningful when tabsOf is not empty). */
export const tabOf = (field) => field.tab || DEFAULT_TAB;

/**
 * The form's tabs in order: the schema's `tabs` list first, then any other tab in the order of its first field.
 * Empty when no field names a tab: the form then has no tabs at all.
 */
export function tabsOf(schema, fields) {
  if (!fields.some((f) => f.tab)) return [];
  const names = [];
  const add = (name) => {
    if (name && !names.includes(name)) names.push(name);
  };
  for (const name of (schema && Array.isArray(schema.tabs) ? schema.tabs : []).map(String)) add(name);
  for (const f of fields) add(tabOf(f));
  return names;
}

/** The row of tab buttons above a tabbed form; `active` is the selected tab. */
export function tabListHtml(tabs, active) {
  const button = (name) =>
    `<button type="button" role="tab" data-tab="${esc(name)}" aria-selected="${name === active}" tabindex="${name === active ? "0" : "-1"}">${esc(name)}</button>`;
  return `<div class="tabs ptabs" role="tablist" aria-label="Settings">${tabs.map(button).join("")}</div>`;
}

/** Sections in the order of their first field: [{name, fields}]. Ungrouped fields form a first, untitled one. */
export function groupFields(fields) {
  const sections = new Map();
  if (fields.some((f) => !f.group)) sections.set("", []);
  for (const f of fields) {
    if (!sections.has(f.group)) sections.set(f.group, []);
    sections.get(f.group).push(f);
  }
  return [...sections].filter(([, list]) => list.length).map(([name, list]) => ({ name, fields: list }));
}

/** Whether a field with `showWhen` ({other: value | [values]}) is shown for these (defaulted) values. */
export function isShown(field, values) {
  if (!field.showWhen) return true;
  return Object.entries(field.showWhen).every(([k, want]) => (Array.isArray(want) ? want.includes(values[k]) : values[k] === want));
}

/** Names of the fields shown while the form holds `values` (missing values take the schema default). */
export function shownNow(schema, fields, values = {}) {
  const full = withDefaults(schema, values);
  return new Set(fields.filter((f) => isShown(f, full)).map((f) => f.name));
}

export const REQUIRED_MESSAGE = "Required";

/** No value: null, undefined, a blank string, an empty list or object. */
export function isBlank(v) {
  if (v == null) return true;
  if (typeof v === "string") return v.trim() === "";
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v).length === 0;
  return false;
}

function holds(rule, value) {
  if ("const" in rule && value !== rule.const) return false;
  return !(Array.isArray(rule.enum) && !rule.enum.includes(value));
}

function conditionHolds(cond, values) {
  for (const n of cond.required || []) if (!(n in values)) return false;
  for (const [n, rule] of Object.entries(cond.properties || {})) {
    if (n in values && !holds(rule, values[n])) return false;
  }
  return true;
}

/** Every schema property with its value: the given one, else the schema default. */
function withDefaults(schema, values) {
  const props = (schema && schema.properties) || {};
  const out = { ...values };
  for (const name of Object.keys(props)) {
    if (!(name in out)) {
      const d = props[name].default !== undefined ? props[name].default : resolveField(props[name], schema).default;
      out[name] = d === undefined ? null : d;
    }
  }
  return out;
}

function activeRules(schema, values) {
  return ((schema && schema.allOf) || []).filter((r) => r && r.if && conditionHolds(r.if, values)).map((r) => r.then || {});
}

/** Names of the fields that must have a value while the form holds `values`. */
export function requiredNow(schema, values = {}) {
  const full = withDefaults(schema, values);
  const names = new Set((schema && schema.required) || []);
  for (const then of activeRules(schema, full)) for (const n of then.required || []) names.add(n);
  return names;
}

/** Field name -> message for each schema requirement `values` does not meet (mirrors the host's check). */
export function unmetRequirements(schema, values = {}) {
  if (!schema) return {};
  const full = withDefaults(schema, values);
  const problems = {};
  const report = (n, msg) => {
    if (!(n in problems)) problems[n] = msg;
  };
  for (const n of schema.required || []) if (isBlank(full[n])) report(n, REQUIRED_MESSAGE);
  for (const then of activeRules(schema, full)) {
    for (const n of then.required || []) if (isBlank(full[n])) report(n, REQUIRED_MESSAGE);
    for (const [n, rule] of Object.entries(then.properties || {})) {
      if (!holds(rule, full[n])) {
        const expected = "const" in rule ? `Must be ${rule.const}` : `Must be one of ${(rule.enum || []).join(", ")}`;
        report(n, rule.errorMessage || expected);
      }
    }
  }
  const order = Object.keys(schema.properties || {});
  const rank = (n) => (order.includes(n) ? order.indexOf(n) : order.length);
  return Object.fromEntries(Object.entries(problems).sort((a, b) => rank(a[0]) - rank(b[0])));
}

/** What is wrong with one number input's collected value, or null. */
export function fieldProblem(field, value) {
  if (field.kind !== "integer" && field.kind !== "number") return null;
  if (value === undefined) return null; // left blank: the stored value stays
  if (!Number.isFinite(value)) return "Enter a number";
  if (field.kind === "integer" && !Number.isInteger(value)) return "Enter a whole number";
  if (field.min != null && value < field.min) return `Must be at least ${field.min}`;
  if (field.max != null && value > field.max) return `Must be at most ${field.max}`;
  return null;
}

/**
 * Field name -> message for everything Save would be refused for, checked before sending.
 * `collected` is collectValues' output; `stored` the plugin's current settings (a set secret is masked,
 * which counts as a value, and a secret left blank keeps it).
 */
export function validateSettings(schema, fields, collected, stored = {}) {
  const errors = {};
  for (const f of fields) {
    const p = fieldProblem(f, collected[f.name]);
    if (p) errors[f.name] = p;
  }
  const unmet = unmetRequirements(schema, { ...stored, ...collected });
  for (const [n, msg] of Object.entries(unmet)) if (!(n in errors)) errors[n] = msg;
  return errors;
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
    } else if (f.kind === "secret") {
      // blank means "keep the stored secret": leave the key out of the patch
      if (raw != null && String(raw) !== "") out[f.name] = String(raw);
    } else if (f.kind === "enum" || f.kind === "string") {
      if (raw != null) out[f.name] = String(raw);
    }
  }
  return out;
}

/**
 * One labelled input. Ids are prefixed with the plugin id so two plugins never collide.
 * `required` (default field.required) shows the asterisk. The asterisk is always rendered and the
 * `.required` class on the field shows it, so a rule that depends on other values can toggle it.
 * Each input has an empty error line (`<id>-e`) below it for a Save that failed.
 */
export function fieldHtml(pluginId, field, value, required = field.required === true, shown = true) {
  const id = `f-${pluginId}-${field.name}`;
  const name = esc(field.name);
  const req = required && field.kind !== "boolean";
  const label = `<label for="${esc(id)}" class="lbl">${esc(field.label)}<span class="req" aria-hidden="true">*</span></label>`;
  const hint = field.help ? `<div class="hint" id="${esc(id)}-h">${esc(field.help)}</div>` : "";
  const described = ` aria-describedby="${field.help ? `${esc(id)}-h ` : ""}${esc(id)}-e"${req ? ' aria-required="true"' : ""}`;
  let input;
  switch (field.kind) {
    case "boolean":
      input = `<input type="checkbox" id="${esc(id)}" name="${name}"${described} ${value ? "checked" : ""}>`;
      break;
    case "enum":
      input = `<select id="${esc(id)}" name="${name}"${described}>${field.options
        .map((o) => `<option value="${esc(o)}" ${o === value ? "selected" : ""}>${esc((field.optionLabels && field.optionLabels[o]) || o)}</option>`)
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
    case "secret": {
      const state = value == null || value === "" ? "not set" : "set";
      input = `<input type="password" id="${esc(id)}" name="${name}" autocomplete="new-password"${described} value="" placeholder="${state}">`;
      break;
    }
    default:
      return `<div class="field" data-field="${name}"${shown ? "" : " hidden"}><span class="lbl">${esc(field.label)}</span><span class="scope">Not editable here.</span></div>`;
  }
  const extra = field.kind === "string-list" ? '<div class="hint">One per line.</div>' : "";
  const error = `<div class="field-err" id="${esc(id)}-e"></div>`;
  return `<div class="field${req ? " required" : ""}" data-field="${name}"${shown ? "" : " hidden"}>${label}${input}${error}${hint}${extra}</div>`;
}

/**
 * The form body: one section per group (groupFields), a titled <fieldset> for a named group.
 * `values` are the stored settings, `required` and `shown` sets of field names (requiredNow, shownNow).
 * A section whose fields are all hidden is hidden too.
 */
export function sectionsHtml(pluginId, fields, values, required, shown) {
  return groupFields(fields)
    .map(({ name, fields: list }) => {
      const body = list
        .map((f) => fieldHtml(pluginId, f, values[f.name] ?? f.default, required.has(f.name), shown.has(f.name)))
        .join("");
      const hidden = list.every((f) => !shown.has(f.name)) ? " hidden" : "";
      return name
        ? `<fieldset class="fgroup" data-group="${esc(name)}"${hidden}><legend>${esc(name)}</legend>${body}</fieldset>`
        : `<div class="fgroup"${hidden}>${body}</div>`;
    })
    .join("");
}

/**
 * The whole form body. Without tabs it is sectionsHtml; with tabs (tabsOf) it is one panel per tab, each holding
 * the sections of its fields, and only the `active` panel is shown.
 */
export function formBodyHtml(pluginId, schema, fields, values, required, shown, active) {
  const tabs = tabsOf(schema, fields);
  if (!tabs.length) return sectionsHtml(pluginId, fields, values, required, shown);
  return tabs
    .map((name) => {
      const own = fields.filter((f) => tabOf(f) === name);
      const hidden = name === active ? "" : " hidden";
      return `<div class="ftab" role="tabpanel" data-tab="${esc(name)}" aria-label="${esc(name)}"${hidden}>${sectionsHtml(pluginId, own, values, required, shown)}</div>`;
    })
    .join("");
}
