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
