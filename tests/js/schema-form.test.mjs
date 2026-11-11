import { test } from "node:test";
import assert from "node:assert/strict";
import { fieldsFromSchema, collectValues, fieldHtml, labelFromName } from "../../src/netview/presentation/web/static/js/settings/schema-form.js";

// uv run python -c "from netview.plugins.builtin.lan_discovery.settings import LanDiscoverySettings as S; ..."
const LAN_DISCOVERY = {
  properties: {
    ping_timeout_ms: { default: 800, maximum: 5000, minimum: 100, title: "Ping Timeout Ms", type: "integer" },
    workers: { default: 64, maximum: 256, minimum: 1, title: "Workers", type: "integer" },
  },
  title: "LanDiscoverySettings",
  type: "object",
};

const pick = (f) => ({ name: f.name, label: f.label, kind: f.kind, min: f.min, max: f.max, default: f.default });

test("fieldsFromSchema reads the LanDiscoverySettings schema", () => {
  assert.deepEqual(fieldsFromSchema(LAN_DISCOVERY).map(pick), [
    { name: "ping_timeout_ms", label: "Ping timeout (ms)", kind: "integer", min: 100, max: 5000, default: 800 },
    { name: "workers", label: "Workers", kind: "integer", min: 1, max: 256, default: 64 },
  ]);
});

test("fieldsFromSchema handles no schema", () => {
  assert.deepEqual(fieldsFromSchema(null), []);
  assert.deepEqual(fieldsFromSchema({}), []);
});

test("labelFromName turns units into brackets and uses sentence case", () => {
  assert.equal(labelFromName("ping_timeout_ms"), "Ping timeout (ms)");
  assert.equal(labelFromName("interval_s"), "Interval (s)");
  assert.equal(labelFromName("workers"), "Workers");
});

test("a hand-written title wins over the name", () => {
  const [f] = fieldsFromSchema({ properties: { x: { type: "string", title: "Gateway address", description: "Where to look" } } });
  assert.equal(f.label, "Gateway address");
  assert.equal(f.help, "Where to look");
  assert.equal(f.kind, "string");
});

test("kinds: boolean, enum, list, Optional and $ref", () => {
  const schema = {
    $defs: { Mode: { enum: ["a", "b"], type: "string" } },
    properties: {
      on: { type: "boolean", default: true },
      mode: { $ref: "#/$defs/Mode", default: "a" },
      hosts: { type: "array", items: { type: "string" } },
      maybe: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
      weird: { type: "object" },
    },
  };
  const fields = fieldsFromSchema(schema);
  assert.deepEqual(fields.map((f) => f.kind), ["boolean", "enum", "string-list", "number", "unsupported"]);
  assert.deepEqual(fields[1].options, ["a", "b"]);
});

test("collectValues converts numbers, booleans and lists", () => {
  const fields = fieldsFromSchema({
    properties: {
      n: { type: "integer" },
      x: { type: "number" },
      on: { type: "boolean" },
      off: { type: "boolean" },
      s: { type: "string" },
      list: { type: "array", items: { type: "string" } },
      blank: { type: "integer" },
    },
  });
  const fd = new FormData();
  fd.set("n", "900");
  fd.set("x", "1.5");
  fd.set("on", "on");
  fd.set("s", "hi");
  fd.set("list", " a \n\nb\n");
  fd.set("blank", "");
  assert.deepEqual(collectValues(fields, fd), { n: 900, x: 1.5, on: true, off: false, s: "hi", list: ["a", "b"] });
});

test("collectValues accepts a plain object", () => {
  const fields = fieldsFromSchema(LAN_DISCOVERY);
  assert.deepEqual(collectValues(fields, { ping_timeout_ms: "900", workers: "64" }), { ping_timeout_ms: 900, workers: 64 });
});

test("every input id is prefixed with the plugin id", () => {
  const [a] = fieldsFromSchema(LAN_DISCOVERY);
  const html = fieldHtml("lan_discovery", a, 800);
  assert.match(html, /id="f-lan_discovery-ping_timeout_ms"/);
  assert.match(html, /for="f-lan_discovery-ping_timeout_ms"/);
  assert.match(html, /min="100"/);
});

test("fieldHtml escapes labels, help and values", () => {
  const [f] = fieldsFromSchema({ properties: { s: { type: "string", title: "<b>x</b>", description: "a & b" } } });
  const html = fieldHtml("p", f, '"><script>');
  assert.ok(!html.includes("<b>x"));
  assert.ok(!html.includes("<script>"));
  assert.match(html, /a &amp; b/);
});

const SECRET_PLAIN = { properties: { key: { type: "string", format: "password", writeOnly: true } } };
const SECRET_OPTIONAL = {
  properties: { key: { anyOf: [{ type: "string", format: "password", writeOnly: true }, { type: "null" }], default: null } },
};

test("secret field renders password input", () => {
  for (const schema of [SECRET_PLAIN, SECRET_OPTIONAL]) {
    const [f] = fieldsFromSchema(schema);
    assert.equal(f.kind, "secret");
    const html = fieldHtml("p", f, "********");
    assert.match(html, /type="password"/);
    assert.match(html, /autocomplete="new-password"/);
    assert.match(html, /value=""/);
    assert.ok(!html.includes("********"));
  }
});

test("secret field shows set state", () => {
  const [f] = fieldsFromSchema(SECRET_OPTIONAL);
  assert.match(fieldHtml("p", f, "********"), /placeholder="set"/);
  assert.match(fieldHtml("p", f, null), /placeholder="not set"/);
});

test("secret field left blank is omitted", () => {
  const fields = fieldsFromSchema({
    properties: { host: { type: "string" }, key: { type: "string", format: "password", writeOnly: true } },
  });
  assert.deepEqual(collectValues(fields, { host: "h", key: "" }), { host: "h" });
  assert.deepEqual(collectValues(fields, { host: "h" }), { host: "h" });
  assert.deepEqual(collectValues(fields, { host: "h", key: "new" }), { host: "h", key: "new" });
});
