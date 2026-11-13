import { test } from "node:test";
import assert from "node:assert/strict";
import { createUiHost } from "../../src/netview/presentation/web/static/js/slots.js";
import register from "../../src/netview/plugins/builtin/lan_discovery/static/ui.js";
import { openStream } from "../../src/netview/presentation/web/static/js/api.js";
import { esc, fmtAgo } from "../../src/netview/presentation/web/static/js/util.js";

function fakeUi(summary) {
  const slots = [];
  let renders = 0;
  const ui = {
    util: { esc, fmtAgo },
    apiBase: "/api/v1/plugins/lan_discovery",
    apiGet: async () => summary.current,
    slot: (name, spec) => slots.push([name, spec]),
    requestRender: () => {
      renders++;
    },
  };
  return { ui, slots, renders: () => renders };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

test("the tile is titled Sweep coverage and asks for a re-render once its fetch resolves", async () => {
  const summary = { current: { hosts: 254, replied: 18, arp_only: 1, duration_ms: 4200, last_ms: 5 } };
  const f = fakeUi(summary);
  register(f.ui);
  await tick();
  assert.ok(f.renders() >= 1, "requestRender after the first fetch");
  const html = f.slots[0][1].render({});
  assert.ok(html.includes("Sweep coverage"));
  assert.ok(html.includes("18"));
  assert.ok(html.includes("of 254 answered"));
  assert.ok(html.includes("took 4.2 s"));
});

test("the tile before any sweep says so", async () => {
  const f = fakeUi({ current: { hosts: 0, replied: 0, duration_ms: 0, last_ms: null } });
  register(f.ui);
  await tick();
  assert.ok(f.slots[0][1].render({}).includes("no sweep yet"));
});

test("each render refetches the summary and shows the new value after it resolves", async () => {
  const summary = { current: { hosts: 10, replied: 1, duration_ms: 1000, last_ms: 1 } };
  const f = fakeUi(summary);
  register(f.ui);
  await tick();
  const before = f.renders();
  summary.current = { hosts: 10, replied: 7, duration_ms: 1000, last_ms: 2 };
  f.slots[0][1].render({}); // triggers a refetch
  await tick();
  assert.ok(f.renders() > before);
  assert.ok(f.slots[0][1].render({}).includes(">7<"));
});

test("host.requestRender calls the registered renderer and is safe without one", () => {
  const host = createUiHost();
  host.requestRender();
  let n = 0;
  host.setRenderer(() => n++);
  host.requestRender();
  assert.equal(n, 1);
});

test("openStream reports state frames", () => {
  const listeners = {};
  globalThis.EventSource = class {
    constructor() {
      this.close = () => {};
    }
    addEventListener(name, fn) {
      listeners[name] = fn;
    }
  };
  const seen = [];
  const s = openStream((e) => seen.push(e.type));
  listeners.state({ data: "{}" });
  listeners.domain({ data: "{}" });
  s.close();
  delete globalThis.EventSource;
  assert.deepEqual(seen, ["state", "domain"]);
});

import { resolvePermission } from "../../src/netview/presentation/web/static/js/slots.js";

const authWith = (...ids) => ({ user: { username: "u", displayName: "U" }, can: (id) => ids.includes(id), isAdmin: false });
const moduleUrl = (body) => "data:text/javascript," + encodeURIComponent(body);
const REGISTERING = "export default function (ui) { ui.slot('page', { id: 'p', permission: 'use' }); ui.slot('page', { id: 'open' }); globalThis.__can = [ui.can('use'), ui.can('core.scan'), ui.user.username]; }";

test("slot with permission hidden without it", async () => {
  const host = createUiHost(authWith("g-demo.view"));
  await host.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(REGISTERING) }]);
  assert.deepEqual(host.get("page").map((s) => s.id), ["open"]);
  const allowed = createUiHost(authWith("g-demo.view", "g-demo.use"));
  await allowed.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(REGISTERING) }]);
  assert.deepEqual(allowed.get("page").map((s) => s.id), ["p", "open"]);
});

test("plugin module not loaded without view", async () => {
  globalThis.__can = "untouched";
  const host = createUiHost(authWith());
  await host.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(REGISTERING) }]);
  assert.equal(globalThis.__can, "untouched");
  assert.deepEqual(host.get("page"), []);
  assert.deepEqual(host.errors, {});
});

test("uiApi.can resolves relative ids", async () => {
  const host = createUiHost(authWith("g-demo.view", "g-demo.use", "core.scan"));
  await host.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(REGISTERING) }]);
  assert.deepEqual(globalThis.__can, [true, true, "u"]);
  assert.equal(resolvePermission("demo", "use"), "demo.use");
  assert.equal(resolvePermission("demo", "core.scan"), "core.scan");
  assert.equal(resolvePermission("demo", "demo.use"), "demo.use");
});

test("slot specs carry pluginId (source id), pluginGuid and pluginDisplayName", async () => {
  const host = createUiHost(authWith("g-demo.view"));
  await host.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(REGISTERING) }]);
  const open = host.get("page").find((s) => s.id === "open");
  assert.equal(open.pluginId, "7");
  assert.equal(open.pluginGuid, "g-demo");
  assert.equal(open.pluginDisplayName, "Demo");
});

test("the view check and relative permissions use the guid, not the source id", async () => {
  const byId = createUiHost(authWith("7.view", "7.use"));
  await byId.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(REGISTERING) }]);
  assert.deepEqual(byId.get("page"), []);
  assert.equal(resolvePermission("g-demo", "use"), "g-demo.use");
});

test("the module sees pluginId and apiBase from the source id", async () => {
  const host = createUiHost(authWith("g-demo.view"));
  const body = "export default function (ui) { globalThis.__api = [ui.pluginId, ui.apiBase]; }";
  await host.loadPlugins([{ id: "7", guid: "g-demo", display_name: "Demo", state: "active", ui_module: moduleUrl(body) }]);
  assert.deepEqual(globalThis.__api, ["7", "/api/v1/plugins/7"]);
});
