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
