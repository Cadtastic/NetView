// Pure model for the Trends blade (unit-tested): the range chips and the remembered range.
export const RANGE_KEY = "netview.geotrace.trendsRange";
export const DEFAULT_RANGE = "24h";
export const RANGES = [
  { key: "24h", label: "24 h", words: "24 hours" },
  { key: "7d", label: "7 d", words: "7 days" },
  { key: "30d", label: "30 d", words: "30 days" },
  { key: "90d", label: "90 d", words: "90 days" },
];

export function normalizeRange(value) {
  return RANGES.some((r) => r.key === value) ? value : DEFAULT_RANGE;
}

export function rangeSubtitle(key) {
  const r = RANGES.find((x) => x.key === key) || RANGES[0];
  return `last ${r.words}`;
}

export function loadRange(storage) {
  try {
    return normalizeRange((storage ?? globalThis.localStorage).getItem(RANGE_KEY));
  } catch (e) {
    return DEFAULT_RANGE;
  }
}

export function saveRange(key, storage) {
  try {
    (storage ?? globalThis.localStorage).setItem(RANGE_KEY, normalizeRange(key));
  } catch (e) {
    // blocked storage: the range just isn't remembered
  }
}

/**
 * Route-change times moved onto the start of their bucket. The chart's series points are bucket starts, so a change in the
 * last bucket would otherwise fall after the chart's last point and get no marker. Changes before the first bucket are dropped.
 */
export function snapChanges(changes, points) {
  const times = (Array.isArray(points) ? points : []).map((p) => p[0]).filter(Number.isFinite);
  if (times.length < 2 || !Array.isArray(changes)) return [];
  const t0 = times[0];
  const last = times[times.length - 1];
  const width = times[1] - t0;
  if (!(width > 0)) return [];
  const out = changes
    .filter((m) => Number.isFinite(m) && m >= t0)
    .map((m) => Math.min(last, t0 + Math.floor((m - t0) / width) * width));
  return [...new Set(out)];
}
