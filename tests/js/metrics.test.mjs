import { test } from "node:test";
import assert from "node:assert/strict";
import { limitFor, mergeMetrics, createMetricsClient, newestTime } from "../../src/netview/presentation/web/static/js/metrics.js";

const pts = (from, n, v = 1) => Array.from({ length: n }, (_, i) => [from + i * 5000, v]);

test("limitFor keeps 720 samples for the long series and 120 for the rest", () => {
  for (const name of ["health.gateway", "health.internet", "health.dns.1.1.1.1", "local.down_bps", "local.up_bps"]) {
    assert.equal(limitFor(name), 720, name);
  }
  for (const name of ["health.device.aa:bb", "traffic.down.192.168.1.5", "other.thing"]) {
    assert.equal(limitFor(name), 120, name);
  }
});

test("mergeMetrics adds no duplicates when a delta overlaps the cache", () => {
  const cache = { "health.gateway": [[1000, 1], [6000, 2]] };
  mergeMetrics(cache, { "health.gateway": [[1000, 1], [6000, 2], [11000, 3]], "traffic.down.x": [[1000, 5]] });
  assert.deepEqual(cache["health.gateway"], [[1000, 1], [6000, 2], [11000, 3]]);
  assert.deepEqual(cache["traffic.down.x"], [[1000, 5]]);
  mergeMetrics(cache, { "health.gateway": [[11000, 3]] });
  assert.equal(cache["health.gateway"].length, 3);
});

test("mergeMetrics trims each series to its own limit, keeping the newest", () => {
  const cache = {};
  mergeMetrics(cache, { "health.device.x": pts(0, 200), "health.gateway": pts(0, 800) });
  assert.equal(cache["health.device.x"].length, 120);
  assert.equal(cache["health.gateway"].length, 720);
  assert.equal(cache["health.device.x"].at(-1)[0], 199 * 5000);
  assert.equal(cache["health.gateway"][0][0], 80 * 5000);
});

test("mergeMetrics keeps null samples and returns the same cache object", () => {
  const cache = {};
  assert.equal(mergeMetrics(cache, { a: [[1, null], [2, 3]] }), cache);
  assert.deepEqual(cache.a, [[1, null], [2, 3]]);
  assert.doesNotThrow(() => mergeMetrics(cache, null));
});

test("the client asks only for what is newer than the newest sample", async () => {
  const urls = [];
  const replies = [
    { now_ms: 1, series: { "health.gateway": [[1000, 1], [6000, 2]] } },
    { now_ms: 2, series: { "health.gateway": [[11000, 3]], "traffic.down.x": [[11000, 9]] } },
  ];
  const client = createMetricsClient(async (url) => {
    urls.push(url);
    return replies.shift();
  });
  await client.refresh();
  const cache = await client.refresh();
  assert.deepEqual(urls, ["/api/v1/metrics?since_ms=0", "/api/v1/metrics?since_ms=6000"]);
  assert.equal(cache, client.cache);
  assert.equal(newestTime(cache), 11000);
  assert.equal(cache["health.gateway"].length, 3);
});

test("a failed fetch throws and keeps the old cache", async () => {
  let fail = false;
  const client = createMetricsClient(async () => {
    if (fail) throw new Error("down");
    return { now_ms: 1, series: { a: [[1, 1]] } };
  });
  await client.refresh();
  fail = true;
  await assert.rejects(client.refresh(), /down/);
  assert.deepEqual(client.cache.a, [[1, 1]]);
});
