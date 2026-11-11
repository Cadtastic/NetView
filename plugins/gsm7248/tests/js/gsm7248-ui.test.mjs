import { test } from "node:test";
import assert from "node:assert/strict";
import {
  faceplateLayout,
  portCellHtml,
  portRanges,
  portSortKey,
  speedShort,
} from "../../static/port-grid.js";
import register, { buildMacMap, createStore, renderConnection, renderSshTest, sshTestResult, switchAvailable, tileHtml } from "../../static/ui.js";
import { esc, fmtRate } from "../../../../src/netview/presentation/web/static/js/util.js";

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
  assert.ok(bad.includes("v word bad"));
  assert.ok(bad.includes("⚠"));
  assert.ok(bad.includes("Unreachable"));
  assert.ok(bad.includes("timeout"));
});

test("tile: an error before the first poll is shown, not 'waiting'", () => {
  const html = tileHtml(summary({ reachable: null, switch: null, last_error: "SnmpError: SNMP request failed: PySnmpError" }), esc, fmtRate);
  assert.ok(html.includes("v word bad"));
  assert.ok(html.includes("SNMP request failed"));
  assert.ok(!html.includes("waiting for the first poll"));
  const idle = tileHtml(summary({ reachable: null, switch: null, last_error: null }), esc, fmtRate);
  assert.ok(idle.includes("waiting for the first poll"));
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
  const all = {};
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
    slot: (name, spec) => {
      slots[name] = spec;
      (all[name] ??= []).push(spec);
    },
    requestRender: () => {},
  };
  return { ui, slots, all, calls };
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

test("switchAvailable: only a set-up plugin whose last poll reached the switch", () => {
  const ok = { summary: { configured: true, reachable: true }, error: null };
  assert.equal(switchAvailable(ok), true);
  assert.equal(switchAvailable({ ...ok, summary: { configured: true, reachable: false } }), false);
  assert.equal(switchAvailable({ ...ok, summary: { configured: true, reachable: null } }), false);
  assert.equal(switchAvailable({ ...ok, summary: { configured: false, reachable: true } }), false);
  assert.equal(switchAvailable({ ...ok, error: "404: plugin is off" }), false);
  assert.equal(switchAvailable({ summary: null, error: null }), false);
  assert.equal(switchAvailable(null), false);
});

test("devices column is offered only while the switch is reachable, and keeps asking", async () => {
  let reachable = false;
  let t = 0;
  const f = fakeUi({});
  f.ui.apiGet = async (path) => {
    f.calls.push(path);
    return path.endsWith("/summary") ? { ...summary(), reachable } : [];
  };
  register(f.ui, () => t);
  await tick();
  const col = f.slots["devices.column"];
  assert.equal(col.available(), false);
  // the hidden column draws no cells, so available() itself must keep the data fresh
  reachable = true;
  t += 11000;
  assert.equal(col.available(), false);
  await tick();
  assert.equal(col.available(), true);
  reachable = false;
  t += 11000;
  col.available();
  await tick();
  assert.equal(col.available(), false);
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
  assert.deepEqual(
    f.all["settings.section"].map((s) => [s.title, s.tab]),
    [["Test the SNMP connection", "SNMP"], ["Test the SSH connection", "SSH"]],
  );
});

test("devices column refreshes /macs at most once per 10 s while only the Devices page is mounted", async () => {
  let t = 1000;
  let macs = [];
  const f = fakeUi({ summary: summary(), ports: [], vlans: [], macs });
  const origGet = f.ui.apiGet;
  f.ui.apiGet = async (path) => (path.endsWith("/macs") ? (f.calls.push(path), macs) : origGet(path));
  register(f.ui, () => t);
  await tick();
  const col = f.slots["devices.column"];
  const macCalls = () => f.calls.filter((c) => c.endsWith("/macs")).length;
  assert.equal(macCalls(), 1);
  assert.equal(col.text({ mac: "aa:aa" }), "");
  t += 5000;
  col.text({ mac: "aa:aa" });
  await tick();
  assert.equal(macCalls(), 1);
  macs = [{ mac: "aa:aa", port: "0/7", via_uplink: false }];
  t += 6000;
  col.text({ mac: "aa:aa" });
  await tick();
  assert.equal(macCalls(), 2);
  assert.equal(col.text({ mac: "aa:aa" }), "0/7");
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

test("portRanges compresses runs within a slot", () => {
  const all = Array.from({ length: 48 }, (_, i) => `0/${i + 1}`);
  assert.equal(portRanges(all), "0/1–0/48");
  assert.equal(portRanges(["0/3", "0/1", "0/2", "0/5", "0/6", "1/1", "1/2", "1/3", "cpu"]), "0/1–0/3, 0/5, 0/6, 1/1–1/3, cpu");
  assert.equal(portRanges([]), "");
});

test("report draw fetches once per port per 15 s", async () => {
  let t = 1000;
  const f = fakeUi({
    summary: summary(), ports: [], vlans: [],
    macs: [{ mac: "aa:aa", port: "0/5", via_uplink: false }],
    5: { name: "0/5", oper_up: true, speed_mbps: 1000, duplex: "full", devices: [{ mac: "aa:aa" }], mac_history: [], rates: null, vlans: { untagged: [], tagged: [] } },
    samples: [],
  });
  let renders = 0;
  f.ui.requestRender = () => renders++;
  f.ui.util.lineChart = () => {};
  f.ui.util.fmtAgo = String;
  globalThis.document = { head: { appendChild() {} }, createElement: () => ({ children: [], dataset: {}, style: {}, append() {}, set textContent(_v) {} }), createTextNode: () => ({}) };
  register(f.ui, () => t);
  await tick();
  const sec = f.slots["report.live-section"];
  assert.equal(sec.id, "gsm7248-port");
  const box = { dataset: {}, children: [], isConnected: true, append() {}, set textContent(_v) {} };
  const before = f.calls.length;
  for (let i = 0; i < 50; i++) sec.draw(box, { ip: "1.2.3.4", device: { mac: "AA:AA" }, state: {} });
  await tick();
  assert.deepEqual(f.calls.slice(before).sort(), ["/api/v1/plugins/gsm7248/ports/0/5", "/api/v1/plugins/gsm7248/ports/0/5/samples"]);
  assert.equal(f.calls.filter((c) => c.endsWith("/macs")).length, 1, "/macs refresh is throttled");
  assert.ok(renders >= 1);
  t += 16000;
  sec.draw(box, { ip: "1.2.3.4", device: { mac: "AA:AA" }, state: {} });
  await tick();
  assert.equal(f.calls.length - before, 8, "2 initial + 2 port + 4 MAC-map refresh");
  // a device the switch has never seen makes no requests
  const n = f.calls.length;
  sec.draw(box, { ip: "9.9.9.9", device: { mac: "zz" }, state: {} });
  sec.draw(box, { ip: "9.9.9.9", device: null, state: {} });
  assert.equal(f.calls.length, n);
  delete globalThis.document;
});

test("report: a landed fetch repaints the open box itself, and draws refresh the MAC map at most every 10 s", async () => {
  let t = 1000;
  const f = fakeUi({
    summary: summary(), ports: [], vlans: [],
    macs: [{ mac: "aa:aa", port: "0/5", via_uplink: false }],
    5: { name: "0/5", oper_up: true, speed_mbps: 1000, duplex: "full", devices: [{ mac: "aa:aa" }], mac_history: [], rates: null, vlans: { untagged: [], tagged: [] } },
    samples: [{ t_ms: 1, in_bps: 1, out_bps: 2 }],
  });
  const charts = [];
  f.ui.util.lineChart = (_el, o) => charts.push(o);
  f.ui.util.fmtAgo = String;
  const mk = () => ({ children: [], dataset: {}, style: {}, hidden: false, append() {}, set textContent(_v) {} });
  globalThis.document = { head: { appendChild() {} }, createElement: mk, createTextNode: () => ({}) };
  register(f.ui, () => t);
  await tick();
  const sec = f.slots["report.live-section"];
  const box = mk();
  box.isConnected = true;
  sec.draw(box, { ip: "1.2.3.4", device: { mac: "aa:aa" }, state: {} });
  assert.equal(charts.length, 0, "nothing to chart before the fetch lands");
  await tick();
  assert.equal(charts.length, 1, "repainted without another draw");
  // a disconnected box is not repainted
  t += 16000;
  box.isConnected = false;
  sec.draw(box, { ip: "1.2.3.4", device: { mac: "aa:aa" }, state: {} });
  assert.equal(charts.length, 2, "the draw itself paints from cache");
  await tick();
  assert.equal(charts.length, 2, "no repaint into a disconnected box");
  // 50 draws over 25 s fetch /macs at most 3 times
  const macsBefore = f.calls.filter((c) => c.endsWith("/macs")).length;
  for (let i = 0; i < 50; i++) {
    t += 500;
    sec.draw(box, { ip: "1.2.3.4", device: { mac: "aa:aa" }, state: {} });
    await tick();
  }
  assert.ok(f.calls.filter((c) => c.endsWith("/macs")).length - macsBefore <= 3);
  delete globalThis.document;
});

test("sshTestResult says what was and was not proven", () => {
  const r = (state, extra = {}) => sshTestResult({ status: { state, detail: "D", text: "", ...extra } });
  assert.deepEqual(r("connected", { text: "User:\nmore" }), { ok: true, text: "✓ SSH works and the switch answered: User:" });
  assert.equal(r("in_use").ok, true);
  assert.ok(r("in_use").text.includes("not tested"));
  assert.equal(r("silent").ok, false);
  assert.ok(r("silent").text.startsWith("⚠ SSH works"));
  assert.ok(r("no_device").text.startsWith("⚠ SSH works"));
  assert.deepEqual(r("unreachable"), { ok: false, text: "⚠ D" });
  assert.equal(sshTestResult(null).ok, false);
});

test("test SSH button posts an empty body to the probe and shows the result or the error", async () => {
  const listeners = {};
  const out = { textContent: "", classList: { add() {}, remove() {} } };
  const btn = { disabled: false, addEventListener: (_e, fn) => (listeners.click = fn) };
  const body = { innerHTML: "", querySelector: (sel) => (sel === "[data-act=test]" ? btn : out) };
  const sent = [];
  let reply = async () => ({ status: { state: "unreachable", detail: "Host key verification failed.", text: "" } });
  renderSshTest(body, {
    apiBase: "/api/v1/plugins/gsm7248",
    apiSend: (method, path, b) => {
      sent.push([method, path, b]);
      return reply();
    },
  });
  assert.ok(body.innerHTML.includes("one Enter"));
  await listeners.click();
  assert.deepEqual(sent[0], ["POST", "/api/v1/plugins/gsm7248/console/probe", {}]);
  assert.equal(out.textContent, "⚠ Host key verification failed.");
  reply = async () => {
    throw new Error("The serial console is turned off in Settings");
  };
  await listeners.click();
  assert.ok(out.textContent.includes("turned off"));
  assert.equal(btn.disabled, false);
});
