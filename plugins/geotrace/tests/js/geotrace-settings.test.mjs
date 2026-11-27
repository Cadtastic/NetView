import { test } from "node:test";
import assert from "node:assert/strict";
import { geoStatusText, bundleStatusText, canDownloadBundle, hasCoordinates, pickedHome } from "../../static/settings-model.js";
import { COPY } from "../../static/banners.js";

const fmt = (ms) => `T${ms}`;

test("geo status: nothing downloaded yet", () => {
  const t = geoStatusText({ geo: { city: null, asn: null, last_error: null, checked_ms: null } }, fmt);
  assert.equal(t.month, "Not downloaded yet");
  assert.equal(t.checked, "Not checked yet");
  assert.equal(t.error, null);
});

test("geo status: months, last check, last error", () => {
  const geo = { city: { month: "2026-11" }, asn: { month: "2026-10" }, last_error: "HTTP 404", checked_ms: 5 };
  const t = geoStatusText({ geo }, fmt);
  assert.equal(t.month, "City 2026-11, ASN 2026-10");
  assert.equal(t.checked, "Last checked T5");
  assert.equal(t.error, "Last error: HTTP 404");
});

test("geo status: one file only, and a missing status", () => {
  assert.equal(geoStatusText({ geo: { city: { month: "2026-11" }, asn: null } }, fmt).month, "City 2026-11");
  assert.equal(geoStatusText(null, fmt).month, "Not downloaded yet");
});

test("bundle status text covers every state, including not_published", () => {
  assert.equal(bundleStatusText({ bundle: { state: "not_published" } }), COPY.bundleNotPublished);
  assert.equal(bundleStatusText({ bundle: { state: "missing" } }), COPY.bundleLoading);
  assert.equal(bundleStatusText({ bundle: { state: "downloading" } }), COPY.bundleLoading);
  assert.equal(bundleStatusText({ bundle: { state: "ready", version: "1.144.0" } }), "Ready");
  assert.equal(bundleStatusText({ bundle: { state: "failed", error: "timeout" } }), "Download failed: timeout");
  assert.equal(bundleStatusText({ bundle: { state: "failed" } }), "Download failed");
  assert.equal(bundleStatusText(null), "Checking…");
});

test("download button is off for not_published, ready and downloading", () => {
  for (const s of ["not_published", "ready", "downloading"]) assert.equal(canDownloadBundle({ bundle: { state: s } }), false);
  for (const s of ["missing", "failed"]) assert.equal(canDownloadBundle({ bundle: { state: s } }), true);
  assert.equal(canDownloadBundle(null), false);
});

test("coordinates must be numbers in range", () => {
  assert.equal(hasCoordinates("40.7", "-111.9"), true);
  assert.equal(hasCoordinates("", "10"), false);
  assert.equal(hasCoordinates("91", "10"), false);
  assert.equal(hasCoordinates("10", "181"), false);
  assert.equal(hasCoordinates("abc", "1"), false);
});

test("picked values are rounded to 5 places", () => {
  assert.deepEqual(pickedHome(40.7608123456, -111.8910987654), { lat: "40.76081", lon: "-111.89110" });
});

import { requestPick, takePickRequest, savePicked, takePicked } from "../../static/pick.js";

const memory = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
};
const blocked = { getItem() { throw new Error("no"); }, setItem() { throw new Error("no"); }, removeItem() { throw new Error("no"); } };

test("a pick request is taken once", () => {
  const s = memory();
  assert.equal(takePickRequest(s), false);
  assert.equal(requestPick(s), true);
  assert.equal(takePickRequest(s), true);
  assert.equal(takePickRequest(s), false);
});

test("a picked point is taken once and bad data is ignored", () => {
  const s = memory();
  savePicked(40.5, -111.25, s);
  assert.deepEqual(takePicked(s), { lat: 40.5, lon: -111.25 });
  assert.equal(takePicked(s), null);
  s.setItem("netview.geotrace.picked", "{\"lat\":\"x\"}");
  assert.equal(takePicked(s), null);
});

test("blocked storage never throws", () => {
  assert.equal(requestPick(blocked), false);
  assert.equal(takePickRequest(blocked), false);
  assert.equal(takePicked(blocked), null);
  savePicked(1, 2, blocked);
});
