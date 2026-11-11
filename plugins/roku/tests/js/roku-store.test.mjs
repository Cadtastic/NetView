import { test } from "node:test";
import assert from "node:assert/strict";
import { createStore, EMPTY_TOOLTIP } from "../../static/store.js";

const TIP = "No Roku TVs found yet. Click to open Roku settings and scan.";

function harness(replies) {
  const calls = { get: 0, render: 0, timers: [], clock: 1000000 };
  const ui = {
    apiBase: "/api/v1/plugins/roku",
    apiGet: async () => {
      calls.get += 1;
      const r = replies.shift();
      if (r instanceof Error) throw r;
      return r;
    },
    requestRender: () => { calls.render += 1; },
  };
  const setTimer = (fn, ms) => { calls.timers.push({ fn, ms }); return calls.timers.length; };
  const now = () => calls.clock;
  return { ui, calls, setTimer, now };
}
const tv = { id: "a" };

test("unavailable() is null before load, the tooltip when empty, null with TVs", async () => {
  const h = harness([{ tvs: [], scan: {} }, { tvs: [tv], scan: {} }]);
  const s = createStore(h.ui, { setTimer: h.setTimer });
  assert.equal(EMPTY_TOOLTIP, TIP);
  assert.equal(s.unavailable(), null);
  assert.equal(s.get(), null);
  await s.load();
  assert.equal(s.unavailable(), TIP);
  await s.load();
  assert.equal(s.unavailable(), null);
  assert.equal(s.get().tvs.length, 1);
});

test("store re-loads only while empty and requests a render when emptiness flips", async () => {
  const done = { running: false, finished_ms: 5 };
  const h = harness([{ tvs: [], scan: done }, { tvs: [], scan: done }, { tvs: [tv], scan: done }, { tvs: [tv], scan: done }]);
  const s = createStore(h.ui, { setTimer: h.setTimer, now: h.now });
  await s.load();
  assert.equal(h.calls.render, 1); // unknown -> empty flips the nav tooltip
  assert.equal(h.calls.timers.length, 1);
  assert.equal(h.calls.timers[0].ms, 30000);
  await h.calls.timers[0].fn();
  assert.equal(h.calls.render, 1); // still empty: no render
  assert.equal(h.calls.timers.length, 2);
  await h.calls.timers[1].fn();
  assert.equal(h.calls.render, 2); // empty -> non-empty
  assert.equal(h.calls.timers.length, 2); // no further timer once TVs exist
  await s.load();
  assert.equal(h.calls.render, 2);
});

test("a failed load keeps the last data and subscribers hear about every load", async () => {
  const h = harness([{ tvs: [tv], scan: {} }, new Error("boom")]);
  const s = createStore(h.ui, { setTimer: h.setTimer });
  let heard = 0;
  const off = s.subscribe(() => { heard += 1; });
  await s.load();
  await s.load();
  assert.equal(s.get().tvs.length, 1);
  assert.equal(heard, 2);
  off();
  await s.load().catch(() => {});
  assert.equal(heard, 2);
});

async function firstDelay(scan, elapsedMs) {
  const h = harness([{ tvs: [], scan }]);
  const s = createStore(h.ui, { setTimer: h.setTimer, now: h.now });
  h.calls.clock += elapsedMs;
  await s.load();
  assert.equal(h.calls.timers.length, 1);
  return h.calls.timers[0].ms;
}

test("empty list with a running scan re-checks in 3000 ms", async () => {
  assert.equal(await firstDelay({ running: true, started_ms: 1, finished_ms: null }, 120000), 3000);
});

test("empty list, no finished scan, 10 s after creation re-checks in 3000 ms", async () => {
  assert.equal(await firstDelay({ running: false, finished_ms: null }, 10000), 3000);
  assert.equal(await firstDelay({}, 10000), 3000);
});

test("empty list, no finished scan, 61 s after creation re-checks in 30000 ms", async () => {
  assert.equal(await firstDelay({ running: false, finished_ms: null }, 61000), 30000);
});

test("empty list with a finished scan re-checks in 30000 ms", async () => {
  assert.equal(await firstDelay({ running: false, started_ms: 1, finished_ms: 2 }, 1000), 30000);
});

test("startup: empty with no scan, then TVs found -> render and no further re-check", async () => {
  const h = harness([{ tvs: [], scan: {} }, { tvs: [tv], scan: { running: false, finished_ms: 9 } }]);
  const s = createStore(h.ui, { setTimer: h.setTimer, now: h.now });
  await s.load();
  assert.equal(h.calls.render, 1);
  assert.equal(h.calls.timers.length, 1);
  assert.equal(h.calls.timers[0].ms, 3000);
  h.calls.clock += 3000;
  await h.calls.timers[0].fn();
  assert.equal(h.calls.render, 2);
  assert.equal(s.unavailable(), null);
  assert.equal(h.calls.timers.length, 1);
});
