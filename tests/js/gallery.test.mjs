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

import {
  availableCardHtml, availableFooter, catalogLine, emptyAvailableText,
} from "../../src/netview/presentation/web/static/js/settings/gallery.js";

const entry = (o = {}) => ({
  id: "starlink", name: "Starlink", version: "0.1.0", description: "Dish", author: "Cadtastic",
  capabilities: ["health"], installable: true, reason: null, ...o,
});
const NOW = 1_800_000_000_000;

test("catalogLine fresh, stale-with-error and bundled", () => {
  const fresh = { source: "https://x", fetched_at_ms: NOW - 4 * 60_000, error: null, plugins: [] };
  assert.equal(catalogLine(fresh, NOW), "From github.com/Cadtastic/NetView \u00b7 checked 4 min ago");
  assert.equal(catalogLine({ ...fresh, fetched_at_ms: NOW - 5_000 }, NOW), "From github.com/Cadtastic/NetView \u00b7 checked just now");
  assert.ok(catalogLine({ ...fresh, fetched_at_ms: NOW - 2 * 3_600_000 }, NOW).endsWith("checked 2 h ago"));
  const bad = catalogLine({ ...fresh, error: "Couldn't reach GitHub" }, NOW);
  assert.match(bad, /^Couldn't reach GitHub \u00b7 showing the list from \d{4}-\d{2}-\d{2}$/);
  assert.equal(catalogLine({ source: "x", fetched_at_ms: null, error: "Couldn't reach GitHub", plugins: [] }, NOW), "Couldn't reach GitHub");
  assert.equal(catalogLine({ source: "bundled", fetched_at_ms: null, error: null, plugins: [] }, NOW), "Built-in list");
});

test("availableFooter for each job state and for a reason", () => {
  const e = entry();
  assert.match(availableFooter(e, undefined), /data-install="starlink"(?! disabled)/);
  assert.ok(availableFooter(e, { state: "queued" }).includes("Queued"));
  const dl = availableFooter(e, { state: "downloading", percent: 62 });
  assert.ok(dl.includes("Downloading\u2026 62%") && dl.includes('value="62"'));
  const indeterminate = availableFooter(e, { state: "downloading", percent: null });
  assert.ok(indeterminate.includes("Downloading\u2026") && !indeterminate.includes("value="));
  assert.ok(availableFooter(e, { state: "installing" }).includes("Installing\u2026"));
  const failed = availableFooter(e, { state: "failed", error: "<b>boom</b>" });
  assert.ok(failed.includes('class="err"') && failed.includes("&lt;b&gt;boom") && !failed.includes(" disabled"));
  const blocked = availableFooter(entry({ installable: false, reason: "Needs a newer netview" }), undefined);
  assert.ok(blocked.includes("Needs a newer netview") && blocked.includes(" disabled"));
});

test("empty states", () => {
  assert.equal(emptyAvailableText({ error: null, fetched_at_ms: NOW, plugins: [] }), "Every available plugin is installed.");
  assert.equal(emptyAvailableText({ error: null, fetched_at_ms: NOW, plugins: [entry()] }, true), "No plugins found.");
  assert.equal(
    emptyAvailableText({ error: "x", fetched_at_ms: null, plugins: [] }),
    "Couldn't reach GitHub. Check the connection and press Refresh.",
  );
});

test("available card escapes author and description", () => {
  const html = availableCardHtml(entry({ author: "<i>me</i>", description: "<script>x</script>", name: "<b>N</b>" }), undefined);
  assert.ok(!html.includes("<i>me") && !html.includes("<script>") && !html.includes("<b>N"));
  assert.ok(html.includes("by &lt;i&gt;me") && html.includes('class="chip solid"') && !html.includes("sdot"));
});
