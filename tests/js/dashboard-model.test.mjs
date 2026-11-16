import { test } from "node:test";
import assert from "node:assert/strict";
import {
  KEY_RE, SPAN_COLS, TILE_COLS, TYPE_LABELS, BUILTIN_PLUGIN_GROUP, BUILTIN_TYPE_GROUP,
  itemFromSpec, emptyLayout, applyLayout, spanOf, groupItems, moveKey, nudge, nextSpan,
  dropSpot, toSaved, sameLayout, saveAction,
} from "../../src/netview/presentation/web/static/js/dashboard/layout.js";

const G1 = "c66a564b-0254-44cf-bb74-1c7f6ebae6be";
const G2 = "11111111-2222-3333-4444-555555555555";

const card = (id, extra = {}) => itemFromSpec({ pluginId: "7", pluginGuid: G1, id, pluginSource: "folder", pluginDisplayName: "Acme", ...extra }, "card");
const core = (id, kind = "card") => itemFromSpec({ pluginId: "core", id }, kind);

test("constants", () => {
  assert.equal(TILE_COLS, 2);
  assert.deepEqual(SPAN_COLS, { third: 4, half: 6, full: 12 });
  assert.equal(TYPE_LABELS.access_point, "Access point");
  assert.equal(BUILTIN_PLUGIN_GROUP, "NetView");
  assert.equal(BUILTIN_TYPE_GROUP, "NetView (built in)");
  assert.ok(KEY_RE.test("core.tile.online"));
});

test("itemFromSpec builds keys for core and plugin items", () => {
  const c = core("watches");
  assert.equal(c.layoutKey, "core.card.watches");
  assert.equal(c.owner, "core");
  assert.equal(c.fixed, false);
  const p = card("temps", { span: "full" });
  assert.equal(p.layoutKey, `${G1}.card.temps`);
  assert.equal(p.owner, G1);
  assert.equal(p.kind, "card");
});

test("an item whose id fails KEY_RE is fixed, shown last and never saved", () => {
  const it = itemFromSpec({ pluginId: "7", pluginGuid: G1, id: "my card", pluginSource: "folder" }, "card");
  assert.equal(it.fixed, true);
  assert.equal(it.layoutKey, null);
  const a = card("a");
  const items = [it, a];
  const { visible } = applyLayout(items, emptyLayout());
  assert.deepEqual(visible.map((i) => i.runtimeKey), [a.runtimeKey, it.runtimeKey]);
  assert.deepEqual(toSaved(items, emptyLayout()).order, [a.layoutKey]);
});

test("the failed-plugin placeholder is fixed", () => {
  const f = itemFromSpec({ pluginId: "9", id: "failed" }, "card");
  assert.equal(f.fixed, true);
  assert.equal(f.layoutKey, null);
  const a = core("watches");
  const { visible } = applyLayout([f, a], { ...emptyLayout(), order: ["core.card.watches"] });
  assert.equal(visible.at(-1), f);
  assert.deepEqual(toSaved([f, a], emptyLayout()).order, ["core.card.watches"]);
});

test("built-in plugins group under NetView; installed ones by name or type label", () => {
  const b = itemFromSpec({ pluginId: "1", pluginGuid: G2, id: "x", pluginSource: "builtin", pluginDisplayName: "Health", pluginType: "server" }, "card");
  assert.equal(b.groupPlugin, "NetView");
  assert.equal(b.groupType, "NetView (built in)");
  const c = core("events");
  assert.equal(c.groupPlugin, "NetView");
  assert.equal(c.groupType, "NetView (built in)");
  const t = card("a", { pluginType: "switch" });
  assert.equal(t.groupPlugin, "Acme");
  assert.equal(t.groupType, "Switch");
  assert.equal(card("a").groupType, "Other");
  assert.equal(card("a", { pluginType: "weird" }).groupType, "Other");
});

test("defaultSpan comes from the spec; tiles are fixed width 2", () => {
  assert.equal(card("a", { span: "full" }).defaultSpan, "full");
  assert.equal(card("a").defaultSpan, null);
  const tile = core("online", "tile");
  assert.equal(spanOf(tile, emptyLayout()), 2);
  assert.equal(spanOf(card("a"), emptyLayout()), 6);
  assert.equal(spanOf(card("a", { span: "third" }), emptyLayout()), 4);
  const k = card("a");
  assert.equal(spanOf(k, { ...emptyLayout(), spans: { [k.layoutKey]: "full" } }), 12);
});

test("applyLayout: saved order first, new items after, fixed last, unknown keys ignored", () => {
  const a = core("watches"), b = core("events"), c = card("c"), d = card("d");
  const f = itemFromSpec({ pluginId: "9", id: "failed" }, "card");
  const layout = { ...emptyLayout(), order: [d.layoutKey, "core.card.gone", a.layoutKey] };
  const { visible, hidden } = applyLayout([f, a, b, c, d], layout);
  assert.deepEqual(visible.map((i) => i.runtimeKey), [d.runtimeKey, a.runtimeKey, b.runtimeKey, c.runtimeKey, f.runtimeKey]);
  assert.deepEqual(hidden, []);
});

test("hidden keys leave visible and appear in hidden", () => {
  const a = core("watches"), b = core("events");
  const { visible, hidden } = applyLayout([a, b], { ...emptyLayout(), hidden: [a.layoutKey] });
  assert.deepEqual(visible, [b]);
  assert.deepEqual(hidden, [a]);
});

test("a hidden key for a missing item makes no tray entry and is dropped by toSaved", () => {
  const a = core("watches");
  const layout = { ...emptyLayout(), hidden: ["core.card.gone"], spans: { "core.card.gone": "full", [a.layoutKey]: "third" } };
  const { hidden } = applyLayout([a], layout);
  assert.deepEqual(hidden, []);
  const saved = toSaved([a], layout);
  assert.deepEqual(saved.hidden, []);
  assert.deepEqual(saved.spans, { [a.layoutKey]: "third" });
  assert.deepEqual(saved.order, [a.layoutKey]);
});

test("toSaved keeps group and the display order including hidden items", () => {
  const a = core("watches"), b = core("events"), c = card("c");
  const layout = { ...emptyLayout(), group: "plugin", order: [c.layoutKey, a.layoutKey], hidden: [a.layoutKey] };
  const saved = toSaved([a, b, c], layout);
  assert.deepEqual(saved.order, [c.layoutKey, a.layoutKey, b.layoutKey]);
  assert.deepEqual(saved.hidden, [a.layoutKey]);
  assert.equal(saved.group, "plugin");
  assert.equal(saved.version, 1);
});

test("groupItems: none gives one unnamed group", () => {
  const a = core("watches"), b = card("c");
  assert.deepEqual(groupItems([a, b], "none"), [{ name: "", items: [a, b] }]);
});

test("groupItems puts the built-in group first, then alphabetical", () => {
  const z = card("z", { pluginDisplayName: "Zeta" });
  const a = card("a", { pluginDisplayName: "Alpha" });
  const c = core("events");
  const g = groupItems([z, a, c], "plugin");
  assert.deepEqual(g.map((x) => x.name), ["NetView", "Alpha", "Zeta"]);
  const t = groupItems([z, a, c], "plugin_type");
  assert.deepEqual(t.map((x) => x.name), ["NetView (built in)", "Other"]);
});

test("groupItems keeps fixed items last in their plugin's group", () => {
  const fixed = itemFromSpec({ pluginId: "7", pluginGuid: G1, id: "bad id", pluginSource: "folder", pluginDisplayName: "Acme" }, "card");
  const a = card("a");
  const g = groupItems([fixed, a], "plugin");
  assert.equal(g.length, 1);
  assert.deepEqual(g[0].items, [a, fixed]);
});

test("moveKey, nudge and nextSpan", () => {
  assert.deepEqual(moveKey(["a", "b", "c"], "a", "c", true), ["b", "c", "a"]);
  assert.deepEqual(moveKey(["a", "b", "c"], "c", "a", false), ["c", "a", "b"]);
  assert.deepEqual(moveKey(["a", "b", "c"], "b", "b", true), ["a", "b", "c"]);
  assert.deepEqual(nudge(["a", "b", "c"], "a", 1, ["a", "b", "c"]), ["b", "a", "c"]);
  assert.deepEqual(nudge(["a", "b", "c"], "a", -1, ["a", "b", "c"]), ["a", "b", "c"]);
  assert.deepEqual(nudge(["a", "b", "c"], "c", 1, ["a", "b", "c"]), ["a", "b", "c"]);
  assert.deepEqual(nudge(["a", "x", "b", "c"], "b", -1, ["a", "b", "c"]), ["b", "a", "x", "c"]);
  assert.equal(nextSpan("third"), "half");
  assert.equal(nextSpan("half"), "full");
  assert.equal(nextSpan("full"), "third");
});

test("dropSpot: halves of a card, the gap mid-row, and the empty end of a row", () => {
  const r = [{ key: "a", left: 0, top: 0, right: 100, bottom: 50 }, { key: "b", left: 120, top: 0, right: 220, bottom: 50 }, { key: "c", left: 0, top: 70, right: 100, bottom: 120 }];
  assert.deepEqual(dropSpot(r, 30, 25), { key: "a", after: false });
  assert.deepEqual(dropSpot(r, 80, 25), { key: "a", after: true });
  assert.deepEqual(dropSpot(r, 110, 25), { key: "b", after: false });
  assert.deepEqual(dropSpot(r, 400, 25), { key: "b", after: true });
  assert.deepEqual(dropSpot(r, 400, 95), { key: "c", after: true });
  assert.equal(dropSpot([], 1, 1), null);
});

test("dropSpot: a point between rows with no row match goes after the last rect", () => {
  const r = [{ key: "a", left: 0, top: 0, right: 100, bottom: 50 }, { key: "c", left: 0, top: 200, right: 100, bottom: 250 }];
  assert.deepEqual(dropSpot(r, 50, 120), { key: "c", after: true });
});

test("sameLayout compares normalized records", () => {
  const a = { ...emptyLayout(), hidden: ["x", "y"], spans: { a: "full", b: "half" } };
  const b = { version: 1, order: [], hidden: ["y", "x"], spans: { b: "half", a: "full" }, group: "none" };
  assert.equal(sameLayout(a, b), true);
  assert.equal(sameLayout(a, { ...b, order: ["q"] }), false);
  assert.equal(sameLayout(a, { ...b, group: "plugin" }), false);
  assert.equal(sameLayout(emptyLayout(), {}), true);
  assert.equal(sameLayout({ ...emptyLayout(), order: ["a", "b"] }, { ...emptyLayout(), order: ["b", "a"] }), false);
});

test("saveAction: reset then save with no edits deletes", () => {
  assert.equal(saveAction({ editingDefault: false, resetPressed: true, edited: false }), "delete");
  assert.equal(saveAction({ editingDefault: false, resetPressed: true, edited: true }), "put");
  assert.equal(saveAction({ editingDefault: true, resetPressed: false, edited: true }), "default");
  assert.equal(saveAction({ editingDefault: false, resetPressed: false, edited: false }), "put");
});

test("a marked failed placeholder is fixed, has no owner and keeps its plugin's group", () => {
  const f = itemFromSpec({ pluginId: "9", id: "failed", failed: true, pluginDisplayName: "Acme", pluginSource: "folder", pluginType: "switch" }, "card");
  assert.equal(f.fixed, true);
  assert.equal(f.layoutKey, null);
  assert.equal(f.owner, null);
  const a = card("a");
  const g = groupItems([f, a], "plugin");
  assert.deepEqual(g.map((x) => x.name), ["Acme"]);
  assert.deepEqual(g[0].items, [a, f]);
  const t = groupItems([f, card("a", { pluginType: "switch" })], "plugin_type");
  assert.deepEqual(t.map((x) => x.name), ["Switch"]);
  assert.equal(t[0].items.at(-1), f);
});

test("a failed placeholder for a built-in plugin groups under NetView", () => {
  const f = itemFromSpec({ pluginId: "1", id: "failed", failed: true, pluginDisplayName: "Health", pluginSource: "builtin" }, "card");
  assert.equal(f.groupPlugin, "NetView");
  assert.equal(f.groupType, "NetView (built in)");
});

test("failed: true stays fixed even if a guid is wrongly present", () => {
  const f = itemFromSpec({ pluginId: "9", pluginGuid: G1, id: "failed", failed: true, pluginDisplayName: "Acme", pluginSource: "folder" }, "card");
  assert.equal(f.fixed, true);
  assert.equal(f.layoutKey, null);
  assert.equal(f.owner, null);
});

test("a spec without an id (or with an empty one) is fixed with no layout key; runtime keys stay distinct", () => {
  const spec = (id) => ({ pluginId: "9", pluginGuid: G1, id, pluginSource: "folder", pluginDisplayName: "Acme" });
  const a = itemFromSpec(spec(undefined), "tile");
  const b = itemFromSpec(spec(undefined), "tile");
  const c = itemFromSpec(spec(""), "tile");
  for (const it of [a, b, c]) {
    assert.equal(it.fixed, true);
    assert.equal(it.layoutKey, null);
  }
  assert.equal(new Set([a.runtimeKey, b.runtimeKey, c.runtimeKey]).size, 3);
  const s = spec(null);
  assert.equal(itemFromSpec(s, "tile").runtimeKey, itemFromSpec(s, "tile").runtimeKey); // stable per spec
});
