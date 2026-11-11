import { test } from "node:test";
import assert from "node:assert/strict";
import { portChartSeries } from "../../static/port-grid.js";
import { drawReport, reportModel } from "../../static/report.js";

const samples = [
  { if_index: 5, t_ms: 1000, in_bps: 10, out_bps: 100 },
  { if_index: 5, t_ms: 2000, in_bps: 20, out_bps: null },
];
const dev = (mac) => ({ mac, display_name: "x", ip: "192.168.1.9" });
const detail = (devices, extra = {}) => ({
  name: "0/5", oper_up: true, speed_mbps: 1000, duplex: "full", pvid: 10,
  vlans: { untagged: [10], tagged: [] }, rates: { in_bps: 11, out_bps: 222 },
  devices, mac_history: [{ mac: "aa:aa", vlan: 10, first_ms: 500, last_ms: 900 }], ...extra,
});
const opts = { ip: "192.168.1.9", mac: "AA:AA", fmtAgo: (ms) => `ago${ms}` };
const direct = { port: "0/5", via: false };
const tile = (m, k) => (m.tiles.find((t) => t.k === k) || {}).v;

test("portChartSeries keeps In then Out", () => {
  const s = portChartSeries(samples);
  assert.deepEqual(s.map((x) => [x.name, x.color]), [["In", "--series-1"], ["Out", "--series-2"]]);
  assert.deepEqual(s[0].points, [[1000, 10], [2000, 20]]);
  assert.deepEqual(s[1].points, [[1000, 100], [2000, null]]);
  assert.deepEqual(portChartSeries(null).map((x) => x.points), [[], []]);
});

test("reportModel: null without an attachment", () => {
  assert.equal(reportModel(null, detail([]), samples, opts), null);
});

test("reportModel: uplink gives only the note", () => {
  const m = reportModel({ port: "0/11", via: true }, null, null, opts);
  assert.equal(m.heading, "Switch port");
  assert.deepEqual(m.tiles, []);
  assert.equal(m.series, null);
  assert.equal(m.note, "Seen by the GSM7248 through uplink port 0/11; the device is on another switch or access point.");
});

test("reportModel: single-device port charts Download from out_bps then Upload from in_bps", () => {
  const m = reportModel(direct, detail([dev("aa:aa")]), samples, opts);
  assert.equal(tile(m, "Port"), "0/5");
  assert.equal(tile(m, "VLAN"), "10");
  assert.equal(tile(m, "Link"), "1G full");
  assert.equal(tile(m, "Download now"), "222");
  assert.equal(tile(m, "Upload now"), "11");
  assert.equal(tile(m, "First seen here"), "ago500");
  assert.deepEqual(m.series.map((s) => [s.name, s.color]), [["Download", "--series-1"], ["Upload", "--series-2"]]);
  assert.deepEqual(m.series[0].points, [[1000, 100], [2000, null]]);
  assert.deepEqual(m.series[1].points, [[1000, 10], [2000, 20]]);
  assert.equal(m.chartTitle, "192.168.1.9's traffic on switch port 0/5, last hour");
});

test("reportModel: link down", () => {
  const m = reportModel(direct, detail([dev("aa:aa")], { oper_up: false }), samples, opts);
  assert.equal(tile(m, "Link"), "link down");
});

test("reportModel: shared port has no series and says shared by 3 devices", () => {
  const m = reportModel(direct, detail([dev("aa:aa"), dev("b"), dev("c")]), samples, opts);
  assert.equal(m.series, null);
  assert.equal(m.note, "Port 0/5 is shared by 3 devices, so its traffic is not this device's alone.");
});

test("reportModel: loading detail shows dashes", () => {
  const m = reportModel(direct, null, null, opts);
  assert.equal(tile(m, "Port"), "0/5");
  for (const k of ["VLAN", "Link", "Download now", "Upload now", "First seen here"]) assert.equal(tile(m, k), "–");
  assert.equal(m.series, null);
});

// minimal DOM shim for drawReport
function makeDoc() {
  const node = (tag) => {
    const n = {
      tagName: tag.toUpperCase(), children: [], className: "", dataset: {}, hidden: false, style: {}, _text: "",
      append(...k) { for (const c of k) { c.parentNode = n; n.children.push(c); } },
      get textContent() { return n._text + n.children.map((c) => c.textContent).join(""); },
      set textContent(v) { n.children = []; n._text = String(v); },
    };
    return n;
  };
  return { createElement: node, createTextNode: (t) => { const n = node("#text"); n._text = t; return n; } };
}
const all = (n) => [n, ...n.children.flatMap(all)];

test("drawReport escapes a hostile port name", () => {
  globalThis.document = makeDoc();
  const box = document.createElement("div");
  const hostile = "<img src=x onerror=1>";
  const m = reportModel({ port: hostile, via: true }, null, null, opts);
  drawReport(box, m, () => {}, String);
  assert.ok(box.textContent.includes(hostile));
  assert.ok(!all(box).some((n) => n.tagName === "IMG"));
  drawReport(box, null, () => {}, String);
  assert.equal(box.children.length, 0);
  delete globalThis.document;
});

test("reportModel: one MAC on two VLANs is one device and charts", () => {
  const m = reportModel(direct, detail([dev("aa:aa"), dev("AA:AA")]), samples, opts);
  assert.equal(m.note, "");
  assert.ok(m.series);
});

test("reportModel: shared note counts distinct MACs", () => {
  const m = reportModel(direct, detail([dev("aa:aa"), dev("aa:aa"), dev("b")]), samples, opts);
  assert.equal(m.series, null);
  assert.ok(m.note.includes("shared by 2 devices"));
});

test("reportModel: a port whose only device is another MAC is stale, so dashes and no series", () => {
  const m = reportModel(direct, detail([dev("bb:bb")]), samples, opts);
  assert.equal(m.series, null);
  assert.equal(m.note, "");
  assert.equal(tile(m, "Link"), "–");
  assert.equal(tile(m, "Download now"), "–");
});
