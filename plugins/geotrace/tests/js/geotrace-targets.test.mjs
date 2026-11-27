import { test } from "node:test";
import assert from "node:assert/strict";
import { statusKind, checkAddress, routeSubtitle, agoText, fmtRtt, targetLine, formProblems } from "../../static/targets.js";

const last = (o = {}) => ({ trace_id: 1, started_ms: 0, status: "done", rtt_ms: 40, loss_pct: 0, hop_count: 8, ...o });
const target = (o = {}) => ({ id: 1, name: "n", address: "a.com", family: "ipv4", interval_min: 15, enabled: true, last: last(), note: "", ...o });

test("status dot: no trace yet is idle", () => {
  assert.equal(statusKind(target({ last: null })), "idle");
});

test("status dot: failed or not reached is bad", () => {
  assert.equal(statusKind(target({ last: last({ status: "failed" }) })), "bad");
  assert.equal(statusKind(target({ last: last({ status: "not_reached" }) })), "bad");
  assert.equal(statusKind(target({ last: last({ status: "failed", loss_pct: 0 }), note: "slower" })), "bad");
});

test("status dot: loss or a slower note is warn, otherwise ok", () => {
  assert.equal(statusKind(target({ last: last({ loss_pct: 10 }) })), "warn");
  assert.equal(statusKind(target({ note: "58 ms, slower than usual" })), "warn");
  assert.equal(statusKind(target({ note: "same route for 3 days" })), "ok");
  assert.equal(statusKind(target()), "ok");
});

test("address check mirrors the server", () => {
  assert.equal(checkAddress("netflix.com"), true);
  assert.equal(checkAddress("https://netflix.com/"), false);
  assert.equal(checkAddress("netflix.com\n"), false);
  assert.equal(checkAddress("8.8.8.8"), true);
  assert.equal(checkAddress("2001:4860:4860::8888"), true);
  assert.equal(checkAddress("fe80::1%eth0"), false);
  assert.equal(checkAddress("host:80"), false);
  assert.equal(checkAddress("a b.com"), false);
  assert.equal(checkAddress("-a.com"), false);
  assert.equal(checkAddress("a-.com"), false);
  assert.equal(checkAddress(""), false);
  assert.equal(checkAddress("a".repeat(63) + ".com"), true);
  assert.equal(checkAddress("a".repeat(64) + ".com"), false);
  assert.equal(checkAddress(("a".repeat(60) + ".").repeat(5) + "com"), false);
});

test("form problems name the field", () => {
  assert.deepEqual(formProblems({ name: "x", address: "netflix.com" }), []);
  assert.match(formProblems({ name: " ", address: "netflix.com" })[0], /name/i);
  assert.match(formProblems({ name: "x", address: "https://netflix.com/" })[0], /address/i);
  assert.match(formProblems({ name: "x".repeat(101), address: "a.com" })[0], /100/);
});

test("route subtitle", () => {
  const now = 10 * 60 * 1000;
  const s = routeSubtitle(last({ started_ms: now - 2 * 60 * 1000, hop_count: 8, rtt_ms: 58.4, loss_pct: 0 }), now);
  assert.equal(s, "8 hops · traced 2 min ago · 58 ms · loss 0%");
  assert.equal(routeSubtitle(last({ hop_count: 1, rtt_ms: null, loss_pct: null, started_ms: now }), now), "1 hop · traced just now · – · loss –");
  assert.equal(routeSubtitle(null, now), "No trace yet");
});

test("ago text and rtt text", () => {
  assert.equal(agoText(0, 30_000), "just now");
  assert.equal(agoText(0, 90_000), "2 min ago");
  assert.equal(agoText(0, 3 * 3600_000), "3 h ago");
  assert.equal(agoText(0, 3 * 86400_000), "3 d ago");
  assert.equal(fmtRtt(null), "–");
  assert.equal(fmtRtt(4.26), "4.3 ms");
  assert.equal(fmtRtt(58.4), "58 ms");
});

test("list line", () => {
  assert.equal(targetLine(target({ note: "route changed" })), "every 15 min · route changed");
  assert.equal(targetLine(target({ enabled: false })), "paused");
  assert.equal(targetLine(target()), "every 15 min");
});
