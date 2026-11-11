// The device report's "Switch port" section: a pure model (reportModel) and the DOM drawing (drawReport).
// Port out is traffic the switch sends to the device, so it is the device's download; port in is its upload.
import { speedShort } from "./port-grid.js";

const DASH = "–";

/**
 * Model of the section, or null when the switch has not seen the device.
 * `attachment` is `{port, via}`; `detail` is /ports/{name} and `samples` /ports/{name}/samples (either may be null while loading).
 * `opts` is `{ip, mac, fmtAgo, fmtRate}`; the formatters are optional.
 */
export function reportModel(attachment, detail, samples, opts = {}) {
  if (!attachment) return null;
  const port = attachment.port;
  if (attachment.via) {
    return {
      heading: "Switch port",
      tiles: [],
      note: `Seen by the GSM7248 through uplink port ${port}; the device is on another switch or access point.`,
      series: null,
      chartTitle: "",
    };
  }
  const fmtRate = opts.fmtRate || ((v) => String(v));
  const mac = String(opts.mac || "").toLowerCase();
  // /macs and the per-port detail come from different fetches. A detail whose learned MACs do not include this
  // device predates its move onto the port, so it is treated as still loading.
  const macs = new Set(((detail && detail.devices) || []).map((d) => String(d.mac).toLowerCase()));
  if (detail && !macs.has(mac)) detail = null;
  const rate = (v) => (v == null ? DASH : fmtRate(v));
  const rates = detail && detail.rates;
  const seen = detail && (detail.mac_history || []).find((h) => String(h.mac).toLowerCase() === mac);
  const fmtAgo = opts.fmtAgo || ((ms) => new Date(ms).toLocaleString());
  let vlan = DASH;
  if (detail) {
    const v = detail.pvid != null ? detail.pvid : (detail.vlans && detail.vlans.untagged[0]);
    if (v != null) vlan = String(v);
  }
  let link = DASH;
  if (detail) link = detail.oper_up ? `${speedShort(detail.speed_mbps)} ${detail.duplex || ""}`.trim() : "link down";
  const tiles = [
    { k: "Port", v: port },
    { k: "VLAN", v: vlan },
    { k: "Link", v: link },
    { k: "Download now", v: detail ? rate(rates && rates.out_bps) : DASH },
    { k: "Upload now", v: detail ? rate(rates && rates.in_bps) : DASH },
    { k: "First seen here", v: seen ? fmtAgo(seen.first_ms) : DASH },
  ];
  const count = detail ? macs.size : 0; // distinct MACs: one MAC on two VLANs is still one device
  const model = { heading: "Switch port", tiles, note: "", series: null, chartTitle: `${opts.ip}'s traffic on switch port ${port}, last hour` };
  if (count > 1) {
    model.note = `Port ${port} is shared by ${count} devices, so its traffic is not this device's alone.`;
  } else if (count === 1 && samples) {
    model.series = [
      { name: "Download", color: "--series-1", points: samples.map((s) => [s.t_ms, s.out_bps]) },
      { name: "Upload", color: "--series-2", points: samples.map((s) => [s.t_ms, s.in_bps]) },
    ];
  }
  return model;
}

const parts = new WeakMap();

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Draw the model into `el`. All text goes in through textContent. A null model empties it. */
export function drawReport(box, model, lineChart, fmtRate) {
  if (!model) {
    box.textContent = "";
    parts.delete(box);
    return;
  }
  let p = parts.get(box);
  if (!p) {
    box.textContent = "";
    p = { h3: el("h3"), grid: el("div", "livegrid"), note: el("p", "note"), title: el("div", "k chart-title"), chart: el("div", "live-chart") };
    box.append(p.h3, p.grid, p.note, p.title, p.chart);
    parts.set(box, p);
  }
  p.h3.textContent = model.heading;
  p.grid.textContent = "";
  for (const t of model.tiles) {
    const tile = el("div", "tile");
    tile.append(el("div", "k", t.k), el("div", "v", t.v));
    p.grid.append(tile);
  }
  p.note.textContent = model.note;
  p.note.hidden = !model.note;
  p.title.hidden = p.chart.hidden = !model.series;
  if (model.series) {
    p.title.textContent = model.chartTitle;
    lineChart(p.chart, { label: model.chartTitle, series: model.series, fmt: fmtRate });
  } else {
    p.chart.textContent = "";
  }
}
