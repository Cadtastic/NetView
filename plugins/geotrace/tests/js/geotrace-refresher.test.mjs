import { test } from "node:test";
import assert from "node:assert/strict";
import { createRefresher, loadErrorAfter, LOAD_ERROR } from "../../static/refresher.js";

const deferred = () => {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
};

test("two refreshes on one tick: the superseded one waits for the newest and reports its result", async () => {
  const gates = [deferred(), deferred()];
  let call = 0;
  const applied = [];
  const refresh = createRefresher({
    isGone: () => false,
    load: () => gates[call++].promise,
    apply: (r) => applied.push(r.name),
  });
  const first = refresh();
  const second = refresh();
  let firstDone = false;
  first.then(() => (firstDone = true));
  gates[0].resolve({ name: "old", targetsOk: false }); // the older answer lands first, and failed
  await new Promise((r) => setImmediate(r));
  assert.equal(firstDone, false, "must not settle before the newest does");
  assert.deepEqual(applied, []);
  gates[1].resolve({ name: "new", targetsOk: true });
  assert.equal(await second, true);
  assert.equal(await first, true);
  assert.deepEqual(applied, ["new"]);
});

test("the Targets blade shows no error line once the newest refresh landed with a list", async () => {
  let snapTargets = null;
  const gates = [deferred(), deferred()];
  let call = 0;
  const refresh = createRefresher({
    isGone: () => false,
    load: () => gates[call++].promise,
    apply: (r) => (snapTargets = r.targets),
  });
  const first = refresh();
  refresh();
  gates[0].resolve({ targets: [1], targetsOk: true });
  gates[1].resolve({ targets: [1, 2], targetsOk: true });
  const ok = await first; // what reload() awaits
  assert.equal(loadErrorAfter(ok, snapTargets), "");
});

test("a real failure with no list still shows the error; a failure with an old list does not", () => {
  assert.equal(loadErrorAfter(false, null), LOAD_ERROR);
  assert.equal(loadErrorAfter(false, [{ id: 1 }]), "");
  assert.equal(loadErrorAfter(true, null), "");
});

test("a page that is gone applies nothing and reports false", async () => {
  let gone = false;
  const applied = [];
  const refresh = createRefresher({ isGone: () => gone, load: async () => ({ targetsOk: true }), apply: (r) => applied.push(r) });
  const p = refresh();
  gone = true;
  assert.equal(await p, false);
  assert.deepEqual(applied, []);
});
