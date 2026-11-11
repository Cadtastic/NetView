import { test } from "node:test";
import assert from "node:assert/strict";
import { tvSvg } from "../../static/tv.js";

test("tvSvg on and off", () => {
  const on = tvSvg({ on: true, name: "Living Room TV" });
  const off = tvSvg({ on: false, name: "Living Room TV" });
  assert.match(on, /aria-label="Living Room TV is on"/);
  assert.match(off, /aria-label="Living Room TV is off"/);
  assert.match(on, /role="img"/);
  assert.match(on, /HOME/);
  assert.doesNotMatch(off, /HOME/);
  assert.match(off, /#e0463a/);
  assert.doesNotMatch(on, /#e0463a/);
  assert.match(on, /#3c3f46/);
});

test("tvSvg gradient ids are prefixed rk- and the name is escaped", () => {
  const svg = tvSvg({ on: true, name: 'A "<b>" TV' });
  for (const m of svg.matchAll(/<linearGradient id="([^"]+)"/g)) assert.match(m[1], /^rk-/);
  assert.doesNotMatch(svg, /<b>/);
  assert.match(svg, /&lt;b&gt;/);
});
