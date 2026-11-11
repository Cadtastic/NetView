import { test } from "node:test";
import assert from "node:assert/strict";
import register, { makeHelpers, uploadedWhileIdle } from "../../src/netview/plugins/builtin/starlink/static/ui.js";
import * as util from "../../src/netview/presentation/web/static/js/util.js";

// The plugin's UI module cannot import core modules, so it gets `ui.util` at registration; the tests hand it the same.
const h = makeHelpers(util);

const NOW = 1_800_000_000_000;
const pts = (values, step = 5000, end = NOW) => values.map((v, i) => [end - (values.length - 1 - i) * step, v]);

const entry = (ip, over = {}) => ({
  ip,
  source: "starlink",
  down_bps: 2_000_000,
  up_bps: 500_000,
  down_avg_bps: 1_500_000,
  up_avg_bps: 400_000,
  down_total: 5_000_000,
  up_total: 300_000,
  seen_ms: NOW,
  extra: { name: "Living room TV", signal_dbm: -52.5, down_link: 866, up_link: 433, assoc_s: 7200, role: "client", ap: "Kitchen" },
  ...over,
});
const job = (over = {}) => ({ owner: "starlink", name: "poll.traffic", last_ok: true, last_error: null, ...over });
const dev = (ip, over = {}) => ({ key: `k${ip}`, ip, is_self: false, display_name: "", type: "", device_name: "", nickname: null, ...over });

function state(over = {}) {
  return {
    jobs: [job()],
    traffic: [entry("192.0.2.20")],
    traffic_totals: [{ source: "starlink", clients: 2, down_bps: 12_300_000, up_bps: 800_000, t_ms: NOW }],
    devices: [dev("192.0.2.20", { display_name: "Living room TV" })],
    metrics: {},
    ...over,
  };
}

// ---- uploadedWhileIdle (LD 978-982)

test("uploadedWhileIdle counts upload only in steps where download is under 50 000 bps and the step is under 30 s", () => {
  assert.deepEqual(uploadedWhileIdle([0, 5000, 10000], [0, 10000, 10000], [0, 80000, 80000]), { bytes: 100000, seconds: 10 });
});

test("uploadedWhileIdle skips busy steps, long gaps, missing samples and a series that is too short", () => {
  assert.deepEqual(uploadedWhileIdle([0, 5000], [0, 60000], [0, 80000]), { bytes: 0, seconds: 0 });
  assert.deepEqual(uploadedWhileIdle([0, 5000], [0, 50000], [0, 80000]), { bytes: 0, seconds: 0 }, "50 000 is not below 50 000");
  assert.deepEqual(uploadedWhileIdle([0, 30000], [0, 0], [0, 80000]), { bytes: 0, seconds: 0 }, "30 s is not under 30 s");
  assert.deepEqual(uploadedWhileIdle([0, 5000, 10000], [0, null, 0], [0, 80000, null]), { bytes: 0, seconds: 0 });
  assert.deepEqual(uploadedWhileIdle([0], [0], [0]), { bytes: 0, seconds: 0 });
  assert.deepEqual(uploadedWhileIdle([], [], []), { bytes: 0, seconds: 0 });
});

// ---- tiles

test("the all-devices tile shows download / upload in Mbit/s and the client count", () => {
  const t = h.allTile(state());
  assert.equal(t.label, "All Wi-Fi devices");
  assert.equal(t.value, "12 / 0.80");
  assert.equal(t.unit, "Mbit/s");
  assert.equal(t.sub, "2 clients, from the Starlink router");
  assert.equal(h.allTile(state({ traffic_totals: [{ source: "starlink", clients: 1, down_bps: 0, up_bps: 0, t_ms: NOW }] })).sub, "1 client, from the Starlink router");
});

test("the top uploader is the non-self device with the highest 10 minute upload average", () => {
  const s = state({
    traffic: [
      entry("192.0.2.20", { up_avg_bps: 400_000 }),
      entry("192.0.2.21", { up_avg_bps: 900_000 }),
      entry("192.0.2.22", { up_avg_bps: 5_000_000 }),
      entry("192.0.2.23", { up_avg_bps: null }),
    ],
    devices: [dev("192.0.2.20"), dev("192.0.2.21", { display_name: "Hall camera" }), dev("192.0.2.22", { is_self: true, display_name: "This device" })],
  });
  const t = h.topTile(s);
  assert.equal(t.label, "Top uploader (10 min average)");
  assert.equal(t.value, "900.0");
  assert.equal(t.unit, "kbit/s");
  assert.equal(t.sub, "Hall camera");
});

test("the top uploader falls back to the router's name, then the address, and shows a dash with no clients", () => {
  assert.equal(h.topTile(state({ devices: [] })).sub, "Living room TV");
  assert.equal(h.topTile(state({ devices: [], traffic: [entry("192.0.2.20", { extra: {} })] })).sub, "192.0.2.20");
  const none = h.topTile(state({ traffic: [] }));
  assert.equal(none.value, "–");
});

test("a failing job gives one Router traffic tile with the error, and no other tile", () => {
  const s = state({ jobs: [job({ last_ok: false, last_error: "OSError: router API refused: HTTP 404" })] });
  assert.equal(h.allTile(s).label, "Router traffic");
  assert.equal(h.allTile(s).value, "–");
  assert.equal(h.allTile(s).sub, "Unavailable: router API refused: HTTP 404");
  assert.equal(h.topTile(s), null);
  assert.equal(h.tileHtml(null), "");
});

test("before the first run, or with no job, no tile is shown", () => {
  for (const jobs of [[], [job({ last_ok: null })], [{ owner: "other", name: "poll.traffic", last_ok: true }]]) {
    assert.equal(h.allTile(state({ jobs })), null);
    assert.equal(h.topTile(state({ jobs })), null);
  }
});

test("tile text from the router is escaped", () => {
  const s = state({ jobs: [job({ last_ok: false, last_error: "<script>x</script>" })] });
  const html = h.tileHtml(h.allTile(s));
  assert.ok(!html.includes("<script"));
  assert.ok(html.includes("&lt;script&gt;"));
  const top = h.tileHtml(h.topTile(state({ devices: [], traffic: [entry("192.0.2.20", { extra: { name: "<img src=x onerror=1>" } })] })));
  assert.ok(!top.includes("<img"));
});

// ---- the Traffic column (LD 660-666)

test("the traffic cell shows download, upload with a sparkline, and the bytes sent", () => {
  const s = state({ metrics: { "traffic.up.192.0.2.20": pts([1000, 2000, null, 3000]) } });
  const cell = h.trafficCell(dev("192.0.2.20"), s);
  assert.ok(cell.includes("↓ 2.0 Mbit/s"));
  assert.ok(cell.includes("↑ 500.0 kbit/s"));
  assert.ok(cell.includes("<svg"));
  assert.ok(cell.includes("--series-2") || cell.includes("var("), "the sparkline uses the second series colour");
  assert.ok(cell.includes("sent 300 KB since connecting"));
  assert.ok(!cell.includes("·"));
});

test("a device with no traffic entry reads not a Wi-Fi client while the job is ok, and router data unavailable while it fails", () => {
  const ok = h.trafficCell(dev("192.0.2.99"), state());
  assert.ok(ok.includes("not a Wi-Fi client of the router"));
  const failing = h.trafficCell(dev("192.0.2.99"), state({ jobs: [job({ last_ok: false, last_error: "x" })] }));
  assert.ok(failing.includes("router data unavailable"));
  assert.ok(!failing.includes("not a Wi-Fi client"));
  const none = h.trafficCell(dev("192.0.2.99"), state({ jobs: [] }));
  assert.ok(none.includes("router data unavailable"));
});

test("the traffic column sorts by the upload average, highest first, and devices without traffic last", () => {
  const s = state({ traffic: [entry("192.0.2.20", { up_avg_bps: 400_000 }), entry("192.0.2.21", { up_avg_bps: 900_000 })] });
  const keys = ["192.0.2.20", "192.0.2.21", "192.0.2.99"].map((ip) => h.trafficSortKey(dev(ip), s));
  const order = ["192.0.2.20", "192.0.2.21", "192.0.2.99"].sort((a, b) => keys[["192.0.2.20", "192.0.2.21", "192.0.2.99"].indexOf(a)] - keys[["192.0.2.20", "192.0.2.21", "192.0.2.99"].indexOf(b)]);
  assert.deepEqual(order, ["192.0.2.21", "192.0.2.20", "192.0.2.99"]);
});

// ---- the report's live section (LD 975-999)

const history = () => ({
  "traffic.down.192.0.2.20": pts([0, 10000, 10000]),
  "traffic.up.192.0.2.20": pts([0, 80000, 80000]),
});

test("the live section has the seven tiles in order", () => {
  const m = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: state({ metrics: history() }) });
  assert.deepEqual(
    m.tiles.map((t) => t.k),
    ["Upload now", "Download now", "Upload 10 min average", "Uploaded while idle", "Sent since connecting", "Received since connecting", "Wi-Fi signal"],
  );
  const by = Object.fromEntries(m.tiles.map((t) => [t.k, t]));
  assert.deepEqual([by["Upload now"].v, by["Upload now"].u], ["500.0", "kbit/s"]);
  assert.deepEqual([by["Download now"].v, by["Download now"].u], ["2.0", "Mbit/s"]);
  assert.deepEqual([by["Uploaded while idle"].v, by["Uploaded while idle"].u], ["100 KB", "in 10 s"]);
  assert.equal(by["Sent since connecting"].v, "300 KB");
  assert.equal(by["Received since connecting"].v, "5.0 MB");
  assert.deepEqual([by["Wi-Fi signal"].v, by["Wi-Fi signal"].u], ["-52.5", "dBm"]);
});

test("uploaded while idle shows a dash without idle samples, and minutes from a minute up", () => {
  const none = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: state() });
  const idle = none.tiles.find((t) => t.k === "Uploaded while idle");
  assert.deepEqual([idle.v, idle.u], ["–", ""]);
  const long = {
    "traffic.down.192.0.2.20": pts(new Array(20).fill(0), 10000),
    "traffic.up.192.0.2.20": pts(new Array(20).fill(8000), 10000),
  };
  const m = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: state({ metrics: long }) });
  assert.equal(m.tiles.find((t) => t.k === "Uploaded while idle").u, "in 3 min");
});

test("the chart is the device's own traffic, with download in series 1 and upload in series 2", () => {
  const m = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: state({ metrics: history() }) });
  assert.equal(m.chartTitle, "192.0.2.20's own traffic, from the router's counters, last 10 min");
  assert.deepEqual(m.series.map((s) => [s.name, s.color]), [["Download", "--series-1"], ["Upload", "--series-2"]]);
  assert.equal(m.series[0].points.length, 3);
});

test("the link line names the role, access point and time, and leaves out what is missing", () => {
  assert.equal(
    h.linkLine({ role: "client", ap: "Kitchen", assoc_s: 7200, down_link: 866, up_link: 433 }),
    "Connected as a client to access point Kitchen for 2 h. Link rates 866 Mbit/s down and 433 Mbit/s up, as the router reports them.",
  );
  assert.equal(h.linkLine({ role: "mesh node", assoc_s: 90 }), "Connected as a mesh node for 2 min.");
  assert.equal(h.linkLine({ ap: "Hall" }), "Connected to access point Hall.");
  assert.equal(h.linkLine({ down_link: 100 }), "Link rate 100 Mbit/s down, as the router reports it.");
  assert.equal(h.linkLine({}), "");
  assert.equal(h.linkLine(undefined), "");
  assert.ok(!h.linkLine({ role: "client", ap: "Kitchen", assoc_s: 7200, down_link: 866, up_link: 433 }).includes("·"));
});

test("the ACR note shows for a TV by type, device name, nickname or router name, and not otherwise", () => {
  const e = entry("192.0.2.20", { extra: { name: "Kitchen" } });
  assert.equal(h.isTv(dev("192.0.2.20", { type: "Smart TV" }), e), true);
  assert.equal(h.isTv(dev("192.0.2.20", { device_name: "Roku Ultra" }), e), true);
  assert.equal(h.isTv(dev("192.0.2.20", { nickname: "Television" }), e), true);
  assert.equal(h.isTv(dev("192.0.2.20"), entry("192.0.2.20", { extra: { name: "Living room TV" } })), true);
  assert.equal(h.isTv(dev("192.0.2.20", { type: "Printer" }), e), false);
  assert.equal(h.isTv(dev("192.0.2.20", { type: "Settv" }), e), false, "tv must be a whole word");
  assert.equal(h.isTv(null, e), false);
  const m = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20", { type: "Smart TV" }), state: state() });
  assert.ok(m.acr.startsWith("Smart TVs and ACR: "));
  assert.ok(m.acr.includes("Settings → Privacy → Smart TV experience → Use info from TV inputs"));
  assert.equal(h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: state({ traffic: [entry("192.0.2.20", { extra: {} })] }) }).acr, "");
});

test("the footer says the figures come from the router's counters", () => {
  const m = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: state() });
  assert.equal(
    m.footer,
    "Traffic figures come from the Starlink router's counters for 192.0.2.20: they show how much it sends, not where. Seeing which servers it talks to (an ACR service, for example) needs the router's DNS and flow logs, which OPNsense provides after the cutover.",
  );
});

test("a device with no traffic entry has no live section", () => {
  assert.equal(h.liveModel({ ip: "192.0.2.99", device: dev("192.0.2.99"), state: state() }), null);
  assert.equal(h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20"), state: { jobs: [], traffic: [], metrics: {} } }), null);
});

test("no user-visible string has a middle dot", () => {
  const m = h.liveModel({ ip: "192.0.2.20", device: dev("192.0.2.20", { type: "Smart TV" }), state: state({ metrics: history() }) });
  const all = JSON.stringify([m, h.allTile(state()), h.topTile(state()), h.trafficCell(dev("192.0.2.20"), state())]);
  assert.ok(!all.includes("·"));
});

// ---- registration

function fakeUi() {
  const slots = [];
  const ui = { util, apiBase: "/api/v1/plugins/starlink", apiGet: async () => ({}), slot: (name, spec) => slots.push([name, spec]), requestRender: () => {} };
  return { ui, slots };
}

test("registration: two tiles at 30 and 31, the traffic column and the traffic live section", () => {
  const f = fakeUi();
  register(f.ui);
  const by = (name) => f.slots.filter(([n]) => n === name).map(([, s]) => s);
  const tiles = by("dashboard.tile");
  assert.deepEqual(tiles.map((s) => s.order), [30, 31]);
  assert.ok(tiles[0].render(state()).includes("All Wi-Fi devices"));
  assert.ok(tiles[1].render(state()).includes("Top uploader (10 min average)"));
  const failing = state({ jobs: [job({ last_ok: false, last_error: "OSError: boom" })] });
  assert.ok(tiles[0].render(failing).includes("Unavailable: boom"));
  assert.equal(tiles[1].render(failing), "");
  const [col] = by("devices.column");
  assert.deepEqual([col.id, col.label, col.sub], ["traffic", "Traffic", "(from router)"]);
  assert.ok(col.render(dev("192.0.2.20"), state()).includes("↓ 2.0 Mbit/s"));
  assert.equal(typeof col.sortKey, "function");
  const [live] = by("report.live-section");
  assert.equal(live.id, "traffic");
});

test("a broken state does not throw out of the tiles or the column", () => {
  const f = fakeUi();
  register(f.ui);
  const col = f.slots.find(([n]) => n === "devices.column")[1];
  for (const bad of [{}, { jobs: null, traffic: null, metrics: null }]) {
    assert.doesNotThrow(() => col.render(dev("192.0.2.20"), bad));
    assert.doesNotThrow(() => col.sortKey(dev("192.0.2.20"), bad));
    for (const [n, spec] of f.slots) if (n === "dashboard.tile") assert.doesNotThrow(() => spec.render(bad));
  }
});
