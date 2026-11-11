import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_TAB, fieldsFromSchema, formBodyHtml, groupFields, isShown, sectionsHtml, shownNow, tabListHtml, tabsOf,
} from "../../src/netview/presentation/web/static/js/settings/schema-form.js";
import { activeTab, showFieldErrors, tabAfterKey } from "../../src/netview/presentation/web/static/js/settings/plugins-tab.js";

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

// ---- tabs

const TABBED = {
  tabs: ["General", "SNMP"],
  properties: {
    host: { type: "string", group: "Connection", tab: "SNMP" },
    note: { type: "string" },
    interval: { type: "integer", group: "Polling", tab: "General" },
    ssh_host: { type: "string", group: "Console", tab: "SSH" },
  },
};
const tabbed = fieldsFromSchema(TABBED);

test("a form without a tab on any field has no tabs", () => {
  assert.deepEqual(tabsOf(SCHEMA, fields), []);
  const shown = shownNow(SCHEMA, fields, { version: "3" });
  assert.equal(
    formBodyHtml("p", SCHEMA, fields, { version: "3" }, new Set(), shown, null),
    sectionsHtml("p", fields, { version: "3" }, new Set(), shown),
  );
});

test("tabsOf: the schema order first, then the rest by first field", () => {
  assert.deepEqual(tabsOf(TABBED, tabbed), ["General", "SNMP", "SSH"]);
  assert.deepEqual(tabsOf({ properties: TABBED.properties }, tabbed), ["SNMP", DEFAULT_TAB, "SSH"]);
});

test("formBodyHtml: one panel per tab, only the active one shown, untabbed fields on General", () => {
  const html = formBodyHtml("p", TABBED, tabbed, {}, new Set(), new Set(tabbed.map((f) => f.name)), "SNMP");
  const panels = html.split('<div class="ftab"').slice(1);
  assert.equal(panels.length, 3);
  assert.match(panels[0], /^ role="tabpanel" data-tab="General" aria-label="General" hidden>/);
  assert.match(panels[1], /^ role="tabpanel" data-tab="SNMP" aria-label="SNMP">/);
  assert.match(panels[2], / data-tab="SSH" aria-label="SSH" hidden>/);
  assert.ok(panels[0].includes('data-field="note"') && panels[0].includes('data-field="interval"'));
  assert.ok(panels[1].includes('data-field="host"') && !panels[1].includes('data-field="note"'));
  assert.ok(panels[2].includes('data-field="ssh_host"'));
});

test("tabListHtml marks the active tab and escapes names", () => {
  const html = tabListHtml(["General", "<b>"], "General");
  assert.match(html, /role="tablist"/);
  assert.match(html, /data-tab="General" aria-selected="true" tabindex="0">General</);
  assert.match(html, /aria-selected="false" tabindex="-1">&lt;b&gt;</);
});

test("activeTab keeps a remembered tab only while the form still has it", () => {
  assert.equal(activeTab([], "SNMP"), null);
  assert.equal(activeTab(["General", "SNMP"], "SNMP"), "SNMP");
  assert.equal(activeTab(["General", "SNMP"], "Gone"), "General");
  assert.equal(activeTab(["General", "SNMP"], undefined), "General");
});

test("tabAfterKey moves with the arrow, Home and End keys and wraps", () => {
  const t = ["General", "SNMP", "SSH"];
  assert.equal(tabAfterKey(t, "General", "ArrowRight"), "SNMP");
  assert.equal(tabAfterKey(t, "SSH", "ArrowRight"), "General");
  assert.equal(tabAfterKey(t, "General", "ArrowLeft"), "SSH");
  assert.equal(tabAfterKey(t, "SNMP", "Home"), "General");
  assert.equal(tabAfterKey(t, "SNMP", "End"), "SSH");
  assert.equal(tabAfterKey(t, "SNMP", "Enter"), null);
});
