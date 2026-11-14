import { test } from "node:test";
import assert from "node:assert/strict";
import { filterMenu, menuHtml, crumbHtml, pageHeadHtml } from "../../src/netview/presentation/web/static/js/blade.js";

const MENU = [
  { items: [{ id: "general", label: "General", icon: "<i></i>" }] },
  { group: "Identity", items: [{ id: "users", label: "Users", icon: "<i></i>", count: 2 }, { id: "roles", label: "Roles", icon: "<i></i>" }] },
];

test("filterMenu keeps matching items and drops empty groups", () => {
  const menu = [{ items: [{ id: "general", label: "General" }] }, { group: "Identity", items: [{ id: "users", label: "Users" }, { id: "roles", label: "Roles" }] }];
  assert.deepEqual(filterMenu(menu, "RO"), [{ group: "Identity", items: [{ id: "roles", label: "Roles" }] }]);
});

test("filterMenu with an empty query returns everything", () => {
  assert.deepEqual(filterMenu(MENU, "  "), MENU);
});

test("menuHtml marks the active item and shows counts", () => {
  const html = menuHtml(MENU, "users", new Set());
  assert.match(html, /<button[^>]*data-blade-item="users"[^>]*class="on"[^>]*aria-current="page"|<button[^>]*data-blade-item="users"[^>]*aria-current="page"/);
  assert.equal((html.match(/aria-current="page"/g) || []).length, 1);
  assert.match(html, /<span class="blade-n">2<\/span>/);
  assert.match(html, /data-blade-group="Identity"[^>]*aria-expanded="true"/);
});

test("menuHtml renders no items for a collapsed group", () => {
  const html = menuHtml(MENU, "general", new Set(["Identity"]));
  assert.match(html, /data-blade-group="Identity"[^>]*aria-expanded="false"/);
  assert.doesNotMatch(html, /data-blade-item="users"/);
  assert.match(html, /data-blade-item="general"/);
});

test("crumbHtml links all but the last part", () => {
  assert.equal(crumbHtml(["Admin", "Users", "Edit Addam"]), '<a data-crumb="0">Admin</a> › <a data-crumb="1">Users</a> › <b>Edit Addam</b>');
});

test("crumbHtml and pageHeadHtml escape text", () => {
  assert.equal(crumbHtml(["<x>"]), "<b>&lt;x&gt;</b>");
  const html = pageHeadHtml({ title: "<x>", sub: "<y>", commands: [{ id: "a", label: "<z>", icon: "" }] });
  assert.match(html, /&lt;x&gt;/);
  assert.match(html, /&lt;y&gt;/);
  assert.match(html, /&lt;z&gt;/);
  assert.doesNotMatch(html, /<x>|<y>|<z>/);
});

test("pageHeadHtml renders commands as data-cmd buttons", () => {
  const html = pageHeadHtml({ title: "Users", sub: "People", commands: [{ id: "add", label: "Add", icon: "<svg></svg>" }] });
  assert.match(html, /<h1>Users<\/h1>/);
  assert.match(html, /class="blade-sub"/);
  assert.match(html, /<div class="blade-cmd">[\s\S]*<button[^>]*data-cmd="add"[^>]*>[\s\S]*<svg><\/svg>[\s\S]*Add/);
});

test("pageHeadHtml omits the sub line and the command bar when empty", () => {
  const html = pageHeadHtml({ title: "T" });
  assert.doesNotMatch(html, /blade-sub|blade-cmd/);
});

import { shouldCloseChild, createBlade } from "../../src/netview/presentation/web/static/js/blade.js";

test("shouldCloseChild only handles Esc while a child is open", () => {
  assert.equal(shouldCloseChild("Escape", true), true);
  assert.equal(shouldCloseChild("Escape", false), false);
  assert.equal(shouldCloseChild("Enter", true), false);
});

function stub(extra = {}) {
  const listeners = {};
  const attrs = {};
  return {
    innerHTML: "", dataset: {}, title: "", value: "",
    classList: { add() {}, remove() {}, toggle: () => false, contains: () => false },
    addEventListener: (t, f) => (listeners[t] = f),
    removeEventListener() {},
    setAttribute: (k, v) => (attrs[k] = v),
    querySelector: () => stub(),
    querySelectorAll: () => [],
    contains: () => false,
    listeners, attrs,
    ...extra,
  };
}

function fakeRoot() {
  const parts = {};
  const get = (sel) => (parts[sel] ??= stub());
  return { root: { innerHTML: "", querySelector: get }, parts };
}

test("createBlade passes push:false for the initial select and push:true for clicks", () => {
  globalThis.document = { activeElement: null };
  const { root, parts } = fakeRoot();
  const calls = [];
  createBlade(root, {
    crumbRoot: "Admin",
    menu: [{ items: [{ id: "a", label: "A" }, { id: "b", label: "B" }] }],
    onSelect: (id, _page, _api, opts) => calls.push([id, opts.push]),
  });
  assert.deepEqual(calls, [["a", false]]);
  parts[".blade-items"].listeners.click({ target: { closest: (s) => (s === "[data-blade-item]" ? { dataset: { bladeItem: "b" } } : null) } });
  assert.deepEqual(calls, [["a", false], ["b", true]]);
  delete globalThis.document;
});

test("drawMenu restores focus to the selected menu item after redraw", () => {
  const { root, parts } = fakeRoot();
  let focused = null;
  const btn = (id) => ({ dataset: { bladeItem: id }, focus: () => (focused = id), closest: () => btn(id) });
  const items = stub();
  parts[".blade-items"] = items;
  const active = { closest: (s) => (s === "[data-blade-item]" ? { dataset: { bladeItem: "b" } } : null) };
  globalThis.document = { activeElement: active };
  items.contains = (el) => el === active;
  items.querySelectorAll = (s) => (s === "[data-blade-item]" ? [btn("a"), btn("b")] : []);
  const api = createBlade(root, { crumbRoot: "Admin", menu: [{ items: [{ id: "a", label: "A" }, { id: "b", label: "B" }] }], onSelect() {} });
  focused = null;
  api.setMenu([{ items: [{ id: "a", label: "A", count: 1 }, { id: "b", label: "B", count: 2 }] }]);
  assert.equal(focused, "b");
  delete globalThis.document;
});
