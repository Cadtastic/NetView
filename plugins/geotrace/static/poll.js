// A polite poller: one request at a time, nothing fetched while the page is hidden. Pure apart from the timers
// (injectable, so it is unit-tested with a hand-run clock).

/**
 * createPoller(fetchFn, {intervalMs, isVisible}) -> {start(), stop(), now()}.
 * start() runs fetchFn every intervalMs, counted from the end of the previous run, so runs never overlap.
 * now() runs it straight away; if a run is already going it returns that run instead of starting another.
 * While isVisible() is false nothing is fetched. A fetchFn that throws is ignored (the next tick tries again).
 */
export function createPoller(fetchFn, { intervalMs, isVisible = () => true, setTimer = globalThis.setTimeout, clearTimer = globalThis.clearTimeout }) {
  let timer = null;
  let running = false;
  let inflight = null;

  function run() {
    if (inflight) return inflight;
    if (!isVisible()) return Promise.resolve();
    inflight = (async () => {
      try {
        await fetchFn();
      } catch (e) {
        // the next tick tries again
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  function schedule() {
    if (!running) return;
    if (timer !== null) clearTimer(timer);
    timer = setTimer(async () => {
      timer = null;
      await run();
      schedule();
    }, intervalMs);
  }

  return {
    start() {
      if (running) return;
      running = true;
      schedule();
    },
    stop() {
      running = false;
      if (timer !== null) clearTimer(timer);
      timer = null;
    },
    now: run,
  };
}
