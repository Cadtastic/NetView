import { test } from "node:test";
import assert from "node:assert/strict";
import { navHtml, navItems, navLabel, needsSetup, nextNavMarkup, pickRoute } from "../../src/netview/presentation/web/static/js/nav.js";
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
  assert.match(html, /aria-disabled="true"[^>]*class="off" data-setup="gsm7248" title="GSM7248 needs configuring in Settings[^"]*">Switch/);
});

test("needs-setup nav item carries an amber dot", () => {
  const html = navHtml(navItems(ROUTES, [plugin({ configured: false })], "/"));
  assert.match(html, /Switch<span class="sdot warn sm" role="img" aria-label="Needs configuring"/);
  assert.ok(!navHtml(navItems(ROUTES, [plugin()], "/")).includes("sdot"));
});

test("a tab disabled by unavailable() opens the plugin's settings but carries no needs-configuring dot", () => {
  const routes = [...ROUTES, { path: "/p/roku/tvs", label: "Roku", pluginId: "roku", unavailable: () => "No Roku TVs found yet." }];
  const items = navItems(routes, [plugin(), plugin({ id: "roku", name: "Roku" })], "/");
  assert.equal(items[3].setup, false);
  const html = navHtml(items);
  assert.match(html, /aria-disabled="true"[^>]*class="off" data-setup="roku" title="No Roku TVs found yet.">Roku<\/a>/);
  assert.ok(!html.includes("sdot"));
});

test("nextNavMarkup sees a tab turn from needs-configuring to unavailable() as a change", () => {
  const routes = [...ROUTES.slice(0, 2), { path: "/p/roku/tvs", label: "Roku", pluginId: "roku", unavailable: () => "No TVs." }];
  const setup = navHtml(navItems(routes, [plugin({ id: "roku", name: "Roku", configured: false })], "/"));
  const empty = navHtml(navItems(routes, [plugin({ id: "roku", name: "Roku" })], "/"));
  assert.notEqual(nextNavMarkup(setup, empty), null);
  assert.equal(nextNavMarkup(empty, navHtml(navItems(routes, [plugin({ id: "roku", name: "Roku" })], "/"))), null);
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

test("nextNavMarkup returns the markup only when it differs from what is shown", () => {
  const a = navHtml(navItems(ROUTES, [plugin()], "/"));
  assert.equal(nextNavMarkup(null, a), a);
  assert.equal(nextNavMarkup(a, a), null);
  assert.equal(nextNavMarkup(a, navHtml(navItems(ROUTES, [plugin()], "/devices"))) !== null, true);
  assert.equal(nextNavMarkup(a, navHtml(navItems(ROUTES, [plugin()], "/"))), null);
});

import { canSeeAdmin, withAdminRoute } from "../../src/netview/presentation/web/static/js/nav.js";
import { configurable, tabsFor as settingsTabsFor } from "../../src/netview/presentation/web/static/js/settings/dialog.js";

const holder = (...ids) => ({ can: (id) => ids.includes(id), isAdmin: false });

test("nav includes Admin only for users or system holders", () => {
  const base = [{ path: "/", label: "Dashboard" }];
  const mount = () => {};
  assert.equal(withAdminRoute(base, holder("core.view"), mount).length, 1);
  assert.deepEqual(withAdminRoute(base, holder("core.users"), mount).map((r) => r.path), ["/", "/admin"]);
  assert.deepEqual(withAdminRoute(base, holder("core.system"), mount).map((r) => r.path), ["/", "/admin"]);
  assert.equal(canSeeAdmin(holder()), false);
});

test("the settings Plugins tab lists only plugins the user may configure", () => {
  const list = [{ id: "1", guid: "ga" }, { id: "2", guid: "gb" }];
  assert.deepEqual(configurable(list, holder("ga.configure")).map((p) => p.id), ["1"]); // the guid, not the source id
  assert.deepEqual(configurable(list, holder("1.configure")), []);
  assert.equal(configurable(list, null).length, 2);
  assert.equal(configurable(list, holder("core.plugins")).length, 2); // turning plugins on or off needs the list too
});

test("the Available tab (install controls) is for administrators only", () => {
  assert.ok(settingsTabsFor([], 0, true).some((t) => t.id === "plugins:available"));
  assert.ok(!settingsTabsFor([], 0, false).some((t) => t.id === "plugins:available"));
});

test("navLabel: the display name alone for a one-page plugin, name plus page for several", () => {
  const spec = { id: "switch", title: "Ports", pluginDisplayName: "GSM7248" };
  assert.equal(navLabel(spec, 1), "GSM7248");
  assert.equal(navLabel(spec, 2), "GSM7248 \u00b7 Ports");
  assert.equal(navLabel({ id: "tvs", pluginDisplayName: "Roku" }, 2), "Roku \u00b7 tvs"); // no title: the page id
  assert.equal(navLabel({ id: "x", title: "Fallback" }, 1), "Fallback"); // a spec without a display name
});

import { canConfigure } from "../../src/netview/presentation/web/static/js/settings/plugins-tab.js";

test("canConfigure asks for <guid>.configure", () => {
  const info = { id: "7", guid: "g7" };
  assert.equal(canConfigure(holder("g7.configure").can, info), true);
  assert.equal(canConfigure(holder("7.configure").can, info), false);
});
