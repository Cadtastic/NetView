// Pure column, grouping and sorting logic for the devices table (no DOM access).

const FIXED = new Set(["status", "ip", "actions"]);
const NAME_PAIR = ["nickname", "device_name"]; // one of these must stay visible
const NAME_LABEL = { nickname: "Nickname", device_name: "Device name" };
const STATUS_LABEL = { online: "Online", quiet: "Quiet", offline: "Offline" };

/** Columns to draw: hidden ones and the one used for grouping are dropped. */
export function visibleColumns(cols, hidden, groupBy) {
  return cols.filter((c) => !hidden.has(c.id) && c.id !== groupBy);
}

/** Whether a column may be hidden right now, and why not. */
export function canHide(colId, hidden) {
  if (FIXED.has(colId)) return { ok: false, reason: "always shown" };
  if (NAME_PAIR.includes(colId)) {
    const other = NAME_PAIR.find((id) => id !== colId);
    if (hidden.has(other)) return { ok: false, reason: `needed while ${NAME_LABEL[other]} is hidden` };
  }
  return { ok: true, reason: "" };
}

/** Compile the user's IP grouping pattern; an invalid one throws an Error whose message the UI shows. */
export function compileIpRegex(pattern) {
  if (pattern instanceof RegExp) return pattern;
  try {
    return new RegExp(pattern);
  } catch (e) {
    throw new Error("Not a valid regular expression: " + e.message);
  }
}

/** The group a device belongs to. `cols` is only needed for grouping by a plugin column. */
export function groupKey(device, groupBy, ipRegex, cols = []) {
  if (groupBy === "status") return STATUS_LABEL[device.status] || String(device.status ?? "");
  if (groupBy === "type") return device.type || "Unknown type";
  if (groupBy === "vendor") return device.vendor || "Unknown vendor";
  if (groupBy === "ip") {
    const m = String(device.ip ?? "").match(compileIpRegex(ipRegex));
    if (!m) return "(no match)";
    return (m[1] ?? m[0]) || "(empty match)";
  }
  const col = cols.find((c) => c.id === groupBy);
  if (col && typeof col.groupKey === "function") return String(col.groupKey(device) || "Unknown");
  return "";
}

/** IPv4 address as a number; anything else sorts last. */
export function ipNum(ip) {
  const parts = String(ip ?? "").split(".");
  if (parts.length !== 4 || parts.some((p) => !/^\d+$/.test(p))) return Infinity;
  return parts.reduce((a, b) => a * 256 + Number(b), 0);
}

function compare(a, b) {
  if (typeof a === "number" && typeof b === "number") return a < b ? -1 : a > b ? 1 : 0;
  const x = String(a ?? "").toLowerCase();
  const y = String(b ?? "").toLowerCase();
  return x < y ? -1 : x > y ? 1 : 0;
}

/** A sorted copy. A column's `sortKey(device)` wins; otherwise the IP is compared numerically. */
export function sortDevices(devices, sortKey, dir, cols) {
  const col = cols.find((c) => c.id === sortKey);
  const keyOf = col && typeof col.sortKey === "function" ? col.sortKey : (d) => ipNum(d.ip);
  return [...devices].sort((a, b) => (compare(keyOf(a), keyOf(b)) || compare(ipNum(a.ip), ipNum(b.ip))) * dir);
}
