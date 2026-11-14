import { test } from "node:test";
import assert from "node:assert/strict";
import { orderCards, orderTiles, coreTiles, coreCardSpecs } from "../../src/netview/presentation/web/static/js/pages/dashboard.js";
import { createDashboardGrid } from "../../src/netview/presentation/web/static/js/dashboard/grid.js";
import { itemFromSpec, emptyLayout, applyLayout, groupItems } from "../../src/netview/presentation/web/static/js/dashboard/layout.js";
import { sortDevices } from "../../src/netview/presentation/web/static/js/table-model.js";

/** A minimal DOM: elements with children, attributes, classes, text and innerHTML. Counts every node move. */
const moves = { count: 0 };
function stubDoc() {
  const make = (tag) => {
    const e = {
      tag,
      className: "",
      textContent: "",
      innerHTML: "",
      hidden: false,
      children: [],
      attrs: {},
      listeners: {},
      parentNode: null,
      setAttribute(k, v) {
        this.attrs[k] = String(v);
      },
      removeAttribute(k) {
        delete this.attrs[k];
      },
      addEventListener(t, fn) {
        this.listeners[t] = fn;
      },
      click() {
        if (this.listeners.click) this.listeners.click({ preventDefault() {} });
      },
      classList: {
        toggle(c, on) {
          const set = new Set(e.className.split(" ").filter(Boolean));
          if (on) set.add(c);
          else set.delete(c);
          e.className = [...set].join(" ");
        },
        contains: (c) => e.className.split(" ").includes(c),
      },
      appendChild(c) {
        return this.insertBefore(c, null);
      },
      insertBefore(c, ref) {
        moves.count++;
        if (c.parentNode) c.parentNode.children = c.parentNode.children.filter((x) => x !== c);
        c.parentNode = this;
        const at = ref ? this.children.indexOf(ref) : -1;
        if (at < 0) this.children.push(c);
        else this.children.splice(at, 0, c);
        return c;
      },
      remove() {
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this);
        this.parentNode = null;
      },
    };
    return e;
  };
  return { createElement: make };
}

const spec = (pluginId, id, extra = {}) => ({ pluginId, id, title: id, ...extra });
const quietly = (fn) => {
  const original = console.error;
  console.error = () => {};
  try {
    fn();
  } finally {
    console.error = original;
  }
};

test("orderCards sorts by order (default 30), then registration order", () => {
  const specs = [spec("a", "late", { order: 60 }), spec("b", "default1"), spec("c", "early", { order: 10 }), spec("d", "default2"), spec("e", "zero", { order: 0 })];
  assert.deepEqual(orderCards(specs).map((s) => s.id), ["zero", "early", "default1", "default2", "late"]);
  assert.deepEqual(orderCards([]), []);
});

test("orderTiles defaults to 50, so the core tiles (0 to 3) come first", () => {
  const specs = [spec("p", "plug"), spec("p", "first", { order: 4 })];
  assert.deepEqual(orderTiles(specs).map((s) => s.id), ["first", "plug"]);
  const core = coreTiles({ devices: [], jobs: [] });
  assert.deepEqual(core.map((t) => t.order), [0, 1, 2, 3]);
});

test("the core cards are Watches (order 10, full) and Events (order 60, half)", () => {
  const [watches, events] = coreCardSpecs({});
  assert.deepEqual([watches.id, watches.order, watches.span], ["watches", 10, "full"]);
  assert.deepEqual([events.id, events.order, events.span], ["events", 60, "half"]);
});

// ---- the persistent grid ------------------------------------------------------------------------
const GUID_A = "11111111-1111-1111-1111-111111111111";
const GUID_B = "22222222-2222-2222-2222-222222222222";
const entry = (s, kind = "card") => ({ item: itemFromSpec(s, kind), spec: s });
const gridOf = (group) => group.children.find((c) => c.className.split(" ").includes("dash-grid"));
const cardEls = (root) => root.children.flatMap((g) => gridOf(g).children);
const viewFor = (entries, group, layout = { ...emptyLayout(), group }) => ({
  groups: groupItems(applyLayout(entries.map((e) => e.item), layout).visible, group),
  editing: false,
  layout,
});
const none = (entries, layout) => viewFor(entries, "none", layout ? { ...layout, group: "none" } : undefined);
const plug = (guid, name, id, extra = {}) => spec("p-" + guid.slice(0, 1), id, { pluginGuid: guid, pluginDisplayName: name, pluginType: "router", pluginSource: "user", ...extra });
const has = (el, c) => el.className.split(" ").includes(c);

test("a throwing draw gives an error card while the others render", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const drawn = [];
  const entries = [
    entry(plug(GUID_A, "A", "one", { draw: (el) => drawn.push(el) })),
    entry(plug(GUID_B, "B", "boom", { draw: () => { throw new Error("kaput"); } })),
    entry(plug(GUID_A, "A", "plain", { render: () => "<p>hello</p>" })),
  ];
  quietly(() => grid.update(entries, {}, none(entries)));
  assert.equal(cardEls(root).length, 3);
  const bad = grid.nodes.get(entries[1].item.runtimeKey);
  assert.equal(bad.error.textContent, "This card failed: kaput");
  assert.ok(!has(bad.error, "hide"));
  assert.ok(has(grid.nodes.get(entries[0].item.runtimeKey).error, "hide"));
  assert.equal(drawn.length, 1);
  assert.equal(grid.nodes.get(entries[2].item.runtimeKey).body.innerHTML, "<p>hello</p>");
});

test("cards persist across updates and keep the order they are given", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const bodies = [];
  const entries = [
    entry(plug(GUID_A, "A", "y", { draw: (el) => bodies.push(el) })),
    entry(plug(GUID_B, "B", "x", { draw: (el) => bodies.push(el) })),
  ];
  grid.update(entries, {}, none(entries));
  const first = [...cardEls(root)];
  assert.deepEqual(first.map((c) => c.attrs["data-card"]), entries.map((e) => e.item.runtimeKey));
  grid.update(entries, {}, none(entries));
  assert.deepEqual(cardEls(root), first, "the same section elements");
  assert.equal(bodies.length, 4);
  assert.equal(bodies[0], bodies[2], "draw gets the same body element every time");
  assert.ok(has(first[0], "card") && has(first[0], "dash-item"));
});

test("a card recovers after a failed draw, and a vanished spec is removed", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  let fail = true;
  const flaky = plug(GUID_A, "A", "flaky", { span: "full", draw: () => { if (fail) throw new Error("once"); } });
  const stays = plug(GUID_A, "A", "stays", { render: () => "" });
  let entries = [entry(flaky), entry(stays)];
  quietly(() => grid.update(entries, {}, none(entries)));
  const node = grid.nodes.get(entries[0].item.runtimeKey);
  assert.ok(has(node.el, "col-12"));
  assert.ok(node.error.textContent.includes("once"));
  fail = false;
  entries = [entry(flaky)];
  grid.update(entries, {}, none(entries));
  assert.ok(has(node.error, "hide"));
  assert.equal(node.error.textContent, "");
  assert.deepEqual(cardEls(root), [node.el]);
  assert.equal(grid.nodes.size, 1);
});

test("nodes are created once and survive regrouping and edit toggles", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const entries = [
    entry(plug(GUID_A, "Alpha", "a1", { draw: () => {} })),
    entry(plug(GUID_B, "Beta", "b1", { draw: () => {} })),
    entry(plug(GUID_A, "Alpha", "a2", { draw: () => {} })),
    entry({ pluginId: "p-t", id: "tl", pluginGuid: GUID_B, pluginDisplayName: "Beta", pluginType: "router", pluginSource: "user", render: () => "<div class='k'>x</div>" }, "tile"),
  ];
  grid.update(entries, {}, none(entries));
  const before = [...grid.nodes.values()].map((n) => n.el);
  const bodies = [...grid.nodes.values()].map((n) => n.body);
  const viewByPlugin = viewFor(entries, "plugin");
  grid.update(entries, {}, viewByPlugin);
  grid.update(entries, {}, { ...viewByPlugin, editing: true });
  grid.update(entries, {}, viewFor(entries, "plugin_type"));
  grid.update(entries, {}, none(entries));
  assert.deepEqual([...grid.nodes.values()].map((n) => n.el), before);
  assert.deepEqual([...grid.nodes.values()].map((n) => n.body), bodies);
  assert.equal(cardEls(root).length, 4, "everything is back in the grid");
});

test("a tile whose render returns empty is hidden but keeps its slot", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  let html = "";
  const tile = entry({ pluginId: "p-t", id: "t", pluginGuid: GUID_A, pluginDisplayName: "A", render: () => html }, "tile");
  const other = entry({ pluginId: "p-t", id: "u", pluginGuid: GUID_A, pluginDisplayName: "A", render: () => "<b>u</b>" }, "tile");
  const entries = [tile, other];
  grid.update(entries, {}, none(entries));
  const node = grid.nodes.get(tile.item.runtimeKey);
  assert.equal(node.el.hidden, true);
  assert.deepEqual(cardEls(root), [node.el, grid.nodes.get(other.item.runtimeKey).el], "still in its slot");
  html = "<b>now</b>";
  grid.update(entries, {}, none(entries));
  assert.equal(node.el.hidden, false);
  assert.equal(node.el.innerHTML, "<b>now</b>");
  assert.ok(has(node.el, "tile"));
});

test("a fixed (failed) card is rendered last and marked data-fixed", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const failed = entry({ pluginId: "broken", id: "failed", failed: true, pluginDisplayName: "Broken", pluginSource: "user", pluginType: "router", span: "full", render: () => "<p>x</p>" });
  const entries = [failed, entry(plug(GUID_A, "A", "ok", { render: () => "" }))];
  grid.update(entries, {}, none(entries));
  const els = cardEls(root);
  assert.equal(els[els.length - 1], grid.nodes.get(failed.item.runtimeKey).el);
  assert.ok("data-fixed" in els[els.length - 1].attrs);
  assert.ok(!("data-fixed" in els[0].attrs));
});

test("an unchanged update does not move any node", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const entries = [entry(plug(GUID_A, "A", "a", { render: () => "x" })), entry(plug(GUID_B, "B", "b", { render: () => "y" }))];
  const view = viewFor(entries, "plugin");
  grid.update(entries, {}, view);
  moves.count = 0;
  grid.update(entries, {}, view);
  grid.update(entries, {}, { ...view, editing: true });
  grid.update(entries, {}, { ...view, editing: false });
  assert.equal(moves.count, 0);
});

test("col classes follow spanOf", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const tile = entry({ pluginId: "core", id: "online", render: () => "x" }, "tile");
  const card = entry(plug(GUID_A, "A", "c", { render: () => "x", span: "half" }));
  const entries = [tile, card];
  grid.update(entries, {}, none(entries));
  const el = (e) => grid.nodes.get(e.item.runtimeKey).el;
  assert.ok(has(el(tile), "col-2"));
  assert.ok(has(el(card), "col-6"));
  const layout = { ...emptyLayout(), spans: { [card.item.layoutKey]: "full" } };
  grid.update(entries, {}, none(entries, layout));
  assert.ok(has(el(card), "col-12"));
  assert.ok(!has(el(card), "col-6"));
  assert.equal(el(card).attrs["data-layout-key"], card.item.layoutKey);
});

test("a group head toggles collapsed; the head is left out for an unnamed group", () => {
  const doc = stubDoc();
  const root = doc.createElement("div");
  const grid = createDashboardGrid(doc, root);
  const entries = [entry(plug(GUID_A, "Alpha", "a", { render: () => "x" }))];
  grid.update(entries, {}, none(entries));
  assert.equal(root.children[0].children.length, 1, "the grid only");
  grid.update(entries, {}, viewFor(entries, "plugin"));
  const group = root.children.find((g) => has(g, "dash-group"));
  const head = group.children.find((c) => has(c, "dash-group-head"));
  assert.ok(head);
  head.click();
  assert.ok(has(group, "collapsed"));
  head.click();
  assert.ok(!has(group, "collapsed"));
});

test("sortDevices passes the state to the sortKey of a column", () => {
  const cols = [{ id: "x", sortKey: (d, state) => state.rank[d.ip] }];
  const devices = [{ ip: "192.168.1.1" }, { ip: "192.168.1.2" }];
  const sorted = sortDevices(devices, "x", 1, cols, { rank: { "192.168.1.1": 2, "192.168.1.2": 1 } });
  assert.deepEqual(sorted.map((d) => d.ip), ["192.168.1.2", "192.168.1.1"]);
});
