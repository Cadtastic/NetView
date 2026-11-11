// Shared TV list for the Roku slots: one fetch, many readers. While no TV is known it re-checks so the Roku tab
// lights up once a scan (or a saved list) turns something up: every 3 s while a scan is running, or while no scan
// has finished yet and the store is under 60 s old (the startup scan begins ~5 s after NetView starts); otherwise
// every 30 s.
export const EMPTY_TOOLTIP = "No Roku TVs found yet. Click to open Roku settings and scan.";
const RETRY_MS = 30000;
const FAST_RETRY_MS = 3000;
const STARTUP_WINDOW_MS = 60000;

export function createStore(ui, { now = Date.now, setTimer = setTimeout } = {}) {
  const created = now();
  let data = null;
  let waiting = false;
  const subscribers = new Set();

  const unavailable = () => (data && data.tvs.length === 0 ? EMPTY_TOOLTIP : null);

  function retryDelay() {
    const scan = (data && data.scan) || {};
    const pending = scan.finished_ms == null && now() - created < STARTUP_WINDOW_MS;
    return scan.running || pending ? FAST_RETRY_MS : RETRY_MS;
  }

  function scheduleRetry() {
    if (waiting) return;
    waiting = true;
    setTimer(() => {
      waiting = false;
      return load();
    }, retryDelay());
  }

  async function load() {
    const before = unavailable();
    try {
      const r = await ui.apiGet(`${ui.apiBase}/tvs`);
      data = { tvs: Array.isArray(r && r.tvs) ? r.tvs : [], scan: (r && r.scan) || {}, loaded_ms: now() };
    } catch (e) {
      // keep the last good list on screen
    }
    if (unavailable() !== before) ui.requestRender();
    for (const fn of [...subscribers]) fn();
    if (!data || data.tvs.length === 0) scheduleRetry();
  }

  return {
    get: () => data,
    load,
    unavailable,
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}
