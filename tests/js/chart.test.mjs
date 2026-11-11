import { test } from "node:test";
import assert from "node:assert/strict";
import { niceMax, gapMs, segments, endLabels, latencyStats, sparkline } from "../../src/netview/presentation/web/static/js/chart.js";
import * as util from "../../src/netview/presentation/web/static/js/util.js";

test("niceMax rounds up to a four-step axis", () => {
  assert.equal(niceMax(7.3), 8);
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(130), 200);
  assert.equal(niceMax(-5), 1);
  assert.equal(niceMax(NaN), 1);
});

test("gapMs is 2.5 times the median step, or 12.5 s with fewer than two steps", () => {
  assert.equal(gapMs([0, 5000, 10000, 40000]), 12500);
  assert.equal(gapMs([]), 12500);
  assert.equal(gapMs([0, 5000]), 12500);
  assert.equal(gapMs([0, 10000, 20000, 30000]), 25000);
});

test("segments splits at a time jump and sends an isolated point to lone", () => {
  const pts = [[0, 1], [5000, 2], [10000, 3], [40000, 4]];
  const { runs, lone } = segments(pts, 12500);
  assert.deepEqual(runs, [[[0, 1], [5000, 2], [10000, 3]]]);
  assert.deepEqual(lone, [[40000, 4]]);
});

test("segments breaks at a null and keeps nothing for it", () => {
  const pts = [[0, 1], [5000, 2], [10000, null], [15000, 3], [20000, 4], [25000, null], [30000, 5]];
  const { runs, lone } = segments(pts, 12500);
  assert.equal(runs.length, 2);
  assert.deepEqual(lone, [[30000, 5]]);
  assert.deepEqual(segments([], 1000), { runs: [], lone: [] });
});

test("endLabels drops every label when two would be closer than 14 px", () => {
  assert.deepEqual(endLabels([{ y: 10 }, { y: 20 }]), []);
  assert.equal(endLabels([{ y: 40 }, { y: 10 }]).length, 2);
  assert.deepEqual(endLabels([{ y: 40 }, { y: 10 }]).map((l) => l.y), [10, 40]);
  assert.equal(endLabels([{ y: 10 }, { y: 24 }]).length, 2);
  assert.equal(endLabels([{ y: 10 }, { y: 23.9 }]).length, 0);
  assert.equal(endLabels([{ y: 10 }]).length, 1);
  assert.equal(endLabels([{ y: 10 }, { y: 20 }], 5).length, 2);
});

test("latencyStats", () => {
  assert.deepEqual(latencyStats([10, null, 20, 30]), { last: 30, loss: 25, avg: 20, min: 10, max: 30, jitter: 10 });
  assert.deepEqual(latencyStats([]), { last: null, loss: null, avg: null, min: null, max: null, jitter: null });
  const allLost = latencyStats([null, null]);
  assert.equal(allLost.loss, 100);
  assert.equal(allLost.avg, null);
  assert.equal(allLost.last, null);
  assert.equal(latencyStats([5]).jitter, null);
});

test("sparkline draws a line and marks missing samples with bad-coloured ticks", () => {
  const svg = sparkline([1, 2, null, 3], { w: 72, h: 18, color: "--series-2" });
  assert.ok(svg.startsWith("<svg"));
  assert.ok(svg.includes("var(--series-2)"));
  assert.ok(svg.includes("var(--bad)"));
  assert.equal(sparkline([1]), "");
  assert.equal(sparkline([]), "");
  assert.ok(sparkline([1, 2]).includes("var(--series-1)"));
});

test("the chart helpers are re-exported for plugins as ui.util", () => {
  for (const name of ["niceMax", "gapMs", "segments", "endLabels", "latencyStats", "lineChart", "sparkline", "fmtMs"]) {
    assert.equal(typeof util[name], "function", name);
  }
});

test("fmtMs", () => {
  assert.equal(util.fmtMs(2.14), "2.1");
  assert.equal(util.fmtMs(12.6), "13");
  assert.equal(util.fmtMs(null), "–");
});
