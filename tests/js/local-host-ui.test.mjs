import { test } from "node:test";
import assert from "node:assert/strict";
import register, { makeHelpers } from "../../src/netview/plugins/builtin/local_host/static/ui.js";
import * as util from "../../src/netview/presentation/web/static/js/util.js";

// The plugin's UI module cannot import core modules, so it gets `ui.util` at registration; the tests hand it the same.
const h = makeHelpers(util);

const NOW = 1_800_000_000_000;
const pts = (values, step = 5000, end = NOW) => values.map((v, i) => [end - (values.length - 1 - i) * step, v]);

const conns = {
  total: 12,
  states: { ESTABLISHED: 8, LISTENING: 3, SYN_SENT: 1 },
  listening: [{ port: 22, addr: "0.0.0.0", process: "sshd" }],
  remotes: [
    { process: "chrome", remote: "142.250.1.1", port: 443, service: "HTTPS", count: 2, scope: "internet", name: "" },
    { process: "msedge", remote: "192.168.1.128", port: 443, service: "HTTPS", count: 1, scope: "lan", name: "R720 iDRAC" },
  ],
  trying: [
    { process: "msedge", remote: "192.168.1.200", port: 8080, service: "HTTP-alt", count: 1, scope: "lan", name: "" },
    { process: "msedge", remote: "192.168.1.200", port: 8443, service: "HTTPS-alt", count: 1, scope: "lan", name: "" },
  ],
  unique_remotes: 2,
  lan_conns: 1,
};

function fakeUi(snapshot) {
  const slots = [];
  const ui = {
    util,
    apiBase: "/api/v1/plugins/local_host",
    apiGet: async () => snapshot,
    slot: (name, spec) => slots.push([name, spec]),
    requestRender: () => {},
  };
  return { ui, slots };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("the connections sub-text has no middle dot", () => {
  const sub = h.connectionsSub(conns);
  assert.equal(sub, "12 TCP sockets, 2 remote hosts, 1 connections to this LAN. Refreshed every 10 s.");
  assert.ok(!sub.includes("·"));
  assert.equal(h.connectionsSub(null), "0 TCP sockets, 0 remote hosts, 0 connections to this LAN. Refreshed every 10 s.");
});

test("the Wi-Fi tile sub for a link lists the parts that exist", () => {
  assert.equal(h.wifiTile({ ssid: "Home", band: "5 GHz", channel: "36", signal_pct: 80 }).sub, "Home, 5 GHz, channel 36");
  assert.equal(h.wifiTile({ ssid: "Home", signal_pct: 80 }).sub, "Home");
  const off = h.wifiTile(null);
  assert.deepEqual([off.value, off.unit, off.sub], ["–", "", "Not on Wi-Fi"]);
  const on = h.wifiTile({ ssid: "Home", signal_pct: 80 });
  assert.deepEqual([on.value, on.unit], ["80", "%"]);
  const blank = h.wifiTile({ ssid: "", signal_pct: null });
  assert.deepEqual([blank.value, blank.sub], ["–", "Not on Wi-Fi"]);
});

test("the throughput tiles show the last rate and the Wi-Fi link speed or all adapters", () => {
  const metrics = { "local.down_bps": pts([1_000_000, 8_000_000]), "local.up_bps": pts([100_000, null]) };
  const down = h.rateTile("Download (this device)", metrics["local.down_bps"], { rx_rate_mbps: 866 }, "rx_rate_mbps");
  assert.deepEqual([down.label, down.value, down.unit, down.sub], ["Download (this device)", "8.0", "Mbit/s", "Wi-Fi link 866 Mbit/s"]);
  const up = h.rateTile("Upload (this device)", metrics["local.up_bps"], null, "tx_rate_mbps");
  assert.deepEqual([up.value, up.unit, up.sub], ["–", "", "All adapters"]);
  assert.equal(h.rateTile("Download (this device)", [], null, "rx_rate_mbps").value, "–");
  assert.equal(h.rateTile("Download (this device)", undefined, null, "rx_rate_mbps").value, "–");
});

test("the state chips are escaped", () => {
  const html = h.chipsHtml({ "<b>X</b>": 2, ESTABLISHED: 1 });
  assert.ok(!html.includes("<b>X"));
  assert.ok(html.includes("&lt;b&gt;X&lt;/b&gt;"));
  assert.ok(html.includes('<span class="chip">ESTABLISHED <b>1</b></span>'));
});

test("the established table has Process, Remote, Port and Count, and names and processes are escaped", () => {
  const html = h.tableHtml(
    { ...conns, remotes: [{ process: "<i>p</i>", remote: "1.2.3.4", port: 80, service: "HTTP", count: 3, scope: "internet", name: "<script>x</script>" }] },
    "remotes",
  );
  assert.ok(html.includes("<th>Process</th>") && html.includes("<th>Remote</th>"));
  assert.ok(html.includes('<th class="num">Port</th>') && html.includes('<th class="num">Count</th>'));
  assert.ok(!html.includes("<script>") && !html.includes("<i>p"));
  assert.ok(html.includes("&lt;script&gt;x&lt;/script&gt;"));
  assert.ok(html.includes('<span class="addr">1.2.3.4</span>'));
  assert.ok(html.includes('<span class="scope">internet</span>'));
  assert.ok(html.includes('<span class="scope">HTTP</span>'));
  assert.ok(!html.includes("·"));
});

test("the listening table has Port, Address and Process; empty tables say so", () => {
  const html = h.tableHtml(conns, "listening");
  assert.ok(html.includes('<th class="num">Port</th><th>Address</th><th>Process</th>'));
  assert.ok(html.includes("sshd"));
  assert.ok(h.tableHtml({ ...conns, listening: [] }, "listening").includes("None."));
  const trying = h.tableHtml({ ...conns, trying: [] }, "trying");
  assert.ok(trying.includes("Nothing is stuck connecting."));
  assert.ok(!trying.includes("·"));
  assert.ok(h.tableHtml({}, "remotes").includes("None."));
});

test("the tabs: three of them, and arrow keys move between them", () => {
  assert.deepEqual(h.TABS.map((t) => [t.id, t.label]), [["remotes", "Established"], ["trying", "Trying to connect"], ["listening", "Listening"]]);
  assert.equal(h.nextTab("remotes", "ArrowRight"), "trying");
  assert.equal(h.nextTab("listening", "ArrowRight"), "remotes");
  assert.equal(h.nextTab("remotes", "ArrowLeft"), "listening");
  assert.equal(h.nextTab("trying", "Home"), "remotes");
  assert.equal(h.nextTab("trying", "End"), "listening");
  assert.equal(h.nextTab("trying", "x"), null);
});

test("the report text for connections between this device and an IP", () => {
  assert.equal(
    h.connectionText("192.168.1.128", conns),
    "Between this device and 192.168.1.128: 1 open connection from msedge to port 443 (HTTPS).",
  );
  assert.equal(
    h.connectionText("192.168.1.200", conns),
    "Between this device and 192.168.1.200: still trying to reach ports 8080, 8443.",
  );
  const both = {
    remotes: [{ process: "curl", remote: "9.9.9.9", port: 22, service: "", count: 2, scope: "internet", name: "" }],
    trying: [{ process: "curl", remote: "9.9.9.9", port: 80, service: "HTTP", count: 1, scope: "internet", name: "" }],
  };
  assert.equal(
    h.connectionText("9.9.9.9", both),
    "Between this device and 9.9.9.9: 2 open connections from curl to port 22; still trying to reach port 80.",
  );
  assert.equal(h.connectionText("10.0.0.1", conns), "This device has no open connections to 10.0.0.1 right now.");
  assert.equal(h.connectionText("10.0.0.1", null), "This device has no open connections to 10.0.0.1 right now.");
});

test("the report text trims a long list of trying ports to eight", () => {
  const trying = Array.from({ length: 10 }, (_, i) => ({ process: "p", remote: "9.9.9.9", port: 1000 + i, service: "", count: 1, scope: "internet", name: "" }));
  const text = h.connectionText("9.9.9.9", { remotes: [], trying });
  assert.ok(text.endsWith("still trying to reach ports 1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007…."));
});

test("the throughput note: no traffic entry for the IP shows the fallback, an entry hides it", () => {
  assert.equal(h.hasTraffic({ traffic: [{ ip: "1.2.3.4" }] }, "1.2.3.4"), true);
  assert.equal(h.hasTraffic({ traffic: [{ ip: "1.2.3.4" }] }, "5.6.7.8"), false);
  assert.equal(h.hasTraffic({}, "5.6.7.8"), false);
  assert.equal(h.hasTraffic(null, "5.6.7.8"), false);
  assert.equal(
    h.NO_TRAFFIC_NOTE("192.168.1.9"),
    "This device can't see 192.168.1.9's own traffic. After the OPNsense cutover, its Reporting and Insight pages show per-device traffic.",
  );
  assert.equal(h.THROUGHPUT_TITLE("192.168.1.9"), "This device's throughput (all its traffic, not just to 192.168.1.9)");
});

test("the live throughput series use the last 120 local samples", () => {
  const many = pts(Array.from({ length: 300 }, (_, i) => i));
  const s = h.throughputSeries({ "local.down_bps": many, "local.up_bps": many.slice(0, 5) }, 120);
  assert.deepEqual(s.map((x) => [x.name, x.color]), [["Download", "--series-1"], ["Upload", "--series-2"]]);
  assert.equal(s[0].points.length, 120);
  assert.equal(s[0].points[119][1], 299);
  assert.equal(s[1].points.length, 5);
  assert.deepEqual(h.throughputSeries({}, 120).map((x) => x.points), [[], []]);
});

test("registration: three tiles, two cards, and the connections live section", async () => {
  const f = fakeUi({ wifi: { ssid: "Home", band: "5 GHz", channel: "36", signal_pct: 80, rx_rate_mbps: 866, tx_rate_mbps: 700 }, connections: conns, t_ms: NOW });
  register(f.ui);
  await tick();
  const by = (name) => f.slots.filter(([n]) => n === name).map(([, s]) => s);
  const tiles = by("dashboard.tile");
  assert.deepEqual(tiles.map((s) => s.order), [20, 21, 22]);
  const state = { metrics: { "local.down_bps": pts([2_000_000]), "local.up_bps": pts([500_000]) } };
  const html = tiles.map((s) => s.render(state));
  assert.ok(html[0].includes("Wi-Fi signal") && html[0].includes("Home, 5 GHz, channel 36"));
  assert.ok(html[1].includes("Download (this device)") && html[1].includes("Wi-Fi link 866 Mbit/s"));
  assert.ok(html[2].includes("Upload (this device)") && html[2].includes("Wi-Fi link 700 Mbit/s"));
  assert.ok(!html.join("").includes("·"));
  const cards = by("dashboard.card");
  assert.deepEqual(cards.map((s) => [s.title, s.order, s.span]), [["This device's throughput", 22, "third"], ["This device's connections", 40, "half"]]);
  assert.equal(cards[0].sub, "All adapters.");
  const [live] = by("report.live-section");
  assert.equal(live.id, "connections");
});

test("tiles escape what the Wi-Fi link says about itself", async () => {
  const f = fakeUi({ wifi: { ssid: "<script>alert(1)</script>", signal_pct: 50 }, connections: conns, t_ms: NOW });
  register(f.ui);
  await tick();
  const html = f.slots.filter(([n]) => n === "dashboard.tile").map(([, s]) => s.render({ metrics: {} })).join("");
  assert.ok(!html.includes("<script"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("the connections sub-text names the configured refresh interval", () => {
  assert.ok(h.connectionsSub(null, 60).endsWith("Refreshed every 60 s."));
});
