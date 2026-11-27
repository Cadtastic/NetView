// The Route blade: one target's trace as a hop list, with the route drawn on the globe. Blade key "target:<id>".
import { shell } from "./shell.js";
import { globeControl } from "./globe.js";
import { createPoller } from "./poll.js";
import { subscribe, take } from "./follow.js";
import { hopRows } from "./hops.js";
import { routeSubtitle, agoText, fmtRtt, loadSelection, saveSelection } from "./targets.js";

const RUNNING = new Set(["queued", "running"]);
const POLL_MS = 1000;
const NEWEST = "newest";

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function btn(label) {
  const b = h("button", "gt-btn", label);
  b.type = "button";
  return b;
}

const visible = () => document.visibilityState !== "hidden";

function subtitleFor(trace) {
  if (!trace) return "No trace yet";
  if (trace.status === "queued") return "Waiting to trace…";
  if (trace.status === "running") {
    const n = trace.hops ? trace.hops.length : 0;
    return `Tracing… ${n} ${n === 1 ? "hop" : "hops"} so far`;
  }
  if (trace.status === "failed") return trace.error ? `Failed: ${trace.error}` : "Failed";
  return routeSubtitle(trace);
}

function pickerLabel(t, now) {
  const state = t.status === "failed" ? "failed" : fmtRtt(t.rtt_ms);
  return `${agoText(t.started_ms, now)} · ${t.hop_count} ${t.hop_count === 1 ? "hop" : "hops"} · ${state}`;
}

function render(body, ctx) {
  const api = ctx.api;
  const targetId = Number(ctx.params[0]);
  let gone = false;
  let trace = null; // what the hop list shows
  let shownId = null; // the id the globe has drawn
  let wantedId = null; // the trace being followed or looked at
  let fitted = false;
  let history = [];
  const poller = createPoller(pollOnce, { intervalMs: POLL_MS, isVisible: visible });

  const findTarget = (snap) => ((snap && snap.targets) || []).find((t) => t.id === targetId) || null;
  let target = findTarget(ctx.snapshot());

  const bar = h("div", "gt-toolbar");
  const fit = btn("Fit route");
  const along = btn("Fly along route");
  const compare = btn("Compare…");
  const trends = btn("Trends");
  bar.append(fit, along, compare, trends);
  const picker = h("select", "gt-input gt-picker");
  picker.setAttribute("aria-label", "Trace to show");
  const msg = h("p", "gt-msg");
  msg.setAttribute("role", "alert");
  msg.hidden = true;
  const label = h("div", "gt-label", "Hops — click to fly there");
  const list = h("div", "gt-list");
  body.append(bar, picker, msg, label, list);

  fit.addEventListener("click", () => globeControl.fitRoute());
  along.addEventListener("click", () => globeControl.flyAlong());
  compare.addEventListener("click", () => ctx.open("compare", { level: 2 }));
  trends.addEventListener("click", () => ctx.open("trends", { level: 2 }));

  const say = (text) => {
    msg.textContent = text || "";
    msg.hidden = !text;
  };

  function heading() {
    ctx.setTitle(target ? target.name : `Target ${targetId}`, subtitleFor(trace));
  }

  function draw() {
    heading();
    const hops = trace && trace.hops ? trace.hops : [];
    if (!trace) list.replaceChildren(h("p", "gt-muted", "No trace yet. Use Trace now in the Targets blade."));
    else if (!hops.length) list.replaceChildren(h("p", "gt-muted", RUNNING.has(trace.status) ? "Waiting for the first hop…" : "No hops to show."));
    else list.replaceChildren(...hopRows(hops, (hop) => globeControl.flyToHop(hop)));
    if (trace && hops.length) {
      if (shownId !== null && shownId !== trace.id) globeControl.clear(shownId);
      shownId = trace.id;
      globeControl.showTrace(trace, { style: "solid", color: "var(--accent)" });
      if (!fitted) {
        fitted = true;
        globeControl.fitRoute();
      }
    }
  }

  function drawPicker() {
    const now = Date.now();
    const opts = [Object.assign(h("option", "", "Newest"), { value: NEWEST })];
    for (const t of history) opts.push(Object.assign(h("option", "", pickerLabel(t, now)), { value: String(t.id) }));
    picker.replaceChildren(...opts);
    picker.value = wantedFromPicker;
  }
  let wantedFromPicker = NEWEST;

  async function loadHistory() {
    try {
      const rows = await api.gtGet(`/targets/${targetId}/traces?limit=50`);
      if (gone) return;
      history = Array.isArray(rows) ? rows : [];
    } catch (e) {
      history = [];
    }
    drawPicker();
  }

  function accept(next) {
    trace = next;
    draw();
    if (RUNNING.has(next.status)) return;
    poller.stop();
    loadHistory();
  }

  async function pollOnce() {
    const id = wantedId;
    if (id === null) return;
    const next = await api.gtGet(`/traces/${id}`);
    if (gone || id !== wantedId) return;
    accept(next);
  }

  async function show(id) {
    wantedId = id;
    fitted = false;
    say("");
    poller.stop();
    try {
      const next = await api.gtGet(`/traces/${id}`);
      if (gone || id !== wantedId) return;
      accept(next);
      if (RUNNING.has(next.status)) poller.start();
    } catch (e) {
      if (gone || id !== wantedId) return;
      say(e.message || "Could not load that trace.");
    }
  }

  picker.addEventListener("change", () => {
    wantedFromPicker = picker.value;
    if (picker.value === NEWEST) {
      const newest = history[0] ? history[0].id : target && target.last ? target.last.trace_id : null;
      if (newest !== null) show(newest);
    } else show(Number(picker.value));
  });

  const stopFollowing = subscribe(targetId, (traceId) => {
    wantedFromPicker = NEWEST;
    drawPicker();
    show(traceId);
  });

  saveSelection(targetId); // the page's rail reopens this blade next time
  heading();
  drawPicker();
  loadHistory();
  const first = take(targetId) ?? (target && target.last ? target.last.trace_id : null);
  if (first !== null && first !== undefined) show(first);
  else draw();

  return {
    update(snapshot) {
      const next = findTarget(snapshot);
      if (!next && !Array.isArray(snapshot.targets)) return;
      if (!next) {
        // the target was deleted elsewhere
        if (loadSelection() === targetId) saveSelection(null);
        ctx.close(ctx.key);
        return;
      }
      const hadLast = target && target.last ? target.last.trace_id : null;
      target = next;
      heading();
      // A scheduled run finished while the newest trace is on show: move to it.
      const newest = next.last ? next.last.trace_id : null;
      if (wantedFromPicker === NEWEST && newest !== null && newest !== hadLast && !(trace && RUNNING.has(trace.status)) && (!trace || trace.id !== newest)) {
        show(newest);
      }
    },
    destroy() {
      gone = true;
      poller.stop();
      stopFollowing();
      if (shownId !== null) globeControl.clear(shownId);
    },
  };
}

shell.registerBlade("target", { title: (key) => `Target ${key.split(":")[1] ?? ""}`, render });
