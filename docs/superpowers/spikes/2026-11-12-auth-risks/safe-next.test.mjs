// Spike: safeNext keeps sign-in redirects on NetView's own origin.
import { test } from "node:test";
import assert from "node:assert/strict";

/** The same-origin path to go to after sign-in, or "/" for anything that would leave NetView. */
export function safeNext(raw, origin) {
  if (typeof raw !== "string" || raw === "" || raw[0] !== "/") return "/";
  let url;
  try {
    url = new URL(raw, origin); // the browser's own parser: tabs/newlines stripped, "\" read as "/"
  } catch {
    return "/";
  }
  if (url.origin !== origin) return "/";
  if (url.pathname === "/login" || url.pathname === "/setup") return "/";
  const out = url.pathname + url.search + url.hash;
  // Dot segments can collapse into a "//host" pathname ("/.//evil" -> "//evil"), which a browser reads as
  // another site. Check the string we hand back, not just the input.
  if (out.startsWith("//") || out.startsWith("/\\")) return "/";
  if (new URL(out, origin).origin !== origin) return "/";
  return out;
}

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
