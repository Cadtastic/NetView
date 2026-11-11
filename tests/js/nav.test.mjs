import { test } from "node:test";
import assert from "node:assert/strict";
import { navHtml, navItems, needsSetup, pickRoute } from "../../src/netview/presentation/web/static/js/nav.js";
import { resolveTab, tabsFor } from "../../src/netview/presentation/web/static/js/settings/dialog.js";

const ROUTES = [
  { path: "/", label: "Dashboard" },
  { path: "/devices", label: "Devices" },
  { path: "/p/gsm7248/switch", label: "Switch", pluginId: "gsm7248" },
];
const plugin = (o = {}) => ({ id: "gsm7248", name: "GSM7248", enabled: true, state: "active", configured: true, ...o });

test("needsSetup: only an enabled, active plugin with configured false", () => {
  assert.equal(needsSetup(plugin({ configured: false })), true);
  assert.equal(needsSetup(plugin()), false);
  assert.equal(needsSetup(plugin({ configured: false, enabled: false })), false);
  assert.equal(needsSetup(plugin({ configured: false, state: "failed" })), false);
  assert.equal(needsSetup(plugin({ configured: undefined })), false); // an older server without the field
  assert.equal(needsSetup(null), false);
});

test("navItems disables the page of a plugin that needs configuring, with a hint", () => {
  const items = navItems(ROUTES, [plugin({ configured: false })], "/p/gsm7248/switch");
  const sw = items[2];
  assert.equal(sw.disabled, true);
  assert.equal(sw.on, false);
  assert.match(sw.title, /GSM7248 needs configuring in Settings/);
  assert.deepEqual(items.slice(0, 2).map((i) => i.disabled), [false, false]);
});

test("navItems enables it once the plugin is configured", () => {
  const items = navItems(ROUTES, [plugin()], "/p/gsm7248/switch");
  assert.equal(items[2].disabled, false);
  assert.equal(items[2].on, true);
  assert.equal(items[2].title, "");
});

test("pickRoute falls back to the first route for a disabled or unknown path", () => {
  const off = navItems(ROUTES, [plugin({ configured: false })], "/");
  assert.equal(pickRoute(off, "/p/gsm7248/switch").path, "/");
  assert.equal(pickRoute(off, "/nope").path, "/");
  assert.equal(pickRoute(off, "/devices").path, "/devices");
  const on = navItems(ROUTES, [plugin()], "/");
  assert.equal(pickRoute(on, "/p/gsm7248/switch").path, "/p/gsm7248/switch");
});

test("navHtml: a disabled tab has no href, is aria-disabled and opens the plugin's settings", () => {
  const html = navHtml(navItems(ROUTES, [plugin({ configured: false })], "/"));
  assert.match(html, /<a href="#\/" class="on" aria-current="page">Dashboard<\/a>/);
  const sw = html.slice(html.indexOf('data-setup="gsm7248"') - 60);
  assert.ok(!/href=[^>]*>Switch/.test(sw));
  assert.match(html, /aria-disabled="true"[^>]*class="off" data-setup="gsm7248" title="GSM7248 needs configuring in Settings[^"]*">Switch/);
});

test("needs-setup nav item carries an amber dot", () => {
  const html = navHtml(navItems(ROUTES, [plugin({ configured: false })], "/"));
  assert.match(html, /Switch<span class="sdot warn sm" role="img" aria-label="Needs configuring"/);
  assert.ok(!navHtml(navItems(ROUTES, [plugin()], "/")).includes("sdot"));
});

test("navHtml escapes labels and hints", () => {
  const html = navHtml(navItems([{ path: "/p/x/y", label: "<b>", pluginId: "x" }], [plugin({ id: "x", name: "<i>", configured: false })], "/"));
  assert.ok(!html.includes("<b>"));
  assert.ok(!html.includes("<i>"));
});

test("tabsFor groups Installed and Available under Plugins", () => {
  const tabs = tabsFor([plugin({ configured: false }), plugin({ id: "ok", name: "OK" })], 3);
  assert.deepEqual(tabs.map((t) => [t.id, t.parent || null]), [
    ["appearance", null],
    ["plugins", null],
    ["plugins:installed", "plugins"],
    ["plugins:available", "plugins"],
  ]);
  assert.equal(tabs[2].count, 2);
  assert.equal(tabs[2].dot, "warn");
  assert.equal(tabs[3].count, 3);
  assert.ok(!tabs.some((t) => t.id.startsWith("plugin:")));
});

test("resolveTab maps plugins, plugin:<id> and unknown ids", () => {
  assert.deepEqual(resolveTab("plugins"), { tab: "plugins:installed", overlay: null });
  assert.deepEqual(resolveTab("plugin:gsm7248"), { tab: "plugins:installed", overlay: "gsm7248" });
  assert.deepEqual(resolveTab("plugin:nope"), { tab: "plugins:installed", overlay: "nope" });
  assert.deepEqual(resolveTab("plugins:available"), { tab: "plugins:available", overlay: null });
  assert.deepEqual(resolveTab("appearance"), { tab: "appearance", overlay: null });
  assert.deepEqual(resolveTab("bogus"), { tab: "appearance", overlay: null });
});

test("pending plugins never disable or add nav items", () => {
  const pending = plugin({ id: "fresh", name: "Fresh", state: "pending", configured: true, source: "folder" });
  assert.equal(needsSetup(pending), false);
  assert.equal(needsSetup({ ...pending, configured: false }), false);
  const items = navItems(ROUTES, [plugin(), pending], "/");
  assert.equal(items.length, ROUTES.length);
  assert.deepEqual(items.map((i) => i.disabled), [false, false, false]);
});
