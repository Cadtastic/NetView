import { test } from "node:test";
import assert from "node:assert/strict";
import { availableColumns, pluginEnabled, visibleColumns, canHide, groupKey, sortDevices } from "../../src/netview/presentation/web/static/js/table-model.js";

const COLS = [
  { id: "status", label: "Status", fixed: true },
  { id: "nickname", label: "Nickname" },
  { id: "device_name", label: "Device name" },
  { id: "ip", label: "IP", fixed: true },
  { id: "vendor", label: "Vendor" },
  { id: "actions", label: "Actions", fixed: true },
];
const ids = (cols) => cols.map((c) => c.id);

test("visibleColumns drops hidden columns", () => {
  assert.deepEqual(ids(visibleColumns(COLS, new Set(["vendor"]), "none")), ["status", "nickname", "device_name", "ip", "actions"]);
});

test("visibleColumns drops the grouping column but keeps status otherwise", () => {
  assert.deepEqual(ids(visibleColumns(COLS, new Set(), "vendor")), ["status", "nickname", "device_name", "ip", "actions"]);
  assert.ok(!ids(visibleColumns(COLS, new Set(), "status")).includes("status"));
  assert.ok(ids(visibleColumns(COLS, new Set(), "none")).includes("status"));
});

test("canHide refuses to hide both name columns", () => {
  assert.deepEqual(canHide("nickname", new Set(["device_name"])), { ok: false, reason: "needed while Device name is hidden" });
  assert.deepEqual(canHide("device_name", new Set(["nickname"])), { ok: false, reason: "needed while Nickname is hidden" });
  assert.equal(canHide("nickname", new Set()).ok, true);
});

test("canHide refuses fixed columns", () => {
  const r = canHide("ip", new Set());
  assert.equal(r.ok, false);
  assert.equal(r.reason, "always shown");
});

test("groupKey uses the first capture group of the IP regex", () => {
  assert.equal(groupKey({ ip: "192.168.1.7" }, "ip", /^(\d+\.\d+\.\d+)\./), "192.168.1");
  assert.equal(groupKey({ ip: "fe80::1" }, "ip", /^(\d+\.\d+\.\d+)\./), "(no match)");
});

test("groupKey accepts the regex as a string and throws on an invalid one", () => {
  assert.equal(groupKey({ ip: "10.0.0.5" }, "ip", String.raw`^(\d+\.\d+)\.`), "10.0");
  assert.throws(() => groupKey({ ip: "10.0.0.5" }, "ip", "("), Error);
});

test("groupKey for the other modes", () => {
  assert.equal(groupKey({ status: "online" }, "status", null), "Online");
  assert.equal(groupKey({ type: "" }, "type", null), "Unknown type");
  assert.equal(groupKey({ vendor: "" }, "vendor", null), "Unknown vendor");
  assert.equal(groupKey({}, "none", null), "");
});

test("sortDevices compares IPs numerically by default", () => {
  const out = sortDevices([{ ip: "192.168.1.10" }, { ip: "192.168.1.2" }], "ip", 1, COLS);
  assert.deepEqual(out.map((d) => d.ip), ["192.168.1.2", "192.168.1.10"]);
  const desc = sortDevices([{ ip: "192.168.1.2" }, { ip: "192.168.1.10" }], "ip", -1, COLS);
  assert.deepEqual(desc.map((d) => d.ip), ["192.168.1.10", "192.168.1.2"]);
});

test("sortDevices lets a column's sortKey win", () => {
  const cols = [{ id: "x", sortKey: (d) => d.x }];
  const out = sortDevices([{ ip: "10.0.0.1", x: 5 }, { ip: "10.0.0.2", x: 1 }], "x", 1, cols);
  assert.deepEqual(out.map((d) => d.x), [1, 5]);
});

test("sortDevices does not mutate its input", () => {
  const input = [{ ip: "10.0.0.2" }, { ip: "10.0.0.1" }];
  sortDevices(input, "ip", 1, COLS);
  assert.equal(input[0].ip, "10.0.0.2");
});

test("availableColumns leaves out a column whose available() says no, or throws", () => {
  const seen = [];
  const cols = [
    { id: "ip" },
    { id: "p.yes", available: (state) => (seen.push(state), true) },
    { id: "p.no", available: () => false },
    { id: "p.falsy", available: () => undefined },
    { id: "p.boom", available: () => { throw new Error("x"); } },
  ];
  const state = { devices: [] };
  assert.deepEqual(ids(availableColumns(cols, state)), ["ip", "p.yes"]);
  assert.deepEqual(seen, [state]);
});

test("pluginEnabled: off only when the plugin list says so", () => {
  const plugins = [{ id: "a", enabled: true }, { id: "b", enabled: false }];
  assert.equal(pluginEnabled(plugins, "a"), true);
  assert.equal(pluginEnabled(plugins, "b"), false);
  assert.equal(pluginEnabled(plugins, "unknown"), true);
  assert.equal(pluginEnabled(null, "a"), true);
});
