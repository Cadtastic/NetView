// Shared chart helpers: pure maths first, then the DOM line chart and the sparkline.
// Both draw inline SVG with one y-axis, hairline gridlines and series colours taken from theme tokens.
// A series colour is a CSS variable name such as "--series-1"; it is resolved when the chart is drawn.
import { esc } from "./util.js";

// ---------- pure helpers

/** Top of a four-step axis with round steps (1, 2, 2.5 or 5 times a power of ten). */
export function niceMax(v) {
  if (!(v > 0)) return 1;
  const raw = v / 4;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return 4 * (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
}

const DEFAULT_GAP_MS = 12500;

/** The time jump beyond which no line is drawn: 2.5 times the median step (12.5 s when there are fewer than 2 steps). */
export function gapMs(times) {
  const steps = [];
  for (let i = 1; i < times.length; i++) steps.push(times[i] - times[i - 1]);
  if (steps.length < 2) return DEFAULT_GAP_MS;
  steps.sort((a, b) => a - b);
  const median = steps[Math.floor(steps.length / 2)];
  return median > 0 ? 2.5 * median : DEFAULT_GAP_MS;
}

/**
 * Split [t, v] points into drawable runs. A null value, or a jump in time of more than `gap`, ends a run.
 * A run of one point cannot be drawn as a line, so it goes to `lone` and is drawn as a marker.
 */
export function segments(points, gap) {
  const runs = [];
  const lone = [];
  let cur = [];
  const flush = () => {
    if (cur.length > 1) runs.push(cur);
    else if (cur.length === 1) lone.push(cur[0]);
    cur = [];
  };
  for (const p of points) {
    if (p[1] == null) {
      flush();
      continue;
    }
    if (cur.length && p[0] - cur[cur.length - 1][0] > gap) flush();
    cur.push(p);
  }
  flush();
  return { runs, lone };
}

/** End labels sorted top to bottom, or none at all when any two would sit closer than `minGap` px (labels are never nudged). */
export function endLabels(items, minGap = 14) {
  const sorted = [...items].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) if (sorted[i].y - sorted[i - 1].y < minGap) return [];
  return sorted;
}

const round1 = (x) => Math.round(x * 10) / 10;

/** Latency summary of a series of ms values with nulls for lost replies; `loss` is a whole percent. */
export function latencyStats(values) {
  const empty = { last: null, loss: null, avg: null, min: null, max: null, jitter: null };
  if (!values || !values.length) return empty;
  const ok = values.filter((v) => v != null);
  const jumps = ok.slice(1).map((v, i) => Math.abs(v - ok[i]));
  return {
    last: values[values.length - 1],
    loss: Math.round((100 * (values.length - ok.length)) / values.length),
    avg: ok.length ? round1(ok.reduce((a, b) => a + b, 0) / ok.length) : null,
    min: ok.length ? Math.min(...ok) : null,
    max: ok.length ? Math.max(...ok) : null,
    jitter: jumps.length ? round1(jumps.reduce((a, b) => a + b, 0) / jumps.length) : null,
  };
}

// ---------- DOM helpers

const colorOf = (name) => (String(name).startsWith("--") ? `var(${name})` : String(name));

/** Build an HTML element. Text always goes in through textContent. */
function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const kid of kids) if (kid) e.append(kid);
  return e;
}

const swatch = (color, cls = "key") => {
  const i = h("i", { class: cls, "aria-hidden": "true" });
  i.style.setProperty("background", colorOf(color));
  return i;
};

const CHAR_PX = 6.3;
const TIP_GAP = 12;
const views = new WeakMap(); // chart element -> {opts, t (crosshair time), observer, width}

function timeLabel(ts, spanMs) {
  const opts = spanMs < 600000 ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" };
  return new Date(ts).toLocaleTimeString([], opts);
}

/**
 * Which time-axis labels fit a plot `iw` px wide when each label is about `labelPx` wide:
 * start, middle and end; else start and end; else only the end. Labels never overlap.
 * @returns {{t: number, anchor: string}[]}
 */
export function xTicks(t0, t1, iw, labelPx, gapPx = 12) {
  const start = { t: t0, anchor: "start" };
  const end = { t: t1, anchor: "end" };
  if (t1 <= t0) return [end];
  if (3 * labelPx + 2 * gapPx <= iw) return [start, { t: t0 + (t1 - t0) / 2, anchor: "middle" }, end];
  if (2 * labelPx + gapPx <= iw) return [start, end];
  return [end];
}

/**
 * Draw (or redraw) a line chart into `el`.
 * `series` is [{name, color, points: [[t_ms, value|null], ...]}]; `fmt(v)` returns the value with its unit.
 * Redrawing keeps an open "Data table" open and puts the crosshair back where it was.
 */
export function lineChart(el, { label, series, fmt, height = 170 }) {
  const opts = { label, series, fmt, height };
  const prior = views.get(el);
  const view = prior || { t: null, observer: null, width: 0 };
  view.opts = opts;
  views.set(el, view);

  const wasOpen = !!el.querySelector("details[open]");
  const active = document.activeElement;
  const hadFocus = !!(active && active.classList && active.classList.contains("chart-plot") && el.contains(active));

  const drawn = series.filter((s) => s.points && s.points.some((p) => p[1] != null));
  const enough = series.some((s) => s.points && s.points.length >= 2);
  el.textContent = "";
  if (!enough || !drawn.length) {
    el.append(h("p", { class: "empty", text: "Collecting samples…" }));
    return;
  }

  const W = Math.max(240, Math.round(el.clientWidth) || 600);
  const H = height;
  const times = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b);
  const gap = gapMs(times);
  const maps = series.map((s) => new Map(s.points));
  const values = drawn.flatMap((s) => s.points.map((p) => p[1])).filter((v) => v != null);
  const ymax = niceMax(Math.max(...values, 0) * 1.1);
  const top = 10;
  const bottom = 22;
  const ih = H - top - bottom;
  const y = (v) => top + ih - (v / ymax) * ih;

  const ticks = [0, 1, 2, 3, 4].map((i) => ({ v: (ymax * i) / 4, text: fmt((ymax * i) / 4) }));
  const left = Math.min(96, Math.max(40, Math.max(...ticks.map((t) => t.text.length)) * CHAR_PX + 10));
  let labels = [];
  if (series.length <= 4) {
    labels = endLabels(
      series.flatMap((s) => {
        const last = s.points[s.points.length - 1];
        return last && last[1] != null ? [{ y: y(last[1]), text: fmt(last[1]) }] : [];
      }),
    );
  }
  const right = labels.length ? Math.min(110, Math.max(...labels.map((l) => l.text.length)) * CHAR_PX + 16) : 14;
  const iw = W - left - right;
  const t0 = times[0];
  const t1 = times[times.length - 1];
  const span = Math.max(1, t1 - t0);
  const x = (ts) => left + ((ts - t0) / span) * iw;
  const f1 = (n) => n.toFixed(1);

  let g = "";
  for (const [i, tick] of ticks.entries()) {
    const yy = f1(y(tick.v));
    g += `<line class="${i === 0 ? "base" : "grid"}" x1="${left}" x2="${left + iw}" y1="${yy}" y2="${yy}"/>`;
    g += `<text class="tick" x="${left - 6}" y="${Number(yy) + 4}" text-anchor="end">${esc(tick.text)}</text>`;
  }
  const labelPx = timeLabel(t1, span).length * CHAR_PX;
  for (const { t: ts, anchor } of xTicks(t0, t1, iw, labelPx)) {
    g += `<text class="tick" x="${f1(x(ts))}" y="${H - 5}" text-anchor="${anchor}">${esc(timeLabel(ts, span))}</text>`;
  }

  let paths = "";
  let lone = "";
  for (const s of series) {
    const { runs, lone: singles } = segments(s.points, gap);
    const d = runs.map((run) => run.map((p, i) => `${i ? "L" : "M"}${f1(x(p[0]))} ${f1(y(p[1]))}`).join(" ")).join(" ");
    if (d) paths += `<path class="line" d="${d}" style="stroke:${esc(colorOf(s.color))}"/>`;
    for (const p of singles) {
      lone += `<circle class="dot" cx="${f1(x(p[0]))}" cy="${f1(y(p[1]))}" r="4" style="fill:${esc(colorOf(s.color))}"/>`;
    }
  }
  const ends = labels.map((l) => `<text class="endlabel" x="${f1(left + iw + 8)}" y="${f1(l.y + 4)}">${esc(l.text)}</text>`).join("");

  const plot = h("div", {
    class: "chart-plot",
    tabindex: "0",
    role: "img",
    "aria-label": `${label}. Use the left and right arrow keys to read values.`,
  });
  plot.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" focusable="false">${g}${paths}${lone}${ends}` +
    `<line class="xh" x1="0" x2="0" y1="${top}" y2="${top + ih}" visibility="hidden"/><g class="hd"></g>` +
    `<rect class="hit" x="${left}" y="0" width="${iw}" height="${H}"/></svg>`; // only numbers and escaped text
  const svg = plot.querySelector("svg");
  const xh = svg.querySelector(".xh");
  const hd = svg.querySelector(".hd");
  const tip = h("div", { class: "chart-tip", role: "status", "aria-live": "polite" });
  tip.hidden = true;

  const nearest = (ts) => {
    let best = 0;
    for (let i = 1; i < times.length; i++) if (Math.abs(times[i] - ts) < Math.abs(times[best] - ts)) best = i;
    return best;
  };
  const hide = () => {
    view.t = null;
    xh.setAttribute("visibility", "hidden");
    hd.textContent = "";
    tip.hidden = true;
  };
  const showAt = (i) => {
    const ts = times[i];
    view.t = ts;
    const xx = x(ts);
    xh.setAttribute("x1", f1(xx));
    xh.setAttribute("x2", f1(xx));
    xh.setAttribute("visibility", "visible");
    hd.innerHTML = series
      .map((s, k) => {
        const v = maps[k].get(ts);
        return v == null ? "" : `<circle cx="${f1(xx)}" cy="${f1(y(v))}" r="4" style="fill:${esc(colorOf(s.color))}"/>`;
      })
      .join("");
    tip.textContent = "";
    tip.append(h("div", { class: "tt", text: new Date(ts).toLocaleTimeString() }));
    series.forEach((s, k) => {
      const v = maps[k].get(ts);
      tip.append(h("div", { class: "r" }, swatch(s.color), h("b", { text: v == null ? "no data" : fmt(v) }), h("span", { text: s.name })));
    });
    tip.hidden = false;
    const scale = svg.getBoundingClientRect().width / W || 1;
    const px = xx * scale;
    const tw = tip.offsetWidth;
    let lx = plot.offsetLeft + px + TIP_GAP;
    if (px + TIP_GAP + tw > plot.clientWidth) lx = plot.offsetLeft + px - tw - TIP_GAP;
    tip.style.left = `${Math.max(0, lx)}px`;
    tip.style.top = `${plot.offsetTop + 4}px`;
  };
  const fromPointer = (evt) => {
    const r = svg.getBoundingClientRect();
    const px = ((evt.clientX - r.left) * W) / (r.width || W);
    showAt(nearest(t0 + ((px - left) / iw) * span));
  };
  plot.addEventListener("mousemove", fromPointer);
  plot.addEventListener("mouseleave", () => {
    if (document.activeElement !== plot) hide();
  });
  plot.addEventListener("touchstart", (e) => fromPointer(e.touches[0]), { passive: true });
  plot.addEventListener("touchmove", (e) => fromPointer(e.touches[0]), { passive: true });
  plot.addEventListener("touchend", hide);
  plot.addEventListener("focus", () => {
    if (view.t == null) showAt(times.length - 1);
  });
  plot.addEventListener("blur", hide);
  plot.addEventListener("keydown", (e) => {
    const cur = view.t == null ? times.length - 1 : nearest(view.t);
    let next = null;
    if (e.key === "ArrowLeft") next = Math.max(0, cur - 1);
    else if (e.key === "ArrowRight") next = Math.min(times.length - 1, cur + 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = times.length - 1;
    else if (e.key === "Escape") hide();
    if (next == null) return;
    e.preventDefault();
    showAt(next);
  });

  // Data table: the last 12 samples, newest first
  const recent = times.slice(-12).reverse();
  const head = h("tr", {}, h("th", { text: "Time" }), ...series.map((s) => h("th", { class: "num", text: s.name })));
  const rows = recent.map((ts) =>
    h(
      "tr",
      {},
      h("td", { text: new Date(ts).toLocaleTimeString() }),
      ...series.map((s, k) => h("td", { class: "num", text: maps[k].get(ts) == null ? "–" : fmt(maps[k].get(ts)) })),
    ),
  );
  const details = h(
    "details",
    { class: "chart-table" },
    h("summary", { text: "Data table" }),
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, ...rows))),
  );
  if (wasOpen) details.open = true;

  const wrap = h("div", { class: "chart" });
  if (series.length >= 2) {
    wrap.append(h("div", { class: "chart-legend" }, ...series.map((s) => h("span", {}, swatch(s.color), s.name))));
  }
  wrap.append(plot, tip, details);
  el.append(wrap);

  if (view.t != null) showAt(nearest(view.t));
  if (hadFocus) plot.focus({ preventScroll: true });

  // Redraw when the container changes width, so the text stays at its natural size.
  view.width = el.clientWidth;
  if (!view.observer && typeof ResizeObserver !== "undefined") {
    view.observer = new ResizeObserver(() => {
      if (el.isConnected && Math.abs(el.clientWidth - view.width) > 2) lineChart(el, view.opts);
    });
    view.observer.observe(el);
  }
}

/**
 * A tiny trend line as an SVG string. A missing sample is a short tick in the "bad" colour.
 * `values` are numbers or null; fewer than two values draw nothing.
 */
export function sparkline(values, { w = 72, h: height = 18, color = "--series-1" } = {}) {
  const n = values ? values.length : 0;
  if (n < 2) return "";
  const ok = values.filter((v) => v != null);
  const max = Math.max(1, ...ok);
  const sx = (i) => (i / (n - 1)) * (w - 2) + 1;
  const sy = (v) => height - 2 - (v / max) * (height - 4);
  let d = "";
  let pen = false;
  let miss = "";
  values.forEach((v, i) => {
    if (v == null) {
      pen = false;
      miss += `<line x1="${sx(i).toFixed(1)}" x2="${sx(i).toFixed(1)}" y1="${height - 4}" y2="${height}" style="stroke:var(--bad)" stroke-width="1.5"/>`;
      return;
    }
    d += `${pen ? "L" : "M"}${sx(i).toFixed(1)} ${sy(v).toFixed(1)} `;
    pen = true;
  });
  return (
    `<svg class="spark" width="${w}" height="${height}" viewBox="0 0 ${w} ${height}" aria-hidden="true" focusable="false">` +
    `<path d="${d.trim()}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" style="stroke:${esc(colorOf(color))}"/>${miss}</svg>`
  );
}
