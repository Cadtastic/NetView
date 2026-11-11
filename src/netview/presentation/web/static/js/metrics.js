// Client-side metrics cache: series name -> [[t_ms, value|null], ...], fed by GET /api/v1/metrics.

const LONG_LIMIT = 720; // 1 h at 5 s
const SHORT_LIMIT = 120; // 10 min at 5 s
/**
 * How far behind the newest sample a fetch starts. Producers stamp a sample before they append it, and a write
 * lock or a long batch can delay the append, so a point can reach the server later than a newer point from another
 * series. Asking for this much overlap picks those up; mergeMetrics drops the points already cached.
 */
export const OVERLAP_MS = 30000;
const LONG_PREFIXES = ["health.gateway", "health.internet", "health.dns.", "local."];

/** How many samples a series keeps: the long series from the contract, 120 for everything else. */
export function limitFor(name) {
  return LONG_PREFIXES.some((p) => String(name).startsWith(p)) ? LONG_LIMIT : SHORT_LIMIT;
}

/** The newest sample time in the cache (0 when empty). */
export function newestTime(cache) {
  let newest = 0;
  for (const points of Object.values(cache)) {
    if (points.length) newest = Math.max(newest, points[points.length - 1][0]);
  }
  return newest;
}

/**
 * Add a delta (name -> points) to the cache in place and return the cache.
 * A point at or before the series' last cached time is dropped, so overlapping fetches add no duplicates.
 * Each series is trimmed to its limit.
 */
export function mergeMetrics(cache, delta) {
  for (const [name, points] of Object.entries(delta || {})) {
    if (!Array.isArray(points)) continue;
    const have = cache[name] || (cache[name] = []);
    let last = have.length ? have[have.length - 1][0] : -Infinity;
    for (const p of points) {
      if (!Array.isArray(p) || !(p[0] > last)) continue;
      have.push([p[0], p[1] ?? null]);
      last = p[0];
    }
    const limit = limitFor(name);
    if (have.length > limit) have.splice(0, have.length - limit);
    if (!have.length) delete cache[name];
  }
  return cache;
}

/**
 * A metrics client over `apiGet`. refresh() fetches from OVERLAP_MS before the newest sample seen and merges it,
 * so a sample appended late is not missed and one fetched twice is not added twice.
 * A failed fetch throws and leaves the cache as it was.
 */
export function createMetricsClient(apiGet) {
  const cache = {};
  return {
    cache,
    async refresh() {
      const since = Math.max(0, newestTime(cache) - OVERLAP_MS);
      const body = await apiGet(`/api/v1/metrics?since_ms=${since}`);
      mergeMetrics(cache, body && body.series);
      return cache;
    },
  };
}
