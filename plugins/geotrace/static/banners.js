// The notices at the top of the GeoTrace page, chosen from the /status answer and the target count (pure, tested).
export const COPY = {
  empty: "No targets yet. Add one to start tracing.",
  home: "Set your home location in GeoTrace settings so the first hops start at your house.",
  bundleLoading: "Preparing the globe (one-time download, about 5 MB)…",
  bundleNotPublished: "The globe files haven't been published yet. Traces still work; the map appears once they are.",
  noGeo: "Location data is still downloading. Hops are listed but not placed yet.",
  noGeoManual: "Location data hasn't been downloaded yet. Turn on automatic updates or use Update now in GeoTrace settings.",
  noTraceroute: "traceroute is not installed on the NetView server.",
};

/** [{id, kind: "info" | "warn", text}] for the page. `status` is null until the first answer; `targetCount` likewise. */
export function bannersFor(status, targetCount) {
  const out = [];
  if (status) {
    const bundle = status.bundle || {};
    if (bundle.state === "not_published") out.push({ id: "bundle", kind: "info", text: COPY.bundleNotPublished });
    else if (bundle.state === "downloading" || bundle.state === "missing") out.push({ id: "bundle", kind: "info", text: COPY.bundleLoading });
    else if (bundle.state === "failed") {
      const why = bundle.error ? `: ${bundle.error}` : "";
      out.push({ id: "bundle", kind: "warn", text: `The globe files could not be downloaded${why}` });
    }
    const city = status.geo && status.geo.city;
    if (!city) out.push({ id: "geo", kind: "info", text: status.geo && status.geo.auto_update === false ? COPY.noGeoManual : COPY.noGeo });
    if (status.traceroute_ok === false) out.push({ id: "traceroute", kind: "warn", text: COPY.noTraceroute });
    if (status.home_set === false) out.push({ id: "home", kind: "info", text: COPY.home });
  }
  if (targetCount === 0) out.push({ id: "empty", kind: "info", text: COPY.empty });
  return out;
}

export const DISMISSED_KEY = "netview.geotrace.dismissed";

/** Banner texts dismissed in this browser session (sessionStorage may be blocked). */
export function loadDismissed(storage) {
  try {
    const raw = (storage ?? globalThis.sessionStorage).getItem(DISMISSED_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((x) => typeof x === "string") : []);
  } catch (e) {
    return new Set();
  }
}

export function saveDismissed(set, storage) {
  try {
    (storage ?? globalThis.sessionStorage).setItem(DISMISSED_KEY, JSON.stringify([...set]));
  } catch (e) {
    // blocked storage: the banner just comes back next time
  }
}

/** The banners that are not dismissed. A dismissal is tied to the text, so a banner whose text changes shows again. */
export function visibleBanners(list, dismissed) {
  return list.filter((b) => !dismissed.has(b.text));
}
