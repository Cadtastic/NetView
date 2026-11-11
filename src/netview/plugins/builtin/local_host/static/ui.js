// local_host UI: this device's Wi-Fi and throughput tiles, a throughput chart, the connections card and a
// connections note in the report. Values come from state.metrics (series local.*) and from this plugin's /snapshot.
// The module cannot import core files, so the shared helpers arrive as `ui.util` and are passed to makeHelpers.

const LIVE_SAMPLES = 120; // the report chart shows the last 10 min
const MAX_TRYING_PORTS = 8; // LD 996

export const TABS = [
  { id: "remotes", label: "Established" },
  { id: "trying", label: "Trying to connect" },
  { id: "listening", label: "Listening" },
];

const EMPTY = {
  remotes: "None.",
  listening: "None.",
  trying: "Nothing is stuck connecting. Open the iDRAC page in a browser and a stuck attempt shows up here.",
};

/** Everything that needs the shared helpers (esc, fmtRate); all of it is pure. */
export function makeHelpers(util) {
  const { esc, fmtRate } = util;

  /** The card sub-text (LD 864). */
  function connectionsSub(c) {
    const x = c || {};
    return `${x.total ?? 0} TCP sockets, ${x.unique_remotes ?? 0} remote hosts, ${x.lan_conns ?? 0} connections to this LAN. Refreshed every 10 s.`;
  }

  /** {label, value, unit, bad, sub} for the Wi-Fi signal tile. */
  function wifiTile(wifi) {
    const w = wifi || {};
    const parts = w.ssid ? [w.ssid, w.band, w.channel ? `channel ${w.channel}` : ""].filter(Boolean) : [];
    return {
      label: "Wi-Fi signal",
      value: w.signal_pct != null ? String(w.signal_pct) : "–",
      unit: w.signal_pct != null ? "%" : "",
      bad: false,
      sub: parts.length ? parts.join(", ") : "Not on Wi-Fi",
    };
  }

  /** A throughput tile over `points` (local.down_bps or local.up_bps); `linkKey` is the Wi-Fi link speed field. */
  function rateTile(label, points, wifi, linkKey) {
    const last = points && points.length ? points[points.length - 1][1] : null;
    const link = wifi && wifi[linkKey];
    const sub = link ? `Wi-Fi link ${link} Mbit/s` : "All adapters";
    if (last == null) return { label, value: "–", unit: "", bad: false, sub };
    const [value, unit] = fmtRate(last).split(" ");
    return { label, value, unit: unit || "", bad: false, sub };
  }

  const tileHtml = (t) =>
    `<div class="k">${esc(t.label)}</div>` +
    `<div class="v${t.bad ? " bad" : ""}">${esc(t.value)}${t.unit ? `<small>${esc(t.unit)}</small>` : ""}</div>` +
    `<div class="s">${esc(t.sub)}</div>`;

  /** The socket state chips above the tabs. */
  const chipsHtml = (states) =>
    Object.entries(states || {})
      .map(([k, v]) => `<span class="chip">${esc(k)} <b>${esc(v)}</b></span>`)
      .join("");

  /** The table (head and body rows) for a tab; every cell value comes from this device's sockets, so it is escaped. */
  function tableHtml(c, tab) {
    const x = c || {};
    if (tab === "listening") {
      const rows = x.listening || [];
      const body = rows.length
        ? rows
            .map((r) => `<tr><td class="num">${esc(r.port)}</td><td class="mono">${esc(r.addr)}</td><td>${esc(r.process)}</td></tr>`)
            .join("")
        : `<tr><td colspan="3" class="empty">${EMPTY.listening}</td></tr>`;
      return `<thead><tr><th class="num">Port</th><th>Address</th><th>Process</th></tr></thead><tbody>${body}</tbody>`;
    }
    const rows = x[tab === "trying" ? "trying" : "remotes"] || [];
    const body = rows.length
      ? rows
          .map(
            (r) =>
              `<tr><td>${esc(r.process || "–")}</td>` +
              `<td><span class="addr">${esc(r.remote)}</span>${r.name ? " " + esc(r.name) : ""} <span class="scope">${esc(r.scope)}</span></td>` +
              `<td class="num">${esc(r.port)}${r.service ? ` <span class="scope">${esc(r.service)}</span>` : ""}</td>` +
              `<td class="num">${esc(r.count)}</td></tr>`,
          )
          .join("")
      : `<tr><td colspan="4" class="empty">${tab === "trying" ? EMPTY.trying : EMPTY.remotes}</td></tr>`;
    return `<thead><tr><th>Process</th><th>Remote</th><th class="num">Port</th><th class="num">Count</th></tr></thead><tbody>${body}</tbody>`;
  }

  /** The tab an arrow, Home or End key moves to from `current`; null for any other key. */
  function nextTab(current, key) {
    const i = TABS.findIndex((t) => t.id === current);
    if (key === "ArrowRight") return TABS[(i + 1) % TABS.length].id;
    if (key === "ArrowLeft") return TABS[(i - 1 + TABS.length) % TABS.length].id;
    if (key === "Home") return TABS[0].id;
    if (key === "End") return TABS[TABS.length - 1].id;
    return null;
  }

  /** What this device's sockets say about `ip` (LD 993-997), as plain text. */
  function connectionText(ip, conns) {
    const c = conns || {};
    const open = (c.remotes || []).filter((r) => r.remote === ip);
    const trying = (c.trying || []).filter((r) => r.remote === ip);
    const bits = open.map(
      (r) => `${r.count} open connection${r.count > 1 ? "s" : ""} from ${r.process || "?"} to port ${r.port}${r.service ? ` (${r.service})` : ""}`,
    );
    if (trying.length) {
      const ports = trying.slice(0, MAX_TRYING_PORTS).map((r) => r.port).join(", ");
      bits.push(`still trying to reach port${trying.length > 1 ? "s" : ""} ${ports}${trying.length > MAX_TRYING_PORTS ? "…" : ""}`);
    }
    return bits.length ? `Between this device and ${ip}: ${bits.join("; ")}.` : `This device has no open connections to ${ip} right now.`;
  }

  /** True when the core has traffic figures for `ip` from a traffic provider. */
  const hasTraffic = (state, ip) => !!(state && Array.isArray(state.traffic) && state.traffic.some((t) => t.ip === ip));

  const THROUGHPUT_TITLE = (ip) => `This device's throughput (all its traffic, not just to ${ip})`;
  const NO_TRAFFIC_NOTE = (ip) =>
    `This device can't see ${ip}'s own traffic. After the OPNsense cutover, its Reporting and Insight pages show per-device traffic.`;

  /** Download and upload series for the throughput charts, limited to the newest `limit` samples. */
  function throughputSeries(metrics, limit) {
    const m = metrics || {};
    const last = (name) => (m[name] || []).slice(-limit);
    return [
      { name: "Download", color: "--series-1", points: last("local.down_bps") },
      { name: "Upload", color: "--series-2", points: last("local.up_bps") },
    ];
  }

  return {
    connectionsSub,
    wifiTile,
    rateTile,
    tileHtml,
    chipsHtml,
    tableHtml,
    nextTab,
    connectionText,
    hasTraffic,
    throughputSeries,
    THROUGHPUT_TITLE,
    NO_TRAFFIC_NOTE,
    TABS,
  };
}

// ---------- DOM (text always goes in through textContent or an escaped helper)

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Put `text` in the card's sub line (the card grid only sets it once, so a changing sub is updated here). */
function setSub(box, text) {
  const section = box.parentElement;
  let sub = section && section.querySelector(":scope > p.sub");
  if (!sub) {
    sub = el("p", "sub");
    if (section) section.insertBefore(sub, box.previousElementSibling || box);
    else box.prepend(sub);
  }
  sub.textContent = text;
}

export default function register(ui) {
  const h = makeHelpers(ui.util);
  const { lineChart, fmtRate } = ui.util;
  let snapshot = null;
  let loading = false;
  let lastState = null;
  let tab = "remotes";

  function refresh() {
    if (loading) return;
    loading = true;
    ui.apiGet(`${ui.apiBase}/snapshot`)
      .then((s) => {
        snapshot = s;
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
  const wifiOf = () => (snapshot && snapshot.wifi) || null;
  const connsOf = () => (snapshot && snapshot.connections) || null;

  ui.slot("dashboard.tile", {
    id: "wifi",
    order: 20,
    render(state) {
      seen(state);
      return h.tileHtml(h.wifiTile(wifiOf()));
    },
  });
  ui.slot("dashboard.tile", {
    id: "download",
    order: 21,
    render(state) {
      seen(state);
      return h.tileHtml(h.rateTile("Download (this device)", metricsOf(state)["local.down_bps"], wifiOf(), "rx_rate_mbps"));
    },
  });
  ui.slot("dashboard.tile", {
    id: "upload",
    order: 22,
    render(state) {
      seen(state);
      return h.tileHtml(h.rateTile("Upload (this device)", metricsOf(state)["local.up_bps"], wifiOf(), "tx_rate_mbps"));
    },
  });

  ui.slot("dashboard.card", {
    id: "throughput",
    title: "This device's throughput",
    sub: "All adapters.",
    order: 22,
    span: "third",
    draw(box, state) {
      seen(state);
      lineChart(box, { label: "This device's throughput", series: h.throughputSeries(metricsOf(state), Infinity), fmt: fmtRate });
    },
  });

  // The connections card keeps its tabs between redraws, so a focused tab stays focused.
  let parts = null;
  function build(box) {
    const chips = el("div", "chips");
    const tabs = el("div", "tabs");
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", "Connection types");
    const buttons = new Map();
    for (const t of h.TABS) {
      const b = el("button", "", t.label);
      b.type = "button";
      b.id = `lh-tab-${t.id}`;
      b.dataset.v = t.id;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", "lh-panel");
      buttons.set(t.id, b);
      tabs.append(b);
    }
    const table = el("table");
    const panel = el("div", "tablewrap");
    panel.id = "lh-panel";
    panel.setAttribute("role", "tabpanel");
    panel.append(table);
    tabs.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || !b.dataset.v) return;
      tab = b.dataset.v;
      drawConnections(box);
    });
    tabs.addEventListener("keydown", (e) => {
      const to = h.nextTab(tab, e.key);
      if (!to) return;
      e.preventDefault();
      tab = to;
      drawConnections(box);
      buttons.get(to).focus();
    });
    box.textContent = "";
    box.append(chips, tabs, panel);
    parts = { box, chips, buttons, panel, table };
  }

  function drawConnections(box) {
    if (!parts || parts.box !== box) build(box);
    const c = connsOf();
    setSub(box, h.connectionsSub(c));
    parts.chips.innerHTML = h.chipsHtml(c && c.states);
    for (const [id, b] of parts.buttons) {
      b.setAttribute("aria-selected", String(id === tab));
      b.tabIndex = id === tab ? 0 : -1;
      b.classList.toggle("on", id === tab);
    }
    parts.panel.setAttribute("aria-labelledby", `lh-tab-${tab}`);
    parts.table.innerHTML = h.tableHtml(c, tab);
  }

  ui.slot("dashboard.card", {
    id: "connections",
    title: "This device's connections",
    order: 40,
    span: "half",
    draw(box, state) {
      seen(state);
      drawConnections(box);
    },
  });

  ui.slot("report.live-section", {
    id: "connections",
    draw(box, { ip, state }) {
      seen(state);
      const withTraffic = h.hasTraffic(state, ip);
      const mode = withTraffic ? "traffic" : "local";
      if (box.dataset.mode !== mode) {
        box.textContent = "";
        box.dataset.mode = mode;
        box.append(el("h3", "", "This device"), el("p", "note conns"));
        if (!withTraffic) {
          box.append(el("div", "k thr-title"), el("div", "live-chart"), el("p", "note thr-note"));
        }
      }
      box.querySelector(".conns").textContent = h.connectionText(ip, connsOf());
      if (!withTraffic) {
        box.querySelector(".thr-title").textContent = h.THROUGHPUT_TITLE(ip);
        box.querySelector(".thr-note").textContent = h.NO_TRAFFIC_NOTE(ip);
        lineChart(box.querySelector(".live-chart"), {
          label: h.THROUGHPUT_TITLE(ip),
          series: h.throughputSeries(metricsOf(state), LIVE_SAMPLES),
          fmt: fmtRate,
        });
      }
    },
  });
}
