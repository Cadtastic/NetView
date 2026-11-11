// Pure helpers for the GS105E faceplate. No imports, so `node --test` can load this file on its own.
// Geometry comes from the header comment of faceplate.svg (viewBox 0 0 940 270); keep the two in step.

export const FACE_W = 940;
export const FACE_H = 270;
export const JACK_X = [200, 340, 480, 620, 784];
export const JACK_Y = 104;
export const JACK_W = 130;
export const JACK_H = 118;
export const POWER_LED = [30, 192, 26, 16];
// Per-jack LEDs, relative to the jack: x offset, y offset, width, height.
const LED_LEFT = [8, 6, 26, 12];
const LED_RIGHT = [96, 6, 26, 12];

// One colour per VLAN, in VLAN-id order. No green, red or amber: those mean link state.
const VLAN_PALETTE = ["#94a3b8", "#a855f7", "#22b8cf", "#f472b6", "#60a5fa", "#c8a27a", "#818cf8", "#e2e8f0"];

const pct = (v, of) => Math.round((v / of) * 100000) / 1000;
const box = (x, y, w, h) => ({ left: pct(x, FACE_W), top: pct(y, FACE_H), width: pct(w, FACE_W), height: pct(h, FACE_H) });
const boxStyle = (b) => `left:${b.left}%;top:${b.top}%;width:${b.width}%;height:${b.height}%`;

const validPort = (n) => Number.isInteger(n) && n >= 1 && n <= JACK_X.length;

/** Where jack `n` (1 to 5) sits on faceplate.svg, as percentages of the image; null off the face. */
export function jackBox(n) {
  if (!validPort(n)) return null;
  return box(JACK_X[n - 1], JACK_Y, JACK_W, JACK_H);
}

/** The Power LED's box, in percent. */
export function powerLedBox() {
  return box(...POWER_LED);
}

/** Which jack LEDs a link speed lights: both = 1000M, left = 100M, right = 10M, none when there is no link. */
export function ledState(linkMbps) {
  return {
    left: linkMbps === 1000 || linkMbps === 100,
    right: linkMbps === 1000 || linkMbps === 10,
  };
}

/** Where the two LEDs of jack `n` sit on faceplate.svg, in percent; null off the face. */
export function ledBoxes(n) {
  if (!validPort(n)) return null;
  const x = JACK_X[n - 1];
  const at = (led) => box(x + led[0], JACK_Y + led[1], led[2], led[3]);
  return { left: at(LED_LEFT), right: at(LED_RIGHT) };
}

/** Short speed label: 1G, 100M, 10M, or a dash when the speed is unknown. */
export function speedShort(mbps) {
  if (mbps == null || !(mbps > 0)) return "—";
  return mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`;
}

/** The one state a port is shown in. Administratively disabled wins over down. */
export function portState(port) {
  if (/^disable/i.test(String(port.speed_setting || ""))) return { cls: "disabled", words: "admin disabled" };
  if (!port.up) return { cls: "down", words: "link down" };
  return { cls: "up", words: "link up" };
}

/** Map of VLAN id to colour, assigned in VLAN-id order; the palette repeats after eight. */
export function vlanColors(vids) {
  const sorted = [...new Set((vids || []).filter((v) => v != null))].sort((a, b) => a - b);
  return new Map(sorted.map((vid, i) => [vid, VLAN_PALETTE[i % VLAN_PALETTE.length]]));
}

const MIRROR_WORDS = { source: "mirror source", destination: "mirror destination" };
const MIRROR_BADGE = { source: "⇄ src", destination: "⇄ dst" };

function membershipWords(code) {
  if (code === "U") return "untagged in the shown VLAN";
  if (code === "T") return "tagged in the shown VLAN";
  if (code === "" || code == null) return "";
  return "membership unknown";
}

function portWords(port, shownVid) {
  const st = portState(port);
  const parts = [`Port ${port.port}: ${st.words}`];
  if (port.up && port.link_mbps) parts.push(speedShort(port.link_mbps));
  if (port.description) parts.push(port.description);
  if (port.pvid != null) parts.push(`PVID ${port.pvid}`);
  const member = membershipWords(port.vlan_member);
  if (member) parts.push(shownVid != null ? member.replace("the shown VLAN", `VLAN ${shownVid}`) : member);
  if (MIRROR_WORDS[port.mirror]) parts.push(MIRROR_WORDS[port.mirror]);
  return parts;
}

/**
 * HTML of one front-panel jack, laid over faceplate.svg: a button on the jack plus the two speed LEDs.
 * `mode` is "status" or "vlan"; `colors` is the map from vlanColors; `shownVid` names the VLAN that
 * `vlan_member` refers to. Returns "" for a port that is not on the face.
 */
export function jackHtml(port, esc, mode, colors, shownVid = null) {
  const at = jackBox(port.port);
  const leds = ledBoxes(port.port);
  if (!at || !leds) return "";
  const st = portState(port);
  const title = esc(portWords(port, shownVid).join(", "));
  let cls;
  let inner;
  let extra = "";
  if (mode === "vlan") {
    cls = `vlan ${st.cls}`;
    const color = colors && port.pvid != null ? colors.get(port.pvid) : null;
    if (color) extra = `;--vc:${color}`;
    inner =
      `<span class="g5e-jv">${port.pvid == null ? "—" : esc(port.pvid)}</span>` +
      (port.vlan_member === "T" ? `<span class="g5e-jt">T</span>` : "");
  } else {
    cls = st.cls;
    const util = port.up && port.util_percent != null ? Math.max(0, Math.min(100, Math.round(port.util_percent))) : 0;
    inner =
      `<span class="g5e-js">${esc(port.up ? speedShort(port.link_mbps) : st.cls === "disabled" ? "⦸" : "—")}</span>` +
      (MIRROR_BADGE[port.mirror] ? `<span class="g5e-jm">${MIRROR_BADGE[port.mirror]}</span>` : "") +
      (port.up ? `<span class="g5e-util" style="--u:${util}%"></span>` : "");
  }
  const state = ledState(port.up ? port.link_mbps : null);
  const led = (b, on) => `<span class="g5e-led${on ? " on" : ""}" style="${boxStyle(b)}" aria-hidden="true"></span>`;
  return (
    `<button type="button" class="g5e-jack ${cls}" data-port="${esc(port.port)}" style="${boxStyle(at)}${extra}" title="${title}" aria-label="${title}">${inner}</button>` +
    led(leds.left, state.left) +
    led(leds.right, state.right)
  );
}

/** Inline style that puts the Power LED dot over faceplate.svg. */
export function powerDotStyle() {
  return boxStyle(powerLedBox());
}

/** Chart series for a port's samples: In then Out, as `[t_ms, bps]` points (a missing rate stays null). */
export function portChartSeries(samples) {
  const rows = samples || [];
  return [
    { name: "In", color: "--series-1", points: rows.map((s) => [s.t_ms, s.in_bps]) },
    { name: "Out", color: "--series-2", points: rows.map((s) => [s.t_ms, s.out_bps]) },
  ];
}
