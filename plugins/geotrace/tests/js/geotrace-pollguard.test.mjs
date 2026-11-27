import { test } from "node:test";
import assert from "node:assert/strict";
import { createPollGuard, isTargetTrace, isOnceTrace, GONE_TEXT } from "../../static/poll-guard.js";

test("a 404 means the trace is gone", () => {
  const g = createPollGuard();
  assert.equal(g.failed(Object.assign(new Error("unknown trace"), { status: 404 })), "gone");
  assert.equal(GONE_TEXT, "This trace is no longer available.");
});

test("other errors retry a few times, then stop; a good answer resets the count", () => {
  const g = createPollGuard({ maxFailures: 3 });
  const bad = new Error("boom");
  assert.equal(g.failed(bad), "retry");
  assert.equal(g.failed(bad), "retry");
  g.ok();
  assert.equal(g.failed(bad), "retry");
  assert.equal(g.failed(bad), "retry");
  assert.equal(g.failed(bad), "stop");
});

test("Route accepts only a trace of its own target", () => {
  assert.equal(isTargetTrace({ target_id: 4 }, 4), true);
  assert.equal(isTargetTrace({ target_id: 5 }, 4), false);
  assert.equal(isTargetTrace({ target_id: null }, 4), false);
  assert.equal(isTargetTrace(null, 4), false);
});

test("Trace once accepts only a one-off with the same start time as the first answer", () => {
  const first = { trigger: "once", started_ms: 1000 };
  assert.equal(isOnceTrace({ trigger: "once", started_ms: 1000 }, first), true);
  assert.equal(isOnceTrace({ trigger: "once", started_ms: 2000 }, first), false);
  assert.equal(isOnceTrace({ trigger: "scheduled", started_ms: 1000 }, first), false);
  assert.equal(isOnceTrace({ trigger: "once", started_ms: 2000 }, null), true);
  assert.equal(isOnceTrace(null, null), false);
});
