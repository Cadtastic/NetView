import { test } from "node:test";
import assert from "node:assert/strict";
import { scanButtonState, scanErrorMessage } from "../../src/netview/presentation/web/static/js/scan.js";

const base = { capabilities: ["discovery", "api"], jobs: [] };

test("scan button is ready when discovery is available", () => {
  assert.deepEqual(scanButtonState(base, false), { disabled: false, label: "Scan now", title: "" });
});

test("scan button is disabled while scanning", () => {
  const s = scanButtonState(base, true);
  assert.equal(s.disabled, true);
  assert.equal(s.label, "Scanning…");
});

test("scan button follows a running core scan job", () => {
  const s = scanButtonState({ ...base, jobs: [{ owner: "core", name: "scan", running: true }] }, false);
  assert.equal(s.disabled, true);
  assert.equal(s.label, "Scanning…");
});

test("scan button explains a missing discovery plugin", () => {
  const s = scanButtonState({ capabilities: ["api"], jobs: [] }, false);
  assert.equal(s.disabled, true);
  assert.equal(s.label, "Scan now");
  assert.equal(s.title, "No discovery plugin is turned on");
});

test("scan button without state is disabled", () => {
  assert.equal(scanButtonState(null, false).disabled, true);
});

test("scanErrorMessage uses the server message, with a fallback", () => {
  assert.equal(scanErrorMessage({ status: 409, message: "Scan already running" }), "Scan already running");
  assert.equal(scanErrorMessage({ status: 503, message: "" }), "There is no network to scan");
  assert.equal(scanErrorMessage({ status: 409, message: "" }), "A scan is already running");
  assert.equal(scanErrorMessage({ status: 500, message: "" }), "The scan failed");
});
