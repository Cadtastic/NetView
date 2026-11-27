import { test } from "node:test";
import assert from "node:assert/strict";
import { offeredBases, resolveBase } from "../../static/imagery-model.js";

test("Sentinel-2 is offered only when the admin chose it", () => {
  assert.deepEqual(offeredBases("natural_earth").map(([v]) => v), ["natural_earth"]);
  assert.deepEqual(offeredBases(undefined).map(([v]) => v), ["natural_earth"]);
  assert.deepEqual(offeredBases("eox_s2").map(([v]) => v), ["natural_earth", "eox_s2"]);
});

test("a stored pick that is no longer allowed falls back to the admin's choice", () => {
  assert.equal(resolveBase("eox_s2", "natural_earth"), "natural_earth");
  assert.equal(resolveBase("eox_s2", "eox_s2"), "eox_s2");
  assert.equal(resolveBase("natural_earth", "eox_s2"), "natural_earth");
  assert.equal(resolveBase(null, "eox_s2"), "eox_s2");
  assert.equal(resolveBase("junk", "natural_earth"), "natural_earth");
});
