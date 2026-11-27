import { test } from "node:test";
import assert from "node:assert/strict";
import { networkLabel } from "../../static/network.js";

test("private, loopback and link-local addresses are your network", () => {
  for (const ip of ["10.27.10.1", "192.168.1.1", "172.16.0.1", "172.31.255.1", "127.0.0.1", "169.254.1.1", "::1", "fd00::1", "fe80::1"]) {
    assert.equal(networkLabel(ip), "Your network", ip);
  }
});

test("CGNAT is the carrier network", () => {
  for (const ip of ["100.64.0.1", "100.127.255.254"]) assert.equal(networkLabel(ip), "Carrier network", ip);
});

test("public and odd inputs are not labelled", () => {
  for (const ip of ["1.1.1.1", "172.32.0.1", "100.128.0.1", "100.63.0.1", "2606:4700::1", "192.0.2.1", "198.51.100.7", "203.0.113.5", "2001:db8::1", "", null, undefined]) assert.equal(networkLabel(ip), null, String(ip));
});
