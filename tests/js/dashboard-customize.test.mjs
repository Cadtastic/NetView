import { test } from "node:test";
import assert from "node:assert/strict";
import { createCustomizer, toolbarHtml, bannerText } from "../../src/netview/presentation/web/static/js/dashboard/customize.js";
import { emptyLayout, applyLayout } from "../../src/netview/presentation/web/static/js/dashboard/layout.js";

const item = (id, kind = "card", extra = {}) => ({
  runtimeKey: `core.${kind}.${id}`,
  layoutKey: `core.${kind}.${id}`,
  kind,
  owner: "core",
  groupPlugin: "NetView",
  groupType: "NetView (built in)",
  defaultSpan: kind === "card" ? "half" : null,
  fixed: false,
  ...extra,
});

function setup({ layout = emptyLayout(), def = null, can = () => true, items, hasOwn } = {}) {
  const list = items || [item("online", "tile"), item("watches"), item("events"), item("extra")];
  const s = { layout, calls: [], toasts: [], redraws: 0, announced: [], items: list, def };
  const api = {
    saveLayout: async (l) => s.calls.push(["saveLayout", l]),
    resetLayout: async () => s.calls.push(["resetLayout"]),
    saveDefault: async (l, clear) => s.calls.push(["saveDefault", l, clear]),
  };
  s.c = createCustomizer({
    getItems: () => s.items,
    getLayout: () => s.layout,
    setLayout: (l) => (s.layout = l),
    getDefault: () => s.def,
    hasOwn,
    redraw: () => s.redraws++,
    auth: { can },
    api,
    toast: (t, kind) => s.toasts.push(kind ? [t, kind] : t),
    label: (i) => i.layoutKey.split(".").pop(),
    announce: (t) => s.announced.push(t),
  });
  return s;
}

test("toolbarHtml: viewer sees nothing, customizer sees Customize, editing shows Group by and saves", () => {
  assert.equal(toolbarHtml({ editing: false, canCustomize: false }), "");
  const view = toolbarHtml({ editing: false, canCustomize: true });
  assert.match(view, /data-act="customize"/);
  assert.doesNotMatch(view, /data-act="group"/);

  const edit = toolbarHtml({ editing: true, editingDefault: false, canCustomize: true, canDefault: false, group: "plugin" });
  assert.match(edit, /data-act="group"/);
  assert.match(edit, /<option value="none">None<\/option>/);
  assert.match(edit, /<option value="plugin" selected>Plugin<\/option>/);
  assert.match(edit, /<option value="plugin_type">Plugin type<\/option>/);
  for (const a of ["save", "reset", "cancel"]) assert.match(edit, new RegExp(`data-act="${a}"`));
  assert.doesNotMatch(edit, /data-act="default"/);
  assert.match(edit, /class="primary" data-act="save"/);

  const admin = toolbarHtml({ editing: true, editingDefault: false, canCustomize: true, canDefault: true });
  assert.match(admin, /data-act="default"/);
  assert.doesNotMatch(admin, /class="primary" data-act="default"/);
});

test("default editing shows only Group by, Save as default and Cancel", () => {
  const html = toolbarHtml({ editing: true, editingDefault: true, canCustomize: true, canDefault: true });
  assert.match(html, /data-act="group"/);
  assert.match(html, /class="primary" data-act="default"/);
  assert.match(html, /data-act="cancel"/);
  for (const a of ["save", "reset", "customize"]) assert.doesNotMatch(html, new RegExp(`data-act="${a}"`));
});

test("save after reset with no edits calls resetLayout, not saveLayout", async () => {
  const s = setup({ layout: { ...emptyLayout(), hidden: ["core.card.events"] }, def: emptyLayout() });
  s.c.start({ editingDefault: false });
  s.c.reset();
  assert.deepEqual(s.layout.hidden, []);
  await s.c.save();
  assert.deepEqual(s.calls.map((c) => c[0]), ["resetLayout"]);
  assert.equal(s.c.editing, false);
  assert.deepEqual(s.toasts, ["Saved to your profile. Only you see this layout."]);
});

test("save after reset and a further edit calls saveLayout", async () => {
  const s = setup({ def: emptyLayout() });
  s.c.start({ editingDefault: false });
  s.c.reset();
  s.c.hide("core.card.events");
  await s.c.save();
  assert.deepEqual(s.calls.map((c) => c[0]), ["saveLayout"]);
  assert.deepEqual(s.calls[0][1].hidden, ["core.card.events"]);
});

test("reset loads the default with its grouping, or an empty layout when there is none", () => {
  const s = setup({ def: { ...emptyLayout(), group: "plugin", hidden: ["core.card.extra"] } });
  s.c.start({ editingDefault: false });
  s.c.reset();
  assert.equal(s.layout.group, "plugin");
  assert.deepEqual(s.layout.hidden, ["core.card.extra"]);
  const t = setup({ layout: { ...emptyLayout(), group: "plugin_type" }, def: null });
  t.c.start({ editingDefault: false });
  t.c.reset();
  assert.equal(t.layout.group, "none");
});

test("save as default from personal editing passes clearMine true; from default editing false", async () => {
  const a = setup();
  a.c.start({ editingDefault: false });
  a.c.hide("core.card.events");
  await a.c.saveDefault();
  assert.equal(a.calls[0][0], "saveDefault");
  assert.equal(a.calls[0][2], true);
  assert.deepEqual(a.calls[0][1].hidden, ["core.card.events"]);
  assert.deepEqual(a.toasts, ["Saved as the default layout for everyone"]);

  const own = { ...emptyLayout(), hidden: ["core.card.watches"] };
  const b = setup({ layout: own, def: emptyLayout() });
  b.c.start({ editingDefault: true });
  assert.equal(b.c.editingDefault, true);
  assert.deepEqual(b.layout.hidden, []); // the editor starts from the default
  b.c.hide("core.card.events");
  await b.c.save(); // Save while default-editing is the default save
  assert.equal(b.calls[0][0], "saveDefault");
  assert.equal(b.calls[0][2], false);
  assert.equal(b.layout, own); // my own layout is untouched
  assert.equal(b.c.editing, false);
});

test("saving the default shows it to an admin who has no layout of their own", async () => {
  const s = setup({ layout: emptyLayout(), def: emptyLayout(), hasOwn: () => false });
  s.c.start({ editingDefault: true });
  s.c.hide("core.card.events");
  await s.c.save();
  assert.equal(s.c.editing, false);
  assert.deepEqual(s.layout.hidden, ["core.card.events"]); // my view follows the default I just saved
});

test("a failed save keeps editing and toasts the error", async () => {
  const s = setup();
  s.c.start({ editingDefault: false });
  const failing = createCustomizer({
    getItems: () => s.items,
    getLayout: () => s.layout,
    setLayout: (l) => (s.layout = l),
    redraw() {},
    auth: { can: () => true },
    api: { saveLayout: async () => { throw new Error("nope"); }, resetLayout: async () => {}, saveDefault: async () => {} },
    toast: (t, k) => s.toasts.push([t, k]),
  });
  failing.start({});
  await failing.save();
  assert.equal(failing.editing, true);
  assert.deepEqual(s.toasts.at(-1), ["nope", "bad"]);
});

test("cancel restores the layout from before editing", () => {
  const before = { ...emptyLayout(), hidden: ["core.card.extra"], group: "plugin" };
  const s = setup({ layout: before });
  s.c.start({ editingDefault: false });
  s.c.hide("core.card.events");
  s.c.setGroup("none");
  s.c.cancel();
  assert.equal(s.layout, before);
  assert.equal(s.c.editing, false);
  assert.deepEqual(s.toasts, ["Changes discarded"]);
});

test("hide, show and widen mark the layout edited and change hidden/spans", async () => {
  const s = setup({ def: emptyLayout() });
  s.c.start({ editingDefault: false });
  s.c.reset(); // edited = false
  s.c.hide("core.card.events");
  assert.deepEqual(applyLayout(s.items, s.layout).hidden.map((i) => i.layoutKey), ["core.card.events"]);
  s.c.show("core.card.events");
  assert.deepEqual(s.layout.hidden, []);
  s.c.widen("core.card.watches"); // half -> full
  assert.equal(s.layout.spans["core.card.watches"], "full");
  s.c.widen("core.card.watches"); // full -> third
  assert.equal(s.layout.spans["core.card.watches"], "third");
  s.c.widen("core.tile.online"); // tiles have no width
  assert.equal(s.layout.spans["core.tile.online"], undefined);
  await s.c.save();
  assert.equal(s.calls[0][0], "saveLayout");
});

test("move and nudge reorder within the group and announce the new position", () => {
  const s = setup();
  s.c.start({ editingDefault: false });
  assert.deepEqual(s.layout.order, ["core.tile.online", "core.card.watches", "core.card.events", "core.card.extra"]);
  s.c.move("core.card.extra", "core.card.watches", false);
  assert.deepEqual(s.layout.order, ["core.tile.online", "core.card.extra", "core.card.watches", "core.card.events"]);
  s.c.nudge("core.card.extra", 1);
  assert.deepEqual(s.layout.order.slice(1, 3), ["core.card.watches", "core.card.extra"]);
  assert.deepEqual(s.announced, ["Moved extra to position 3 of 4"]);
  s.c.nudge("core.tile.online", -1); // already first: nothing happens
  assert.equal(s.announced.length, 1);
});

test("start is refused without the permission it needs", () => {
  const s = setup({ can: (id) => id === "core.dashboard" });
  s.c.start({ editingDefault: true });
  assert.equal(s.c.editing, false);
  const t = setup({ can: () => false });
  t.c.start({ editingDefault: false });
  assert.equal(t.c.editing, false);
});

test("bannerText copy is exact", () => {
  assert.equal(bannerText(false), "Drag cards to move them. Changes are only yours, and only kept when you save.");
  assert.equal(bannerText(true), "Editing the default layout for everyone. Users who saved their own layout keep it until they reset.");
});
