import { test } from "node:test";
import assert from "node:assert/strict";
import { fieldsFromSchema, groupFields, isShown, sectionsHtml, shownNow } from "../../src/netview/presentation/web/static/js/settings/schema-form.js";
import { showFieldErrors } from "../../src/netview/presentation/web/static/js/settings/plugins-tab.js";

const SCHEMA = {
  properties: {
    note: { type: "string" },
    host: { type: "string", group: "Connection" },
    version: { enum: ["2c", "3"], type: "string", default: "3", group: "Connection" },
    community: { type: "string", group: "v2c", show_when: { version: "2c" } },
    user: { type: "string", group: "v3", show_when: { version: "3" } },
    retries: { type: "integer", group: "Connection" },
    either: { type: "string", group: "v3", show_when: { version: ["2c", "3"] } },
  },
};
const fields = fieldsFromSchema(SCHEMA);

test("fieldsFromSchema reads group and show_when", () => {
  const f = fields.find((x) => x.name === "community");
  assert.equal(f.group, "v2c");
  assert.deepEqual(f.showWhen, { version: "2c" });
  assert.equal(fields.find((x) => x.name === "note").group, "");
});

test("groupFields keeps ungrouped fields first, then sections in order of their first field", () => {
  assert.deepEqual(
    groupFields(fields).map((g) => [g.name, g.fields.map((f) => f.name)]),
    [
      ["", ["note"]],
      ["Connection", ["host", "version", "retries"]],
      ["v2c", ["community"]],
      ["v3", ["user", "either"]],
    ],
  );
  assert.deepEqual(groupFields(fields.filter((f) => f.group)).map((g) => g.name), ["Connection", "v2c", "v3"]);
});

test("isShown matches one value or any of a list", () => {
  const user = fields.find((x) => x.name === "user");
  const either = fields.find((x) => x.name === "either");
  assert.equal(isShown(user, { version: "3" }), true);
  assert.equal(isShown(user, { version: "2c" }), false);
  assert.equal(isShown(either, { version: "2c" }), true);
  assert.equal(isShown(fields[0], {}), true);
});

test("shownNow uses the schema default for a missing value", () => {
  const shown = shownNow(SCHEMA, fields, {});
  assert.ok(shown.has("user"));
  assert.ok(!shown.has("community"));
  assert.ok(shownNow(SCHEMA, fields, { version: "2c" }).has("community"));
});

test("sectionsHtml draws a titled fieldset per group and hides a section with nothing shown", () => {
  const html = sectionsHtml("p", fields, { version: "3" }, new Set(), shownNow(SCHEMA, fields, { version: "3" }));
  assert.match(html, /^<div class="fgroup"><div class="field" data-field="note">/);
  assert.match(html, /<fieldset class="fgroup" data-group="Connection"><legend>Connection<\/legend>/);
  assert.match(html, /<fieldset class="fgroup" data-group="v2c" hidden><legend>v2c<\/legend><div class="field" data-field="community" hidden>/);
  assert.match(html, /<fieldset class="fgroup" data-group="v3"><legend>v3<\/legend>/);
  assert.ok(html.indexOf('data-field="retries"') < html.indexOf('data-group="v2c"'), "retries sits in Connection");
});

test("sectionsHtml escapes the group name", () => {
  const [f] = fieldsFromSchema({ properties: { a: { type: "string", group: "<b>" } } });
  const html = sectionsHtml("p", [f], {}, new Set(), new Set(["a"]));
  assert.ok(!html.includes("<b>"));
});

test("an error on a hidden field goes to the summary line", () => {
  const line = { textContent: "" };
  const hidden = {
    hidden: true,
    dataset: { field: "community" },
    classList: { toggle() {}, contains: () => false },
    querySelector: (sel) => (sel === ".field-err" ? line : { setAttribute() {}, removeAttribute() {} }),
  };
  const rest = showFieldErrors({ querySelectorAll: () => [hidden] }, { community: "Required" });
  assert.deepEqual(rest, ["community: Required"]);
  assert.equal(line.textContent, "");
});
