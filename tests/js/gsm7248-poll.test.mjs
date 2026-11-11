import { test } from "node:test";
import assert from "node:assert/strict";
import { pollButtonState } from "../../src/netview/plugins/builtin/gsm7248/static/page.js";

test("Poll now is enabled when nothing is polling", () => {
  assert.deepEqual(pollButtonState({ polling: false }, false), { disabled: false, label: "Poll now", title: "Poll the switch now" });
  assert.equal(pollButtonState(null, false).disabled, false); // no summary yet
});

test("Poll now is disabled while the server reports a poll running", () => {
  const b = pollButtonState({ polling: true }, false);
  assert.equal(b.disabled, true);
  assert.equal(b.label, "Polling…");
});

test("Poll now is disabled while this page's request is out", () => {
  assert.equal(pollButtonState({ polling: false }, true).disabled, true);
  assert.equal(pollButtonState(null, true).label, "Polling…");
});

test("an older server without the polling field leaves it enabled", () => {
  assert.equal(pollButtonState({ reachable: true }, false).disabled, false);
});

import { memoryText } from "../../src/netview/plugins/builtin/gsm7248/static/page.js";

test("memoryText shows free memory alone when the switch reports no total", () => {
  assert.equal(memoryText({ mem_free_kb: 61224, mem_total_kb: null }), "60 MB");
  assert.equal(memoryText({ mem_free_kb: 61224, mem_total_kb: 131072 }), "60 of 128 MB");
  assert.equal(memoryText({ mem_free_kb: null, mem_total_kb: 131072 }), null);
  assert.equal(memoryText(null), null);
});

import { loadView, managementHtml } from "../../src/netview/plugins/builtin/gsm7248/static/page.js";
import { cpuSlot, faceplateLayout, isCpuInterface } from "../../src/netview/plugins/builtin/gsm7248/static/port-grid.js";
import { esc } from "../../src/netview/presentation/web/static/js/util.js";

const cpuPort = { name: "CPU Interface:  1/3/1", kind: "other", admin_up: true, oper_up: false };

test("the CPU interface goes to the Management view, not Other interfaces", () => {
  const lag = { name: "1/1", kind: "lag", admin_up: true, oper_up: false };
  const f = faceplateLayout([cpuPort, lag]);
  assert.deepEqual(f.mgmt.map((p) => p.name), [cpuPort.name]);
  assert.deepEqual(f.extra.map((p) => p.name), ["1/1"]);
  assert.equal(isCpuInterface(cpuPort), true);
  assert.equal(isCpuInterface(lag), false);
  assert.equal(isCpuInterface({ name: "CPU Interface: 0/1", kind: "ethernet" }), false);
  assert.equal(cpuSlot(cpuPort.name), "1/3/1");
});

test("the Management view shows the address, MAC, CPU interface and status, all escaped", () => {
  const summary = {
    host: "192.168.1.4", reachable: true, last_poll_ms: Date.now(),
    switch: { mac: "00:1b:2f:c2:dc:75" }, health: { cpu_percent: 7, mem_free_kb: 61224, mem_total_kb: null },
  };
  const html = managementHtml(summary, [cpuPort], esc, () => "just now");
  for (const s of ["192.168.1.4", "00:1b:2f:c2:dc:75", "1/3/1", "✓ answering SNMP", "just now", "7 %", "60 MB"]) assert.ok(html.includes(s), s);
  assert.ok(!html.includes("link down"));
  assert.ok(managementHtml({ reachable: false }, [], esc, () => "").includes("⚠ not answering"));
  assert.ok(managementHtml(null, [], esc, () => "").includes("none reported"));
  assert.ok(managementHtml({ host: "<b>" }, [], esc, () => "").includes("&lt;b&gt;"));
});

test("the saved view falls back to Ports for anything unknown", () => {
  const store = new Map();
  globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  try {
    assert.equal(loadView(), "status");
    for (const v of ["vlan", "mgmt"]) {
      store.set("netview.gsm7248.faceView", v);
      assert.equal(loadView(), v);
    }
    store.set("netview.gsm7248.faceView", "bogus");
    assert.equal(loadView(), "status");
  } finally {
    delete globalThis.localStorage;
  }
});
