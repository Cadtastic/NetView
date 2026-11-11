import { test } from "node:test";
import assert from "node:assert/strict";
import { scanSummary, pasteWrapper, scanInProgress, isAlreadyRunning, bindToBody } from "../../static/settings.js";
import { createStore } from "../../static/store.js";

test("scanSummary wording", () => {
  assert.equal(scanSummary({ finished_ms: null }), "No scan yet.");
  assert.match(
    scanSummary({ finished_ms: 1, found: 3, by_ssdp: 2, by_sweep: 3, duration_s: 4.6 }, () => "10:00"),
    /^Last scan 10:00: 3 found \(2 by SSDP, 3 by address check\)\. Took 4\.6 s\.$/,
  );
});

test("pasteWrapper wraps for each OS", () => {
  assert.equal(pasteWrapper("win", "x"), "@'\nx\n'@ | python -");
  assert.equal(pasteWrapper("unix", "x"), "python3 - <<'EOF'\nx\nEOF");
});

test("scanSummary counts what each method found, even when SSDP found TVs outside the sweep", () => {
  assert.match(scanSummary({ finished_ms: 1, found: 4, by_ssdp: 3, by_sweep: 1, duration_s: 1 }, () => "t"), /4 found \(3 by SSDP, 1 by address check\)/);
});

test("scanInProgress: only a scan reported as running", () => {
  assert.equal(scanInProgress({ running: true }), true);
  assert.equal(scanInProgress({ running: false }), false);
  assert.equal(scanInProgress(null), false);
  assert.equal(scanInProgress(undefined), false);
});

test("isAlreadyRunning goes by the 409 status, not the message", () => {
  assert.equal(isAlreadyRunning({ status: 409, message: "busy" }), true);
  assert.equal(isAlreadyRunning({ status: 500, message: "scan already running" }), false);
  assert.equal(isAlreadyRunning(new Error("x")), false);
  assert.equal(isAlreadyRunning(null), false);
});

test("bindToBody unsubscribes from the store when the body is removed", async () => {
  const store = createStore({ apiBase: "/x", apiGet: async () => ({ tvs: [{ id: "a" }], scan: {} }), requestRender() {} });
  let calls = 0;
  const body = { isConnected: true };
  let observer;
  class FakeObserver {
    constructor(cb) { this.cb = cb; observer = this; this.stopped = false; }
    observe() {}
    disconnect() { this.stopped = true; }
  }
  bindToBody(body, store, () => { calls += 1; }, FakeObserver, { body: {} });
  await store.load();
  assert.equal(calls, 1);
  body.isConnected = false;
  observer.cb(); // the DOM changed and the body is gone
  assert.equal(observer.stopped, true);
  await store.load();
  assert.equal(calls, 1);
});

test("bindToBody also stops when a store update finds the body gone", async () => {
  const store = createStore({ apiBase: "/x", apiGet: async () => ({ tvs: [{ id: "a" }], scan: {} }), requestRender() {} });
  let calls = 0;
  const body = { isConnected: true };
  let observer;
  class FakeObserver { constructor() { observer = this; this.stopped = false; } observe() {} disconnect() { this.stopped = true; } }
  bindToBody(body, store, () => { calls += 1; }, FakeObserver, { body: {} });
  body.isConnected = false;
  await store.load();
  assert.equal(calls, 0);
  assert.equal(observer.stopped, true);
});
