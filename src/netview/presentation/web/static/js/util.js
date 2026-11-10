// Formatting helpers, ported from the old LAN monitor's dashboard.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** HTML-escape a value (null and undefined become the empty string). */
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

/** Clock time of an epoch-millisecond timestamp. */
export const fmtTime = (ms) =>
  ms ? new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–";

/** Relative age of an epoch-millisecond timestamp ("12s ago"), or a date once it is a day old. */
export function fmtAgo(ms, now = Date.now()) {
  if (!ms) return "never";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return new Date(ms).toLocaleDateString();
}

/** Decimal byte size ("1.5 MB"). */
export function fmtBytes(n) {
  if (n == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000;
    i++;
  }
  return (n < 10 && i ? n.toFixed(1) : Math.round(n)) + " " + units[i];
}

const fmtScaled = (v) => (v < 1 ? v.toFixed(2) : v < 10 ? v.toFixed(1) : String(Math.round(v)));

/** Bit rate given in bits per second. */
export function fmtRate(bps) {
  if (bps == null) return "–";
  if (bps < 1000) return Math.round(bps) + " bit/s";
  if (bps < 1e6) return (bps / 1e3).toFixed(1) + " kbit/s";
  if (bps < 1e9) return fmtScaled(bps / 1e6) + " Mbit/s";
  return fmtScaled(bps / 1e9) + " Gbit/s";
}
