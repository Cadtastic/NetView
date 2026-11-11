import { test } from "node:test";
import assert from "node:assert/strict";
import { navHtml, navItems, needsSetup, pickRoute } from "../../src/netview/presentation/web/static/js/nav.js";
import { tabsFor } from "../../src/netview/presentation/web/static/js/settings/dialog.js";

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

test("navItems disables a page whose unavailable() returns a reason, with that reason as its title", () => {
  const routes = [...ROUTES, { path: "/p/roku/tvs", label: "Roku", pluginId: "roku",
    unavailable: () => "No Roku TVs found yet. Click to open Roku settings and scan." }];
  const items = navItems(routes, [plugin(), plugin({ id: "roku", name: "Roku" })], "/p/roku/tvs");
  assert.equal(items[3].disabled, true);
  assert.equal(items[3].on, false);
  assert.equal(items[3].title, "No Roku TVs found yet. Click to open Roku settings and scan.");
});

test("navItems keeps a page enabled when unavailable() returns null, and needsSetup still wins", () => {
  const routes = [{ path: "/p/gsm7248/switch", label: "Switch", pluginId: "gsm7248", unavailable: () => null }];
  assert.equal(navItems(routes, [plugin()], "/p/gsm7248/switch")[0].disabled, false);
  assert.match(navItems(routes, [plugin({ configured: false })], "/")[0].title, /needs configuring/);
});

test("navItems treats a throwing unavailable() as available", () => {
  const routes = [{ path: "/p/x/y", label: "Y", pluginId: "x", unavailable: () => { throw new Error("boom"); } }];
  assert.equal(navItems(routes, [], "/p/x/y")[0].disabled, false);
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
  assert.match(html, /aria-disabled="true"[^>]*class="off" data-setup="gsm7248" title="GSM7248 needs configuring in Settings[^"]*">Switch<\/a>/);
});

test("navHtml escapes labels and hints", () => {
  const html = navHtml(navItems([{ path: "/p/x/y", label: "<b>", pluginId: "x" }], [plugin({ id: "x", name: "<i>", configured: false })], "/"));
  assert.ok(!html.includes("<b>"));
  assert.ok(!html.includes("<i>"));
});

test("tabsFor flags a plugin that needs configuring for the settings rail", () => {
  const tabs = tabsFor([plugin({ configured: false }), plugin({ id: "ok", name: "OK" })]);
  assert.deepEqual(tabs.slice(2).map((t) => [t.id, t.setup]), [
    ["plugin:gsm7248", true],
    ["plugin:ok", false],
  ]);
});
