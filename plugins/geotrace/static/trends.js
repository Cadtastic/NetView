// The Trends blade: how one target's route and response times changed over time. Blade key "trends:<id>".
import { shell } from "./shell.js";
import { lineChart } from "/static/js/chart.js";
import { RANGES, loadRange, saveRange, rangeSubtitle } from "./trends-model.js";

const NO_TARGET = "Pick a target first.";

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const CHARTS = [
  { field: "rtt", label: "Time to destination (ms)", name: "Time to destination", color: "--series-1", fmt: (v) => `${Math.round(v * 10) / 10} ms` },
  { field: "hops", label: "Hop count", name: "Hops", color: "--series-2", fmt: (v) => `${Math.round(v * 10) / 10} hops` },
  { field: "loss", label: "Packet loss (%)", name: "Packet loss", color: "--series-3", fmt: (v) => `${Math.round(v * 10) / 10}%` },
];

function render(body, ctx) {
  const targetId = Number(ctx.params[0]);
  if (ctx.params[0] === undefined || !Number.isInteger(targetId)) {
    ctx.setTitle("Trends");
    body.append(h("p", "gt-muted", NO_TARGET));
    return {};
  }
  const api = ctx.api;
  let gone = false;
  let seq = 0;
  let range = loadRange();
  let data = null;
  let lastSeen = null;

  const findTarget = (snap) => ((snap && snap.targets) || []).find((t) => t.id === targetId) || null;
  const heading = () => {
    const t = findTarget(ctx.snapshot());
    ctx.setTitle(t ? t.name : `Target ${targetId}`, rangeSubtitle(range));
  };

  const chips = h("div", "gt-toolbar");
  const chipFor = new Map();
  for (const r of RANGES) {
    const b = h("button", "gt-btn gt-range", r.label);
    b.type = "button";
    b.addEventListener("click", () => choose(r.key));
    chipFor.set(r.key, b);
    chips.append(b);
  }
  const msg = h("p", "gt-msg");
  msg.setAttribute("role", "alert");
  msg.hidden = true;
  const note = h("p", "gt-muted gt-trend-note", "Dashed lines mark route changes.");
  const boxes = CHARTS.map((c) => {
    const box = h("div", "gt-trend");
    box.dataset.chart = c.field;
    return box;
  });
  body.append(chips, msg);
  CHARTS.forEach((c, i) => body.append(h("div", "gt-label", c.label), boxes[i]));
  body.append(note);

  const say = (text) => {
    msg.textContent = text || "";
    msg.hidden = !text;
  };

  function drawChips() {
    for (const [key, b] of chipFor) {
      b.classList.toggle("gt-on", key === range);
      b.setAttribute("aria-pressed", String(key === range));
    }
  }

  function draw() {
    if (!data) return;
    CHARTS.forEach((c, i) => {
      lineChart(boxes[i], {
        label: c.label,
        series: [{ name: c.name, color: c.color, points: Array.isArray(data[c.field]) ? data[c.field] : [] }],
        fmt: c.fmt,
        height: 130,
        markers: Array.isArray(data.changes) ? data.changes : [],
      });
    });
  }

  async function load() {
    const mine = ++seq;
    say("");
    try {
      const next = await api.gtGet(`/targets/${targetId}/trends?range=${range}`);
      if (gone || mine !== seq) return;
      data = next;
      draw();
    } catch (e) {
      if (gone || mine !== seq) return;
      say(e.message || "Could not load the trends.");
    }
  }

  function choose(key) {
    if (key === range) return;
    range = key;
    saveRange(range);
    drawChips();
    heading();
    load();
  }

  drawChips();
  heading();
  const first = findTarget(ctx.snapshot());
  lastSeen = first && first.last ? first.last.trace_id : null;
  load();

  return {
    update(snapshot) {
      const t = findTarget(snapshot);
      if (!t) {
        if (Array.isArray(snapshot.targets)) ctx.close(ctx.key); // deleted elsewhere
        return;
      }
      heading();
      const last = t.last ? t.last.trace_id : null;
      if (last !== lastSeen) {
        lastSeen = last; // a new trace finished: refresh the charts
        load();
      }
    },
    destroy() {
      gone = true;
      seq += 1;
    },
  };
}

shell.registerBlade("trends", { title: "Trends", render });
