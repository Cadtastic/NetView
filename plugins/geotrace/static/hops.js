// The hop list shared by the Route and Trace once blades. Everything the server sent goes through textContent.
import { fmtRtt } from "./targets.js";

const ASSUMED_NOTE = "placed at the ground station";
const IMPLAUSIBLE_NOTE = "location from the database doesn't fit the response time";

export const placed = (hop) => hop != null && Number.isFinite(hop.lat) && Number.isFinite(hop.lon);

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** Mean of the replies that came back, or null when the hop was silent. */
export function hopRtt(hop) {
  const r = (hop.rtts_ms || []).filter(Number.isFinite);
  return r.length ? r.reduce((a, b) => a + b, 0) / r.length : null;
}

export function hopPlace(hop) {
  if (hop.placement === "home") return "Home";
  const place = [hop.city, hop.region].filter(Boolean).join(", ") || hop.country;
  if (place) return place;
  return hop.ip ? "Location unknown" : "No reply";
}

/** The grey line under the place: network name, address and any caution about the placement. */
export function hopDetail(hop) {
  const parts = [hop.as_org, hop.ip];
  if (hop.placement === "assumed") parts.push(ASSUMED_NOTE);
  if (hop.plausible === false) parts.push(IMPLAUSIBLE_NOTE);
  return parts.filter(Boolean).join(" · ");
}

/** Rows for a list of hops; clicking a placed hop calls onPick(hop). */
export function hopRows(hops, onPick) {
  return (hops || []).map((hop) => {
    const canFly = placed(hop);
    const row = h(canFly ? "button" : "div", "gt-row gt-hop");
    if (canFly) {
      row.type = "button";
      row.title = "Fly to this hop";
      row.addEventListener("click", () => onPick(hop));
    }
    const text = h("span", "gt-grow");
    text.append(h("span", "gt-row-name", hopPlace(hop)), h("small", "gt-row-sub", hopDetail(hop)));
    const rtt = hopRtt(hop);
    row.append(h("span", "gt-hop-n", String(hop.n)), text, h("span", rtt === null ? "gt-metric gt-dim" : "gt-metric", fmtRtt(rtt)));
    return row;
  });
}
