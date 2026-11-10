import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveTheme, applyTheme, loadThemePref, saveThemePref } from "../../src/netview/presentation/web/static/js/theme.js";

const LIST = [
  { id: "daylight", url: "/static/themes/daylight.css", error: null },
  { id: "graphite", url: "/static/themes/graphite.css", error: null },
  { id: "user-broken", url: "/themes/user/broken.css", error: "bad header" },
];

test("resolveTheme picks a known theme", () => {
  assert.deepEqual(resolveTheme("graphite", LIST), { mode: "fixed", theme: LIST[1] });
});

test("resolveTheme falls back to system", () => {
  assert.deepEqual(resolveTheme("nope", LIST), { mode: "system" });
  assert.deepEqual(resolveTheme("system", LIST), { mode: "system" });
  assert.deepEqual(resolveTheme(null, LIST), { mode: "system" });
  assert.deepEqual(resolveTheme("user-broken", LIST), { mode: "system" });
});

function fakeDoc() {
  const els = new Map();
  const mk = (id, media) => {
    const attrs = { media };
    return { id, attrs, disabled: false, getAttribute: (k) => attrs[k], setAttribute: (k, v) => (attrs[k] = v), removeAttribute: (k) => delete attrs[k], remove() { els.delete(this.id); }, set href(v) { attrs.href = v; }, get href() { return attrs.href; } };
  };
  els.set("theme-light", mk("theme-light", "(prefers-color-scheme: light)"));
  els.set("theme-dark", mk("theme-dark", "(prefers-color-scheme: dark)"));
  return {
    els,
    documentElement: { dataset: {} },
    head: { appendChild: (e) => els.set(e.id, e) },
    getElementById: (id) => els.get(id) || null,
    createElement: () => mk("", undefined),
  };
}

test("applyTheme fixed adds an unconditional link and mutes the media pair", () => {
  const doc = fakeDoc();
  applyTheme({ mode: "fixed", theme: LIST[1] }, doc);
  assert.equal(doc.els.get("theme").href, "/static/themes/graphite.css");
  assert.equal(doc.els.get("theme").attrs.media, undefined);
  assert.equal(doc.els.get("theme-light").attrs.media, "not all");
  assert.equal(doc.els.get("theme-dark").attrs.media, "not all");
  assert.equal(doc.documentElement.dataset.theme, "graphite");
});

test("applyTheme system restores the media pair and drops the explicit link", () => {
  const doc = fakeDoc();
  applyTheme({ mode: "fixed", theme: LIST[1] }, doc);
  applyTheme({ mode: "system" }, doc);
  assert.equal(doc.els.has("theme"), false);
  assert.equal(doc.els.get("theme-light").attrs.media, "(prefers-color-scheme: light)");
  assert.equal(doc.els.get("theme-dark").attrs.media, "(prefers-color-scheme: dark)");
  assert.equal(doc.documentElement.dataset.theme, undefined);
});

test("theme preference round-trips and survives broken storage", () => {
  const store = new Map();
  globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
  assert.equal(loadThemePref(), "system");
  saveThemePref("harbor");
  assert.equal(store.get("netview-theme"), "harbor");
  assert.equal(loadThemePref(), "harbor");
  globalThis.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(loadThemePref(), "system");
  assert.doesNotThrow(() => saveThemePref("daylight"));
  delete globalThis.localStorage;
  assert.equal(loadThemePref(), "system");
});
