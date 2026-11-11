import { test } from "node:test";
import assert from "node:assert/strict";
import { pollButtonState } from "../../src/netview/plugins/builtin/gsm7248/static/page.js";

test("Poll now is enabled when nothing is polling", () => {
  assert.deepEqual(pollButtonState({ polling: false }, false), { disabled: false, label: "Poll now", title: "Poll the switch now" });
  assert.equal(pollButtonState(null, false).disabled, false); // no summary yet
});

test("Poll now is disabled while the server reports a poll running", () => {
  const b = pollButtonState({ polling: true }, false);
  assert.equal(b.disabled, true);
  assert.equal(b.label, "Polling…");
});

test("Poll now is disabled while this page's request is out", () => {
  assert.equal(pollButtonState({ polling: false }, true).disabled, true);
  assert.equal(pollButtonState(null, true).label, "Polling…");
});

test("an older server without the polling field leaves it enabled", () => {
  assert.equal(pollButtonState({ reachable: true }, false).disabled, false);
});

import { memoryText } from "../../src/netview/plugins/builtin/gsm7248/static/page.js";

test("memoryText shows free memory alone when the switch reports no total", () => {
  assert.equal(memoryText({ mem_free_kb: 61224, mem_total_kb: null }), "60 MB");
  assert.equal(memoryText({ mem_free_kb: 61224, mem_total_kb: 131072 }), "60 of 128 MB");
  assert.equal(memoryText({ mem_free_kb: null, mem_total_kb: 131072 }), null);
  assert.equal(memoryText(null), null);
});
