import { test } from "node:test";
import assert from "node:assert/strict";
import {
  jackBox, jackHtml, ledBoxes, ledState, portChartSeries, portState, speedShort, vlanColors,
} from "../../static/port-grid.js";
import { esc } from "../../../../src/netview/presentation/web/static/js/util.js";

const port = (n, extra = {}) => ({
  port: n, description: "", up: true, speed_setting: "Auto", link_mbps: 1000, flow_control: false, max_mtu: 9216,
  in_bps: 1000, out_bps: 2000, util_percent: 12.4, crc_errors: 0, crc_delta: 0, pvid: 1, vlan_member: "U",
  ingress_kbps: null, egress_kbps: null, mirror: null, ...extra,
});

test("jackBox matches the faceplate geometry", () => {
  assert.deepEqual(jackBox(1), { left: 21.277, top: 38.519, width: 13.83, height: 43.704 });
  assert.equal(jackBox(6), null);
  assert.equal(jackBox(0), null);
  assert.equal(jackBox(2.5), null);
  assert.equal(jackBox(5).left, 83.404);
});

test("ledState follows the link speed", () => {
  assert.deepEqual(ledState(1000), { left: true, right: true });
  assert.deepEqual(ledState(100), { left: true, right: false });
  assert.deepEqual(ledState(10), { left: false, right: true });
  assert.deepEqual(ledState(null), { left: false, right: false });
});

test("ledBoxes sit at x+8 and x+96 inside the jack", () => {
  const b = ledBoxes(1);
  assert.deepEqual(b.left, { left: 22.128, top: 40.741, width: 2.766, height: 4.444 });
  assert.equal(b.right.left, 31.489);
  assert.equal(ledBoxes(9), null);
});

test("speedShort", () => {
  assert.equal(speedShort(1000), "1G");
  assert.equal(speedShort(100), "100M");
  assert.equal(speedShort(10), "10M");
  assert.equal(speedShort(null), "—");
});

test("portState has words as well as a class", () => {
  assert.deepEqual(portState(port(1)), { cls: "up", words: "link up" });
  assert.equal(portState(port(1, { up: false })).cls, "down");
  assert.equal(portState(port(1, { up: false })).words, "link down");
  const off = portState(port(1, { up: false, speed_setting: "Disable" }));
  assert.equal(off.cls, "disabled");
  assert.equal(off.words, "admin disabled");
});

test("vlanColors uses the fixed palette in id order", () => {
  const c = vlanColors([20, 1, 20]);
  assert.equal(c.get(1), "#94a3b8");
  assert.equal(c.get(20), "#a855f7");
});

test("jackHtml (status) shows words for a down port", () => {
  const html = jackHtml(port(3, { up: false, link_mbps: null, in_bps: null }), esc, "status", null);
  assert.ok(html.startsWith('<button type="button" class="g5e-jack down'));
  assert.ok(html.includes('data-port="3"'));
  assert.ok(html.includes("link down"));
  assert.ok(html.includes('aria-label="'));
  assert.ok(html.includes("—"));
});

test("jackHtml (status) shows speed, LEDs and the mirror badge", () => {
  const html = jackHtml(port(1, { mirror: "source", description: "<b>x</b>" }), esc, "status", null);
  assert.ok(html.includes("1G"));
  assert.ok(html.includes("mirror source"));
  assert.ok(html.includes('class="g5e-led on"'));
  assert.ok(!html.includes("<b>x</b>"));
  assert.equal(jackHtml(port(9), esc, "status", null), "");
});

test("jackHtml (vlan) shows the VLAN id and membership word", () => {
  const colors = vlanColors([1, 20]);
  const html = jackHtml(port(2, { pvid: 20, vlan_member: "T" }), esc, "vlan", colors);
  assert.ok(html.includes("vlan"));
  assert.ok(html.includes("20"));
  assert.ok(html.includes("tagged"));
  assert.ok(html.includes("--vc:#a855f7"));
});

test("portChartSeries keeps In then Out", () => {
  const s = portChartSeries([{ t_ms: 1, in_bps: 5, out_bps: 6 }]);
  assert.deepEqual(s.map((x) => [x.name, x.color]), [["In", "--series-1"], ["Out", "--series-2"]]);
  assert.deepEqual(s[1].points, [[1, 6]]);
  assert.deepEqual(portChartSeries(null).map((x) => x.points), [[], []]);
});
