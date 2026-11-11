import { test } from "node:test";
import assert from "node:assert/strict";
import { keyForEvent, createHold, controlState, UNVERIFIED, COMMON_APPS, wireHoldRelease } from "../../static/control.js";
import { tabsHtml, commandsSignature, nextTabsMarkup, scheduleReloads, AFTER_COMMAND_DELAYS_MS } from "../../static/page.js";

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

test("hold sends keyup on leave and on blur, once", async () => {
  const sent = [];
  const timers = fakeTimers();
  const h = createHold((k, a) => sent.push([k, a]), timers);
  h.down("Right");
  timers.advance(400);
  h.up();
  h.up();
  await new Promise((r) => setTimeout(r, 0));
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

test("a second down releases the first key", async () => {
  const sent = [];
  const timers = fakeTimers();
  const h = createHold((k, a) => sent.push([k, a]), timers);
  h.down("Up");
  timers.advance(400);
  h.down("Fwd");
  await new Promise((r) => setTimeout(r, 0)); // a real 300 ms delay lets the first keyup go out before the next keydown
  timers.advance(400);
  h.up();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [["Up", "down"], ["Up", "up"], ["Fwd", "down"], ["Fwd", "up"]]);
});

test("keyup waits for a slow keydown to finish", async () => {
  const sent = [];
  let finishDown;
  const timers = fakeTimers();
  const h = createHold((k, a) => {
    sent.push([k, a]);
    return a === "down" ? new Promise((r) => (finishDown = r)) : Promise.resolve();
  }, timers);
  h.down("Right");
  timers.advance(400);
  h.up();
  await Promise.resolve();
  assert.deepEqual(sent, [["Right", "down"]]);
  finishDown();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [["Right", "down"], ["Right", "up"]]);
});

test("keyup still follows a failed keydown", async () => {
  const sent = [];
  const timers = fakeTimers();
  const h = createHold((k, a) => {
    sent.push([k, a]);
    return a === "down" ? Promise.reject(new Error("x")) : Promise.resolve();
  }, timers);
  h.down("Up");
  timers.advance(400);
  h.up();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [["Up", "down"], ["Up", "up"]]);
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
  assert.match(w.text, /^A different Roku, Kitchen, now answers at this address\. Run a scan in Settings, or edit or remove this TV in Saved TVs\.$/);
  assert.equal(controlState(tv({}, { power: "standby" })).on, false);
});

test("controlState holds a TV that answers but will not identify itself", () => {
  const u = controlState(tv({}, { unverified: true, power: "unknown", error: "ignored" }));
  assert.equal(u.kind, "unverified");
  assert.equal(u.on, false);
  assert.equal(u.text, UNVERIFIED);
  assert.match(u.text, /^This TV answers but doesn't say which Roku it is/);
  assert.equal(controlState(tv({}, { unverified: false })).kind, "ok");
});

test("common apps list is the cheat sheet's, without inputs", () => {
  assert.ok(COMMON_APPS.some(([n, id]) => n === "YouTube" && id === "837"));
  assert.ok(COMMON_APPS.every(([, id]) => /^[0-9]+$/.test(id)));
});

test("keyForEvent ignores events from inside an open dialog", () => {
  const inDialog = { tagName: "BUTTON", closest: (sel) => (sel === "dialog[open]" ? {} : null) };
  assert.equal(keyForEvent({ key: "Escape", target: inDialog }), null);
  assert.equal(keyForEvent({ key: "ArrowLeft", target: inDialog }), null);
  const outside = { tagName: "DIV", closest: () => null };
  assert.equal(keyForEvent({ key: "Escape", target: outside }), "Back");
});

function fakeTarget() {
  const map = new Map();
  return {
    addEventListener(type, fn) { map.set(type, [...(map.get(type) || []), fn]); },
    removeEventListener(type, fn) { map.set(type, (map.get(type) || []).filter((f) => f !== fn)); },
    fire(type) { for (const fn of [...(map.get(type) || [])]) fn({ type }); },
    count: (type) => (map.get(type) || []).length,
  };
}

for (const [name, pick, type] of [
  ["pointerleave on a held button", (b) => b, "pointerleave"],
  ["pointercancel on a held button", (b) => b, "pointercancel"],
  ["window blur", (_b, w) => w, "blur"],
]) {
  test(`wireHoldRelease: ${name} sends keyup once`, async () => {
    const sent = [];
    const timers = fakeTimers();
    const h = createHold((k, a) => sent.push([k, a]), timers);
    const btn = fakeTarget();
    const win = fakeTarget();
    const off = wireHoldRelease([btn], win, () => h.up());
    h.down("Up");
    timers.advance(400);
    pick(btn, win).fire(type);
    pick(btn, win).fire(type);
    await new Promise((r) => setTimeout(r, 0));
    assert.deepEqual(sent, [["Up", "down"], ["Up", "up"]]);
    off();
    assert.equal(btn.count("pointerleave") + btn.count("pointercancel") + win.count("blur"), 0);
  });
}

test("commandsSignature changes only with what the Commands view shows", () => {
  const tv = { id: "a", ip: "10.0.0.5", title: "Den", tv: true, status: { reachable: true, mode: "default", power: "on", checked_at_ms: 1, apps: [{ id: "12", name: "Netflix" }] } };
  const base = commandsSignature(tv, "ps", "Home");
  const quiet = { ...tv, status: { ...tv.status, power: "standby", checked_at_ms: 99, active_app: { name: "x" } } };
  assert.equal(commandsSignature(quiet, "ps", "Home"), base);
  assert.notEqual(commandsSignature({ ...tv, ip: "10.0.0.6" }, "ps", "Home"), base);
  assert.notEqual(commandsSignature({ ...tv, title: "Bed" }, "ps", "Home"), base);
  assert.notEqual(commandsSignature({ ...tv, status: { ...tv.status, mode: "limited" } }, "ps", "Home"), base);
  assert.notEqual(commandsSignature({ ...tv, status: { ...tv.status, apps: [] } }, "ps", "Home"), base);
  assert.notEqual(commandsSignature(tv, "cmd", "Home"), base);
  assert.notEqual(commandsSignature(tv, "ps", "Back"), base);
});

test("nextTabsMarkup returns the markup only when it differs from what is shown", () => {
  const a = tabsHtml([{ id: "a", title: "Den", ip: "192.168.1.5", status: { reachable: true, power: "on" } }], "a");
  const b = tabsHtml([{ id: "a", title: "Den", ip: "192.168.1.5", status: { reachable: false } }], "a");
  assert.equal(nextTabsMarkup(null, a), a);
  assert.equal(nextTabsMarkup(a, a), null);
  assert.equal(nextTabsMarkup(a, b), b);
});

test("scheduleReloads reloads twice after a command, at 1500 ms and 3000 ms", () => {
  assert.deepEqual(AFTER_COMMAND_DELAYS_MS, [1500, 3000]);
  const scheduled = [];
  const reloads = [];
  const ids = scheduleReloads((fn, ms) => (scheduled.push({ fn, ms }), scheduled.length), () => reloads.push("load"));
  assert.deepEqual(scheduled.map((t) => t.ms), [1500, 3000]);
  assert.deepEqual(ids, [1, 2]);
  assert.equal(reloads.length, 0);
  scheduled[0].fn();
  scheduled[1].fn();
  assert.equal(reloads.length, 2);
});

test("scheduleReloads drops each id from the tracking set when its timer fires", () => {
  const scheduled = [];
  const set = new Set();
  const ids = scheduleReloads((fn, ms) => (scheduled.push(fn), scheduled.length), () => {}, [10, 20], set);
  assert.deepEqual([...set], ids);
  scheduled[0]();
  assert.deepEqual([...set], [2]);
  scheduled[1]();
  assert.equal(set.size, 0);
});
