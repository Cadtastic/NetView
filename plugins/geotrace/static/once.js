// The Trace once blade: trace or ping an address without saving it as a target (unless asked).
import { shell } from "./shell.js";
import { globeControl } from "./globe.js";
import { createPoller } from "./poll.js";
import { createPollGuard, isOnceTrace, GONE_TEXT, LOST_TEXT } from "./poll-guard.js";
import { hopRows } from "./hops.js";
import { checkAddress, fmtRtt } from "./targets.js";

const RUNNING = new Set(["queued", "running"]);
const POLL_MS = 1000;

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function btn(label, cls = "gt-btn") {
  const b = h("button", cls, label);
  b.type = "button";
  return b;
}

function option(value, text) {
  const o = h("option", "", text);
  o.value = value;
  return o;
}

const loss = (p) => (p == null ? "–" : `${+p.toFixed(1)}%`);

/** One line for a finished ping burst (or a trace): "min 4.1 ms · avg 5.2 ms · max 9.8 ms · loss 0% · jitter 1.1 ms". */
export function pingLine(t) {
  return `min ${fmtRtt(t.ping_min_ms)} · avg ${fmtRtt(t.rtt_ms)} · max ${fmtRtt(t.ping_max_ms)} · loss ${loss(t.loss_pct)} · jitter ${fmtRtt(t.jitter_ms)}`;
}

function render(body, ctx) {
  const api = ctx.api;
  let gone = false;
  let wantedId = null;
  let shownId = null;
  let fitted = false;
  let first = null; // the first answer for this run: later answers must have its start time
  const guard = createPollGuard();
  const poller = createPoller(pollOnce, { intervalMs: POLL_MS, isVisible: () => document.visibilityState !== "hidden" });

  const address = h("input", "gt-input");
  address.placeholder = "IP address or web address";
  address.spellcheck = false;
  address.setAttribute("aria-label", "IP address or web address");
  const family = h("select", "gt-input");
  family.setAttribute("aria-label", "Address family");
  family.append(option("ipv4", "IPv4"), option("ipv6", "IPv6"));
  const trace = btn("Trace", "gt-btn gt-primary");
  const ping = btn("Ping only");
  const save = btn("Save as target");
  const bar = h("div", "gt-toolbar");
  bar.append(trace, ping, save);
  const msg = h("p", "gt-msg");
  msg.setAttribute("role", "alert");
  msg.hidden = true;
  const status = h("p", "gt-muted");
  const list = h("div", "gt-list");
  const form = h("div", "gt-form");
  form.append(address, family, bar, msg, status, list);
  body.append(form);
  ctx.setTitle("Trace once", "not saved as a target");

  const say = (text) => {
    msg.textContent = text || "";
    msg.hidden = !text;
  };

  function typed() {
    const text = address.value.trim();
    if (!checkAddress(text)) {
      say("Enter a host name (like netflix.com) or an IP address, without https:// or a path.");
      return null;
    }
    say("");
    return text;
  }

  function draw(t) {
    const hops = t.hops || [];
    if (t.status === "queued") status.textContent = "Waiting to start…";
    else if (t.status === "running") status.textContent = t.mode === "ping" ? "Pinging…" : `Tracing… ${hops.length} ${hops.length === 1 ? "hop" : "hops"} so far`;
    else if (t.status === "failed") status.textContent = t.error ? `Failed: ${t.error}` : "Failed";
    else if (t.mode === "ping") status.textContent = pingLine(t);
    else status.textContent = `${hops.length} ${hops.length === 1 ? "hop" : "hops"} · ${pingLine(t)}`;
    list.replaceChildren(...hopRows(hops, (hop) => globeControl.flyToHop(hop)));
    if (hops.length) {
      if (shownId !== null && shownId !== t.id) globeControl.clear(shownId);
      shownId = t.id;
      globeControl.showTrace(t, { style: "solid", color: "var(--accent)" });
      if (!fitted) {
        fitted = true;
        globeControl.fitRoute();
      }
    }
  }

  async function pollOnce() {
    const id = wantedId;
    if (id === null) return;
    let t;
    try {
      t = await api.gtGet(`/traces/${id}`);
    } catch (e) {
      if (gone || id !== wantedId) return;
      const verdict = guard.failed(e);
      if (verdict === "gone") status.textContent = GONE_TEXT;
      else if (verdict === "stop") status.textContent = LOST_TEXT;
      if (verdict !== "retry") poller.stop();
      return;
    }
    if (gone) return poller.stop();
    if (id !== wantedId) return;
    guard.ok();
    if (!isOnceTrace(t, first)) {
      poller.stop(); // the id now belongs to another job (NetView restarted)
      status.textContent = GONE_TEXT;
      return;
    }
    first = first || t;
    draw(t);
    if (!RUNNING.has(t.status)) poller.stop();
  }

  async function run(mode) {
    const text = typed();
    if (text === null) return;
    poller.stop();
    if (shownId !== null) globeControl.clear(shownId);
    shownId = null;
    fitted = false;
    first = null;
    guard.ok();
    list.replaceChildren();
    status.textContent = "";
    trace.disabled = ping.disabled = true;
    try {
      const started = await api.gtSend("POST", "/trace-once", { address: text, family: family.value, mode });
      if (gone) return;
      wantedId = started.trace_id;
      status.textContent = "Waiting to start…";
      poller.start();
      await poller.now();
    } catch (e) {
      say(e.message || "Could not start the trace.");
    }
    if (!gone) trace.disabled = ping.disabled = false;
  }

  trace.addEventListener("click", () => run("trace"));
  ping.addEventListener("click", () => run("ping"));
  address.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !trace.disabled) run("trace");
  });
  save.addEventListener("click", async () => {
    const text = typed();
    if (text === null) return;
    save.disabled = true;
    try {
      const made = await api.gtSend("POST", "/targets", { name: text, address: text, family: family.value });
      if (gone) return;
      say("");
      status.textContent = `Saved as target ${made && made.name ? made.name : text}.`;
      await ctx.refresh();
    } catch (e) {
      if (gone) return;
      say(e.message || "Could not save the target.");
    }
    if (!gone) save.disabled = false;
  });

  return {
    destroy() {
      gone = true;
      poller.stop();
      if (shownId !== null) globeControl.clear(shownId);
    },
  };
}

shell.registerBlade("trace", { title: "Trace once", render });
