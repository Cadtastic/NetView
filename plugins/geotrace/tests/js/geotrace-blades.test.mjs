import { test } from "node:test";
import assert from "node:assert/strict";
import { createBladeStack, BLADES_KEY, loadBlades, saveBlades } from "../../static/blades.js";

const keys = (s) => s.blades.map((b) => b.key);

test("open adds blades left to right", () => {
  const st = createBladeStack();
  st.open("targets", { level: 0 });
  const s = st.open("detail", { level: 1, wide: true });
  assert.deepEqual(keys(s), ["targets", "detail"]);
  assert.deepEqual(s.blades[1], { key: "detail", min: false, wide: true });
  assert.equal(s.blades[0].wide, false);
});

test("opening at a level closes that blade and everything to its right", () => {
  const st = createBladeStack();
  st.open("targets", { level: 0 });
  st.open("detail", { level: 1 });
  st.open("edit", { level: 2 });
  assert.deepEqual(keys(st.open("compare", { level: 1 })), ["targets", "compare"]);
  assert.deepEqual(keys(st.open("trends", { level: 0 })), ["trends"]);
});

test("reopening the same key replaces it and closes those to its right", () => {
  const st = createBladeStack();
  st.open("targets", { level: 0 });
  st.open("detail", { level: 1 });
  st.open("edit", { level: 2 });
  const s = st.open("detail", { level: 1 });
  assert.deepEqual(keys(s), ["targets", "detail"]);
});

test("a key open at another level is moved, not duplicated", () => {
  const st = createBladeStack();
  st.open("targets", { level: 0 });
  st.open("detail", { level: 1 });
  const s = st.open("targets", { level: 1 });
  assert.deepEqual(keys(s), ["targets"]);
});

test("a level beyond the stack is placed at the end", () => {
  const st = createBladeStack();
  assert.deepEqual(keys(st.open("a", { level: 5 })), ["a"]);
});

test("opening a third blade minimises all but the last two", () => {
  const st = createBladeStack();
  st.open("a", { level: 0 });
  st.open("b", { level: 1 });
  let s = st.open("c", { level: 2 });
  assert.deepEqual(s.blades.map((b) => b.min), [true, false, false]);
  s = st.open("d", { level: 3 });
  assert.deepEqual(s.blades.map((b) => b.min), [true, true, false, false]);
});

test("restore expands a minimised blade; minimise collapses one", () => {
  const st = createBladeStack();
  st.open("a", { level: 0 });
  st.open("b", { level: 1 });
  st.open("c", { level: 2 });
  assert.equal(st.restore("a").blades[0].min, false);
  assert.equal(st.minimise("c").blades[2].min, true);
  assert.equal(st.minimise("nope").blades.length, 3);
});

test("close removes the blade and every blade to its right", () => {
  const st = createBladeStack();
  st.open("a", { level: 0 });
  st.open("b", { level: 1 });
  st.open("c", { level: 2 });
  assert.deepEqual(keys(st.close("b")), ["a"]);
  assert.deepEqual(keys(st.close("zzz")), ["a"]);
  assert.deepEqual(keys(st.close("a")), []);
});

test("state returns copies", () => {
  const st = createBladeStack();
  st.open("a", { level: 0 });
  st.state().blades[0].min = true;
  assert.equal(st.state().blades[0].min, false);
});

test("initial blades are sanitised and re-minimised", () => {
  const st = createBladeStack([
    { key: "a", min: false, wide: false }, { key: "b" }, { key: "c", wide: true }, { bad: 1 }, null, { key: "a" },
  ]);
  assert.deepEqual(keys(st.state()), ["a", "b", "c"]);
  assert.deepEqual(st.state().blades.map((b) => b.min), [true, false, false]);
});

test("saveBlades and loadBlades round trip through storage", () => {
  const data = new Map();
  const storage = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v) };
  const st = createBladeStack();
  st.open("a", { level: 0 });
  st.open("b", { level: 1, wide: true });
  saveBlades(st.state(), storage);
  assert.ok(data.has(BLADES_KEY));
  assert.equal(BLADES_KEY, "netview.geotrace.blades");
  assert.deepEqual(keys({ blades: loadBlades(storage) }), ["a", "b"]);
});

test("storage that throws never throws out of load or save", () => {
  const storage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  assert.deepEqual(loadBlades(storage), []);
  assert.doesNotThrow(() => saveBlades({ blades: [] }, storage));
  assert.deepEqual(loadBlades(undefined), []);
  assert.doesNotThrow(() => saveBlades({ blades: [] }, undefined));
});

test("corrupt stored JSON loads as empty", () => {
  assert.deepEqual(loadBlades({ getItem: () => "{not json" }), []);
  assert.deepEqual(loadBlades({ getItem: () => '{"a":1}' }), []);
});
