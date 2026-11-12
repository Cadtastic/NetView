import { test } from "node:test";
import assert from "node:assert/strict";
import { createUiHost } from "../../src/netview/presentation/web/static/js/slots.js";

function hostWithTwo() {
  const host = createUiHost();
  host.slot("page", { id: "main", title: "A", pluginId: "7", pluginGuid: "g7" });
  host.slot("dashboard.tile", { id: "t", pluginId: "7", pluginGuid: "g7" });
  host.slot("page", { id: "main", title: "B", pluginId: "8", pluginGuid: "g8" });
  host.errors["7"] = "boom";
  return host;
}

test("removePlugin drops every slot of that plugin and keeps the others", () => {
  const host = hostWithTwo();
  host.removePlugin("7", "/devices");
  assert.deepEqual(host.get("page").map((s) => s.pluginId), ["8"]);
  assert.equal(host.get("dashboard.tile").length, 0);
  assert.equal("7" in host.errors, false);
});

test("removePlugin reports whether the current route was one of its pages", () => {
  assert.equal(hostWithTwo().removePlugin("7", "/p/7/main"), true);
  assert.equal(hostWithTwo().removePlugin("7", "/p/8/main"), false);
  assert.equal(hostWithTwo().removePlugin("7", "/p/70/main"), false);
  assert.equal(hostWithTwo().removePlugin("7", "/"), false);
});
