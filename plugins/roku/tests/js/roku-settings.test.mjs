import { test } from "node:test";
import assert from "node:assert/strict";
import { scanSummary, pasteWrapper } from "../../static/settings.js";

test("scanSummary wording", () => {
  assert.equal(scanSummary({ finished_ms: null }), "No scan yet.");
  assert.match(
    scanSummary({ finished_ms: 1, found: 3, by_ssdp: 2, by_sweep: 3, duration_s: 4.6 }, () => "10:00"),
    /^Last scan 10:00: 3 found \(2 by SSDP and address check, 1 by address check only\)\. Took 4\.6 s\.$/,
  );
});

test("pasteWrapper wraps for each OS", () => {
  assert.equal(pasteWrapper("win", "x"), "@'\nx\n'@ | python -");
  assert.equal(pasteWrapper("unix", "x"), "python3 - <<'EOF'\nx\nEOF");
});
