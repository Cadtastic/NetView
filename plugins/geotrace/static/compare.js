// The Compare blade: two saved traces of one target, side by side, with the older route dashed on the globe. Blade key "compare:<id>".
import { shell } from "./shell.js";
import { globeControl } from "./globe.js";
import { CMP_NEW, CMP_OLD, COMPARE_KEYS } from "./draw-keys.js";
import { compareRows, splitSentence, cellText, traceLabel } from "./compare-model.js";

const NO_TARGET = "Pick a target first.";
const TOO_FEW = "Not enough traces to compare yet. Two finished traces of this target are needed.";

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function option(value, text) {
  const o = h("option", "", text);
  o.value = String(value);
  return o;
}

function field(text, control) {
  const wrap = h("label", "gt-field");
  wrap.append(h("span", "", text), control);
  return wrap;
}

function render(body, ctx) {
  const targetId = Number(ctx.params[0]);
  if (ctx.params[0] === undefined || !Number.isInteger(targetId)) {
    ctx.setTitle("Compare traces");
    body.append(h("p", "gt-muted", NO_TARGET));
    return {};
  }
  const api = ctx.api;
  let gone = false;
  let seq = 0; // the newest compare request wins
  let data = null; // the API answer on show
  let history = [];
  let wantA = null; // picker choices; null = let the server choose
  let wantB = null;
  let newTrace = null; // the full traces on the globe
  let oldTrace = null;
  let showOld = true;
  let following = true; // both pickers are on the default (newest): a new trace moves the comparison
  let lastSeen = null;

  const findTarget = (snap) => ((snap && snap.targets) || []).find((t) => t.id === targetId) || null;
  const name = () => {
    const t = findTarget(ctx.snapshot());
    return t ? t.name : `Target ${targetId}`;
  };

  const pickA = h("select", "gt-input");
  pickA.setAttribute("aria-label", "Newer trace");
  const pickB = h("select", "gt-input");
  pickB.setAttribute("aria-label", "Older trace");
  const msg = h("p", "gt-msg");
  msg.setAttribute("role", "alert");
  msg.hidden = true;
  const note = h("p", "gt-muted gt-trend-note");
  note.hidden = true;
  const legend = h("div", "gt-list");
  const split = h("p", "gt-split");
  const table = h("div", "gt-cmp-wrap");
  body.append(field("Newer trace", pickA), field("Older trace", pickB), msg, note, legend, split, table);

  const say = (text) => {
    msg.textContent = text || "";
    msg.hidden = !text;
  };

  // While this blade is open it owns the globe: only its two drawings show (the Route blade's is hidden, not deleted).
  function drawGlobe() {
    globeControl.setFocus(COMPARE_KEYS);
    if (newTrace) globeControl.showTrace(newTrace, { style: "solid", color: "var(--accent)", key: CMP_NEW });
    else globeControl.clear(CMP_NEW);
    if (oldTrace && showOld) globeControl.showTrace(oldTrace, { style: "dashed", color: "var(--warn)", key: CMP_OLD });
    else globeControl.clear(CMP_OLD);
  }

  function fillPicker(select, current) {
    const now = Date.now();
    select.replaceChildren(...history.map((t) => option(t.id, traceLabel(t, now))));
    select.value = String(current);
    if (select.value !== String(current)) {
      // older than the 50 newest traces in the list
      select.append(option(current, `Trace ${current}`));
      select.value = String(current);
    }
  }

  function swatch(dashed) {
    const s = h("span", dashed ? "gt-swatch gt-swatch-old" : "gt-swatch gt-swatch-new");
    s.setAttribute("aria-hidden", "true");
    return s;
  }

  function drawLegend() {
    const now = Date.now();
    const newer = h("div", "gt-row");
    const t1 = h("span", "gt-grow");
    t1.append(h("span", "gt-row-name", "Newer"), h("small", "gt-row-sub", traceLabel(data.a, now)));
    newer.append(swatch(false), t1);
    const older = h("label", "gt-row");
    const t2 = h("span", "gt-grow");
    t2.append(h("span", "gt-row-name", "Older"), h("small", "gt-row-sub", traceLabel(data.b, now)));
    const check = h("input");
    check.type = "checkbox";
    check.checked = showOld;
    check.setAttribute("aria-label", "Show the older route on the globe");
    check.addEventListener("change", () => {
      showOld = check.checked;
      drawGlobe();
    });
    older.append(swatch(true), t2, check);
    legend.replaceChildren(h("div", "gt-label", "On the globe"), newer, older);
  }

  function drawTable() {
    const rows = compareRows(data.rows);
    split.textContent = splitSentence(data.split_after, rows);
    const t = h("table", "gt-cmp");
    const head = h("tr");
    head.append(h("th", "", "#"), h("th", "", "Older"), h("th", "", "Newer"));
    t.append(head);
    for (const r of rows) {
      const tr = h("tr", r.className);
      tr.append(h("td", "", String(r.n)), h("td", "", cellText(r.b)), h("td", "", cellText(r.a)));
      t.append(tr);
    }
    table.replaceChildren(t);
  }

  function clearView() {
    legend.replaceChildren();
    split.textContent = "";
    table.replaceChildren();
    newTrace = null;
    oldTrace = null;
    drawGlobe();
  }

  async function load() {
    const mine = ++seq;
    say("");
    const q = [];
    if (wantA !== null) q.push(`a=${wantA}`);
    if (wantB !== null) q.push(`b=${wantB}`);
    let next;
    try {
      next = await api.gtGet(`/targets/${targetId}/compare${q.length ? `?${q.join("&")}` : ""}`);
    } catch (e) {
      if (gone || mine !== seq) return;
      clearView();
      data = null;
      say(/not enough/i.test(e.message || "") ? TOO_FEW : e.message || "Could not compare.");
      return;
    }
    if (gone || mine !== seq) return;
    data = next;
    wantA = data.a.id;
    wantB = data.b.id;
    fillPicker(pickA, wantA);
    fillPicker(pickB, wantB);
    drawLegend();
    drawTable();
    const [fullNew, fullOld] = await Promise.all(
      [data.a.id, data.b.id].map((id) => api.gtGet(`/traces/${id}`).catch(() => null)),
    );
    if (gone || mine !== seq) return;
    newTrace = fullNew; // a failed fetch leaves nothing of the previous pick on the globe
    oldTrace = fullOld;
    drawGlobe();
  }

  async function loadHistory() {
    try {
      const rows = await api.gtGet(`/targets/${targetId}/traces?limit=50`);
      if (gone) return;
      history = (Array.isArray(rows) ? rows : []).filter((t) => t.status === "done");
    } catch (e) {
      if (gone) return;
      history = [];
    }
    if (data) {
      fillPicker(pickA, wantA);
      fillPicker(pickB, wantB);
    }
  }

  const startedOf = (id) => (history.find((t) => t.id === id) || {}).started_ms;

  function picked(a, b) {
    following = false;
    wantA = a;
    wantB = b;
    const sa = startedOf(a);
    const sb = startedOf(b);
    const swap = sa !== undefined && sb !== undefined && sa < sb;
    if (swap) [wantA, wantB] = [b, a];
    note.textContent = swap ? "Swapped so Newer is the more recent trace." : "";
    note.hidden = !swap;
    load();
  }

  pickA.addEventListener("change", () => picked(Number(pickA.value), wantB));
  pickB.addEventListener("change", () => picked(wantA, Number(pickB.value)));

  const heading = () => ctx.setTitle(name(), "Compare traces");
  heading();
  {
    const t = findTarget(ctx.snapshot());
    lastSeen = t && t.last ? t.last.trace_id : null;
  }
  globeControl.setFocus(COMPARE_KEYS);
  loadHistory().then(load);

  return {
    update(snapshot) {
      const next = findTarget(snapshot);
      if (!next) {
        if (Array.isArray(snapshot.targets)) ctx.close(ctx.key); // deleted elsewhere
        return;
      }
      heading();
      const last = next.last ? next.last.trace_id : null;
      if (last !== lastSeen) {
        lastSeen = last;
        if (following) {
          wantA = null;
          wantB = null;
          loadHistory().then(load);
        }
      }
    },
    destroy() {
      gone = true;
      seq += 1;
      globeControl.clear(CMP_NEW);
      globeControl.clear(CMP_OLD);
      globeControl.setFocus(null); // the Route blade's drawing shows again
    },
  };
}

shell.registerBlade("compare", { title: "Compare traces", render });
