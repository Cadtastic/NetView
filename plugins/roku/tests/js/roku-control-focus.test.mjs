import { test } from "node:test";
import assert from "node:assert/strict";
import { renderControl, typingIn } from "../../static/control.js";

// A tiny stand-in for the DOM: each innerHTML assignment makes a fresh text box and OK button, like the real redraw.
function setup() {
  const body = { tagName: "BODY" };
  const doc = { body, activeElement: body, keydown: [], addEventListener(t, f) { if (t === "keydown") this.keydown.push(f); }, removeEventListener() {}, querySelector: () => null };
  const node = (tag, attrs) => ({
    tagName: tag, dataset: attrs.dataset || {}, value: "", selectionStart: 0, selectionEnd: 0, disabled: false,
    matches: (s) => s === attrs.sel,
    focus() { doc.activeElement = this; },
    setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; },
    closest: () => null,
  });
  const el = {
    input: null, ok: null,
    set innerHTML(_h) {
      this.input = node("INPUT", { sel: "[data-text]" });
      this.ok = node("BUTTON", { sel: "button", dataset: { k: "Select" } });
    },
    querySelector(s) { return s === "[data-text]" ? this.input : s === 'button[data-k="Select"]' ? this.ok : null; },
    querySelectorAll: () => [],
    contains(n) { return n === this.input || n === this.ok; },
    addEventListener() {}, removeEventListener() {},
  };
  globalThis.document = doc;
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  return { el, doc };
}

const tv = (app) => ({ id: "a", title: "Den", ip: "10.0.0.5", tv: true, status: { reachable: true, power: "on", mode: "default", checked_at_ms: 1, active_app: app } });

test("a redraw keeps focus, text and caret in the Type text box, and typed h is not a remote key", () => {
  const { el, doc } = setup();
  const sent = [];
  const api = { base: "/api", send: (...a) => { sent.push(a); return Promise.resolve(); }, toast() {}, fmtAgo: () => "now" };
  const first = renderControl(el, tv(null), api);
  el.input.focus();
  el.input.value = "the";
  el.input.selectionStart = el.input.selectionEnd = 3;
  assert.equal(typingIn(el), true);
  first.destroy();
  renderControl(el, tv({ id: "837", name: "YouTube" }), api);
  assert.equal(doc.activeElement, el.input);
  assert.equal(el.input.value, "the");
  assert.equal(el.input.selectionStart, 3);
  for (const f of doc.keydown) f({ key: "h", target: doc.activeElement, preventDefault() {} });
  assert.deepEqual(sent, []);
});

test("a redraw keeps focus on a remote button", () => {
  const { el, doc } = setup();
  const api = { base: "/api", send: () => Promise.resolve(), toast() {}, fmtAgo: () => "now" };
  const first = renderControl(el, tv(null), api);
  el.ok.focus();
  first.destroy();
  renderControl(el, tv({ id: "1", name: "X" }), api);
  assert.equal(doc.activeElement, el.ok);
});
