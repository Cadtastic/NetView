import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// gs105e.css and gsm7248.css load on every page, so every GS105E selector must carry a g5e class.
test("every selector in gs105e.css is scoped with g5e", () => {
  const css = readFileSync(new URL("../../static/gs105e.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const selectors = [];
  for (const m of css.matchAll(/([^{}]+)\{/g)) {
    const head = m[1].trim();
    if (head.startsWith("@")) continue;
    selectors.push(...head.split(",").map((x) => x.trim()));
  }
  assert.ok(selectors.length > 10);
  for (const sel of selectors) assert.ok(sel.includes("g5e"), `unscoped selector: ${sel}`);
});
