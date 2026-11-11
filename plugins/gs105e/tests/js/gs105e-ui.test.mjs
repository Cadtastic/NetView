import { test } from "node:test";
import assert from "node:assert/strict";
import register, { createStore, renderConnection, tileHtml } from "../../static/ui.js";
import { esc, fmtRate } from "../../../../src/netview/presentation/web/static/js/util.js";

const summary = (extra = {}) => ({
  configured: true, host: "192.168.1.5", reachable: true, polling: false, login: "ok", paused_until_ms: null,
  pause_reason: null, last_poll_ms: 1, errors: {}, switch: { name: "sw", firmware: "V1.6.0.11", firmware_tested: true },
  ports: { total: 5, up: 3 }, throughput_bps: { in: 1000, out: 2000 }, ...extra,
});

function fakeUi(responses) {
  const slots = {};
  const calls = [];
  const ui = {
    util: { esc, fmtRate },
    pluginId: "gs105e",
    apiBase: "/api/v1/plugins/gs105e",
    apiGet: async (path) => {
      calls.push(path);
      return responses[path.split("/").pop()];
    },
    apiSend: async () => ({}),
    requestRender: () => {},
    slot: (name, def) => {
      slots[name] = def;
    },
  };
  return { ui, slots, calls };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("register adds the four slots; the settings section is on the Connection tab", async () => {
  const f = fakeUi({ summary: summary(), ports: [], config: {} });
  register(f.ui);
  await tick();
  for (const n of ["dashboard.tile", "page", "report.live-section", "settings.section"]) assert.ok(f.slots[n], n);
  assert.equal(f.slots["settings.section"].tab, "Connection");
  assert.equal(f.slots["report.live-section"].id, "gs105e-summary");
  assert.equal(f.slots.page.id, "switch");
});

test("store throttles to one fetch round per 10 s unless forced", async () => {
  let t = 1000;
  const f = fakeUi({ summary: summary(), ports: [], config: {} });
  const store = createStore(f.ui, () => t);
  await store.refresh(true);
  assert.equal(f.calls.length, 3);
  t += 5000;
  await store.refresh();
  assert.equal(f.calls.length, 3);
  t += 6000;
  await store.refresh();
  assert.equal(f.calls.length, 6);
  await store.refresh(true);
  assert.equal(f.calls.length, 9);
});

test("store keeps the last data and records an error when a fetch fails", async () => {
  const f = fakeUi({ summary: summary(), ports: [], config: {} });
  const store = createStore(f.ui, () => 0);
  await store.refresh(true);
  f.ui.apiGet = async () => {
    throw new Error("boom");
  };
  await store.refresh(true);
  assert.equal(store.data.error, "boom");
  assert.equal(store.data.summary.host, "192.168.1.5");
});

test("tile: unreachable is bad with a word", () => {
  const html = tileHtml(summary({ reachable: false }), esc, fmtRate);
  assert.ok(html.includes('class="v bad"'));
  assert.ok(html.includes("Unreachable"));
  assert.ok(html.includes("⚠"));
});

test("tile: login failed is bad, paused is warn", () => {
  assert.ok(tileHtml(summary({ login: "failed" }), esc, fmtRate).includes('class="v bad"'));
  const p = tileHtml(summary({ login: "paused", paused_until_ms: 5, pause_reason: "user" }), esc, fmtRate);
  assert.ok(p.includes('class="v warn"'));
  assert.ok(p.includes("Paused"));
});

test("tile: healthy shows ports up and throughput; unconfigured and loading are plain", () => {
  const html = tileHtml(summary(), esc, fmtRate);
  assert.ok(html.includes("GS105E"));
  assert.ok(html.includes("3<small>of 5 ports up</small>"));
  assert.ok(html.includes(esc(fmtRate(1000))));
  assert.ok(tileHtml(summary({ configured: false }), esc, fmtRate).includes("Settings"));
  assert.ok(tileHtml(null, esc, fmtRate).includes("loading"));
});

test("renderConnection shows the result of Test connection", async () => {
  const handlers = {};
  const els = {
    btn: { disabled: false, addEventListener: (_, fn) => (handlers.click = fn) },
    out: { textContent: "", classList: { add() {}, remove() {} } },
  };
  const body = { innerHTML: "", querySelector: (s) => (s.includes("test") ? els.btn : els.out) };
  renderConnection(body, { apiBase: "/x", apiSend: async () => ({ ok: "true", product: "GS105Ev2", firmware: "V1", name: "sw" }), util: {} });
  await handlers.click();
  assert.ok(els.out.textContent.includes("GS105Ev2"));
  renderConnection(body, { apiBase: "/x", apiSend: async () => ({ ok: "false", error: "bad password" }), util: {} });
  await handlers.click();
  assert.ok(els.out.textContent.includes("bad password"));
});
