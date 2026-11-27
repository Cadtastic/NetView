// Pure helpers for the GeoTrace settings sections: status answers to text, and coordinate checks (tested).
import { COPY } from "./banners.js";

/** {month, checked, error} lines about the DB-IP files from a /status answer. `fmt` turns epoch milliseconds into text. */
export function geoStatusText(status, fmt = (ms) => new Date(ms).toLocaleString()) {
  const geo = (status && status.geo) || {};
  const parts = [];
  if (geo.city && geo.city.month) parts.push(`City ${geo.city.month}`);
  if (geo.asn && geo.asn.month) parts.push(`ASN ${geo.asn.month}`);
  return {
    month: parts.length ? parts.join(", ") : "Not downloaded yet",
    checked: typeof geo.checked_ms === "number" ? `Last checked ${fmt(geo.checked_ms)}` : "Not checked yet",
    error: geo.last_error ? `Last error: ${geo.last_error}` : null,
  };
}

/** One line for the state of the globe files (same wording as the page notices where there is one). */
export function bundleStatusText(status) {
  const bundle = status && status.bundle;
  if (!bundle) return "Checking…";
  switch (bundle.state) {
    case "not_published":
      return COPY.bundleNotPublished;
    case "missing":
    case "downloading":
      return COPY.bundleLoading;
    case "ready":
      return "Ready";
    case "failed":
      return bundle.error ? `Download failed: ${bundle.error}` : "Download failed";
    default:
      return String(bundle.state || "Unknown");
  }
}

/** "Download now" is offered only when there is something to download and nothing running. */
export function canDownloadBundle(status) {
  const state = status && status.bundle && status.bundle.state;
  return state === "missing" || state === "failed";
}

function inRange(text, limit) {
  if (typeof text !== "string" || text.trim() === "") return false;
  const n = Number(text);
  return Number.isFinite(n) && Math.abs(n) <= limit;
}

/** True when both texts are numbers: latitude within 90, longitude within 180. */
export function hasCoordinates(lat, lon) {
  return inRange(lat, 90) && inRange(lon, 180);
}

/** A globe pick as the text for the two inputs (5 places is about a metre). */
export function pickedHome(lat, lon) {
  return { lat: lat.toFixed(5), lon: lon.toFixed(5) };
}
