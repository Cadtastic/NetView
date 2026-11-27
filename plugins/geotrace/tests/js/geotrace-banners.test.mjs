import { test } from "node:test";
import assert from "node:assert/strict";
import { bannersFor, COPY } from "../../static/banners.js";

const ok = { geo: { city: { path: "x" } }, home_set: true, traceroute_ok: true, bundle: { state: "ready" } };
const ids = (b) => b.map((x) => x.id);

test("exact copy", () => {
  assert.equal(COPY.empty, "No targets yet. Add one to start tracing.");
  assert.equal(COPY.home, "Set your home location in GeoTrace settings so the first hops start at your house.");
  assert.equal(COPY.bundleLoading, "Preparing the globe (one-time download, about 5 MB)…");
  assert.equal(COPY.bundleNotPublished, "The globe files haven't been published yet. Traces still work; the map appears once they are.");
  assert.equal(COPY.noGeo, "Location data is still downloading. Hops are listed but not placed yet.");
  assert.equal(COPY.noTraceroute, "traceroute is not installed on the NetView server.");
});

test("nothing to say while everything is fine", () => {
  assert.deepEqual(bannersFor(ok, 3), []);
  assert.deepEqual(bannersFor(null, null), []);
});

test("empty state only when the count is known to be zero", () => {
  assert.deepEqual(ids(bannersFor(ok, 0)), ["empty"]);
  assert.deepEqual(bannersFor(ok, null), []);
});

test("bundle states", () => {
  for (const s of ["downloading", "missing"]) {
    const b = bannersFor({ ...ok, bundle: { state: s } }, 1);
    assert.equal(b[0].text, COPY.bundleLoading);
  }
  assert.equal(bannersFor({ ...ok, bundle: { state: "not_published" } }, 1)[0].text, COPY.bundleNotPublished);
  const failed = bannersFor({ ...ok, bundle: { state: "failed", error: "timeout" } }, 1)[0];
  assert.equal(failed.kind, "warn");
  assert.match(failed.text, /timeout/);
});

test("no location data, no traceroute, no home", () => {
  assert.deepEqual(ids(bannersFor({ ...ok, geo: { city: null } }, 1)), ["geo"]);
  assert.deepEqual(ids(bannersFor({ ...ok, traceroute_ok: false }, 1)), ["traceroute"]);
  assert.deepEqual(ids(bannersFor({ ...ok, home_set: false }, 1)), ["home"]);
});

test("no location files with automatic updates off says so instead of 'still downloading'", () => {
  const off = bannersFor({ ...ok, geo: { city: null, auto_update: false } }, 1);
  assert.equal(off[0].text, "Location data hasn't been downloaded yet. Turn on automatic updates or use Update now in GeoTrace settings.");
  assert.equal(COPY.noGeoManual, off[0].text);
  const on = bannersFor({ ...ok, geo: { city: null, auto_update: true } }, 1);
  assert.equal(on[0].text, COPY.noGeo);
  assert.equal(bannersFor({ ...ok, geo: { city: { path: "x" }, auto_update: false } }, 1).length, 0);
});
