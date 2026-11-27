// The notices at the top of the GeoTrace page, chosen from the /status answer and the target count (pure, tested).
export const COPY = {
  empty: "No targets yet. Add one to start tracing.",
  home: "Set your home location in GeoTrace settings so the first hops start at your house.",
  bundleLoading: "Preparing the globe (one-time download, about 5 MB)…",
  bundleNotPublished: "The globe files haven't been published yet. Traces still work; the map appears once they are.",
  noGeo: "Location data is still downloading. Hops are listed but not placed yet.",
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
    if (!city) out.push({ id: "geo", kind: "info", text: COPY.noGeo });
    if (status.traceroute_ok === false) out.push({ id: "traceroute", kind: "warn", text: COPY.noTraceroute });
    if (status.home_set === false) out.push({ id: "home", kind: "info", text: COPY.home });
  }
  if (targetCount === 0) out.push({ id: "empty", kind: "info", text: COPY.empty });
  return out;
}
