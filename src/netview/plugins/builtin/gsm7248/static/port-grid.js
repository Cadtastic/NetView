// Pure helpers for the GSM7248 faceplate. No imports, so `node --test` can load this file on its own.

const ETH_NAME = /^0\/(\d+)$/;
const FACE_PORTS = 48;

/** Short speed label: 1G, 100M, 10M, or a dash when the speed is unknown. */
export function speedShort(mbps) {
  if (mbps == null || !(mbps > 0)) return "—";
  return mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`;
}

/** Number used to sort port names: slot * 1000 + port ("0/2" is 2, "1/1" is 1001). Unknown names sort last. */
export function portSortKey(name) {
  const m = /^(\d+)\/(\d+)$/.exec(String(name ?? ""));
  return m ? Number(m[1]) * 1000 + Number(m[2]) : Infinity;
}

/** Compact list of port names: runs in one slot become "0/1–0/24"; other names are kept as they are. */
export function portRanges(names) {
  const known = [];
  const other = [];
  for (const name of names || []) {
    const m = /^(\d+)\/(\d+)$/.exec(String(name ?? ""));
    if (m) known.push({ slot: m[1], n: Number(m[2]), name: String(name) });
    else other.push(String(name));
  }
  known.sort((a, b) => portSortKey(a.name) - portSortKey(b.name));
  const out = [];
  let run = [];
  const flush = () => {
    if (run.length > 2) out.push(`${run[0].name}–${run[run.length - 1].name}`);
    else out.push(...run.map((r) => r.name));
    run = [];
  };
  for (const k of known) {
    const last = run[run.length - 1];
    if (last && (last.slot !== k.slot || k.n !== last.n + 1)) flush();
    run.push(k);
  }
  flush();
  return [...out, ...other].join(", ");
}

/** Odd Ethernet ports on the top row, even on the bottom; combo, LAG and other interfaces go to `extra`. */
export function faceplateLayout(ports) {
  const top = [];
  const bottom = [];
  const extra = [];
  for (const p of [...ports].sort((a, b) => portSortKey(a.name) - portSortKey(b.name))) {
    const m = ETH_NAME.exec(p.name);
    const n = m ? Number(m[1]) : 0;
    if (p.kind === "ethernet" && n >= 1 && n <= FACE_PORTS) (n % 2 ? top : bottom).push(p);
    else extra.push(p);
  }
  return { top, bottom, extra };
}

/** The one state a port is shown in. Admin-disabled wins over down, down over blocking. */
export function portState(port) {
  if (!port.admin_up) return { cls: "disabled", symbol: "⦸", words: "admin disabled" };
  if (!port.oper_up) return { cls: "down", symbol: "▼", words: "link down" };
  if (port.stp_state === "blocking") return { cls: "blocking", symbol: "⏸", words: "link up, STP blocking" };
  return { cls: "up", symbol: "▲", words: "link up" };
}

/** Full-sentence description of a port, used for the cell's title and accessible name. */
export function portTitle(port, esc) {
  const st = portState(port);
  const parts = [`${port.name}: ${st.words}`];
  if (port.oper_up && port.speed_mbps) parts.push(`${speedShort(port.speed_mbps)} ${port.duplex || ""}`.trim());
  if (port.uplink) parts.push("uplink");
  if (port.lag) parts.push(`in ${port.lag}`);
  if (port.alias) parts.push(port.alias);
  const n = (port.devices || []).length;
  if (n) parts.push(`${n} device${n === 1 ? "" : "s"}`);
  return esc(parts.join(", "));
}

/** HTML of one port cell (a button). `esc` is the core's HTML escaper. */
export function portCellHtml(port, esc) {
  const st = portState(port);
  const util = port.rates && port.rates.util_percent != null ? Math.max(0, Math.min(100, Math.round(port.rates.util_percent))) : 0;
  const label = ETH_NAME.test(port.name) ? port.name.slice(2) : port.name;
  const title = portTitle(port, esc);
  const cls = `port ${st.cls}${port.uplink ? " uplink" : ""}`;
  return (
    `<button type="button" class="${cls}" data-port="${esc(port.name)}" title="${title}" aria-label="${title}">` +
    `<span class="pn">${esc(label)}</span>` +
    `<span class="ps">${esc(port.oper_up ? speedShort(port.speed_mbps) : "—")}</span>` +
    `<span class="pi" aria-hidden="true">${st.symbol}</span>` +
    `<span class="util" style="--u:${util}%"></span>` +
    `</button>`
  );
}

/** Uptime in seconds as "3d 4h", "5h 12m" or "7m". */
export function fmtUptime(seconds) {
  if (seconds == null) return "–";
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}
