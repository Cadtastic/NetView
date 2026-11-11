import { test } from "node:test";
import assert from "node:assert/strict";
import register, { makeHelpers } from "../../src/netview/plugins/builtin/health/static/ui.js";
import * as util from "../../src/netview/presentation/web/static/js/util.js";

// The plugin's UI module cannot import core modules, so it gets `ui.util` at registration; the tests hand it the same.
const { latencySub, recentValues, tileModel, dnsTileModel, latencySeries, dnsSeries, latencyCell, latencySortKey, liveModel } =
  makeHelpers(util);

const NOW = 1_800_000_000_000;
const pts = (values, step = 5000, end = NOW) => values.map((v, i) => [end - (values.length - 1 - i) * step, v]);

function fakeUi(summary) {
  const slots = [];
  let renders = 0;
  const ui = {
    util,
    apiBase: "/api/v1/plugins/health",
    apiGet: async () => summary,
    slot: (name, spec) => slots.push([name, spec]),
    requestRender: () => {
      renders++;
    },
  };
  return { ui, slots, renders: () => renders };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("the tile sub-text for samples [10, null, 20, 30] reads 25% loss, average 20 ms over 5 min", () => {
  assert.equal(latencySub([10, null, 20, 30]), "25% loss, average 20 ms over 5 min");
  assert.equal(latencySub([]), "waiting for samples");
  assert.equal(latencySub([null, null]), "100% loss, no replies over 5 min");
});

test("only samples newer than now minus 5 minutes count", () => {
  const points = [[NOW - 400000, 99], [NOW - 299000, 10], [NOW - 1000, 30]];
  assert.deepEqual(recentValues(points, NOW), [10, 30]);
  assert.deepEqual(recentValues(undefined, NOW), []);
});

test("the gateway tile shows the last value, a lost ping in the bad colour, and a dash without samples", () => {
  const tile = tileModel("Gateway ping", pts([10, null, 20, 30]), NOW);
  assert.equal(tile.value, "30");
  assert.equal(tile.unit, "ms");
  assert.equal(tile.bad, false);
  assert.equal(tile.sub, "25% loss, average 20 ms over 5 min");
  const lost = tileModel("Gateway ping", pts([10, null]), NOW);
  assert.equal(lost.value, "lost");
  assert.equal(lost.bad, true);
  const none = tileModel("Gateway ping", [], NOW);
  assert.equal(none.value, "–");
});

test("the DNS tile adds the second server to the sub-text", () => {
  const metrics = { "health.dns.192.168.1.1": pts([15]), "health.dns.1.1.1.1": pts([22.4]) };
  const two = dnsTileModel(["192.168.1.1", "1.1.1.1"], metrics, NOW);
  assert.equal(two.label, "DNS (192.168.1.1)");
  assert.equal(two.value, "15");
  assert.equal(two.sub, "1.1.1.1: 22 ms");
  const one = dnsTileModel(["192.168.1.1"], metrics, NOW);
  assert.equal(one.sub, "answer time");
  const lost = dnsTileModel(["a", "b"], { "health.dns.a": pts([3]), "health.dns.b": pts([null]) }, NOW);
  assert.equal(lost.sub, "b: no answer");
});

test("registration: three tiles, two third-width cards, the latency column and the live section", async () => {
  const f = fakeUi({ gateway: "192.168.1.1", internet: "1.1.1.1", dns: ["192.168.1.1", "1.1.1.1"] });
  register(f.ui);
  await tick();
  assert.ok(f.renders() >= 1);
  const by = (name) => f.slots.filter(([n]) => n === name).map(([, s]) => s);
  assert.deepEqual(by("dashboard.tile").map((s) => s.order), [10, 11, 12]);
  const cards = by("dashboard.card");
  assert.deepEqual(cards.map((s) => [s.title, s.order, s.span]), [["Latency", 20, "third"], ["DNS response", 21, "third"]]);
  assert.equal(cards[0].sub, "Round-trip time in ms; gaps are lost pings.");
  assert.equal(cards[1].sub, "Time to answer one lookup, in ms.");
  const [col] = by("devices.column");
  assert.deepEqual([col.id, col.label, col.sub], ["lat", "Latency", "(live, 10 min)"]);
  const [live] = by("report.live-section");
  assert.equal(live.id, "latency");

  const state = { metrics: { "health.gateway": pts([2, 3]), "health.internet": pts([null]), "health.dns.192.168.1.1": pts([15]) } };
  const html = by("dashboard.tile").map((s) => s.render(state));
  assert.ok(html[0].includes("Gateway ping"));
  assert.ok(html[1].includes("Internet ping (1.1.1.1)"));
  assert.ok(html[2].includes("DNS (192.168.1.1)"));
  assert.ok(!html.join("").includes("·"));
});

test("a summary with markup in it is escaped in the tile titles", async () => {
  const f = fakeUi({ gateway: "<b>x</b>", internet: "<script>alert(1)</script>", dns: ["<i>d</i>"] });
  register(f.ui);
  await tick();
  const html = f.slots.filter(([n]) => n === "dashboard.tile").map(([, s]) => s.render({ metrics: {} })).join("");
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("<i>"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("chart series: gateway and internet get series-1 and series-2; DNS gets one series per server", () => {
  const metrics = { "health.gateway": pts([1, 2]), "health.internet": pts([5, 6]), "health.dns.a": pts([9]), "health.dns.b": pts([8]) };
  const lat = latencySeries({ gateway: "192.168.1.1", internet: "1.1.1.1" }, metrics);
  assert.deepEqual(lat.map((s) => [s.name, s.color]), [["Gateway 192.168.1.1", "--series-1"], ["Internet 1.1.1.1", "--series-2"]]);
  assert.equal(lat[0].points.length, 2);
  const noGw = latencySeries({ gateway: null, internet: "1.1.1.1" }, metrics);
  assert.equal(noGw[0].name, "Gateway");
  const dns = dnsSeries({ dns: ["a", "b"] }, metrics);
  assert.deepEqual(dns.map((s) => [s.name, s.color]), [["a", "--series-1"], ["b", "--series-2"]]);
  const fromMetrics = dnsSeries(null, metrics);
  assert.deepEqual(fromMetrics.map((s) => s.name), ["a", "b"]);
});

test("the latency cell: values, sparkline, average and loss", () => {
  const state = { metrics: { "health.device.k1": pts([10, null, 20, 30]) } };
  const html = latencyCell({ key: "k1", status: "online" }, state);
  assert.ok(html.includes("30 ms"));
  assert.ok(html.includes("<svg"));
  assert.ok(html.includes("average 20 ms, "));
  assert.ok(html.includes('<span class="warn lossw">25% loss</span>'));
  assert.ok(!html.includes("·"));
  const clean = latencyCell({ key: "k1", status: "online" }, { metrics: { "health.device.k1": pts([2.1, 2.3]) } });
  assert.ok(clean.includes("2.3 ms"));
  assert.ok(clean.includes("0% loss"));
  assert.ok(!clean.includes("lossw"));
  const lost = latencyCell({ key: "k1", status: "online" }, { metrics: { "health.device.k1": pts([5, null]) } });
  assert.ok(lost.includes("no reply"));
});

test("the latency cell for a device with no samples", () => {
  const state = { metrics: {} };
  assert.ok(latencyCell({ key: "q", status: "quiet" }, state).includes("ignores ping"));
  assert.ok(latencyCell({ key: "self", status: "online", is_self: true }, state).includes("–"));
  assert.ok(latencyCell({ key: "x", status: "online" }, state).includes("waiting…"));
  assert.ok(latencyCell({ key: "x", status: "online" }, undefined).includes("waiting…"));
});

test("the sort key is the last value and a missing or lost value sorts last", () => {
  const state = { metrics: { "health.device.a": pts([1, 7]), "health.device.b": pts([4, null]) } };
  assert.equal(latencySortKey({ key: "a" }, state), 7);
  assert.equal(latencySortKey({ key: "b" }, state), Infinity);
  assert.equal(latencySortKey({ key: "zz" }, state), Infinity);
});

test("the live section model: tiles, chart title and the loss warning", () => {
  const state = { metrics: { "health.device.k1": pts([10, null, 20, 30, 10]) } };
  const m = liveModel({ ip: "192.168.1.9", device: { key: "k1", status: "online", ip: "192.168.1.9" }, state });
  assert.equal(m.heading, "Live");
  assert.deepEqual(m.tiles.map((t) => t.k), ["Now", "Average", "Best", "Worst", "Jitter", "Loss"]);
  const tile = (k) => m.tiles.find((t) => t.k === k);
  assert.equal(tile("Now").v, "10");
  assert.equal(tile("Best").v, "10");
  assert.equal(tile("Worst").v, "30");
  assert.equal(tile("Loss").v, "20");
  assert.equal(tile("Loss").bad, true);
  assert.equal(m.chartTitle, "Latency from this device to 192.168.1.9, last 10 min");
  assert.equal(m.series[0].name, "Ping 192.168.1.9");
  assert.equal(m.message, null);
});

test("the live section reads lost in the bad colour when the last sample is null", () => {
  const state = { metrics: { "health.device.k1": pts([10, null]) } };
  const m = liveModel({ ip: "1.2.3.4", device: { key: "k1", status: "online" }, state });
  const now = m.tiles.find((t) => t.k === "Now");
  assert.deepEqual([now.v, now.u, now.bad], ["lost", "", true]);
});

test("the live section without samples explains why", () => {
  const empty = { metrics: {} };
  const quiet = liveModel({ ip: "1.2.3.4", device: { key: "q", status: "quiet" }, state: empty });
  assert.equal(quiet.message, "1.2.3.4 ignores ping, so its latency can't be measured live. Its open ports below still work.");
  assert.equal(quiet.tiles.length, 0);
  const self = liveModel({ ip: "1.2.3.4", device: { key: "self", status: "online", is_self: true }, state: empty });
  assert.equal(self.message, "This is the device running the monitor.");
  const waiting = liveModel({ ip: "1.2.3.4", device: { key: "x", status: "online" }, state: empty });
  assert.equal(waiting.message, "Waiting for live samples…");
  const unknown = liveModel({ ip: "1.2.3.4", device: null, state: empty });
  assert.equal(unknown.message, "Waiting for live samples…");
});
