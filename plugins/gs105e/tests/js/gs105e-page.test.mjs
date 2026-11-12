import { test } from "node:test";
import assert from "node:assert/strict";
import { configSectionsHtml, isPaused, loadView, localPauseEnd, pauseExpired, pauseLabel, pollButtonState, statusBanner } from "../../static/page.js";
import { esc } from "../../../../src/netview/presentation/web/static/js/util.js";

const base = (extra = {}) => ({
  configured: true, host: "h", reachable: true, polling: false, login: "ok", paused_until_ms: null, pause_reason: null,
  last_poll_ms: 1, errors: {}, switch: { name: "sw", firmware: "V1.6.0.11", firmware_tested: true },
  ports: { total: 5, up: 1 }, throughput_bps: { in: 0, out: 0 }, ...extra,
});

const config = {
  vlans: { mode: "off", vlan_ids: [1], shown: null, pvids: [] },
  qos: { mode: "dot1p", rate_limits: [{ port: 1, ingress_kbps: 512, egress_kbps: null }], storm_control: true },
  igmp: { enabled: false, vlan: null, validate_v3_header: false, block_unknown: false, router_port: null },
  mirror: { enabled: true, destination: 5, sources: [1, 2] },
  management: { mode: "web", tftp: false, access_list: [["10.0.0.0", "255.0.0.0"]], power_saving: true, loop_detection: false },
};

test("pauseLabel counts the minutes left to the local end of the pause", () => {
  assert.equal(pauseLabel(1_000_000 + 14 * 60_000 - 5_000, 1_000_000), "Paused for 14 min");
  assert.equal(pauseLabel(null, 1_000_000), "");
  assert.equal(pauseLabel(1_000_000, 1_000_000), "");
});

test("the pause runs on server time: paused_until_ms in the browser's past does not matter", () => {
  const now = 5_000_000;
  const s = base({ login: "paused", paused_until_ms: now - 3_600_000, pause_remaining_ms: 5 * 60_000, pause_reason: "user" });
  const end = localPauseEnd(s, now);
  assert.equal(end, now + 5 * 60_000);
  assert.equal(pauseLabel(end, now), "Paused for 5 min");
  assert.equal(pauseExpired(end, now), false);
  assert.equal(pauseExpired(end, end), true);
  assert.equal(localPauseEnd(base(), now), null);
  assert.equal(localPauseEnd(null, now), null);
  assert.equal(pauseExpired(null, now), false);
});

test("statusBanner covers unreachable, login failed, paused and untested firmware", () => {
  assert.equal(statusBanner(base()), null);
  assert.equal(statusBanner(base({ reachable: false })).cls, "bad");
  const failed = statusBanner(base({ login: "failed" }));
  assert.equal(failed.cls, "bad");
  assert.ok(/login/i.test(failed.text));
  const other = statusBanner(base({ login: "paused", paused_until_ms: 5, pause_reason: "another_login" }));
  assert.equal(other.cls, "warn");
  assert.ok(other.text.includes("Paused: another login"));
  assert.ok(statusBanner(base({ login: "paused", paused_until_ms: 5, pause_reason: "user" })).text.includes("Paused"));
  const fw = statusBanner(base({ switch: { firmware: "V9", firmware_tested: false } }));
  assert.equal(fw.cls, "warn");
  assert.ok(fw.text.includes("V9"));
  assert.equal(statusBanner(null), null);
});

test("pollButtonState disables while polling or requesting", () => {
  assert.equal(pollButtonState(base(), false).disabled, false);
  assert.equal(pollButtonState(base({ polling: true }), false).disabled, true);
  assert.equal(pollButtonState(base(), true).label, "Polling…");
});

test("configSectionsHtml: VLANs off, 802.1p/DSCP, mirroring, and escaping", () => {
  const html = configSectionsHtml(config, esc);
  assert.ok(html.includes("VLANs off"));
  assert.ok(html.includes("802.1p/DSCP"));
  assert.ok(html.includes("512"));
  assert.ok(html.includes("10.0.0.0"));
  const withDesc = configSectionsHtml(
    { ...config, vlans: { mode: "basic_8021q", vlan_ids: [1, 20], shown: { vid: 1, members: ["U", "T", "", "", ""] }, pvids: [[1, 1]] } },
    esc,
    [{ port: 1, description: "<script>x</script>" }],
  );
  assert.ok(!withDesc.includes("<script>"));
  assert.ok(withDesc.includes("&lt;script&gt;"));
  assert.ok(!withDesc.includes("VLANs off"));
  assert.ok(configSectionsHtml(null, esc).includes("not read yet"));
});

test("loadView survives missing localStorage", () => {
  assert.equal(loadView(), "status");
});

test("Switch section shows the IP settings, escaped", () => {
  const summary = base({ switch: { name: "<i>sw</i>", dhcp: false, ip: "192.0.2.1", mask: "255.255.255.0", gateway: "192.0.2.2" } });
  const html = configSectionsHtml(config, esc, [], summary);
  for (const t of ["static", "192.0.2.1", "255.255.255.0", "192.0.2.2"]) assert.ok(html.includes(t), t);
  assert.ok(!html.includes("<i>sw</i>"));
  assert.ok(configSectionsHtml(config, esc, [], base({ switch: { dhcp: true } })).includes("DHCP"));
});

test("isPaused follows paused_until_ms, not the login state", () => {
  assert.equal(isPaused(base()), false);
  assert.equal(isPaused(null), false);
  assert.equal(isPaused(base({ login: "paused", paused_until_ms: 5 })), true);
  // login failed takes precedence in `login`, but the pause still runs
  assert.equal(isPaused(base({ login: "failed", paused_until_ms: 5 })), true);
});
