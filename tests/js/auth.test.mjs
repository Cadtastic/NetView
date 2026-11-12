import { test } from "node:test";
import assert from "node:assert/strict";
import { accountMenuHtml, createAuth, safeNext as safeNextRaw } from "../../src/netview/presentation/web/static/js/auth.js";
import { loginUrl } from "../../src/netview/presentation/web/static/js/api.js";

const safeNext = (raw, origin) => safeNextRaw(raw, origin);

const ORIGIN = "https://netview.corp.local:8765";

test("keeps NetView paths", () => {
  assert.equal(safeNext("/", ORIGIN), "/");
  assert.equal(safeNext("/#devices", ORIGIN), "/#devices");
  assert.equal(safeNext("/#gsm7248?port=1%2F0%2F5", ORIGIN), "/#gsm7248?port=1%2F0%2F5");
  assert.equal(safeNext("/docs?x=1", ORIGIN), "/docs?x=1");
});

const evil = [
  "//evil.example",
  "///evil.example",
  "/\\evil.example",
  "/\\/evil.example",
  "/\t/evil.example",
  "/\n/evil.example",
  "/\r\n/evil.example",
  " //evil.example",
  "https://evil.example",
  "https:evil.example",
  "http://netview.corp.local:8765/", // other scheme = other origin
  "javascript:alert(1)",
  "data:text/html,hi",
  "\\\\evil.example",
  "/.//evil.example", // dot segments collapse to "//evil.example"
  "/a/..//evil.example",
  "/%2e//evil.example",
  "/./\\evil.example",
  "/%2F%2Fevil.example", // stays a same-origin path after parsing; checked below
  "",
  null,
  undefined,
  42,
];

for (const raw of evil.filter((r) => r !== "/%2F%2Fevil.example")) {
  test(`rejects ${JSON.stringify(raw)}`, () => assert.equal(safeNext(raw, ORIGIN), "/"));
}

test("encoded slashes stay a harmless same-origin path", () => {
  const out = safeNext("/%2F%2Fevil.example", ORIGIN);
  assert.equal(new URL(out, ORIGIN).origin, ORIGIN);
});

test("does not loop back to login or setup", () => {
  assert.equal(safeNext("/login?next=/x", ORIGIN), "/");
  assert.equal(safeNext("/setup", ORIGIN), "/");
});

test("whatever it returns, following it stays on NetView", () => {
  for (const raw of evil) {
    const out = safeNext(raw, ORIGIN);
    assert.equal(new URL(out, ORIGIN).origin, ORIGIN, String(raw));
  }
});

test("createAuth.can: an administrator can do anything, others only what they were granted", () => {
  const admin = createAuth({ username: "a", display_name: "A", provider: "local", permissions: [], is_admin: true });
  assert.equal(admin.can("core.users"), true);
  assert.equal(admin.isAdmin, true);
  const user = createAuth({ username: "u", display_name: "U", provider: "local", permissions: ["core.view"], is_admin: false });
  assert.equal(user.can("core.view"), true);
  assert.equal(user.can("core.scan"), false);
  assert.equal(user.isAdmin, false);
  assert.equal(user.user.displayName, "U");
});

test("createAuth carries must_change_password", () => {
  assert.equal(createAuth({ must_change_password: true, permissions: [] }).mustChange, true);
  assert.equal(createAuth({ permissions: [] }).mustChange, false);
});

test("accountMenuHtml offers Change password only for local accounts", () => {
  const local = accountMenuHtml(createAuth({ username: "u", display_name: "Ann <b>", provider: "local", permissions: [] }));
  assert.match(local, /Signed in with NetView account/);
  assert.match(local, /Change password/);
  assert.match(local, /Sign out/);
  assert.match(local, /Ann &lt;b&gt;/);
  const outside = accountMenuHtml(createAuth({ username: "u", display_name: "U", provider: "microsoft", permissions: [] }));
  assert.doesNotMatch(outside, /Change password/);
  assert.doesNotMatch(outside, /Signed in with NetView account/);
  assert.match(outside, /Sign out/);
});

test("loginUrl remembers where the browser was", () => {
  assert.equal(
    loginUrl({ pathname: "/", search: "?a=1", hash: "#/devices" }),
    "/login?next=" + encodeURIComponent("/?a=1#/devices"),
  );
});

// ---- api.js error handling
import { apiSend } from "../../src/netview/presentation/web/static/js/api.js";

async function failWith(status, body, pathname = "/") {
  const realFetch = globalThis.fetch;
  const hadLocation = Object.getOwnPropertyDescriptor(globalThis, "location");
  const loc = { pathname, search: "", hash: "", href: pathname };
  globalThis.location = loc;
  globalThis.fetch = async () => ({ ok: false, status, statusText: "x", json: async () => body });
  try {
    const err = await apiSend("POST", "/api/v1/x", {}).then(
      () => null,
      (e) => e,
    );
    return { err, loc };
  } finally {
    globalThis.fetch = realFetch;
    if (hadLocation) Object.defineProperty(globalThis, "location", hadLocation);
    else delete globalThis.location;
  }
}

test("a wrong current password (401) shows its message and does not leave the page", async () => {
  const { err, loc } = await failWith(401, { error: "Current password is wrong" });
  assert.equal(err.message, "Current password is wrong");
  assert.equal(loc.href, "/");
});

test("a signed-out 401 goes to the sign-in page", async () => {
  const { loc } = await failWith(401, { error: "sign in required" });
  assert.match(loc.href, /^\/login\?next=/);
});

test("a 403 reads as a permission message, except the forced password change", async () => {
  assert.equal((await failWith(403, { error: "permission denied" })).err.message, "You don't have permission to do that");
  assert.equal((await failWith(403, { error: "password change required" })).err.message, "password change required");
});

import { afterSignIn } from "../../src/netview/presentation/web/static/js/auth.js";

test("afterSignIn keeps the page after # that the server never saw", () => {
  const origin = "https://netview.test";
  assert.equal(afterSignIn("?next=%2F", "#/devices", origin), "/#/devices");
  assert.equal(afterSignIn("?next=%2F%23%2Fadmin", "", origin), "/#/admin");
  assert.equal(afterSignIn("?next=%2F%23%2Fadmin", "#/devices", origin), "/#/admin"); // an explicit hash wins
  assert.equal(afterSignIn("", "#/devices", origin), "/#/devices");
  assert.equal(afterSignIn("?next=%2F%2Fevil.example", "#/x", origin), "/"); // still safe
});

import { passwordChecks, passwordReady, checksHtml } from "../../src/netview/presentation/web/static/js/auth.js";

const ok = (rows) => Object.fromEntries(rows.map((r) => [r.id, r.ok]));

test("passwordChecks: length, not the username, matching confirmation, different from current", () => {
  const rows = passwordChecks({ password: "short", confirm: "short", username: "kdoe", minLength: 12, current: "old" });
  assert.deepEqual(rows.map((r) => r.id), ["length", "username", "current", "confirm"]);
  assert.deepEqual(ok(rows), { length: false, username: true, current: true, confirm: true });
  assert.equal(rows[0].text, "At least 12 characters");
  assert.equal(passwordReady(rows), false);

  const good = passwordChecks({ password: "a long new phrase", confirm: "a long new phrase", username: "kdoe", minLength: 12, current: "the old phrase!" });
  assert.equal(passwordReady(good), true);
});

test("passwordChecks: reusing the current password fails", () => {
  const rows = passwordChecks({ password: "the old phrase!", confirm: "the old phrase!", minLength: 12, current: "the old phrase!" });
  assert.equal(ok(rows).current, false);
  assert.equal(passwordReady(rows), false);
});

test("passwordChecks: the username rule ignores case and surrounding spaces", () => {
  assert.equal(ok(passwordChecks({ password: "LongUserName12", username: " longusername12 ", minLength: 12 })).username, false);
});

test("passwordChecks: a mismatched confirmation fails, and checks are only listed when they apply", () => {
  assert.equal(ok(passwordChecks({ password: "a long new phrase", confirm: "a long new phras", minLength: 12 })).confirm, false);
  assert.deepEqual(passwordChecks({ password: "x", minLength: 8 }).map((r) => r.id), ["length"]);
});

test("passwordChecks counts characters, not UTF-16 units", () => {
  assert.equal(ok(passwordChecks({ password: "🔒".repeat(8), minLength: 8 })).length, true);
  assert.equal(ok(passwordChecks({ password: "🔒".repeat(7), minLength: 8 })).length, false);
});

test("checksHtml marks each rule met or not", () => {
  const html = checksHtml(passwordChecks({ password: "short", minLength: 12 }));
  assert.match(html, /class="no"/);
  assert.match(html, /At least 12 characters/);
});

test("createAuth exposes the password minimum, defaulting to 12", () => {
  assert.equal(createAuth({ username: "a", password_min_length: 14, permissions: [] }).passwordMinLength, 14);
  assert.equal(createAuth({ username: "a", permissions: [] }).passwordMinLength, 12);
});
