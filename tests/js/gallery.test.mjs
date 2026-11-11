import { test } from "node:test";
import assert from "node:assert/strict";
import { attention, pluginStatus } from "../../src/netview/presentation/web/static/js/settings/gallery.js";

const p = (o = {}) => ({ id: "a", name: "A", enabled: true, state: "active", configured: true, ...o });

test("pluginStatus precedence", () => {
  assert.equal(pluginStatus(p({ state: "failed", restart_required: true, error: "boom" })).kind, "bad");
  assert.deepEqual(pluginStatus(p({ state: "pending", enabled: true })), { kind: "restart", tip: "Awaiting restart" });
  assert.equal(pluginStatus(p({ restart_required: true })).kind, "restart");
  assert.deepEqual(pluginStatus(p({ enabled: false, state: "disabled", configured: false })), { kind: "off", tip: "Off" });
  assert.deepEqual(pluginStatus(p({ configured: false })), { kind: "warn", tip: "Needs configuring" });
  assert.deepEqual(pluginStatus(p()), { kind: "ok", tip: "Active" });
});

test("pluginStatus: Failed shows the first line only", () => {
  assert.equal(pluginStatus(p({ state: "failed", error: "ImportError: x\n  File y\nmore" })).tip, "Failed: ImportError: x");
});

test("attention picks bad over warn", () => {
  assert.equal(attention([p(), p({ configured: false })]), "warn");
  assert.equal(attention([p({ configured: false }), p({ state: "failed", error: "e" })]), "bad");
  assert.equal(attention([p(), p({ state: "pending" })]), "bad");
  assert.equal(attention([p({ restart_required: true })]), "bad");
  assert.equal(attention([p()]), null);
});

import { readFileSync } from "node:fs";
import {
  installedCardHtml, matchesFilter, monogram, sortInstalled, sourceText,
} from "../../src/netview/presentation/web/static/js/settings/gallery.js";

test("sortInstalled puts attention first then by name", () => {
  const list = [
    p({ id: "z", name: "zeta" }),
    p({ id: "b", name: "Beta", configured: false }),
    p({ id: "a", name: "alpha" }),
    p({ id: "f", name: "Fail", state: "failed", error: "x" }),
    p({ id: "r", name: "Restart", restart_required: true }),
  ];
  assert.deepEqual(sortInstalled(list).map((x) => x.id), ["f", "r", "b", "a", "z"]);
});

test("matchesFilter on name and description", () => {
  const x = p({ name: "Starlink", description: "Dish status" });
  assert.equal(matchesFilter(x, "STAR"), true);
  assert.equal(matchesFilter(x, "dish"), true);
  assert.equal(matchesFilter(x, "nope"), false);
  assert.equal(matchesFilter(x, ""), true);
});

test("sourceText and monogram", () => {
  assert.equal(sourceText(p({ source: "folder" })), "Folder");
  assert.equal(sourceText(p({ source: "builtin" })), "Built in");
  assert.equal(sourceText(p({ source: "folder", state: "pending" })), "Just installed");
  assert.equal(monogram("starlink"), "S");
});

test("installed card shows dot top-right, chips and switch", () => {
  const html = installedCardHtml(
    p({ name: "Starlink", version: "1.2", source: "folder", description: "d", capabilities: ["health"] }),
  );
  assert.match(html, /class="pcard" role="button" tabindex="0" data-id="a"/);
  assert.match(html, /aria-label="Starlink, Active"/);
  assert.match(html, /class="pdot"><span class="sdot ok"/);
  assert.match(html, /class="chip solid" title="health">Checks reachability/);
  assert.match(html, /data-enable="a" checked/);
  assert.match(html, /1\.2 · Folder/);
});

test("pending card has no switch and says it loads next start", () => {
  const html = installedCardHtml(p({ state: "pending", source: "folder", capabilities: [] }));
  assert.ok(!html.includes("data-enable"));
  assert.ok(html.includes("Loads the next time netview starts"));
  assert.ok(html.includes("Just installed"));
});

test("failed card switch is disabled", () => {
  const html = installedCardHtml(p({ state: "failed", error: "boom\nmore", capabilities: [] }));
  assert.match(html, /data-enable="a"[^>]*disabled/);
  assert.ok(html.includes("Failed: boom"));
  assert.ok(!html.includes("more"));
});

test("card markup escapes names", () => {
  const html = installedCardHtml(p({ name: "<img onerror=x>", description: "<script>", capabilities: [] }));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script>"));
});

test("plugins-tab redraws through ctx.redraw, never ctx.select", () => {
  const src = readFileSync(
    new URL("../../src/netview/presentation/web/static/js/settings/plugins-tab.js", import.meta.url),
    "utf8",
  );
  assert.ok(!src.includes("ctx.select("));
  assert.ok(src.includes("ctx.redraw()"));
  assert.ok(!src.includes("renderOverview"));
});
