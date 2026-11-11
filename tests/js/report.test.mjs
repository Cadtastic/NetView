import { test } from "node:test";
import assert from "node:assert/strict";
import { matchSection, genericSectionHtml, runningText, failureText } from "../../src/netview/presentation/web/static/js/report/dialog.js";

test("matchSection finds a renderer by plugin id and section id", () => {
  const specs = [
    { pluginId: "inspection", section: "ports", id: "a" },
    { pluginId: "other", section: "ports", id: "b" },
    { pluginId: "inspection", section: "web", id: "c" },
  ];
  assert.equal(matchSection(specs, { plugin_id: "other", id: "ports" }).id, "b");
  assert.equal(matchSection(specs, { plugin_id: "inspection", id: "web" }).id, "c");
  assert.equal(matchSection(specs, { plugin_id: "inspection", id: "missing" }), null);
  assert.equal(matchSection([], { plugin_id: "x", id: "y" }), null);
});

test("the generic renderer escapes markup from a device", () => {
  const html = genericSectionHtml({
    plugin_id: "inspection",
    id: "upnp",
    title: "UPnP <script>alert(1)</script>",
    data: { friendlyName: "<script>alert(2)</script>", "<b>key</b>": "x" },
  });
  assert.ok(!html.includes("<script"));
  assert.ok(!html.includes("<b>"));
  assert.ok(html.includes("&lt;script&gt;alert(2)&lt;/script&gt;"));
  assert.ok(html.startsWith("<h3>"));
});

test("the generic renderer shows scalars only, and never the text field", () => {
  const html = genericSectionHtml({
    title: "Web",
    data: { status: 200, secure: true, none: null, nested: { a: 1 }, list: [1, 2], text: "summary line" },
  });
  assert.ok(html.includes("<dt>status</dt><dd>200</dd>"));
  assert.ok(html.includes("<dd>true</dd>"));
  assert.ok(html.includes("<dd>–</dd>"));
  assert.ok(!html.includes("nested"));
  assert.ok(!html.includes("list"));
  assert.ok(!html.includes("summary line"));
});

test("a section with an error says it failed, with the error escaped", () => {
  const html = genericSectionHtml({ title: "Certificates", data: {}, error: "bad <i>cert</i>" });
  assert.ok(html.includes("This section failed: bad &lt;i&gt;cert&lt;/i&gt;"));
  assert.ok(!html.includes("<dl"));
});

test("a section with no scalar data is just its heading", () => {
  assert.equal(genericSectionHtml({ title: "Empty", data: { text: "x" } }), "<h3>Empty</h3>");
  assert.equal(genericSectionHtml({ title: "None" }), "<h3>None</h3>");
});

test("running and failure texts", () => {
  assert.equal(
    runningText("192.168.1.5", "top"),
    "Inspecting 192.168.1.5: about 1,100 TCP ports, web pages, certificates, mDNS, NetBIOS and UPnP, about 10 seconds…",
  );
  assert.ok(runningText("192.168.1.5", "all").includes("all 65,535 TCP ports"));
  assert.ok(runningText("192.168.1.5", "all").includes("about a minute"));
  assert.equal(failureText({ status: 409, message: "no enabled plugin provides inspection" }), "No inspection plugin is turned on.");
  assert.equal(failureText({ status: 500, message: "boom" }), "Inspection failed: boom");
  assert.ok(!runningText("1.2.3.4", "top").includes("·"));
});
