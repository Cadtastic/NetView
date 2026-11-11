import { test } from "node:test";
import assert from "node:assert/strict";
import {
  fieldsFromSchema,
  fieldHtml,
  fieldProblem,
  isBlank,
  requiredNow,
  unmetRequirements,
  validateSettings,
} from "../../src/netview/presentation/web/static/js/settings/schema-form.js";

// The shape the host sends for the GSM7248 settings, cut down to the fields the rules touch:
// uv run python -c "from netview_local_plugins.gsm7248.settings import Gsm7248Settings as S; import json; print(json.dumps(S.model_json_schema()))"
const SECRET = { anyOf: [{ type: "string", format: "password", writeOnly: true }, { type: "null" }], default: null };
const GSM = {
  properties: {
    host: { type: "string", default: "192.168.1.4", title: "Host" },
    snmp_version: { enum: ["2c", "3"], type: "string", default: "3", title: "SNMP version" },
    community: { ...SECRET, title: "Community (v2c)" },
    v3_user: { type: "string", default: "", title: "v3 user" },
    v3_auth_protocol: { enum: ["none", "md5", "sha"], type: "string", default: "sha" },
    v3_auth_key: { ...SECRET },
    v3_priv_protocol: { enum: ["none", "des", "aes128"], type: "string", default: "des" },
    v3_priv_key: { ...SECRET },
    timeout_s: { type: "number", default: 2, minimum: 0.5, maximum: 10 },
    retries: { type: "integer", default: 1, minimum: 0, maximum: 3 },
  },
  required: ["host"],
  allOf: [
    { if: { properties: { snmp_version: { const: "2c" } }, required: ["snmp_version"] }, then: { required: ["community"] } },
    { if: { properties: { snmp_version: { const: "3" } }, required: ["snmp_version"] }, then: { required: ["v3_user"] } },
    {
      if: { properties: { snmp_version: { const: "3" }, v3_auth_protocol: { enum: ["md5", "sha"] } }, required: ["snmp_version", "v3_auth_protocol"] },
      then: { required: ["v3_auth_key"] },
    },
    {
      if: { properties: { snmp_version: { const: "3" }, v3_priv_protocol: { enum: ["des", "aes128"] } }, required: ["snmp_version", "v3_priv_protocol"] },
      then: { required: ["v3_priv_key"] },
    },
    {
      if: { properties: { snmp_version: { const: "3" }, v3_auth_protocol: { const: "none" } }, required: ["snmp_version", "v3_auth_protocol"] },
      then: { properties: { v3_priv_protocol: { const: "none", errorMessage: "Privacy needs authentication" } } },
    },
  ],
};

test("fieldsFromSchema marks the schema's unconditional required fields", () => {
  const fields = fieldsFromSchema(GSM);
  assert.equal(fields.find((f) => f.name === "host").required, true);
  assert.equal(fields.find((f) => f.name === "v3_user").required, false);
});

test("requiredNow follows the if/then rules on the current values", () => {
  assert.deepEqual([...requiredNow(GSM, {})].sort(), ["host", "v3_auth_key", "v3_priv_key", "v3_user"]);
  assert.deepEqual([...requiredNow(GSM, { snmp_version: "2c" })].sort(), ["community", "host"]);
  assert.deepEqual([...requiredNow(GSM, { v3_auth_protocol: "none", v3_priv_protocol: "none" })].sort(), ["host", "v3_user"]);
});

test("unmetRequirements reports each missing field once, in schema order", () => {
  assert.deepEqual(unmetRequirements(GSM, {}), { v3_user: "Required", v3_auth_key: "Required", v3_priv_key: "Required" });
  assert.deepEqual(unmetRequirements(GSM, { host: " ", snmp_version: "2c" }), { host: "Required", community: "Required" });
});

test("a masked secret counts as set", () => {
  assert.deepEqual(unmetRequirements(GSM, { snmp_version: "2c", community: "********" }), {});
});

test("a fixed-value rule uses its error message", () => {
  const values = { v3_user: "u", v3_auth_protocol: "none", v3_priv_protocol: "des", v3_priv_key: "k" };
  assert.deepEqual(unmetRequirements(GSM, values), { v3_priv_protocol: "Privacy needs authentication" });
});

test("a schema without rules has nothing unmet", () => {
  assert.deepEqual(unmetRequirements(null, {}), {});
  assert.deepEqual(unmetRequirements({ properties: { a: { type: "string" } } }, {}), {});
});

test("isBlank", () => {
  for (const v of [null, undefined, "", "  ", [], {}]) assert.equal(isBlank(v), true);
  for (const v of ["x", 0, false, ["a"]]) assert.equal(isBlank(v), false);
});

test("fieldProblem checks numbers against the schema bounds", () => {
  const fields = fieldsFromSchema(GSM);
  const timeout = fields.find((f) => f.name === "timeout_s");
  const retries = fields.find((f) => f.name === "retries");
  assert.equal(fieldProblem(timeout, undefined), null);
  assert.equal(fieldProblem(timeout, 0.1), "Must be at least 0.5");
  assert.equal(fieldProblem(timeout, 11), "Must be at most 10");
  assert.equal(fieldProblem(retries, 1.5), "Enter a whole number");
  assert.equal(fieldProblem(retries, NaN), "Enter a number");
  assert.equal(fieldProblem(retries, 2), null);
  assert.equal(fieldProblem(fields[0], ""), null);
});

test("validateSettings merges the form onto the stored settings before checking", () => {
  const fields = fieldsFromSchema(GSM);
  const stored = { host: "192.168.1.4", snmp_version: "3", v3_user: "", v3_auth_key: "********", v3_priv_key: null };
  // the form leaves the stored auth key in place (blank secret) and fills the user
  assert.deepEqual(validateSettings(GSM, fields, { v3_user: "netview", retries: 9 }, stored), {
    retries: "Must be at most 3",
    v3_priv_key: "Required",
  });
  assert.deepEqual(validateSettings(GSM, fields, { v3_user: "netview", v3_priv_key: "p" }, stored), {});
});

test("fieldHtml: a required field gets the asterisk class, aria-required and an error line", () => {
  const [host] = fieldsFromSchema(GSM);
  const html = fieldHtml("gsm7248", host, "h");
  assert.match(html, /class="field required" data-field="host"/);
  assert.match(html, /<span class="req" aria-hidden="true">\*<\/span>/);
  assert.match(html, /aria-required="true"/);
  assert.match(html, /<div class="field-err" id="f-gsm7248-host-e"><\/div>/);
  assert.match(html, /aria-describedby="f-gsm7248-host-e"/);
});

test("fieldHtml: the required flag can be overridden for a conditional rule", () => {
  const user = fieldsFromSchema(GSM).find((f) => f.name === "v3_user");
  assert.match(fieldHtml("p", user, "", true), /class="field required"/);
  const plain = fieldHtml("p", user, "");
  assert.match(plain, /class="field" data-field="v3_user"/);
  assert.ok(!plain.includes("aria-required"));
});

test("fieldHtml: the error line sits directly below the input, before the help text", () => {
  const html = fieldHtml("p", fieldsFromSchema({ properties: { s: { type: "string", description: "Help" } } })[0], "");
  assert.ok(html.indexOf("field-err") < html.indexOf('class="hint"'));
  assert.match(html, /aria-describedby="f-p-s-h f-p-s-e"/);
});

test("fieldHtml: a checkbox is never marked required", () => {
  const [on] = fieldsFromSchema({ properties: { on: { type: "boolean" } }, required: ["on"] });
  const html = fieldHtml("p", on, true);
  assert.ok(!html.includes("required"));
});

import { showFieldErrors } from "../../src/netview/presentation/web/static/js/settings/plugins-tab.js";

function fakeField(name) {
  const classes = new Set();
  const attrs = {};
  const line = { textContent: "" };
  const input = {
    setAttribute: (k, v) => (attrs[k] = v),
    removeAttribute: (k) => delete attrs[k],
  };
  return {
    dataset: { field: name },
    classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), contains: (c) => classes.has(c) },
    querySelector: (sel) => (sel === ".field-err" ? line : input),
    state: () => ({ invalid: classes.has("invalid"), msg: line.textContent, ariaInvalid: attrs["aria-invalid"] }),
  };
}

test("showFieldErrors marks each named field, clears the rest and returns unknown names", () => {
  const host = fakeField("host");
  const user = fakeField("v3_user");
  const form = { querySelectorAll: () => [host, user] };
  const rest = showFieldErrors(form, { v3_user: "Required", settings: "Bad shape" });
  assert.deepEqual(user.state(), { invalid: true, msg: "Required", ariaInvalid: "true" });
  assert.deepEqual(host.state(), { invalid: false, msg: "", ariaInvalid: undefined });
  assert.deepEqual(rest, ["settings: Bad shape"]);
  assert.deepEqual(showFieldErrors(form, {}), []);
  assert.deepEqual(user.state(), { invalid: false, msg: "", ariaInvalid: undefined });
});
