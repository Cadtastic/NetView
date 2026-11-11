import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  buildCommand, readField, buildTypeText, defaultShell, appRows, renderCommands, LIMITED_403, COPY_BLOCKED,
} from "../../static/commands.js";
import { READ, CONTROL, KEYS, APPS, RECIPES } from "../../static/cheatsheet-data.js";

const U = "http://192.168.1.60:8060";

test("POST commands per shell", () => {
  assert.equal(buildCommand("ps", "POST", U + "/keypress/Home"), '(Invoke-WebRequest "http://192.168.1.60:8060/keypress/Home" -Method Post -UseBasicParsing).StatusCode');
  assert.equal(buildCommand("curl", "POST", U + "/keypress/Home"), 'curl -X POST "http://192.168.1.60:8060/keypress/Home"');
  assert.equal(buildCommand("cmd", "POST", U + "/keypress/Home"), 'curl -X POST "http://192.168.1.60:8060/keypress/Home"');
});

test("GET with and without output file per shell", () => {
  const u = U + "/query/device-info";
  assert.equal(buildCommand("ps", "GET", u), '(Invoke-WebRequest "http://192.168.1.60:8060/query/device-info" -UseBasicParsing).Content');
  assert.equal(buildCommand("ps", "GET", u, "icon.png"), 'Invoke-WebRequest "http://192.168.1.60:8060/query/device-info" -OutFile icon.png -UseBasicParsing');
  for (const sh of ["curl", "cmd"]) {
    assert.equal(buildCommand(sh, "GET", u), 'curl "http://192.168.1.60:8060/query/device-info"');
    assert.equal(buildCommand(sh, "GET", u, "icon.png"), 'curl -o icon.png "http://192.168.1.60:8060/query/device-info"');
  }
});

test("readField per shell", () => {
  const u = U + "/query/device-info";
  assert.equal(readField("curl", u, "power-mode"), 'curl -s "http://192.168.1.60:8060/query/device-info" | grep -o "<power-mode[ >][^<]*" | sed "s/.*>//"');
  assert.equal(readField("cmd", u, "power-mode"), 'curl -s "http://192.168.1.60:8060/query/device-info" | findstr /c:"<power-mode"');
  assert.equal(readField("ps", u, "power-mode"), '(Select-Xml -Content (Invoke-WebRequest "http://192.168.1.60:8060/query/device-info" -UseBasicParsing).Content -XPath "//power-mode").Node.InnerText');
});

test("data matches the reference key groups and app ids", () => {
  assert.equal(KEYS.length, 8);
  assert.ok(KEYS.some((g) => g.g === "Antenna channels"));
  assert.deepEqual(APPS.find((a) => a[0] === "Netflix"), ["Netflix", "12"]);
  assert.equal(READ.length, 8);
  assert.equal(CONTROL.length, 9);
  assert.equal(RECIPES.length, 8);
  assert.deepEqual(RECIPES[0].read, ["/query/device-info", "power-mode"]);
});

// Run the reference file's own build()/readField() and compare, plus its data arrays.
const refPath = fileURLToPath(new URL("../../../../docs/superpowers/reference/roku-ecp-cheat-sheet.html", import.meta.url));
const ref = readFileSync(refPath, "utf8");
const slice = (from, to) => ref.slice(ref.indexOf(from), ref.indexOf(to, ref.indexOf(from)));
const refCode = slice("function build(method, path, out)", "var READ = [");
const dataCode = slice("var READ = [", "var toastEl");
const load = (shell) =>
  new Function("state", `function base(){return "${U}";}
${refCode}
${dataCode}
return {build, readField, READ, CONTROL, KEYS, APPS, RECIPES};`)({ shell });

test("builders are byte-equal to the reference for every shell", () => {
  for (const shell of ["ps", "cmd", "curl"]) {
    const h = load(shell);
    for (const [m, p, out] of [["GET", "/query/apps"], ["GET", "/query/icon/2285", "icon.png"], ["POST", "/launch/12?contentId=1&mediaType=series"]]) {
      assert.equal(buildCommand(shell, m, U + p, out), h.build(m, p, out));
    }
    assert.equal(readField(shell, U + "/query/active-app", "app"), h.readField(U, "/query/active-app", "app"));
  }
});

test("data and recipe commands are equal to the reference", () => {
  const h = load("curl");
  assert.deepEqual(JSON.parse(JSON.stringify(READ)), JSON.parse(JSON.stringify(h.READ)));
  assert.deepEqual(JSON.parse(JSON.stringify(CONTROL)), JSON.parse(JSON.stringify(h.CONTROL)));
  assert.deepEqual(KEYS, h.KEYS);
  assert.deepEqual(APPS, h.APPS);
  assert.deepEqual(RECIPES.map((r) => r.t), h.RECIPES.map((r) => r.t));
  for (const shell of ["ps", "cmd", "curl"]) {
    const ref2 = load(shell);
    ref2.RECIPES.forEach((r, i) => {
      const mine = RECIPES[i];
      const want = r.p ? ref2.build(r.m, r.p) : r.f(U);
      const got = mine.read ? readField(shell, U + mine.read[0], mine.read[1]) : buildCommand(shell, mine.m, U + mine.p);
      assert.equal(got, want);
    });
  }
});

test("type-text builder: one Lit_ line per character, URL-encoded", () => {
  assert.equal(buildTypeText("cmd", U, "a b'"), [
    'curl -s -X POST "http://192.168.1.60:8060/keypress/Lit_a"',
    'curl -s -X POST "http://192.168.1.60:8060/keypress/Lit_%20"',
    'curl -s -X POST "http://192.168.1.60:8060/keypress/Lit_b"',
    'curl -s -X POST "http://192.168.1.60:8060/keypress/Lit_%27"',
  ].join("\n"));
  assert.equal(buildTypeText("curl", U, "hi!"), 'for c in h i %21; do\n  curl -s -X POST "http://192.168.1.60:8060/keypress/Lit_$c"\ndone');
  assert.ok(buildTypeText("ps", U, "it's").startsWith("'it''s'.ToCharArray() | ForEach-Object {"));
  assert.equal(buildTypeText("ps", U, ""), "# Enter some text above");
  assert.equal(buildTypeText("cmd", U, ""), "rem Enter some text above");
});

test("default shell follows the platform", () => {
  assert.equal(defaultShell("Win32"), "ps");
  assert.equal(defaultShell("MacIntel"), "curl");
  assert.equal(defaultShell("Linux x86_64"), "curl");
  assert.equal(defaultShell(undefined), "curl");
});

function fakeEl() {
  return { innerHTML: "", addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const tv = (over = {}, status = {}) => ({ id: "a", ip: "192.168.1.60", title: "Den <b>TV</b>", tv: true, status: { reachable: true, mode: "default", ...status }, ...over });

test("view targets the selected TV and escapes its name", () => {
  const el = fakeEl();
  renderCommands(el, tv(), { shell: "curl" });
  assert.match(el.innerHTML, /Every command targets <b>Den &lt;b&gt;TV&lt;\/b&gt;<\/b> at <b>192\.168\.1\.60:8060<\/b>/);
  assert.ok(el.innerHTML.includes('curl -X POST &quot;http://192.168.1.60:8060/keypress/Home&quot;'));
  assert.ok(!el.innerHTML.includes("data-limited"));
  for (const id of ["recipes", "read", "control", "keys", "apps", "access", "errors"]) assert.ok(el.innerHTML.includes(`id="rk-${id}"`), id);
});

test("limited TV shows the 403 callout", () => {
  const el = fakeEl();
  renderCommands(el, tv({}, { mode: "limited" }), { shell: "ps" });
  assert.ok(el.innerHTML.includes("data-limited"));
  assert.ok(el.innerHTML.includes(LIMITED_403.replace(/'/g, "&#39;")));
});

test("hostile app ids never reach a copy-paste command", () => {
  const bad = ["1$(curl x|sh)", '1";calc;"', "tvinput.hdmi9", "12\n", ""];
  const apps = [{ id: "12", name: "Netflix" }, ...bad.map((id) => ({ id, name: "Evil" }))];
  assert.deepEqual(appRows(tv({}, { apps })).rows, [["Netflix", "12"]]);
  const el = fakeEl();
  renderCommands(el, tv({}, { apps }), { shell: "curl" });
  assert.ok(!el.innerHTML.includes("curl x"));
  assert.ok(!el.innerHTML.includes("calc"));
});

test("app ids use the TV's own apps when it listed them", () => {
  assert.equal(appRows(tv()).known, false);
  assert.equal(appRows(tv()).rows, APPS);
  const own = appRows(tv({}, { apps: [{ id: "12", name: "Netflix" }, { id: "tvinput.hdmi1", name: "HDMI 1", type: "tvin" }, { id: 99, name: "<Mine>" }] }));
  assert.equal(own.known, true);
  assert.deepEqual(own.rows, [["Netflix", "12"], ["<Mine>", "99"]]);
  const el = fakeEl();
  renderCommands(el, tv({}, { apps: [{ id: "99", name: "<Mine>" }] }), { shell: "curl" });
  assert.ok(el.innerHTML.includes("&lt;Mine&gt;"));
  assert.ok(!el.innerHTML.includes("<Mine>"));
});

test("non-TV Rokus do not get TV-only rows", () => {
  const el = fakeEl();
  renderCommands(el, tv({ tv: false }), { shell: "curl" });
  assert.ok(!el.innerHTML.includes("tv-channels"));
  assert.ok(!el.innerHTML.includes("InputHDMI2"));
  const el2 = fakeEl();
  renderCommands(el2, tv(), { shell: "curl" });
  assert.ok(el2.innerHTML.includes("tv-channels"));
});

test("copy-blocked wording is exact", () => {
  assert.equal(COPY_BLOCKED, "Copy is blocked here. The command is selected; press Ctrl+C.");
});
