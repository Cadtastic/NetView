// The device report's "NETGEAR GS105E" section: a pure model (reportModel) and the DOM drawing (drawReport).

const DASH = "–";

/**
 * Model of the section, or null unless the report is for the switch itself (`ip` equals `summary.host`).
 * `link` is the plugin's own page, as a hash route the shell understands.
 */
export function reportModel(summary, ip, fmtRate = (v) => `${v} bit/s`) {
  if (!summary || !summary.host || ip !== summary.host) return null;
  const sw = summary.switch;
  const t = summary.throughput_bps;
  const ports = summary.ports;
  const reachable = summary.reachable === true ? "yes" : summary.reachable === false ? "no" : "unknown";
  return {
    heading: "NETGEAR GS105E",
    tiles: [
      { k: "Reachable", v: reachable },
      { k: "Login", v: String(summary.login || DASH).replace("_", " ") },
      { k: "Ports up", v: ports ? `${ports.up} of ${ports.total}` : DASH },
      { k: "Firmware", v: (sw && sw.firmware) || DASH },
      { k: "Model", v: (sw && sw.product) || DASH },
      { k: "Throughput", v: t ? `in ${fmtRate(t.in)}, out ${fmtRate(t.out)}` : DASH },
    ],
    link: "#/p/gs105e/switch",
  };
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Draw the model into `box`. All text goes in through textContent. A null model empties it. */
export function drawReport(box, model) {
  box.textContent = "";
  if (!model) return;
  const grid = el("div", "livegrid");
  for (const t of model.tiles) {
    const tile = el("div", "tile");
    tile.append(el("div", "k", t.k), el("div", "v gs-small", t.v));
    grid.append(tile);
  }
  const a = el("a", "", "Open the Switch page");
  a.href = model.link;
  box.append(el("h3", "", model.heading), grid, a);
}
