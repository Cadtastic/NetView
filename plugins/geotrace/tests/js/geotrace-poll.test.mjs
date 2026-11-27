import { test } from "node:test";
import assert from "node:assert/strict";
import { createPoller } from "../../static/poll.js";

// A hand-run clock: timers are collected and fired by tick().
function clock() {
  const timers = new Map();
  let next = 1;
  return {
    setTimer: (fn, ms) => {
      timers.set(next, { fn, ms });
      return next++;
    },
    clearTimer: (id) => timers.delete(id),
    pending: () => timers.size,
    async tick() {
      const [id, t] = [...timers][0];
      timers.delete(id);
      await t.fn();
    },
  };
}

const flush = () => new Promise((r) => setImmediate(r));

test("fetches once per tick and reschedules", async () => {
  const c = clock();
  let calls = 0;
  const p = createPoller(async () => void calls++, { intervalMs: 1000, isVisible: () => true, ...c });
  p.start();
  assert.equal(calls, 0);
  await c.tick();
  await c.tick();
  assert.equal(calls, 2);
  assert.equal(c.pending(), 1);
});

test("never overlaps: now() while a request is running joins it", async () => {
  const c = clock();
  let calls = 0;
  let release;
  const p = createPoller(
    () => {
      calls++;
      return new Promise((r) => (release = r));
    },
    { intervalMs: 1000, isVisible: () => true, ...c },
  );
  const a = p.now();
  const b = p.now();
  assert.equal(calls, 1);
  release();
  await Promise.all([a, b]);
  const c2 = p.now();
  assert.equal(calls, 2, "a new run starts once the first has ended");
  release();
  await c2;
});

test("a slow request holds the next tick back until it ends", async () => {
  const c = clock();
  let calls = 0;
  let release;
  const p = createPoller(
    () => {
      calls++;
      return new Promise((r) => (release = r));
    },
    { intervalMs: 1000, isVisible: () => true, ...c },
  );
  p.start();
  const ticking = c.tick();
  await flush();
  assert.equal(c.pending(), 0, "no second timer while the request runs");
  release();
  await ticking;
  assert.equal(calls, 1);
  assert.equal(c.pending(), 1);
});

test("does not fetch while hidden, resumes when visible", async () => {
  const c = clock();
  let calls = 0;
  let visible = false;
  const p = createPoller(async () => void calls++, { intervalMs: 1000, isVisible: () => visible, ...c });
  p.start();
  await c.tick();
  await p.now();
  assert.equal(calls, 0);
  visible = true;
  await c.tick();
  assert.equal(calls, 1);
});

test("stop cancels the timer and a failing fetch does not end polling", async () => {
  const c = clock();
  let calls = 0;
  const p = createPoller(
    async () => {
      calls++;
      throw new Error("boom");
    },
    { intervalMs: 1000, isVisible: () => true, ...c },
  );
  p.start();
  await c.tick();
  assert.equal(calls, 1);
  assert.equal(c.pending(), 1);
  p.stop();
  assert.equal(c.pending(), 0);
});
