// The Targets blade (list, add/edit form, delete with confirm, Trace now) plus the pure helpers the other blades share.
import { shell } from "./shell.js";
import { follow } from "./follow.js";
import { LOAD_ERROR, loadErrorAfter } from "./refresher.js";

export const TARGET_KEY = "netview.geotrace.target";
export const INTERVALS = [5, 15, 30, 60];

/** What a new target (or a one-off trace) starts from: the admin's defaults from /status, else 15 min and IPv4. */
export function addDefaults(status) {
  const d = status && status.defaults;
  return {
    interval_min: d && INTERVALS.includes(d.interval_min) ? d.interval_min : 15,
    family: d && (d.family === "ipv4" || d.family === "ipv6") ? d.family : "ipv4",
  };
}
const NAME_MAX = 100;
const LABEL = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;
const IPV4 = /^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;

// -- pure helpers (unit-tested) --------------------------------------------------------------------

function isIpLiteral(text) {
  if (IPV4.test(text)) return true;
  if (!text.includes(":") || !/^[0-9A-Fa-f:.]+$/.test(text)) return false; // no "%scope", brackets or port
  try {
    new URL(`http://[${text}]/`); // the URL parser knows the IPv6 grammar
    return true;
  } catch (e) {
    return false;
  }
}

/** Mirrors the server's valid_address: an IP literal, or a host name of labels (1-63 chars, letters, digits, "-"). */
export function checkAddress(text) {
  if (typeof text !== "string") return false;
  if (isIpLiteral(text)) return true;
  if (text.length < 1 || text.length > 253) return false;
  return text.split(".").every((label) => LABEL.test(label));
}

/** Plain-language problems with the form fields (empty when fine). The address is checked as given; trim it first. */
export function formProblems({ name, address }) {
  const out = [];
  const n = String(name ?? "").trim();
  if (!n) out.push("Give the target a name.");
  else if (n.length > NAME_MAX) out.push(`The name can be at most ${NAME_MAX} characters.`);
  if (!checkAddress(String(address ?? ""))) out.push("The address must be a host name (like netflix.com) or an IP address, without https:// or a path.");
  return out;
}

/** The status dot: worst of reachability, loss and a slowdown note; idle until the first trace. */
export function statusKind(target) {
  const last = target && target.last;
  if (!last) return "idle";
  if (last.status === "failed" || last.reached === false) return "bad";
  if ((last.loss_pct ?? 0) > 0 || /slower/i.test(target.note || "")) return "warn";
  return "ok";
}

export function agoText(ms, now = Date.now()) {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function fmtRtt(ms) {
  if (ms == null) return "–";
  return ms < 10 ? `${ms.toFixed(1)} ms` : `${Math.round(ms)} ms`;
}

const fmtLoss = (p) => (p == null ? "loss –" : `loss ${+p.toFixed(1)}%`);

/** "8 hops · traced 2 min ago · 58 ms · loss 0%" for a trace (or a target's `last`). */
export function routeSubtitle(trace, now = Date.now()) {
  if (!trace) return "No trace yet";
  const n = trace.hop_count ?? 0;
  const base = `${n} ${n === 1 ? "hop" : "hops"} · traced ${agoText(trace.started_ms, now)} · ${fmtRtt(trace.rtt_ms)} · ${fmtLoss(trace.loss_pct)}`;
  return trace.status === "done" && trace.reached === false ? `${base} · not reached` : base;
}

/** The figure on the right of a target row: "failed", the RTT, or "loss N%" when the RTT is missing or loss > 0. */
export function targetMetric(target) {
  const last = target.last;
  if (!last) return "–";
  if (last.status === "failed") return "failed";
  const loss = last.loss_pct;
  if (last.rtt_ms == null || (loss ?? 0) > 0) return loss == null ? "–" : `loss ${+loss.toFixed(1)}%`;
  return fmtRtt(last.rtt_ms);
}

/** The small line under a target's name: "every 15 min · route changed 3 h ago". */
export function targetLine(target) {
  if (!target.enabled) return "paused";
  return target.note ? `every ${target.interval_min} min · ${target.note}` : `every ${target.interval_min} min`;
}

// -- selection -------------------------------------------------------------------------------------

/** The saved selected target id, or null (storage may be blocked). */
export function loadSelection(storage) {
  try {
    const raw = (storage ?? globalThis.localStorage).getItem(TARGET_KEY);
    const id = raw === null ? NaN : Number(raw);
    return Number.isInteger(id) ? id : null;
  } catch (e) {
    return null;
  }
}

export function saveSelection(id, storage) {
  try {
    const s = storage ?? globalThis.localStorage;
    if (id === null) s.removeItem(TARGET_KEY);
    else s.setItem(TARGET_KEY, String(id));
  } catch (e) {
    // blocked storage: the selection just isn't remembered
  }
}

export const routeKey = (id) => `target:${id}`;

// -- the blade -------------------------------------------------------------------------------------

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

/** NetView's status dot (the shared .sdot styles), built with DOM calls so nothing goes through innerHTML. */
export function dot(kind, tip) {
  const d = h("span", `sdot sm ${kind}`);
  d.setAttribute("role", "img");
  d.setAttribute("aria-label", tip);
  d.dataset.tip = tip;
  return d;
}

const DOT_TIPS = { ok: "Reachable", warn: "Loss or slower than usual", bad: "Not reached", idle: "No trace yet" };

function field(labelText, control) {
  const label = h("label", "gt-field");
  label.append(h("span", "gt-field-label", labelText), control);
  return label;
}

function option(value, text) {
  const o = h("option", "", text);
  o.value = String(value);
  return o;
}

function render(body, ctx) {
  const api = ctx.api;
  let targets = ctx.snapshot().targets;
  let selected = loadSelection();
  let confirming = null;
  let busy = false;
  let gone = false;
  let failed = false;

  const bar = h("div", "gt-toolbar");
  const add = btn("+ Add target");
  const traceNow = btn("Trace now");
  bar.append(add, traceNow);
  const msg = h("p", "gt-msg");
  msg.setAttribute("role", "alert");
  msg.hidden = true;
  const formBox = h("div", "gt-form-box");
  const list = h("div", "gt-list");
  body.append(bar, msg, formBox, list);

  const say = (text) => {
    msg.textContent = text || "";
    msg.hidden = !text;
  };

  function drawList() {
    traceNow.disabled = busy || selected === null || !(targets || []).some((t) => t.id === selected);
    if (targets === null) return failed ? list.replaceChildren() : list.replaceChildren(h("p", "gt-muted", "Loading…"));
    if (!targets.length) return list.replaceChildren(h("p", "gt-muted", "No targets yet. Add one to start tracing."));
    list.replaceChildren(...targets.map(row));
  }

  function row(t) {
    const kind = statusKind(t);
    const item = h("div", "gt-row");
    item.classList.toggle("gt-sel", t.id === selected);
    const main = h("button", "gt-row-main");
    main.type = "button";
    main.setAttribute("aria-pressed", String(t.id === selected));
    const text = h("span", "gt-grow");
    text.append(h("span", "gt-row-name", t.name), h("small", "gt-row-sub", targetLine(t)));
    const metric = h("span", `gt-metric gt-${kind}`, targetMetric(t));
    if (t.last && t.last.rtt_ms != null) metric.title = fmtRtt(t.last.rtt_ms);
    main.append(dot(kind, DOT_TIPS[kind]), text, metric);
    main.addEventListener("click", () => select(t.id));
    item.appendChild(main);
    if (confirming === t.id) {
      const ask = h("div", "gt-confirm");
      const yes = btn("Delete", "gt-btn gt-danger");
      const no = btn("Cancel");
      yes.addEventListener("click", () => remove(t));
      no.addEventListener("click", () => {
        confirming = null;
        drawList();
      });
      ask.append(h("span", "gt-grow", `Delete ${t.name} and its saved traces?`), yes, no);
      item.appendChild(ask);
    } else {
      const edit = btn("✎", "gt-icon-btn");
      edit.setAttribute("aria-label", `Edit ${t.name}`);
      edit.title = "Edit";
      edit.addEventListener("click", () => openForm(t));
      const del = btn("×", "gt-icon-btn");
      del.setAttribute("aria-label", `Delete ${t.name}`);
      del.title = "Delete";
      del.addEventListener("click", () => {
        confirming = t.id;
        drawList();
      });
      item.append(edit, del);
    }
    return item;
  }

  function select(id) {
    selected = id;
    saveSelection(id);
    say("");
    drawList();
    ctx.open(routeKey(id), { level: 1 });
  }

  // The page owns the list: refresh() reloads it and calls update() on every open blade, this one included.
  async function reload() {
    const ok = await ctx.refresh();
    if (gone) return;
    targets = ctx.snapshot().targets;
    const text = loadErrorAfter(ok, targets);
    failed = text !== "";
    say(text);
    drawList();
  }

  async function remove(t) {
    say("");
    try {
      await api.gtSend("DELETE", `/targets/${t.id}`);
    } catch (e) {
      confirming = null;
      say(e.message || "Could not delete the target.");
      return drawList();
    }
    confirming = null;
    if (selected === t.id) {
      selected = null;
      saveSelection(null);
      ctx.close(routeKey(t.id));
    }
    await reload();
  }

  function openForm(t) {
    say("");
    const name = h("input", "gt-input");
    name.maxLength = NAME_MAX;
    name.value = t ? t.name : "";
    const address = h("input", "gt-input");
    address.placeholder = "IP address or web address";
    address.value = t ? t.address : "";
    address.spellcheck = false;
    const family = h("select", "gt-input");
    family.append(option("ipv4", "IPv4"), option("ipv6", "IPv6"));
    const defaults = addDefaults((ctx.snapshot() || {}).status); // editing keeps the target's own values
    family.value = t ? t.family : defaults.family;
    const interval = h("select", "gt-input");
    for (const m of INTERVALS) interval.append(option(m, `every ${m} min`));
    interval.value = String(t ? t.interval_min : defaults.interval_min);
    const enabled = h("input");
    enabled.type = "checkbox";
    enabled.checked = t ? t.enabled : true;
    const enabledLabel = h("label", "gt-check");
    enabledLabel.append(enabled, h("span", "", "Trace on a schedule"));
    const err = h("p", "gt-msg");
    err.setAttribute("role", "alert");
    err.hidden = true;
    const save = btn(t ? "Save" : "Add", "gt-btn gt-primary");
    save.type = "submit";
    const cancel = btn("Cancel");
    const buttons = h("div", "gt-toolbar");
    buttons.append(save, cancel);
    const form = h("form", "gt-form");
    form.noValidate = true;
    form.append(field("Name", name), field("Address", address), field("Family", family), field("Interval", interval), enabledLabel, err, buttons);
    formBox.replaceChildren(form);
    name.focus();

    const close = () => formBox.replaceChildren();
    cancel.addEventListener("click", close);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fields = {
        name: name.value.trim(),
        address: address.value.trim(),
        family: family.value,
        interval_min: Number(interval.value),
        enabled: enabled.checked,
      };
      const problems = formProblems(fields);
      err.hidden = problems.length === 0;
      err.textContent = problems.join(" ");
      if (problems.length) return;
      save.disabled = true;
      try {
        const saved = t ? await api.gtSend("PUT", `/targets/${t.id}`, fields) : await api.gtSend("POST", "/targets", fields);
        close();
        await reload();
        if (!t && saved && Number.isInteger(saved.id)) select(saved.id);
      } catch (e) {
        err.textContent = e.message || "Could not save the target.";
        err.hidden = false;
        save.disabled = false;
      }
    });
  }

  add.addEventListener("click", () => openForm(null));
  traceNow.addEventListener("click", async () => {
    if (selected === null) return;
    const id = selected;
    busy = true;
    drawList();
    say("");
    try {
      const started = await api.gtSend("POST", `/targets/${id}/trace`);
      follow(id, started.trace_id);
      ctx.open(routeKey(id), { level: 1 });
    } catch (e) {
      say(e.message || "Could not start the trace.");
    }
    busy = false;
    drawList();
  });

  drawList();
  if (targets === null) reload();
  return {
    update(snapshot) {
      if (Array.isArray(snapshot.targets)) {
        targets = snapshot.targets;
        if (failed) {
          failed = false;
          if (msg.textContent === LOAD_ERROR) say(""); // keep a delete or trace error
        }
      }
      if (selected !== null && targets && !targets.some((t) => t.id === selected)) {
        selected = null;
        saveSelection(null);
      }
      drawList();
    },
    destroy() {
      gone = true;
    },
  };
}

shell.registerBlade("targets", { title: "Targets", render });
