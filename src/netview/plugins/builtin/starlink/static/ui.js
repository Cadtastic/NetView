// starlink UI: router-wide traffic tiles, the Traffic column and a traffic section in the report. Ports of LD 660-666
// and 975-999, with commas where the old dashboard had middle dots.
// Values come from state.traffic, state.traffic_totals, state.metrics (traffic.down.<ip>, traffic.up.<ip>), state.devices
// and the job status (owner "starlink", name "poll.traffic"). Everything a router or device said goes through esc()
// or textContent. The module cannot import core files, so the shared helpers arrive as `ui.util`.

const SOURCE = "starlink";
const IDLE_DOWN_BPS = 50000; // a sample counts as idle when download is below this (LD 978-982)
const MAX_IDLE_STEP_S = 30; // and the step to the previous sample is shorter than this
const TV = /\btv\b|roku|television/i;

const ACR_NOTE =
  "Smart TVs and ACR: a TV with automatic content recognition sends small fingerprints of what's on screen every few seconds, " +
  "even from an HDMI input. Look for steady upload while Download now is near zero (counted above as Uploaded while idle). " +
  "On a Roku TV, turn it off under Settings → Privacy → Smart TV experience → Use info from TV inputs.";

const footer = (ip) =>
  `Traffic figures come from the Starlink router's counters for ${ip}: they show how much it sends, not where. ` +
  "Seeing which servers it talks to (an ACR service, for example) needs the router's DNS and flow logs, which OPNsense provides after the cutover.";

/**
 * Bytes uploaded in steps where the device was barely downloading (what it starts on its own), and the seconds those
 * steps cover. Inputs are parallel arrays: times in ms, rates in bits per second (null for a missing sample).
 */
export function uploadedWhileIdle(times_ms, down_bps, up_bps) {
  let bytes = 0;
  let seconds = 0;
  for (let i = 1; i < times_ms.length; i++) {
    const down = down_bps[i];
    const up = up_bps[i];
    const dt = (times_ms[i] - times_ms[i - 1]) / 1000;
    if (down != null && up != null && down < IDLE_DOWN_BPS && dt > 0 && dt < MAX_IDLE_STEP_S) {
      bytes += (up / 8) * dt;
      seconds += dt;
    }
  }
  return { bytes, seconds };
}

/** Everything that needs the shared helpers (esc, fmtRate, fmtBytes, sparkline); all of it is pure. */
export function makeHelpers(util) {
  const { esc, fmtRate, fmtBytes, sparkline } = util;

  const list = (v) => (Array.isArray(v) ? v : []);
  const metricsOf = (state) => (state && state.metrics) || {};

  /** The poll.traffic job of this plugin, or null. */
  const trafficJob = (state) => list(state && state.jobs).find((j) => j.owner === SOURCE && j.name === "poll.traffic") || null;
  const jobOk = (state) => {
    const j = trafficJob(state);
    return !!j && j.last_ok === true;
  };
  const jobFailing = (state) => {
    const j = trafficJob(state);
    return !!j && j.last_ok === false;
  };
  /** The job's error without the exception class in front ("OSError: router API refused" becomes "router API refused"). */
  const errorText = (state) => String((trafficJob(state) || {}).last_error || "unknown error").replace(/^[A-Za-z]+(?:Error|Exception): /, "");

  const trafficFor = (state, ip) => list(state && state.traffic).find((t) => t.source === SOURCE && t.ip === ip) || null;
  const deviceFor = (state, ip) => list(state && state.devices).find((d) => d.ip === ip) || null;

  /** A rate as {v, u}, e.g. {v: "2.0", u: "Mbit/s"}. */
  function rateParts(bps) {
    const text = fmtRate(bps);
    const i = text.indexOf(" ");
    return i < 0 ? { v: text, u: "" } : { v: text.slice(0, i), u: text.slice(i + 1) };
  }
  const mbit = (bps) => {
    const v = bps / 1e6;
    return v < 1 ? v.toFixed(2) : v < 10 ? v.toFixed(1) : String(Math.round(v));
  };
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  const tileHtml = (t) =>
    t
      ? `<div class="k">${esc(t.label)}</div>` +
        `<div class="v${t.bad ? " bad" : ""}">${esc(t.value)}${t.unit ? `<small>${esc(t.unit)}</small>` : ""}</div>` +
        `<div class="s" title="${esc(t.sub)}">${esc(t.sub)}</div>`
      : "";

  /** "All Wi-Fi devices": the router's total down / up. While the job fails, the one "Router traffic" tile. Null before the first run. */
  function allTile(state) {
    if (jobFailing(state)) return { label: "Router traffic", value: "–", unit: "", bad: false, sub: `Unavailable: ${errorText(state)}` };
    if (!jobOk(state)) return null;
    const totals = list(state.traffic_totals).find((t) => t.source === SOURCE);
    if (!totals) return { label: "All Wi-Fi devices", value: "–", unit: "", bad: false, sub: "Waiting for the first reading" };
    return {
      label: "All Wi-Fi devices",
      value: `${mbit(totals.down_bps)} / ${mbit(totals.up_bps)}`,
      unit: "Mbit/s",
      bad: false,
      sub: `${plural(totals.clients, "client")}, from the Starlink router`,
    };
  }

  /** "Top uploader": the non-self device with the highest 10 minute upload average. Null unless the job is ok. */
  function topTile(state) {
    if (!jobOk(state)) return null;
    let best = null;
    for (const t of list(state.traffic)) {
      if (t.source !== SOURCE || t.up_avg_bps == null) continue;
      const d = deviceFor(state, t.ip);
      if (d && d.is_self) continue;
      if (!best || t.up_avg_bps > best.t.up_avg_bps) best = { t, d };
    }
    const label = "Top uploader (10 min average)";
    if (!best) return { label, value: "–", unit: "", bad: false, sub: "No Wi-Fi clients yet" };
    const { v, u } = rateParts(best.t.up_avg_bps);
    const name = (best.d && best.d.display_name) || (best.t.extra && best.t.extra.name) || best.t.ip;
    return { label, value: v, unit: u, bad: false, sub: name };
  }

  const upSeries = (state, ip) => list(metricsOf(state)[`traffic.up.${ip}`]);

  /** The Traffic column cell (LD 660-666). */
  function trafficCell(d, state) {
    const t = trafficFor(state, d.ip);
    if (!t) {
      return `<span class="scope">${jobOk(state) ? "not a Wi-Fi client of the router" : "router data unavailable"}</span>`;
    }
    const spark = sparkline(upSeries(state, d.ip).map((p) => p[1]), { color: "--series-2" });
    return (
      `<div class="latc" title="Download and upload right now, from the router's counters"><span class="lv">↓ ${esc(fmtRate(t.down_bps))}</span></div>` +
      `<div class="latc"><span class="lv">↑ ${esc(fmtRate(t.up_bps))}</span>${spark}</div>` +
      `<div class="scope">sent ${esc(fmtBytes(t.up_total))} since connecting</div>`
    );
  }

  /** Highest 10 minute upload average first; a device the router does not list sorts last. */
  function trafficSortKey(d, state) {
    const t = trafficFor(state, d.ip);
    return t && t.up_avg_bps != null ? -t.up_avg_bps : Infinity;
  }

  function duration(seconds) {
    const s = Math.round(seconds);
    if (s < 60) return `${s} s`;
    if (s < 3600) return `${Math.round(s / 60)} min`;
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    if (s < 86400) return m ? `${h} h ${m} min` : `${h} h`;
    const days = Math.floor(s / 86400);
    const rest = Math.round((s % 86400) / 3600);
    return rest ? `${days} d ${rest} h` : `${days} d`;
  }

  /** The line under the tiles: role, access point, time connected, link rates. Parts that are missing are left out. */
  function linkLine(extra) {
    const x = extra || {};
    const parts = [];
    if (x.role || x.ap || x.assoc_s != null) {
      let s = "Connected";
      if (x.role) s += ` as a ${x.role}`;
      if (x.ap) s += ` to access point ${x.ap}`;
      if (x.assoc_s != null) s += ` for ${duration(x.assoc_s)}`;
      parts.push(`${s}.`);
    }
    const down = x.down_link != null ? `${x.down_link} Mbit/s down` : "";
    const up = x.up_link != null ? `${x.up_link} Mbit/s up` : "";
    if (down && up) parts.push(`Link rates ${down} and ${up}, as the router reports them.`);
    else if (down || up) parts.push(`Link rate ${down || up}, as the router reports it.`);
    return parts.join(" ");
  }

  /** True when the type, device name, nickname or the router's name for it says it is a TV (LD 991). */
  function isTv(device, t) {
    const text = [device && device.type, device && device.device_name, device && device.nickname, t && t.extra && t.extra.name]
      .filter(Boolean)
      .join(" ");
    return TV.test(text);
  }

  /** The traffic part of the report's live section; null when the router has no entry for the address. */
  function liveModel({ ip, device, state }) {
    const t = trafficFor(state, ip);
    if (!t) return null;
    const metrics = metricsOf(state);
    const up = list(metrics[`traffic.up.${ip}`]);
    const down = list(metrics[`traffic.down.${ip}`]);
    const downAt = new Map(down.map((p) => [p[0], p[1]]));
    const idle = uploadedWhileIdle(
      up.map((p) => p[0]),
      up.map((p) => (downAt.has(p[0]) ? downAt.get(p[0]) : null)),
      up.map((p) => p[1]),
    );
    const tile = (k, v, u = "") => ({ k, v, u: v === "–" ? "" : u });
    const rate = (k, bps) => {
      const { v, u } = rateParts(bps);
      return tile(k, v, u);
    };
    const x = t.extra || {};
    return {
      heading: "Traffic from the router",
      tiles: [
        rate("Upload now", t.up_bps),
        rate("Download now", t.down_bps),
        rate("Upload 10 min average", t.up_avg_bps),
        tile("Uploaded while idle", idle.seconds ? fmtBytes(idle.bytes) : "–", idle.seconds < 60 ? `in ${Math.round(idle.seconds)} s` : `in ${Math.round(idle.seconds / 60)} min`),
        tile("Sent since connecting", fmtBytes(t.up_total)),
        tile("Received since connecting", fmtBytes(t.down_total)),
        tile("Wi-Fi signal", x.signal_dbm != null ? String(x.signal_dbm) : "–", "dBm"),
      ],
      link: linkLine(x),
      chartTitle: `${ip}'s own traffic, from the router's counters, last 10 min`,
      series: [
        { name: "Download", color: "--series-1", points: down },
        { name: "Upload", color: "--series-2", points: up },
      ],
      acr: isTv(device, t) ? ACR_NOTE : "",
      footer: footer(ip),
    };
  }

  return {
    rateParts,
    tileHtml,
    allTile,
    topTile,
    trafficCell,
    trafficSortKey,
    linkLine,
    isTv,
    liveModel,
    errorText,
    trafficFor,
    uploadedWhileIdle,
  };
}

// ---------- DOM for the report's live section (text always goes in through textContent)

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function build(box) {
  box.textContent = "";
  const title = el("div", "k chart-title");
  title.style.fontSize = "12.5px";
  const acr = el("p", "note acr");
  acr.append(el("b", "", ""), document.createTextNode(""));
  box.append(el("h3", "", ""), el("div", "livegrid"), el("p", "note link"), title, el("div", "live-chart"), acr, el("p", "note foot"));
  box.dataset.mode = "traffic";
}

function drawLive(box, model, lineChart, fmt) {
  if (!model) {
    box.textContent = "";
    delete box.dataset.mode;
    return;
  }
  if (box.dataset.mode !== "traffic") build(box);
  box.querySelector("h3").textContent = model.heading;
  const grid = box.querySelector(".livegrid");
  grid.textContent = "";
  for (const t of model.tiles) {
    const tile = el("div", "tile");
    const v = el("div", "v", t.v);
    if (t.u) v.append(el("small", "", t.u));
    tile.append(el("div", "k", t.k), v);
    grid.append(tile);
  }
  const link = box.querySelector(".link");
  link.textContent = model.link;
  link.hidden = !model.link;
  box.querySelector(".chart-title").textContent = model.chartTitle;
  lineChart(box.querySelector(".live-chart"), { label: model.chartTitle, series: model.series, fmt });
  const acr = box.querySelector(".acr");
  acr.hidden = !model.acr;
  if (model.acr) {
    const head = "Smart TVs and ACR:";
    acr.firstChild.textContent = head;
    acr.lastChild.textContent = model.acr.slice(head.length);
  }
  box.querySelector(".foot").textContent = model.footer;
}

export default function register(ui) {
  const h = makeHelpers(ui.util);
  const { lineChart, fmtRate } = ui.util;

  ui.slot("dashboard.tile", {
    id: "all-devices",
    order: 30,
    render: (state) => h.tileHtml(h.allTile(state)),
  });
  ui.slot("dashboard.tile", {
    id: "top-uploader",
    order: 31,
    render: (state) => h.tileHtml(h.topTile(state)),
  });

  ui.slot("devices.column", {
    id: "traffic",
    label: "Traffic",
    sub: "(from router)",
    render: (d, state) => h.trafficCell(d, state),
    sortKey: (d, state) => h.trafficSortKey(d, state),
  });

  ui.slot("report.live-section", {
    id: "traffic",
    draw(box, { ip, device, state }) {
      drawLive(box, h.liveModel({ ip, device, state }), lineChart, fmtRate);
    },
  });
}
