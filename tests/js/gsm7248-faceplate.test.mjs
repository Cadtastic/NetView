import { test } from "node:test";
import assert from "node:assert/strict";
import {
  facePort,
  faceplateLayout,
  jackBox,
  jackHtml,
  portRanges,
  portSortKey,
  sfpBox,
  vlanColors,
  vlanLegend,
  vlanView,
} from "../../src/netview/plugins/builtin/gsm7248/static/port-grid.js";
import { esc } from "../../src/netview/presentation/web/static/js/util.js";

const eth = (name, extra = {}) => ({
  name, alias: "", kind: "ethernet", admin_up: true, oper_up: true, speed_mbps: 1000, stp_state: "forwarding",
  uplink: false, rates: null, devices: [], pvid: 1, vlans: { untagged: [1], tagged: [] }, ...extra,
});

test("facePort reads both name forms", () => {
  assert.equal(facePort("0/1"), 1);
  assert.equal(facePort("0/48"), 48);
  assert.equal(facePort("1/0/1"), 1);
  assert.equal(facePort("1/0/48"), 48);
  assert.equal(facePort("0/49"), null);
  assert.equal(facePort("1/1"), null);
  assert.equal(facePort("3/1"), null);
  assert.equal(facePort("1/1/1"), null);
  assert.equal(facePort("cpu"), null);
  assert.equal(facePort(null), null);
});

test("unit/slot/port names land on the faceplate", () => {
  const ports = [
    ...Array.from({ length: 48 }, (_, i) => eth(`1/0/${i + 1}`)),
    { ...eth("0/3/1"), kind: "lag" },
  ];
  const f = faceplateLayout(ports);
  assert.equal(f.top.length, 24);
  assert.equal(f.bottom.length, 24);
  assert.equal(f.top[0].name, "1/0/1");
  assert.equal(f.bottom[23].name, "1/0/48");
  assert.deepEqual(f.extra.map((p) => p.name), ["0/3/1"]);
});

test("three-part names sort and range", () => {
  assert.ok(portSortKey("1/0/2") < portSortKey("1/0/10"));
  assert.ok(portSortKey("0/48") < portSortKey("1/0/1"));
  assert.equal(portRanges(["1/0/3", "1/0/1", "1/0/2", "1/0/7"]), "1/0/1–1/0/3, 1/0/7");
});

test("jackBox places odd ports on top and even below, in four blocks", () => {
  const b1 = jackBox(1);
  const b2 = jackBox(2);
  const b3 = jackBox(3);
  const b13 = jackBox(13);
  assert.equal(b1.left, b2.left);
  assert.ok(b2.top > b1.top);
  assert.ok(b3.left > b1.left);
  // 54-unit pitch inside a block, and a wider step across the gap between blocks
  const pitch = b3.left - b1.left;
  assert.ok(Math.abs(pitch - (54 / 1930) * 100) < 0.01);
  assert.ok(b13.left - jackBox(11).left > pitch * 1.3);
  const b48 = jackBox(48);
  assert.ok(b48.left + b48.width < 100);
  assert.equal(jackBox(49), null);
});

test("sfpBox only for the combo ports", () => {
  assert.equal(sfpBox(44), null);
  const a = sfpBox(45);
  const b = sfpBox(46);
  const c = sfpBox(47);
  assert.equal(a.left, b.left);
  assert.ok(b.top > a.top);
  assert.ok(c.left > a.left);
  assert.ok(a.left > jackBox(47).left + jackBox(47).width);
});

test("vlanView: access, trunk and none", () => {
  assert.deepEqual(vlanView(eth("0/1", { pvid: 10, vlans: { untagged: [10], tagged: [] } })), { kind: "access", vid: 10, members: [10] });
  assert.deepEqual(vlanView(eth("0/1", { pvid: 1, vlans: { untagged: [1], tagged: [10, 20] } })), { kind: "trunk", vid: 1, members: [1, 10, 20] });
  assert.deepEqual(vlanView(eth("0/1", { pvid: null, vlans: { untagged: [], tagged: [] } })), { kind: "none", vid: null, members: [] });
  assert.equal(vlanView(eth("0/1", { pvid: null, vlans: { untagged: [30], tagged: [] } })).vid, 30);
  assert.equal(vlanView({ name: "0/1" }).kind, "none");
});

test("vlanColors is stable by VLAN id and repeats after the palette", () => {
  const c = vlanColors([30, 1, 10]);
  assert.equal(c.get(1), vlanColors([1]).get(1));
  assert.notEqual(c.get(1), c.get(10));
  assert.notEqual(c.get(10), c.get(30));
  const many = vlanColors(Array.from({ length: 9 }, (_, i) => i + 1));
  assert.equal(many.get(9), many.get(1));
});

test("vlanLegend counts access ports per VLAN and trunks apart", () => {
  const ports = [
    eth("0/1"),
    eth("0/2"),
    eth("0/3", { pvid: 10, vlans: { untagged: [10], tagged: [] } }),
    eth("0/11", { vlans: { untagged: [1], tagged: [10] } }),
    { ...eth("1/1"), kind: "lag" },
  ];
  const lg = vlanLegend(ports, [{ vid: 1, name: "default" }, { vid: 10, name: "servers" }]);
  assert.deepEqual(lg.vlans.map((v) => [v.vid, v.name, v.count]), [[1, "default", 2], [10, "servers", 1]]);
  assert.equal(lg.trunks, 1);
  assert.ok(lg.vlans[0].color);
});

test("status jack shows state without colour alone", () => {
  const up = jackHtml(eth("0/6", { uplink: true, rates: { util_percent: 42.4 } }), esc, "status");
  assert.ok(up.includes('class="jack up uplink"'));
  assert.ok(up.includes('data-port="0/6"'));
  assert.ok(up.includes("link up"));
  assert.ok(up.includes("--u:42%"));
  assert.ok(up.includes("↑"));
  assert.ok(up.includes("left:"));
  const blocking = jackHtml(eth("0/4", { stp_state: "blocking" }), esc, "status");
  assert.ok(blocking.includes("⏸"));
  const disabled = jackHtml(eth("0/5", { admin_up: false, oper_up: false }), esc, "status");
  assert.ok(disabled.includes("⦸"));
  const down = jackHtml(eth("0/3", { oper_up: false }), esc, "status");
  assert.ok(down.includes('class="jack down"'));
  assert.ok(down.includes("link down"));
});

test("vlan jack carries the id, the members and the colour", () => {
  const colors = vlanColors([1, 10, 20]);
  const access = jackHtml(eth("0/3", { pvid: 10, vlans: { untagged: [10], tagged: [] } }), esc, "vlan", colors);
  assert.ok(access.includes(">10<"));
  assert.ok(access.includes('data-vlans="10"'));
  assert.ok(access.includes(`--vc:${colors.get(10)}`));
  assert.ok(access.includes("VLAN 10"));
  const trunk = jackHtml(eth("0/11", { vlans: { untagged: [1], tagged: [10, 20] } }), esc, "vlan", colors);
  assert.ok(trunk.includes("trunk"));
  assert.ok(trunk.includes(">T<"));
  assert.ok(trunk.includes('data-vlans="1 10 20"'));
  assert.ok(trunk.includes("tagged 10, 20"));
});

test("combo ports also mark their SFP cage", () => {
  const html = jackHtml(eth("0/47"), esc, "status");
  assert.equal(html.match(/data-port="0\/47"/g).length, 2);
  assert.ok(html.includes('class="jack sfp up"'));
  assert.equal(jackHtml(eth("0/44"), esc, "status").match(/data-port=/g).length, 1);
});

test("jack escapes alias", () => {
  const html = jackHtml(eth("0/8", { alias: "<img onerror=x>" }), esc, "status");
  assert.ok(!html.includes("<img"));
});
