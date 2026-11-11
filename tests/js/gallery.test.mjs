import { test } from "node:test";
import assert from "node:assert/strict";
import { attention, pluginStatus } from "../../src/netview/presentation/web/static/js/settings/gallery.js";

const p = (o = {}) => ({ id: "a", name: "A", enabled: true, state: "active", configured: true, ...o });

test("pluginStatus precedence", () => {
  assert.equal(pluginStatus(p({ state: "failed", restart_required: true, error: "boom" })).kind, "bad");
  assert.deepEqual(pluginStatus(p({ state: "pending", enabled: true })), { kind: "restart", tip: "Awaiting restart" });
  assert.equal(pluginStatus(p({ restart_required: true })).kind, "restart");
  assert.deepEqual(pluginStatus(p({ enabled: false, state: "disabled", configured: false })), { kind: "off", tip: "Off" });
  assert.deepEqual(pluginStatus(p({ configured: false })), { kind: "warn", tip: "Needs configuring" });
  assert.deepEqual(pluginStatus(p()), { kind: "ok", tip: "Active" });
});

test("pluginStatus: Failed shows the first line only", () => {
  assert.equal(pluginStatus(p({ state: "failed", error: "ImportError: x\n  File y\nmore" })).tip, "Failed: ImportError: x");
});

test("attention picks bad over warn", () => {
  assert.equal(attention([p(), p({ configured: false })]), "warn");
  assert.equal(attention([p({ configured: false }), p({ state: "failed", error: "e" })]), "bad");
  assert.equal(attention([p(), p({ state: "pending" })]), "bad");
  assert.equal(attention([p({ restart_required: true })]), "bad");
  assert.equal(attention([p()]), null);
});
