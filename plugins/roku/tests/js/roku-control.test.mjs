import { test } from "node:test";
import assert from "node:assert/strict";
import { keyForEvent, createHold, controlState, COMMON_APPS } from "../../static/control.js";
import { tabsHtml } from "../../static/page.js";

const ev = (key, extra = {}) => ({ key, target: { tagName: "DIV" }, ...extra });

test("keyForEvent maps keys", () => {
  assert.equal(keyForEvent(ev("ArrowUp")), "Up");
  assert.equal(keyForEvent(ev("ArrowDown")), "Down");
  assert.equal(keyForEvent(ev("ArrowLeft")), "Left");
  assert.equal(keyForEvent(ev("ArrowRight")), "Right");
  assert.equal(keyForEvent(ev("Enter")), "Select");
  assert.equal(keyForEvent(ev("Backspace")), "Back");
  assert.equal(keyForEvent(ev("Escape")), "Back");
  assert.equal(keyForEvent(ev("h")), "Home");
  assert.equal(keyForEvent(ev("H")), "Home");
  assert.equal(keyForEvent(ev(" ")), "Play");
  assert.equal(keyForEvent(ev("x")), null);
});

test("keyForEvent ignores text fields and modifiers", () => {
  for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) {
    assert.equal(keyForEvent({ key: "ArrowUp", target: { tagName } }), null);
  }
  assert.equal(keyForEvent({ key: "ArrowUp", target: { tagName: "DIV", isContentEditable: true } }), null);
  for (const m of ["ctrlKey", "altKey", "metaKey"]) assert.equal(keyForEvent(ev("h", { [m]: true })), null);
});

function fakeTimers() {
  let t = 0, id = 0;
  const pending = new Map();
  return {
    setTimeout(fn, ms) { id += 1; pending.set(id, { fn, at: t + ms }); return id; },
    clearTimeout(i) { pending.delete(i); },
    advance(ms) {
      t += ms;
      for (const [i, p] of [...pending]) if (p.at <= t) { pending.delete(i); p.fn(); }
    },
  };
}

test("hold sends keyup on leave and on blur, once", () => {
  const sent = [];
  const timers = fakeTimers();
  const h = createHold((k, a) => sent.push([k, a]), timers);
  h.down("Right");
  timers.advance(400);
  h.up();
  h.up();
  assert.deepEqual(sent, [["Right", "down"], ["Right", "up"]]);
});

test("a quick click on a holdable key sends one press", () => {
  const sent = [];
  const timers = fakeTimers();
  const h = createHold((k, a) => sent.push([k, a]), timers);
  h.down("Left");
  timers.advance(100);
  h.up();
  timers.advance(1000);
  h.up();
  assert.deepEqual(sent, [["Left", "press"]]);
});

test("a second down releases the first key", () => {
  const sent = [];
  const timers = fakeTimers();
  const h = createHold((k, a) => sent.push([k, a]), timers);
  h.down("Up");
  timers.advance(400);
  h.down("Fwd");
  timers.advance(400);
  h.up();
  assert.deepEqual(sent, [["Up", "down"], ["Up", "up"], ["Fwd", "down"], ["Fwd", "up"]]);
});

const st = (o = {}) => ({ reachable: true, power: "on", mode: "default", ...o });
const tv = (o = {}, s = {}) => ({ id: "a", title: "Living Room TV", name: "n", ip: "192.168.1.5", tv: true, status: st(s), ...o });

test("tab dot classes and tooltip text", () => {
  const tvs = [
    tv({ id: "a", title: "Living Room TV" }),
    tv({ id: "b", title: "Bedroom <TV>", ip: "192.168.1.6" }, { power: "standby", mode: "default" }),
    tv({ id: "c", title: "Den", ip: "192.168.1.7" }, { mode: "limited" }),
    tv({ id: "d", title: "Gone", ip: "192.168.1.8" }, { reachable: false, power: "unknown", mode: "" }),
  ];
  const html = tabsHtml(tvs, "b");
  assert.match(html, /role="tab"[^>]*aria-selected="false"[^>]*data-id="a"[^>]*title="192\.168\.1\.5 · on · Network access: Default"><span class="dot on">/);
  assert.match(html, /aria-selected="true"[^>]*data-id="b"[^>]*title="192\.168\.1\.6 · standby · Network access: Default"><span class="dot ">/);
  assert.match(html, /data-id="c"[^>]*title="192\.168\.1\.7 · on · Network access: Limited"><span class="dot lim">/);
  assert.match(html, /data-id="d"[^>]*title="192\.168\.1\.8 · not answering"><span class="dot ">/);
  assert.match(html, /Bedroom &lt;TV&gt;/);
});

test("controlState picks the mode of the view", () => {
  assert.equal(controlState(tv()).kind, "ok");
  assert.equal(controlState(tv({}, { mode: "limited" })).kind, "limited");
  assert.equal(controlState(tv({}, { reachable: false, power: "unknown" })).kind, "silent");
  const w = controlState(tv({}, { reachable: false, wrong_device: "Kitchen" }));
  assert.equal(w.kind, "wrong");
  assert.match(w.text, /^A different Roku, Kitchen, now answers at this address\. Run a scan in Settings\.$/);
  assert.equal(controlState(tv({}, { power: "standby" })).on, false);
});

test("common apps list is the cheat sheet's, without inputs", () => {
  assert.ok(COMMON_APPS.some(([n, id]) => n === "YouTube" && id === "837"));
  assert.ok(COMMON_APPS.every(([, id]) => /^[0-9]+$/.test(id)));
});
