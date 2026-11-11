import { test } from "node:test";
import assert from "node:assert/strict";
import { dotHtml } from "../../src/netview/presentation/web/static/js/dot.js";

test("dot markup has role, label and tip", () => {
  assert.equal(
    dotHtml("ok", "Active"),
    '<span class="sdot ok" role="img" aria-label="Active" data-tip="Active"></span>',
  );
});

test("sm and still modifiers", () => {
  assert.match(dotHtml("warn", "x", { size: "sm" }), /class="sdot warn sm"/);
  assert.match(dotHtml("bad", "x", { still: true }), /class="sdot bad still"/);
  assert.match(dotHtml("off", "x", { size: "sm", still: true }), /class="sdot off sm still"/);
});

test("tip is escaped", () => {
  const html = dotHtml("ok", "<b>");
  assert.ok(!html.includes("<b>"));
  assert.match(html, /aria-label="&lt;b&gt;"/);
});
