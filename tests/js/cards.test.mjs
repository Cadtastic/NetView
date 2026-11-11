import { test } from "node:test";
import assert from "node:assert/strict";
import { layerChips, historyStrip, statusChip, watchHtml, watchRows, addErrorText } from "../../src/netview/presentation/web/static/js/cards/watches.js";
import { eventsHtml } from "../../src/netview/presentation/web/static/js/cards/events.js";
import { CORE_COLUMNS, actionsCell, isIpv4 } from "../../src/netview/presentation/web/static/js/pages/devices.js";

const watch = (o = {}) => ({
  ip: "192.168.1.128",
  label: "R720 iDRAC",
  ports: [443, 22],
  state: "degraded",
  since_ms: null,
  l2: true,
  mac: "aa:bb:cc:00:00:01",
  rtt_ms: 2.14,
  port_state: { 443: "open", 22: "filtered" },
  diagnosis: "Reachable, but port 22 gives no answer.",
  history: [1, 1, 0.5, 0],
  ...o,
});

test("layer chips: ARP, ping and each port", () => {
  const html = layerChips(watch());
  assert.ok(html.includes("✓ ARP aa:bb:cc:00:00:01"));
  assert.ok(html.includes("✓ Ping 2.1 ms"));
  assert.ok(html.includes("✓ TCP 443 open"));
  assert.ok(html.includes("✕ TCP 22 no answer"));
  assert.ok(layerChips(watch({ port_state: { 22: "closed" } })).includes("✕ TCP 22 refused"));
});

test("a routed host has no ARP layer, and a missing ping reads as failed", () => {
  const html = layerChips(watch({ l2: null, mac: null, rtt_ms: null, port_state: {} }));
  assert.ok(html.includes("n/a (routed)"));
  assert.ok(html.includes("✕ Ping<"));
  assert.ok(layerChips(watch({ l2: false, mac: null })).includes("✕ ARP<"));
});

test("a watch that has not been checked yet shows neutral chips, not failures", () => {
  const html = layerChips(watch({ state: "pending", l2: null, mac: null, rtt_ms: null, port_state: {} }));
  assert.ok(!html.includes("✕"));
  assert.ok(!html.includes("bad"));
  assert.ok(html.includes("… TCP 443"));
});

test("status dots carry the plan labels and kinds", () => {
  const plan = {
    up: ["Up", "ok"], degraded: ["Partly up", "warn"], present: ["On the network only", "warn"],
    absent: ["Not on the network", "bad"], down: ["No reply", "bad"], pending: ["Checking", "off"],
  };
  for (const [state, [label, kind]] of Object.entries(plan)) {
    const html = statusChip(state);
    assert.ok(html.includes(`aria-label="${label}"`), state);
    assert.ok(html.includes(`class="sdot ${kind}"`), state);
  }
});

test("the history strip maps 1, 0.5 and anything else", () => {
  const html = historyStrip([1, 0.5, 0]);
  assert.ok(html.includes('class="u"'));
  assert.ok(html.includes('class="d"'));
  assert.ok(html.includes('class="x"'));
  assert.ok(html.includes("Last 3 checks"));
});

test("a watch with markup in its label and diagnosis renders literally", () => {
  const html = watchHtml(watch({ label: "<img src=x onerror=1>", diagnosis: "<script>1</script>" }));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("·"));
  assert.ok(html.includes('data-unwatch="192.168.1.128"'));
});

test("a watch with no status yet reads as Checking", () => {
  const rows = watchRows({ watch_status: [], watches: [{ ip: "10.0.0.9", ports: [], label: "" }] });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].state, "pending");
  assert.equal(watchRows({ watch_status: [watch()], watches: [{ ip: "192.168.1.128", ports: [], label: "" }] }).length, 1);
  assert.deepEqual(watchRows({}), []);
});

test("adding a watch: a 422 explains the format", () => {
  assert.equal(addErrorText({ status: 422, message: "bad ip" }), "Couldn't add that: bad ip. Format: IP[:port,port][=label]");
  assert.equal(addErrorText({ status: 500, message: "boom" }), "boom");
});

test("events are newest first with a kind chip, and markup is escaped", () => {
  const html = eventsHtml([
    { kind: "new", text: "first", t_ms: 1000 },
    { kind: "offline", text: "<b>later</b>", t_ms: 2000 },
  ]);
  assert.ok(html.indexOf("&lt;b&gt;later") < html.indexOf("first"));
  assert.ok(!html.includes("<b>"));
  assert.ok(html.includes(">Offline<"));
  assert.ok(eventsHtml([]).includes("Nothing yet. Events start after the first sweep."));
});

test("Inspect becomes View report once inspected, and is disabled without the plugin", () => {
  const d = { ip: "192.168.1.5", key: "k", watched: false };
  const on = actionsCell(d, { capabilities: ["inspection"], inspected: { "192.168.1.5": 5 } });
  assert.ok(on.includes("View report"));
  assert.ok(on.includes('data-inspect="192.168.1.5"'));
  assert.ok(on.includes('data-watch="192.168.1.5"'));
  assert.ok(!on.includes("disabled"));
  assert.ok(actionsCell(d, { capabilities: ["inspection"], inspected: {} }).includes(">Inspect<"));
  const off = actionsCell(d, { capabilities: [], inspected: {} });
  assert.ok(off.includes('disabled title="No inspection plugin is turned on"'));
});

test("a watched device has no Watch button, and this device cannot be forgotten or watched", () => {
  const state = { capabilities: ["inspection"], inspected: {} };
  assert.ok(!actionsCell({ ip: "1.1.1.1", key: "k", watched: true }, state).includes("data-watch"));
  const self = actionsCell({ ip: "1.1.1.2", key: "self", is_self: true }, state);
  assert.ok(self.includes("data-inspect"));
  assert.ok(!self.includes("data-forget"));
  assert.ok(!self.includes("data-watch"));
});

test("offline and quiet devices only offer Forget, styled as a danger button", () => {
  const state = { capabilities: ["inspection"], inspected: { "1.1.1.3": 5 } };
  for (const status of ["offline", "quiet"]) {
    const html = actionsCell({ ip: "1.1.1.3", key: "k3", status, watched: false }, state);
    assert.ok(html.includes('class="small danger" data-forget="k3"'));
    assert.ok(!html.includes("data-inspect"));
    assert.ok(!html.includes("data-watch"));
  }
  const online = actionsCell({ ip: "1.1.1.3", key: "k3", status: "online", watched: false }, state);
  assert.ok(online.includes("data-inspect") && online.includes("data-watch") && online.includes("small danger"));
});

test("isIpv4", () => {
  assert.equal(isIpv4("192.168.1.125"), true);
  assert.equal(isIpv4(" 10.0.0.1 "), true);
  for (const bad of ["192.168.1", "256.1.1.1", "a.b.c.d", "1.2.3.4.5", "", "1.2.3.-4"]) assert.equal(isIpv4(bad), false, bad);
});

test("the type cell adds a guess line only for vendor-derived types", () => {
  const type = CORE_COLUMNS.find((c) => c.id === "type");
  assert.ok(type.td({ type: "Printer", type_source: "vendor" }).includes("guess from maker"));
  assert.ok(!type.td({ type: "Printer", type_source: "inspection" }).includes("guess from maker"));
  assert.ok(!type.td({ type: "This device", type_source: "vendor", is_self: true }).includes("guess from maker"));
});
