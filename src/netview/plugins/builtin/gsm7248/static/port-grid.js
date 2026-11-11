// Pure helpers for the GSM7248 faceplate. No imports, so `node --test` can load this file on its own.

const FACE_NAME = /^(?:\d+\/)?0\/(\d+)$/;
const PORT_NAME = /^((?:\d+\/)?\d+)\/(\d+)$/;
const FACE_PORTS = 48;

// Geometry of faceplate.svg, in its own units (viewBox 0 0 1930 176).
const FACE_W = 1930;
const FACE_H = 176;
const BLOCK_X = [179, 529, 879, 1229];
const JACK_W = 54;
const JACK_H = 52;
const JACK_Y = 36;
const SFP_X = [1597, 1689];
const SFP_Y = [40, 100];
const SFP_W = 64;
const SFP_H = 40;
const SFP_PAD = 3;
const CONSOLE_BOX = [1773, 40, 56, 100]; // the DB9 console port with its two screws

// One colour per VLAN, in VLAN-id order. No green, red or amber: those mean link state.
const VLAN_PALETTE = ["#94a3b8", "#a855f7", "#22b8cf", "#f472b6", "#60a5fa", "#c8a27a", "#818cf8", "#e2e8f0"];

/** Short speed label: 1G, 100M, 10M, or a dash when the speed is unknown. */
export function speedShort(mbps) {
  if (mbps == null || !(mbps > 0)) return "—";
  return mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`;
}

/**
 * Number used to sort port names. "0/2" is 2 and "1/1" is 1001 (slot * 1000 + port); the unit/slot/port form
 * the real switch reports ("1/0/2") adds unit * 1,000,000. Unknown names sort last.
 */
export function portSortKey(name) {
  const parts = String(name ?? "").split("/");
  if ((parts.length !== 2 && parts.length !== 3) || !parts.every((x) => /^\d+$/.test(x))) return Infinity;
  const [port, slot, unit = 0] = parts.map(Number).reverse();
  return unit * 1_000_000 + slot * 1000 + port;
}

/** Compact list of port names: runs in one slot become "0/1–0/24"; other names are kept as they are. */
export function portRanges(names) {
  const known = [];
  const other = [];
  for (const name of names || []) {
    const m = PORT_NAME.exec(String(name ?? ""));
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

/** The front-panel number (1 to 48) of a port named "0/N" or "U/0/N"; null for anything else. */
export function facePort(name) {
  const m = FACE_NAME.exec(String(name ?? ""));
  const n = m ? Number(m[1]) : 0;
  return n >= 1 && n <= FACE_PORTS ? n : null;
}

const CPU_NAME = /^CPU Interface:\s*(.*)$/i;

/** True for the switch's internal link to its own management processor ("CPU Interface: 1/3/1"). */
export function isCpuInterface(port) {
  return !!port && port.kind !== "ethernet" && CPU_NAME.test(String(port.name ?? ""));
}

/** The unit/slot/port of a CPU interface name ("CPU Interface:  1/3/1" gives "1/3/1"); other names unchanged. */
export function cpuSlot(name) {
  const m = CPU_NAME.exec(String(name ?? ""));
  return m ? m[1].trim() : String(name ?? "");
}

/**
 * Odd Ethernet ports on the top row, even on the bottom. CPU interfaces go to `mgmt`; LAG and any other
 * interfaces go to `extra`.
 */
export function faceplateLayout(ports) {
  const top = [];
  const bottom = [];
  const extra = [];
  const mgmt = [];
  for (const p of [...ports].sort((a, b) => portSortKey(a.name) - portSortKey(b.name))) {
    const n = p.kind === "ethernet" ? facePort(p.name) : null;
    if (n) (n % 2 ? top : bottom).push(p);
    else if (isCpuInterface(p)) mgmt.push(p);
    else extra.push(p);
  }
  return { top, bottom, extra, mgmt };
}

const pct = (v, of) => Math.round((v / of) * 100000) / 1000;
const box = (x, y, w, h) => ({ left: pct(x, FACE_W), top: pct(y, FACE_H), width: pct(w, FACE_W), height: pct(h, FACE_H) });
const boxStyle = (b) => `left:${b.left}%;top:${b.top}%;width:${b.width}%;height:${b.height}%`;

/** Where copper jack `n` sits on faceplate.svg, as percentages of the image; null off the face. */
export function jackBox(n) {
  if (!Number.isInteger(n) || n < 1 || n > FACE_PORTS) return null;
  const i = n - 1;
  const x = BLOCK_X[Math.floor(i / 12)] + 2 + JACK_W * Math.floor((i % 12) / 2);
  return box(x, JACK_Y + JACK_H * (i % 2), JACK_W, JACK_H);
}

// Every jack, SFP cage and port number on faceplate.svg (x, y, w, h), leaving the logo and the console port clear.
const PORT_AREA = [166, 12, 1604, 152];

/** Inline style that places a box over the whole port area of faceplate.svg (the Management view's cover). */
export function portAreaStyle() {
  return boxStyle(box(...PORT_AREA));
}

/** Where the SFP cage of combo port `n` (45 to 48) sits on faceplate.svg; null for other ports. */
export function sfpBox(n) {
  if (!Number.isInteger(n) || n < 45 || n > FACE_PORTS) return null;
  const i = n - 45;
  return box(SFP_X[Math.floor(i / 2)] - SFP_PAD, SFP_Y[i % 2] - SFP_PAD, SFP_W + 2 * SFP_PAD, SFP_H + 2 * SFP_PAD);
}

const CONSOLE_STATES = {
  connected: { cls: "up", symbol: "✓", words: "the switch answered" },
  silent: { cls: "quiet", symbol: "–", words: "no answer" },
  in_use: { cls: "blocking", symbol: "⏸", words: "a console session is open" },
  no_device: { cls: "disabled", symbol: "⚠", words: "serial port not found" },
  unreachable: { cls: "disabled", symbol: "⚠", words: "SSH host unreachable" },
};

/**
 * The one state the serial console is shown in, from GET /console; null when the console is turned off.
 * Like a port, every state has a symbol and words, never colour alone.
 */
export function consoleState(info) {
  if (!info || !info.enabled) return null;
  if (info.probing) return { cls: "quiet", symbol: "…", words: "probing" };
  const known = info.status && CONSOLE_STATES[info.status.state];
  return known || { cls: "quiet", symbol: "?", words: "not probed yet" };
}

/** HTML of the button laid over the console port of faceplate.svg; empty when the console is turned off. */
export function consoleButtonHtml(info, esc, expanded) {
  const st = consoleState(info);
  if (!st) return "";
  const hint = info.can_open ? "Click for details, double-click or right-click to open a terminal" : "Click for details";
  const title = esc(`Serial console: ${st.words}. ${hint}`);
  return (
    `<button type="button" class="jack console ${st.cls}" data-console style="${boxStyle(box(...CONSOLE_BOX))}" ` +
    `title="${title}" aria-label="${title}" aria-expanded="${expanded ? "true" : "false"}">` +
    `<span class="js" aria-hidden="true">${st.symbol}</span></button>`
  );
}

/**
 * How a port is shown in the VLAN view. `access` has one untagged VLAN (`vid`); `trunk` is also tagged in
 * others; `none` has no VLAN data. `members` is every VLAN the port belongs to, in order.
 */
export function vlanView(port) {
  const vl = port.vlans || {};
  const untagged = vl.untagged || [];
  const tagged = vl.tagged || [];
  const vid = port.pvid ?? untagged[0] ?? null;
  const members = [...new Set([...(vid == null ? [] : [vid]), ...untagged, ...tagged])].sort((a, b) => a - b);
  return { kind: tagged.length ? "trunk" : vid == null ? "none" : "access", vid, members };
}

/** Map of VLAN id to colour, assigned in VLAN-id order; the palette repeats after eight. */
export function vlanColors(vids) {
  const sorted = [...new Set(vids)].sort((a, b) => a - b);
  return new Map(sorted.map((vid, i) => [vid, VLAN_PALETTE[i % VLAN_PALETTE.length]]));
}

/**
 * Legend of the VLAN view: each VLAN seen on a front-panel port with its name, colour and number of access
 * ports, plus the number of trunk ports. `vlanRows` is the /vlans list, used for names.
 */
export function vlanLegend(ports, vlanRows) {
  const names = new Map((vlanRows || []).map((v) => [v.vid, v.name || ""]));
  const counts = new Map();
  let trunks = 0;
  for (const p of ports || []) {
    if (p.kind !== "ethernet" || !facePort(p.name)) continue;
    const v = vlanView(p);
    for (const vid of v.members) if (!counts.has(vid)) counts.set(vid, 0);
    if (v.kind === "trunk") trunks += 1;
    else if (v.kind === "access") counts.set(v.vid, counts.get(v.vid) + 1);
  }
  const colors = vlanColors([...counts.keys()]);
  const vlans = [...colors.keys()].map((vid) => ({ vid, name: names.get(vid) || "", count: counts.get(vid), color: colors.get(vid) }));
  return { vlans, trunks, colors };
}

/** The one state a port is shown in. Admin-disabled wins over down, down over blocking. */
export function portState(port) {
  if (!port.admin_up) return { cls: "disabled", symbol: "⦸", words: "admin disabled" };
  if (!port.oper_up) return { cls: "down", symbol: "▼", words: "link down" };
  if (port.stp_state === "blocking") return { cls: "blocking", symbol: "⏸", words: "link up, STP blocking" };
  return { cls: "up", symbol: "▲", words: "link up" };
}

function portWords(port) {
  const st = portState(port);
  const parts = [`${port.name}: ${st.words}`];
  if (port.oper_up && port.speed_mbps) parts.push(`${speedShort(port.speed_mbps)} ${port.duplex || ""}`.trim());
  if (port.uplink) parts.push("uplink");
  if (port.lag) parts.push(`in ${port.lag}`);
  if (port.alias) parts.push(port.alias);
  const n = (port.devices || []).length;
  if (n) parts.push(`${n} device${n === 1 ? "" : "s"}`);
  return parts;
}

/** Full-sentence description of a port, used for the cell's title and accessible name. */
export function portTitle(port, esc) {
  return esc(portWords(port).join(", "));
}

function vlanWords(v) {
  if (v.kind === "access") return [`VLAN ${v.vid}`];
  if (v.kind !== "trunk") return [];
  const tagged = v.members.filter((m) => m !== v.vid);
  return [`trunk${v.vid == null ? "" : `, untagged ${v.vid}`}, tagged ${tagged.join(", ")}`];
}

/**
 * HTML of one front-panel port, laid over faceplate.svg: a button on the copper jack and, for the combo
 * ports, an inert twin on the SFP cage. `mode` is "status" or "vlan"; `colors` is the map from vlanColors.
 */
export function jackHtml(port, esc, mode, colors) {
  const n = facePort(port.name);
  const at = jackBox(n);
  if (!at) return "";
  const st = portState(port);
  const v = vlanView(port);
  const title = esc([...portWords(port), ...vlanWords(v)].join(", "));
  const name = esc(port.name);
  let cls;
  let inner;
  let extra = "";
  if (mode === "vlan") {
    cls = `vlan ${v.kind}${port.oper_up ? " live" : ""}`;
    const color = v.kind === "access" && colors ? colors.get(v.vid) : null;
    if (color) extra = `;--vc:${color}`;
    inner = v.kind === "none" ? "" : `<span class="jv">${v.kind === "trunk" ? "T" : esc(v.vid)}</span>`;
  } else {
    cls = `${st.cls}${port.uplink ? " uplink" : ""}`;
    const util = port.rates && port.rates.util_percent != null ? Math.max(0, Math.min(100, Math.round(port.rates.util_percent))) : 0;
    inner =
      (st.cls === "disabled" || st.cls === "blocking" ? `<span class="js" aria-hidden="true">${st.symbol}</span>` : "") +
      (port.uplink && st.cls === "up" ? `<span class="ju" aria-hidden="true">↑</span>` : "") +
      (port.oper_up ? `<span class="util" style="--u:${util}%"></span>` : "");
  }
  const vl = ` data-vlans="${esc(v.members.join(" "))}"`;
  const cage = sfpBox(n);
  return (
    `<button type="button" class="jack ${cls}" data-port="${name}"${vl} style="${boxStyle(at)}${extra}" title="${title}" aria-label="${title}">${inner}</button>` +
    (cage ? `<span class="jack sfp ${cls}" data-port="${name}"${vl} style="${boxStyle(cage)}${extra}" title="${title}" aria-hidden="true"></span>` : "")
  );
}

/** HTML of one port cell (a button), used for interfaces that are not on the front panel. `esc` is the core's HTML escaper. */
export function portCellHtml(port, esc) {
  const st = portState(port);
  const util = port.rates && port.rates.util_percent != null ? Math.max(0, Math.min(100, Math.round(port.rates.util_percent))) : 0;
  const label = /^0\/\d+$/.test(port.name) ? port.name.slice(2) : port.name;
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

/** Chart series for a port's samples: In then Out, as `[t_ms, bps]` points (a missing rate stays null). */
export function portChartSeries(samples) {
  const rows = samples || [];
  return [
    { name: "In", color: "--series-1", points: rows.map((s) => [s.t_ms, s.in_bps]) },
    { name: "Out", color: "--series-2", points: rows.map((s) => [s.t_ms, s.out_bps]) },
  ];
}
