import { test } from "node:test";
import assert from "node:assert/strict";
import { createInstaller } from "../../src/netview/presentation/web/static/js/settings/installer.js";

function rig(states) {
  const seq = [...states];
  const done = [];
  const events = [];
  const inst = createInstaller({
    get: async () => seq.shift(),
    send: async () => ({ job: "j1", state: "queued", percent: null, error: null }),
    wait: async () => {},
    onDone: async (id, name) => done.push([id, name]),
  });
  inst.subscribe((e) => events.push(e));
  return { inst, done, events };
}

const tick = () => new Promise((r) => setTimeout(r, 5));

test("a job finishes with no subscriber left on screen", async () => {
  const { inst, done } = rig([{ state: "running", percent: 50 }, { state: "done" }]);
  const unsub = inst.subscribe(() => {});
  unsub(); // the Available pane was replaced by another tab
  await inst.install("a", "Alpha");
  await tick();
  assert.deepEqual(done, [["a", "Alpha"]]);
  assert.equal(inst.get("a"), undefined);
});

test("a re-rendered pane sees the job in flight", async () => {
  const { inst } = rig([{ state: "running", percent: 10 }, { state: "running", percent: 10 }, { state: "done" }]);
  await inst.install("a", "Alpha");
  assert.equal(inst.get("a").job, "j1");
  await inst.install("a", "Alpha"); // second click is ignored, no 409
  await tick();
});

test("progress fires only when something changed", async () => {
  const { inst, events } = rig([{ state: "running", percent: 10 }, { state: "running", percent: 10 }, { state: "done" }]);
  await inst.install("a", "Alpha");
  await tick();
  const progress = events.filter((e) => e.type === "progress");
  assert.equal(progress.length, 2); // queued, running 10 (the repeat is skipped)
  assert.equal(events.at(-1).type, "done");
});

test("stop ends polling", async () => {
  const { inst, done } = rig([{ state: "running", percent: 1 }, { state: "done" }]);
  await inst.install("a", "Alpha");
  inst.stop();
  await tick();
  assert.deepEqual(done, []);
});
