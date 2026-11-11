// Install jobs for the Available gallery. One installer lives for as long as the Settings dialog is open, so a job keeps
// polling (and finishes) while the user is on another tab, and a re-rendered pane shows the job still in flight.

const defaultWait = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * deps: {get(path), send(method, path, body), wait(ms), pollMs, onDone(id, name)}.
 * subscribe(fn) gets {type: "progress"|"done", id}; "progress" fires only when state, percent or error changed.
 */
export function createInstaller({ get, send, wait = defaultWait, pollMs = 300, onDone = async () => {} }) {
  const jobs = new Map(); // plugin id -> {job, state, percent, error, name}
  const queue = [];
  const listeners = new Set();
  let polling = false;
  let stopped = false;

  const emit = (event) => listeners.forEach((fn) => fn(event));
  const set = (id, next) => {
    const prev = jobs.get(id);
    jobs.set(id, next);
    if (!prev || prev.state !== next.state || prev.percent !== next.percent || prev.error !== next.error) {
      emit({ type: "progress", id });
    }
  };

  const runQueue = async () => {
    if (polling) return;
    polling = true;
    try {
      while (queue.length && !stopped) {
        const id = queue.shift();
        const mine = jobs.get(id);
        if (!mine || !mine.job) continue;
        for (;;) {
          let job;
          try {
            job = await get(`/api/v1/plugins/install/${encodeURIComponent(mine.job)}`);
          } catch (e) {
            if (stopped) return;
            set(id, { ...mine, state: "failed", percent: null, error: e.message || "Install failed" });
            break;
          }
          if (stopped) return;
          if (job.state === "done") {
            jobs.delete(id);
            await onDone(id, mine.name);
            emit({ type: "done", id });
            break;
          }
          set(id, { ...mine, state: job.state, percent: job.percent, error: job.error });
          if (job.state === "failed") break;
          await wait(pollMs);
          if (stopped) return;
        }
      }
    } finally {
      polling = false;
    }
  };

  return {
    get: (id) => jobs.get(id),
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    async install(id, name) {
      const cur = jobs.get(id);
      if (cur && cur.state !== "failed") return;
      set(id, { job: null, state: "queued", percent: null, error: null, name });
      try {
        const job = await send("POST", "/api/v1/plugins/install", { id });
        set(id, { job: job.job, state: job.state, percent: job.percent, error: job.error, name });
        queue.push(id);
        runQueue();
      } catch (e) {
        set(id, { job: null, state: "failed", percent: null, error: e.message || "Install failed", name });
      }
    },
    /** Stop polling (the dialog closed). The server finishes any running job on its own. */
    stop() {
      stopped = true;
      queue.length = 0;
      listeners.clear();
    },
  };
}
