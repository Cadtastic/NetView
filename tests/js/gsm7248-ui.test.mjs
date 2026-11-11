import { test } from "node:test";
import assert from "node:assert/strict";
import {
  faceplateLayout,
  portCellHtml,
  portSortKey,
  speedShort,
} from "../../src/netview/plugins/builtin/gsm7248/static/port-grid.js";
import register, { buildMacMap, createStore, renderConnection, tileHtml } from "../../src/netview/plugins/builtin/gsm7248/static/ui.js";
import { esc, fmtRate } from "../../src/netview/presentation/web/static/js/util.js";

const eth = (n, extra = {}) => ({
  name: `0/${n}`, alias: "", kind: "ethernet", admin_up: true, oper_up: true,
  speed_mbps: 1000, stp_state: "forwarding", uplink: false, rates: null, devices: [], ...extra,
});
const ports = [
  ...Array.from({ length: 48 }, (_, i) => eth(i + 1)),
  { ...eth(1), name: "1/1", kind: "lag" },
  { ...eth(1), name: "0/49", kind: "other" },
];

test("faceplate odd top even bottom", () => {
  const f = faceplateLayout(ports);
  assert.equal(f.top[0].name, "0/1");
  assert.equal(f.bottom[0].name, "0/2");
  assert.equal(f.top.length, 24);
  assert.equal(f.bottom.length, 24);
});

test("faceplate extras", () => {
  const f = faceplateLayout(ports);
  assert.ok(f.extra.some((p) => p.name === "1/1"));
  assert.ok(f.extra.some((p) => p.name === "0/49"));
  assert.ok(!f.top.some((p) => p.name === "1/1"));
});

test("cell shows state without colour", () => {
  const down = portCellHtml(eth(3, { oper_up: false }), esc);
  assert.ok(down.includes("▼"));
  assert.ok(down.includes("link down"));
  assert.ok(down.includes("port down"));
  const blocking = portCellHtml(eth(4, { stp_state: "blocking" }), esc);
  assert.ok(blocking.includes("⏸"));
  assert.ok(blocking.includes("blocking"));
  const disabled = portCellHtml(eth(5, { admin_up: false, oper_up: false }), esc);
  assert.ok(disabled.includes("⦸"));
  const up = portCellHtml(eth(6, { uplink: true }), esc);
  assert.ok(up.includes("▲"));
  assert.ok(up.includes("uplink"));
  assert.ok(up.includes("1G"));
});

test("cell has a utilisation bar", () => {
  const html = portCellHtml(eth(7, { rates: { util_percent: 42.4 } }), esc);
  assert.ok(html.includes('<span class="util" style="--u:42%">'));
});

test("cell escapes alias", () => {
  const html = portCellHtml(eth(8, { alias: "<img onerror=x>" }), esc);
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img onerror=x&gt;"));
});

test("speedShort", () => {
  assert.equal(speedShort(1000), "1G");
  assert.equal(speedShort(100), "100M");
  assert.equal(speedShort(10), "10M");
  assert.equal(speedShort(null), "—");
  assert.equal(speedShort(10000), "10G");
});

test("portSortKey numeric", () => {
  assert.ok(portSortKey("0/2") < portSortKey("0/10"));
  assert.ok(portSortKey("0/48") < portSortKey("1/1"));
  assert.equal(typeof portSortKey("0/5"), "number");
  assert.equal(portSortKey("0/2"), 2);
  assert.equal(portSortKey("1/1"), 1001);
  assert.equal(portSortKey(""), Infinity);
});

// ---- ui.js: tile, column, store, settings section
const summary = (extra = {}) => ({
  configured: true, reachable: true, last_error: null,
  switch: { name: "sw" }, health: { cpu_percent: 7 },
  ports: { total: 48, up: 5, uplinks: 1 }, throughput_bps: { in: 12300000, out: 1000 }, ...extra,
});

test("tile: values, no middle dot", () => {
  const html = tileHtml(summary(), esc, fmtRate);
  assert.ok(html.includes("5<small>of 48 ports up</small>"));
  assert.ok(html.includes("↓ 12 Mbit/s"));
  assert.ok(html.includes(", CPU 7%"));
  assert.ok(!html.includes("·"));
});

test("tile: not configured and unreachable", () => {
  assert.ok(tileHtml(summary({ configured: false }), esc, fmtRate).includes("Set up in Settings"));
  const bad = tileHtml(summary({ reachable: false, last_error: "timeout" }), esc, fmtRate);
  assert.ok(bad.includes("v bad"));
  assert.ok(bad.includes("⚠"));
  assert.ok(bad.includes("Unreachable"));
  assert.ok(bad.includes("timeout"));
});

test("buildMacMap prefers a direct port over an uplink", () => {
  const map = buildMacMap([
    { mac: "AA:BB", port: "0/11", via_uplink: true },
    { mac: "aa:bb", port: "0/5", via_uplink: false },
    { mac: "cc:dd", port: "0/11", via_uplink: true },
    { mac: "ee:ff", port: null, via_uplink: false },
  ]);
  assert.deepEqual(map.get("aa:bb"), { port: "0/5", via: false });
  assert.deepEqual(map.get("cc:dd"), { port: "0/11", via: true });
  assert.equal(map.has("ee:ff"), false);
});

function fakeUi(responses) {
  const slots = {};
  const calls = [];
  const ui = {
    util: { esc, fmtRate },
    pluginId: "gsm7248",
    apiBase: "/api/v1/plugins/gsm7248",
    apiGet: async (path) => {
      calls.push(path);
      return responses[path.split("/").pop()];
    },
    apiSend: async () => ({}),
    slot: (name, spec) => (slots[name] = spec),
    requestRender: () => {},
  };
  return { ui, slots, calls };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("store throttles to one fetch per 10 s unless forced", async () => {
  let t = 1000;
  const f = fakeUi({ summary: summary(), ports: [], macs: [], vlans: [] });
  const store = createStore(f.ui, () => t);
  await store.refresh(true);
  assert.equal(f.calls.length, 4);
  t += 5000;
  await store.refresh();
  assert.equal(f.calls.length, 4);
  t += 6000;
  await store.refresh();
  assert.equal(f.calls.length, 8);
  await store.refresh(true);
  assert.equal(f.calls.length, 12);
});

test("devices column: text, sort and group by port", async () => {
  const f = fakeUi({
    summary: summary(), ports: [], vlans: [],
    macs: [
      { mac: "aa:aa", port: "0/5", via_uplink: false },
      { mac: "bb:bb", port: "0/11", via_uplink: true },
    ],
  });
  register(f.ui);
  await tick();
  const col = f.slots["devices.column"];
  assert.equal(col.id, "port");
  assert.equal(col.label, "Switch port");
  assert.equal(col.text({ mac: "AA:AA" }), "0/5");
  assert.equal(col.text({ mac: "bb:bb" }), "via 0/11");
  assert.equal(col.text({ mac: "zz" }), "");
  assert.equal(typeof col.sortKey({ mac: "aa:aa" }), "number");
  assert.equal(col.sortKey({ mac: "zz" }), Infinity);
  assert.equal(col.groupKey({ mac: "bb:bb" }), "0/11");
  assert.equal(f.slots.page.id, "switch");
  assert.equal(f.slots.page.title, "Switch");
  assert.equal(f.slots["settings.section"].title, "Connection");
});

test("test connection button posts an empty body and shows sys_descr or the error", async () => {
  const listeners = {};
  const out = { textContent: "", classList: { add() {}, remove() {} } };
  const btn = { disabled: false, addEventListener: (_e, fn) => (listeners.click = fn) };
  const body = { innerHTML: "", querySelector: (sel) => (sel === "[data-act=test]" ? btn : out) };
  const sent = [];
  let reply = { ok: "true", sys_descr: "GSM7248 switch" };
  renderConnection(body, {
    apiBase: "/api/v1/plugins/gsm7248",
    apiSend: async (method, path, b) => {
      sent.push([method, path, b]);
      return reply;
    },
    util: {},
  });
  await listeners.click();
  assert.deepEqual(sent[0], ["POST", "/api/v1/plugins/gsm7248/test", {}]);
  assert.ok(out.textContent.includes("GSM7248 switch"));
  reply = { ok: "false", error: "timeout" };
  await listeners.click();
  assert.ok(out.textContent.includes("timeout"));
  assert.equal(btn.disabled, false);
});
