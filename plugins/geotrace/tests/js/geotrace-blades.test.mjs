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

import { createBladeController, bladeTitle } from "../../static/blades.js";
import { createSubscriptions } from "../../static/subscriptions.js";

test("open without options or level goes to the end of the stack", () => {
  const st = createBladeStack();
  st.open("a");
  const s = st.open("b");
  assert.deepEqual(keys(s), ["a", "b"]);
  assert.deepEqual(keys(st.open("c", {})), ["a", "b", "c"]);
  assert.deepEqual(keys(st.open("d", { wide: true })), ["a", "b", "c", "d"]);
});

test("changes requested while rendering are queued, never re-entered", () => {
  const st = createBladeStack();
  const depth = { now: 0, max: 0, calls: 0 };
  let ctl;
  const apply = (state) => {
    depth.now++;
    depth.calls++;
    depth.max = Math.max(depth.max, depth.now);
    if (state.blades.length === 1) ctl.run(() => st.open("child")); // a blade opening another from its render
    depth.now--;
  };
  ctl = createBladeController(apply);
  ctl.run(() => st.open("parent"));
  assert.equal(depth.max, 1);
  assert.equal(depth.calls, 2);
  assert.deepEqual(keys(st.state()), ["parent", "child"]);
});

test("a throwing apply does not wedge the controller", () => {
  const st = createBladeStack();
  let boom = true;
  const ctl = createBladeController(() => {
    if (boom) throw new Error("x");
  });
  assert.throws(() => ctl.run(() => st.open("a")));
  boom = false;
  assert.doesNotThrow(() => ctl.run(() => st.open("b")));
});

test("bladeTitle takes a string or a function of key and snapshot", () => {
  assert.equal(bladeTitle("Targets", "targets", {}), "Targets");
  const fn = (key, snap) => `T ${key.split(":")[1]} of ${snap.targets.length}`;
  assert.equal(bladeTitle(fn, "target:7", { targets: [1, 2] }), "T 7 of 2");
  assert.equal(bladeTitle(() => { throw new Error("x"); }, "k", {}, "fallback"), "fallback");
  assert.equal(bladeTitle(undefined, "k", {}, "fallback"), "fallback");
});

test("a blade's onChange subscriptions are dropped when it is disposed", () => {
  const subs = createSubscriptions();
  const seen = [];
  const a = subs.forBlade();
  const b = subs.forBlade();
  a.onChange((s) => seen.push(["a", s]));
  const offB = b.onChange((s) => seen.push(["b", s]));
  subs.emit(1);
  a.dispose();
  subs.emit(2);
  offB();
  subs.emit(3);
  assert.deepEqual(seen, [["a", 1], ["b", 1], ["b", 2]]);
  const late = a.onChange(() => seen.push("late"));
  subs.emit(4);
  assert.equal(seen.includes("late"), false);
  assert.equal(typeof late, "function");
});

test("a throwing listener does not stop the others", () => {
  const subs = createSubscriptions();
  const seen = [];
  const a = subs.forBlade();
  a.onChange(() => { throw new Error("x"); });
  a.onChange((s) => seen.push(s));
  const quiet = console.error;
  console.error = () => {};
  try { subs.emit(9); } finally { console.error = quiet; }
  assert.deepEqual(seen, [9]);
});
