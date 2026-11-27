import { test } from "node:test";
import assert from "node:assert/strict";
import { compareRows, splitSentence, cellText } from "../../static/compare-model.js";
import { CMP_NEW, CMP_OLD, COMPARE_KEYS, routeDrawKey, isShown, drawKey } from "../../static/draw-keys.js";
import { snapChanges, RANGES, DEFAULT_RANGE, normalizeRange, loadRange, saveRange, rangeSubtitle } from "../../static/trends-model.js";

const hop = (n, city, rtt) => ({ n, ip: "8.8.8.8", city, region: "CA", rtts_ms: [rtt], placement: "located" });

test("compareRows keeps the hops and marks differing rows", () => {
  const rows = compareRows([
    { n: 1, a: hop(1, "Denver", 10), b: hop(1, "Denver", 11), differs: false },
    { n: 2, a: hop(2, "Dallas", 30), b: hop(2, "Reno", 28), differs: true },
    { n: 3, a: null, b: hop(3, "Reno", 40), differs: true },
  ]);
  assert.deepEqual(rows.map((r) => r.n), [1, 2, 3]);
  assert.deepEqual(rows.map((r) => r.differs), [false, true, true]);
  assert.deepEqual(rows.map((r) => r.className), ["", "gt-diff", "gt-diff"]);
  assert.equal(rows[2].a, null);
  assert.equal(rows[1].b.city, "Reno");
});

test("compareRows tolerates junk", () => {
  assert.deepEqual(compareRows(null), []);
  assert.deepEqual(compareRows(undefined), []);
});

test("splitSentence names the hop, or says the routes are the same", () => {
  assert.equal(splitSentence(3, []), "They split after hop 3.");
  assert.equal(splitSentence(0, []), "They split from the first hop.");
  assert.equal(splitSentence(null, compareRows([{ n: 1, a: hop(1, "X", 1), b: hop(1, "X", 1), differs: false }])), "Same route.");
  assert.equal(splitSentence(null, compareRows([{ n: 1, a: hop(1, "X", 1), b: null, differs: true }])), "The routes differ.");
});

test("cellText: place and time, a dash for a missing hop, stars for a silent one", () => {
  assert.equal(cellText(null), "—");
  assert.equal(cellText({ n: 4, ip: null, rtts_ms: [], placement: "none" }), "* * *");
  assert.equal(cellText(hop(2, "Dallas", 38)), "Dallas, CA · 38 ms");
});

test("trends ranges and the remembered one", () => {
  assert.deepEqual(RANGES.map((r) => r.key), ["24h", "7d", "30d", "90d"]);
  assert.deepEqual(RANGES.map((r) => r.label), ["24 h", "7 d", "30 d", "90 d"]);
  assert.equal(DEFAULT_RANGE, "24h");
  assert.equal(normalizeRange("30d"), "30d");
  assert.equal(normalizeRange("1y"), "24h");
  assert.equal(normalizeRange(null), "24h");
  assert.equal(rangeSubtitle("7d"), "last 7 days");
  assert.equal(rangeSubtitle("24h"), "last 24 hours");
});

test("loadRange / saveRange use storage safely", () => {
  const mem = new Map();
  const storage = { getItem: (k) => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, v) };
  assert.equal(loadRange(storage), "24h");
  saveRange("90d", storage);
  assert.equal(mem.get("netview.geotrace.trendsRange"), "90d");
  assert.equal(loadRange(storage), "90d");
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(loadRange(broken), "24h");
  saveRange("7d", broken); // must not throw
});

test("snapChanges puts each change on its bucket start, including the last bucket", () => {
  const pts = [[1000, 1], [1100, 2], [1200, 3], [1300, 4]];
  assert.deepEqual(snapChanges([1050, 1349, 1300], pts), [1000, 1300]);
  assert.deepEqual(snapChanges([500, 9999], pts), [1300]); // before the range is dropped; later than the end clamps
  assert.deepEqual(snapChanges([1000], []), []);
  assert.deepEqual(snapChanges(null, pts), []);
});

test("compare drawing keys never equal a bare trace id or the route's key", () => {
  assert.equal(new Set([CMP_NEW, CMP_OLD, routeDrawKey(7)]).size, 3);
  for (const k of [...COMPARE_KEYS, routeDrawKey(7)]) assert.equal(typeof k, "string");
  for (const id of [0, 1, 7, 42]) {
    assert.notEqual(CMP_NEW, id);
    assert.notEqual(CMP_NEW, String(id));
    assert.notEqual(CMP_OLD, String(id));
    assert.notEqual(routeDrawKey(id), id);
    assert.notEqual(routeDrawKey(id), String(id));
  }
  assert.equal(drawKey({ id: 5 }, undefined), 5);
  assert.equal(drawKey({ id: 5 }, CMP_OLD), CMP_OLD);
});

test("focus hides every drawing outside the focused set", () => {
  const focus = new Set(COMPARE_KEYS);
  assert.equal(isShown(CMP_NEW, focus), true);
  assert.equal(isShown(routeDrawKey(7), focus), false);
  assert.equal(isShown(routeDrawKey(7), null), true);
});
