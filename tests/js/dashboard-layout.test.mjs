import { test } from "node:test";
import assert from "node:assert/strict";
import { orderCards, orderTiles, spanClass, createCardGrid, coreTiles, coreCardSpecs } from "../../src/netview/presentation/web/static/js/pages/dashboard.js";
import { sortDevices } from "../../src/netview/presentation/web/static/js/table-model.js";

/** A minimal DOM: elements with children, attributes, text and innerHTML. */
function stubDoc() {
  const make = (tag) => ({
    tag,
    className: "",
    textContent: "",
    innerHTML: "",
    children: [],
    attrs: {},
    parent: null,
    setAttribute(k, v) {
      this.attrs[k] = v;
    },
    appendChild(c) {
      if (c.parent) c.parent.children = c.parent.children.filter((x) => x !== c);
      c.parent = this;
      this.children.push(c);
      return c;
    },
    remove() {
      if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this);
      this.parent = null;
    },
  });
  return { createElement: make };
}

const keys = (container) => container.children.map((c) => c.attrs["data-card"]);
const body = (card) => card.children.find((c) => c.className === "card-body");
const errBox = (card) => card.children.find((c) => c.className.startsWith("err"));
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

test("spanClass maps to the six-column grid", () => {
  assert.equal(spanClass("third"), "span-2");
  assert.equal(spanClass("half"), "span-3");
  assert.equal(spanClass("full"), "span-6");
  assert.equal(spanClass(undefined), "span-3");
  assert.equal(spanClass("huge"), "span-3");
});

test("the core cards are Watches (order 10, full) and Events (order 60, half)", () => {
  const [watches, events] = coreCardSpecs({});
  assert.deepEqual([watches.id, watches.order, watches.span], ["watches", 10, "full"]);
  assert.deepEqual([events.id, events.order, events.span], ["events", 60, "half"]);
});

test("a throwing draw gives an error card while the others render", () => {
  const doc = stubDoc();
  const container = doc.createElement("div");
  const grid = createCardGrid(doc, container);
  const drawn = [];
  const specs = [
    spec("good", "one", { draw: (el) => drawn.push(el) }),
    spec("bad", "boom", {
      draw: () => {
        throw new Error("kaput");
      },
    }),
    spec("html", "plain", { render: () => "<p>hello</p>" }),
  ];
  quietly(() => grid.update(specs, {}));
  assert.equal(container.children.length, 3);
  const bad = container.children.find((c) => c.attrs["data-card"] === "bad.boom");
  assert.equal(errBox(bad).textContent, "This card failed: kaput");
  assert.ok(!errBox(bad).className.includes("hide"));
  const good = container.children.find((c) => c.attrs["data-card"] === "good.one");
  assert.ok(errBox(good).className.includes("hide"));
  assert.equal(drawn.length, 1);
  const plain = container.children.find((c) => c.attrs["data-card"] === "html.plain");
  assert.equal(body(plain).innerHTML, "<p>hello</p>");
});

test("cards persist across updates and are kept in order", () => {
  const doc = stubDoc();
  const container = doc.createElement("div");
  const grid = createCardGrid(doc, container);
  const bodies = [];
  const specs = [spec("late", "x", { order: 60, draw: (el) => bodies.push(el) }), spec("early", "y", { order: 10, draw: (el) => bodies.push(el) })];
  grid.update(specs, {});
  const first = [...container.children];
  assert.deepEqual(keys(container), ["early.y", "late.x"]);
  grid.update(specs, {});
  assert.deepEqual(container.children, first, "the same section elements");
  assert.equal(bodies.length, 4);
  assert.equal(bodies[0], bodies[2], "draw gets the same body element every time");
  assert.equal(first[0].className, "card span-3");
});

test("a card recovers after a failed draw, and a vanished spec is removed", () => {
  const doc = stubDoc();
  const container = doc.createElement("div");
  const grid = createCardGrid(doc, container);
  let fail = true;
  const flaky = spec("p", "flaky", {
    span: "full",
    draw: () => {
      if (fail) throw new Error("once");
    },
  });
  quietly(() => grid.update([flaky, spec("p", "stays", { render: () => "" })], {}));
  const card = container.children.find((c) => c.attrs["data-card"] === "p.flaky");
  assert.equal(card.className, "card span-6");
  assert.ok(errBox(card).textContent.includes("once"));
  fail = false;
  grid.update([flaky], {});
  assert.ok(errBox(card).className.includes("hide"));
  assert.equal(errBox(card).textContent, "");
  assert.deepEqual(keys(container), ["p.flaky"]);
});

test("sortDevices passes the state to the sortKey of a column", () => {
  const cols = [{ id: "x", sortKey: (d, state) => state.rank[d.ip] }];
  const devices = [{ ip: "192.168.1.1" }, { ip: "192.168.1.2" }];
  const sorted = sortDevices(devices, "x", 1, cols, { rank: { "192.168.1.1": 2, "192.168.1.2": 1 } });
  assert.deepEqual(sorted.map((d) => d.ip), ["192.168.1.2", "192.168.1.1"]);
});
