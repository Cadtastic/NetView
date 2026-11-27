import { test } from "node:test";
import assert from "node:assert/strict";
import { arcPoints, routePoints, blend, streetAlpha, fitView, STARLINK_ALTITUDE_M } from "../../static/geometry.js";

const denver = { lon: -104.99, lat: 39.74 };
const dallas = { lon: -96.8, lat: 32.78 };
const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} vs ${b}`);

test("arcPoints: endpoints are exact and the arc peaks in the middle", () => {
  const pts = arcPoints(denver, dallas, { steps: 40 });
  assert.equal(pts.length, 41);
  assert.deepEqual(pts[0], { lon: denver.lon, lat: denver.lat, h: 0 });
  assert.deepEqual(pts[40], { lon: dallas.lon, lat: dallas.lat, h: 0 });
  const peak = Math.max(...pts.map((p) => p.h));
  assert.equal(pts[20].h, peak);
  assert.ok(pts[10].h < peak && pts[30].h < peak);
});

test("arcPoints: default lift is min(distance * 0.12, 350000) + 2000", () => {
  const pts = arcPoints(denver, dallas, { steps: 2 });
  const d = 1_000_000; // Denver to Dallas is about 1 070 km, so 0.12 * d is under the cap
  assert.ok(pts[1].h > d * 0.1 && pts[1].h < 350000 + 2000);
  const far = arcPoints({ lon: 0, lat: 0 }, { lon: 90, lat: 0 }, { steps: 2 });
  near(far[1].h, 352000, 1e-3);
});

test("arcPoints: an explicit lift sets the peak and the path stays on the great circle", () => {
  const pts = arcPoints(denver, dallas, { liftM: 550000, steps: 2 });
  near(pts[1].h, 550000, 1e-3);
  assert.ok(pts[1].lon > denver.lon && pts[1].lon < dallas.lon);
});

test("arcPoints: the same point twice gives a flat arc", () => {
  const pts = arcPoints(denver, denver, { steps: 4 });
  assert.ok(pts.every((p) => p.lon === denver.lon && p.lat === denver.lat));
});

const hop = (n, lat, lon, extra = {}) => ({ n, lat, lon, asn: null, ...extra });

test("routePoints: silent hops are skipped and legs join without a repeated point", () => {
  const hops = [hop(1, 38.8, -104.8), hop(2, null, null), hop(3, 39.7, -105), hop(4, 32.8, -96.8)];
  const pts = routePoints(hops, { starlink: false });
  assert.deepEqual(routePoints([hop(1, null, null), hop(2, undefined, undefined)], { starlink: false }), []);
  assert.deepEqual(pts[0], { lon: -104.8, lat: 38.8, h: 0 });
  assert.deepEqual(pts[pts.length - 1], { lon: -96.8, lat: 32.8, h: 0 });
  const keys = pts.map((p) => `${p.lon},${p.lat},${p.h}`);
  assert.equal(new Set(keys).size, keys.length);
});

test("routePoints: a single placed hop gives one point", () => {
  assert.deepEqual(routePoints([hop(1, 10, 20)], { starlink: false }), [{ lon: 20, lat: 10, h: 0 }]);
});

test("routePoints: Starlink first leg peaks at 550 000 m, other legs do not", () => {
  const hops = [hop(1, 38.8, -104.8), hop(2, 39.7, -105), hop(3, 32.8, -96.8)];
  assert.equal(STARLINK_ALTITUDE_M, 550000);
  const pts = routePoints(hops, { starlink: true });
  near(Math.max(...pts.map((p) => p.h)), 550000, 1e-3);
  const plain = routePoints(hops, { starlink: false });
  assert.ok(Math.max(...plain.map((p) => p.h)) < 400000);
  const second = pts.slice(Math.floor(pts.length / 2) + 2);
  assert.ok(Math.max(...second.map((p) => p.h)) < 400000);
});

test("blend: zero far out, one close in, linear between", () => {
  assert.equal(blend(4_000_000), 0);
  assert.equal(blend(24_000_000), 0);
  assert.equal(blend(600_000), 1);
  assert.equal(blend(9000), 1);
  near(blend(2_300_000), 0.5);
  assert.equal(streetAlpha(600_000), 0.92);
  assert.equal(streetAlpha(9_000_000), 0);
});

test("fitView: empty list shows the whole Earth", () => {
  const v = fitView([]);
  assert.ok(Number.isFinite(v.lon) && Number.isFinite(v.lat));
  assert.ok(v.heightM >= 15_000_000);
});

test("fitView: a single hop centres on it at a close height", () => {
  const v = fitView([hop(1, 39.74, -104.99)]);
  near(v.lon, -104.99, 1e-6);
  near(v.lat, 39.74, 1e-6);
  assert.ok(v.heightM > 0 && v.heightM <= 3_000_000);
});

test("fitView: a route is centred between its ends and fits both", () => {
  const v = fitView([hop(1, 38.8, -104.8), hop(2, null, null), hop(3, 37.3, -121.9)]);
  assert.ok(v.lon < -104.8 && v.lon > -121.9);
  assert.ok(v.heightM > 1_000_000);
});
