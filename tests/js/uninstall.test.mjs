import { test } from "node:test";
import assert from "node:assert/strict";
import {
  confirmUninstallHtml, failureText, runUninstall, toastText, uninstallName, uninstallSectionHtml,
} from "../../src/netview/presentation/web/static/js/settings/uninstall.js";

const info = (o = {}) => ({
  id: "7", card_key: "ck", name: "Roku", display_name: "Roku TV", folder: "roku", uninstallable: true, owns_data: true, state: "active", ...o,
});

test("section is hidden for a built-in and for a plugin_dirs plugin", () => {
  assert.equal(uninstallSectionHtml(info({ uninstallable: false, folder: null })), "");
  assert.equal(uninstallSectionHtml(info({ uninstallable: false })), "");
});

test("section shows an Uninstall button for an uninstallable plugin", () => {
  const html = uninstallSectionHtml(info());
  assert.match(html, /data-uninstall/);
  assert.match(html, />Uninstall</);
});

test("section shows for a stopped card whose uninstall didn't finish (retry)", () => {
  const stopped = info({ state: "failed", owns_data: false, error: "Uninstall didn't finish: locked. It will be removed when netview restarts" });
  const html = uninstallSectionHtml(stopped);
  assert.match(html, /data-uninstall/);
  assert.doesNotMatch(confirmUninstallHtml(stopped), /type="checkbox"/);
});

test("dialog has the data checkbox only when the card owns its data", () => {
  assert.match(confirmUninstallHtml(info({ owns_data: true })), /<input type="checkbox" data-delete-data>/);
  assert.doesNotMatch(confirmUninstallHtml(info({ owns_data: false })), /checkbox/);
});

test("dialog copy is exact", () => {
  const html = confirmUninstallHtml(info());
  assert.match(html, /Uninstall Roku TV\?/);
  assert.match(html, /Its folder is deleted\. It stops now and is fully gone after netview restarts\./);
  assert.match(html, /Also delete its saved settings and data/);
  assert.doesNotMatch(html, /checked/);
  assert.match(html, /data-cancel[^>]*>Cancel</);
  assert.match(html, /class="danger"[^>]*data-confirm[^>]*>Uninstall</);
});

test("dialog escapes the plugin name", () => {
  assert.doesNotMatch(confirmUninstallHtml(info({ display_name: "<img src=x>" })), /<img/);
});

test("name falls back from display_name to name", () => {
  assert.equal(uninstallName(info()), "Roku TV");
  assert.equal(uninstallName(info({ display_name: "" })), "Roku");
  assert.equal(uninstallName(info({ display_name: undefined })), "Roku");
});

test("failure and toast copy", () => {
  assert.equal(failureText("disk busy"), "Uninstall didn't finish: disk busy. It will be removed when netview restarts");
  assert.equal(toastText(info()), "Roku TV uninstalled");
});

test("runUninstall posts the folder and delete_data and returns the answer", async () => {
  const calls = [];
  const send = async (method, path, body) => (calls.push([method, path, body]), { finished: true, error: null });
  const out = await runUninstall(info(), true, send);
  assert.deepEqual(calls, [["POST", "/api/v1/plugins/uninstall", { folder: "roku", delete_data: true }]]);
  assert.deepEqual(out, { finished: true, error: null });
});

test("runUninstall never asks to delete data for a card that does not own it", async () => {
  let body;
  await runUninstall(info({ owns_data: false }), true, async (m, p, b) => ((body = b), { finished: false, error: "x" }));
  assert.equal(body.delete_data, false);
});

import { startUninstall } from "../../src/netview/presentation/web/static/js/settings/uninstall.js";
import { pendingBodyHtml } from "../../src/netview/presentation/web/static/js/settings/overlay.js";

function fakeCtx() {
  const calls = [];
  return {
    calls,
    removePlugin: () => calls.push("removePlugin"),
    finishUninstall: async () => calls.push("finish"),
    reloadPlugins: async () => calls.push("reload"),
    redraw: () => calls.push("redraw"),
  };
}

test("startUninstall drops the plugin when finished", async () => {
  const ctx = fakeCtx();
  const notes = [];
  await startUninstall(ctx, info(), () => {}, async () => ({ answer: { finished: true, error: null } }), (m) => notes.push(m));
  assert.deepEqual(ctx.calls, ["finish", "redraw"]);
  assert.deepEqual(notes, ["Roku TV uninstalled"]);
});

test("startUninstall drops the plugin before re-fetching when not finished", async () => {
  const ctx = fakeCtx();
  const errs = [];
  await startUninstall(ctx, info(), (t) => errs.push(t), async () => ({ answer: { finished: false, error: "busy" } }), () => {});
  assert.deepEqual(ctx.calls, ["removePlugin", "reload", "redraw"]);
  assert.equal(errs.at(-1), "Uninstall didn't finish: busy. It will be removed when netview restarts");
});

test("startUninstall does nothing on cancel", async () => {
  const ctx = fakeCtx();
  await startUninstall(ctx, info(), () => {}, async () => ({ cancelled: true }), () => {});
  assert.deepEqual(ctx.calls, []);
});

test("a pending uninstallable plugin's overlay body has the Uninstall section", () => {
  const admin = { isAdmin: () => true };
  const pending = info({ state: "pending", capabilities: [] });
  assert.match(pendingBodyHtml(admin, pending), /data-uninstall/);
  assert.doesNotMatch(pendingBodyHtml({ isAdmin: () => false }, pending), /data-uninstall/);
  assert.doesNotMatch(pendingBodyHtml(admin, info({ state: "pending", uninstallable: false })), /data-uninstall/);
});
