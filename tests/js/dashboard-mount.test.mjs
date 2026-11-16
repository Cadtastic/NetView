import { test } from "node:test";
import assert from "node:assert/strict";
import { mountDashboard } from "../../src/netview/presentation/web/static/js/pages/dashboard.js";
import { notifyLayoutChanged, LAYOUT_EVENT } from "../../src/netview/presentation/web/static/js/dashboard/api.js";

// A minimal DOM, enough for mountDashboard and the grid.
function stubDoc() {
  const make = (tag) => {
    const e = {
      tag,
      className: "",
      textContent: "",
      innerHTML: "",
      hidden: false,
      children: [],
      attrs: {},
      parentNode: null,
      setAttribute(k, v) {
        this.attrs[k] = String(v);
      },
      getAttribute(k) {
        return k in this.attrs ? this.attrs[k] : null;
      },
      hasAttribute(k) {
        return k in this.attrs;
      },
      removeAttribute(k) {
        delete this.attrs[k];
      },
      listeners: {},
      addEventListener(t, f) {
        this.listeners[t] = f;
      },
      removeEventListener() {},
      contains(o) {
        for (let n = o; n; n = n.parentNode) if (n === this) return true;
        return false;
      },
      querySelector: () => null,
      querySelectorAll: () => [],
      get ownerDocument() {
        return doc;
      },
      classList: {
        toggle(c, on) {
          const set = new Set(e.className.split(" ").filter(Boolean));
          if (on) set.add(c);
          else set.delete(c);
          e.className = [...set].join(" ");
        },
        contains: (c) => e.className.split(" ").includes(c),
      },
      append(...kids) {
        kids.forEach((k) => this.appendChild(k));
      },
      appendChild(c) {
        return this.insertBefore(c, null);
      },
      insertBefore(c, ref) {
        if (c.parentNode) c.parentNode.children = c.parentNode.children.filter((x) => x !== c);
        c.parentNode = this;
        const at = ref ? this.children.indexOf(ref) : -1;
        if (at < 0) this.children.push(c);
        else this.children.splice(at, 0, c);
        return c;
      },
      remove() {
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((x) => x !== this);
        this.parentNode = null;
      },
    };
    return e;
  };
  const doc = { createElement: make };
  return doc;
}

const flush = () => new Promise((r) => setTimeout(r, 0));
const LAYOUT = { version: 1, order: [], hidden: [], spans: {}, group: "none" };

/** Press the toolbar button `act` the way a click on it would arrive. */
function press(el, top, act) {
  const btn = { parentNode: top, getAttribute: (n) => (n === "data-act" ? act : null), closest: (sel) => (sel === "[data-act]" ? btn : null) };
  el.listeners.click({ target: btn });
}

/** Install fake window/document/fetch; `reply` decides each GET. Returns the log and a restore function. */
function env(reply) {
  const win = new EventTarget();
  win.localStorage = { getItem: () => null, setItem() {} };
  const added = [];
  const removed = [];
  const add = win.addEventListener.bind(win);
  const remove = win.removeEventListener.bind(win);
  win.addEventListener = (t, f) => (added.push(t), add(t, f));
  win.removeEventListener = (t, f) => (removed.push(t), remove(t, f));
  const log = console.error;
  console.error = () => {}; // the stub DOM cannot draw the core cards; the grid reports that and carries on
  const saved = { window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch };
  const fetches = [];
  globalThis.window = win;
  globalThis.document = stubDoc();
  globalThis.fetch = async (url, init) => {
    fetches.push([url, init && init.method]);
    return reply(fetches.length);
  };
  return {
    win,
    added,
    removed,
    fetches,
    restore() {
      console.error = log;
      for (const [k, v] of Object.entries(saved)) {
        if (v === undefined) delete globalThis[k];
        else globalThis[k] = v;
      }
    },
  };
}

const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });
const ctxFor = (can) => ({ auth: { can }, host: { get: () => [], errors: {} }, getPlugins: () => [] });
const STATE = { devices: [], jobs: [], events: [], watches: [] };

test("the dashboard listens for layout changes while mounted and stops on destroy", async () => {
  const e = env(() => json({ layout: LAYOUT, source: "user", default: null }));
  try {
    const el = document.createElement("div");
    const view = mountDashboard(el, ctxFor(() => true));
    await flush();
    assert.deepEqual(e.added, [LAYOUT_EVENT]);
    assert.equal(e.fetches.length, 1);

    notifyLayoutChanged(); // not editing: reads the layout again
    await flush();
    assert.equal(e.fetches.length, 2);

    view.destroy();
    assert.deepEqual(e.removed, [LAYOUT_EVENT]);
    notifyLayoutChanged();
    await flush();
    assert.equal(e.fetches.length, 2);
  } finally {
    e.restore();
  }
});

test("a layout-changed event while editing does nothing", async () => {
  const e = env(() => json({ layout: LAYOUT, source: "user", default: null }));
  try {
    const el = document.createElement("div");
    const view = mountDashboard(el, ctxFor(() => true));
    await flush();
    view.update(STATE);
    const top = el.children[0];
    assert.match(top.innerHTML, /data-act="customize"/);
    press(el, top, "customize");
    assert.match(top.innerHTML, /data-act="save"/);
    assert.equal(e.fetches.length, 1);
    notifyLayoutChanged();
    await flush();
    assert.equal(e.fetches.length, 1);
    view.destroy();
  } finally {
    e.restore();
  }
});

test("a failed layout read shows the default but offers no Customize, and a later read restores it", async () => {
  let failing = true;
  const e = env(() => (failing ? json({ detail: "boom" }, 500) : json({ layout: LAYOUT, source: "user", default: null })));
  try {
    const el = document.createElement("div");
    const view = mountDashboard(el, ctxFor(() => true));
    await flush();
    view.update(STATE);
    const top = el.children[0];
    assert.doesNotMatch(top.innerHTML, /data-act="customize"/);
    press(el, top, "customize");
    assert.doesNotMatch(top.innerHTML, /data-act="save"/); // refused: nothing real to edit

    failing = false;
    notifyLayoutChanged();
    await flush();
    assert.match(top.innerHTML, /data-act="customize"/);
    view.destroy();
  } finally {
    e.restore();
  }
});

test("a pending default-edit request is ignored when the layout read failed", async () => {
  const { requestDefaultEdit } = await import("../../src/netview/presentation/web/static/js/pages/dashboard.js");
  const e = env(() => json({ detail: "boom" }, 500));
  try {
    requestDefaultEdit();
    const el = document.createElement("div");
    const view = mountDashboard(el, ctxFor(() => true));
    await flush();
    view.update(STATE);
    const top = el.children[0];
    assert.doesNotMatch(top.innerHTML, /Save as default for everyone/);
    assert.doesNotMatch(top.innerHTML, /dash-banner/);
    view.destroy();
  } finally {
    e.restore();
  }
});
