import { test } from "node:test";
import assert from "node:assert/strict";
import { CORE_COLUMNS, statChips, forgetPrompt, isLocalMac } from "../../src/netview/presentation/web/static/js/pages/devices.js";
import { coreTiles } from "../../src/netview/presentation/web/static/js/pages/dashboard.js";

const col = (id) => CORE_COLUMNS.find((c) => c.id === id);
const dev = (o = {}) => ({
  key: "aa:bb:cc:00:00:01",
  ip: "192.168.1.5",
  mac: "00:1a:2b:00:00:01",
  status: "online",
  nickname: null,
  device_name: null,
  vendor: null,
  type: null,
  first_seen_ms: 1,
  last_seen_ms: 2,
  ...o,
});

test("a nickname with markup renders literally", () => {
  const html = col("nickname").td(dev({ nickname: "Café <b>" }));
  assert.ok(html.includes("Café &lt;b&gt;"));
  assert.ok(!html.includes("<b>"));
});

test("a device name with markup is escaped too", () => {
  const html = col("device_name").td(dev({ device_name: "<img src=x onerror=1>", name_source: "mdns" }));
  assert.ok(!html.includes("<img"));
});

test("an empty vendor renders blank, not unknown", () => {
  const html = col("vendor").td(dev({ vendor: null }));
  assert.ok(!/unknown/i.test(html));
  assert.equal(html, "<td></td>");
});

test("a private (locally administered) MAC with no vendor says so", () => {
  assert.equal(isLocalMac("3e:de:bc:01:02:03"), true);
  assert.equal(isLocalMac("00:1a:2b:01:02:03"), false);
  assert.equal(isLocalMac(null), false);
  assert.ok(col("vendor").td(dev({ mac: "3e:de:bc:01:02:03" })).includes("Random or local MAC"));
});

test("the vendor cell adds the TTL operating system hint under the maker", () => {
  const html = col("vendor").td(dev({ vendor: "Intel", ttl: 128, os_hint: "Windows" }));
  assert.equal(html, '<td>Intel<div class="scope">TTL 128: Windows</div></td>');
  assert.equal(col("vendor").td(dev({ vendor: "Intel", ttl: null, os_hint: "" })), "<td>Intel</td>");
});

test("IP and MAC use the addr class", () => {
  assert.ok(col("ip").td(dev()).startsWith('<td class="addr">'));
  assert.ok(col("mac").td(dev()).startsWith('<td class="addr">'));
});

test("device status cell has a still small dot and the word", () => {
  const kinds = { online: "ok", quiet: "warn", offline: "bad" };
  for (const [status, kind] of Object.entries(kinds)) {
    const html = col("status").td(dev({ status }));
    assert.ok(html.includes(`class="sdot ${kind} sm still"`), status);
    assert.ok(html.includes(`</span>${status[0].toUpperCase()}${status.slice(1)}</span>`), status);
  }
  assert.ok(col("status").td(dev({ status: "weird" })).includes('class="sdot idle sm still"'));
});

test("the actions cell has a Forget button with an escaped key, except for this device", () => {
  const html = col("actions").td(dev({ key: 'k"1', nickname: "Printer" }));
  assert.ok(html.includes("data-forget="));
  assert.ok(html.includes("Forget"));
  assert.ok(!html.includes('k"1'));
  assert.ok(!col("actions").td(dev({ is_self: true })).includes("Forget"));
});

test("statChips shows separate chips", () => {
  const html = statChips({ online: 14, quiet: 6, offline: 2 });
  assert.equal((html.match(/class="chip/g) || []).length, 3);
  assert.ok(html.includes("<b>14</b> online"));
  assert.ok(html.includes("<b>6</b> quiet"));
  assert.ok(html.includes("<b>2</b> offline"));
  assert.ok(!html.includes("·"));
});

test("forgetPrompt names the device and keeps the nickname promise", () => {
  assert.equal(
    forgetPrompt(dev({ nickname: "Printer" })),
    "Forget Printer? Its nickname is kept and comes back if the device returns.",
  );
  assert.ok(forgetPrompt(dev({ device_name: "nas" })).startsWith("Forget nas?"));
  assert.ok(forgetPrompt(dev()).startsWith("Forget 192.168.1.5?"));
});

const state = (jobs) => ({ devices: [dev(), dev({ status: "offline" })], jobs });

test("core tile is Last sweep and uses the finish time", () => {
  const now = Date.now();
  const tiles = coreTiles(
    state([{ owner: "core", name: "scan", last_run_ms: now - 60000, last_finished_ms: now - 5000, last_ok: true }]),
    now,
  );
  const t = tiles.find((x) => x.id === "sweep");
  assert.equal(t.k, "Last sweep");
  assert.equal(t.v, "5s ago");
});

test("core tile shows a dash before any sweep, and the failure text", () => {
  assert.equal(coreTiles(state([])).find((x) => x.id === "sweep").v, "–");
  const failed = coreTiles(
    state([{ owner: "core", name: "scan", last_run_ms: 1, last_finished_ms: 2, last_ok: false, last_error: "no network" }]),
    10_000,
  ).find((x) => x.id === "sweep");
  assert.equal(failed.s, "no network");
});

import { actionsCell as actionsCellFor } from "../../src/netview/presentation/web/static/js/pages/devices.js";
import { hasNoAccess } from "../../src/netview/presentation/web/static/js/pages/no-access.js";
import { watchHtml as watchHtmlFor } from "../../src/netview/presentation/web/static/js/cards/watches.js";
import { canRerun } from "../../src/netview/presentation/web/static/js/report/dialog.js";

const upDevice = { key: "k1", ip: "10.0.0.5", status: "online", watched: false };
const granting = (...ids) => ({ can: (id) => ids.includes(id) });

test("devices actions html omits forget without core.forget", () => {
  const state = { capabilities: [] };
  assert.match(actionsCellFor(upDevice, state, granting("core.forget", "core.watches")), /data-forget/);
  const html = actionsCellFor(upDevice, state, granting("core.watches"));
  assert.doesNotMatch(html, /data-forget/);
  assert.match(html, /data-watch/);
  assert.doesNotMatch(actionsCellFor(upDevice, state, granting("core.forget")), /data-watch/);
  const offline = actionsCellFor({ ...upDevice, status: "offline" }, state, granting());
  assert.doesNotMatch(offline, /data-forget/);
});

test("watch Remove and the report re-run buttons follow their permissions", () => {
  const w = { ip: "10.0.0.5", state: "up", layers: [], history: [], diagnosis: "" };
  assert.match(watchHtmlFor(w, true), /data-unwatch/);
  assert.doesNotMatch(watchHtmlFor(w, false), /data-unwatch/);
  assert.equal(canRerun(granting("core.scan")), true);
  assert.equal(canRerun(granting("core.view")), false);
});

test("a user with no permissions at all gets the no-access page", () => {
  assert.equal(hasNoAccess({ is_admin: false, permissions: [] }), true);
  assert.equal(hasNoAccess({ is_admin: false, permissions: ["core.view"] }), false);
  assert.equal(hasNoAccess({ is_admin: true, permissions: [] }), false);
});
