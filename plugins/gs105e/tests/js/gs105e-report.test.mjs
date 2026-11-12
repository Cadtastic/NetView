import { test } from "node:test";
import assert from "node:assert/strict";
import { reportModel } from "../../static/report.js";

const summary = {
  configured: true, host: "192.168.1.5", reachable: true, login: "ok", ports: { total: 5, up: 2 },
  throughput_bps: { in: 10, out: 20 }, switch: { name: "sw", product: "GS105Ev2", firmware: "V1.6.0.11" },
};

test("reportModel is null for another IP or no summary", () => {
  assert.equal(reportModel(summary, "192.168.1.9"), null);
  assert.equal(reportModel(null, "192.168.1.5"), null);
});

test("reportModel gives tiles for the switch IP", () => {
  const m = reportModel(summary, "192.168.1.5");
  assert.equal(m.heading, "NETGEAR GS105E");
  const tile = (k) => (m.tiles.find((t) => t.k === k) || {}).v;
  assert.equal(tile("Ports up"), "2 of 5");
  assert.equal(tile("Firmware"), "V1.6.0.11");
  assert.equal(tile("Reachable"), "yes");
  assert.ok(m.link);
});

test("reportModel matches the switch's own address when the host setting is a name", () => {
  const named = { ...summary, host: "switch.lan", switch: { ...summary.switch, ip: "192.168.1.5" } };
  assert.ok(reportModel(named, "192.168.1.5"));
  assert.equal(reportModel(named, "192.168.1.9"), null);
});

test("reportModel shows a dash for throughput when there are no live rates", () => {
  const m = reportModel({ ...summary, throughput_bps: null }, "192.168.1.5");
  assert.equal(m.tiles.find((t) => t.k === "Throughput").v, "–");
});
