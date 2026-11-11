import { test } from "node:test";
import assert from "node:assert/strict";
import register, { makeHelpers } from "../../src/netview/plugins/builtin/inspection/static/ui.js";
import * as util from "../../src/netview/presentation/web/static/js/util.js";

// The plugin's UI module cannot import core modules, so it gets `ui.util` at registration; the tests hand it the same.
const h = makeHelpers(util);

const cert = {
  subject: "router-0100",
  subject_org: "SpaceX",
  issuer: "SpaceX Router CA",
  issuer_org: "SpaceX",
  not_after: "Jan  1 2030",
  self_signed: false,
  san: ["a.test", "b.test"],
};

const web = (items) => ({ id: "web", title: "Web interfaces", data: { items } });
const item = (over = {}) => ({
  port: 80,
  url: "http://192.0.2.10/",
  status: 200,
  reason: "OK",
  title: "Home",
  server: "nginx",
  powered_by: "",
  generator: "",
  realm: "",
  location: "",
  tls: null,
  cert: null,
  ...over,
});

function fakeUi(openPorts) {
  const slots = [];
  const calls = [];
  const ui = {
    util,
    apiBase: "/api/v1/plugins/inspection",
    apiGet: async (path) => {
      calls.push(path);
      return openPorts;
    },
    slot: (name, spec) => slots.push([name, spec]),
    requestRender: () => {},
  };
  return { ui, slots, calls };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("the web renderer escapes a page title, so a script tag shows literally", () => {
  const html = h.webHtml(web([item({ title: "<script>alert(1)</script>" })]));
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(!html.includes("<script"));
});

test("only http and https URLs become links, with target and rel set", () => {
  const html = h.webHtml(web([item({ url: "https://192.0.2.10:8443/", port: 8443 })]));
  assert.ok(html.includes('<a href="https://192.0.2.10:8443/" target="_blank" rel="noopener noreferrer">'));
  const bad = h.webHtml(web([item({ url: "javascript:alert(1)" }), item({ url: "data:text/html,<b>" }), item({ url: "//evil/x" })]));
  assert.ok(!bad.includes("<a "));
  assert.ok(!bad.includes('href="javascript'));
  assert.ok(bad.includes("javascript:alert(1)")); // shown as text
  assert.ok(!bad.includes("<b>"));
  assert.equal(h.safeUrl("HTTP://x"), true);
  assert.equal(h.safeUrl(" javascript:x"), false);
  assert.equal(h.safeUrl(""), false);
  assert.equal(h.safeUrl(null), false);
});

test("a URL with quotes cannot break out of the href", () => {
  const html = h.webHtml(web([item({ url: 'http://192.0.2.10/" onmouseover="x' })]));
  assert.ok(!html.includes('" onmouseover'));
  assert.ok(html.includes("&quot; onmouseover=&quot;x"));
});

test("web details follow the link, joined with commas and no middle dots", () => {
  const html = h.webHtml(
    web([item({ title: "Home", server: "nginx", powered_by: "PHP", generator: "WordPress", realm: "admin", location: "/login", reason: "OK" })]),
  );
  assert.ok(html.includes("200 OK, “Home”, server: nginx, powered by PHP, WordPress, login: admin, redirects to /login"));
  assert.ok(!html.includes("·"));
});

test("the web renderer shows the certificate line under a TLS page", () => {
  const html = h.webHtml(web([item({ url: "https://192.0.2.10/", tls: "TLSv1.3", cert })]));
  assert.ok(html.includes("TLSv1.3, certificate router-0100 (SpaceX), issued by SpaceX, expires Jan  1 2030, also a.test, b.test"));
});

test("the certificate line: self-signed, no subject and no TLS", () => {
  assert.equal(
    h.certLine({ ...cert, self_signed: true, san: [] }, "TLSv1.2"),
    "TLS TLSv1.2, certificate router-0100 (SpaceX), issued by SpaceX, self-signed, expires Jan  1 2030",
  );
  assert.equal(h.certLine({ subject: "", issuer: "", not_after: "" }, "TLSv1"), "TLS TLSv1, certificate (no name), issued by ?, expires ?");
  assert.equal(h.certLine(null, "TLSv1.3"), "TLS TLSv1.3");
  assert.equal(h.certLine(null, null), "");
  assert.equal(h.certLine({ subject: null }, null), "");
});

const ports = (open, over = {}) => ({
  id: "ports",
  title: "Open TCP ports",
  data: { ports_spec: "top", scanned: 2, open, refused: 1, no_answer: 0, duration_s: 0.4, ...over },
});

test("the ports renderer: the first line, then Port, Usually and What answered", () => {
  const html = h.portsHtml(
    ports([
      { port: 22, name: "SSH", banner: "SSH-2.0-OpenSSH_9.6" },
      { port: 80, name: "HTTP", http: { scheme: "http", url: "http://x/", status: 200, title: "Home", server: "nginx", cert: null, tls: null } },
    ]),
  );
  assert.ok(html.includes("2 TCP ports in 0.4 s: 2 open, 1 refused, 0 no answer"));
  assert.ok(html.includes("<th>Usually</th>") && html.includes("<th>What answered</th>"));
  assert.ok(html.includes('<span class="mono">SSH-2.0-OpenSSH_9.6</span>'));
  assert.ok(html.includes("HTTP 200, “Home”, nginx"));
  assert.ok(!html.includes("·"));
});

test("the ports renderer escapes banners, titles and certificate fields", () => {
  const html = h.portsHtml(
    ports([
      { port: 23, name: "Telnet", banner: "<img src=x onerror=alert(1)>" },
      {
        port: 443,
        name: "HTTPS",
        http: { scheme: "https", status: 200, title: "<b>t</b>", server: "<i>s</i>", tls: "TLSv1.3", cert: { ...cert, subject: "<u>cn</u>" } },
      },
    ]),
  );
  assert.ok(!/<(img|b|i|u)[ >]/.test(html));
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
  assert.ok(html.includes("&lt;u&gt;cn&lt;/u&gt;"));
});

test("the ports renderer: a TLS-only port, a silent port, a skipped port and no open ports", () => {
  const html = h.portsHtml(
    ports([
      { port: 3389, name: "RDP", http: { scheme: "https", status: null, tls: "TLSv1.2", cert } },
      { port: 5000, name: "UPnP/NAS/Flask" },
      { port: 6000, name: "X11", skipped: true },
    ]),
  );
  assert.ok(html.includes("HTTPS (TLS only, no HTTP reply)"));
  assert.ok(html.includes("Open, but sends no greeting and doesn't speak HTTP"));
  assert.ok(html.includes("Open, not analyzed"));
  const none = h.portsHtml(ports([], { refused: 0, no_answer: 2 }));
  assert.ok(none.includes("None of the scanned ports are open."));
  assert.ok(!none.includes("<table"));
});

test("the summary renderer lists the hints, or says there is no clear match", () => {
  const some = h.summaryHtml({ id: "summary", title: "What it probably is", data: { hints: ["Plex Media Server.", "<b>x</b>"] } });
  assert.ok(some.includes("<h3>What it probably is</h3>"));
  assert.ok(some.includes('<ul class="hints"><li>Plex Media Server.</li><li>&lt;b&gt;x&lt;/b&gt;</li></ul>'));
  const none = h.summaryHtml({ id: "summary", title: "What it probably is", data: { hints: [] } });
  assert.ok(none.includes("No clear match."));
  assert.ok(!none.includes("<ul"));
});

test("the identity renderer is a key and value list", () => {
  const html = h.identityHtml({
    id: "identity",
    title: "Identity",
    data: {
      mac: "a8:bb:cc:00:00:01",
      vendor: "Roku, Inc",
      rtt_ms: 2.5,
      ttl: 64,
      os_hint: "Linux/Apple/Android/embedded",
      names: ["tv.lan", "<i>x</i>"],
      netbios: { name: "ROKU", workgroup: "WORKGROUP" },
    },
  });
  assert.ok(html.includes('<dl class="kv">'));
  assert.ok(html.includes("<dt>MAC</dt><dd>a8:bb:cc:00:00:01, Roku, Inc</dd>"));
  assert.ok(html.includes("<dt>Ping</dt><dd>2.5 ms, TTL 64 (Linux/Apple/Android/embedded)</dd>"));
  assert.ok(html.includes("<dt>Names</dt><dd>tv.lan, &lt;i&gt;x&lt;/i&gt;</dd>"));
  assert.ok(html.includes("<dt>NetBIOS</dt><dd>ROKU, workgroup WORKGROUP</dd>"));
  const bare = h.identityHtml({ id: "identity", title: "Identity", data: { mac: null, vendor: "", rtt_ms: null, ttl: null, names: [], netbios: null } });
  assert.ok(bare.includes("unknown (not on this subnet?)"));
  assert.ok(bare.includes("<dd>no reply</dd>"));
  assert.ok(bare.includes("none (reverse DNS, NetBIOS, mDNS and UPnP all silent)"));
  assert.ok(!bare.includes("NetBIOS</dt>"));
});

test("the mdns, upnp and discovery renderers", () => {
  const mdns = h.mdnsHtml({
    id: "mdns",
    title: "mDNS and Bonjour",
    data: { hostname: "den-tv.local", services: [{ type: "_airplay._tcp.local", instances: ["Den <TV>"], txt: { model: "OLED", manufacturer: "LG" } }] },
  });
  assert.ok(mdns.includes("<dt>Host name</dt><dd>den-tv.local</dd>"));
  assert.ok(mdns.includes("Den &lt;TV&gt;"));
  assert.ok(mdns.includes("model=OLED  manufacturer=LG"));
  const upnp = h.upnpHtml({
    id: "upnp",
    title: "UPnP and SSDP",
    data: { entries: [{ friendlyName: "<b>Roku</b>", manufacturer: "Roku", modelName: "Ultra", server: "Roku/9", location: "http://192.0.2.10:8060/d.xml" }, {}] },
  });
  assert.ok(upnp.includes("<dt>&lt;b&gt;Roku&lt;/b&gt;</dt>"));
  assert.ok(upnp.includes("<dd>Roku, Ultra"));
  assert.ok(upnp.includes("Roku/9, http://192.0.2.10:8060/d.xml"));
  assert.ok(upnp.includes("<dt>Device</dt>"));
  assert.ok(!upnp.includes("·"));
  const none = h.discoveryHtml({ id: "discovery", title: "Discovery protocols", data: {} });
  assert.ok(none.includes("<h3>Discovery protocols</h3>"));
  assert.ok(none.includes("No answer to mDNS, UPnP/SSDP or NetBIOS."));
});

test("the open ports column: blank when never inspected, none found, or the first three and a count", () => {
  assert.equal(h.portsCell(undefined), "");
  assert.equal(h.portsCell(null), "");
  assert.equal(h.portsCell([]), '<div class="scope" title="">no open ports found</div>');
  const five = [22, 80, 443, 8080, 9100].map((port, i) => ({ port, name: ["SSH", "HTTP", "HTTPS", "", "Printer"][i] }));
  const cell = h.portsCell(five);
  assert.ok(cell.includes("open: 22 SSH, 80 HTTP, 443 HTTPS +2 more"));
  assert.ok(cell.includes('title="22 SSH, 80 HTTP, 443 HTTPS, 8080, 9100 Printer"'));
  assert.ok(!h.portsCell(five.slice(0, 3)).includes("more"));
  assert.ok(!cell.includes("·"));
  assert.ok(h.portsCell([{ port: 1, name: "<b>" }]).includes("&lt;b&gt;"));
  assert.equal(h.portsCount([]), 0);
  assert.equal(h.portsCount(undefined), -1);
  assert.equal(h.portsCount(five), 5);
});

test("registration: one renderer per section and the open ports column, fetched from /open-ports", async () => {
  const f = fakeUi({ "192.0.2.10": [{ port: 22, name: "SSH" }], "192.0.2.11": [] });
  register(f.ui);
  await tick();
  const by = (name) => f.slots.filter(([n]) => n === name).map(([, s]) => s);
  assert.deepEqual(
    by("report.section").map((s) => s.section),
    ["summary", "identity", "web", "ports", "mdns", "upnp", "discovery"],
  );
  assert.deepEqual(f.calls, ["/api/v1/plugins/inspection/open-ports"]);
  const [col] = by("devices.column");
  assert.equal(col.id, "ports");
  assert.equal(col.label, "Open ports");
  const state = {};
  assert.ok(col.render({ ip: "192.0.2.10" }, state).includes("open: 22 SSH"));
  assert.ok(col.render({ ip: "192.0.2.11" }, state).includes("no open ports found"));
  assert.equal(col.render({ ip: "192.0.2.12" }, state), "");
  assert.equal(col.sortKey({ ip: "192.0.2.10" }, state), 1);
  assert.equal(col.sortKey({ ip: "192.0.2.12" }, state), -1);
});

test("the open ports are refetched once per state change, not once per render", async () => {
  const f = fakeUi({});
  register(f.ui);
  await tick();
  const [col] = f.slots.filter(([n]) => n === "devices.column").map(([, s]) => s);
  const a = { n: 1 };
  col.render({ ip: "192.0.2.10" }, a);
  col.render({ ip: "192.0.2.11" }, a);
  col.render({ ip: "192.0.2.10" }, a);
  await tick();
  assert.equal(f.calls.length, 2); // the first fetch at registration, one for the new state
  col.render({ ip: "192.0.2.10" }, { n: 2 });
  await tick();
  assert.equal(f.calls.length, 3);
});

test("a section draws into its element through the renderer", async () => {
  const f = fakeUi({});
  register(f.ui);
  const spec = f.slots.find(([n, s]) => n === "report.section" && s.section === "web")[1];
  const el = { innerHTML: "" };
  spec.draw(el, web([item({ title: "<script>x</script>" })]), {});
  assert.ok(el.innerHTML.includes("<h3>Web interfaces</h3>"));
  assert.ok(el.innerHTML.includes("&lt;script&gt;x&lt;/script&gt;"));
});
