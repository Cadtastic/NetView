// health UI: ping tiles, latency and DNS charts, a live latency column and a live section in the report.
// Values come from state.metrics (series health.*) and from this plugin's /summary.
// The module cannot import core files, so the shared helpers arrive as `ui.util` and are passed to makeHelpers.

const WINDOW_MS = 300000; // the tiles summarise the last 5 minutes
const WAITING = "Waiting for live samples…";

/** Everything that needs the shared helpers (esc, fmtMs, latencyStats, sparkline); all of it is pure. */
export function makeHelpers(util) {
  const { esc, fmtMs, latencyStats, sparkline } = util;
  const ms = (v) => `${fmtMs(v)} ms`;

  /** The sample values (ms or null) of a series that are newer than `now` minus 5 minutes. */
  const recentValues = (points, now = Date.now()) =>
    (points || []).filter((p) => p[0] > now - WINDOW_MS).map((p) => p[1]);

  /** The sub-text of a ping tile, e.g. "25% loss, average 20 ms over 5 min". */
  function latencySub(values) {
    if (!values.length) return "waiting for samples";
    const s = latencyStats(values);
    if (s.avg == null) return `${s.loss}% loss, no replies over 5 min`;
    return `${s.loss}% loss, average ${fmtMs(s.avg)} ms over 5 min`;
  }

  /** {label, value, unit, bad, sub} for a ping tile over `points`. */
  function tileModel(label, points, now) {
    const values = recentValues(points, now);
    if (!values.length) return { label, value: "–", unit: "", bad: false, sub: latencySub(values) };
    const last = values[values.length - 1];
    return last == null
      ? { label, value: "lost", unit: "", bad: true, sub: latencySub(values) }
      : { label, value: fmtMs(last), unit: "ms", bad: false, sub: latencySub(values) };
  }

  /** The DNS tile: the first server's last answer time, and the second server's in the sub-text. */
  function dnsTileModel(servers, metrics, now) {
    const [first, second] = servers;
    if (!first) return { label: "DNS", value: "–", unit: "", bad: false, sub: "no server yet" };
    const tile = tileModel(`DNS (${first})`, (metrics || {})[`health.dns.${first}`], now);
    if (!second) return { ...tile, sub: tile.value === "–" ? "waiting for samples" : "answer time" };
    const values = recentValues((metrics || {})[`health.dns.${second}`], now);
    const last = values.length ? values[values.length - 1] : undefined;
    const other = last === undefined ? "waiting for samples" : last == null ? "no answer" : ms(last);
    return { ...tile, sub: `${second}: ${other}` };
  }

  const tileHtml = (t) =>
    `<div class="k">${esc(t.label)}</div>` +
    `<div class="v${t.bad ? " bad" : ""}">${esc(t.value)}${t.unit ? `<small>${esc(t.unit)}</small>` : ""}</div>` +
    `<div class="s">${esc(t.sub)}</div>`;

  /** Series for the Latency chart. */
  function latencySeries(summary, metrics) {
    const gateway = summary && summary.gateway;
    const internet = summary && summary.internet;
    return [
      { name: gateway ? `Gateway ${gateway}` : "Gateway", color: "--series-1", points: metrics["health.gateway"] || [] },
      { name: internet ? `Internet ${internet}` : "Internet", color: "--series-2", points: metrics["health.internet"] || [] },
    ];
  }

  /** Series for the DNS chart: one per server, from the summary or, before it arrives, from the metrics. */
  function dnsSeries(summary, metrics) {
    const known = summary && Array.isArray(summary.dns) ? summary.dns : [];
    const servers = known.length
      ? known
      : Object.keys(metrics)
          .filter((n) => n.startsWith("health.dns."))
          .map((n) => n.slice("health.dns.".length));
    return servers.slice(0, 2).map((server, i) => ({
      name: server,
      color: `--series-${i + 1}`,
      points: metrics[`health.dns.${server}`] || [],
    }));
  }

  const deviceValues = (state, key) => ((state && state.metrics && state.metrics[`health.device.${key}`]) || []).map((p) => p[1]);

  /** The Latency column cell, ported from the old dashboard (LD 687-692). */
  function latencyCell(d, state) {
    const values = deviceValues(state, d.key);
    if (!values.length) {
      return `<span class="scope">${d.status === "quiet" ? "ignores ping" : d.is_self ? "–" : "waiting…"}</span>`;
    }
    const s = latencyStats(values);
    const now = s.last == null ? "no reply" : ms(s.last);
    const loss = s.loss > 0 ? `<span class="warn lossw">${esc(s.loss)}% loss</span>` : "0% loss";
    return (
      `<div class="latc"><span class="lv">${esc(now)}</span>${sparkline(values)}</div>` +
      `<div class="scope">average ${esc(fmtMs(s.avg))} ms, ${loss}</div>`
    );
  }

  /** Sort by the last value; a lost ping, no samples or no ping at all sorts last. */
  function latencySortKey(d, state) {
    const values = deviceValues(state, d.key);
    const last = values.length ? values[values.length - 1] : null;
    return last == null ? Infinity : last;
  }

  /** What the report's Live section shows for a device: tiles, a chart, or the reason there are no samples. */
  function liveModel({ ip, device, state }) {
    const model = { heading: "Live", tiles: [], chartTitle: "", series: [], message: null };
    const key = device && device.key;
    const values = key ? deviceValues(state, key) : [];
    if (!values.length) {
      model.message =
        device && device.status === "quiet"
          ? `${ip} ignores ping, so its latency can't be measured live. Its open ports below still work.`
          : device && device.is_self
            ? "This is the device running the monitor."
            : WAITING;
      return model;
    }
    const s = latencyStats(values);
    const tile = (k, v, u = "ms", bad = false) => ({ k, v, u: v === "lost" || v === "–" ? "" : u, bad });
    model.tiles = [
      s.last == null ? tile("Now", "lost", "", true) : tile("Now", fmtMs(s.last)),
      tile("Average", fmtMs(s.avg)),
      tile("Best", fmtMs(s.min)),
      tile("Worst", fmtMs(s.max)),
      tile("Jitter", fmtMs(s.jitter)),
      tile("Loss", s.loss == null ? "–" : String(s.loss), "%", s.loss > 0),
    ];
    model.chartTitle = `Latency from this device to ${ip}, last 10 min`;
    model.series = [{ name: `Ping ${ip}`, color: "--series-1", points: state.metrics[`health.device.${key}`] }];
    return model;
  }

  return { ms, recentValues, latencySub, tileModel, dnsTileModel, tileHtml, latencySeries, dnsSeries, latencyCell, latencySortKey, liveModel };
}

// ---------- DOM for the report's live section (text always goes in through textContent)

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function drawLive(box, model, lineChart, fmt) {
  const mode = model.message ? "message" : "chart";
  if (box.dataset.mode !== mode) {
    box.textContent = "";
    box.dataset.mode = mode;
    box.append(el("h3", "", model.heading));
    if (mode === "message") {
      box.append(el("p", "empty msg"));
    } else {
      const grid = el("div", "livegrid");
      const title = el("div", "k");
      title.style.fontSize = "12.5px";
      box.append(grid, title, el("div", "live-chart"));
    }
  }
  if (mode === "message") {
    box.querySelector(".msg").textContent = model.message;
    return;
  }
  const grid = box.querySelector(".livegrid");
  grid.textContent = "";
  for (const t of model.tiles) {
    const tile = el("div", "tile");
    const v = el("div", t.bad ? "v bad" : "v", t.v);
    if (t.u) v.append(el("small", "", t.u));
    tile.append(el("div", "k", t.k), v);
    grid.append(tile);
  }
  box.querySelector(".k").textContent = model.chartTitle;
  lineChart(box.querySelector(".live-chart"), { label: model.chartTitle, series: model.series, fmt });
}

export default function register(ui) {
  const h = makeHelpers(ui.util);
  const { lineChart } = ui.util;
  let summary = null;
  let loading = false;
  let lastState = null;

  function refresh() {
    if (loading) return;
    loading = true;
    ui.apiGet(`${ui.apiBase}/summary`)
      .then((s) => {
        summary = s;
      })
      .catch(() => {})
      .finally(() => {
        loading = false;
        ui.requestRender();
      });
  }
  refresh();

  // Refetch once per state update; the re-render requested above passes the same state object, so it starts no new fetch.
  function seen(state) {
    if (state !== lastState) {
      lastState = state;
      refresh();
    }
  }
  const metricsOf = (state) => (state && state.metrics) || {};

  ui.slot("dashboard.tile", {
    id: "gateway",
    order: 10,
    render(state) {
      seen(state);
      return h.tileHtml(h.tileModel("Gateway ping", metricsOf(state)["health.gateway"], Date.now()));
    },
  });
  ui.slot("dashboard.tile", {
    id: "internet",
    order: 11,
    render(state) {
      seen(state);
      const target = summary && summary.internet;
      const label = target ? `Internet ping (${target})` : "Internet ping";
      return h.tileHtml(h.tileModel(label, metricsOf(state)["health.internet"], Date.now()));
    },
  });
  ui.slot("dashboard.tile", {
    id: "dns",
    order: 12,
    render(state) {
      seen(state);
      const metrics = metricsOf(state);
      const servers = h.dnsSeries(summary, metrics).map((s) => s.name);
      return h.tileHtml(h.dnsTileModel(servers, metrics, Date.now()));
    },
  });

  ui.slot("dashboard.card", {
    id: "latency",
    title: "Latency",
    sub: "Round-trip time in ms; gaps are lost pings.",
    order: 20,
    span: "third",
    draw(box, state) {
      seen(state);
      lineChart(box, { label: "Latency", series: h.latencySeries(summary, metricsOf(state)), fmt: h.ms });
    },
  });
  ui.slot("dashboard.card", {
    id: "dns",
    title: "DNS response",
    sub: "Time to answer one lookup, in ms.",
    order: 21,
    span: "third",
    draw(box, state) {
      seen(state);
      lineChart(box, { label: "DNS response", series: h.dnsSeries(summary, metricsOf(state)), fmt: h.ms });
    },
  });

  ui.slot("devices.column", {
    id: "lat",
    label: "Latency",
    sub: "(live, 10 min)",
    render: (d, state) => h.latencyCell(d, state),
    sortKey: (d, state) => h.latencySortKey(d, state),
  });

  ui.slot("report.live-section", {
    id: "latency",
    draw(box, { ip, device, state }) {
      drawLive(box, h.liveModel({ ip, device, state }), lineChart, h.ms);
    },
  });
}
