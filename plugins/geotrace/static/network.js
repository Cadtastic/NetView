// Names for hops the database could not place, from their address alone (pure, tested).
const v4 = (ip) => {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(ip);
  return m ? m.slice(1).map(Number) : null;
};

/** "Your network" for private, loopback and link-local addresses, "Carrier network" for CGNAT, else null. */
export function networkLabel(ip) {
  if (typeof ip !== "string") return null;
  const a = v4(ip);
  if (a) {
    const [x, y] = a;
    if (x === 100 && y >= 64 && y <= 127) return "Carrier network";
    if (x === 10 || x === 127 || (x === 172 && y >= 16 && y <= 31) || (x === 192 && y === 168) || (x === 169 && y === 254)) return "Your network";
    return null;
  }
  const t = ip.toLowerCase();
  if (t === "::1") return "Your network";
  const first = parseInt(t.split(":")[0] || "0", 16);
  if (t.includes(":") && Number.isFinite(first) && ((first & 0xfe00) === 0xfc00 || (first & 0xffc0) === 0xfe80)) return "Your network";
  return null;
}
